"""Sequential single-read delivery; file-only execution, never production DB writes."""
import copy,hashlib,json,time,uuid
from pathlib import Path
from .d_region_adapter import prepare_source,detect,asset_builder,check,dump,VERSION as REGION_VERSION
from .d_text_reader import read
from .d_stream_contract import Output,Question,PROMPT,configuration
from .d_delivery import build
from .d_recovery import unique,repair_syntax,array_objects
VERSION='d-bank-4-carry-forward'

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def region_signature(source):
 root=Path(__file__).parent
 files=sorted((root/'region_core').glob('*.py'))+sorted((root/'region_core').glob('*.json'))+[root/'d_region_adapter.py',root/'d_locked_composites.json']
 return digest([source,REGION_VERSION,[(p.name,file_hash(p)) for p in files if p.exists()],144])

def cached_region(pdf,n,sid,folder,cancel,signature,detector):
 marker=folder/'cache.json'
 if marker.exists():
  try:
   cached=json.loads(marker.read_text())
   if cached['signature']==signature and all((folder/p).is_file() and file_hash(folder/p)==h for p,h in cached['files'].items()):
    return cached['page'],cached['assets'],True
  except (KeyError,ValueError,OSError):pass
 result=detector(pdf,n,sid,folder,cancel);page=result['page'];page['region_path']=str(folder)
 registry=Path(__file__).with_name('d_locked_composites.json')
 composites=(json.loads(registry.read_text()) if registry.exists() else {}).get(sid,{}).get(str(n),[])
 assets=asset_builder(result['regions'],folder,composites)
 files={page['original']:file_hash(folder/page['original'])}
 files.update({a['asset']:file_hash(a['path']) for a in assets})
 dump(marker,dict(signature=signature,page=page,assets=assets,files=files))
 return page,assets,False

def _compatible(output,generate_solution):
 # Local legacy metadata normalization, never an API retry.
 for q in output.get('questions',[]):
  meta=q.get('metadata')
  if isinstance(meta,dict) and 'difficulty' in meta:
   meta.setdefault('estimated_difficulty',meta.pop('difficulty'))
  if not generate_solution:
   if isinstance(meta,dict):meta.pop('common_mistakes',None)
   q['solution']={'status':'disabled'}
 return output

def recover(raw,generate_solution=True):
 _,output_model=configuration(generate_solution)
 repaired,edits=repair_syntax(raw)
 for status,text in [('raw_success',raw),('repaired',repaired)]:
  try:return dict(status=status,output=output_model.model_validate(_compatible(json.loads(text,object_pairs_hook=unique),generate_solution)).model_dump(),edits=[] if status=='raw_success' else edits)
  except ValueError:pass
 # Keep independently valid questions, never invent closure/checks.
 from .d_stream_contract import Transcription
 from .d_stream_contract import EstimatedMetadata,ImportMetadata,EvidenceSolution,DisabledSolution,EvidenceDelivery
 Metadata=EstimatedMetadata if generate_solution else ImportMetadata
 Solution=EvidenceSolution if generate_solution else DisabledSolution
 Delivery=EvidenceDelivery
 output=dict(questions=[],asset_assignments=[],page_extractions=[],issues=[])
 for original in array_objects(repaired,'questions'):
  original=_compatible(dict(questions=[original]),generate_solution)['questions'][0]
  try:q=Transcription.model_validate({k:v for k,v in original.items() if k not in ['metadata','solution','delivery_check','continuation_of','context_closed']}).model_dump()
  except ValueError:continue
  missing=[]
  for key,model in [('metadata',Metadata),('solution',Solution),('delivery_check',Delivery)]:
   try:q[key]=model.model_validate(original.get(key)).model_dump()
   except ValueError:q[key]=None;missing.append(key)
  cid=original.get('continuation_of')
  q.update(continuation_of=cid if isinstance(cid,str) else None,context_closed=original.get('context_closed') is True,_recovery_missing=missing)
  output['questions'].append(q)
 from .d_contract import Assignment,Page
 for key,model in [('asset_assignments',Assignment),('page_extractions',Page)]:
  for item in array_objects(repaired,key):
   try:output[key].append(model.model_validate(item).model_dump())
   except ValueError:pass
 return dict(status='partial' if output['questions'] else 'unrecoverable',output=output,edits=edits)

