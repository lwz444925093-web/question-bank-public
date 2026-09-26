"""Pillow + standard library only; inspect actual PDF-rendered pixels."""
from PIL import Image, ImageChops, ImageStat


def components(mask,limit=20000):
    """8-connected run-length labelling; returns pixel counts and bounding boxes."""
    im=mask.convert('L');w,h=im.size;raw=im.tobytes();parents=[];stats=[];previous=[]
    def find(x):
        while parents[x]!=x:parents[x]=parents[parents[x]];x=parents[x]
        return x
    for y in range(h):
        row=raw[y*w:(y+1)*w];current=[];x=0
        while x<w:
            start=row.find(b'\xff',x)
            if start<0:break
            end=row.find(b'\x00',start)
            if end<0:end=w
            x=end;matches=[find(i) for a,b,i in previous if a<=end and b>=start]
            if matches:
                idx=min(matches)
                for other in set(matches):
                    other=find(other);idx=find(idx)
                    if other==idx:continue
                    parents[other]=idx;s=stats[other];t=stats[idx]
                    t[0]+=s[0];t[1]=min(t[1],s[1]);t[2]=min(t[2],s[2]);t[3]=max(t[3],s[3]);t[4]=max(t[4],s[4])
                s=stats[find(idx)];s[0]+=end-start;s[1]=min(s[1],start);s[3]=max(s[3],end);s[4]=y+1
            else:
                idx=len(parents)
                if idx>=limit:raise ValueError('raster_component_budget_exceeded')
                parents.append(idx);stats.append([end-start,start,y,end,y+1])
            current.append((start,end,idx))
        previous=current
    return [dict(pixels=s[0],bbox=s[1:]) for i,s in enumerate(stats) if find(i)==i]


def inspect(image,cfg):
    rgba=image.convert('RGBA');alpha=rgba.getchannel('A');white=Image.new('RGBA',rgba.size,'white');white.alpha_composite(rgba);rgb=white.convert('RGB');gray=rgb.convert('L')
    w,h=gray.size;pixels=w*h;hist=gray.histogram();variance=ImageStat.Stat(gray).var[0]
    border=gray.crop((0,0,w,min(h,3))).histogram();border=[a+b for a,b in zip(border,gray.crop((0,max(0,h-3),w,h)).histogram())]
    target=sum(border)//2;acc=0;background=255
    for i,n in enumerate(border):
        acc+=n
        if acc>=target:background=i;break
    # Foreground relative to border background preserves white ink on black.
    delta=ImageChops.difference(gray,Image.new('L',gray.size,background))
    threshold=cfg.get('raster_contrast_threshold',22)
    mask=delta.point(lambda x:255 if x>=threshold else 0)
    cc=components(mask,cfg.get('max_raster_components',20000))
    foreground=sum(c['pixels'] for c in cc);largest=max([c['pixels'] for c in cc]or[0])
    extent=max([max(c['bbox'][2]-c['bbox'][0],c['bbox'][3]-c['bbox'][1]) for c in cc]or[0])
    dark=sum(hist[:180]);nonwhite=sum(hist[:245]);minval,maxval=gray.getextrema();alpha_fraction=(pixels-alpha.histogram()[0])/max(pixels,1)
    if alpha_fraction==0:state='invisible';reason='zero effective alpha'
    elif minval>=253 and variance<.4:state='invisible';reason='actual rendered pixels are effectively white; no contrasted ink'
    elif minval<253 and nonwhite>=20 and foreground<16:state='uncertain';reason='extended low-contrast content; retained rather than discarded'
    elif foreground<=8 and extent<=4 and dark<=8:state='near_blank';reason='only a few isolated pixels; no extended line or useful component'
    elif foreground>=16 and extent>=8:state='visible';reason='extended contrasted components, not white-area percentage alone'
    else:state='uncertain';reason='low contrast or uniform dark content; retained for inspection'
    if maxval<180 and variance<1:state='uncertain';reason='uniform dark object; not discarded as white/transparent'
    return dict(state=state,reason=reason,pixel_size=[w,h],nonwhite_pixels=nonwhite,nonwhite_ratio=nonwhite/max(pixels,1),
                dark_pixels=dark,foreground_pixels=foreground,foreground_ratio=foreground/max(pixels,1),variance=variance,
                alpha_effective_fraction=alpha_fraction,background_gray=background,contrast_threshold=threshold,
                component_count=len(cc),largest_component_pixels=largest,max_component_extent=extent,
                ink_bbox=list(mask.getbbox()) if mask.getbbox() else None,components=cc),mask
