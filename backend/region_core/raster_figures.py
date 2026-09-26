"""Bounded non-text component cores with short label attachment."""
from .raster_geometry import area,overlap,box_union,expand,group_boxes

def detect(cs,em,w,h,text_lines,tables,cfg):
    lineboxes=[l['bbox'] for l in text_lines];text_ids={i for l in text_lines for i in l['ids']}
    seeds=[]
    for c in cs:
        b=c['bbox'];ww=c['width'];hh=c['height']
        if any(overlap(b,t)>.25*area(b) for t in tables):continue
        if c['id'] in text_ids:continue
        # Underlines / header rules / skinny scan borders are not figure cores.
        if (ww>em*4 and hh<em*.55) or (hh>h*.55 and ww<em*.55):continue
        if hh>=em*1.95 and ww>=em*1.25 and c['pixels']>=em*3:seeds.append(c)
    groups=group_boxes([c['bbox'] for c in seeds],em*.18,em*.45);figures=[];unknown=[]
    cores=[box_union([seeds[i]['bbox'] for i in g]) for g in groups]
    def distance(a,b):return max(a[0]-b[2],b[0]-a[2],0)**2+max(a[1]-b[3],b[1]-a[3],0)**2
    for group in groups:
        selected=[seeds[i] for i in group];core=box_union([c['bbox'] for c in selected]);a=area(core)
        if a<w*h*.0008:continue
        if a>w*h*cfg['max_figure_fraction'] or core[3]-core[1]>h*cfg['max_figure_height_fraction']:
            unknown.append(dict(core=core,reason='non-text structure exceeds bounded figure geometry'));continue
        limit=min(em*cfg['max_safe_expansion_em'],cfg['max_safe_expansion_pt']*2)
        neighborhood=expand(core,em*cfg['label_reach_em'],w,h)
        attached=[]
        for c in cs:
            b=c['bbox']
            if c in selected or any(overlap(b,t)>.5*area(b) for t in tables):continue
            if c['id'] in text_ids:continue
            if any(distance(b,other)<distance(b,core) for other in cores if other!=core):continue
            if c['height']<em*1.9 and c['width']<em*2.8 and c['pixels']>=3 and overlap(neighborhood,b)>0:
                if b[0]>=core[0]-limit and b[2]<=core[2]+limit and b[1]>=core[1]-limit and b[3]<=core[3]+limit:attached.append(c)
        # Short axis digits may be grouped into a nearby text line and excluded
        # from attached. Less than a glyph's width cut the leading 1 of 100 in
        # the real exam p8. Keep bounded extra context around the complete core;
        # semantic QA still decides whether any essential label is missing.
        safe=expand(box_union([core]+[c['bbox'] for c in attached]),max(3,em*.65),w,h)
        contamination=sum(overlap(safe,b) for b in lineboxes)/max(1,area(safe))
        figures.append(dict(core=core,safe=safe,components=[c['id'] for c in selected],labels=[dict(component_id=c['id'],bbox=c['bbox'],text='') for c in attached],text_density=round(contamination,3),component_count=len(selected)+len(attached),safe_expansion=[core[0]-safe[0],core[1]-safe[1],safe[2]-core[2],safe[3]-core[3]],reason='large non-text components; bounded local short-component attachment'))
    return figures,unknown
