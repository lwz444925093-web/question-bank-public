"""User-selected remaining pages, with explicit opt-in for uncertain coverage."""
import hashlib,uuid
import fitz
from . import store,tasks
from .material_catalog import original,is_import,pages
from .work_queue import submission_lock
from .unified_import import submit as submit_unified
from .material_catalog import current_completed

def source(data):
 subject=data.get('subject','数学')
 if subject not in ['数学','物理']:raise ValueError('不支持的学科')
 path=original(data.get('path',''))
 if path.suffix.lower()!='.pdf':raise ValueError('目前仅 PDF 支持按剩余页码导入')
 raw=path.read_bytes();sid=hashlib.sha256(raw).hexdigest()
 if data.get('source_id')!=sid:raise ValueError('文件内容已变化，请刷新文件列表')
 with fitz.open(stream=raw,filetype='pdf') as pdf:
  if pdf.is_encrypted:raise ValueError('不支持加密 PDF')
  total=len(pdf)
 return path,raw,sid,subject,total

def state(sid,subject,total,method="A"):
 qs=[q for q in store.all_rows('questions') if q.get('source',{}).get('id')==sid and q.get('subject','数学')==subject]
 # Explicit empty-page records also allow remaining-page planning.
 retained=set();unknown=0
 for q in qs:
  p=pages(q.get('pages') or q.get('source',{}).get('pages'),total)
  if not p:unknown+=1
  retained|=p
 if unknown:raise ValueError(f'有 {unknown} 道题目缺少可靠来源页码，暂不能安全计算剩余部分，请先核对页码')
 active=set();completed=set()
 from .page_extraction import recorded
 for t in store.all_rows('tasks'):
  b=t.get('bundle',{})
  if not (is_import(t) and (b.get('source_id') or b.get('sha256'))==sid and b.get('subject','数学')==subject):continue
  completed|=current_completed(t,qs,total)
  if t.get('status') in ['queued','running']:
   p=pages(b.get('pages'),total)
   active|=p or set(range(1,total+1))
 return dict(total_pages=total,retained_pages=sorted(retained),active_pages=sorted(active),completed_pages=sorted(completed),remaining_pages=sorted(set(range(1,total+1))-retained-active-completed),uncertain_pages=sorted(retained-active-completed))

def plan(data):
 path,raw,sid,subject,total=source(data)
 return dict(path=data['path'],name=path.name,source_id=sid,subject=subject,**state(sid,subject,total,data.get('method','A')))

def allowed_pages(current,data):
 allowed=set(current['remaining_pages'])
 if data.get('include_uncertain') is True:allowed.update(current['uncertain_pages'])
 return allowed

def submit(data):
 path,raw,sid,subject,total=source(data)
 selected=data.get('pages')
 if not isinstance(selected,list) or not selected or any(type(p) is not int or p<1 or p>total for p in selected):raise ValueError('请选择有效的剩余页码')
 selected=sorted(set(selected))
 with submission_lock:
  current=state(sid,subject,total)
  if not set(selected)<=allowed_pages(current,data):raise ValueError('所选页已完成、正在处理，或尚未确认补查已有题目的页面')
  result=submit_unified(raw,path.name,subject,selected_pages=selected,request_id=uuid.uuid4().hex,generate_solution=data.get('generate_solution'),**({'light_review':data['light_review']} if 'light_review' in data else {}))
 return dict(task_id=result['id'],status=result['status'],pages=selected)

def import_file(data):
 subject=data.get('subject','数学')
 if subject not in ['数学','物理']:raise ValueError('不支持的学科')
 path=original(data.get('path',''));raw=path.read_bytes();sid=hashlib.sha256(raw).hexdigest()
 if data.get('source_id')!=sid:raise ValueError('文件内容已变化，请刷新文件列表')
 with submission_lock:
  if any(q.get('source',{}).get('id')==sid and q.get('subject','数学')==subject for q in store.all_rows('questions')):raise ValueError('此文件已有题目，请改用导入剩余部分或核对现有题目')
  for t in store.all_rows('tasks'):
   b=t.get('bundle',{})
   if is_import(t) and (b.get('source_id') or b.get('sha256'))==sid and b.get('subject','数学')==subject and t.get('status') in ['queued','running']:return dict(task_id=t['id'],status=t['status'],existing=True)
  result=submit_unified(raw,path.name,subject,request_id=uuid.uuid4().hex,generate_solution=data.get('generate_solution'),**({'light_review':data['light_review']} if 'light_review' in data else {}))
 return dict(task_id=result['id'],status=result['status'])
