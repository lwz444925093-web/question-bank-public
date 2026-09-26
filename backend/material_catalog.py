"""Read-only material directory inventory, matched by content, never filename."""
import hashlib,os
from pathlib import Path
from functools import lru_cache
from collections import defaultdict
import fitz
from . import store
from .file_dates import added_time
SUPPORTED={'.pdf','.txt','.docx','.png','.jpg','.jpeg'}

def root():
 configured=os.environ.get('QUESTION_BANK_MATERIALS_DIR')
 if configured:return Path(configured).expanduser().resolve()
 desktop=store.ROOT.parents[1]/'导入材料'
 return desktop.resolve() if desktop.is_dir() else (store.ROOT/'input').resolve()

def safe_path(relative):
 base=root();p=(base/relative).resolve()
 try:p.relative_to(base)
 except ValueError:raise ValueError('目录必须位于导入材料目录内')
 return p

def original(relative):
 p=safe_path(relative)
 if not p.is_file() or p.suffix.lower() not in SUPPORTED:raise ValueError('材料文件不存在或格式不支持')
 return p

@lru_cache(maxsize=2048)
def inspect(path,size,mtime,ctime):
 p=Path(path);h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 count=None;error=''
 if p.suffix.lower()=='.pdf':
  try:
   with fitz.open(p) as pdf:
    if pdf.is_encrypted:error='PDF 已加密，页数无法读取'
    else:count=len(pdf)
  except Exception:error='PDF 页数无法读取，请检查文件'
 return h.hexdigest(),count,error

def pages(values,total=None):
 return {p for p in (values or []) if type(p) is int and p>0 and (total is None or p<=total)}

def is_import(t):
 b=t.get('bundle',{})
 if b.get('operation') or t.get('review_task') or b.get('question_ids'):return False
 # Old maintenance jobs copied a PDF bundle but were not imports.
 if not Path(b.get('display_name','')).suffix.lower() in SUPPORTED and any(word in b.get('display_name','') for word in ['检查独立水印','SVG重绘验收']):return False
 return bool(b.get('original')) and bool(b.get('source_id') or b.get('sha256'))

def current_completed(task,qs,total=None):
 """Only retained questions and explicit empty pages justify current coverage."""
 from .page_extraction import recorded
 done=recorded(task,total)
 empty=pages(task.get('page_extraction',{}).get('empty_pages'),total)&done
 ids={q['id'] for q in qs};expected=set(task.get('question_ids',[]))
 if expected and not expected<=ids:return empty
 retained=set().union(*(pages(q.get('pages') or q.get('source',{}).get('pages'),total) for q in qs)) if qs else set()
 return empty|(done&retained)

def summarize(qs,tasks,total):
 retained=set().union(*(pages(q.get('pages') or q.get('source',{}).get('pages'),total) for q in qs)) if qs else set()
 submitted=set().union(*(pages(t.get('bundle',{}).get('pages'),total) for t in tasks)) if tasks else set()
 confirmed=set();completed=set()
 from .page_extraction import recorded
 for t in tasks:
  completed|=current_completed(t,qs,total)
  coverage=t.get('coverage') or {}
  if t.get('status')=='succeeded' and coverage.get('status')=='confirmed':confirmed|=pages(coverage.get('confirmed_pages'),total)
 active=[t for t in tasks if t.get('status') in ['queued','running']]
 ordered=sorted(tasks,key=lambda t:t.get('created_at',0),reverse=True);latest=ordered[0] if ordered else None
 status='not_imported'
 if qs:status='has_questions'
 elif tasks:status='history_only'
 if not qs and latest and latest.get('status') in ['failed','partial','cancelled','interrupted']:status='incomplete'
 empty_pages=set().union(*(pages(t.get('page_extraction',{}).get('empty_pages'),total) for t in tasks)) if tasks else set()
 if total and len(empty_pages)==total and not qs:status='parsed_empty'
 if active:status='processing'
 pending=sum(q.get('review_status')!='approved' for q in qs)
 records=[dict(id=t['id'],status=t.get('status'),pages=sorted(pages(t.get('bundle',{}).get('pages'),total)),saved_count=t.get('saved_count',len(t.get('question_ids',[]))),created_at=t.get('created_at'),finished_at=t.get('finished_at'),reason=t.get('error') or ('部分处理未完成' if t.get('status')=='partial' else '')) for t in ordered]
 return dict(status=status,question_count=len(qs),pending_count=pending,empty_pages=sorted(empty_pages&completed),completed_pages=sorted(completed),retained_pages=sorted(retained),submitted_pages=sorted(submitted),confirmed_pages=sorted(confirmed&completed),submitted_without_questions=sorted(submitted-retained-completed),unsubmitted_pages=sorted(set(range(1,total+1))-submitted-retained) if total else [],coverage_confirmed=bool(total and len(confirmed&completed)==total),unknown_page_questions=sum(not pages(q.get('pages') or q.get('source',{}).get('pages'),total) for q in qs) if total else 0,tasks=records)

