"""Native page detection and local immutable crops; no CLI or viewer."""
import argparse
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sys
import time
import traceback
import fitz
from PIL import Image, ImageDraw
from .model import area, plain, digest
from .pdf_native import read_page
from .grouping import group_page
from .raster_split import add_raster_regions

COLORS={'text':'#2563eb','figure_candidate':'#e43e42','table':'#109b63','unknown':'#86909c','raster_group':'#8b5fc8'}


def save_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def analyze_page(input_path, page_number, source_id, out, cfg, dpi):
    started=time.perf_counter(); out=Path(out)
    doc=fitz.open(input_path); page=doc[page_number-1]
    if page.rect.width*page.rect.height*(dpi/72)**2>cfg['max_render_pixels']:
        raise ValueError('render_pixel_limit_exceeded')
    data=read_page(page,cfg)
    regions=group_page(data,cfg,source_id,page_number)
    regions=add_raster_regions(page,data,regions,cfg,source_id,page_number)
    scale=dpi/72; matrix=fitz.Matrix(scale,scale)
    pix=page.get_pixmap(matrix=matrix,alpha=False)
    key=f'{source_id[:12]}-p{page_number}'
    for folder in ('pages','overlays','crops','objects'):(out/folder).mkdir(exist_ok=True,parents=True)
    pix.save(str(out/'pages'/f'{key}.png'))
    def pixel_box(b):
        rect=fitz.Rect(b)*page.rotation_matrix*matrix
        return [rect.x0-pix.x,rect.y0-pix.y,rect.x1-pix.x,rect.y1-pix.y]
    overlay=Image.open(out/'pages'/f'{key}.png').convert('RGB'); draw=ImageDraw.Draw(overlay)
    for i,r in enumerate(regions):
        r['core_pixel_bbox']=pixel_box(r['core_bbox']);r['safe_pixel_bbox']=pixel_box(r['safe_bbox'])
        crop=page.get_pixmap(matrix=matrix,clip=fitz.Rect(r['safe_bbox'])*page.rotation_matrix,alpha=False)
        name=f"{source_id[:12]}-{r['region_id']}.png"
        crop.save(str(out/'crops'/name));r['crop']='crops/'+name
        r['crop_pixel_bbox']=[crop.x-pix.x,crop.y-pix.y,crop.x-pix.x+crop.width,crop.y-pix.y+crop.height]
        r['crop_size']=[crop.width,crop.height]
        r['safe_area_fraction']=area(r['safe_bbox'])/area(data['bounds'])
        r['page_key']=key
        b=r['safe_pixel_bbox'];draw.rectangle(b,outline=COLORS[r['type']],width=2)
        # Labels go outside the region where possible; original page remains intact.
        draw.text((b[0],max(0,b[1]-12)),str(i+1),fill=COLORS[r['type']])
    overlay.save(out/'overlays'/f'{key}.png')
    save_json(out/'objects'/f'{key}.json',data)
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform!='darwin':peak*=1024
    meta=dict(page_key=key,source_id=source_id,page=page_number,
              native_size=[page.cropbox.width,page.cropbox.height],rotation=page.rotation,
              cropbox=list(page.cropbox),mediabox=list(page.mediabox),cropbox_position=list(page.cropbox_position),
              render_size=[pix.width,pix.height],dpi=dpi,render_origin=[pix.x,pix.y],
              coordinates={'core_safe':'MuPDF unrotated CropBox-relative points, top-left origin; 72 pt/inch',
                           'pixel_bbox':'rotated displayed page pixels, top-left origin',
                           'pdf_to_mupdf_matrix':list(page.transformation_matrix),
                           'unrotated_to_rotated_matrix':list(page.rotation_matrix),
                           'unrotated_to_pixel_matrix':list(page.rotation_matrix*matrix),
                           'pixel_offset':[-pix.x,-pix.y],
                           'rounding':'crop uses MuPDF outward integer device bounds; crop_pixel_bbox is authoritative'},
              text_reliability=data['text_reliability'],classification=data['classification'],classification_reasons=data['classification_reasons'],
              possible_ocr_overlay=data['possible_ocr_overlay'],suspicious_character_ratio=data['suspicious_character_ratio'],
              text_characters=data['text_characters'],object_count=len(data['objects']),
              object_counts={k:sum(o['kind']==k for o in data['objects']) for k in ('text','image','path')},
              table_probes=data['tables'],table_error=data['table_error'],
              original=f'pages/{key}.png',overlay=f'overlays/{key}.png',objects=f'objects/{key}.json',
              region_counts={k:sum(r['type']==k for r in regions) for k in COLORS},
              figure_area_sum=sum(r['safe_area_fraction'] for r in regions if r['type']=='figure_candidate'),
              alternative_count=0,elapsed_seconds=time.perf_counter()-started,worker_peak_rss_bytes=peak)
    return meta,regions

