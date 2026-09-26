"""Native Word extraction. OLE is never executed; only embedded previews are read."""
import struct
import io, zipfile, subprocess, re, posixpath, tempfile, os, shutil, json, hashlib
from pathlib import Path
from urllib.parse import unquote
from lxml import etree
from PIL import Image, ImageChops
import pypandoc
from .docx_compat import sanitize, external_header_image_refs, PARSER
from .image_background import opaque_rgb
from . import store
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':R,'v':'urn:schemas-microsoft-com:vml'}

def normalize_symbol_charset(raw):
    """Honor the original symbol-font byte codes; DEFAULT_CHARSET corrupts them."""
    data=bytearray(raw)
    offset=(22 if data[:4]==bytes.fromhex('d7cdc69a') else 0)+18
    symbolic={b'Euclid Math One',b'Euclid Math Two',b'Euclid Extra',b'Euclid Symbol',b'MT Extra',b'MT Extra Tiger',b'Symbol',b'Symbol Tiger',b'Symbol Tiger Expert'}
    while offset+6<=len(data):
        words,kind=struct.unpack_from('<IH',data,offset)
        if words<3 or offset+2*words>len(data):break
        if kind==0x2fb and words>=28:
            face=bytes(data[offset+24:offset+2*words]).split(b'\0')[0]
            if face in symbolic:data[offset+19]=2
        offset+=words*2
    return bytes(data)

def convert_vectors(items, folder):
    """Convert only individual WMF/EMF assets, with no document rendering."""
    stamp=folder/'native-vector-fonts-v3.ok'
    missing=[(name,raw) for name,raw in items if not (folder/name).exists() or not stamp.exists()]
    if not missing:return
    from .platform_runtime import soffice
    exe=soffice()
    if not exe:raise ValueError("此 Word 的旧公式或组合图需要 LibreOffice，请安装后重试")
    with tempfile.TemporaryDirectory(prefix='word-assets-') as tmp:
        tmp=Path(tmp); paths=[]
        for name,raw in missing:
            # WMF and EMF are auto-detected by LibreOffice.
            src=tmp/(Path(name).stem+'.wmf');src.write_bytes(normalize_symbol_charset(raw));paths.append(str(src))
        font_config=etree.Element('fontconfig')
        for directory in ['/System/Library/Fonts','/System/Library/Fonts/Supplemental','/Applications/Microsoft Word.app/Contents/Resources/DFonts',str(store.DATA/'word-fonts')]:
            etree.SubElement(font_config,'dir').text=directory
        etree.SubElement(font_config,'cachedir').text=str(tmp/'cache')
        fonts=tmp/'fonts.conf';fonts.write_bytes(etree.tostring(font_config,encoding='utf-8'))
        proc=subprocess.run([exe,'-env:UserInstallation='+(tmp/'profile').as_uri(),'--headless','--convert-to','png:draw_png_Export:{"PixelWidth":{"type":"long","value":3000}}','--outdir',str(tmp),*paths],capture_output=True,timeout=180,env=(dict(os.environ) if os.name=='nt' else dict(os.environ,FONTCONFIG_FILE=str(fonts))))
        for name,_ in missing:
            rendered=tmp/name
            def content():
                if not rendered.exists():return None
                with Image.open(rendered) as im:
                    rgb=opaque_rgb(im);bbox=ImageChops.difference(rgb,Image.new('RGB',rgb.size,'white')).getbbox()
                    return (rgb,bbox) if bbox else None
            result=content()
            if result is None:
                # LibreOffice batch import sometimes emits an empty canvas for a
                # valid WMF. A fresh isolated document recovers its saved drawing.
                retry=tmp/('retry-'+Path(name).stem);retry.mkdir()
                subprocess.run([exe,'-env:UserInstallation='+(retry/'profile').as_uri(),'--headless','--convert-to','png','--outdir',str(retry),str(tmp/(Path(name).stem+'.wmf'))],capture_output=True,timeout=45,env=(dict(os.environ) if os.name=='nt' else dict(os.environ,FONTCONFIG_FILE=str(fonts))))
                rendered=retry/name;result=content()
            if result is None:raise ValueError('Word图片未能完整读取，原文件已保留：'+name)
            rgb,bbox=result;left,top,right,bottom=bbox
            rgb.crop((max(0,left-4),max(0,top-4),min(rgb.width,right+4),min(rgb.height,bottom+4))).save(folder/name)

    stamp.write_text('MathType symbol fonts and explicit symbol charset')

CACHE_VERSION='native-drawings-static-eq-v11'

