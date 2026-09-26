"""Opt-in pure D with issues-only QA; the backend owns every disposition."""
import json,re,copy
from typing import Literal
from .d_contract import Strict,Assignment,Page
from .d_pure import Question as Transcription,PROMPT as PURE_PROMPT
from .d_recovery import repair_syntax,unique,array_objects

PROFILE='pure_d_light_review_v1'
class Issue(Strict):
 code:Literal['missing_condition','missing_option','missing_subquestion','missing_asset','wrong_assignment','image_text_conflict','missing_critical_label','missing_image_structure','missing_table_information','cross_page_missing_context','source_problem','uncertain_transcription','minor_whitespace','minor_repeated_text','minor_neighbor_content','minor_layout','missing_printed_number']
 detail:str
 asset_ids:list[str]
class Question(Transcription):
 quality_issues:list[Issue]
class Output(Strict):
 questions:list[Question]
 asset_assignments:list[Assignment]
 page_extractions:list[Page]
 issues:list[str]

PROMPT=PURE_PROMPT.replace('不做content/delivery/source检查，不判断可解性，不做质量自检，','仅做下述轻量使用障碍审查，不判断数学可解性，').replace('issues只记转录/边界不确定，不进行完整质量检查。','issues只记转录/边界不确定；具体使用障碍写quality_issues。')+'''
轻量质量审查与本次转录同一次阅读完成，不进行第二轮整页分析。每题必须返回quality_issues数组；未发现具体障碍时为[]。只报告能指出原文/固定asset中具体位置、内容差异的问题，不输出批准、usable、严重度或通过状态，由后端决定状态。
实质问题：missing_condition题干必要条件缺失；missing_option选项缺失；missing_subquestion小问缺失；missing_asset作答必要图表缺失或未归属；wrong_assignment图配到错题/错选项；missing_image_structure图主体截断；missing_critical_label关键数字/点名/单位/图例/刻度缺失；missing_table_information必要表格信息缺失；cross_page_missing_context跨页上下文未闭合；image_text_conflict原页与固定asset关键内容冲突；source_problem原始材料本身有明确冲突；uncertain_transcription关键文字无法可靠转录。detail用中文说明具体缺少/冲突的内容和证据，asset_ids只列涉及的真实资产，无资产则[]。
不因白边、裁图稍宽、少量重复正文、轻微杂质或缺少原题号而拦截；若记录这些只能分别用minor_whitespace、minor_layout、minor_repeated_text、minor_neighbor_content、missing_printed_number。不要把纯排版问题升级为缺题/缺图。不得以没有答案、解析、知识标签或难度为缺陷。
当固定asset与完整原页在关键数字、标签、单位、图例、刻度、几何点名上冲突或缺失，立即记录具体quality_issue；不猜测缺失像素，不反复尝试数学解释或长链试算。完整原页明确可读时照原页转录文字，但仍保留固定asset的问题；无法明确则如实保留不确定。到此停止，不解题，也不生成answer/explanation/common_mistakes/solution_check。不得用数学推导修正原题。
跨页仍遵循原有carry规则：页尾文字看似完整但必要图在后页，或小问/表格未完，context_closed=false；下一页有证据闭合后可去掉已解决的缺失问题，保留仍存在的障碍。不能因为一题未完成把同页其他完整题标有问题。
'''

MISSING={'missing_condition','missing_option','missing_subquestion','missing_asset','missing_table_information','cross_page_missing_context'}
MINOR={'minor_whitespace','minor_repeated_text','minor_neighbor_content','minor_layout','missing_printed_number'}

def recover(raw):
 repaired,edits=repair_syntax(raw)
 for status,text in [('raw_success',raw),('repaired',repaired)]:
  try:return dict(status=status,output=Output.model_validate(json.loads(text,object_pairs_hook=unique)).model_dump(),edits=[] if status=='raw_success' else edits)
  except ValueError:pass
 out=dict(questions=[],asset_assignments=[],page_extractions=[],issues=[])
 for item in array_objects(repaired,'questions'):
  try:row=Question.model_validate(item).model_dump()
  except ValueError:
   # Preserve readable transcription, but never interpret absent/invalid QA as passed.
   try:row=Transcription.model_validate({k:v for k,v in item.items() if k in Transcription.model_fields}).model_dump()
   except ValueError:continue
   row.update(quality_issues=None,_recovery_missing=['quality_issues'])
  out['questions'].append(row)
 for key,model in [('asset_assignments',Assignment),('page_extractions',Page)]:
  for item in array_objects(repaired,key):
   try:out[key].append(model.model_validate(item).model_dump())
   except ValueError:pass
 return dict(status='partial' if out['questions'] else 'unrecoverable',output=out,edits=edits)

