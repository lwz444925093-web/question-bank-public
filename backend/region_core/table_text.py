"""Conservative native cell text; complex mathematical layouts stay visual."""
import re
import unicodedata


def native_text_cells(table, objects):
    rows=table.get('extracted_text') or []
    height,width=table['rows'],table['columns']
    cells=table.get('cells') or []
    if len(rows)!=height or any(len(row)!=width for row in rows) or len(cells)!=height*width:
        return None
    # A merged cell has no independent box and must never be flattened.
    boxes=sorted(cells,key=lambda b:(round(b[1],1),b[0]))
    result=[]
    for i,row in enumerate(rows):
        out=[]
        for j,value in enumerate(row):
            if value is None or '\n' in value or '\r' in value:return None
            if any(unicodedata.category(c) in ('Cc','Cf','Cs','Co') or c=='\ufffd' for c in value):return None
            box=boxes[i*width+j];chars=[];sizes=[]
            for obj in objects:
                if obj['kind']!='text':continue
                picked=[c for c in obj.get('chars',[]) if c['c'].strip() and box[0]<=sum(c['bbox'][::2])/2<=box[2] and box[1]<=sum(c['bbox'][1::2])/2<=box[3]]
                if not picked:continue
                if re.search('symbol|math|euclid|mtextra',obj.get('font',''),re.I):return None
                chars.extend(picked);sizes.append(obj['size'])
            # Baseline shifts can encode exponents/subscripts that plain text loses.
            origins=[c['origin'][1] for c in chars]
            if origins and max(origins)-min(origins)>max(sizes)*.18:return None
            source=''.join(c['c'] for c in sorted(chars,key=lambda c:c['bbox'][0]))
            if ''.join(source.split())!=''.join(value.split()):return None
            out.append(value.strip())
        result.append(out)
    return result
