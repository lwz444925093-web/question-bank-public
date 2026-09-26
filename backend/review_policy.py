"""Only question/import defects gate the question bank; solutions are optional."""
import re

GENERIC={'等待人工核对题目、答案与解析','等待人工核对答案与解析','答案和解析待人工核对','答案与解析待人工核对'}

def has_material_issue(text):
 """Recognize concrete defects without treating '未造成缺失或矛盾' as one.

 Negation is deliberately limited to the defect phrase in its own clause. A
 subsequent '但刻度缺失' and double negatives still require review.
 """
 defects=r'不一致|矛盾|漏识别|识别错误|缺少必要|缺失必要|关键(?:标签|数字|单位|刻度|图例|点名).{0,12}(?:缺失|截断|无法辨认)'
 negated=re.compile(r'(?:未造成|并未造成|未发现|没有发现|不存在|没有|未见|无)(?:任何|明显|实质性?|关键|数据|内容|图文|文字|题干|标签|选项|缺失|错误|缺少|或|与|及|和|、|的|所需|必要)*$')
 for clause in re.split(r'[，,。；;！？!?]|但是|但|然而|不过',str(text)):
  for hit in re.finditer(defects,clause):
   prefix=clause[:hit.start()]
   denial=negated.search(prefix)
   if denial and not re.search(r'并非|不是|不代表|不能说',prefix[:denial.start()]):continue
   return True
 return False

def split_issues(issues):
 blockers=[];notes=[]
 for issue in issues or []:
  text=str(issue).strip()
  # Keep statements about ambiguous conditions, diagrams or options as blockers,
  # even when they also mention a resulting answer problem.
  solution_only=bool(re.match(r'^(?:本题)?(?:暂无|缺少|未提供|没有|未生成|尚未生成)?(?:参考)?(?:答案|解析)',text)) and not re.search(r'题干|题目条件|条件不|条件缺|题图|选项|缺图|裁[切剪]|无法辨认|歧义|多解',text) and not has_material_issue(text)
  if text in GENERIC or solution_only:notes.append(text)
  elif text:blockers.append(text)
 return list(dict.fromkeys(blockers)),list(dict.fromkeys(notes))

def separate_solution_notes(q):
 q['issues'],notes=split_issues(q.get('issues',[]))
 if notes:q['solution_notes']=list(dict.fromkeys(q.get('solution_notes',[])+notes))
 return q

def accept_manual_crops(q):
 """A user's saved crop is adopted; unresolved model/source defects still block."""
 separate_solution_notes(q)
 for record in q.get('figure_records',[]):
  if record.get('manual_crop') and (q.get('figure_workflow_version')!=2 or record.get('baseline_revision')==q.get('revision')):
   record.update(state='verified',original_status='accepted',confirmation='user_crop_saved',note='人工裁切已采用',figure_status='ready',figure_issue=None)
 if q.get('figure_workflow_version')==2:
  from .figure_workflow import sync
  return sync(q)
 remaining=any(r.get('state')!='verified' for r in q.get('figure_records',[]))
 q.update(review_status='pending' if q.get('issues') or remaining else 'approved',processing_status='review' if remaining else 'complete',processing_reason='题图仍有具体问题待核对' if remaining else '')
 return q


def approve_question(q,include_figures=False):
 """Explicit user confirmation of the question and figures, not its solutions."""
 import copy,time
 from .figure_state import image_slots
 from .manual_crop import figure_record
 q.setdefault('manual_approvals',[]).append(dict(time=time.time(),baseline_revision=q['revision'],issues=copy.deepcopy(q.get('issues',[])),processing_status=q.get('processing_status'),processing_reason=q.get('processing_reason'),figure_records=copy.deepcopy(q.get('figure_records',[]))))
 if q.get('figure_workflow_version')==2:
  from .figure_workflow import sync
  q.update(content_status='ready',content_issues=[],issues=[],review_origin='human')
  if include_figures:
   q.update(manual_full_review=True,missing_required_figure=False,import_review_blocked=False)
   for record in q.get('figure_records',[]):
    record.update(figure_status='ready',figure_issue=None,state='verified',original_status='accepted',confirmation='user_review_approved')
  return sync(q)
 q['figure_records']=[dict(figure_record(q,s),**s,original_status='accepted',confirmation='user_review_approved') for s in image_slots(q)]
 for record in q['figure_records']:record['state']='verified'
 q.update(issues=[],review_status='approved',processing_status='complete',processing_reason='',review_origin='human')
 return q

def sync_question_review(q):
 """Recompute question-review state without certifying an unverified image."""
 from .figure_state import image_slots
 separate_solution_notes(q)
 if q.get('figure_workflow_version')==2:
  from .figure_workflow import sync
  return sync(q)
 unverified=any(s['state']!='verified' for s in image_slots(q))
 q.update(review_status='pending' if q.get('issues') or unverified else 'approved',processing_status='review' if unverified else 'complete',processing_reason='题图定位或核验待人工确认' if unverified else '')
 return q
