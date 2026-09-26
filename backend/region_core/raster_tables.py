"""Rule grids with populated cells; empty coordinate grids are not tables."""
from .raster_deps import cv2,np
from .raster_geometry import components,expand,overlap,area

def structures(mask,em):
    # Close tiny breaks before line opening; modest skew admitted by later Hough probe.
    closed=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((2,2),np.uint8))
    horizontal=cv2.morphologyEx(closed,cv2.MORPH_OPEN,np.ones((1,max(25,int(em*3))),np.uint8))
    vertical=cv2.morphologyEx(closed,cv2.MORPH_OPEN,np.ones((max(25,int(em*3)),1),np.uint8))
    return horizontal,vertical

def runs(values):
    indices=np.flatnonzero(values);out=[]
    for x in indices:
        if not out or x>out[-1][-1]+2:out.append([int(x)])
        else:out[-1].append(int(x))
    return [int(np.mean(x)) for x in out]

def detect(mask,cs,em,horizontal,vertical):
    network=cv2.bitwise_or(horizontal,vertical)
    joined=cv2.dilate(network,np.ones((5,5),np.uint8))
    nets,_=components(joined);h,w=mask.shape;tables=[];uncertain=[]
    for c in nets:
        b=c['bbox'];x0,y0,x1,y1=b;ww=x1-x0;hh=y1-y0
        if ww<em*6 or hh<em*2.5 or ww*hh>w*h*.4:continue
        xs=runs((vertical[y0:y1,x0:x1]>0).sum(axis=0)>hh*.60)
        ys=runs((horizontal[y0:y1,x0:x1]>0).sum(axis=1)>ww*.60)
        if len(xs)<3 or len(ys)<3:continue
        filled=0;cells=0
        for ya,yb in zip(ys,ys[1:]):
            for xa,xb in zip(xs,xs[1:]):
                cell=[x0+xa+3,y0+ya+3,x0+xb-3,y0+yb-3];cells+=1
                glyphs=[o for o in cs if .22*em<=o['height']<=1.9*em and o['width']<=em*3 and overlap(cell,o['bbox'])>.8*area(o['bbox'])]
                # A legitimate cell often contains a single digit or unknown
                # letter. Count occupied cells, not the length of their text.
                filled+=len(glyphs)>=2 or any(o['height']>=.55*em for o in glyphs)
        occupied=filled/max(1,cells)
        intersections=sum(horizontal[min(h-1,y0+y),min(w-1,x0+x)]>0 or mask[min(h-1,y0+y),min(w-1,x0+x)]>0 for x in xs for y in ys)/max(1,len(xs)*len(ys))
        item=dict(core=expand([x0+xs[0],y0+ys[0],x0+xs[-1]+1,y0+ys[-1]+1],3,w,h),rows=len(ys)-1,columns=len(xs)-1,internal_text=round(occupied,3),intersections=round(float(intersections),3),horizontal_lines=len(ys),vertical_lines=len(xs),cell_boxes=[[[x0+xa,y0+ya,x0+xb,y0+yb] for xa,xb in zip(xs,xs[1:])] for ya,yb in zip(ys,ys[1:])])
        if occupied>=.35:item['type']='table';tables.append(item)
        elif occupied>.12:item['type']='unknown';uncertain.append(item)
    return tables,uncertain
