from .raster_deps import cv2,np

def box_union(boxes):
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
def area(b):return max(0,b[2]-b[0])*max(0,b[3]-b[1])
def overlap(a,b):return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
def expand(b,p,w,h):return [max(0,int(b[0]-p)),max(0,int(b[1]-p)),min(w,int(b[2]+p)),min(h,int(b[3]+p))]
def components(mask,limit=16000):
    n,labels,stats,centers=cv2.connectedComponentsWithStats(mask,8)
    if n>limit:raise ValueError('raster_component_budget_exceeded')
    cs=[]
    for i,(x,y,w,h,pixels) in enumerate(stats[1:],1):
        if pixels<3:continue
        cs.append(dict(id=i,bbox=[int(x),int(y),int(x+w),int(y+h)],pixels=int(pixels),width=int(w),height=int(h),cx=float(centers[i,0]),cy=float(centers[i,1])))
    return cs,labels

def mask_boxes(shape,boxes):
    out=np.zeros(shape,np.uint8)
    for x0,y0,x1,y1 in boxes:out[int(y0):int(y1),int(x0):int(x1)]=255
    return out

def group_boxes(boxes,xgap,ygap):
    groups=[]
    for i,b in enumerate(boxes):
        links=[j for j,g in enumerate(groups) if any(not(b[0]>boxes[k][2]+xgap or b[2]<boxes[k][0]-xgap or b[1]>boxes[k][3]+ygap or b[3]<boxes[k][1]-ygap) for k in g)]
        if links:
            group=[i]
            for j in reversed(links):group+=groups.pop(j)
            groups.append(group)
        else:groups.append([i])
    return groups
