"""Deterministic geometric proposals, never question-number parsing."""
from .model import area, union, intersect, expand, gap, coverage, digest


def _visible_ink_path(path):
    """A white fill does not hide the black outline of a hollow conductor."""
    return any(
        path.get(key) is not None and min(path[key]) <= .97
        and (path.get(opacity) is None or path[opacity] > 0)
        for key, opacity in (('fill', 'fill_opacity'), ('color', 'stroke_opacity'))
    )


def _closed_curve(obj, em):
    if obj['kind'] != 'path':
        return False
    b = obj['bbox']; items = obj['path'].get('items', [])
    curves = [i for i in items if i[0] == 'c']
    # A separate sphere can be smaller than a text line, but has a complete
    # two-dimensional outline. Fractions and minus signs do not qualify.
    return (min(b[2]-b[0], b[3]-b[1]) >= em*.7 and len(curves) >= 4
            and max(abs(curves[0][1][i]-curves[-1][-1][i]) for i in (0, 1)) < .2)


def group_page(data, cfg, source_id, page_number):
    objects=data['objects']; texts=[o for o in objects if o['kind']=='text']
    em=data['em']; bounds=data['bounds']; page_area=area(bounds)
    semantics=data.get('text_reliability',{}).get('text_semantics_reliable',True)
    cfg_hash=digest(cfg); regions=[]; seeds=[]; exclusions=[]
    reliable_tables=[t for t in data['tables'] if t['reliable']]
    line_texts = {}
    for t in texts:
        line_texts.setdefault(t['line'], []).append(t['text'])
    prose_lines = {line for line, parts in line_texts.items()
                   if len(''.join(parts)) > 12 and any(c in ''.join(parts) for c in '，。；？：,.?;:')}

    def region(kind, core, members, reason, labels=None, warnings=None, padding=None):
        labels=labels or []; warnings=warnings or []
        joined=union([core]+[t['bbox'] for t in labels])
        pad=min(cfg['max_padding_pt'],em*cfg['padding_em']) if padding is None else padding
        safe=intersect(expand(joined,pad),bounds)
        # Reduce only extra padding at nearby body text; never remove core/labels.
        ids={o['id'] for o in members+labels}
        for t in texts:
            if t['id'] in ids or not area(intersect(t['bbox'], safe)): continue
            b=t['bbox']
            if b[2]<=joined[0]: safe[0]=max(safe[0],b[2]+.5)
            elif b[0]>=joined[2]: safe[2]=min(safe[2],b[0]-.5)
            elif b[3]<=joined[1]: safe[1]=max(safe[1],b[3]+.5)
            elif b[1]>=joined[3]: safe[3]=min(safe[3],b[1]-.5)
        if kind=='figure_candidate' and any(o['id'] not in ids and len(o['text'])>5 and area(intersect(o['bbox'],safe))>em for o in texts):
            warnings.append('safe box intersects unreferenced prose; inspect crop')
        refs=sorted(ids)
        rid=f'p{page_number}-{kind}-{digest([source_id,page_number,cfg_hash,kind,refs])[:12]}'
        if area(safe)/page_area>cfg['max_cluster_area_fraction'] and kind=='figure_candidate':
            warnings.append('fallback_large_context: not a clean usable figure')
        for t in labels: t['figure_refs'].append(rid)
        r=dict(region_id=rid,source_id=source_id,page=page_number,type=kind,
               core_bbox=list(core),safe_bbox=safe,source_objects=refs,
               text='\n'.join(o['text'] for o in members+labels if o['kind']=='text'),
               labels=[dict(object_id=t['id'],text=t['text'],bbox=t['bbox']) for t in labels],
               detection_reasons=reason,warnings=warnings,algorithm_version=cfg['algorithm_version'],
               config_hash=cfg_hash,proposal_role='core',review_status='unreviewed')
        regions.append(r); return r

    for t in reliable_tables:
        members=[o for o in objects if coverage(t['bbox'],expand(o['bbox'],.01))>.8]
        r=region('table',t['bbox'],members,[t['reason'],f"{t['rows']} rows x {t['columns']} columns",f"cell interior occupancy {t['interior_occupied_fraction']:.3f}"],warnings=['rule-based table candidate; not human confirmed'])
        r['table_structure']=dict(rows=t['rows'],columns=t['columns'],basis='native-rule-lines',text_authority='full_page')
        if semantics:
            from .table_text import native_text_cells
            cell_text=native_text_cells(t,members)
            if cell_text is not None:
                r['table_structure'].update(text_cells=cell_text,text_authority='verified_native_cells')

    for o in objects:
        if o['kind']=='text': continue
        b=o['bbox']; w=b[2]-b[0]; h=b[3]-b[1]; why=None
        if any(coverage(t['bbox'],expand(b,.05))>.85 for t in reliable_tables):
            o['disposition']='table_component';continue
        if o['kind']=='image':
            if area(b)/page_area>.6 or data['classification']=='raster_dominant': why='raster page/context image: excluded from successful figures'
            elif w<em*.7 and h<em*1.5: why='small inline image/formula fragment: uncertain'
        else:
            p=o['path']
            if not _visible_ink_path(p): why='white background/cover path'
            elif w>bounds[2]*.6 and h<em*.25: why='long horizontal rule: cannot bridge drawing clusters'
            elif w>bounds[2]*.9 and h>bounds[3]*.8: why='page frame/background'
            elif h<em*.2 and w<em*12 and any(gap(b,t['bbox'])<em*.3 for t in texts if len(t['text'])>5):
                why='horizontal stroke adjacent to prose: underline/inline formula'
            elif w<em*2 and h<em*1.5 and any(coverage(expand(t['bbox'],em*.25),b)>.5 or gap(b,t['bbox'])<em*.15 for t in texts if len(t['text'])>3):
                why='small path attached to text/formula'
        if why:
            o['disposition']=why; exclusions.append(o)
        else:
            o['disposition']='core_seed';seeds.append(o)

    # Conservative bounded connected components. Cluster boxes may not grow across
    # the page via chains of underlines. Prose in gaps blocks otherwise near cores.
    clusters=[[o] for o in seeds]
    def allowed(a,b, detached=False):
        ba=union(o['bbox'] for o in a);bb=union(o['bbox'] for o in b)
        combined=union([ba,bb])
        if detached:
            if not semantics or gap(ba,bb)>em*cfg.get('detached_curve_gap_em', 2.75):return False
            # Relax only horizontal whitespace within a drawing row; never
            # cross a question line, merge vertically, or recursively span a page.
            overlap=min(ba[3],bb[3])-max(ba[1],bb[1])
            if overlap < min(ba[3]-ba[1],bb[3]-bb[1])*.6:return False
            if combined[2]-combined[0]>em*20:return False
            if not any(min(box[2]-box[0],box[3]-box[1])>=em*2 for box in (ba,bb)):return False
            if not any(_closed_curve(o,em) for o in a+b):return False
            # Whole text lines are the barrier: a single Latin span from a
            # sentence must not be mistaken for a harmless diagram label.
            if any(t['line'] in prose_lines and area(intersect(combined,t['bbox'])) for t in texts):return False
        elif gap(ba,bb)>em*cfg['cluster_gap_em']:return False
        if area(combined)>page_area*cfg['max_cluster_area_fraction'] or combined[2]-combined[0]>bounds[2]*cfg['max_cluster_width_fraction'] or combined[3]-combined[1]>bounds[3]*cfg['max_cluster_height_fraction']:return False
        # Two non-overlapping substantial raster instances stay distinct; small
        # overlays can still join a containing vector/bitmap diagram.
        if any(x['kind']=='image' and area(x['bbox'])>em*em*9 for x in a) and any(x['kind']=='image' and area(x['bbox'])>em*em*9 for x in b) and not area(intersect(ba,bb)): return False
        for t in texts:
            if len(t['text'])>12 and coverage(combined,t['bbox'])>.7 and coverage(ba,t['bbox'])<.2 and coverage(bb,t['bbox'])<.2:return False
        return True
    changed=True
    while changed:
        changed=False
        for i in range(len(clusters)):
            match=next((j for j in range(i+1,len(clusters)) if allowed(clusters[i],clusters[j])),None)
            if match is not None:
                clusters[i]+=clusters.pop(match);changed=True;break
    changed=True
    while changed:
        changed=False
        for i in range(len(clusters)):
            match=next((j for j in range(i+1,len(clusters)) if allowed(clusters[i],clusters[j],detached=True)),None)
            if match is not None:
                clusters[i]+=clusters.pop(match);changed=True;break
    cores=[union(o['bbox'] for o in c) for c in clusters]
    label_owners={}
    for t in texts:
        b=t['bbox']; size=t['size']; w=b[2]-b[0]; h=b[3]-b[1]
        eligible=[]
        line_text=''.join(x['text'] for x in texts if x['line']==t['line']) if semantics else ''
        section_heading=line_text.strip().startswith('【') and '】' in line_text
        for ci, core in enumerate(cores):
            distance=gap(core,b); inside=coverage(core,b)>.72
            # Uses position, size, direction and extent, not a 6-character test.
            # Long legends can be included inside or aligned just below a core.
            compact=w<=max(em*4, (core[2]-core[0])*.32) and h<=em*2.5
            caption=b[1]>=core[3]-em*.3 and b[1]<=core[3]+em*cfg['label_reach_em'] and w<=(core[2]-core[0])*1.4 and size<=em*1.05
            near=distance<=em*cfg['label_reach_em'] and size<=em*1.15 and (compact or caption)
            if inside or (near and semantics):
                if section_heading and not inside: continue
                if not inside and t['line'] in prose_lines: continue
                # Do not absorb normal text lines ending in prose punctuation.
                if semantics and not inside and any(c in t['text'] for c in '，。；？：') and len(t['text'])>8:continue
                eligible.append((distance, -coverage(core,b),ci))
        if eligible:label_owners[t['id']]=min(eligible)[2]
    for ci,(core,members) in enumerate(zip(cores,clusters)):
        labels=[t for t in texts if label_owners.get(t['id'])==ci]
        warnings=[]
        if core[2]-core[0]<em*2 and core[3]-core[1]<em*2 and all(o['kind']=='path' for o in members):
            region('unknown',core,members,['isolated small drawing: formula or symbol; not enough spatial evidence'],padding=1);continue
        if core[2]-core[0]<em*.2 or core[3]-core[1]<em*.2:
            region('unknown',core,members,['isolated thin rule retained, not discarded'],padding=1);continue
        if data['suspicious_character_ratio']>.08:warnings.append('text encoding unreliable; label text may be corrupted; inspect original crop')
        if any(coverage(core,t['bbox'])>.5 for t in data['tables'] if not t['reliable']):warnings.append('grid/table ambiguity; retained as figure candidate')
        body_overlap=[t for t in texts if t not in labels and len(t['text'])>12 and coverage(core,t['bbox'])>.4]
        if body_overlap:warnings.append('core intersects prose; inspect for merged context')
        if any(o['kind']=='image' for o in members):warnings.append('embedded raster content not OCR inspected; labels inside bitmap are visually preserved but not transcribed')
        region('figure_candidate',core,members,['local image/path connected component',f'{len(members)} structural components',f'{len(labels)} nearby/contained text fragments; attachment measured from core without recursive expansion'],labels,warnings)
    # Exclusions are visible unknown regions and remain individually traceable.
    for o in exclusions:
        if area(intersect(expand(o['bbox'],.5),bounds)):
            region('unknown',expand(o['bbox'],.4),[o],[o['disposition']],padding=.5)
    # Text regions use source lines, while fine-grained spans stay in the inventory.
    by_id={o['id']:o for o in texts}
    for line in data['lines']:
        members=[by_id[x] for x in line['spans']]
        core=union(o['bbox'] for o in members)
        if area(intersect(core,bounds)):
            r=region('text',core,members,['native text line; reading order is only a spatial suggestion'],padding=.5)
            r['contained_by_figures']=sorted({rid for o in members for rid in o['figure_refs']})
    regions.sort(key=lambda r:(round(r['core_bbox'][1],1),r['core_bbox'][0],r['type']))
    for i,r in enumerate(regions):r['reading_order_hint']=i+1
    return regions