def compact(text):return ''.join(str(text).split())
def closure(q,incoming,current,assignments=(),assets=()):
 cid=q.get('continuation_of');prior=next((c for c in incoming if c['carry_id']==cid),None)
 pages=q['source_pages'];state=q['cross_page_status']
 if not q.get('context_closed') or state in ['starts_on_page_continues_next','cross_page_uncertain']:return False,'题目上下文尚未闭合'
 if state=='continues_from_previous' or cid:
  if not prior:return False,'续题缺少可匹配的前文'
  old=prior['question'];expected=sorted(set(old['source_pages']+[current]))
  if sorted(pages)!=expected or expected!=list(range(min(expected),max(expected)+1)):return False,'跨页来源不连续或缺失'
  if compact(old['question_text']) not in compact(q['question_text']):return False,'合并结果未完整保留前页题文'
  for field,label in [('options','label'),('subquestions','number')]:
   for part in old[field]:
    if not any(p[label]==part[label] and compact(part['text']) in compact(p['text']) for p in q[field]):return False,'合并结果未完整保留前页选项或小问'
  if prior.get('boundary_candidate'):
   from .d_boundary import has_new_content
   if not has_new_content(q,prior,current,assignments,assets):return False,'未发现可确认的下一页续接内容'
  return True,''
 if state!='complete_on_page' or pages!=[current]:return False,'单页题来源或闭合状态不一致'
 return True,''

def normalize_unchanged_carry(output,incoming):
 # Some responses repeat an unmatched carry verbatim with continuation_of=null.
 # Exact identity/content/source equality permits deduplication without guessing.
 for q in output['questions']:
  if q.get('continuation_of') or q.get('context_closed'):continue
  matches=[c for c in incoming if all(q.get(k)==c['question'].get(k) for k in ['question_id','source_pages','question_text','options','subquestions'])]
  if len(matches)==1:q['continuation_of']=matches[0]['carry_id']

def may_continue_forward(q,prior,current):
 if current not in q['source_pages']:return False
 if not prior and (q['cross_page_status']=='continues_from_previous' or (q['cross_page_status']=='cross_page_uncertain' and not q['question_text'].strip())):return False
 return True

def retain_missing_tail_figure(output,current,last_page):
 # A page-end reference to an absent source figure is unfinished context even
 # when the text alone is solvable. Do not treat damaged in-page crops this way.
 from .d_continuation_assets import source_figure_absent,TAIL_NOTE
 qs=output['questions']
 if not qs or current>=last_page:return
 q=qs[-1]
 attached=[a for a in output['asset_assignments'] if a['question_id']==q['question_id']]
 if q['source_pages']==[current] and q['requires_image'] and not attached and source_figure_absent(q):
  q.update(cross_page_status='starts_on_page_continues_next',context_closed=False)
  q['issues']=list(dict.fromkeys(q['issues']+[TAIL_NOTE]))

def dedupe_associated(output):
 qs={q['question_id']:q for q in output['questions']}
 for link in output['asset_assignments']:
  q=qs.get(link['question_id'])
  if not q:continue
  texts=[q['question_text']]+[x['text'] for k in ['options','subquestions'] for x in q[k]]
  corpus='\n'.join(compact(t) for t in texts);seen=set();kept=[]
  for text in link['associated_text']:
   key=compact(text)
   if key and key not in corpus and key not in seen:kept.append(text);seen.add(key)
  link['associated_text']=kept

def coverage(record):
 requested=record['source']['pages'];raw=[p for u in record['units'] for p in u.get('page_extractions',[])]
 pending={p for q in record['questions'] if q.get('continuation_status')=='pending_continuation' for p in q['source_pages']}
 unresolved={p for s in record.get('unresolved_segments',[]) for p in s['pages']};done=[];empty=[];states=[]
 for n in requested:
  rows=[p for p in raw if p['page']==n];status='incomplete';reason='没有唯一的原页识别完成记录'
  if len(rows)==1 and rows[0]['status'] in ['complete','no_questions']:
   if n in unresolved:reason='页段请求尚未完成'
   elif n in pending:reason='本页存在尚未闭合的跨页题'
   else:
    status=rows[0]['status'];reason='原页可见内容已完整读取，跨页上下文已闭合';done.append(n)
    if status=='no_questions':empty.append(n)
  elif len(rows)==1:reason=rows[0].get('reason') or '原页内容未完整提取'
  states.append(dict(page=n,status=status,reason=reason))
 return dict(basis='explicit-page-report-v1',completed_pages=done,empty_pages=empty,incomplete_pages=sorted(set(requested)-set(done)),pages=raw,effective_pages=states)

