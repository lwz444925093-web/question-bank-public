"""Bounded recursive whitespace splitting of local image instances; no OCR."""
import copy
from PIL import Image
import fitz
from .visibility import inspect
from .model import area,intersect,expand,digest


def has_graphics(mask,box,components,scale):
    a,b,c,d=box
    parts=[x for x in components if x['bbox'][0]>=a and x['bbox'][1]>=b and x['bbox'][2]<=c and x['bbox'][3]<=d]
    # A long structural stroke matters even if it is one pixel wide. Tiny glyphs
    # alone do not justify making an independent diagram from a title/axis label.
    return (c-a)>=18*scale and (d-b)>=18*scale and any((x['bbox'][3]-x['bbox'][1]>=24*scale or x['bbox'][2]-x['bbox'][0]>=30*scale and x['bbox'][3]-x['bbox'][1]>=12*scale) and x['pixels']>=12*scale for x in parts)


def split_image(image,cfg):
    stats,mask=inspect(image,cfg);scale=cfg.get('raster_analysis_dpi',144)/72
    if stats['state'] in ('near_blank','invisible'):return stats,[],[]
    if not mask.getbbox():return stats,[dict(bbox=[0,0,*image.size],reason='uniform/low contrast: preserve full context',uncertain=True)],[]
    table=raster_table_probe(mask,stats)
    if table:
        stats['raster_table']=table
        return stats,[dict(bbox=table['bbox'],safe_bbox=table['bbox'],reason=table['reason'],uncertain=True,type='table')],[]
    evidence=[];budget=cfg.get('max_raster_children',8);leaves=[]
    def trim(box):
        b=mask.crop(box).getbbox()
        return [box[0]+b[0],box[1]+b[1],box[0]+b[2],box[1]+b[3]] if b else None
    def text_band(box):
        parts=[c for c in stats['components'] if c['bbox'][0]>=box[0] and c['bbox'][1]>=box[1] and c['bbox'][2]<=box[2] and c['bbox'][3]<=box[3]]
        return len(parts)>=20 and box[3]-box[1]>=15*scale and sum(c['bbox'][3]-c['bbox'][1]<=13*scale for c in parts)/max(1,len(parts))>.95 and not has_graphics(mask,box,stats['components'],scale)
    def recurse(box,depth=0):
        box=trim(box)
        if not box:return
        if depth>=cfg.get('max_split_depth',4):leaves.append(dict(bbox=box,reason='depth budget reached',uncertain=True));return
        options=[]
        for axis in (0,1):
            sub=mask.crop(box)
            if axis==0:sub=sub.transpose(Image.Transpose.TRANSPOSE)
            width,height=sub.size;raw=sub.tobytes();empty=[not any(raw[y*width:(y+1)*width]) for y in range(height)]
            j=0
            while j<height:
                if not empty[j]:j+=1;continue
                start=j
                while j<height and empty[j]:j+=1
                length=j-start;min_gap=cfg.get('split_gap_pt',11)*scale
                if start==0 or j==height or length<4*scale:continue
                cut=box[axis]+(start+j)/2
                left=list(box);right=list(box);left[axis+2]=int(cut);right[axis]=int(cut)
                left=trim(left);right=trim(right)
                if not left or not right:continue
                lg=has_graphics(mask,left,stats['components'],scale);rg=has_graphics(mask,right,stats['components'],scale)
                text_cut=axis==1 and (lg and text_band(right) or rg and text_band(left))
                if not (lg and rg and length>=min_gap or text_cut):continue
                # Broad, full-axis whitespace only. Never cut through faint pixels:
                # actual ink on the cut strip must be within threshold evidence.
                score=min(1,length/(min_gap*3))*.5+min(area(left),area(right))/max(area(left),area(right))*.3+.2
                if text_cut:score=1+area(left if text_band(left) else right)/area(box)
                options.append((score,axis,start,j,left,right,length))
        if options and len(leaves)<budget-1:
            score,axis,start,end,left,right,length=max(options,key=lambda x:x[0])
            evidence.append(dict(axis='x' if axis==0 else 'y',parent_box=box,gap=[box[axis]+start,box[axis]+end],gap_pixels=length,heuristic_score=round(min(score,1),3),reason='full whitespace gap; structural component evidence on both sides'))
            recurse(left,depth+1);recurse(right,depth+1)
        else:leaves.append(dict(bbox=box,reason='no sufficiently separated structural groups',uncertain=False))
    recurse([0,0,*mask.size])
    if len(leaves)>budget:return stats,[dict(bbox=list(mask.getbbox()),reason='child budget exceeded; unsplit context retained',uncertain=True)],evidence
    pad=cfg.get('split_padding_pt',2.5)*scale
    for leaf in leaves:
        if text_band(leaf['bbox']):leaf['type']='unknown';leaf['reason']='dense small-component text-like band; no OCR; retained separately'
        leaf['safe_bbox']=intersect(expand(leaf['bbox'],pad),[0,0,*image.size])
    return stats,leaves,evidence


