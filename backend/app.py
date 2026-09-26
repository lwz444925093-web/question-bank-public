from typing import Optional
import json,uuid,copy,os
from fastapi import FastAPI,UploadFile,File,Form,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from . import store,tasks
from .inputs import prepare
from .model import Extracted,Block
from .exporter import export_doc,math_xml,answer_blocks,explanation_blocks
from . import trash
PRESERVE_DATABASE=os.environ.get('QUESTION_BANK_NO_BACKGROUND_DB_WRITES')=='1'
if PRESERVE_DATABASE:
    # Deployment mode opens an existing database read-only: no migrations,
    # interrupted-task recovery or automatic expiry writes at startup.
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect((store.DATA/'bank.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as c:
        tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'questions','revisions','tasks','cache','exports','settings','trash'}<=tables:
            raise RuntimeError('现有数据库结构不完整；保护模式不会修改数据库')
else:
    store.init()
    trash.init()
app=FastAPI()
from .d_shadow_routes import router as d_shadow_router
app.include_router(d_shadow_router)
@app.on_event('startup')
async def warm_readable_content():
    # Validate legacy formula presentation once while starting, so opening the
    # bank does not wait on individual local Word-formula conversions.
    import asyncio
    from .text_format import format_question_content
    def warm():
        for question in store.all_rows('questions'):
            format_question_content(question)
    await asyncio.to_thread(warm)

@app.on_event('startup')
async def start_trash_cleanup():
    if PRESERVE_DATABASE:return
    import asyncio
    async def cleanup():
        while True:
            await asyncio.to_thread(trash.purge)
            await asyncio.sleep(60)
    app.state.trash_cleanup=asyncio.create_task(cleanup())
@app.on_event('shutdown')
async def stop_trash_cleanup():
    if hasattr(app.state,'trash_cleanup'):app.state.trash_cleanup.cancel()
@app.get('/api/categories')
def category_tree():
    from .categories import get
    return get()
@app.post('/api/categories')
def category_change(data:dict):
    from .categories import mutate
    return mutate(data)
@app.get('/api/trash')
def trash_list():return trash.listed()
@app.post('/api/trash/move')
def trash_move(data:dict):return trash.move(data.get('ids'))
@app.post('/api/trash/restore')
def trash_restore(data:dict):return trash.restore(data.get('ids'))

@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','').split(':')[0]
    origin=request.headers.get('origin')
    if host not in ['127.0.0.1','localhost','testserver'] or (origin and origin!=str(request.base_url).rstrip('/')): return JSONResponse({'detail':'仅允许同源本地访问'},status_code=403)
    if os.environ.get('QUESTION_BANK_D_SHADOW_ONLY')=='1' and request.method not in ['GET','HEAD','OPTIONS'] and request.url.path!='/api/import' and not request.url.path.startswith('/api/d-shadow/'):
        return JSONResponse({'detail':'隔离服务禁止正式持久化操作'},status_code=403)
    return await call_next(request)
@app.exception_handler(ValueError)
async def bad(request,exc): return JSONResponse({'detail':str(exc)},status_code=422)
@app.get('/api/tasks/{id}/evidence')
def task_evidence(id:str):
    task=store.get('tasks',id)
    if not task:raise HTTPException(404)
    if not __import__('re').fullmatch(r'[a-f0-9]{32}',id):raise HTTPException(400)
    folder=store.DATA/'tasks'/id
    path=next((folder/name for name in ['extraction-raw.private.txt','response.private.txt','final.json'] if (folder/name).is_file()),None)
    raw=path.read_text(errors='replace') if path else ''
    if not raw and (folder/'opencode.private.jsonl').is_file():
        recovered=[]
        for line in (folder/'opencode.private.jsonl').read_text(errors='replace').splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('type')=='text':recovered.append(str(event.get('part',{}).get('text','')))
        raw='以下为未完成的原始回复片段，不代表已通过校验：\n'+'\n'.join(recovered)
    return dict(raw=raw[:100000],truncated=len(raw)>100000,error=task.get('error',''),source_id=task['bundle'].get('source_id'),assets=list(dict.fromkeys(task['bundle'].get('assets',[])+([task['bundle']['original']] if task['bundle'].get('original') else []))),status=task['status'])

@app.get('/api/changes')
def changes(request:Request):
    from fastapi.responses import StreamingResponse
    from .change_events import stream
    return StreamingResponse(stream(request),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.get('/api/materials')
def material_list(subject:str='数学',directory:str=None,recursive:bool=True,method:str=None):
    from .material_catalog import listing
    return listing(subject,directory,recursive,method)
@app.post('/api/materials/import')
def material_import(data:dict):
    from .remaining_import import import_file
    return import_file(data)
@app.post('/api/materials/remaining/plan')
def remaining_plan(data:dict):
    from .remaining_import import plan
    return plan(data)
@app.post('/api/materials/remaining/submit')
def remaining_submit(data:dict):
    from .remaining_import import submit
    return submit(data)
@app.get('/api/materials/file')
def material_file(path:str):
    from .material_catalog import original
    p=original(path)
    return FileResponse(p,filename=p.name,content_disposition_type='inline')

@app.get('/api/light-review/settings')
def light_review_settings():return store.get('settings','light_review_import') or {'enabled':True}
@app.put('/api/light-review/settings')
def light_review_settings_save(data:dict):
    if type(data.get('enabled')) is not bool:raise ValueError('开关必须为布尔值')
    store.put('settings','light_review_import',{'enabled':data['enabled']});return data
@app.get('/api/light-review/latest')
def light_review_latest(subject:str='数学'):
    from .light_review_batch import get
    rows=[t for t in store.all_rows('tasks') if t.get('light_review_batch') and t.get('subject')==subject]
    return get(max(rows,key=lambda t:t['created_at'])['id']) if rows else None
@app.post('/api/light-review')
def light_review_start(data:dict):
    from .light_review_batch import submit
    return submit(data.get('subject','数学'))
@app.get('/api/light-review/{id}')
def light_review_status(id:str):
    from .light_review_batch import get
    return get(id)
@app.post('/api/light-review/{id}/confirm')
def light_review_confirm(id:str,data:dict):
    from .light_review_batch import confirm
    return confirm(id,data.get('confirmed'),data.get('question_ids'))

@app.get('/api/questions')
def questions():
    from .text_format import format_question_content
    return [format_question_content(q) for q in sorted(store.all_rows('questions'),key=lambda q:(q.get('created_at',0),q['id']),reverse=True)]
@app.put('/api/questions/{id}')
def save(id:str,q:dict):
    old=store.get('questions',id)
    if not old: raise HTTPException(404)
    values={k:q[k] for k in Extracted.model_fields if k in q}
    if 'estimated_difficulty' in old and 'difficulty' not in values:values['difficulty']=''
    core=Extracted.model_validate(values).model_dump()
    if 'estimated_difficulty' in old:core.pop('difficulty',None)
    result=dict(old,**core,human_answer=[Block.model_validate(b).model_dump() for b in q.get('human_answer',[])])
    result['answer_edited']=bool(q.get('answer_edited',False))
    result['explanation_edited']=bool(q.get('explanation_edited',False))
    result['answer_is_complete']=bool(q.get('answer_is_complete',False))
    result['human_explanation']=[Block.model_validate(b).model_dump() for b in q.get('human_explanation',[])]
    result['review_status']=q.get('review_status','pending')
    if result['review_status'] not in ['pending','approved']: raise ValueError('审核状态错误')
    if q.get('approve_review') is True:
        from .review_policy import approve_question
        approve_question(result,include_figures=q.get('approve_full_review') is True)
    from .text_format import format_question_content
    prior_content=format_question_content(old)
    comparable_content=format_question_content(result)
    if result.get('figure_workflow_version')==2 and not q.get('approve_review') and any(prior_content[k]!=comparable_content[k] for k in ['stem','options','subquestions']):
        result['content_status']='needs_review'
        result['manual_full_review']=False
    return store.save_question(result,q['revision'])
@app.get('/api/questions/{id}/crop')
def crop_choices(id:str):
    from .manual_crop import choices
    return choices(id)
@app.get('/api/questions/{id}/crop/source/{page}')
def crop_source_page(id:str,page:int):
    from .manual_crop import source_page
    return FileResponse(source_page(id,page))
@app.post('/api/questions/{id}/crop/preview')
def crop_preview(id:str,data:dict):
    from .manual_crop import preview
    return preview(id,data)
@app.post('/api/questions/{id}/crop/apply')
def crop_apply(id:str,data:dict):
    from .manual_crop import apply
    return apply(id,data)
@app.post('/api/questions/{id}/crop/save')
def crop_save(id:str,data:dict):
    from .manual_crop import save_batch
    return save_batch(id,data)
@app.post('/api/questions/{id}/crop/undo')
def crop_undo(id:str,data:dict):
    from .manual_crop import undo
    return undo(id,data)
@app.get('/api/questions/{id}/revisions')
def revisions(id:str):
    with store.conn() as c: return [json.loads(r[0]) for r in c.execute('SELECT body FROM revisions WHERE id=? ORDER BY revision DESC',(id,))]
@app.post('/api/questions/{id}/review')
def manual_review(id:str,data:dict):
    from .manual_review import submit
    return submit(id,data)
@app.post('/api/questions/{id}/review/start')
def start_review(id:str,data:dict):
    from .manual_review import submit
    return submit(id,data)
@app.get('/api/questions/{id}/review/latest')
def latest_review(id:str):
    from .manual_review import latest
    return latest(id)
@app.post('/api/questions/{id}/review/{pid}/stop')
def stop_review(id:str,pid:str):
    from .manual_review import stop
    return stop(id,pid)
@app.post('/api/questions/{id}/review/apply')
def apply_review(id:str,data:dict):
    from .manual_review import apply
    return apply(id,data)
@app.post('/api/questions/{id}/restore')
def restore_revision(id:str,data:dict):
    from .manual_review import restore
    return restore(id,data)
@app.post('/api/import')
async def upload(file:UploadFile=File(...),start:int=Form(1),end:int=Form(0),subject:str=Form("数学"),question_regions:str=Form(''),detail_regions:str=Form(''),mode:str=Form('legacy'),method:str=Form('A'),generate_solution:Optional[bool]=Form(None),light_review:Optional[bool]=Form(None)):
    if subject not in ['数学','物理']: raise ValueError('不支持的学科')
    import asyncio
    raw=await file.read()
    if os.environ.get('QUESTION_BANK_D_SHADOW_ONLY')=='1':mode='d_shadow'
    if mode=='d_shadow':
        if question_regions or detail_regions:raise ValueError('D使用完整原页，不接受模型或人工预裁输入')
        from .d_shadow import submit
        return submit(raw,file.filename or '',subject,start,end)
    if mode!='legacy':raise ValueError('不支持的导入模式')
    if question_regions or detail_regions:raise ValueError('统一导入使用完整原文件，不接收预裁区域')
    from .unified_import import submit
    return await asyncio.to_thread(submit,raw,file.filename or '',subject,start,end,**({'generate_solution':generate_solution} if generate_solution is not None else {}),**({'light_review':light_review} if light_review is not None else {}))
@app.post('/api/import/preview')
async def preview_import(file:UploadFile=File(...)):
    import asyncio
    bundle=await asyncio.to_thread(prepare,await file.read(),file.filename or '')
    from .docx_preview import render
    html=await asyncio.to_thread(render,bundle)
    return {'html':html,'source_id':bundle['source_id'],'assets':bundle['assets']}
@app.post('/api/text')
def text(data:dict):
    subject=data.get('subject','数学')
    if subject not in ['数学','物理']: raise ValueError('不支持的学科')

    bundle=prepare(str(data.get('text','')).encode(),'pasted.txt');bundle['subject']=subject;return tasks.submit(bundle)
@app.get('/api/tasks')
def task_list():
    from .manual_review import task_records
    from .task_summary import enrich
    return sorted(enrich(store.all_rows('tasks')+task_records(),store.all_rows('questions')),key=lambda r:r.get('created_at') or 0,reverse=True)
@app.get('/api/tasks/{id}/cost')
def task_live_cost(id:str):
    from .task_summary import enrich
    task=store.get('tasks',id)
    if not task:raise HTTPException(404)
    result=enrich([task],[])[0]
    return dict(status=task.get('status'),task_cost=result['task_cost'])

@app.get('/api/tasks/{id}/d-evidence')
def d_evidence(id:str):
    task=store.get('tasks',id)
    if not task or task.get('import_method')!='D':raise HTTPException(404)
    path=store.DATA/'tasks'/id/'d-stage'/'result.json'
    if not path.is_file():raise HTTPException(404)
    return json.loads(path.read_text())
@app.post('/api/tasks/{id}/cancel')
def cancel(id:str):
    event=tasks.cancellations.get(id)
    if event: event.set()
    return {'ok':True}
@app.post('/api/tasks/{id}/retry')
def retry(id:str,body:dict=None):
    task=store.get('tasks',id)
    if not task: raise HTTPException(404)
    if task['status'] not in ['failed','partial','cancelled','interrupted']: raise ValueError('当前任务不能重试')
    if task.get('import_method')=='D':
        from .d_import import retry as retry_d
        return retry_d(task,pages=(body or {}).get('pages'))
    bundle=dict(task['bundle'],_unit_key=task.get('unit_key',task['key']),_budget_id=task.get('budget_id',id),_provider_config=task.get('provider_config',{}))
    if (store.DATA/'tasks'/id/'extracted.private.json').is_file():bundle['_resume_extracted_from']=id
    if task.get('provider_config',{}).get('provider')=='opencode' and (store.DATA/'tasks'/id/'final.json').is_file() and any(word in task.get('error','') for word in ['结构','公式','格式']):
        bundle['repair_from_task']=id
    if (store.DATA/'tasks'/id/'clean'/'final.json').is_file():
        bundle['repair_from_task']=id
        bundle['resume_clean_from_task']=id
    retry_task=tasks.submit(bundle)
    task['recovered_by']=retry_task['id'];store.put('tasks',id,task)
    return retry_task
@app.post('/api/figures/rebuild')
def rebuild_figures(data:dict):
    from .diagrams import prepare_rebuild
    if tasks.config().get('provider')!='opencode':raise ValueError('请先在设置中选择 OpenCode 导入')
    bundle=prepare_rebuild(str(data.get('source_id','')),str(data.get('subject','物理')),data.get('question_ids'))
    if data.get('feedback'):bundle['user_feedback']=str(data['feedback'])
    if data.get('crop_only'):bundle['crop_only']=True
    return tasks.submit(bundle)
@app.get('/api/source/{id}/{name}')
def source(id:str,name:str):
    if len(id)!=64 or any(c not in '0123456789abcdef' for c in id) or '/' in name or '\\' in name or name.startswith('.'): raise HTTPException(400)
    p=store.DATA/'sources'/id/name
    if not p.is_file(): raise HTTPException(404)
    return FileResponse(p)
@app.get('/api/templates')
def templates(): return store.all_rows('settings') if False else store.get('settings','templates') or []
@app.post('/api/templates')
def template(params:dict):
    data=store.get('settings','templates') or []; data.append(params); store.put('settings','templates',data); return data
@app.post('/api/export')
def export(data:dict):
    if not 1<=len(data.get('items',[]))<=30: raise ValueError('请选择1至30道题')
    params=data['params']
    if params.get('kind') not in ['student','teacher','lesson']: raise ValueError('文档类型错误')
    if not 1<=float(params.get('margin',2))<=5 or not 8<=float(params.get('size',11))<=24: raise ValueError('页边距或字号超范围')
    items=[]
    for item in data['items']:
        q=store.get('questions',item['id'])
        if not q: raise ValueError('题目不存在')
        from .figure_workflow import can_use
        if not can_use(q):
            raise ValueError('题目后处理或题图定位尚未完成，请先核对来源；审阅参考不能进入正式出卷')
        from .text_format import format_question_content
        items.append(dict(question=format_question_content(q),score=item.get('score',5),blank=item.get('blank',2)))
    problems=[]
    for item in items:
        q=item['question']; bs=q['stem']+[b for p in q['options']+q['subquestions'] for b in p['blocks']]
        if params['kind']!='student': bs+=answer_blocks(q); bs+=explanation_blocks(q)
        for b in bs:
            try:
                if b['kind']=='geometry' and not params.get('draft'): raise ValueError('几何图Mac Word逐对象编辑待人工验收')
                if b['kind']=='image':
                    from .export_images import image_path
                    image_path(q.get('source'),b['asset'])
                if b['kind']=='equation': math_xml(b['latex'])
                for s in b['spans']+[s for row in b['rows'] for cell in row for s in cell]:
                    if s['kind']=='math': math_xml(s['text'])
            except Exception as e: problems.append('题号 '+q['original_number']+'：'+str(e))
    if problems: raise ValueError('；'.join(problems))
    id=uuid.uuid4().hex; path=store.DATA/'exports'/(id+'.docx')
    path.parent.mkdir(parents=True,exist_ok=True)
    try: export_doc(items,params,path)
    except Exception as e: raise ValueError('导出阻止：'+str(e))
    snapshot=dict(id=id,items=items,params=params,warnings=['字体可用性及Word版面待人工确认']+(['草稿：几何图Mac Word编辑待验收'] if params.get('draft') else []))
    store.put('exports',id,snapshot); return dict(id=id,url='/api/export/'+id,warnings=snapshot['warnings'])
@app.get('/api/export/{id}/document')
def export_document(id:str):
    from .editable_export import get
    return get(id)
@app.post('/api/export/{id}/document')
def save_export_document(id:str,data:dict):
    from .editable_export import save
    return save(id,data)
@app.get('/api/exports')
def exports(): return store.all_rows('exports')
@app.get('/api/export/{id}')
def download(id:str):
    if not store.get('exports',id): raise HTTPException(404)
    return FileResponse(store.DATA/'exports'/(id+'.docx'),filename=id+'.docx')
@app.post('/api/export/{id}/preview')
def export_preview(id:str):
    from .export_preview import render
    return render(id)
@app.get('/api/export/{id}/preview/{page}')
def export_preview_page(id:str,page:int):
    if len(id)!=32 or any(c not in '0123456789abcdef' for c in id) or not store.get('exports',id): raise HTTPException(404)
    path=store.DATA/'exports'/(id+'-preview')/('page-'+str(page)+'.png')
    if page<1 or not path.is_file(): raise HTTPException(404)
    return FileResponse(path)
from . import deepseek
@app.get('/api/deepseek/settings')
def deepseek_settings(): return deepseek.public_settings()
@app.put('/api/deepseek/settings')
def deepseek_save(data:dict): return deepseek.save_settings(data)
@app.post('/api/deepseek/generate')
def deepseek_generate(data:dict): return deepseek.generate(data)
@app.get('/api/opencode/sessions')
def opencode_sessions(): return store.get('settings','opencode_sessions') or []
@app.post('/api/opencode/open')
def opencode_open(data:dict): return deepseek.open_window(data.get('session_id'))

@app.get('/api/questions/{id}/similar')
def similar(id:str):
    from .similarity import compare
    q=store.get('questions',id)
    if not q:raise HTTPException(404)
    return compare(q)
@app.post('/api/questions/{id}/similar/ignore')
def ignore_similar(id:str,data:dict):
    from .similarity import compare
    q=store.get('questions',id)
    if not q or q['revision']!=data.get('revision'):raise ValueError('题目已修改，请刷新相似题')
    candidate=next((c for c in compare(q)['candidates'] if c['id']==data.get('other_id') and c['revision']==data.get('other_revision')),None)
    if not candidate:raise ValueError('候选内容已变化，请重新对照')
    store.put('settings',candidate['ignore_key'],dict(ignored=True))
    return {'ok':True}
@app.post('/api/questions/{id}/prefix')
def prefix_action(id:str,data:dict):
    from .prefix_clean import preview,undo
    q=store.get('questions',id)
    if not q or q['revision']!=data.get('revision'):raise ValueError('修订冲突，请刷新后重试')
    action=data.get('action','preview')
    if action=='preview':return preview(q)
    if action not in ['apply','undo']:raise ValueError('未知清洗操作')
    derived=undo(q) if action=='undo' else preview(q)['question']
    derived.setdefault('source_snapshot',{k:copy.deepcopy(q[k]) for k in Extracted.model_fields if k in q})
    derived['revision_note']='撤销前缀清洗' if action=='undo' else '采用前缀清洗'
    return store.save_question(derived,q['revision'],image_only=True)

@app.get('/api/duplicates')
def duplicate_scan(subject:str='数学'):
    from .duplicate_index import scan
    return scan(subject)
@app.post('/api/duplicates/ignore')
def duplicate_ignore(data:dict):
    from .duplicate_index import dismiss
    return dismiss(data)
@app.post('/api/duplicates/merge')
def duplicate_merge(data:dict):
    from .duplicate_index import merge
    return merge(data)

app.mount('/',StaticFiles(directory=os.environ.get('QUESTION_BANK_FRONTEND',str(store.ROOT/'frontend'/'dist')),html=True),name='frontend')
