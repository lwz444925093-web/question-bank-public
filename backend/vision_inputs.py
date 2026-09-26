"""Source-rendered views and explicit, reversible image coordinate provenance.

All public boxes refer to the visible, rotated CropBox (0..1000). A view's
pixel_origin accounts for raster rounding; PDF unrotated coordinates are a
separate transform. Never crop/upscale the 108-DPI page preview for reading.
"""
import hashlib, json, math
from pathlib import Path
import fitz
from PIL import Image, ImageOps

VERSION='source-views-v2'
ROLES={'page_context','question_view','detail_view','figure_asset'}

def checked_box(box):
    if not isinstance(box,(list,tuple)) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):
        raise ValueError('bbox 必须是四个有限数字')
    x0,y0,x1,y1=box
    if not (0<=x0<x1<=1000 and 0<=y0<y1<=1000):raise ValueError('bbox 超出 0–1000 或为空')
    return list(box)

def image_info(path):
    path=Path(path);raw=path.read_bytes()
    with Image.open(path) as im:
        rgb=im.convert('RGB')
        return dict(file=path.name,width=im.width,height=im.height,format=im.format,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),pixel_sha256=hashlib.sha256(str(rgb.size).encode()+rgb.tobytes()).hexdigest())

def source_image(folder):
    for ext in ('png','jpg','jpeg'):
        p=Path(folder)/('original.'+ext)
        if p.is_file():return p
    return Path(folder)/'image.png'

def region_asset_name(page,box,role,dpi):
    ident=hashlib.sha256(json.dumps([VERSION,page,box,role,dpi],sort_keys=True).encode()).hexdigest()[:20]
    return f'vision-{role}-{page}-{ident}.png'

def render_region(folder,page,box,role='question_view',dpi=216,view_id=None):
    folder=Path(folder);box=checked_box(box)
    if role not in ROLES:raise ValueError('未知视觉图片用途')
    if type(page) is not int or page<1:raise ValueError('源页码必须为正整数')
    if not 72<=dpi<=360:raise ValueError('区域渲染 DPI 必须为72–360')
    path=folder/region_asset_name(page,box,role,dpi)
    pdf=folder/'original.pdf'
    source=pdf if pdf.is_file() else source_image(folder)
    def fingerprint(file):
        st=file.stat();return [st.st_size,st.st_mtime_ns,st.st_ctime_ns]
    source_stamp=fingerprint(source)
    metadata=path.with_suffix('.json')
    try:
        cached=json.loads(metadata.read_text())
        if cached['source_stamp']==source_stamp and cached['image_stamp']==fingerprint(path):
            return dict(cached['view'],view_id=view_id or path.name)
    except (OSError,ValueError,KeyError,TypeError):pass
    if pdf.is_file():
        with fitz.open(pdf) as doc:
            p=doc[page-1];w,h=p.rect.width,p.rect.height
            clip=fitz.Rect(box[0]*w/1000,box[1]*h/1000,box[2]*w/1000,box[3]*h/1000)
            pix=p.get_pixmap(clip=clip,dpi=dpi,alpha=False)
            raw=pix.tobytes('png')
            geometry=dict(page_size=[w,h],rotation=p.rotation,cropbox=list(p.cropbox),mediabox=list(p.mediabox),derotation_matrix=list(p.derotation_matrix),pixel_origin=[pix.x,pix.y],pixels_per_unit=dpi/72,clip_source=list(clip),source_kind='pdf',dpi=dpi)
    else:
        if page!=1:raise ValueError('图片只支持源页1')
        with Image.open(source_image(folder)) as original:
            from .image_background import opaque_rgb
            im=opaque_rgb(ImageOps.exif_transpose(original));w,h=im.size
            rect=[round(box[0]*w/1000),round(box[1]*h/1000),round(box[2]*w/1000),round(box[3]*h/1000)]
            if rect[2]<=rect[0] or rect[3]<=rect[1]:raise ValueError('区域小于一个源像素')
            import io
            stream=io.BytesIO();im.crop(rect).save(stream,format='PNG');raw=stream.getvalue()
            geometry=dict(page_size=[w,h],rotation=0,cropbox=[0,0,w,h],mediabox=[0,0,w,h],derotation_matrix=[1,0,0,1,0,0],pixel_origin=rect[:2],pixels_per_unit=1,clip_source=rect,source_kind='image',dpi=None)
    # Concurrent calls to the same region never expose a partially written image.
    if not path.exists() or path.read_bytes()!=raw:
        import uuid
        temp=folder/(path.stem+'-'+uuid.uuid4().hex+'.tmp');temp.write_bytes(raw);temp.replace(path)
    view=dict(view_id=view_id or path.name,asset=path.name,path=str(path),page=page,role=role,source_box=box,coordinate_space='local-image-0-1000',**geometry,**image_info(path))
    import uuid
    temporary=metadata.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(dict(source_stamp=source_stamp,image_stamp=fingerprint(path),view=view)))
    temporary.replace(metadata)
    return view