def add_raster_regions(page,data,regions,cfg,source_id,page_number):
    by_id={o['id']:o for o in data['objects']};new=[];superseded={};scale=cfg['raster_analysis_dpi']/72
    for original in regions:
        images=[by_id[x] for x in original['source_objects'] if x in by_id and by_id[x]['kind']=='image']
        if not images:new.append(original);continue
        for obj in images:
            parent=copy.deepcopy(original);pid=f'p{page_number}-raster-{digest([source_id,page_number,digest(cfg),obj["id"]])[:12]}'
            parent.update(region_id=pid,type='raster_group',proposal_role='parent',children=[],image_instance=obj['image'],parent_id=None,core_bbox=obj['bbox'],safe_bbox=obj['bbox'],labels=[],text='',source_objects=[obj['id']])
            bounds=intersect(obj['bbox'],data['bounds'])
            if area(bounds)<=0:continue
            parent['safe_bbox']=bounds
            rotation=page.rotation
            try:
                page.set_rotation(0)
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=fitz.Rect(bounds),alpha=False)
            finally:page.set_rotation(rotation)
            image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            stats,leaves,evidence=split_image(image,cfg)
            parent['visibility']={k:v for k,v in stats.items() if k!='components'}
            parent['split_evidence']=evidence;parent['split_analysis']=dict(dpi=cfg['raster_analysis_dpi'],pixel_origin=[pix.x,pix.y],pixel_size=[pix.width,pix.height],coordinates='unrotated canonical page device pixels')
            parent['detection_reasons']=['original raster instance preserved; parent is not an independent figure success',stats['reason']]
            if 'small inline image/formula' in ' '.join(original['detection_reasons']):
                leaves=[];parent['warnings']=['small inline raster retained as parent only'];parent['split_status']='inline_raster'
            elif area(bounds)/area(data['bounds'])>.6 or data['classification']=='raster_dominant':
                leaves=[];parent['warnings']=['whole-page raster: full scanned-page segmentation is outside this experiment'];parent['split_status']='unsupported_page_raster'
            elif stats['state'] in ('near_blank','invisible'):
                leaves=[];parent['warnings']=[f"{stats['state']}: excluded from primary figure candidates"];parent['split_status']='filtered'
            else:parent['split_status']='auto_split' if len(leaves)>1 else 'single_or_unresolved'
            parent['automatic_split']=len(leaves)>1;parent['text_semantics_reliable']=data['text_reliability']['text_semantics_reliable']
            new.append(parent)
            for index,leaf in enumerate(leaves):
                if not leaf.get('safe_bbox'):leaf['safe_bbox']=leaf['bbox']
                def mapped(b):return [(b[0]+pix.x)/scale,(b[1]+pix.y)/scale,(b[2]+pix.x)/scale,(b[3]+pix.y)/scale]
                child=copy.deepcopy(original);cid=pid+f'-c{index+1}'
                core=mapped(leaf['bbox']);safe=mapped(leaf['safe_bbox'])
                # Keep reliable native labels from the original association, but
                # never pull corrupted outside text into a raster child.
                labels=[x for x in original['labels'] if data['text_reliability']['text_semantics_reliable'] and area(intersect(expand(safe,data['em']),x['bbox']))>0]
                if labels:
                    from .model import union
                    safe=intersect(union([safe]+[x['bbox'] for x in labels]),data['bounds'])
                child.update(region_id=cid,type=leaf.get('type','figure_candidate'),parent_id=pid,proposal_role='child',core_bbox=core,safe_bbox=safe,
                             parent_bbox=bounds,child_relative_pixel_bbox=leaf['safe_bbox'],child_relative_bbox_pt=[safe[0]-bounds[0],safe[1]-bounds[1],safe[2]-bounds[0],safe[3]-bounds[1]],
                             automatic_split=len(leaves)>1,split_evidence=evidence,split_status=parent['split_status'],visibility=parent['visibility'],labels=labels,
                             text='\n'.join(x['text'] for x in labels),source_objects=[obj['id']]+[x['object_id'] for x in labels],
                             detection_reasons=[leaf['reason'],'child coordinates mapped from fixed-DPI unrotated original PDF render'],
                             warnings=['raster text not transcribed; visual inspection required']+(['experimental/uncertain split'] if leaf['uncertain'] else []))
                if not data['text_reliability']['text_semantics_reliable']:child['warnings'].append('text semantics unreliable; no external text attachment')
                parent['children'].append(cid);new.append(child)
            superseded[original['region_id']]=parent['children']
    for obj in data['objects']:
        if obj['kind']=='text':obj['figure_refs']=[r['region_id'] for r in new if r['type']=='figure_candidate' and any(l['object_id']==obj['id'] for l in r['labels'])]
    # Remove stale native text links to now-replaced initial raster proposals.
    for r in new:
        if 'contained_by_figures' in r:r['contained_by_figures']=sorted({v for oid in r['source_objects'] for v in by_id.get(oid,{}).get('figure_refs',[])})
    new.sort(key=lambda r:(round(r['core_bbox'][1],1),r['core_bbox'][0],r['proposal_role']=='child'))
    for i,r in enumerate(new):
        r['reading_order_hint']=i+1;r['text_semantics_reliable']=data['text_reliability']['text_semantics_reliable']
        source_types=sorted({by_id[x]['kind'] for x in r['source_objects'] if x in by_id});r['source_types']=source_types
        # Explain every additive heuristic term; score is not a probability.
        breakdown={'structural_source':.45,'bounded_geometry':.20 if r.get('safe_area_fraction',area(r['safe_bbox'])/area(data['bounds']))<.32 else 0,
                   'visibility':.15 if r.get('visibility',{}).get('state','visible')=='visible' else 0,
                   'separation':.15 if r.get('automatic_split') else .10,'warnings_penalty':-.05*min(3,len(r['warnings']))}
        if r['type']=='raster_group':breakdown['parent_not_single_figure']=-.2
        r['score_breakdown']=breakdown;r['heuristic_score']=round(max(0,min(1,sum(breakdown.values()))),3)
    return new


