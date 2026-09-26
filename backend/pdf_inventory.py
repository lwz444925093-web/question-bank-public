"""Inspect pages without silently discarding unidentified overlays."""
import json
from pathlib import Path
import fitz

def inspect_pdf(pdf):
    pages=[]
    for index,page in enumerate(pdf):
        text=page.get_text().strip()
        images=[]
        for image in page.get_images(full=True):
            images.append(dict(xref=image[0],width=image[2],height=image[3],rects=[list(r) for r in page.get_image_rects(image[0])]))
        pages.append(dict(page=index+1,width=page.rect.width,height=page.rect.height,text_characters=len(text),kind='文字或混合' if text else '扫描或图形',images=images))
    return dict(page_count=len(pdf),pages=pages)

def verified_clean_page(folder,page_number):
    manifest=Path(folder)/'verified-clean-pages.json'
    if not manifest.exists():return None
    data=json.loads(manifest.read_text())
    record=data.get(str(page_number))
    if not record or not record.get('verified'):return None
    asset=record['asset']
    if Path(asset).name!=asset:return None
    path=Path(folder)/asset
    return path if path.is_file() else None
