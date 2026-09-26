"""Delivery-based adapter; used only by the isolated staging service/benchmark."""
import copy,json,hashlib,time
from pathlib import Path
from . import d_delivery_contract as contract
from .d_contract import Question as BaseQuestion,Assignment,Page
from .d_recovery import unique,repair_syntax,array_objects
from .d_assembler import assemble,text_blocks,cross_page_guard
from .d_region_adapter import check
VERSION='d-delivery-1'
MINOR={'minor_whitespace','minor_repeated_text','minor_neighbor_content','minor_layout'}
SUBSTANTIVE={'missing_condition','incorrect_text','missing_option','missing_asset','wrong_assignment','image_text_conflict','missing_critical_label','missing_image_structure','missing_table_information','ambiguous_neighbor_content','cross_page_missing_context','source_problem'}

def recover(raw):
 repaired,edits=repair_syntax(raw);errors=[]
 for label,text in [('raw_success',raw),('repaired',repaired)]:
  try:return dict(status=label,output=contract.Output.model_validate(json.loads(text,object_pairs_hook=unique)).model_dump(),edits=[] if label=='raw_success' else edits)
  except ValueError as exc:errors.append(str(exc)[:700])
 # Recover each section independently; invalid solutions never delete valid transcription.
 output=dict(questions=[],asset_assignments=[],page_extractions=[],issues=[])
 for original in array_objects(repaired,'questions'):
  try:
   base=BaseQuestion.model_validate({k:v for k,v in original.items() if k not in ['metadata','solution','delivery_check']}).model_dump()
  except ValueError:continue
  missing=[]
  for key,model in [('metadata',contract.Metadata),('solution',contract.Solution),('delivery_check',contract.Delivery)]:
   try:base[key]=model.model_validate(original.get(key)).model_dump()
   except ValueError:base[key]=None;missing.append(key)
  base['_recovery_missing']=missing;output['questions'].append(base)
 for key,model in [('asset_assignments',Assignment),('page_extractions',Page)]:
  for value in array_objects(repaired,key):
   try:output[key].append(model.model_validate(value).model_dump())
   except ValueError:pass
 return dict(status='partial' if output['questions'] else 'unrecoverable',output=output,edits=edits,errors=errors)

def decide(q,local_issues):
 facts=q.get('delivery_check');blocks=list(local_issues);missing=[];cleanup=[]
 if not q['question_text'].strip():missing.append('missing_question_text')
 if not facts:blocks.append('delivery_check_unavailable')
 else:
  for issue in facts['issues']:
   if issue['code'] in SUBSTANTIVE:
    (missing if issue['severity']=='missing' else blocks).append(issue['code']+': '+issue['detail'])
   elif issue['code'] in MINOR:cleanup.append(issue['detail'])
  for k in ['content_complete','options_complete','required_assets_present','text_image_consistent']:
   if not facts[k]:blocks.append(k+'=false')
  if facts['source_issue']:blocks.append('source_issue')
  if facts.get('critical_source_ambiguity'):blocks.append('来源关键内容存在歧义')
  # A failed solve or an unexplained solvable=false cannot veto otherwise complete content.
 state='incomplete' if missing else 'needs_content_review' if blocks else 'usable_with_cleanup' if cleanup else 'usable'
 return state,list(dict.fromkeys(missing+blocks)),cleanup

def knowledge_only(tags):
 import re
 diagnostics=r'信息不足|条件不足|待审核|待核对|推测|识别失败|生成失败|题干缺失|缺少题干|跨页待|missing_|needs_review|incomplete|source_issue'
 return list(dict.fromkeys(t.strip() for t in tags if isinstance(t,str) and t.strip() and not re.search(diagnostics,t,re.I)))