def extract_docx(raw,path,folder):
    # Security validation is repeated even when the local extraction is cached.
    try:safe,legacy_count=sanitize(raw,ignore_external_header_images=True)
    except etree.XMLSyntaxError as exc:raise ValueError('Word内部 XML/OLE 结构损坏，请重新另存为 DOCX') from exc
    folder=Path(folder);cache=folder/'native-word-extraction.json'
    digest=hashlib.sha256(raw).hexdigest()
    try:
        saved=json.loads(cache.read_text())
        from .docx_fast import VERSION as PARSE_VERSION
        if saved.get('version')==CACHE_VERSION and saved.get('source_sha256')==digest and saved.get('result',{}).get('docx_local',{}).get('version')==PARSE_VERSION:
            result=saved['result']
            if set(saved['asset_hashes'])==set(result['assets']) and all((folder/name).is_file() and hashlib.sha256((folder/name).read_bytes()).hexdigest()==value for name,value in saved['asset_hashes'].items()):
                result['images']=[str(folder/name) for name in result['assets']]
                result['docx_extraction']['cached']=True
                return result
    except (OSError,ValueError,KeyError,TypeError):pass
    try:result=_extract_docx(raw,path,folder,safe,legacy_count)
    except KeyError as exc:raise ValueError('Word正文或资源文件缺失，请重新另存为 DOCX') from exc
    record=dict(version=CACHE_VERSION,source_sha256=digest,result=result,asset_hashes={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in result['assets']})
    with tempfile.NamedTemporaryFile(mode='w',dir=folder,prefix='native-word-',suffix='.tmp',delete=False) as stream:
        json.dump(record,stream,ensure_ascii=False);temporary=Path(stream.name)
    temporary.replace(cache)
    return result

