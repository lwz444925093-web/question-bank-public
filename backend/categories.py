"""Editable category tree plus many-to-many direct question placements.
Ancestor membership is derived, never duplicated in question content/revisions.
"""
import copy,hashlib,json,uuid
from . import store
KEY='library-categories-v1'

def child_id(parent,name):return 'cat-'+hashlib.sha256((str(parent)+'/'+name).encode()).hexdigest()[:20]

def hydrate(saved,questions):
    data=copy.deepcopy(saved or {'version':0,'nodes':[],'placements':{}});nodes={n['id']:n for n in data['nodes']}
    def ensure(name,parent=None):
        existing=next((n['id'] for n in nodes.values() if n['name']==name and n['parentId']==parent and not n.get('archived')),None)
        if existing:return existing
        identity=child_id(parent,name)
        if identity not in nodes:nodes[identity]={'id':identity,'name':name,'parentId':parent,'archived':bool(nodes.get(parent,{}).get('archived'))}
        return identity
    roots={s:ensure(s) for s in ['数学','物理']}
    if not saved:
        for root in roots.values():
            for grade in ['七年级','八年级','九年级','高一','高二','高三']:ensure(grade,root)
    for q in questions:
        if q['id'] in data['placements']:continue
        root=roots.get(q.get('subject','数学')) or ensure(q.get('subject') or '其他')
        grade=q.get('grade') or '未分年级';grade={'7年级':'七年级','8年级':'八年级','9年级':'九年级','初一':'七年级','初二':'八年级','初三':'九年级'}.get(grade,grade)
        parent=ensure(grade,root) if grade else root
        tags=[str(k).strip() for k in q.get('knowledge',[]) if str(k).strip()]
        data['placements'][q['id']]=list(dict.fromkeys(ensure(k,parent) for k in tags)) or [parent]
    data['nodes']=list(nodes.values());return data

def get():return hydrate(store.get('settings',KEY),store.all_rows('questions'))

def mutate(data):
    with store.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT body FROM settings WHERE id=?',(KEY,)).fetchone()
        questions=[json.loads(r[0]) for r in c.execute('SELECT body FROM questions WHERE id NOT IN (SELECT id FROM trash)')]
        state=hydrate(json.loads(row[0]) if row else None,questions)
        if data.get('version')!=state['version']:raise ValueError('分类已被更新，请刷新后重试')
        nodes={n['id']:n for n in state['nodes']};op=data.get('operation');identity=data.get('id');node=nodes.get(identity)
        def descendants(root):
            found={root}
            while True:
                more={n['id'] for n in nodes.values() if n['parentId'] in found}
                if more<=found:return found
                found|=more
        if op in ['create','rename','move']:
            name=str(data.get('name','')).strip()
            if op in ['create','rename'] and not 1<=len(name)<=80:raise ValueError('分类名称需要1至80个字符')
            parent=data.get('parentId')
            if op in ['create','move'] and parent is not None and (parent not in nodes or nodes[parent].get('archived')):raise ValueError('上级分类不存在')
            if op=='create':
                identity=uuid.uuid4().hex;nodes[identity]={'id':identity,'name':name,'parentId':parent,'archived':False}
            else:
                if not node:raise ValueError('分类不存在')
                if op=='rename':node['name']=name
                else:
                    if parent in descendants(identity):raise ValueError('不能把分类放到自身或子分类里面')
                    node['parentId']=parent
        elif op in ['archive','restore']:
            if not node:raise ValueError('分类不存在')
            for key in descendants(identity):nodes[key]['archived']=op=='archive'
            if op=='restore':
                parent=node['parentId']
                while parent:
                    nodes[parent]['archived']=False;parent=nodes[parent]['parentId']
        elif op in ['assign','unassign']:
            if not node or node.get('archived'):raise ValueError('分类不存在')
            ids=data.get('questionIds');valid={q['id'] for q in questions}
            if not isinstance(ids,list) or not ids or len(ids)>1000 or any(qid not in valid for qid in ids):raise ValueError('请选择现有题目')
            for qid in ids:
                before=state['placements'].setdefault(qid,[])
                state['placements'][qid]=list(dict.fromkeys(before+[identity])) if op=='assign' else [v for v in before if v!=identity]
        else:raise ValueError('不支持的分类操作')
        state.update(nodes=list(nodes.values()),version=state['version']+1)
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(KEY,json.dumps(state,ensure_ascii=False)))
    return state
