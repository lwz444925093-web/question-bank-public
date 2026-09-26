"""Extract/locate once, verify/solve once; solution retries never edit source."""
import copy,hashlib,json,time,shutil
from pathlib import Path
from typing import Literal,Optional
from pydantic import Field
from . import store
from .answer_format import ANSWER_FORMAT_INSTRUCTION
from .model import Strict,Extracted,ParseResult,Block
from .figure_state import image_slots,block_at
from .figure_workflow import QualityCheck,QUALITY_INSTRUCTION,finish,ensure,sync
from .request_boundary import json_payload

class LocatedFigure(Strict):
 position:str
 asset:str
 page:Optional[int]
 box:Optional[list[float]]
 issue:str
class LocatedQuestion(Extracted):
 initial_figures:list[LocatedFigure]=Field(default_factory=list)
class LocatedParseResult(ParseResult):
 questions:list[LocatedQuestion]
class ContentCheck(Strict):
 status:Literal['ready','needs_review','incomplete']
 issues:list[str]
class FigureCheck(QualityCheck):
 figure_id:str
 position:str
 readable:bool
class Solution(Strict):
 answer:list[Block]
 explanation:list[Block]
class SolutionCheck(Strict):
 status:Literal['ready','needs_retry','needs_review','failed']
 issues:list[str]
class SolveOutput(Strict):
 solution:Solution
 solution_check:SolutionCheck
 knowledge:list[str]
class VerifySolveOutput(SolveOutput):
 content_check:ContentCheck
 figure_checks:list[FigureCheck]

EXTRACT_INSTRUCTION='''本次仅提取源题并同时给出第一次图形定位，不解题。ai_answer、ai_explanation、original_answer、original_explanation均返回空数组。不得修改原题使其可解。
PDF/上传图片：每处必要题干图、选项图、小问图都保留为独立image block，其asset引用源页；initial_figures为每处image block返回精确position路径（stem/0、options/0/blocks/0、subquestions/0/blocks/0等）、同一asset、物理page、该整页0..1000坐标box[x1,y1,x2,y2]。图形所有必要字母、箭头、虚线、弧线和单位完整优先；禁止重绘。别漏题干图，不能只提取选项图。
DOCX原生图片：复用其明确asset及原文位置，page=null、box=null，不重新识别整页、不裁独立图片。无法确定图槽归属就明确issues，不补造。
如提供page-N-grid.png，网格每50、数字每100，仅辅助定位；用无网格原页读文字，返回坐标是整页网格坐标，绝非像素坐标。图片asset仍引用page-N.png，禁止引用网格图。每个图形选项独立保存image block，严禁把整行选项图塞进A并将B/C/D置空。
source_regions仅是整道题目大致范围，与initial_figures图框不同；图框无法确认允许box=null，解释issue。提取指定完整题目范围，不提取教材知识介绍或标准答案部分。'''
VERIFY_INSTRUCTION=QUALITY_INSTRUCTION.replace('不解题、不修改题干','图片判断不修改题干').replace('只判断，不提议重新调用模型，不输出修图、解题或重绘内容。','图片检查不提议重新调用模型，不输出修图或重绘内容。')+'''
这一次同时完成content_check、figure_checks、solution、solution_check。figure_checks每个figure_id/position独立返回，asset必须来自本次figures；readable检查必要标签是否可辨。无图题figure_checks必须为空，不做图片核验。
content_check检查已保存题干、公式、选项、小问、表格与必要原文上下文一致性；只报告具体缺失、误读或矛盾，不能修改原题。不得为方便求解补负号、改数字或补条件。解不出来不等于题目导入错误。
根据当前已保存的题目生成答案answer和完整解析explanation，使用Block结构，数学采用LaTeX。不借用其他题目或历史答案。源页只用来核对来源；若源页与当前题目矛盾，报告疑点，不暗自用修正后的题目给确定答案。图缺失影响求解时solution_check=needs_review并说明限制。
答案或解析缺失/中断、明显计算矛盾返回needs_retry；题意歧义返回needs_review；正常完整返回ready。不执行代码、不调用工具、不得多数投票。'''
SOLVE_INSTRUCTION='''仅根据本次question与当前保存图片，独立生成答案answer和完整解析explanation，以及solution_check。不要提取/改写题目，不定位、不裁图、不核验图片，不请求原PDF/DOCX。没有历史答案或参考答案，不以旧答案为目标修正。
solution_check: ready=答案解析完整一致；needs_retry=答案/解析为空或中断、内部明显矛盾；needs_review=题意歧义或图片/条件不足；failed=本次求解失败。不会解不能作为题目错误证据。只报告解题疑点，不修改文字/图片状态。不执行代码，不调用工具，不用随机数值采样代替证明。只返回Schema JSON。'''

