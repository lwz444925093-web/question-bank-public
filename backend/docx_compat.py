"""Read legacy equation previews, never activate OLE. Render a sanitized copy locally."""
import hashlib,io,json,os,posixpath,re,shutil,subprocess,tempfile,threading,zipfile
from pathlib import Path,PurePosixPath
from lxml import etree
import fitz
from . import store
VERSION='preview-pdf-v2'
_lock=threading.Lock()
PARSER=lambda:etree.XMLParser(resolve_entities=False,no_network=True)

def needed(raw):
 if not zipfile.is_zipfile(io.BytesIO(raw)):return False
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  return any(n.startswith('word/embeddings/') or n.lower().endswith(('.wmf','.emf')) for n in z.namelist())

def external_header_image_refs(raw):
 """References excluded from native body extraction; never resolve their URLs."""
 result={}
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  for name in z.namelist():
   if not re.fullmatch(r'word/_rels/(?:header|footer)\d+\.xml\.rels',name):continue
   ids=[r.get('Id') for r in etree.fromstring(z.read(name),PARSER()) if r.get('TargetMode')=='External' and r.get('Type','').endswith('/image')]
   if ids:result['word/'+name.rsplit('/',1)[1][:-5]]=ids
 return result

def sanitize(raw,ignore_external_header_images=False):
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  names=z.namelist()
  if sum(i.file_size for i in z.infolist())>250*1024*1024:raise ValueError('Word展开后过大')
  for n in names:
   if PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n:raise ValueError('DOCX内部路径不安全')
   if 'vbaproject' in n.lower():raise ValueError('不支持含宏的Word文件')
  changed={};count=0
  ignored=external_header_image_refs(raw) if ignore_external_header_images else {}
  # A DrawingML image can retain its original link alongside an embedded copy.
  # Ignore that link only when every use has an existing internal image payload.
  relationship='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
  for relname in names:
   if not relname.startswith('word/_rels/') or not relname.endswith('.xml.rels'):continue
   owner='word/'+relname.rsplit('/',1)[1][:-5]
   if owner not in names:continue
   rels={r.get('Id'):r for r in etree.fromstring(z.read(relname),PARSER())}
   xml=etree.fromstring(z.read(owner),PARSER())
   for rid,rel in rels.items():
    if rel.get('TargetMode')!='External' or not rel.get('Type','').endswith('/image'):continue
    uses=[el for el in xml.iter() if any(el.get(relationship+k)==rid for k in ('id','link','embed'))]
    def embedded_copy(el):
     local=rels.get(el.get(relationship+'embed'))
     if etree.QName(el).localname!='blip' or el.get(relationship+'link')!=rid or local is None:return False
     target=local.get('Target','')
     path=posixpath.normpath(posixpath.join(posixpath.dirname(owner),target))
     return local.get('TargetMode')!='External' and local.get('Type','').endswith('/image') and bool(target) and not target.startswith('/') and path in names and z.getinfo(path).file_size>0
    if uses and all(embedded_copy(el) for el in uses):ignored.setdefault(owner,[]).append(rid)
  for n in names:
   if n.endswith('.rels'):
    root=etree.fromstring(z.read(n),PARSER())
    for rel in list(root):
     header_image=rel.get('Id') in ignored.get('word/'+n.rsplit('/',1)[1][:-5],[]) and n.startswith('word/_rels/')
     if rel.get('TargetMode')=='External' and not rel.get('Type','').endswith('/hyperlink') and not header_image:raise ValueError('Word含外部资源，请先嵌入文档')
     if rel.get('Type','').endswith('/oleObject') or rel.get('TargetMode')=='External':root.remove(rel)
    changed[n]=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
   elif n.startswith('word/') and n.endswith('.xml'):
    root=etree.fromstring(z.read(n),PARSER())
    if n in ignored:
     relationship='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
     for image in root.xpath('//*[local-name()="blip" or local-name()="imagedata"]'):
      external=[key for key in ['id','link','embed'] if image.get(relationship+key) in ignored[n]]
      if not external:continue
      for key in external:image.attrib.pop(relationship+key,None)
      # Keep an embedded alternative when present; remove only the unavailable
      # external image node, never surrounding header text or other drawings.
      if not any(image.get(relationship+k) for k in ['id','link','embed']):image.getparent().remove(image)
    for obj in root.xpath('//*[local-name()="object"]'):
     oles=obj.xpath('.//*[local-name()="OLEObject"]')
     if not oles:continue
     if any(o.get('ProgID') not in ['Equation.DSMT4','Equation.3','PBrush'] for o in oles):raise ValueError('Word含未支持的嵌入对象，未执行转换')
     if not obj.xpath('.//*[local-name()="imagedata"]'):raise ValueError('旧公式缺少可见预览，无法保证完整转换')
     for o in oles:o.getparent().remove(o);count+=1
     obj.tag='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'
    changed[n]=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
   elif n=='[Content_Types].xml':
    root=etree.fromstring(z.read(n),PARSER())
    for item in list(root):
     if 'oleObject' in item.get('ContentType','') or item.get('PartName','').startswith('/word/embeddings/'):root.remove(item)
    changed[n]=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
  output=io.BytesIO()
  with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as out:
   for n in names:
    if not n.startswith('word/embeddings/'):out.writestr(n,changed.get(n,z.read(n)))
  return output.getvalue(),count

