"""Render individual native Word drawings, never the source document or OLE."""
import copy,hashlib,io,json,os,posixpath,re,shutil,subprocess,tempfile,zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from lxml import etree
from PIL import Image,ImageChops
import fitz
from .docx_compat import PARSER

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
V='urn:schemas-microsoft-com:vml'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
SHAPES={'group','shape','rect','roundrect','oval','line','polyline','curve','arc'}
HEADINGS={'学习目标','思维导图','知识梳理','题型精讲','强化训练'}


def native_drawing(pict):
    if etree.QName(pict).localname!='pict':return False
    if pict.xpath('.//*[local-name()="group" or local-name()="textbox"]'):return True
    images=pict.xpath('.//*[local-name()="imagedata"]')
    return any(not any(i.get('{'+R+'}'+k) for k in ['id','embed','link']) for i in images) or (not images and any(etree.QName(n).namespace==V and etree.QName(n).localname in SHAPES for n in pict.iter()))


def drawing_text(pict):return pict.xpath('.//*[local-name()="txbxContent"]//*[local-name()="t"]/text()')


def section_heading(pict):
    # Only explicit source headings, allowing their decorative section digits.
    text=''.join(drawing_text(pict));words=re.sub(r'[\s0-9０-９]','',text)
    return words if words in HEADINGS else ''


def validate_drawing(pict,archive,relations):
    if pict.xpath('.//*[local-name()="OLEObject" or local-name()="object" or local-name()="altChunk" or local-name()="instrText" or local-name()="fldSimple"]'):
        raise ValueError('Word组合图含嵌入对象或动态字段，未执行转换')
    used={}
    for node in pict.iter():
        if not isinstance(node.tag,str):continue
        tag=etree.QName(node).localname
        for key,value in node.attrib.items():
            name=etree.QName(key).localname
            if name in ['src','href'] and value:raise ValueError('Word组合图含未嵌入资源，未读取外链')
            if key=='{'+R+'}link':raise ValueError('Word组合图含外链图片，无法完整读取')
            if etree.QName(key).namespace==R and name in ['id','embed']:
                rel=relations.get(value)
                if rel is None or not rel.get('Type','').endswith('/image') or rel.get('TargetMode')=='External':raise ValueError('Word图片关系缺失或外链图片，无法完整读取')
                target=unquote(rel.get('Target',''));media=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word',target))
                if not media.startswith('word/media/') or media not in archive.namelist():raise ValueError('Word图片文件缺失')
                used[value]=(rel,media)
        if tag=='imagedata' and not any(node.get('{'+R+'}'+k) for k in ['id','embed']):
            parent=node.getparent();kind=etree.QName(parent).localname
            picture_type=parent.get('type','').endswith('_t75') or parent.get('{urn:schemas-microsoft-com:office:office}spt')=='75'
            if kind not in SHAPES or picture_type:raise ValueError('Word图片关系缺失，未将缺失位图当作原生形状')
    return used


def explicit_geometry(drawing):
    """Resolve WPS's style-only line endpoints and VML's default stroke locally.

    LibreOffice drops v:line without from/to and treats the absent default
    stroke as a hairline. A straight path in the same bounding box preserves
    the stored transforms, flips, endpoints, arrows and dash settings.
    """
    for node in drawing.iter():
        if not isinstance(node.tag,str) or etree.QName(node).namespace!=V:continue
        kind=etree.QName(node).localname
        if kind=='line' and not node.get('from') and not node.get('to'):
            style=dict(part.split(':',1) for part in node.get('style','').split(';') if ':' in part)
            style={k.strip():v.strip() for k,v in style.items()}
            if not all(re.fullmatch(r'[0-9.]+',style.get(k,'')) for k in ['width','height']):raise ValueError('Word原生连线缺少可靠端点，未忽略连线')
            size=re.fullmatch(r'\s*([0-9.]+)[, ]+([0-9.]+)\s*',node.get('coordsize','21600,21600'))
            if not size:raise ValueError('Word原生连线坐标无法读取')
            node.tag='{'+V+'}shape';node.set('path','m0,0l'+size[1]+','+size[2]+'e');node.set('filled','f');kind='shape'
        if kind in SHAPES-{'group'} and not node.get('strokeweight') and not node.xpath('./v:stroke[@weight]',namespaces={'v':V}):
            # https://learn.microsoft.com/windows/win32/vml/msdn-online-vml-strokeweight-attribute
            node.set('strokeweight','1px')


