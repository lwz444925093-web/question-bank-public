import sqlite3,json,time,uuid,os,threading,copy
from contextlib import contextmanager,nullcontext
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=Path(os.environ.get('QUESTION_BANK_DATA',str(ROOT/'data')))

class TaskCancellation(threading.Event):
    """Event-compatible cancellation with a linear boundary against DB commits."""
    def __init__(self):
        super().__init__();self._commit_gate=threading.RLock()
    def set(self):
        # Never held while waiting for SQLite's write lock. A commit already
        # holding this gate completes before cancellation is acknowledged.
        with self._commit_gate:super().set()

_write_context=threading.local()

@contextmanager
def cancellation_scope(cancel):
    previous=getattr(_write_context,'cancel',None)
    _write_context.cancel=cancel
    try:yield
    finally:_write_context.cancel=previous

@contextmanager
def _question_transaction():
    cancel=getattr(_write_context,'cancel',None)
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        gate=getattr(cancel,'_commit_gate',None)
        with gate if gate is not None else nullcontext():
            if cancel and cancel.is_set():raise ValueError('任务已取消，未提交题目')
            yield c
            if cancel and cancel.is_set():raise ValueError('任务已取消，未提交题目')
            # Explicitly commit while still holding the gate; the connection
            # context rolls back the entire revision/counter on an exception.
            c.commit()

class Connection(sqlite3.Connection):
    """A transaction context must release its file descriptor on every exit."""
    def __exit__(self, *args):
        try:return super().__exit__(*args)
        finally:self.close()

def conn():
    c=sqlite3.connect(DATA/'bank.sqlite',timeout=20,factory=Connection); c.row_factory=sqlite3.Row; return c
def process_alive(pid):
    if not pid: return False
    try: os.kill(pid,0); return True
    except OSError: return False
def init():
    DATA.mkdir(exist_ok=True)
    with conn() as c:
        for sql in ['CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, body TEXT)','CREATE TABLE IF NOT EXISTS revisions(id TEXT, revision INTEGER, body TEXT, PRIMARY KEY(id,revision))','CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT)','CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, body TEXT)','CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY, body TEXT)','CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY, body TEXT)']: c.execute(sql)
        for row in c.execute('SELECT * FROM tasks').fetchall():
            d=json.loads(row['body'])
            if d['status'] in ['running','queued'] and not process_alive(d.get('pid')): d.update(status='interrupted',error='服务重启，任务已中断，可人工重试'); c.execute('UPDATE tasks SET body=? WHERE id=?',(json.dumps(d,ensure_ascii=False),row['id']))
def put(table,id,d):
    assert table in ['questions','tasks','cache','exports','settings']
    key='key' if table=='cache' else 'id'
    with conn() as c: c.execute(f'INSERT OR REPLACE INTO {table}({key},body) VALUES(?,?)',(id,json.dumps(d,ensure_ascii=False)))
def get(table,id):
    assert table in ['questions','tasks','cache','exports','settings']
    with conn() as c: r=c.execute(f'SELECT body FROM {table} WHERE {"key" if table=="cache" else "id"}=?',(id,)).fetchone()
    if table=='questions':
        with conn() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='trash'").fetchone() and c.execute('SELECT 1 FROM trash WHERE id=?',(id,)).fetchone():return None
    return json.loads(r[0]) if r else None
def all_rows(table):
    assert table in ['questions','tasks','exports','settings']
    with conn() as c:
        where=" WHERE id NOT IN (SELECT id FROM trash)" if table=='questions' and c.execute("SELECT 1 FROM sqlite_master WHERE name='trash'").fetchone() else ''
        return [json.loads(r[0]) for r in c.execute(f'SELECT body FROM {table}{where} ORDER BY rowid DESC')]
def revision_content(q):
    """Ignore bookkeeping and equivalent optional empty values, not review evidence."""
    ignored={'revision','updated_at','revision_note'}
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if x is not None and x != [] and x != '' and x is not False}
        if isinstance(v,list):return [clean(x) for x in v]
        return v
    return clean({k:v for k,v in q.items() if k not in ignored and not k.startswith('__')})

def save_question(q,expected=None,image_only=False):
    from .text_format import format_blocks
    # Normalize explicit subscript notation for both browser formulas and editable Word export.
    q=copy.deepcopy(q)
    from .prefix_clean import clean_exam_headings
    clean_exam_headings(q)
    from .review_policy import separate_solution_notes
    had_issues=bool(q.get('issues'))
    separate_solution_notes(q)
    if had_issues and not q.get('issues') and q.get('processing_status')=='complete':q['review_status']='approved'
    for key in ['stem','ai_answer','ai_explanation','human_answer','human_explanation','source_answer','source_explanation']:
        if key in q:q[key]=format_blocks(q[key])
    for key in ['options','subquestions']:
        if key in q:q[key]=[{**part,'blocks':format_blocks(part['blocks'])} for part in q[key]]
    from .table_normalize import normalize as normalize_tables
    normalize_tables(q)
    from .figure_workflow import sync
    sync(q)
    with _question_transaction() as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='trash'").fetchone() and c.execute('SELECT 1 FROM trash WHERE id=?',(q['id'],)).fetchone():raise ValueError('题目已移入回收站，不能修改')
        row=c.execute('SELECT body FROM questions WHERE id=?',(q['id'],)).fetchone(); old=json.loads(row[0]) if row else None
        if old and expected!=old['revision']: raise ValueError('修订冲突，请刷新后重试')
        if old and not image_only and any(old[k]!=q[k] for k in ['stem','options','subquestions']) and q.get('issues'): q['review_status']='pending'
        if old and old.get('source_snapshot') is not None:q['source_snapshot']=old['source_snapshot']
        q['created_at']=old.get('created_at',q.get('created_at',time.time())) if old else q.get('created_at',time.time())
        # Stable across edits, type changes, restores and deletion; serialize allocation in this transaction.
        if old and old.get('bank_number'):q['bank_number']=old['bank_number']
        else:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            month=datetime.fromtimestamp(q['created_at'],ZoneInfo('Asia/Shanghai')).strftime('%y%m')
            key='question_number_sequence:'+month
            counter=c.execute('SELECT body FROM settings WHERE id=?',(key,)).fetchone()
            sequence=(json.loads(counter[0])['value'] if counter else 0)+1
            if sequence>99999:raise ValueError('本月题目编号已满，未保存')
            q['bank_number']=month+f'{sequence:05d}'
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps({'value':sequence})))
        if old and revision_content(old)==revision_content(q):return old
        q['revision']=(old['revision'] if old else 0)+1; q['updated_at']=time.time()
        body=json.dumps(q,ensure_ascii=False); c.execute('INSERT OR REPLACE INTO questions VALUES(?,?)',(q['id'],body)); c.execute('INSERT INTO revisions VALUES(?,?,?)',(q['id'],q['revision'],body))
    return q
