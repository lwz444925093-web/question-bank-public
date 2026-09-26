import hashlib,io,uuid
import fitz
from PIL import Image,ImageOps
from .store import DATA
from .image_background import opaque_rgb

def decode_text(raw):
    """Read common Chinese text encodings without replacing unreadable bytes."""
    error='文本编码无法识别，请另存为 UTF-8 格式的 TXT 后重新上传'
    if raw.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        encodings=['utf-32']
    elif raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        encodings=['utf-16']
    elif raw.startswith(b'\xef\xbb\xbf'):
        encodings=['utf-8-sig']
    else:
        encodings=['utf-8','gb18030']
    for encoding in encodings:
        try:text=raw.decode(encoding)
        except UnicodeDecodeError:continue
        if any(ord(ch)<32 and ch not in '\t\r\n' for ch in text):
            raise ValueError(error)
        return text
    raise ValueError(error)

def prepare(raw,name,start=1,end=0,selected_pages=None):
    if not raw: raise ValueError('文件为空')
    ext=name.rsplit('.',1)[-1].lower()
    if ext not in ['txt','pdf','png','jpg','jpeg','docx']: raise ValueError('仅支持 TXT、PDF、PNG、JPG、DOCX')
    digest=hashlib.sha256(raw).hexdigest(); folder=DATA/'sources'/digest; folder.mkdir(parents=True,exist_ok=True); path=folder/('original.'+ext)
    if not path.exists(): path.write_bytes(raw)
    bundle=dict(display_name=name,sha256=digest,source_id=digest,pages=[],text='',images=[],assets=[],original=path.name)
    if ext=='txt': bundle['text']=decode_text(raw)
    elif ext=='docx':
        from .docx_input import extract_docx
        bundle.update(extract_docx(raw,path,folder))
    elif ext=='pdf':
        pdf=fitz.open(stream=raw,filetype='pdf')
        if pdf.is_encrypted: raise ValueError('不支持加密PDF')
        if selected_pages is not None:
            if not isinstance(selected_pages,list) or not selected_pages or any(type(p) is not int or p<1 or p>len(pdf) for p in selected_pages):raise ValueError('物理页码范围无效')
            page_numbers=sorted(set(selected_pages))
        else:
            if end==0:end=len(pdf)
            if start<1 or end<start or end>len(pdf): raise ValueError('物理页码范围无效')
            page_numbers=range(start,end+1)
        from .pdf_inventory import inspect_pdf,verified_clean_page
        import json
        bundle['pdf_inventory']=inspect_pdf(pdf)
        (folder/'page-inventory.json').write_text(json.dumps(bundle['pdf_inventory'],ensure_ascii=False,indent=2))
        for n in page_numbers:
            page=pdf[n-1]; text=page.get_text(); bundle['pages'].append(n); bundle['text']+=f'\n【PDF页码{n}】\n'+text
            # One rendering per selected page retains math/layout and cross-page context; text is also supplied.
            target=folder/f'page-{n}.png'; page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(target); bundle['images'].append(str(verified_clean_page(folder,n) or target)); bundle['assets'].append(target.name)
        from .vision_inputs import text_quality,VERSION
        bundle['text_layer_quality']={str(n):text_quality(pdf[n-1]) for n in bundle['pages']}
        # Retain the page evidence, but do not send needless visual attachments for
        # a conservatively checked text-only source. Mixed/formula/scan stays visual.
        bundle['images']=[p for n,p in zip(bundle['pages'],bundle['images']) if not bundle['text_layer_quality'][str(n)]['text_only_safe']]
        bundle['vision_version']=VERSION
        pdf.close()
    else:
        im=Image.open(io.BytesIO(raw)); im.verify()
        im=Image.open(io.BytesIO(raw))
        if im.width*im.height>30_000_000: raise ValueError('图片像素过大')
        target=folder/'image.png'; opaque_rgb(ImageOps.exif_transpose(im)).save(target); bundle['images']=[str(target)]; bundle['assets']=['image.png']
    return bundle
