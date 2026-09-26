"""Validated local image resolution and SVG export with a PNG compatibility image."""
import io,re,subprocess,shutil
from pathlib import Path
from functools import lru_cache
from PIL import Image
from docx.opc.part import Part
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree
from . import store

def image_path(source,asset):
    source_id=(source or {}).get('id','')
    if not re.fullmatch(r'[a-f0-9]{64}',source_id) or not asset or Path(asset).name!=asset or '\\' in asset or asset.startswith('.'):
        raise ValueError('图片来源或文件名无效：'+str(asset))
    folder=(store.DATA/'sources'/source_id).resolve();path=(folder/asset).resolve()
    if path.parent!=folder or not path.is_file():raise ValueError('图片素材缺失：'+asset)
    return path

@lru_cache(maxsize=64)
def svg_png(svg):
    from .diagrams import validate_svg
    svg=validate_svg(svg.decode())
    node=shutil.which('node')
    if not node:raise ValueError('SVG 导出需要 Node.js，请运行项目安装程序')
    p=subprocess.run([node,str(store.ROOT/'frontend/scripts/render-svg.mjs')],input=svg,capture_output=True,timeout=30)
    if p.returncode:raise ValueError('SVG 渲染失败，请检查项目图片依赖')
    return p.stdout

def image_data(source,asset):
    path=image_path(source,asset);raw=path.read_bytes();svg=raw if path.suffix.lower()=='.svg' else None
    if svg:raw=svg_png(svg)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            size=image.size
            if image.format not in ['PNG','JPEG']:
                result=io.BytesIO();image.convert('RGBA').save(result,format='PNG');raw=result.getvalue()
    except Exception as e:raise ValueError('图片无法读取：'+asset) from e
    return raw,size,svg

def add_image(paragraph,data,width_cm,height_cm):
    from docx.shared import Cm
    raw,size,svg=data
    drawing=paragraph.add_run().add_picture(io.BytesIO(raw),width=Cm(width_cm),height=Cm(height_cm))
    if svg:
        part=paragraph.part;package=part.package
        svgpart=Part(package.next_partname('/word/media/vector%d.svg'),'image/svg+xml',svg,package)
        rid=part.relate_to(svgpart,RT.IMAGE)
        blip=drawing._inline.xpath('.//a:blip')[0]
        extlist=etree.SubElement(blip,'{http://schemas.openxmlformats.org/drawingml/2006/main}extLst')
        ext=etree.SubElement(extlist,'{http://schemas.openxmlformats.org/drawingml/2006/main}ext',uri='{96DAC541-7B7A-43D3-8B79-37D633B846F1}')
        node=etree.SubElement(ext,'{http://schemas.microsoft.com/office/drawing/2016/SVG/main}svgBlip',nsmap={'asvg':'http://schemas.microsoft.com/office/drawing/2016/SVG/main'})
        node.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed',rid)
    return drawing
