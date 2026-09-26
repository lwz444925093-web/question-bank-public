"""Local n-gram retrieval. Scores are similarity, not probability or merge decisions."""
import collections,hashlib,json,math,re,unicodedata
from . import store
from .prefix_clean import preview
VERSION='char-ngrams-v1'
def representation(q):
 q=preview(q)['question'];parts=[];images=[];missing=False
 def block(b):
  nonlocal missing
  if b['kind']=='image':
   parts.append('[图槽]')
   from .export_images import image_path
   try:path=image_path(q.get('source'),b['asset'])
   except ValueError:missing=True;images.append('unknown');return
   trusted=not q.get('processing_status') or any(r.get('asset')==b['asset'] and r.get('state')=='verified' for r in q.get('figure_records',[]))
   if not path.is_file() or not trusted:missing=True;images.append('unknown');return
   images.append(hashlib.sha256(path.read_bytes()).hexdigest());return
  if b['kind']=='equation':parts.append(b['latex'])
  elif b['kind']=='table':parts.append('|'.join(''.join(s['text'] for s in cell) for row in b['rows'] for cell in row))
  elif b['kind']=='geometry':parts.append(json.dumps(b['shapes'],ensure_ascii=False,sort_keys=True))
  else:parts.append(''.join(s['text'] for s in b.get('spans',[])))
 for b in q.get('stem',[]):block(b)
 for field in ['options','subquestions']:
  for p in q.get(field,[]):
   parts.append(field+':'+p['label'])
   for b in p['blocks']:block(b)
 # Preserve quantities, polarity, units, formulas, tables and position/order of images.
 text=''.join(parts);text=unicodedata.normalize('NFC',text)
 text=re.sub(r'\s+','',text)
 meaningful=''.join(parts).replace('[图槽]','')
 if '如图' in meaningful and not images:missing=True
 fingerprint=hashlib.sha256(json.dumps([text,images],ensure_ascii=False).encode()).hexdigest()
 return dict(text=text,images=images,missing=missing,fingerprint=fingerprint,meaningful=meaningful)
def tokens(text):return collections.Counter(text[i:i+n] for n in [2,3] for i in range(max(0,len(text)-n+1)))
def compare(query,limit=5):
 rows=[q for q in store.all_rows('questions') if q['id']!=query['id'] and q.get('subject')==query.get('subject')]
 qr=representation(query);representations=[representation(q) for q in rows]
 if not qr['meaningful'].strip():return dict(status='unsupported',reason='仅图或无有效正文的题目暂不支持相似检索',candidates=[])
 counts=[tokens(qr['text'])]+[tokens(r['text']) for r in representations];df=collections.Counter()
 for c in counts:df.update(c.keys())
 vectors=[{t:n*(math.log((len(counts)+1)/(df[t]+1))+1) for t,n in c.items()} for c in counts]
 def cosine(a,b):
  denom=math.sqrt(sum(v*v for v in a.values())*sum(v*v for v in b.values()))
  return sum(v*b.get(t,0) for t,v in a.items())/denom if denom else 0
 candidates=[]
 for q,r,v in zip(rows,representations,vectors[1:]):
  key='similar-ignore-'+hashlib.sha256('|'.join(sorted([query['id']+qr['fingerprint'],q['id']+r['fingerprint']])).encode()).hexdigest()
  if store.get('settings',key):continue
  score=cosine(vectors[0],v)
  exact=qr['fingerprint']==r['fingerprint'] and not qr['missing'] and not r['missing']
  same_numeric_pattern=re.sub(r'\d+(?:\.\d+)?','#',qr['text'])==re.sub(r'\d+(?:\.\d+)?','#',r['text'])
  if not exact and score<0.65 and not same_numeric_pattern:continue
  diffs=[]
  if qr['images']!=r['images']:diffs.append('题图不同')
  if qr['missing'] or r['missing']:diffs.append('题图缺失或归属未确认，不能认定内容相同')
  numeric=re.findall(r'\d+(?:\.\d+)?',qr['text'])!=re.findall(r'\d+(?:\.\d+)?',r['text'])
  if numeric:diffs.append('数值不同')
  if qr['text']!=r['text']:diffs.append('正文/公式/选项/条件存在差异，请对照')
  candidates.append(dict(id=q['id'],original_number=q.get('original_number'),revision=q['revision'],score=round(score,3),kind='内容相同候选' if exact else ('可能变式' if numeric and (score>=.75 or same_numeric_pattern) else '相近表述'),reason=diffs or ['规范化内容与题图指纹相同，仍由你决定保留'],question=q,ignore_key=key))
 return dict(status='ready',version=VERSION,candidates=sorted(candidates,key=lambda c:(c['kind']=='内容相同候选',c['score']),reverse=True)[:limit],notice='分数表示文字相似程度，不是重复概率；不会自动合并或删除。')