VERIFY_INSTRUCTION += "\n" + ANSWER_FORMAT_INSTRUCTION
SOLVE_INSTRUCTION += "\n" + ANSWER_FORMAT_INSTRUCTION
KNOWLEDGE_INSTRUCTION='同时返回顶层knowledge知识点标签数组。根据本题实际考查内容和解答中使用的核心方法，通常给出1至5个简洁、具体的中文知识点，如“三角形全等”“平行四边形的性质”“一元二次方程”。优先沿用question.knowledge中适用的名称，避免同义重复；不要把题型、难度、来源、审核状态、整句解题结论当作知识点。条件不足时只标记可确定的知识点，无法确定则返回[]，不得猜测。标签与答案解析在本次请求一起生成，不修改题干或图片。'
VERIFY_INSTRUCTION += "\n" + KNOWLEDGE_INSTRUCTION
SOLVE_INSTRUCTION += "\n" + KNOWLEDGE_INSTRUCTION
SOLVE_INSTRUCTION += '\n如材料包含teacher_request，这是教师本次的作答要求；在不改写题目和不虚构条件的前提下遵循它。返回前逐小问核对answer栏本身有完整作答和最终结果，不能只列已知、定义或解题起点，也不能只把结果写入explanation。结果缺失时须在本次回复补全，仍无法完成则标记needs_retry。'

def merge_knowledge(existing,generated):
 """Add grounded solution tags without deleting existing teacher tags."""
 tags=[]
 for values in [existing,generated]:
  if not isinstance(values,list):continue
  for value in values:
   if isinstance(value,str) and value.strip() and value.strip() not in tags:tags.append(value.strip())
 return tags

def enabled(cfg):return cfg.get('verify_solve_enabled',True)

def question_payload(q):
 return {k:copy.deepcopy(q[k]) for k in ['id','revision','original_number','subject','stem','options','subquestions','pages','knowledge'] if k in q}

