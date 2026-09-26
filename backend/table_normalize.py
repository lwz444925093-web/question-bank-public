"""Recover explicit tab/Markdown tables without guessing column boundaries."""
import copy,re

def cells(block):
 if block.get('kind')!='paragraph':return None
 spans=block.get('spans',[])
 if not any(s.get('kind')=='text' and '\t' in s.get('text','') for s in spans):return None
 result=[[]]
 for span in spans:
  parts=span.get('text','').split('\t') if span.get('kind')=='text' else [span.get('text','')]
  for i,text in enumerate(parts):
   if i:result.append([])
   if text:result[-1].append(dict(span,text=text))
 return result

def markdown_cells(block):
 """Require outer pipes; math spans and escaped literal pipes stay in cells."""
 if block.get('kind')!='paragraph':return None
 spans=block.get('spans',[])
 if not spans or spans[0].get('kind')!='text' or spans[-1].get('kind')!='text':return None
 if not spans[0].get('text','').lstrip().startswith('|') or not spans[-1].get('text','').rstrip().endswith('|'):return None
 result=[[]]
 for span in spans:
  if span.get('kind')!='text':result[-1].append(dict(span));continue
  text=span.get('text','');start=0
  for match in re.finditer(r'(?<!\\)\|',text):
   if match.start()>start:result[-1].append(dict(span,text=text[start:match.start()].replace('\\|','|')))
   result.append([]);start=match.end()
  if start<len(text):result[-1].append(dict(span,text=text[start:].replace('\\|','|')))
 if any(s.get('text','').strip() for c in (result[0],result[-1]) for s in c):return None
 rows=result[1:-1]
 for cell in rows:
  if cell and cell[0].get('kind')=='text':cell[0]['text']=cell[0]['text'].lstrip()
  if cell and cell[-1].get('kind')=='text':cell[-1]['text']=cell[-1]['text'].rstrip()
  cell[:]=[s for s in cell if s.get('text')]
 return rows if len(rows)>=2 else None

def separator(row):
 return bool(row) and all(re.fullmatch(r':?-{3,}:?', ''.join(s['text'] for s in cell)) and all(s['kind']=='text' for s in cell) for cell in row)

def table_key(rows):
 return tuple(tuple(''.join(''.join(s.get('text','').split()) for s in cell) for cell in row) for row in rows)

def remove_adjacent_native_transcription(blocks,refs):
 """Remove a complete literal Markdown copy only beside its verified table."""
 def exact(rows):
  # Formatting padding is ignorable; whitespace inside a cell is content.
  return tuple(tuple(''.join(s.get('text','') for s in cell).strip() for cell in row) for row in rows)
 proven=set()
 for ref in refs:
  structure=ref.get('table_structure') or {}
  if ref.get('asset_type')!='table' or structure.get('text_authority') not in ('verified_native_cells','verified_source_cells'):continue
  values=structure.get('text_cells')
  if not values or len(values)!=structure.get('rows') or any(len(row)!=structure.get('columns') for row in values):continue
  if any(not isinstance(value,str) for row in values for value in row):continue
  proven.add(tuple(tuple(value.strip() for value in row) for row in values))
 changed=False;i=0
 while i<len(blocks):
  block=blocks[i]
  if block.get('kind')!='table' or exact(block.get('rows',[])) not in proven:i+=1;continue
  start=i
  while start and markdown_cells(blocks[start-1]) is not None:start-=1
  rows=[markdown_cells(b) for b in blocks[start:i]]
  if len(rows)>=2 and exact(rows)==exact(block['rows']):
   del blocks[start:i];changed=True;i=start
  i+=1
 return changed

def match_native_rows(candidate,expected):
 """Remove only blank edge columns proven extra by exact native cell content."""
 if len(candidate)!=len(expected) or not expected:return None
 width=len(expected[0])
 if not candidate or len({len(row) for row in candidate})!=1:return None
 rows=[list(row) for row in candidate]
 while len(rows[0])>width and all(not table_key([row])[0][0] for row in rows):
  rows=[row[1:] for row in rows]
 while len(rows[0])>width and all(not table_key([row])[0][-1] for row in rows):
  rows=[row[:-1] for row in rows]
 return rows if table_key(rows)==table_key(expected) else None