def _extract_docx(raw,path,folder,safe,legacy_count):
    warnings=['DOCX无稳定物理页码，请对照原Word。']
    ignored_header_images=external_header_image_refs(raw)
    if ignored_header_images:warnings.append('页眉页脚中 '+str(sum(map(len,ignored_header_images.values())))+' 个外链图片未嵌入，已略过；正文与题图照常读取。')
    images=[];assets=[];media_map={};vectors=[];filtered=[];source_issues=[];inline_assets={}
    # Identify saved MathType equation previews before sanitizing away OLE.
    with zipfile.ZipFile(io.BytesIO(raw)) as original:
        original_root=etree.fromstring(original.read('word/document.xml'),PARSER())
        equation_ids={}
        for obj in original_root.xpath('//*[local-name()="object"]'):
            if not obj.xpath('.//*[local-name()="OLEObject" and (@ProgID="Equation.DSMT4" or @ProgID="Equation.3")]'):continue
            for image in obj.xpath('.//*[local-name()="imagedata"]'):
                style=image.getparent().get('style','')
                dimensions={k:float(v)*({'pt':1,'in':72,'cm':72/2.54,'mm':72/25.4}[unit]) for k,v,unit in re.findall(r'(width|height):\s*([0-9.]+)(pt|in|cm|mm)',style)}
                if not all(dimensions.get(k,0)>0 for k in ('width','height')):raise ValueError('旧公式缺少原始尺寸，未缩放或丢弃公式')
                equation_ids[image.get('{'+R+'}id')]=dimensions
    with zipfile.ZipFile(io.BytesIO(safe)) as z:
        root=etree.fromstring(z.read('word/document.xml'),PARSER())
        from .docx_fields import restore_eq_fields
        restored_fields=restore_eq_fields(root)
        rels=etree.fromstring(z.read('word/_rels/document.xml.rels'),PARSER()) if 'word/_rels/document.xml.rels' in z.namelist() else []
        by_id={r.get('Id'):r for r in rels}
        from .docx_vml import native_drawing,render_drawings,section_heading
        native_items=[];replacements=[];native_nodes=set()
        for pict in root.xpath('//*[local-name()="pict"][not(ancestor::*[local-name()="pict" or local-name()="drawing"])]'):
            if not native_drawing(pict):continue
            name='docx-native5-image-'+str(len(assets)+1)+'.png';index=len(assets)
            native_items.append((name,pict));assets.append(name);images.append(str(folder/name));native_nodes.update(pict.iter())
            heading=section_heading(pict)
            replacements.append((pict,(heading+' ' if heading else '')+'WORDASSET'+str(index)+'END'))
        native_records=render_drawings(native_items,z,by_id,folder)
        nodes=root.xpath('//a:blip | //v:imagedata',namespaces=NS)
        for node in nodes:
            if node in native_nodes:continue
            rid=node.get('{'+R+'}embed') or node.get('{'+R+'}id') or node.get('{'+R+'}link')
            rel=by_id.get(rid)
            if rel is None or not rel.get('Type','').endswith('/image') or rel.get('TargetMode')=='External':raise ValueError('Word图片关系缺失或外链图片，无法完整读取')
            target=unquote(rel.get('Target',''));media=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word',target))
            if not media.startswith('word/media/') or media not in z.namelist():raise ValueError('Word图片文件缺失')
            container=node
            while container.getparent() is not None and container.tag not in ['{'+W+'}drawing','{'+W+'}pict']:container=container.getparent()
            if container.tag not in ['{'+W+'}drawing','{'+W+'}pict']:raise ValueError('Word图片位置结构无法识别，未忽略图片')
            # Only explicit Office accessibility decoration flags permit dropping images.
            decorative=bool(container.xpath('.//*[local-name()="decorative" and (@val="1" or @val="true")]'))
            if decorative:filtered.append(media);replacements.append((container,''));continue
            # Some MathType objects are literal punctuation/Chinese characters.
            # Their embedded MathML is authoritative text, not OCR or a guess.
            embedded=re.search(rb'<math\b[\s\S]*?</math>',z.read(media)) if media.lower().endswith(('.wmf','.emf')) else None
            if embedded:
                math=etree.fromstring(embedded[0],PARSER())
                if len(math)==1 and etree.QName(math[0]).localname in ('mi','mo','mn') and len(math[0])==0 and math[0].text:
                    replacements.append((container,math[0].text));filtered.append(media);continue
            if media not in media_map:
                name='docx-native5-image-'+str(len(assets)+1)+'.png';media_map[media]=name;data=z.read(media)
                if media.lower().endswith(('.wmf','.emf')):vectors.append((name,data))
                else:
                    if media.lower().endswith('.svg'):
                        from .export_images import svg_png
                        data=svg_png(data)
                    with Image.open(io.BytesIO(data)) as im:
                        if im.width*im.height>30_000_000:raise ValueError('Word单张图片像素过大')
                        opaque_rgb(im).save(folder/name)
                assets.append(name);images.append(str(folder/name))
            index=assets.index(media_map[media])
            if rid in equation_ids:inline_assets[index]=dict(asset=media_map[media],**equation_ids[rid])
            replacements.append((container,'WORDASSET'+str(index)+'END'))
        convert_vectors(vectors,folder)
        # Replace image XML with text sentinels before Pandoc, including legacy VML.
        done=set()
        for container,marker in replacements:
            if container in done:raise ValueError('Word组合图片需要人工核对，未静默丢弃')
            done.add(container);text=etree.Element('{'+W+'}t');text.text=marker
            container.getparent().replace(container,text)
        if root.xpath('//*[local-name()="txbxContent"]'):source_issues.append('包含浮动文本框，需要核对阅读顺序')
        if root.xpath('//*[local-name()="chart" or local-name()="diagram" or local-name()="altChunk"]'):source_issues.append('包含图表或外部嵌入内容')
        if root.xpath('//*[local-name()="drawing" or local-name()="pict"]'):source_issues.append('包含尚未复制的 Word 绘图对象')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as out:
            for name in z.namelist():out.writestr(name,etree.tostring(root) if name=='word/document.xml' else z.read(name))
    with tempfile.TemporaryDirectory(prefix='word-text-') as tmp:
        src=Path(tmp)/'native.docx';src.write_bytes(stream.getvalue())
        proc=subprocess.run([pypandoc.get_pandoc_path(),str(src),'-f','docx','-t','json'],capture_output=True,timeout=30)
    if proc.returncode:raise ValueError('Word正文读取失败')
    ast=json.loads(proc.stdout)
    def restore_inline(value):
        if isinstance(value,list):
            result=[]
            for child in value:
                if isinstance(child,dict) and child.get('t')=='Str':
                    text=child['c'];cursor=0
                    for match in re.finditer(r'WORDASSET(\d+)END',text):
                        item=inline_assets.get(int(match[1]))
                        if not item:continue
                        if match.start()>cursor:result.append({'t':'Str','c':text[cursor:match.start()]})
                        result.append({'t':'Image','c':[['',[],[['data-native-equation','1'],['width',str(item['width'])],['height',str(item['height'])]]],[],[item['asset'],'']]})
                        cursor=match.end()
                    if cursor:
                        if cursor<len(text):result.append({'t':'Str','c':text[cursor:]})
                    else:result.append(child)
                else:result.append(restore_inline(child))
            return result
        if isinstance(value,dict):return {k:restore_inline(v) for k,v in value.items()}
        return value
    ast=restore_inline(ast)
    from .docx_fast import parse_ast
    local=parse_ast(ast,assets,legacy_previews=0 if inline_assets else legacy_count,source_issues=source_issues)
    markdown=subprocess.run([pypandoc.get_pandoc_path(),'-f','json','-t','markdown+tex_math_dollars','--wrap=none'],input=proc.stdout,capture_output=True,timeout=30)
    if markdown.returncode:raise ValueError('Word正文格式读取失败')
    text=markdown.stdout.decode()
    for i,asset in enumerate(assets):
        marker='WORDASSET'+str(i)+'END'
        if marker not in text:raise ValueError('Word图片位置丢失：'+asset)
        text=text.replace(marker,'![]('+asset+')')
    if legacy_count:warnings.append('旧公式按内嵌预览图片保留，未执行嵌入对象。')
    return dict(preview_ast=ast,text=text,images=images,assets=assets,source_warnings=warnings,native_docx=True,docx_local=local,docx_extraction=dict(version='native-assets-v4',legacy_previews=legacy_count,vector_images=len(vectors),native_drawings=len(native_records),native_drawing_records=native_records,static_eq_fields=restored_fields,ignored_header_images=ignored_header_images,filtered_decorations=len(filtered)))