def raster_table_probe(mask,stats):
    """Rule-line grid + many small components in cell interiors; no OCR."""
    box=mask.getbbox()
    if not box:return None
    sub=mask.crop(box);w,h=sub.size
    def peaks(im):
        width,height=im.size;raw=im.tobytes();good=[sum(raw[y*width:(y+1)*width])/255>=width*.62 for y in range(height)];groups=[];i=0
        while i<height:
            if not good[i]:i+=1;continue
            a=i
            while i<height and good[i]:i+=1
            groups.append((a+i-1)/2)
        return groups
    ys=peaks(sub);xs=peaks(sub.transpose(Image.Transpose.TRANSPOSE))
    if len(xs)<3 or len(ys)<3 or len(xs)>30 or len(ys)>40:return None
    cells=[];filled=0
    for y0,y1 in zip(ys,ys[1:]):
        for x0,x1 in zip(xs,xs[1:]):
            cell=[box[0]+x0,box[1]+y0,box[0]+x1,box[1]+y1];cells.append(cell)
            glyphs=[c for c in stats['components'] if c['bbox'][0]>cell[0]+3 and c['bbox'][1]>cell[1]+3 and c['bbox'][2]<cell[2]-3 and c['bbox'][3]<cell[3]-3 and 3<=c['bbox'][3]-c['bbox'][1]<=35 and c['pixels']>=4]
            filled+=len(glyphs)>=2
    ratio=filled/max(len(cells),1)
    if ratio<.4:return None
    return dict(bbox=list(box),rows=len(ys)-1,columns=len(xs)-1,cell_interior_component_occupancy=ratio,
                row_lines=ys,column_lines=xs,reason='long intersecting raster rules plus small text-like components inside cells; image text preserved, not transcribed',uncertain=True)
