"""Optional per-development-run ledger. Not a permanent application quota."""
import fcntl,json,os,time,uuid
from pathlib import Path
def change(fn):
 name=os.environ.get('QUESTION_BANK_RUN_LEDGER')
 if not name:return None
 with Path(name).open('r+') as f:
  fcntl.flock(f.fileno(),fcntl.LOCK_EX);data=json.load(f);value=fn(data)
  f.seek(0);json.dump(data,f,ensure_ascii=False,indent=2);f.truncate();f.flush();os.fsync(f.fileno());return value

def reserve(model,role='worker'):
 def write(data):
  if len(data['attempts'])>=data['limit']:raise ValueError('本轮真实诊断预算耗尽，未发出请求')
  id=role+'-'+uuid.uuid4().hex
  data['attempts'].append(dict(id=id,role=role,status='started',time=time.time(),model=model,upstream_calls=None))
  return id
 return change(write)
def finish(id,**values):
 if id:
  def write(data):
   row=next(r for r in data['attempts'] if r['id']==id);row.update(values)
  change(write)