def single_drawing_docx(pict,archive,relations):
    """Copy one complete drawing plus its styles and referenced media only."""
    used=validate_drawing(pict,archive,relations)
    root=etree.Element('{'+W+'}document',nsmap=pict.nsmap);body=etree.SubElement(root,'{'+W+'}body')
    paragraph=etree.SubElement(body,'{'+W+'}p');pr=etree.SubElement(paragraph,'{'+W+'}pPr')
    spacing=etree.SubElement(pr,'{'+W+'}spacing');spacing.set('{'+W+'}before','0');spacing.set('{'+W+'}after','0')
    run=etree.SubElement(paragraph,'{'+W+'}r');drawing=copy.deepcopy(pict);explicit_geometry(drawing);run.append(drawing)
    width=height=0
    for node in drawing:
        if etree.QName(node).namespace!=V or etree.QName(node).localname not in SHAPES:continue
        style=dict(part.split(':',1) for part in node.get('style','').split(';') if ':' in part)
        style={k.strip():v.strip() for k,v in style.items()}
        def length(key):
            match=re.fullmatch(r'([0-9.]+)(pt|in|cm|mm|px)',style.get(key,''))
            if not match:return 0
            return float(match[1])*{'pt':1,'in':72,'cm':72/2.54,'mm':72/25.4,'px':.75}[match[2]]
        width=max(width,length('width'));height=max(height,length('height'))
        # Source anchoring positions locate a group on the source page. Its
        # internal coordinate origin, child transforms and rotations stay intact.
        for key in list(style):
            if key in ['position','left','top','margin-left','margin-top'] or key.startswith('mso-position-'):style.pop(key)
        node.set('style',';'.join(k+':'+v for k,v in style.items())+';')
    if not width or not height or max(width,height)>1400:raise ValueError('Word组合图缺少可靠尺寸或尺寸过大，未裁掉图形')
    section=etree.SubElement(body,'{'+W+'}sectPr');size=etree.SubElement(section,'{'+W+'}pgSz')
    size.set('{'+W+'}w',str(round(max(612,width+144)*20)));size.set('{'+W+'}h',str(round(max(792,height+144)*20)))
    margin=etree.SubElement(section,'{'+W+'}pgMar')
    for key in ['top','right','bottom','left']:margin.set('{'+W+'}'+key,'720')
    parts={'word/document.xml':etree.tostring(root,encoding='UTF-8',xml_declaration=True)}
    relroot=etree.Element('{'+REL+'}Relationships',nsmap={None:REL})
    for rel,media in used.values():
        relroot.append(copy.deepcopy(rel));parts[media]=archive.read(media)
    for rid,rel in relations.items():
        if rel.get('Type','').rsplit('/',1)[-1] not in ['styles','numbering','fontTable','theme']:continue
        target=posixpath.normpath(posixpath.join('word',rel.get('Target','')))
        if target in archive.namelist():parts[target]=archive.read(target);relroot.append(copy.deepcopy(rel))
    parts['word/_rels/document.xml.rels']=etree.tostring(relroot,encoding='UTF-8',xml_declaration=True)
    package=etree.Element('{'+REL+'}Relationships',nsmap={None:REL})
    etree.SubElement(package,'{'+REL+'}Relationship',Id='rId1',Type=R+'/officeDocument',Target='word/document.xml')
    parts['_rels/.rels']=etree.tostring(package)
    types=etree.fromstring(archive.read('[Content_Types].xml'),PARSER())
    for item in list(types):
        if etree.QName(item).localname=='Override' and item.get('PartName','').lstrip('/') not in parts:types.remove(item)
    parts['[Content_Types].xml']=etree.tostring(types)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as dest:
        for name,data in parts.items():dest.writestr(name,data)
    return out.getvalue()


def render_drawings(items,archive,relations,folder):
    if not items:return []
    from .platform_runtime import soffice
    exe=soffice()
    if not exe:raise ValueError("此 Word 的旧公式或组合图需要 LibreOffice，请安装后重试")
    records=[];folder=Path(folder)
    with tempfile.TemporaryDirectory(prefix='word-native-drawings-') as tmp:
        tmp=Path(tmp);paths=[]
        for name,pict in items:
            src=tmp/(Path(name).stem+'.docx');src.write_bytes(single_drawing_docx(pict,archive,relations));paths.append(str(src))
        fonts=tmp/'fonts.conf';fonts.write_text('<fontconfig><dir>/System/Library/Fonts</dir><dir>/System/Library/Fonts/Supplemental</dir><dir>/Applications/Microsoft Word.app/Contents/Resources/DFonts</dir><cachedir>'+str(tmp/'cache')+'</cachedir><alias><family>宋体</family><prefer><family>Songti SC</family></prefer></alias><alias><family>微软雅黑</family><prefer><family>Heiti SC</family></prefer></alias></fontconfig>')
        result=subprocess.run([exe,'-env:UserInstallation='+(tmp/'profile').as_uri(),'--headless','--convert-to','pdf:writer_pdf_Export','--outdir',str(tmp),*paths],capture_output=True,timeout=180,env=(dict(os.environ) if os.name=='nt' else dict(os.environ,FONTCONFIG_FILE=str(fonts))))
        for name,pict in items:
            pdf=tmp/(Path(name).stem+'.pdf')
            if result.returncode or not pdf.is_file():raise ValueError('Word原生组合图未能完整渲染：'+name)
            with fitz.open(pdf) as doc:
                if len(doc)!=1:raise ValueError('Word独立组合图超出单页，未采用不完整图形：'+name)
                expected=Counter(re.sub(r'\s','', ''.join(drawing_text(pict))))
                actual=Counter(re.sub(r'\s','',doc[0].get_text()))
                if expected-actual:raise ValueError('Word组合图文字或标签未完整保留：'+name)
                raw=doc[0].get_pixmap(matrix=fitz.Matrix(4,4),alpha=False).tobytes('png')
            with Image.open(io.BytesIO(raw)) as im:
                rgb=im.convert('RGB');bbox=ImageChops.difference(rgb,Image.new('RGB',rgb.size,'white')).getbbox()
                if not bbox:raise ValueError('Word组合图渲染为空白，未丢弃：'+name)
                x0,y0,x1,y1=bbox;rgb.crop((max(0,x0-8),max(0,y0-8),min(rgb.width,x1+8),min(rgb.height,y1+8))).save(folder/name)
            records.append(dict(asset=name,source_xml_sha256=hashlib.sha256(etree.tostring(pict)).hexdigest(),text=drawing_text(pict),section_heading=section_heading(pict),route='isolated-native-drawing-to-png',all_source_text_retained=True))
    (folder/'native-drawing-manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    return records