def view_box_to_page(view,box):
    x0,y0,x1,y1=checked_box(box);ox,oy=view['pixel_origin'];scale=view['pixels_per_unit'];w,h=view['page_size']
    pixels=[x0*view['width']/1000,y0*view['height']/1000,x1*view['width']/1000,y1*view['height']/1000]
    source=[(ox+pixels[0])/scale,(oy+pixels[1])/scale,(ox+pixels[2])/scale,(oy+pixels[3])/scale]
    return checked_box([max(0,min(1000,v/d*1000)) for v,d in zip(source,[w,h,w,h])])

def page_box_to_view(view,box):
    box=checked_box(box);ox,oy=view['pixel_origin'];scale=view['pixels_per_unit'];w,h=view['page_size']
    values=[(v*d/1000*scale-off)/size*1000 for v,d,off,size in zip(box,[w,h,w,h],[ox,oy,ox,oy],[view['width'],view['height'],view['width'],view['height']])]
    return values

def page_box_to_pdf(view,box):
    """PDF page's unrotated coordinate system; separate from displayed page."""
    box=checked_box(box);w,h=view['page_size']
    r=fitz.Rect(box[0]*w/1000,box[1]*h/1000,box[2]*w/1000,box[3]*h/1000)
    return list(r*fitz.Matrix(*view['derotation_matrix']))

def padded_box(box,page_size,margin):
    x0,y0,x1,y1=checked_box(box);w,h=page_size
    return [max(0,x0-margin/w*1000),max(0,y0-margin/h*1000),min(1000,x1+margin/w*1000),min(1000,y1+margin/h*1000)]

def text_quality(page):
    """Conservative evidence, not a claim that every existing text layer is good."""
    text=page.get_text();chars=[c for c in text if not c.isspace()]
    bad=sum(c=='\ufffd' or 0xE000<=ord(c)<=0xF8FF or (ord(c)<32) for c in chars)
    suspicious=bool(bad) or '(cid:' in text or '\x00' in text
    reliable=len(chars)>=20 and not suspicious
    visual=bool(page.get_images() or page.get_drawings())
    return dict(characters=len(chars),suspicious_characters=bad,reliable=reliable,visual_objects=visual,text_only_safe=reliable and not visual)

def with_question_views(bundle,regions,detail_regions=None):
    """Explicit complete-question regions; overlapping parts remain one question.

    Regions are supplied by a checked source selection, never guessed from fixed
    heights. Ambiguous automatic boundaries retain the page context instead.
    """
    from . import store
    folder=store.DATA/'sources'/bundle['source_id']
    if not isinstance(regions,list) or not regions or len(regions)>12:raise ValueError('完整题目区域须为1–12个')
    details=detail_regions or []
    if not isinstance(details,list) or len(details)>4:raise ValueError('局部细节最多4个，按需提供')
    views=[]
    for role,items in [('question_view',regions),('detail_view',details)]:
        for index,item in enumerate(items):
            if not isinstance(item,dict) or item.get('page') not in (bundle.get('pages') or [1]):raise ValueError('视觉区域引用材料外页码')
            question=str(item.get('question','')).strip()
            if not question:raise ValueError('区域必须记录所属题号')
            view=render_region(folder,item['page'],item['box'],role)
            view.update(question=question,part=item.get('part',index+1),overlap=item.get('overlap',0),deduplication='same question + source page + overlapping source coordinates; never duplicate a stem or subquestion')
            views.append(view)
    result=dict(bundle,pages=bundle.get('pages') or [1],images=[v['path'] for v in views],vision_views=views,vision_version=VERSION,region_only=True,target_questions=list(dict.fromkeys(v['question'] for v in views if v['role']=='question_view')))
    result['assets']=list(dict.fromkeys(bundle.get('assets',[])+[v['asset'] for v in views if v['role']=='question_view']))
    # Supply only text intersecting the selected regions; do not leak adjacent answers.
    text=[]
    if (folder/'original.pdf').is_file():
        with fitz.open(folder/'original.pdf') as doc:
            for v in views:
                if v['role']=='question_view':
                    p=doc[v['page']-1]
                    if text_quality(p)['reliable']:text.append(p.get_text(clip=fitz.Rect(page_box_to_pdf(v,v['source_box']))))
    result['text']='\n'.join(text)
    return result

def write_input_manifest(bundle,taskdir,model):
    views={v['asset']:v for v in bundle.get('vision_views',[])}
    rows=[]
    for p in bundle.get('images',[]):
        row=image_info(p);view=views.get(Path(p).name)
        row.update(role=view['role'] if view else ('page_context' if Path(p).name.startswith('page-') else 'recognition_context'),provenance=view)
        rows.append(row)
    data=dict(version=VERSION,model=model,source_id=bundle.get('source_id'),stage='project-before-opencode',transport_observed=False,detail='not set by project',images=rows)
    (Path(taskdir)/'vision_input_manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    return data