def normalized_issues(items):
 # Narrow contradiction guard: concrete clipped labels cannot be cosmetic just
 # because the model chose minor_layout. No image guessing or geometry changes.
 rows=copy.deepcopy(items or [])
 for i in rows:
  if i['code'] not in MINOR:continue
  for part in re.split(r'[。；;，,]|但是|但|然而|不过',i['detail']):
   if not re.search(r'并非没有|不代表没有|不能说没有',part) and re.search(r'无(?:关键)?(?:标签|数字|单位|刻度|图例).*缺失|(?:没有|不存在|未发现|并非|未见).*(?:缺失|裁切|截断)',part):continue
   if re.search(r'(?:关键标签|类别标签|组别标签|刻度(?:数字|标签)?|图例|单位|点名|数字)[^。；;]{0,24}(?:缺失|被裁切|被截断|未包含|不可见|无法辨认|被裁成)',part):
    i['code']='missing_critical_label';break
   if re.search(r'(?:图(?:形)?主体|必要图形|几何图|函数图象|柱形|连线)[^。；;]{0,18}(?:缺失|被裁切|被截断|未包含|不可见)',part):
    i['code']='missing_image_structure';break
 return rows

def named_polygon_issues(text):
 # Only a Chinese three-to-ten-gon name immediately followed by vertex
 # labels (optionally Unicode subscripts). Do not parse/repair general LaTeX.
 pattern=r"(?<![一二三四五六七八九十百0-9])([三四五六七八九十])边形([A-Z][A-Z₀-₉]*)(?![A-Za-z0-9₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹_'′\\^]|[ \t]+[A-Za-z₀-₉])"
 counts=dict(zip('三四五六七八九十',range(3,11)));issues=[]
 for match in re.finditer(pattern,text):
  number,name=match.groups();n=counts[number]
  vertices=re.findall(r'[A-Z][₀-₉]*',name)
  # A written closing vertex is allowed only in addition to all n vertices.
  if len(vertices)==n+1 and vertices[0]==vertices[-1]:vertices=vertices[:-1]
  if len(vertices)!=n:continue
  repeated=list(dict.fromkeys(v for v in vertices if vertices.count(v)>1))
  if repeated:
   issues.append(dict(code='uncertain_transcription',detail=f"本地完整性检查：{number}边形{name}的顶点标记{'、'.join(repeated)}重复，请对照原页核对点名及下标；原转录未改写。",asset_ids=[]))
 return issues

def decide(raw,local,assets):
 blocks=list(local);missing=[];cleanup=[];items=normalized_issues(raw.get('quality_issues')) if raw.get('quality_issues') is not None else None
 if not raw['question_text'].strip():missing.append('题干缺失')
 if items is None:blocks.append('轻量审查结构不完整，请核对')
 items=(items or [])+named_polygon_issues(raw['question_text'])
 for issue in items or []:
  if not issue['detail'].strip():blocks.append('审查问题缺少具体说明')
  if set(issue['asset_ids'])-set(assets):blocks.append('审查引用了未知图片资源')
  if issue['code'] in MINOR:cleanup.append(issue['detail'])
  elif issue['code'] in MISSING:missing.append(issue['detail'])
  else:blocks.append(issue['detail'])
 if 'missing_image_asset' in local:missing.append('缺少作答必要图表')
 status='incomplete' if missing else 'needs_review' if blocks else 'usable_with_cleanup' if cleanup else 'usable'
 codes={i['code'] for i in items or []}
 # Compatibility facts are backend-derived, never model approval/solvability.
 facts=dict(basis='backend-light-issues-v1',content_complete=not bool(codes&MISSING or missing),options_complete='missing_option' not in codes,
  required_assets_present='missing_asset' not in codes and 'missing_image_asset' not in local,
  text_image_consistent='image_text_conflict' not in codes,source_issue='source_problem' in codes,
  issues=[dict(i,severity='minor' if i['code'] in MINOR else 'missing' if i['code'] in MISSING else 'substantive') for i in items or []])
 return status,list(dict.fromkeys(missing+blocks)),list(dict.fromkeys(cleanup)),facts
