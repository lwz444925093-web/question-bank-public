"""Paragraph geometry without recognizing characters or numbers."""
from .raster_geometry import box_union,overlap,area,group_boxes
import statistics

def detect(cs,em,w,h,excluded):
    glyphs=[c for c in cs if .30*em<=c['height']<=1.8*em and .08*em<=c['width']<=2.8*em and c['pixels']>=4 and not any(overlap(c['bbox'],b)>.5*area(c['bbox']) for b in excluded)]
    rows=[]
    for c in sorted(glyphs,key=lambda c:c['cy']):
        candidates=[r for r in rows if abs(statistics.median(o['cy'] for o in r)-c['cy'])<em*.48]
        if candidates:min(candidates,key=lambda r:abs(statistics.median(o['cy'] for o in r)-c['cy'])).append(c)
        else:rows.append([c])
    lines=[]
    for row in rows:
        segments=[]
        for c in sorted(row,key=lambda c:c['bbox'][0]):
            if segments and c['bbox'][0]-segments[-1][-1]['bbox'][2]<em*2.4:segments[-1].append(c)
            else:segments.append([c])
        for seg in segments:
            b=box_union([c['bbox'] for c in seg]);width=b[2]-b[0]
            if len(seg)>=6 and width>=em*5:
                lines.append(dict(bbox=b,ids=[c['id'] for c in seg],count=len(seg),density=sum(c['pixels'] for c in seg)/max(1,area(b))))
    # Paragraph merging is bounded and stopped at table/figure exclusions.
    groups=[]
    for line in sorted(lines,key=lambda l:(l['bbox'][1],l['bbox'][0])):
        b=line['bbox'];matches=[]
        for i,g in enumerate(groups):
            last=g[-1]['bbox'];gb=box_union([x['bbox'] for x in g]);gap=b[1]-last[3]
            aligned=abs(b[0]-gb[0])<em*3 or (b[0]>=gb[0]-em and b[2]<=gb[2]+em)
            if 0<=gap<em*1.65 and aligned and b[3]-gb[1]<h*.20:
                bridge=box_union([gb,b])
                if not any(overlap(bridge,e)>0 for e in excluded):matches.append(i)
        if matches:groups[matches[-1]].append(line)
        else:groups.append([line])
    blocks=[]
    for g in groups:
        box=box_union([l['bbox'] for l in g]);gaps=[g[i+1]['bbox'][1]-g[i]['bbox'][3] for i in range(len(g)-1)]
        blocks.append(dict(core=box,lines=g,ids=sum([l['ids'] for l in g],[]),line_count=len(g),component_count=sum(l['count'] for l in g),line_spacing_consistency=round(1/(1+(statistics.pstdev(gaps)/em if len(gaps)>1 else 0)),3),text_density=round(sum(l['density'] for l in g)/len(g),3)))
    # Remove nested fragments and coalesce intersecting paragraph boxes.
    changed=True
    while changed:
        changed=False
        for i in range(len(blocks)):
            for j in range(i+1,len(blocks)):
                a,b=blocks[i],blocks[j];joined=box_union([a['core'],b['core']])
                if overlap(a['core'],b['core'])>0 and joined[3]-joined[1]<h*.23 and not any(overlap(joined,e)>0 for e in excluded):
                    lineset={tuple(l['bbox']):l for l in a['lines']+b['lines']}
                    a.update(core=joined,lines=list(lineset.values()),ids=list(set(a['ids']+b['ids'])),line_count=len(lineset),component_count=len(set(a['ids']+b['ids'])))
                    blocks.pop(j);changed=True;break
            if changed:break
    return blocks,lines
