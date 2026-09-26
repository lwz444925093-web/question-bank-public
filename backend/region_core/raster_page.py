"""Deterministic full-page scan analysis. No OCR, model, or backend imports."""
import hashlib,time,resource,sys,json,math
from pathlib import Path
import fitz
from PIL import Image,ImageDraw
from .raster_deps import cv2,np
from .raster_geometry import components,mask_boxes,expand,area,overlap,box_union
from .raster_watermark import masks as watermark_masks
from .raster_tables import structures,detect as tables_detect
from .raster_text_blocks import detect as text_detect
from .raster_figures import detect as figures_detect
from .model import digest

COLORS={'text':'#367ac7','figure_candidate':'#d55350','table':'#258764','unknown':'#a18b43','raster_page_parent':'#8665b0'}

def segment(rgb,cfg):
    h,w=rgb.shape[:2]
    if w*h>cfg['max_analysis_pixels']:raise ValueError('raster_analysis_pixel_budget_exceeded')
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);color,watermark,wm_info=watermark_masks(rgb)
    work=gray.copy(); halo=cv2.dilate(watermark,np.ones((3,3),np.uint8)); work[(halo>0)&(gray>130)]=255
    # Local threshold keeps faint lines, while an absolute threshold rejects paper texture.
    fg=cv2.adaptiveThreshold(work,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,41,13)
    fg[work>228]=0
    cs,labelmap=components(fg,cfg['max_components'])
    heights=[c['height'] for c in cs if 8<=c['height']<=45 and .18<=c['width']/c['height']<=2 and c['pixels']>15]
    em=float(np.median(heights)) if heights else 18.;em=max(9,min(32,em))
    horizontal,vertical=structures(fg,em)
    tables,grid_unknown=tables_detect(fg,cs,em,horizontal,vertical);tboxes=[t['core'] for t in tables]
    preliminary,lines=text_detect(cs,em,w,h,tboxes)
    figures,large_unknown=figures_detect(cs,em,w,h,lines,tboxes,cfg)
    fboxes=[f['safe'] for f in figures]
    text,lines=text_detect(cs,em,w,h,tboxes+fboxes)
    # Paragraph regions may retain a short opening line, but page margin furniture is unknown.
    regions=[]
    for t in tables:
        regions.append(dict(type='table',core=t['core'],safe=expand(t['core'],3,w,h),statistics=t,score_breakdown={'horizontal_grid':.22,'vertical_grid':.22,'intersections':round(.18*t['intersections'],3),'cell_regularities':.13,'internal_text':round(.20*t['internal_text'],3)},warnings=[],reason='closed rule-line network with repeated cells and interior text-like components'))
    for f in figures:
        stats={k:v for k,v in f.items() if k not in ['core','safe','labels']};b=f['safe'];wm=float((watermark[b[1]:b[3],b[0]:b[2]]>0).mean());stats['watermark_overlap']=round(wm,4)
        regions.append(dict(type='figure_candidate',core=f['core'],safe=b,statistics=stats,labels=f['labels'],score_breakdown={'component_cluster':.25,'non_text_structure':.22,'bounded_geometry':.16,'local_whitespace':.12,'label_attachment':min(.12,len(f['labels'])*.025),'text_density_penalty':-round(min(.20,f['text_density']),3),'watermark_overlap':-round(min(.12,wm),3)},warnings=['experimental scan figure; geometric rules do not prove label completeness']+(['near paragraph: inspect context'] if f['text_density']>.05 else []),reason=f['reason']))
    for t in text:
        b=t['core'];margin=b[3]<h*.035 or b[3]>h*.93
        regions.append(dict(type='unknown' if margin else 'text',subtype='page_furniture' if margin else 'text_like',core=b,safe=expand(b,2,w,h),statistics={k:v for k,v in t.items() if k not in ['core','ids','lines']},score_breakdown={'line_alignment':.32,'small_component_density':.30,'line_spacing_consistency':round(.23*t['line_spacing_consistency'],3)},warnings=['geometry only; no OCR transcription'],reason='aligned small components grouped into bounded paragraph blocks' if not margin else 'margin text-like furniture; not a main figure'))
    for u in grid_unknown+large_unknown:
        regions.append(dict(type='unknown',core=u['core'],safe=expand(u['core'],3,w,h),statistics=u,score_breakdown={'ambiguous_structure':.4},warnings=['uncertain geometry; not counted as figure success'],reason=u.get('reason','grid without sufficient table interior text evidence')))
    assigned=[r['safe'] for r in regions];residual=[c for c in cs if c['pixels']>=em*.8 and not any(overlap(c['bbox'],b)>.5*area(c['bbox']) for b in assigned)]
    # Retain unexplained residual clusters without manufacturing tiny figure candidates.
    from .raster_geometry import group_boxes
    for indices in group_boxes([c['bbox'] for c in residual],em*1.1,em*.7):
        group=[residual[i] for i in indices];b=box_union([c['bbox'] for c in group])
        if len(group)<2 and area(b)<em*em*2:continue
        regions.append(dict(type='unknown',core=b,safe=expand(b,2,w,h),statistics={'component_count':len(group)},score_breakdown={'unclassified_ink':.35},warnings=['residual ink; no semantic assumption'],reason='remaining foreground components'))
    if len(regions)>cfg['max_regions']:raise ValueError('raster_region_budget_exceeded')
    layers={'grayscale':gray,'foreground':fg,'horizontal_structure':horizontal,'vertical_structure':vertical,'color':color,'watermark':watermark,'text_like':mask_boxes(fg.shape,[r['safe'] for r in regions if r['type']=='text']),'table':mask_boxes(fg.shape,tboxes),'figure_core':mask_boxes(fg.shape,[f['core'] for f in figures]),'figure_safe':mask_boxes(fg.shape,fboxes)}
    colors=np.zeros((int(labelmap.max())+1,3),np.uint8)
    for i in range(1,len(colors)):colors[i]=[(i*67)%200+30,(i*113)%200+30,(i*43)%200+30]
    layers['components']=colors[labelmap];density=cv2.blur((fg>0).astype(np.float32),(35,35));layers['whitespace']=((1-density)*255).astype(np.uint8)
    return regions,layers,dict(character_scale_pixels=em,component_count=len(cs),components=cs,watermark=wm_info,foreground_fraction=float((fg>0).mean()),algorithm='threshold + rule lines + components + paragraph alignment; no OCR')

