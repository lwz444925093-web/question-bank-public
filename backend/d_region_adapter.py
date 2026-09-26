"""Cancellable local Region analysis, fixed image authority, no model geometry."""
import hashlib,json,multiprocessing,time,shutil
from pathlib import Path
import fitz
from PIL import Image,ImageOps
from .region_core import model

VERSION='d-shadow-2'
def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(path)
def check(cancel):
    if cancel and cancel.is_set():raise InterruptedError('cancelled')
def page_worker(path,n,source,out):
    try:
        from .region_core.pdf_native import read_page
        core=Path(__file__).with_name('region_core');cfg=json.loads((core/'config.json').read_text())
        with fitz.open(path) as doc:data=read_page(doc[n-1],cfg)
        if data['classification']=='raster_dominant':
            from .region_core.raster_page import analyze_page
            cfg=json.loads((core/'raster_config.json').read_text())
        else:
            from .region_core.native_page import analyze_page
        page,regions=analyze_page(path,n,source,out,cfg,144)
        dump(Path(out)/'result.json',dict(page=page,regions=regions))
    except Exception as exc:dump(Path(out)/'result.json',dict(error=type(exc).__name__+': '+str(exc)))

def detect(path,n,source,out,cancel=None,timeout=60):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    proc=multiprocessing.get_context('spawn').Process(target=page_worker,args=(str(path),n,source,str(out)))
    start=time.monotonic();proc.start()
    try:
        while proc.is_alive():
            check(cancel)
            if time.monotonic()-start>timeout:raise TimeoutError('region_page_timeout')
            proc.join(.1)
        result=json.loads((out/'result.json').read_text())
        if 'error' in result:raise ValueError(result['error'])
        return result
    finally:
        if proc.is_alive():proc.terminate();proc.join(2)
        if proc.is_alive():proc.kill();proc.join()

def asset_builder(regions,folder,composites=()):
    """Only existing detected figure/table regions; never nearby text candidates."""
    folder=Path(folder);byid={r['region_id']:r for r in regions};groups=[];used=set()
    for ids in composites:
        if ids and all(i in byid and byid[i]['type'] in ['figure_candidate','unknown'] for i in ids) and any(byid[i]['type']=='figure_candidate' for i in ids):
            groups.append([byid[i] for i in ids]);used.update(ids)
    groups += [[r] for r in regions if r['type'] in ['figure_candidate','table'] and r['region_id'] not in used and not r.get('children') and r.get('visibility',{}).get('state')!='invisible']
    assets=[]
    for group in groups:
        # A crop can change while its source object IDs stay fixed. Include the
        # immutable crop bytes and composition coordinates so re-imports never
        # give new pixels an old asset name or overwrite historical versions.
        identity=[dict(region_id=r['region_id'],crop_sha256=hashlib.sha256((folder/r['crop']).read_bytes()).hexdigest(),
                       crop_pixel_bbox=r.get('crop_pixel_bbox')) for r in group]
        sig=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
        aid='asset-'+sig;target=folder/(aid+'.png')
        if len(group)==1:shutil.copy2(folder/group[0]['crop'],target)
        else:
            # Preserve relative positions and each fixed crop. Blank interstices
            # never import unapproved text pixels from the bounding union.
            boxes=[r['crop_pixel_bbox'] for r in group];box=model.union(boxes)
            canvas=Image.new('RGB',(round(box[2]-box[0]),round(box[3]-box[1])),'white')
            for r,b in zip(group,boxes):
                with Image.open(folder/r['crop']) as im:canvas.paste(im,(round(b[0]-box[0]),round(b[1]-box[1])))
            canvas.save(target)
        assets.append(dict(asset_id=aid,asset_type='table' if group[0]['type']=='table' else 'figure',asset=target.name,
            source_pages=sorted({r['page'] for r in group}),region_ids=[r['region_id'] for r in group],
            composite=len(group)>1,parent_ids=list(dict.fromkeys(r.get('parent_id') for r in group if r.get('parent_id'))),
            geometry=[{k:r.get(k) for k in ('region_id','safe_bbox','core_bbox','crop_pixel_bbox','page')} for r in group],
            warnings=list(dict.fromkeys(w for r in group for w in r.get('warnings',[]))),
            pixel_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),path=str(target)))
        if len(group)==1 and group[0].get('table_structure'):
            assets[-1]['table_structure']=dict(group[0]['table_structure'])
    return assets

def prepare_source(raw,name,folder,start=1,end=0):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);ext=Path(name).suffix.lower()
    if len(raw)>100*1024*1024 or not raw:raise ValueError('empty_or_oversize_input')
    if ext not in ['.pdf','.docx','.png','.jpg','.jpeg']:raise ValueError('unsupported_document_type')
    source=folder/('original'+ext);source.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest();meta=dict(source_id=digest,display_name=name,original=source.name,subject='数学')
    if ext=='.docx':
        from .docx_input import extract_docx
        native=extract_docx(raw,source,folder);dump(folder/'native-docx.json',native)
        return meta|dict(total_pages=None,pages=[],unsupported='unsupported_page: DOCX无可靠整页渲染，原生图片和表格文本保留供人工核对',native=native),None
    if ext!='.pdf':
        with Image.open(source) as im:
            if im.width*im.height>30_000_000:raise ValueError('image_pixel_limit')
            im=ImageOps.exif_transpose(im).convert('RGB');pdf=fitz.open();page=pdf.new_page(width=im.width/2,height=im.height/2)
            import io
            b=io.BytesIO();im.save(b,format='PNG');page.insert_image(page.rect,stream=b.getvalue());source=folder/'render-source.pdf';pdf.save(source);pdf.close()
    with fitz.open(source) as doc:
        if doc.needs_pass:raise ValueError('encrypted_pdf')
        total=len(doc);end=end or total
        if start<1 or end<start or end>total:raise ValueError('invalid_page_range')
    return meta|dict(total_pages=total,pages=list(range(start,end+1))),source