def build(recovery,assets,source,pages,offset=0):
 output=recovery['output'];raw_questions=output['questions'];base_keys=set(BaseQuestion.model_fields)
 minimal={**output,'questions':[{k:v for k,v in q.items() if k in base_keys} for q in raw_questions],'issues':[]}
 if recovery.get('pure_d'):
  from .d_pure import presentation_questions
  minimal['questions']=presentation_questions(minimal['questions'])
 continuation_mode=recovery.get('continuation_mode',False)
 base=assemble(dict(status='raw_success',output=minimal),assets,source,pages,offset,continuation_mode)
 ids=[q['question_id'] for q in raw_questions];assigned=output['asset_assignments'];byasset={a['asset_id']:a for a in assets}
 for q,raw in zip(base['questions'],raw_questions):
  links=[l for l in assigned if l['question_id']==raw['question_id'] and l['semantic_role']!='unassigned'];local=[]
  if ids.count(raw['question_id'])!=1:local.append('duplicate_question_id')
  if len({o['label'] for o in raw['options']})!=len(raw['options']):local.append('duplicate_option_label')
  for link in links:
   aid=link['asset_id']
   if aid not in byasset:local.append('missing_asset:'+aid)
   if sum(l['asset_id']==aid for l in assigned)!=1:local.append('ambiguous_asset_assignment:'+aid)
   if link['semantic_role']=='option' and link['option_label'] not in [o['label'] for o in raw['options']]:local.append('invalid_option_reference:'+aid)
  attached=[byasset[l['asset_id']] for l in links if l['asset_id'] in byasset]
  local+=cross_page_guard(dict(raw,source_pages=q['source_pages'],cross_page_status=q['cross_page_status']),attached,pages,continuation_mode)
  if raw['requires_image'] and not attached:local.append('missing_image_asset')
  if any(w.startswith('invalid_option_reference:') for w in q['warning']):local.append('invalid_option_reference')
  if recovery.get('light_review'):
   for option in raw['options']:
    if not option['text'].strip() and not any(l['semantic_role']=='option' and l['option_label']==option['label'] and l['asset_id'] in byasset for l in links):
     local.append('选项'+option['label']+'既没有文字也没有对应图片')
   # Unresolved asset ownership can affect image questions; never veto text-only peers.
   if raw['requires_image'] and any(e.startswith(('missing_asset_assignment:','unknown_question_reference:','invalid_unassigned:')) for e in base['assembly_errors']):
    local.append('本页有图片归属未完成，需核对本题必要配图')
  state,issues,cleanup=decide(raw,local);meta=dict(raw.get('metadata') or {});sol=raw.get('solution') or {}
  meta['knowledge_tags']=knowledge_only(meta.get('knowledge_tags',[]))
  q.update(import_method='D',delivery_policy=VERSION,delivery_status=state,delivery_check=raw.get('delivery_check'),delivery_issues=issues,cleanup_notes=cleanup,
   diagnostic_warnings=list(dict.fromkeys(q['warning']+output.get('issues',[]))),issues=issues,content_issues=issues,warning=q['warning'],
   draft_status='ready' if state in ['usable','usable_with_cleanup'] else 'incomplete' if state=='incomplete' else 'needs_review',
   content_status='ready' if state in ['usable','usable_with_cleanup'] else 'incomplete' if state=='incomplete' else 'needs_review',
   knowledge=meta.get('knowledge_tags',[]),difficulty=meta.get('estimated_difficulty',meta.get('difficulty','')),pitfalls=meta.get('common_mistakes',[]),metadata=meta,
   question_type=meta.get('question_type') or q['question_type'],ai_answer=text_blocks(sol.get('answer','')) if sol.get('answer','').strip() else [],ai_explanation=text_blocks(sol.get('explanation','')) if sol.get('explanation','').strip() else [],
   solution_status=sol.get('status','failed'),solution_issues=sol.get('issues',['solution_schema_unavailable']),solution_attempts=[],figure_workflow_version=2)
  if 'estimated_difficulty' in meta:q['estimated_difficulty']=meta['estimated_difficulty'];q.pop('difficulty',None)
  q['generate_solution']=recovery.get('generate_solution',True)
  if not q['generate_solution']:
   q.update(solution_status='disabled',ai_answer=[],ai_explanation=[],pitfalls=[],solution_issues=[])
   q['metadata'].pop('common_mistakes',None)
  elif (raw.get('delivery_check') or {}).get('critical_source_ambiguity') is True:
   q.update(solution_status='unavailable_due_to_source_issue',ai_answer=[],ai_explanation=[],solution_issues=['来源关键内容存在歧义，已停止自动求解'])
  if q['solution_status']=='ready' and (not q['ai_answer'] or not q['ai_explanation']):q.update(solution_status='failed',solution_issues=q['solution_issues']+['empty_answer_or_explanation'])
  q['answer_status']='答案解析已生成' if q['solution_status']=='ready' else '已关闭答案解析生成' if q['solution_status']=='disabled' else '答案解析待核对'
  # Overall content gate holds unresolved semantic issues. Cosmetic notes never mark fixed pixels defective.
  from .figure_state import image_slots
  prior=q['figure_records'];records=[]
  for slot in image_slots(q):
   old=next((r for r in prior if r['asset']==slot['asset']),{})
   records.append(dict(old,**slot,figure_status='ready',figure_issue=None,original_status='accepted',delivery_basis='full-page-text-plus-fixed-assets',cleanup_notes=cleanup))
  q['figure_records']=records;q['missing_required_figure']='missing_image_asset' in local
  from .figure_workflow import sync
  sync(q)
  if recovery.get('pure_d'):
   # No model QA was requested. Never fabricate a passed quality check.
   structural=list(dict.fromkeys(local+raw.get('issues',[])))
   q.update(d_import_profile='pure_d_page_overview_v1',metadata=None,metadata_status='needs_generation',question_type='',question_type_status='needs_generation',
    knowledge=[],estimated_difficulty=None,pitfalls=[],quality_check_status='disabled',delivery_check=None,
    content_status='needs_review',content_issues=structural+['纯D导入未执行质量检查，请人工审核'],
    solution_status='needs_generation' if q['generate_solution'] else 'disabled',solution_issues=[],
    answer_status='答案解析待生成' if q['generate_solution'] else '已关闭答案解析生成',
    extraction_issues=structural,issues=structural+['纯D导入未执行质量检查，请人工审核'])
   q.pop('difficulty',None)
   q['source_snapshot']['question_type']=''
   q['source_snapshot']['estimated_difficulty']=None
   for r in q['figure_records']:
    r.update(original_status='unverified',quality_check_status='disabled',delivery_basis='fixed-asset-assignment-only')
   sync(q)
  if recovery.get('light_review'):
   from .d_light import PROFILE,decide as decide_light
   state,issues,cleanup,facts=decide_light(raw,local,byasset)
   q.update(d_import_profile=PROFILE,delivery_policy=PROFILE,quality_check_status='completed' if raw.get('quality_issues') is not None else 'unavailable',
    quality_issues=raw.get('quality_issues'),delivery_status=state,delivery_check=facts,delivery_issues=issues,cleanup_notes=cleanup,
    draft_status='ready' if state in ['usable','usable_with_cleanup'] else 'incomplete' if state=='incomplete' else 'needs_review',
    content_status='ready' if state in ['usable','usable_with_cleanup'] else 'incomplete' if state=='incomplete' else 'needs_review',
    content_issues=issues,issues=issues,extraction_issues=local,generate_solution=False,solution_status='disabled')
   for r in q['figure_records']:
    r.update(original_status='accepted',quality_check_status='completed',delivery_basis='backend-light-issues-v1')
   sync(q)
  q['source_evidence']=[dict(page=p,asset=f'page-{p}.png',status='完整原页') for p in q['source_pages']]
  q['recovery_missing']=raw.get('_recovery_missing',[])
 return base