def analyze_page(input_path,page_number,source_id,out,cfg,dpi=144):
    started=time.perf_counter();out=Path(out)
    with fitz.open(input_path) as doc:
        page=doc[page_number-1];adpi=cfg['analysis_dpi'];ascale=adpi/72
        if page.rect.width*page.rect.height*max(dpi,adpi)**2/72**2>min(cfg['max_render_pixels'],cfg['max_analysis_pixels']*max(1,(dpi/adpi)**2)):raise ValueError('raster_render_pixel_budget_exceeded')
        analysis=page.get_pixmap(matrix=fitz.Matrix(ascale,ascale),alpha=False,colorspace=fitz.csRGB);rgb=np.frombuffer(analysis.samples,np.uint8).reshape(analysis.height,analysis.width,3)
        found,layers,stats=segment(rgb,cfg);pix=analysis if dpi==adpi else page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False,colorspace=fitz.csRGB)
        original=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);key=f'{source_id[:12]}-p{page_number}';cfg_hash=digest(cfg)
        for folder in ['pages','overlays','crops','objects','layers']:(out/folder).mkdir(parents=True,exist_ok=True)
        original.save(out/'pages'/f'{key}.png');layerpaths={}
        for name,array in layers.items():
            im=Image.fromarray(array);im=im.resize(original.size,Image.Resampling.NEAREST) if im.size!=original.size else im
            path=f'layers/{key}-{name}.png';im.save(out/path);layerpaths[name]=path
        scale=dpi/adpi;inv=~(page.rotation_matrix*fitz.Matrix(ascale,ascale));bounds=[0,0,page.cropbox.width,page.cropbox.height]
        def canonical(b):return list(fitz.Rect(b)*inv)
        def pixels(b):return [int(math.floor(b[0]*scale)),int(math.floor(b[1]*scale)),int(math.ceil(b[2]*scale)),int(math.ceil(b[3]*scale))]
        pid=f'p{page_number}-scan-parent-{digest([source_id,page_number,cfg_hash])[:12]}'
        parent=dict(region_id=pid,source_id=source_id,page=page_number,type='raster_page_parent',core_bbox=bounds,safe_bbox=bounds,core_pixel_bbox=[0,0,pix.width,pix.height],safe_pixel_bbox=[0,0,pix.width,pix.height],source_objects=['raster-page'],source_types=['raster_page'],text='',labels=[],warnings=['full-page source parent; never an independent figure success'],detection_reasons=['original page retained for traceability'],algorithm_version=cfg['algorithm_version'],config_hash=cfg_hash,proposal_role='parent',review_status='unreviewed',children=[],parent_id=None,visibility={'state':'visible' if stats['foreground_fraction'] else 'invisible'},heuristic_score=0,score_breakdown={'traceability_only':0},statistics={'component_count':stats['component_count'],'watermark':stats['watermark']})
        regions=[parent]
        for i,r in enumerate(sorted(found,key=lambda r:(r['core'][1],r['core'][0]))):
            rid=f'p{page_number}-scan-{r["type"]}-{digest([source_id,cfg_hash,r["core"],r["type"]])[:12]}'
            labels=[dict(object_id=f'cc-{l["component_id"]}',text='',bbox=canonical(l['bbox'])) for l in r.get('labels',[])]
            score=round(max(0,min(1,sum(r['score_breakdown'].values()))),3)
            rr=dict(region_id=rid,source_id=source_id,page=page_number,type=r['type'],subtype=r.get('subtype'),core_bbox=canonical(r['core']),safe_bbox=canonical(r['safe']),core_pixel_bbox=pixels(r['core']),safe_pixel_bbox=pixels(r['safe']),source_objects=['raster-page']+[f'cc-{n}' for n in r['statistics'].get('components',[])],source_types=['raster_page','connected_components'],text='',labels=labels,warnings=r['warnings'],detection_reasons=[r['reason']],algorithm_version=cfg['algorithm_version'],config_hash=cfg_hash,proposal_role='child',review_status='unreviewed',parent_id=pid,parent_bbox=bounds,child_relative_pixel_bbox=pixels(r['safe']),child_relative_bbox_pt=canonical(r['safe']),automatic_split=True,split_status='scan_geometry',split_evidence=[r['reason']],text_semantics_reliable=False,statistics=r['statistics'],heuristic_score=score,score_breakdown=r['score_breakdown'])
            if r['type']=='table':rr['table_structure']=dict(rows=r['statistics']['rows'],columns=r['statistics']['columns'],basis='raster-rule-lines',text_authority='full_page')
            regions.append(rr);parent['children'].append(rid)
        overlay=original.copy();draw=ImageDraw.Draw(overlay)
        for i,r in enumerate(regions):
            r.update(reading_order_hint=i+1,page_key=key,crop_pixel_bbox=r['safe_pixel_bbox'],safe_area_fraction=area(r['safe_bbox'])/area(bounds))
            b=r['safe_pixel_bbox'];crop=original.crop(b);r['crop_size']=list(crop.size);r['crop']=f'crops/{source_id[:12]}-{r["region_id"]}.png';crop.save(out/r['crop'])
            draw.rectangle(b,outline=COLORS[r['type']],width=2);draw.text((b[0],max(0,b[1]-12)),r['type'][:2]+str(i),fill=COLORS[r['type']])
        overlay.save(out/'overlays'/f'{key}.png');(out/'objects'/f'{key}.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        meta=dict(page_key=key,source_id=source_id,page=page_number,native_size=[page.cropbox.width,page.cropbox.height],rotation=page.rotation,cropbox=list(page.cropbox),mediabox=list(page.mediabox),cropbox_position=list(page.cropbox_position),render_size=[pix.width,pix.height],dpi=dpi,analysis_dpi=adpi,render_origin=[pix.x,pix.y],coordinates={'core_safe':'unrotated CropBox-relative points','pixel_bbox':'rotated displayed page pixels','pdf_to_mupdf_matrix':list(page.transformation_matrix),'unrotated_to_rotated_matrix':list(page.rotation_matrix),'unrotated_to_pixel_matrix':list(page.rotation_matrix*fitz.Matrix(dpi/72,dpi/72)),'pixel_offset':[-pix.x,-pix.y],'rounding':'outward integer window of original full-page render'},text_reliability={'text_geometry_available':False,'text_semantics_reliable':False,'warnings':['scan text-like geometry only; no OCR']},classification='raster_dominant',classification_reasons=['routed from native structural coverage check'],analyzer=cfg['algorithm_version'],original=f'pages/{key}.png',overlay=f'overlays/{key}.png',objects=f'objects/{key}.json',debug_layers=layerpaths,scan_statistics={k:v for k,v in stats.items() if k!='components'},region_counts={k:sum(r['type']==k for r in regions) for k in COLORS},elapsed_seconds=time.perf_counter()-started,worker_peak_rss_bytes=peak,figure_area_sum=sum(r['safe_area_fraction'] for r in regions if r['type']=='figure_candidate'),alternative_count=0)
    return meta,regions
