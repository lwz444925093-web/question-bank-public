"""Conservative color suppression for analysis only; never edit source pixels."""
from .raster_deps import cv2,np

def masks(rgb):
    r,g,b=[rgb[:,:,i].astype(np.int16) for i in range(3)]
    chroma=(r-np.minimum(g,b)>25)&(r>120)&(g>80)&(b>80)&(np.maximum(g,b)-np.minimum(g,b)<70)
    candidate=chroma.astype(np.uint8)*255
    points=cv2.findNonZero(candidate);wm=np.zeros(candidate.shape,np.uint8);evidence={'colored_pixels':int(chroma.sum()),'suppressed':False}
    if points is not None and len(points)>250:
        x,y,w,h=cv2.boundingRect(points);rect=cv2.minAreaRect(points);(_, _),(rw,rh),ang=rect
        if rw<rh:ang+=90
        angle=((ang+90)%180)-90
        # Large pale red diagonal stamp only. Local saturated/color diagrams remain.
        broad=w>rgb.shape[1]*.25 and h>rgb.shape[0]*.15
        diagonal=18<abs(angle)<72
        evidence.update(bbox=[x,y,x+w,y+h],principal_angle=round(angle,2),broad=broad,diagonal=diagonal)
        if broad and diagonal:
            wm=candidate;evidence['suppressed']=True
    return candidate,wm,evidence
