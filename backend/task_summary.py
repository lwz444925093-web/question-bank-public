"""Live question outcomes and per-task observed request costs (read-only)."""
import json
from . import store

def enrich(rows,questions):
 by_id={q['id']:q for q in questions}
 def members(t,seen=None):
  seen=set() if seen is None else seen
  if t['id'] in seen:return []
  seen.add(t['id']);out=[t]
  for child in rows:
   if child.get('parent_id')==t['id']:out.extend(members(child,seen))
  return out
 result=[]
 for task in rows:
  t=dict(task);group=members(t)
  if not t.get('review_task') and not t.get('bundle',{}).get('operation'):
   ids=set(i for member in group for i in member.get('question_ids',[]))
   counts=dict(approved=0,pending=0,failed=0,unavailable=0)
   for qid in ids:
    q=by_id.get(qid)
    if not q:counts['unavailable']+=1
    elif q.get('processing_status')=='incomplete':counts['failed']+=1
    elif q.get('review_status')=='approved':counts['approved']+=1
    elif q.get('processing_status')=='saved' and t.get('status') not in ('running','queued'):counts['failed']+=1
    else:counts['pending']+=1
   counts['known']=bool(ids) or any(m.get('page_extraction',{}).get('basis')=='explicit-page-report-v1' for m in group)
   counts['unresolved_batch']=any(m.get('status') in ('failed','partial','interrupted','cancelled') and not m.get('question_ids') and (m.get('error') or not counts['known']) for m in group)
   t['question_outcomes']=counts
  ids=set(i for member in group for i in member.get('question_ids',[]))
  modern=[by_id[i] for i in ids if i in by_id and by_id[i].get('figure_workflow_version')==2]
  if modern:
   from .figure_workflow import sync
   modern=[sync(dict(q)) for q in modern]
   figures=[f for q in modern for f in q.get('figure_records',[])]
   t['import_outcomes']=dict(discovered=len(ids),content={k:sum(q.get('content_status')==k for q in modern) for k in ['ready','needs_review','incomplete']},figures={k:sum(f.get('figure_status')==k for f in figures) for k in ['ready','needs_manual_crop','needs_recrop_from_source','failed']},directly_usable=sum(q['directly_usable'] for q in modern),needs_figure_work=sum(q['figure_status']!='ready' for q in modern),missing_figures=sum(q.get('missing_required_figure',False) for q in modern))
  if modern:t['import_outcomes']['solutions']={k:sum(q.get('solution_status')==k for q in modern) for k in ['ready','needs_generation','needs_retry','needs_review','failed']}
  amount=0.;calls=0;missing=0;pending=0
  for member in group:
   if member.get('import_method')=='D':
    metric_files=list((store.DATA/'tasks'/member['id']/'d-stage'/'calls').rglob('metrics.json'))
    if metric_files:
     for path in metric_files:
      try:metric=json.loads(path.read_text())
      except (ValueError,OSError):pending+=1;continue
      if type(metric.get('request_count')) is int and metric['request_count']==0:continue
      cost=metric.get('cost_cny_estimate')
      if isinstance(cost,(int,float)):amount+=cost;calls+=metric.get('request_count',1)
      elif member.get('status') in ('queued','running') and not metric.get('error') and metric.get('http_seconds') is None:pending+=metric.get('request_count',1)
      else:missing+=max(metric.get('request_count',0),1)
    else:
     metrics=member.get('d_metrics',{});cost=metrics.get('cost_cny_estimate');n=metrics.get('requests',0)
     if isinstance(cost,(int,float)):amount+=cost;calls+=n
     elif type(metrics.get('requests')) is int and metrics['requests']==0:pass
     elif n or member.get('started_at'):missing+=max(n,1)
   folder=store.DATA/'tasks'/member['id']
   # Word equation batches have per-request metrics, including failed batches.
   # Count those directly rather than treating the aggregate usage as one call.
   word_metrics=list((folder/'editable-equations').rglob('metrics.json'))
   if word_metrics:
    for path in word_metrics:
     try:metric=json.loads(path.read_text())
     except (ValueError,OSError):missing+=1;continue
     n=metric.get('request_count',1);cost=metric.get('cost_cny_estimate')
     if type(metric.get('request_count')) is int and n==0:continue
     if isinstance(cost,(int,float)):amount+=cost;calls+=n
     elif member.get('status') in ('queued','running') and not metric.get('error') and metric.get('http_seconds') is None:pending+=max(n,1)
     else:missing+=max(n,1)
   # Native Word can add an integrity review and solutions after formula
   # recovery. Its review has HTTP metrics; solutions retain usage.json.
   native_metrics=list((folder/'native-services'/'quality-review'/'calls').rglob('metrics.json'))
   for path in native_metrics:
    try:metric=json.loads(path.read_text())
    except (ValueError,OSError):missing+=1;continue
    n=metric.get('request_count',1);cost=metric.get('cost_cny_estimate')
    if n==0:continue  # Credential/budget preflight failed before a request.
    if isinstance(cost,(int,float)):amount+=cost;calls+=n
    elif member.get('status') in ('queued','running') and not metric.get('error') and metric.get('http_seconds') is None:pending+=n
    else:missing+=n
   files=list(folder.rglob('usage.json')) if folder.is_dir() else []
   if word_metrics:files=[p for p in files if not p.is_relative_to(folder/'editable-equations')]
   # A request writes one usage file; do not sum its aggregate meta again.
   request_dirs={p.parent for p in folder.rglob('opencode.private.jsonl')} if folder.is_dir() else set()
   observed=set()
   for path in files:
    observed.add(path.parent)
    try:
     meta=json.loads(path.read_text());estimate=meta.get('cost_estimate')
     if meta.get('cached'):continue
     if not estimate or not isinstance(estimate.get('amount'),(int,float)):missing+=1;continue
     amount+=estimate['amount'];calls+=meta.get('application_requests',1)
    except (ValueError,OSError,TypeError):missing+=1
   missing+=len(request_dirs-observed)
   if member.get('import_method')!='D' and not files and not request_dirs and not word_metrics and not native_metrics and not any(c.get('parent_id')==member['id'] for c in rows):
    meta=member.get('meta') or {}
    if meta.get('cached'):continue
    estimate=meta.get('cost_estimate')
    if estimate and isinstance(estimate.get('amount'),(int,float)):amount+=estimate['amount'];calls+=meta.get('application_requests',1)
    elif member.get('started_at') or member.get('status') not in ('queued',):missing+=1
  t['task_cost']=dict(amount=round(amount,6) if calls or not missing else None,complete=missing==0 and pending==0,observed_calls=calls,missing_calls=missing,pending_calls=pending)
  result.append(t)
 return result
