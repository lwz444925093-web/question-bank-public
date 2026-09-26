"""Isolated D delivery execution; production store is rejected before any write."""
import json,time,uuid,threading,hashlib
from pathlib import Path
from . import store,tasks
from .d_region_adapter import prepare_source,detect,asset_builder,check,dump
from .d_text_reader import read
from .d_delivery import assert_staging,recover,build,persist,VERSION
from .d_delivery_contract import PROMPT,Output
from .work_queue import pool,submission_lock
BLOCKED=threading.Event()

def submit(raw,name,subject,start=1,end=0):
 assert_staging()
 if subject not in ['数学','物理']:raise ValueError('unsupported_subject')
 if Path(name).suffix.lower() not in ['.pdf','.png','.jpg','.jpeg']:raise ValueError('D staging supports PDF/PNG/JPG')
 key=hashlib.sha256(raw+json.dumps([VERSION,subject,start,end]).encode()).hexdigest()
 with submission_lock:
  old=next((t for t in store.all_rows('tasks') if t.get('key')==key),None)
  if old:return old
  tid=uuid.uuid4().hex;folder=store.DATA/'tasks'/tid/'delivery';folder.mkdir(parents=True)
  source,pdf=prepare_source(raw,name,folder/'source',start,end)
  source.update(subject=subject,path=str(folder/'source'/source['original']),import_id=tid)
  record=dict(id=tid,key=key,mode='d_delivery_staging',version=VERSION,status='queued',created_at=time.time(),source=source,questions=[],pages=[],assets=[],errors=[],units=[],production_db_writes=0)
  dump(folder/'result.json',record)
  task=dict(id=tid,key=key,import_method='D',status='queued',created_at=record['created_at'],bundle=dict(source_id=source['source_id'],subject=subject,original=source['original'],display_name=name,pages=source['pages'],import_method='D'),question_ids=[],stage='D delivery staging 排队')
  store.put('tasks',tid,task);tasks.cancellations[tid]=store.TaskCancellation();pool.submit(run,tid);return task

def run(tid,reader=None):
 assert_staging();reader=reader or read;folder=store.DATA/'tasks'/tid/'delivery';record=json.loads((folder/'result.json').read_text());task=store.get('tasks',tid);cancel=tasks.cancellations[tid];started=time.time()
 def save():
  task['stage']=f"D staging：{len(record['pages'])} 页 / {len(record['questions'])} 题";dump(folder/'result.json',record);store.put('tasks',tid,task)
 try:
  check(cancel);task.update(status='running',started_at=started);record.update(status='running');save()
  source=record['source'];pdf=folder/'source'/('original.pdf' if source['original'].endswith('.pdf') else 'render-source.pdf');units=[]
  for p in source['pages']:
   check(cancel);pagefolder=folder/'regions'/str(p)
   result=detect(pdf,p,source['source_id'],pagefolder,cancel);page=result['page'];page['region_path']=str(pagefolder)
   # No hash/file/question registry and no nearby candidate import.
   assets=asset_builder(result['regions'],pagefolder)
   record['pages'].append(page);record['assets']+=assets;units.append((page,assets));save()
  while units:
   check(cancel);batch=[units.pop(0)]
   if units and units[0][0]['page']==batch[0][0]['page']+1:batch.append(units.pop(0))
   pages=[p['page'] for p,a in batch];assets=[a for p,aa in batch for a in aa];callfolder=folder/'calls'/('-'.join(map(str,pages)))
   material=dict(subject=source['subject'],source_pages=pages,pages=[dict(page=p['page'],original=p['original']) for p,a in batch],asset_catalog=[{k:a[k] for k in ['asset_id','asset_type','source_pages']} for a in assets])
   images=[Path(p['region_path'])/p['original'] for p,a in batch]+[Path(a['path']) for a in assets]
   try:
    if BLOCKED.is_set():raise ValueError('transport_blocked_no_automatic_retry')
    # Existing response is evidence, never silently overwrite or replay the network request.
    if (callfolder/'metrics.json').exists():raise ValueError('request_already_attempted_no_automatic_retry')
    raw,meta=reader(material,images,callfolder,cancel,prompt=PROMPT,schema=Output.model_json_schema())
    check(cancel);recovery=recover(raw);dump(callfolder/'recovery.json',recovery)
    result=build(recovery,assets,dict(source,import_id=tid+':'+','.join(map(str,pages))),pages,len(record['questions']))
    record['questions']+=result['questions'];record['units'].append(dict(pages=pages,recovery=recovery['status'],**{k:v for k,v in result.items() if k!='questions'}));save()
   except InterruptedError:raise
   except Exception as exc:
    record['errors'].append(dict(pages=pages,error=str(exc)))
    if any(x in str(exc) for x in ['http_401','http_402','http_403','transport_blocked']):BLOCKED.set();break
  check(cancel);persist(record,cancel);check(cancel)
  task.update(status='partial' if record['errors'] or any(u['recovery']=='unrecoverable' for u in record['units']) else 'succeeded',question_ids=[q['id'] for q in record['questions']],saved_count=len(record['questions']))
  record['status']=task['status']
 except Exception as exc:task.update(status='cancelled' if cancel.is_set() else 'failed',error=str(exc));record.update(status=task['status'],error=str(exc))
 finally:
  ms=[json.loads(p.read_text()) for p in (folder/'calls').glob('*/metrics.json')]
  metrics=dict(requests=sum(m.get('request_count',0) for m in ms),http_seconds=sum(m.get('http_seconds',0) for m in ms),wall_seconds=time.time()-started,locate=0,verify=0,recrop=0)
  for k in ['input_tokens','output_tokens','reasoning_tokens','cost_cny_estimate']:metrics[k]=sum(m[k] for m in ms) if ms and all(m.get(k)is not None for m in ms) else None
  record.update(metrics=metrics,finished_at=time.time(),counts={s:sum(q['delivery_status']==s for q in record['questions']) for s in ['usable','usable_with_cleanup','needs_content_review','incomplete']})
  task.update(d_metrics=metrics,finished_at=record['finished_at']);save()
