"""Stable per-position figure identity; compatible with old image blocks."""
import hashlib,copy

def image_slots(q):
 records=q.get('figure_records',[]);result=[]
 groups=[('stem',q.get('stem',[]))]
 for field in ['options','subquestions']:
  groups.extend((field+'/'+str(i)+'/blocks',p['blocks']) for i,p in enumerate(q.get(field,[])))
 for prefix,blocks in groups:
  for i,b in enumerate(blocks):
   if b.get('kind')!='image':continue
   position=prefix+'/'+str(i)
   prior=next((r for r in records if r.get('position')==position and r.get('asset')==b['asset']),None)
   if prior is None:
    matches=[r for r in records if r.get('asset')==b['asset']]
    prior=matches[0] if len(matches)==1 else {}
   fid=prior.get('figure_id') or hashlib.sha256((q.get('id','draft')+'|'+position+'|'+b['asset']).encode()).hexdigest()[:20]
   result.append(dict(figure_id=fid,position=position,asset=b['asset'],state=prior.get('state','unverified')))
 return result

def block_at(q,position):
 path=position.split('/');value=q
 for key in path:value=value[int(key)] if isinstance(value,list) else value[key]
 return value

def reference_evidence(q,bundle):
 assets=bundle.get('assets',[]);original=bundle.get('original') or q.get('source',{}).get('file')
 pages=q.get('pages') or bundle.get('pages') or []
 if not pages:return [dict(page=None,asset=original,status='来源原件；定位待核对')]
 result=[dict(page=p,asset=('page-'+str(p)+'.png') if ('page-'+str(p)+'.png') in assets else (assets[0] if len(assets)==1 else original),status='定位待核对') for p in pages]
 result.extend(dict(page=v['page'],asset=v['asset'],role=v['role'],source_box=v['source_box'],part=v.get('part',1),overlap=v.get('overlap',0),status='识别上下文；非已核验题图') for v in bundle.get('vision_views',[]) if v.get('question')==q.get('original_number'))
 return result
