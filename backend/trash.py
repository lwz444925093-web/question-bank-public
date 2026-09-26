"""Recoverable question deletion; shared source documents are never removed."""
import json,time
from . import store
RETENTION=7*24*3600

def init():
    with store.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS trash(id TEXT PRIMARY KEY, deleted_at REAL, expires_at REAL)')

def purge():
    with store.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        ids=[r[0] for r in c.execute('SELECT id FROM trash WHERE expires_at<=?',(time.time(),))]
        for id in ids:
            c.execute('DELETE FROM questions WHERE id=?',(id,))
            c.execute('DELETE FROM revisions WHERE id=?',(id,))
            for row in c.execute("SELECT id,body FROM settings WHERE id LIKE 'review-%'").fetchall():
                record=json.loads(row['body'])
                if record.get('question_id')==id:c.execute('DELETE FROM settings WHERE id=?',(row['id'],))
        # Keep the ID tombstone so a late AI worker cannot recreate a deleted question.

def listed():
    purge()
    with store.conn() as c:
        return [dict(json.loads(r['body']),deleted_at=r['deleted_at'],expires_at=r['expires_at']) for r in c.execute('SELECT q.body,t.deleted_at,t.expires_at FROM trash t JOIN questions q ON q.id=t.id ORDER BY t.deleted_at DESC')]

def move(ids):
    if not isinstance(ids,list) or not ids or not all(isinstance(x,str) for x in ids):raise ValueError('请选择要删除的题目')
    ids=list(dict.fromkeys(ids)); now=time.time()
    with store.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        for id in ids:
            if not c.execute('SELECT 1 FROM questions WHERE id=?',(id,)).fetchone():raise ValueError('部分题目已不存在，请刷新')
        for id in ids:c.execute('INSERT OR IGNORE INTO trash VALUES(?,?,?)',(id,now,now+RETENTION))
    return {'count':len(ids)}

def restore(ids):
    purge()
    if not isinstance(ids,list) or not ids:raise ValueError('请选择要恢复的题目')
    with store.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        for id in ids:
            if not c.execute('SELECT 1 FROM trash t JOIN questions q ON t.id=q.id WHERE t.id=? AND t.expires_at>?',(id,time.time())).fetchone():raise ValueError('题目已过期或已恢复，请刷新')
        for id in ids:c.execute('DELETE FROM trash WHERE id=?',(id,))
    return {'count':len(ids)}