def convert(raw,name):
 sid=hashlib.sha256(raw).hexdigest();folder=store.DATA/'docx-compat'/sid/VERSION
 with _lock:
  folder.mkdir(parents=True,exist_ok=True);pdf=folder/'render.pdf';meta=folder/'conversion.json'
  if pdf.is_file() and meta.is_file():return pdf.read_bytes(),json.loads(meta.read_text())
  safe,count=sanitize(raw);(folder/'original.docx').write_bytes(raw)
  from .platform_runtime import soffice
  executable=soffice()
  if not executable:raise ValueError('旧公式Word需要本地LibreOffice转换，目前未安装')
  with tempfile.TemporaryDirectory(prefix='word-preview-') as tmp:
   tmp=Path(tmp);src=tmp/'render.docx';src.write_bytes(safe);profile=tmp/'profile'
   fonts=tmp/'fonts.conf'
   fonts.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/System/Library/Fonts</dir><dir>/System/Library/Fonts/Supplemental</dir><cachedir>'+str(tmp/'font-cache')+'</cachedir><alias><family>SimSun</family><prefer><family>Songti SC</family></prefer></alias><alias><family>宋体</family><prefer><family>Songti SC</family></prefer></alias><alias><family>Calibri</family><prefer><family>Arial</family></prefer></alias><alias><family>sans-serif</family><prefer><family>Arial Unicode MS</family></prefer></alias></fontconfig>')
   env=dict(os.environ) if os.name=='nt' else dict(os.environ,FONTCONFIG_FILE=str(fonts))
   proc=subprocess.run([executable,'-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','pdf:writer_pdf_Export','--outdir',str(tmp),str(src)],capture_output=True,timeout=180,env=env)
   rendered=tmp/'render.pdf'
   if proc.returncode or not rendered.is_file():raise ValueError('旧公式Word转换失败，未提交模型：'+proc.stderr.decode(errors='replace')[-300:])
   with fitz.open(rendered) as doc:
    if not len(doc):raise ValueError('Word转换未得到可用页面')
    info=dict(version=VERSION,source_sha256=sid,source_name=name,legacy_preview_count=count,pages=len(doc),route='saved-preview-to-pdf',notice='旧公式按原Word内嵌显示图保留，转换页码可能不同于Word。')
   shutil.copy2(rendered,pdf);meta.write_text(json.dumps(info,ensure_ascii=False,indent=2))
  return pdf.read_bytes(),info

def converted_source(raw,name):
 pdf,info=convert(raw,name)
 folder=store.DATA/'sources'/hashlib.sha256(pdf).hexdigest();folder.mkdir(parents=True,exist_ok=True)
 (folder/'original-upload.docx').write_bytes(raw)
 (folder/'word-conversion.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
 return pdf,Path(name).stem+'（Word兼容转换）.pdf',info