def metrics_for(folder):
 calls=[];reads={}
 for p in sorted((folder/'calls').glob('*/attempt-*/metrics.json')):
  m=json.loads(p.read_text());m['evidence_path']=str(p.relative_to(folder));calls.append(m)
  material=p.parent/'material.json'
  if material.exists():
   for page in json.loads(material.read_text()).get('pages',[]):reads[str(page['page'])]=reads.get(str(page['page']),0)+m.get('request_count',0)
 known=[m for m in calls if m.get('cost_cny_estimate') is not None]
 out=dict(requests=sum(m.get('request_count',0) for m in calls),http_seconds=sum(m.get('http_seconds',0) for m in calls),locate=0,verify=0,recrop=0,calls=calls,full_page_reads=reads,known_cost_cny=sum(m['cost_cny_estimate'] for m in known),unknown_cost_calls=len(calls)-len(known))
 for key in ['input_tokens','output_tokens','reasoning_tokens','cost_cny_estimate']:
  out[key]=sum(m[key] for m in calls) if calls and all(m.get(key) is not None for m in calls) else None
 return out

def run(record,raw,name,subject,start,end,cancel,folder,reader=None,on_update=None,selected_pages=None,retry_pages=(),detector=None,generate_solution=True,pure_d=False,light_review=False):
 if light_review:
  if generate_solution:raise ValueError('轻量审查导入不生成答案解析')
  pure_d=True
  from .d_light import PROMPT as prompt,Output as output_model,recover as recover_reply
 elif pure_d:
  from .d_pure import PROMPT as prompt,Output as output_model,recover as recover_reply
 else:
  prompt,output_model=configuration(generate_solution)
  recover_reply=lambda raw:recover(raw,generate_solution)
 schema=output_model.model_json_schema()
 folder=Path(folder);reader=reader or read;detector=detector or detect;started=time.time();current=None;incoming=[]
 resuming=any((folder/'calls').glob('*/attempt-*/boundary.json'))
 record.update(version=VERSION,status='running',questions=[],pages=[],assets=[],units=[],errors=[],unresolved_segments=[],region_cache_hits=0,generate_solution=generate_solution)
 def save():
  record['updated_at']=time.time();record['metrics']=metrics_for(folder);dump(folder/'result.json',record)
  if on_update:on_update(record)
 try:
  source,pdf=prepare_source(raw,name,folder/'source',start,end);source.update(subject=subject,import_id=record['id']);record['source']=source
  if selected_pages is not None:source['pages']=list(selected_pages)
  if not set(retry_pages)<=set(source['pages']):raise ValueError('重跑页段超出本任务范围')
  signature=region_signature(source['source_id']);units=[];save()
  for n in source['pages']:
   check(cancel);page,assets,reused=cached_region(pdf,n,source['source_id'],folder/'regions'/str(n),cancel,signature,detector)
   record['region_cache_hits']+=int(reused);record['pages'].append(page);record['assets']+=assets;units.append((page,assets));save()
  for page,assets in units:
   current=page['page'];check(cancel)
   if incoming and max(p for c in incoming for p in c['question']['source_pages'])!=current-1:
    incoming=[] # selected-page gaps never imply a continuation
   carried={a['asset_id']:a for c in incoming for a in c['assets']};all_assets=list({**carried,**{a['asset_id']:a for a in assets}}.values())
   material=dict(source_file=name,subject=subject,source_pages=[current],pages=[dict(page=current,original=page['original'],classification=page['classification'])],asset_catalog=[{k:v for k,v in a.items() if k not in ['path','warnings','geometry']} for a in all_assets],carry_forward=[{k:v for k,v in c.items() if k!='assets'} for c in incoming])
   images=[Path(page['region_path'])/page['original']]+[Path(a['path']) for a in all_assets]
   fingerprint=digest([VERSION,material,signature,prompt,schema,[file_hash(p) for p in images]])
   base=folder/'calls'/f'page-{current}';attempts=sorted(base.glob('attempt-*'));reuse=None;projection=None
   for a in reversed(attempts):
    boundary=a/'boundary.json'
    invalid=(a/'recovery.json').exists() and json.loads((a/'recovery.json').read_text()).get('status') in ['unrecoverable','partial']
    if invalid and current in retry_pages:continue
    if boundary.exists() and json.loads(boundary.read_text()).get('fingerprint')==fingerprint and (a/'raw.txt').exists():reuse=a;break
   if reuse is None:
    from .d_stream_replay import project
    registry={a['asset_id']:a for a in record['assets']}
    for a in reversed(attempts):
     if not all((a/f).exists() for f in ['raw.txt','material.json','boundary.json','prompt.txt','schema.json']):continue
     old=json.loads((a/'material.json').read_text());old.pop('request_context',None)
     if (a/'prompt.txt').read_text()!=prompt or json.loads((a/'schema.json').read_text())!=schema:continue
     try:old_hashes=[file_hash(images[0])]+[file_hash(registry[x['asset_id']]['path']) for x in old['asset_catalog']]
     except (KeyError,OSError):continue
     if digest([VERSION,old,signature,prompt,schema,old_hashes])!=json.loads((a/'boundary.json').read_text()).get('fingerprint'):continue
     recovered_old=recover_reply((a/'raw.txt').read_text())
     if recovered_old['status'] not in ['raw_success','repaired']:continue
     candidate=project(old,material,recovered_old['output'])
     if candidate is not None:reuse=a;projection=candidate;break
   if reuse:
    callfolder=reuse;raw_reply=json.dumps(projection['output'],ensure_ascii=False) if projection is not None else (reuse/'raw.txt').read_text()
    if projection is not None:dump(folder/'replays'/f'page-{current}.json',dict(source_call=str(reuse),**projection))
   else:
    if resuming and current not in retry_pages:
     record['unresolved_segments'].append(dict(pages=[current],state='unresolved' if attempts else 'not_requested',reason='该页段未完成或上下文已变化；需要显式选择重跑此页段',retry_allowed=True));incoming=[];continue
    callfolder=base/f'attempt-{len(attempts)+1:03d}';dump(callfolder/'boundary.json',dict(fingerprint=fingerprint,started_at=time.time(),page=current))
    material['request_context']=dict(retry=bool(attempts),retry_reason='用户显式重跑未完成页段' if attempts else None)
    dump(callfolder/'material.json',material)
    record['active_call']=dict(pages=[current],carry_count=len(incoming),started_at=time.time());save()
    try:raw_reply,meta=reader(material,images,callfolder,cancel,prompt=prompt,schema=schema)
    except BaseException as exc:
     record['unresolved_segments'].append(dict(pages=[current],state='unresolved',reason=type(exc).__name__+': '+str(exc),retry_allowed=True));raise
    if not (callfolder/'raw.txt').exists():(callfolder/'raw.txt').write_text(raw_reply)
    if not (callfolder/'metrics.json').exists():dump(callfolder/'metrics.json',meta)
   record.pop('active_call',None);check(cancel)
   recovered=recover_reply(raw_reply)
   if projection is None:dump(callfolder/'recovery.json',recovered)
   from .d_continuation_assets import join_numbered_orphan,retain_join_review
   output=copy.deepcopy(recovered['output']);normalize_unchanged_carry(output,incoming);join_numbered_orphan(output,incoming,all_assets,current);retain_missing_tail_figure(output,current,source['total_pages']);dedupe_associated(output)
   context_pages=sorted({current}|{p for c in incoming for p in c['question']['source_pages']})
   assembly=copy.deepcopy(recovered);assembly['output']=output;assembly['continuation_mode']=True;assembly['generate_solution']=generate_solution;assembly['pure_d']=pure_d;assembly['light_review']=light_review
   # The assembler sees source context pages, while coverage uses only actual visual page reports.
   assembly['output']['page_extractions']=[dict(page=p,status='complete',reason='assembly context only') for p in context_pages]
   built=build(assembly,all_assets,dict(source,import_id=record['id']+':page:'+str(current)),context_pages)
   returned=[];next_carry=[];tail_candidate=None
   occurrences={}
   for q,original in zip(built['questions'],output['questions']):
    local_id=original['question_id'];occurrences[local_id]=occurrences.get(local_id,0)+1
    q['id']=uuid.uuid5(uuid.NAMESPACE_URL,record['id']+':page:'+str(current)+':question:'+local_id+':'+str(occurrences[local_id])).hex;q['internal_question_id']=q['id']
    cid=original.get('continuation_of');prior=next((c for c in incoming if c['carry_id']==cid),None)
    matches=sum(x.get('continuation_of')==cid for x in output['questions']) if cid else 0
    closed,reason=closure(original,incoming,current,output['asset_assignments'],all_assets)
    if cid and matches!=1:closed=False;reason='同一续题被重复关联'
    if prior and matches==1:
     q['id']=prior['saved_id'];q['internal_question_id']=q['id'];returned.append(cid)
     record['questions']=[old for old in record['questions'] if old['id']!=q['id']]
    q['continuation_status']='closed' if closed else 'pending_continuation';q['context_closed']=closed;q['import_pipeline']=VERSION
    if not closed:
     q.update(draft_status='pending_continuation',delivery_status='pending_continuation',content_status='needs_review',review_status='pending',processing_status='review',solution_status='needs_review' if generate_solution else 'disabled')
     q['content_issues']=list(dict.fromkeys(q.get('content_issues',[])+[reason]));q['issues']=q['content_issues'];q['solution_issues']=['跨页上下文尚未闭合，答案不能作为最终结果']
     carry_id=prior['carry_id'] if prior else 'carry-'+q['id']
     links=[l for l in output['asset_assignments'] if l['question_id']==original['question_id']]
     refs={l['asset_id'] for l in links};attached=[a for a in all_assets if a['asset_id'] in refs]
     if may_continue_forward(original,prior,current):next_carry.append(dict(carry_id=carry_id,saved_id=q['id'],question=original,asset_assignments=links,assets=attached,source_state=dict(pages=original['source_pages'],context_closed=False,reason=reason)))
    retain_join_review(q,original)
    from .figure_workflow import sync
    sync(q)
    record['questions'].append(q)
    from .d_boundary import candidate
    tail_candidate=candidate(q,original,[l for l in output['asset_assignments'] if l['question_id']==original['question_id']],all_assets,current)
   from .d_boundary import flag_unmatched_boundary
   flag_unmatched_boundary(record,incoming,output,current,returned)
   for c in incoming:
    if c['carry_id'] not in returned and not c.get('boundary_candidate'):
     record['unresolved_segments'].append(dict(pages=[current],state='unresolved',reason='本页响应没有明确返回已提供的续题，原片段保留待审核',retry_allowed=True))
   if tail_candidate and current<source['pages'][-1]:next_carry.append(tail_candidate)
   incoming=list({c['carry_id']:c for c in next_carry}.values())
   reports=recovered['output']['page_extractions']
   if len(reports)!=1 or reports[0]['page']!=current:
    record['unresolved_segments'].append(dict(pages=[current],state='unresolved',reason='本页识别状态记录缺失或页码不一致',retry_allowed=True))
   if recovered['status']=='partial':
    record['errors'].append(dict(pages=[current],error='partial_schema_recovery',details='已保留有效题目，仍需核对遗漏内容'))
    record['unresolved_segments'].append(dict(pages=[current],state='unresolved',reason='部分响应结构无法恢复，需要核对本页是否漏题',retry_allowed=True))
   record['units'].append(dict(pages=[current],context_pages=context_pages,recovery=recovered['status'],assembly_errors=built['assembly_errors'],page_extractions=reports,carry_in=sum(not c.get('boundary_candidate') for c in material['carry_forward']),carry_out=sum(not c.get('boundary_candidate') for c in incoming),boundary_candidates_in=sum(bool(c.get('boundary_candidate')) for c in material['carry_forward']),boundary_candidates_out=sum(bool(c.get('boundary_candidate')) for c in incoming),closed_carry_ids=[c['carry_id'] for c in material['carry_forward'] if c['carry_id'] in returned and not any(n['carry_id']==c['carry_id'] for n in incoming)],request_reused=bool(reuse),cache_projection=projection is not None))
   if built['assembly_errors']:record['errors'].append(dict(pages=[current],error='assembly_validation',details=built['assembly_errors']))
   if recovered['status']=='unrecoverable':record['unresolved_segments'].append(dict(pages=[current],state='unresolved',reason='响应无法恢复有效题目',retry_allowed=True));break
   save()
 except InterruptedError:record['status']='cancelled'
 except Exception as exc:record.update(status='failed',error=type(exc).__name__+': '+str(exc))
 finally:
  record.pop('active_call',None)
  processed={p for u in record['units'] for p in u['pages']};unresolved={p for s in record['unresolved_segments'] for p in s['pages']}
  for p in record.get('source',{}).get('pages',[]):
   if p not in processed|unresolved:record['unresolved_segments'].append(dict(pages=[p],state='not_requested',reason='该页段尚未完成',retry_allowed=True))
  for segment in record['unresolved_segments']:segment['type']='unresolved_page_segment'
  record['page_extraction']=coverage(record) if record.get('source') else {}
  review=any(q.get('continuation_status')=='pending_continuation' or q.get('review_status')!='approved' or q.get('solution_status') not in ['ready','disabled'] for q in record['questions'])
  if record['status']=='running':record['status']='completed_with_review' if review or record['errors'] or record['page_extraction']['incomplete_pages'] else 'succeeded'
  record['counts']={s:sum(q['draft_status']==s for q in record['questions']) for s in ['ready','needs_review','incomplete','pending_continuation']}
  record['wall_seconds']=time.time()-started;record['finished_at']=time.time();save()
 return record