def listing(subject='数学',directory=None,recursive=True,method=None):
 if subject not in ['数学','物理']:raise ValueError('不支持的学科')
 base=root()
 if not base.is_dir():return dict(root_name=base.name,directory='',directories=[],files=[],error='材料目录不存在')
 dirs=[''];all_files=[];errors=[]
 def on_error(exc):errors.append('部分子目录无法读取：'+str(Path(exc.filename).name))
 for current,subdirs,filenames in os.walk(base,followlinks=False,onerror=on_error):
  subdirs[:]=sorted(d for d in subdirs if not d.startswith('.') and not (Path(current)/d).is_symlink())
  for d in subdirs:dirs.append((Path(current)/d).relative_to(base).as_posix())
  for name in sorted(filenames):
   p=Path(current)/name
   if not p.is_symlink() and not name.startswith('.') and p.suffix.lower() in SUPPORTED:all_files.append(p)
 if directory is None:directory=subject if subject in dirs else ''
 chosen=safe_path(directory)
 if not chosen.is_dir():raise ValueError('材料子目录不存在')
 groups=defaultdict(list);task_groups=defaultdict(list);other=defaultdict(set)
 for q in store.all_rows('questions'):
  sid=q.get('source',{}).get('id');s=q.get('subject','数学')
  if s==subject:groups[sid].append(q)
  elif sid:other[sid].add(s)
 for t in store.all_rows('tasks'):
  if not is_import(t):continue
  b=t['bundle'];sid=b.get('source_id') or b.get('sha256');s=b.get('subject','数学')
  if s==subject:task_groups[sid].append(t)
  elif sid:other[sid].add(s)
 result=[]
 for p in all_files:
  if (not recursive and p.parent!=chosen) or (recursive and chosen!=p.parent and chosen not in p.parents):continue
  row=dict(path=p.relative_to(base).as_posix(),name=p.name,folder=p.parent.relative_to(base).as_posix(),kind=p.suffix[1:].upper())
  try:
   stat=p.stat();sid,total,error=inspect(str(p),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
   arrived,basis=added_time(p,stat)
   row.update(added_at=arrived,added_at_basis=basis,size=stat.st_size,source_id=sid,total_pages=total,file_error=error,other_subjects=sorted(other[sid]),**summarize(groups[sid],task_groups[sid],total))
  except OSError:
   row.update(file_error='无法读取文件',total_pages=None,other_subjects=[],**summarize([],[],None))
  result.append(row)
 result.sort(key=lambda row:(-row.get('added_at',0),row['path'].casefold()))
 return dict(root_name=base.name,directory=chosen.relative_to(base).as_posix().replace('.', '') if chosen==base else chosen.relative_to(base).as_posix(),directories=sorted(dirs),files=result,error='；'.join(errors))