def request_once(provider,bundle,taskdir,schema,instruction,cancel=None,progress=None):
 """Durable request identity: replay completed output, never resend uncertain calls."""
 taskdir=Path(taskdir);taskdir.mkdir(parents=True,exist_ok=True)
 digest=hashlib.sha256(json.dumps([bundle,schema,instruction],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
 marker=taskdir/'request-started.json';done=taskdir/'request-completed.json'
 if marker.exists():
  if json.loads(marker.read_text())['sha256']!=digest:raise ValueError('检查点输入已变化，禁止覆盖或重发已完成请求')
  if done.exists():
   result=json.loads(done.read_text());return result['raw'],result['meta']
  if (taskdir/'final.json').is_file() and (taskdir/'usage.json').is_file():
   return (taskdir/'final.json').read_text(),json.loads((taskdir/'usage.json').read_text())
  raise ValueError('已有调用记录但完成状态不确定；停止重发，请先核对API记录')
 marker.write_text(json.dumps(dict(sha256=digest,started_at=time.time())))
 raw,meta=provider.request(bundle,taskdir,schema,instruction,cancel,progress)
 done.write_text(json.dumps(dict(raw=raw,meta=meta),ensure_ascii=False))
 return raw,meta

def extraction_payload(raw,taskdir):
 try:return json_payload(raw)
 except ValueError as original:
  # A known rows serialization error closes the outer rows array after each row.
  # Remove only the redundant bracket between rows, outside every string token.
  import re
  decoder=json.JSONDecoder();mask=list(raw);i=0
  while i<len(raw):
   if raw[i]!='"':i+=1;continue
   try:_,end=decoder.raw_decode(raw,i)
   except ValueError:raise original
   mask[i:end]=[' ']*(end-i);i=end
  masked=''.join(mask);deletions=[m.start(1) for m in re.finditer(r'\]\s*\]\s*(\])\s*,\s*\[\s*\[',masked)]
  deletions += [m.start(1) for m in re.finditer(r'\]\s*\]\s*\]\s*(\])\s*,',masked)]
  if not deletions:raise original
  candidate=''.join(ch for i,ch in enumerate(raw) if i not in set(deletions))
  try:out=json_payload(candidate)
  except ValueError:raise original
  # No source string, number, asset, or ordering is changed by this operation.
  Path(taskdir,'rows-serialization-repair.json').write_text(json.dumps(dict(deleted_bracket_offsets=deletions,original_sha256=hashlib.sha256(raw.encode()).hexdigest(),candidate_sha256=hashlib.sha256(candidate.encode()).hexdigest(),model_requests=0)))
  return out

def normalize_inactive_block_fields(payload):
 """Fill only absent fields that cannot carry content for the declared block kind."""
 out=copy.deepcopy(payload);changes=[];active={'paragraph':'spans','equation':'latex','table':'rows','image':'asset','geometry':'shapes'}
 defaults={'spans':[],'latex':'','rows':[],'shapes':[],'asset':''}
 def walk(value,path):
  if isinstance(value,dict):
   kind=value.get('kind')
   if kind in active and active[kind] in value:
    for key,default in defaults.items():
     if key!=active[kind] and key not in value:value[key]=copy.deepcopy(default);changes.append(path+'.'+key)
   for k,v in list(value.items()):walk(v,path+'.'+k)
  elif isinstance(value,list):
   for i,v in enumerate(value):walk(v,path+f'/{i}')
 walk(out,'root');return out,changes

def extract_located(provider,bundle,taskdir,cancel,progress):
 from .opencode_import import SOURCE_PROMPT,validate_parse_output
 bundle=copy.deepcopy(bundle)
 if bundle.get('original','').lower().endswith('.pdf') and bundle.get('pages'):
  from .diagrams import grid_previews
  from PIL import Image
  folder=store.DATA/'sources'/bundle['source_id'];grids=grid_previews(folder,bundle['pages'])
  bundle['images']=list(dict.fromkeys(bundle.get('images',[])+grids))
  bundle['coordinate_reference']={'range':[0,1000],'origin':'top-left','grids':[]}
  for page,path in zip(bundle['pages'],grids):
   with Image.open(path) as im:bundle['coordinate_reference']['grids'].append(dict(page=page,asset=Path(path).name,width=im.width,height=im.height))
 raw,meta=request_once(provider,dict(bundle,_operation='extract_locate'),taskdir,LocatedParseResult.model_json_schema(),SOURCE_PROMPT+'\n'+EXTRACT_INSTRUCTION,cancel,progress)
 normalized,changes=normalize_inactive_block_fields(extraction_payload(raw,taskdir))
 if changes:Path(taskdir,'inactive-fields-normalized.json').write_text(json.dumps(changes,ensure_ascii=False))
 located=LocatedParseResult.model_validate(normalized);locations=[q.initial_figures for q in located.questions];plain=located.model_dump()
 for q in plain['questions']:q.pop('initial_figures',None)
 canonical=validate_parse_output(json.dumps(plain,ensure_ascii=False),bundle).model_dump()
 for q,regions in zip(canonical['questions'],locations):q['initial_figures']=[r.model_dump() for r in regions]
 return canonical,meta

def locate_locally(q,taskdir):
 folder=store.DATA/'sources'/q['source']['id'];records=[];native=q['source']['file'].lower().endswith('.docx')
 for slot in image_slots(q):
  if q.get('fixed_region_input'):
   prior=next((r for r in q.get('figure_records',[]) if r.get('figure_id')==slot['figure_id'] and r.get('asset')==slot['asset']),{})
   path=folder/slot['asset'];expected=prior.get('content_hash')
   valid=path.is_file() and bool(expected) and hashlib.sha256(path.read_bytes()).hexdigest()==expected
   record=dict(prior,**slot,box=None,baseline_revision=q['revision'])
   if not valid:record['unlocated']=True
   records.append(record)
   continue
  region=next((r for r in q.get('initial_figures',[]) if r['position']==slot['position'] and r['asset']==slot['asset']),None)
  if native:
   path=folder/slot['asset']
   if not path.is_file():continue
   digest=hashlib.sha256(path.read_bytes()).hexdigest();asset='native-'+slot['figure_id']+'-'+digest[:12]+path.suffix
   if not (folder/asset).exists():shutil.copyfile(path,folder/asset)
   records.append(dict(slot,asset=asset,original_asset=slot['asset'],original_hash=digest,page=None,box=None,baseline_revision=q['revision']))
  elif region and region.get('box') is not None:
   try:
    from .vision_inputs import render_region
    if region['page'] not in q['pages']:raise ValueError('图框页码不属于本题')
    view=render_region(folder,region['page'],region['box'],'figure_asset',dpi=288);asset='first-'+slot['figure_id']+'-'+view['pixel_sha256'][:12]+'.png'
    if not (folder/asset).exists():shutil.copyfile(view['path'],folder/asset)
    records.append(dict(slot,asset=asset,page=region['page'],box=region['box'],source_render=view,original_asset=asset,content_hash=hashlib.sha256((folder/asset).read_bytes()).hexdigest(),baseline_revision=q['revision']))
   except (ValueError,RuntimeError,KeyError) as exc:q.setdefault('figure_import_issues',[]).append(str(exc))
  if not any(r['figure_id']==slot['figure_id'] for r in records):
   # Preserve unresolved source slots; unique aliases keep per-slot checks independent.
   path=folder/slot['asset'];asset=slot['asset']
   if path.is_file():
    asset='unlocated-'+slot['figure_id']+path.suffix
    if not (folder/asset).exists():shutil.copyfile(path,folder/asset)
   records.append(dict(slot,asset=asset,original_asset=slot['asset'],page=region.get('page') if region else None,box=None,baseline_revision=q['revision'],unlocated=True))
 return records

def material_for(q,records,taskdir,with_source):
 source=q.get('source') or {};folder=store.DATA/'sources'/source.get('id','');current=copy.deepcopy(q);figures=[];images=[];by_id={r['figure_id']:r for r in records}
 for slot in image_slots(q):
  r=by_id.get(slot['figure_id'],dict(slot));asset=r['asset'];block_at(current,slot['position'])['asset']=asset
  if (folder/asset).is_file():images.append(str(folder/asset))
  figures.append(dict(figure_id=slot['figure_id'],position=slot['position'],asset=asset,page=r.get('page'),box=r.get('box')))
 context=[]
 if with_source:
  if (folder/'original.pdf').is_file() or q.get('fixed_region_input'):
   for page in q.get('pages',[]):
    path=folder/f'page-{page}.png'
    if path.is_file():images.append(str(path));context.append(dict(page=page,asset=path.name,role='source_page'))
  elif not q['source']['file'].lower().endswith('.docx') and (folder/'image.png').is_file():images.append(str(folder/'image.png'));context.append(dict(asset='image.png',role='source_upload'))
  else:context.append(dict(role='native_question_excerpt',text=q.get('native_source_excerpt','原文片段不可用，请明确提示无法完成来源一致性检查')))
 return dict(original='已保存题目',display_name='题目 '+q['original_number'],source_id=source.get('id',''),question=question_payload(current),images=list(dict.fromkeys(images)),figures=figures,source_context=context)

def solution_only_material(q,taskdir):
 material=material_for(q,[],taskdir,False)
 return {k:v for k,v in material.items() if k not in ['source_context','figures']}|dict(_operation='solution_only',target_field='solution')

def recover_sections(raw):
 """Decode only intact, uniquely named sections; never repair generated text."""
 from .request_boundary import unique_pairs
 decoder=json.JSONDecoder(object_pairs_hook=unique_pairs);found={};counts={};index=0
 names={'content_check','figure_checks','solution','solution_check','knowledge'}
 while index<len(raw):
  if raw[index]!='"':index+=1;continue
  try:key,end=decoder.raw_decode(raw,index)
  except ValueError:break
  index=end
  if not isinstance(key,str):continue
  after=end
  while after<len(raw) and raw[after].isspace():after+=1
  if key not in names or after>=len(raw) or raw[after]!=':':continue
  counts[key]=counts.get(key,0)+1;after+=1
  while after<len(raw) and raw[after].isspace():after+=1
  try:value,_=decoder.raw_decode(raw,after);found[key]=value
  except ValueError:pass
 return {k:v for k,v in found.items() if counts[k]==1}

def solution_result(payload):
 try:
  payload,compatibility=normalize_inactive_block_fields(payload)
  solution=payload.get('solution')
  if isinstance(solution,dict):
   if 'knowledge' in solution:
    payload['knowledge']=merge_knowledge(payload.get('knowledge',[]),solution.pop('knowledge'))
    compatibility.append('move_solution_knowledge_to_top_level')
   for field in ['answer_asset','explanation_asset','answer_only','explanation_only']:
    if field in solution and solution[field] in ('',None,[]):
     solution.pop(field);compatibility.append('remove_empty_'+field)
  # Old checkpoints lack tags; malformed tags must not discard a valid solution.
  out=SolveOutput.model_validate({k:payload[k] for k in ['solution','solution_check']}|dict(knowledge=merge_knowledge([],payload.get('knowledge',[])))).model_dump()
  from .manual_review import normalize_solution
  out['solution'],_=normalize_solution(out['solution'])
  from .solution_integrity import has_content
  if not has_content(out['solution']['answer']) or not has_content(out['solution']['explanation']):out['solution_check']=dict(status='needs_retry',issues=['答案或解析为空'])
  text=' '.join(s.get('text','') for field in out['solution'].values() for b in field for s in b.get('spans',[]))
  if any(token in text for token in ['解析待补充','解析未完成','后续步骤略去','此处省略推导']):out['solution_check']=dict(status='needs_retry',issues=['解析包含未完成标记'])
  if compatibility:out['compatibility_repairs']=compatibility
  return out
 except (ValueError,KeyError,TypeError) as exc:return dict(solution=dict(answer=[],explanation=[]),solution_check=dict(status='needs_retry',issues=['solution结构不完整：'+str(exc)[:250]]))

def attempts_differ(attempts):
 answers=[a.get('solution',{}).get('answer') for a in attempts if a.get('solution',{}).get('answer')]
 if len(answers)<2:return []
 return ['多次独立答案存在差异，保留各次结果供人工核对；不按多数决定'] if len({json.dumps(a,ensure_ascii=False,sort_keys=True) for a in answers})>1 else []

def solve_request(q,taskdir,cfg,cancel,progress,teacher_request=None):
 from .solution_provider import SolutionProvider
 material=solution_only_material(q,taskdir)
 if teacher_request:material['teacher_request']=teacher_request
 raw,meta=request_once(SolutionProvider(store.ROOT,dict(cfg,reasoning='low')),material,taskdir,SolveOutput.model_json_schema(),SOLVE_INSTRUCTION,cancel,progress)
 return solution_result(json_payload(raw)),meta

def save_attempts(q,attempts):
 last=attempts[-1];differences=attempts_differ(attempts);status=last['solution_check']['status']
 if len(attempts)>=3 and status in ['failed','needs_retry'] or differences:status='needs_review'
 from .solution_integrity import solution_complete
 usable=next((a for a in reversed(attempts) if solution_complete(a.get('solution',{}),a.get('solution_check',{}).get('status'))),None)
 # Failed/partial attempts remain diagnostic evidence. They must not replace a
 # prior complete answer with an empty or half-written generated result.
 if usable:
  q['knowledge']=merge_knowledge(q.get('knowledge',[]),usable.get('knowledge',[]))
  q.update(ai_answer=copy.deepcopy(usable['solution']['answer']),ai_explanation=copy.deepcopy(usable['solution']['explanation']))
 q.update(solution_status=status,solution_issues=last['solution_check']['issues']+differences,solution_attempts=copy.deepcopy(attempts),solution_differences=differences,answer_status='答案解析已生成' if status=='ready' else '答案解析待核对',import_owned_revision=q['revision']+1)
 return store.save_question(q,q['revision'],image_only=True)

def complete_question(qid,taskdir,cfg,cancel,progress):
 taskdir=Path(taskdir);taskdir.mkdir(parents=True,exist_ok=True);q=store.get('questions',qid)
 if (taskdir/'result.json').exists():return q
 checkpoint=taskdir/'question-start.json'
 if checkpoint.exists():
  original=json.loads(checkpoint.read_text())
  if q.get('solution_attempts'):
   # Completed first pass is not re-verified during task resume.
   return continue_solutions(q,taskdir,cfg,cancel,progress)
  if q['revision']!=original['revision']:raise ValueError('题目已有新版本，停止旧题任务')
 else:checkpoint.write_text(json.dumps(q,ensure_ascii=False))
 baseline=q['revision'];ensure(q)
 cfg=dict(cfg,reasoning='low',request_limits={**cfg.get('request_limits',{}),'recrops':0,'format_repairs':0})
 records=locate_locally(q,taskdir);material=material_for(q,records,taskdir,True)
 has_figures=bool(material['figures']);material['_operation']='verify_solve' if has_figures else 'content_solve'
 if not has_figures:material.pop('figures',None)
 from .opencode_import import OpenCodeProvider
 checks=[];payload={};meta={};error=''
 try:
  raw,meta=request_once(OpenCodeProvider(store.ROOT,cfg),material,taskdir/'verify-solve',VerifySolveOutput.model_json_schema(),VERIFY_INSTRUCTION,cancel,progress)
  try:payload=json_payload(raw)
  except ValueError as exc:
   payload=recover_sections(raw);error='整体JSON不完整；仅采用可独立解析并校验的分区：'+str(exc)[:160]
   (taskdir/'partial-sections.json').write_text(json.dumps(dict(sections=list(payload),error=error),ensure_ascii=False))
  try:
   cc=ContentCheck.model_validate(payload['content_check']).model_dump();q.update(content_status=cc['status'],content_issues=cc['issues'])
  except (ValueError,KeyError,TypeError):q.update(content_status='needs_review',content_issues=['内容检查结构不完整，保留原题待核对'])
  try:
   cs=[FigureCheck.model_validate(c).model_dump() for c in payload['figure_checks']]
   expected={(f['figure_id'],f['position'],f['asset']) for f in material.get('figures',[])}
   if len(cs)!=len(expected) or {(c['figure_id'],c['position'],c['asset']) for c in cs}!=expected:raise ValueError('图槽核验不完整或重复')
   for c in cs:
    if not c['readable']:c['critical_labels_present']=False
   checks=cs
   for c in checks:
    if any(r.get('unlocated') and r['figure_id']==c['figure_id'] for r in records):
     c['contains_other_question_content']=True;c['extra_content']='excessive'
  except (ValueError,KeyError,TypeError) as exc:error='图片检查结构不完整：'+str(exc)[:200]
 except Exception as exc:
  if cancel and cancel.is_set():raise
  error=str(exc)[:300];q.update(content_status='needs_review',content_issues=['合并检查未完成，原题保留待核对'])
 if cancel and cancel.is_set():raise ValueError('任务取消，不采用迟到结果')
 if store.get('questions',qid)['revision']!=baseline:raise ValueError('题目已修改，不采用迟到核验解题结果')
 if has_figures:q=finish(q,records,checks,error,localizations=0 if q.get('fixed_region_input') or q['source']['file'].endswith('.docx') else 1)
 else:q=store.save_question(sync(q),baseline,image_only=True)
 attempts=[dict(attempt=1,kind=material['_operation'],baseline_revision=baseline,**solution_result(payload),meta=meta,error=error)]
 q=save_attempts(q,attempts)
 return continue_solutions(q,taskdir,cfg,cancel,progress)

def continue_solutions(q,taskdir,cfg,cancel,progress):
 if q.get("generate_solution") is False or q.get("solution_status")=="unavailable_due_to_source_issue":return q
 attempts=copy.deepcopy(q['solution_attempts']);qid=q['id']
 for index in range(len(attempts)+1,4):
  if attempts[-1]['solution_check']['status'] not in ['needs_retry','failed']:break
  expected=q['revision'];latest=store.get('questions',qid)
  if latest['revision']!=expected:raise ValueError('题目已修改，停止旧题解答重试')
  trigger=copy.deepcopy(attempts[-1].get('solution_check',{}))
  retry_folder=taskdir/f'solution-attempt-{index}';retry_folder.mkdir(parents=True,exist_ok=True)
  (retry_folder/'retry-reason.json').write_text(json.dumps(dict(attempt=index,trigger=trigger),ensure_ascii=False,indent=2))
  try:out,retry_meta=solve_request(latest,taskdir/f'solution-attempt-{index}',cfg,cancel,progress)
  except Exception as exc:
   if cancel and cancel.is_set():raise
   out=dict(solution=dict(answer=[],explanation=[]),solution_check=dict(status='failed',issues=[str(exc)[:250]]));retry_meta={}
  transport_failed=not bool(retry_meta) and out['solution_check']['status']=='failed'
  attempts.append(dict(attempt=index,kind='solution_only',baseline_revision=expected,retry_reason=trigger,**out,meta=retry_meta))
  if (cancel and cancel.is_set()) or store.get('questions',qid)['revision']!=expected:raise ValueError('不采用迟到的答案重试结果')
  q=save_attempts(q,attempts)
  if transport_failed:break
 (taskdir/'result.json').write_text(json.dumps(dict(question=q,attempts=attempts),ensure_ascii=False,indent=2))
 return q


def start_solution_only(q,taskdir,cfg,cancel,progress):
 """Explicit opt-in after pure extraction: first solve plus at most two retries."""
 if q.get('generate_solution') is not True:return q
 if not q.get('context_closed') or q.get('extraction_issues'):return q
 taskdir=Path(taskdir);taskdir.mkdir(parents=True,exist_ok=True)
 if q.get('solution_attempts'):return continue_solutions(q,taskdir,cfg,cancel,progress)
 expected=q['revision']
 # Transport/unknown errors propagate; never turn them into blind retries.
 out,meta=solve_request(q,taskdir/'solution-attempt-1',cfg,cancel,progress)
 if (cancel and cancel.is_set()) or store.get('questions',q['id'])['revision']!=expected:raise ValueError('不采用迟到的答案结果')
 q=save_attempts(q,[dict(attempt=1,kind='solution_only',baseline_revision=expected,**out,meta=meta)])
 return continue_solutions(q,taskdir,cfg,cancel,progress)