def asset_tables(q,groups):
 """Use reliable native cells, or remove a table image's exact transcription copy.

 The asset and its source geometry remain in asset_refs for comparison. No image
 is removed on dimensions alone, or when its text differs from the editable table.
 """
 refs={a['asset']:a for a in q.get('asset_refs',[]) if a.get('asset_type')=='table'}
 changed=False;removed=set()
 for blocks in groups:
  for block in list(blocks):
   if block.get('kind')!='image' or block.get('asset') not in refs:continue
   ref=refs[block['asset']];structure=ref.get('table_structure') or {};native=structure.get('text_authority') in ('verified_native_cells','verified_source_cells')
   expected=structure.get('text_cells') if native else None
   if expected is not None:
    rows=[[[dict(kind='text',text=value)] if value else [] for value in row] for row in expected]
   else:
    # associated_text is explicitly attached to this asset by the transcription;
    # normalize only its complete tabular rows, never infer from nearby prose.
    from .d_assembler import text_blocks
    associated=[b for text in ref.get('associated_text',[]) for b in text_blocks(text)]
    probe={'stem':associated};normalize(probe)
    tables=[b for b in probe['stem'] if b.get('kind')=='table']
    if len(tables)!=1 or len(probe['stem'])!=1:continue
    rows=tables[0]['rows']
   if len(rows)!=structure.get('rows') or any(len(r)!=structure.get('columns') for r in rows):continue
   if native:
    for candidate in blocks:
     if candidate.get('kind')!='table':continue
     matched=match_native_rows(candidate['rows'],rows)
     if matched is not None:candidate['rows']=matched
   matching=[b for b in blocks if b.get('kind')=='table' and table_key(b['rows'])==table_key(rows)]
   if matching:
    blocks.remove(block)
   elif native and not any(b.get('kind')=='table' for b in blocks):
    block.clear();block.update(kind='table',rows=copy.deepcopy(rows),spans=[],latex='',shapes=[],asset='')
   else:continue
   asset=ref['asset'];removed.add(asset);changed=True
   ref['editable_table']=dict(basis=structure['text_authority'] if native else 'exact_associated_text',rows=copy.deepcopy(rows))
 if removed:q['figure_records']=[r for r in q.get('figure_records',[]) if r.get('asset') not in removed]
 return changed

def normalize(q):
 # Keep positions tied to block identity when paragraph runs collapse into tables.
 from .figure_state import image_slots,block_at
 bindings=[(block_at(q,s['position']),r) for s in image_slots(q) for r in q.get('figure_records',[]) if r.get('position')==s['position']]
 groups=[q.get('stem',[])]+[p.get('blocks',[]) for key in ('options','subquestions') for p in q.get(key,[])]
 changed=False
 for blocks in groups:
  from .probability_table import normalize_probability_tables
  if normalize_probability_tables(blocks):changed=True
  i=0
  while i<len(blocks):
   row=cells(blocks[i])
   markdown=False
   if not row:
    row=markdown_cells(blocks[i])
    markdown=bool(row and i+1<len(blocks) and separator(markdown_cells(blocks[i+1])))
    if not markdown:i+=1;continue
   end=i+1;rows=[row]
   parser=markdown_cells if markdown else cells
   while end<len(blocks) and (next_row:=parser(blocks[end])) is not None:
    rows.append(next_row);end+=1
   if markdown:
    if len(rows)<3 or len(rows[1])!=len(row):i=end;continue
    rows.pop(1)
   if len(rows)>=2 and len(row)>=2 and all(len(r)==len(row) for r in rows):
    blocks[i:end]=[dict(kind='table',rows=rows,spans=[],latex='',shapes=[],asset='')];changed=True;i+=1
   else:i=end
 if changed:
  positions={id(block_at(q,s['position'])):s['position'] for s in image_slots(q)}
  for block,record in bindings:
   if id(block) in positions:record['position']=positions[id(block)]
 if asset_tables(q,groups):
  changed=True
  positions={id(block_at(q,s['position'])):s['position'] for s in image_slots(q)}
  for block,record in bindings:
   if id(block) in positions:record['position']=positions[id(block)]
 if any([remove_adjacent_native_transcription(blocks,q.get('asset_refs',[])) for blocks in groups]):
  changed=True
  positions={id(block_at(q,s['position'])):s['position'] for s in image_slots(q)}
  for block,record in bindings:
   if id(block) in positions:record['position']=positions[id(block)]
 return changed
