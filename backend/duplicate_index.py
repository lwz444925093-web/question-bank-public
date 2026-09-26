"""Local incremental representations + bounded inverted-index retrieval. No model calls."""
import collections,hashlib,json,math,threading,time
from . import store,similarity
_lock=threading.RLock()
_cache={}

def signature(q):
 # Include file stat changes, so replacing a crop invalidates its representation.
 from .export_images import image_path
 stats=[]
 def visit(v):
  if isinstance(v,dict):
   if v.get('kind')=='image':
    try:
     p=image_path(q.get('source'),v.get('asset',''));s=p.stat();stats.append((str(p),s.st_size,s.st_mtime_ns))
    except (OSError,ValueError):stats.append(('missing',v.get('asset')))
   for x in v.values():visit(x)
  elif isinstance(v,list):
   for x in v:visit(x)
 for field in ['stem','options','subquestions']:visit(q.get(field,[]))
 return hashlib.sha256(json.dumps([q,stats],sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def ignore_key(a,b,ra,rb):
 return 'similar-ignore-'+hashlib.sha256('|'.join(sorted([a['id']+ra['fingerprint'],b['id']+rb['fingerprint']])).encode()).hexdigest()

def dismiss(data):
 a=store.get('questions',data.get('left_id'));b=store.get('questions',data.get('right_id'))
 if not a or not b or a['revision']!=data.get('left_revision') or b['revision']!=data.get('right_revision'):raise ValueError('题目已变化，请重新检查')
 store.put('settings',ignore_key(a,b,similarity.representation(a),similarity.representation(b)),dict(ignored=True))
 return {'ok':True}

def scan(subject):
 start=time.perf_counter()
 with _lock:
  qs=sorted([q for q in store.all_rows('questions') if subject=='全部' or q.get('subject')==subject],key=lambda q:q['id'])
  reps=[];grams=[];hits=0
  active={q['id'] for q in store.all_rows('questions')}
  for key in list(_cache):
   if key not in active:del _cache[key]
  for q in qs:
   key=signature(q);cached=_cache.get(q['id'])
   if cached and cached[0]==key:r,g=cached[1:];hits+=1
   else:r=similarity.representation(q);g=similarity.tokens(r['text']);_cache[q['id']]=(key,r,g)
   reps.append(r);grams.append(g)
  exact=collections.defaultdict(list);postings=collections.defaultdict(list)
  for i,r in enumerate(reps):
   if not r['missing'] and r['meaningful'].strip():exact[r['fingerprint']].append(i)
   for g in grams[i]:postings[g].append(i)
  pairs=set();exact_pairs=set()
  # Represent an exact group as a spanning set, not a quadratic pair list.
  for group in exact.values():
   for j in group[1:]:exact_pairs.add((group[0],j))
  max_posting=max(10,min(100,int(math.sqrt(max(1,len(qs))))*2))
  for i,g in enumerate(grams):
   rare=sorted((x for x in g if 1<len(postings[x])<=max_posting),key=lambda x:(len(postings[x]),x))[:32]
   scores=collections.Counter(j for x in rare for j in postings[x] if j!=i)
   for j,_ in scores.most_common(40):
    if reps[i]['fingerprint']!=reps[j]['fingerprint'] or reps[i]['missing'] or reps[j]['missing']:pairs.add(tuple(sorted((i,j))))
  vectors=[{t:n*(math.log((len(qs)+1)/(len(postings[t])+1))+1) for t,n in g.items()} for g in grams]
  norms=[math.sqrt(sum(v*v for v in g.values())) for g in vectors]
  with store.conn() as c:
   ignored={r[0] for r in c.execute("SELECT id FROM settings WHERE id LIKE 'similar-ignore-%'")}
  results=[]
  for i,j in sorted(pairs|exact_pairs):
   r,s=reps[i],reps[j];den=norms[i]*norms[j];score=sum(v*vectors[j].get(t,0) for t,v in vectors[i].items())/den if den else 0
   if ignore_key(qs[i],qs[j],r,s) in ignored:continue
   is_exact=(i,j) in exact_pairs
   if not is_exact and score<.65:continue
   reasons=[]
   if r['images']!=s['images']:reasons.append('题图不同')
   if r['missing'] or s['missing']:reasons.append('题图缺失或归属未确认')
   if r['text']!=s['text']:reasons.append('正文、公式或选项存在差异')
   results.append(dict(left_id=qs[i]['id'],right_id=qs[j]['id'],exact=is_exact,score=round(score,3),kind='内容相同' if is_exact else '相似待核对',reason=reasons or ['文字与题图指纹相同']))
  results.sort(key=lambda r:(not r['exact'],-r['score'],r['left_id']))
  return dict(rows=results,questions=qs,total=len(qs),cache_hits=hits,comparisons=len(pairs|exact_pairs),seconds=round(time.perf_counter()-start,3),notice='相似检查采用有限候选检索，可能漏掉相似题；内容相同按完整指纹分组。')

def merge(data):
 from . import trash
 keep,drop=data.get('keep'),data.get('drop')
 if not keep or not drop or keep==drop:raise ValueError('请选择两道不同题目')
 with store.conn() as c:
  c.execute('BEGIN IMMEDIATE')
  for id,revision in [(keep,data.get('keep_revision')),(drop,data.get('drop_revision'))]:
   row=c.execute('SELECT body FROM questions WHERE id=?',(id,)).fetchone()
   if not row or c.execute('SELECT 1 FROM trash WHERE id=?',(id,)).fetchone() or json.loads(row['body'])['revision']!=revision:raise ValueError('题目已变化，请重新检查')
  now=time.time();c.execute('INSERT INTO trash VALUES(?,?,?)',(drop,now,now+trash.RETENTION))
 return {'kept_id':keep,'removed_id':drop}
