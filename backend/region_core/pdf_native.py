"""Local structural extraction only. No OCR, networking or project imports."""
import statistics
import fitz
from .model import area, union, coverage, plain
from .text_reliability import assess_text


def read_page(page, cfg):
    # Disabling image payload avoids duplicating decoded images in text extraction.
    raw = page.get_text('rawdict', flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
    objects, lines = [], []
    char_count = bad_count = 0
    for bi, block in enumerate(raw['blocks']):
        for li, line in enumerate(block.get('lines', [])):
            line_id = f'b{bi}-l{li}'
            refs = []
            for si, span in enumerate(line['spans']):
                chars = span.get('chars', [])
                # Preserve individual source characters; split spatially separate text
                # even if the producer put a vertex and prose in the same span.
                runs, run = [], []
                for ch in chars:
                    previous = next((c for c in reversed(run) if c['c'].strip()), None)
                    if previous and ch['c'].strip() and (gap_along(previous['bbox'], ch['bbox'], line['dir']) > span['size']*1.5):
                        runs.append(run); run = []
                    run.append(ch)
                if run:
                    runs.append(run)
                for ri, run in enumerate(runs):
                    visible = [c for c in run if c['c'].strip()]
                    text = ''.join(c['c'] for c in run).strip()
                    if not visible:
                        continue
                    oid = f'{line_id}-s{si}-r{ri}'
                    obj = dict(id=oid, kind='text', bbox=union(c['bbox'] for c in visible),
                               text=text, size=span['size'], font=span['font'], direction=line['dir'],
                               block=bi, line=line_id, span=si, chars=run, figure_refs=[])
                    objects.append(obj); refs.append(oid)
                    char_count += len(text)
                    bad_count += sum(ord(c)<32 or c=='\ufffd' or 0x80<=ord(c)<=0xbf for c in text)
            if refs:
                lines.append(dict(id=line_id, bbox=list(line['bbox']), spans=refs))
    sizes = [o['size'] for o in objects if len(o['text'])>8]
    em = statistics.median(sizes) if sizes else 10.0
    images = page.get_image_info(xrefs=True)
    for i, im in enumerate(images):
        objects.append(dict(id=f'image-{i}', kind='image', bbox=list(im['bbox']), instance_index=i, **{'image': plain(im)}))
    paths = page.get_drawings()
    for i, p in enumerate(paths):
        objects.append(dict(id=f'path-{i}', kind='path', bbox=list(p['rect']), path=plain(p)))
    if len(objects)>cfg['max_objects'] or sum(len(p['items']) for p in paths)>cfg['max_path_items']:
        raise ValueError('object_limit_exceeded: native object/path count exceeds configured budget')
    bounds = [0, 0, page.cropbox.width, page.cropbox.height]
    largest = max([area(x['bbox'])/area(bounds) for x in images] or [0])
    # Estimate union coverage, not a sum that double-counts repeated overlaps.
    image_area = rect_union_area([x['bbox'] for x in images])/area(bounds)
    bad_ratio = bad_count/max(char_count, 1)
    reasons = [f'{char_count} text characters; {len(images)} displayed image instances; {len(paths)} paths',
               f'image union coverage {image_area:.3f}; largest instance {largest:.3f}',
               f'suspicious/control character ratio {bad_ratio:.3f} (heuristic only)']
    if largest>.72 or image_area>.88:
        classification = 'raster_dominant'
        reasons.append('large raster coverage; any text may be an OCR overlay, not proof of native layout')
    elif char_count>=30 and bad_ratio<.08:
        classification = 'mixed' if image_area>.20 else 'native'
        reasons.append('usable text with localized images/paths; producer/OCR provenance cannot be proved')
    elif char_count or images or paths:
        classification = 'mixed' if images and char_count else 'uncertain'
        reasons.append('text encoding or sparse structures need visual inspection')
    else:
        classification = 'uncertain'; reasons.append('empty page')
    tables, table_error = [], None
    probe_doc = fitz.open()
    glyph_setting = bool(fitz.TOOLS.set_small_glyph_heights())
    try:
        # PyMuPDF 1.26.5 find_tables can change CropBox when restoring rotation.
        # Isolate it on a one-page in-memory copy and probe unrotated geometry.
        probe_doc.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        probe = probe_doc[0]
        probe.set_rotation(0)
        for i, t in enumerate(probe.find_tables().tables):
            cells = [list(c) for c in t.cells if c]
            interior = []
            for c in cells:
                inset=[c[0]+em*.4,c[1]+em*.4,c[2]-em*.4,c[3]-em*.4]
                interior.append(any(coverage(inset, o['bbox'])>.6 for o in objects if o['kind']=='text'))
            occupied = sum(interior)/max(1,len(cells))
            reliable = t.row_count>=2 and t.col_count>=2 and occupied>=.45
            tables.append(dict(id=f'table-{i}',kind='table_probe',bbox=list(t.bbox),cells=cells,
                               rows=t.row_count, columns=t.col_count, extracted_text=t.extract(),
                               interior_occupied_fraction=occupied, reliable=reliable,
                               reason='ruled cells plus interior text occupancy' if reliable else 'grid-like lines without enough cell-interior text; retain drawing'))
    except Exception as exc:
        table_error = str(exc)
    finally:
        fitz.TOOLS.set_small_glyph_heights(glyph_setting)
        probe_doc.close()
    return dict(text_reliability=assess_text(objects, largest>.72 and char_count>0), objects=plain(objects), lines=plain(lines), tables=tables, table_error=table_error,
                bounds=bounds, em=em, classification=classification, classification_reasons=reasons,
                text_characters=char_count, suspicious_character_ratio=bad_ratio,
                possible_ocr_overlay=largest>.72 and char_count>0,
                image_union_fraction=image_area, largest_image_fraction=largest)


def gap_along(a,b,d):
    return b[0]-a[2] if abs(d[0])>=abs(d[1]) else b[1]-a[3]


def rect_union_area(boxes):
    xs=sorted({x for b in boxes for x in (b[0],b[2])}); total=0
    for x0,x1 in zip(xs,xs[1:]):
        ys=sorted((b[1],b[3]) for b in boxes if b[0]<x1 and b[2]>x0)
        end=None; height=0
        for a,b in ys:
            if end is None or a>end: height+=b-a;end=b
            elif b>end: height+=b-end;end=b
        total+=(x1-x0)*height
    return total