def assert_staging():
 from . import store
 prod=(store.ROOT/'data').resolve();data=store.DATA.resolve();allowed=(store.ROOT/'work/d-delivery').resolve()
 if data==prod or not data.is_relative_to(allowed):raise RuntimeError('D delivery dry-run requires isolated work/d-delivery database')

def persist(record,cancel):
 assert_staging()
 from . import store
 import shutil
 folder=store.DATA/'sources'/record['source']['source_id'];folder.mkdir(parents=True,exist_ok=True)
 for p in record['pages']:
  check(cancel);shutil.copyfile(Path(p['region_path'])/p['original'],folder/f"page-{p['page']}.png")
 source=Path(record['source']['path'])
 if source.is_file():shutil.copyfile(source,folder/source.name)
 for asset in record['assets']:
  check(cancel);p=Path(asset['path'])
  if hashlib.sha256(p.read_bytes()).hexdigest()!=asset['pixel_sha256']:raise ValueError('fixed_asset_hash_mismatch')
  shutil.copyfile(p,folder/asset['asset'])
 with store.cancellation_scope(cancel):
  for q in record['questions']:
   check(cancel)
   if store.get('questions',q['id']):continue
   q.update(created_at=time.time(),revision=0,schema_version='1.0')
   store.save_question(q)
