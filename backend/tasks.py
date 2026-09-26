import threading,uuid,time,json,os
from .work_queue import pool,submission_lock
from . import store
from .provider import CodexCliProvider,DeepSeekProvider
cancellations={}; lock=threading.Lock()
def config(bundle=None):
    from .deepseek import settings
    saved=settings()
    if saved.get('import_provider','opencode')=='codex':
        cfg=json.loads((store.ROOT/'config.json').read_text());cfg['provider']='codex';return cfg
    return dict(provider='opencode',model=saved.get('opencode_model') or 'deepseek/deepseek-flash',reasoning='low',timeout_seconds=600,verify_solve_enabled=True)
def provider_for(cfg):
    if cfg['provider']=='local_docx':
        from .docx_fast import LocalProvider
        return LocalProvider(cfg)
    if cfg['provider']=='codex': return CodexCliProvider(store.ROOT,cfg)
    from .opencode_import import OpenCodeProvider
    return OpenCodeProvider(store.ROOT,cfg)
def submit(bundle):
    with submission_lock:return _submit(bundle)
def _submit(bundle):
    cfg=dict(bundle.get('_provider_config') or config(bundle))
    service_config=cfg.get('native_service_config')
    if bundle.get('native_services') and service_config is None:
        from .deepseek import settings
        saved=settings()
        service_config=dict(provider='opencode',model=saved.get('opencode_model') or 'deepseek/deepseek-flash',reasoning='low',timeout_seconds=600)
    if (bundle.get('docx_local') or {}).get('eligible'):cfg=dict(provider='local_docx',verify_solve_enabled=False)
    if service_config is not None:cfg['native_service_config']=service_config
    if bundle.get('native_docx'):cfg['verify_solve_enabled']=False
    # Display labels and the persisted retry budget do not change the source.
    # Keep all other configuration (including explicit experiment groups) in
    # the identity; this is not a broad model/configuration cache whitelist.
    identity_cfg={k:v for k,v in cfg.items() if k!='_budget_id'}
    provider=provider_for(identity_cfg)
    key=provider.key({k:v for k,v in bundle.items() if not k.startswith('_') and k not in ['display_name','session_title']})
    for task in store.all_rows('tasks'):
        if task.get('key')==key and task.get('status') in ['queued','running','succeeded']: return task
    id=uuid.uuid4().hex; task=dict(id=id,key=key,unit_key=bundle.get('_unit_key',key),budget_id=bundle.get('_budget_id',id),status='queued',provider_config=cfg,pid=os.getpid(),error='',bundle=bundle,created_at=time.time(),stage='排队等待',progress_log=[{'time':time.time(),'text':'文件已读取，等待解析'}]); store.put('tasks',id,task); cancellations[id]=store.TaskCancellation(); pool.submit(run,id); return task
def persist_drafts(task,result,meta,cancel=None):
    from .figure_state import reference_evidence,image_slots
    ids=[];baselines={};bundle=task['bundle'];unit=task.get('unit_key',task['key'])
    for i,source in enumerate(result['questions']):
        if cancel and cancel.is_set():break
        qid=uuid.uuid5(uuid.NAMESPACE_URL,unit+str(i)).hex
        existing=store.get('questions',qid)
        if existing:
            ids.append(qid)
            if existing.get('import_owned_revision')==existing['revision']:baselines[qid]=existing['revision']
            continue
        q=json.loads(json.dumps(source));q['source_snapshot']=json.loads(json.dumps(source))
        if (bundle.get('docx_local') or {}).get('eligible'):
            from .docx_fast import source_excerpt
            q['native_source_excerpt']=source_excerpt(source)
        elif bundle['original'].lower().endswith('.docx'):
            import re
            text=bundle.get('text','');matches=list(re.finditer(r'(?m)^\s*(\d+)\\?[.．、]',text))
            for index,match in enumerate(matches):
                if match[1]==str(source['original_number']):
                    q['native_source_excerpt']=text[match.start():matches[index+1].start() if index+1<len(matches) else len(text)];break
        from .prefix_clean import preview
        q=preview(q)['question'];q['ai_issues']=list(q.get('issues',[]))
        q.update(id=qid,schema_version='1.0',revision=0,human_answer=[],human_explanation=[],
            source=dict(id=bundle['source_id'],file=bundle['original'],display_name=bundle.get('display_name',bundle['original']),pages=q['pages'],region=None),
            provider_info=meta,created_at=time.time(),import_unit=unit,import_owned_revision=1,
            processing_status='saved',processing_reason='源题已保存，后处理尚未完成',
            review_status='pending',review_origin='draft',answer_status='源题草稿已保存')
        q['source_evidence']=reference_evidence(q,bundle)
        q['figure_records']=[dict(v,state='unverified',original_asset=v['asset']) for v in image_slots(q)]
        if cancel and cancel.is_set():break
        from .figure_workflow import ensure
        ensure(q)
        q.update(solution_status='needs_generation',solution_attempts=[],solution_issues=[])
        saved=store.save_question(q);ids.append(qid);baselines[qid]=saved['revision']
    return ids,baselines

def needs_figure_processing(q):
    if not q:return True # A deleted question must not abort ordering for the whole batch.
    from .figure_state import image_slots
    import re
    return bool(image_slots(q)) or bool(re.search('如图|图象|图像|图甲|图乙|电路图|示意图|统计图',json.dumps([q['stem'],q.get('options',[]),q['subquestions']],ensure_ascii=False)))

def mark_incomplete(qid,revision,reason):
    q=store.get('questions',qid)
    if not q or q['revision']!=revision:return
    q.update(processing_status='incomplete',processing_reason=reason,review_status='pending')
    if q.get('figure_workflow_version')==2:
        from .figure_workflow import ensure
        ensure(q)
        for r in q['figure_records']:r.update(figure_status='needs_recrop_from_source',figure_issue='incomplete',quality_error=reason)
    q['import_owned_revision']=q['revision']+1
    store.save_question(q,q['revision'],image_only=True)

def run(id):
    # Covers draft and figure writes in this task's thread. Recursive source
    # units restore their parent's scope; subsequent/manual work stays outside.
    with store.cancellation_scope(cancellations[id]):return _run(id)

def _run(id):
    from .request_boundary import configure,snapshot
    task=store.get('tasks',id);cancel=cancellations[id]
    cfg=configure(task.get('provider_config') or config(task['bundle']),task.get('budget_id',id))
    task['provider_config']=cfg;task['budget_id']=cfg['_budget_id']
    task.setdefault('coverage',dict(status='unconfirmed',total_questions=None))
    def progress(text,session_id=None):
        if session_id:task['session_id']=session_id
        task['stage']=text;task.setdefault('progress_log',[]).append(dict(time=time.time(),text=text))
        task['progress_log']=task['progress_log'][-100:];store.put('tasks',id,task)
    taskdir=store.DATA/'tasks'/id;taskdir.mkdir(parents=True,exist_ok=True)
    try:
        if cancel.is_set():raise ValueError('任务已取消')
        task.pop('error',None);task.pop('error_category',None)
        task.update(status='running',started_at=time.time());progress('准备解析并保存源题草稿')
        if not task['bundle'].get('_is_unit') and not task['bundle'].get('operation'):
            from .material_units import plan
            units=plan(task['bundle'])
            if len(units)>1:
                unit_records=[];question_ids=[];failures=[]
                for material in units:
                    if cancel.is_set():raise ValueError('任务已取消')
                    child_id=uuid.uuid5(uuid.NAMESPACE_URL,task.get('unit_key',task['key'])+material['unit_id']).hex
                    child=store.get('tasks',child_id)
                    if not child or child.get('status')!='succeeded':
                        material.update(_is_unit=True)
                        if child and (store.DATA/'tasks'/child_id/'extracted.private.json').is_file():material['_resume_extracted_from']=child_id
                        child=dict(id=child_id,key=task['key']+'-'+material['unit_id'],unit_key=task.get('unit_key',task['key'])+'-'+material['unit_id'],budget_id=cfg['_budget_id'],parent_id=id,status='queued',provider_config=cfg,bundle=material,created_at=time.time())
                        store.put('tasks',child_id,child);cancellations[child_id]=cancel;run(child_id)
                        child=store.get('tasks',child_id)
                    question_ids.extend(child.get('question_ids',[]))
                    unit_records.append(dict(id=child_id,source_range=material['source_range'],status=child['status'],question_ids=child.get('question_ids',[])))
                    task.update(units=unit_records,question_ids=question_ids,saved_count=len(question_ids));progress('已处理 '+str(len(unit_records))+'/'+str(len(units))+' 个明确题号范围；已保存 '+str(len(question_ids))+' 道')
                    if cancel.is_set():raise ValueError('任务已取消，已保存的题目和检查点保留')
                    if child['status']!='succeeded':failures.append(dict(unit=child_id,reason=child.get('error','单元后处理未完成')))
                task.update(status='partial' if failures else 'succeeded',failures=failures,coverage=dict(status='unconfirmed',total_questions=None,source_units=len(units),finished_units=sum(r['status']=='succeeded' for r in unit_records)),evidence_available=True)
                progress('编号文本分批结束；源范围记录已保存，总题数仍待对照确认');return
        if task['bundle'].get('operation')=='diagrams':
            from .diagrams import rebuild
            result,meta=rebuild(task['bundle'],taskdir,cfg,cancel,progress)
            if cancel.is_set():raise ValueError('任务已取消，未采用迟到题图')
            task.update(status='partial' if result.get('failures') or (result.get('unresolved_question_ids') and 'automatic_recrops' not in result) else 'succeeded',question_ids=result['question_ids'],meta=meta,figure_result=result)
            progress('题图处理结束：'+str(result['figures'])+' 处采用；待核对 '+str(len(result.get('unresolved_question_ids',[])))+' 题');return
        provider=provider_for(cfg);cached=store.get('cache',task['key'])
        resume=task['bundle'].get('_resume_extracted_from')
        if resume and (store.DATA/'tasks'/resume/'extracted.private.json').is_file():
            result=json.loads((store.DATA/'tasks'/resume/'extracted.private.json').read_text());meta=dict(cached=True,cost='复用已保存源题草稿',seconds=0)
        elif cached:
            result,meta=cached['result'],dict(cached['meta'],cached=True)
        else:
            # Overlay removal is optional: it cannot precede durable source extraction.
            native=task['bundle'].get('docx_local') or {}
            if task['bundle'].get('native_docx') and not native.get('eligible') and native.get('reason'):
                progress('Word原文和图片已保留；复杂结构继续识别：'+native['reason'])
            result,meta=provider.parse(task['bundle'],taskdir,cancel,progress=progress)
        (taskdir/'extracted.private.json').write_text(json.dumps(result,ensure_ascii=False))
        if cancel.is_set():raise ValueError('任务已取消，迟到返回仅留证据，不写入题库')
        ids,baselines=persist_drafts(task,result,meta,cancel)
        from .page_extraction import completed
        task.update(question_ids=ids,saved_count=len(ids),meta=meta,evidence_available=True,page_extraction=completed(result,task['bundle']))
        if cancel.is_set():raise ValueError('任务已取消，已保存的题目和检查点保留')
        progress('已保存 '+str(len(ids))+' 道源题草稿；总题数未知，材料覆盖未确认')
        failures=[];dependency_error=None
        # Local finalization must not wait behind a slow or failed image-model call.
        # Keep the original IDs/order for coverage and display; reorder only the work.
        ordered_ids=sorted(ids,key=lambda qid:needs_figure_processing(store.get('questions',qid)))
        for qid in ordered_ids:
            if cancel.is_set():raise ValueError('任务已取消，已保存的题目和检查点保留')
            q=store.get('questions',qid)
            if qid not in baselines:
                failures.append(dict(question_id=qid,reason='存在较新人工修订，未覆盖'));continue
            baseline=baselines[qid]
            if dependency_error:
                mark_incomplete(qid,baseline,dependency_error);failures.append(dict(question_id=qid,reason=dependency_error));continue
            try:
                if cancel.is_set():raise ValueError('任务已取消')
                if task['bundle'].get('native_docx'):
                    # Embedded Word assets are already final source images.
                    # Optional review/answers run separately after all copies finish.
                    issues=q.get('issues',[])
                    if cfg['provider']=='local_docx':
                        # Positions and bytes were copied from the original Word,
                        # so source diagrams need no paid crop/vision approval.
                        for record in q.get('figure_records',[]):
                            record.update(figure_status='ready',state='verified',figure_issue=None,confirmation='native_word_source_copy')
                        q['delivery_check']=dict(required_assets_present=True,content_complete=True)
                        if q.get('figure_records'):q['missing_required_figure']=False
                    retained_solution=bool(task['bundle'].get('native_services') and q.get('solution_attempts'))
                    answer_status=q.get('answer_status','答案解析待核对') if retained_solution else '已保留原文答案解析' if q.get('original_answer') or q.get('original_explanation') else '未生成答案解析'
                    q.update(processing_status='review' if issues else 'complete',processing_reason='；'.join(map(str,issues)),review_status='pending' if issues else 'approved',answer_status=answer_status,solution_status=q.get('solution_status','needs_retry') if retained_solution else 'disabled',import_owned_revision=baseline+1)
                    store.save_question(q,baseline,image_only=True)
                    continue
                from .verify_solve import enabled,complete_question
                if cfg['provider']=='opencode' and enabled(cfg):
                    complete_question(qid,taskdir/('verify-solve-'+qid),cfg,cancel,progress)
                    continue
                # Explicit visual wording still requires verification if a slot was omitted.
                needs_figure=needs_figure_processing(q)
                if cfg['provider']=='opencode' and needs_figure and task['bundle'].get('original','').lower().endswith(('.pdf','.png','.jpg','.jpeg','.docx')):
                    from .diagrams import prepare_rebuild,rebuild
                    from .figure_workflow import prepare_material
                    material=prepare_material(qid)
                    material['crop_only']=True
                    outcome,_=rebuild(material,taskdir/('figure-'+qid),cfg,cancel,progress)
                    if outcome.get('unresolved_question_ids') and not store.get('questions',qid).get('figure_workflow_version'):failures.append(dict(question_id=qid,reason='题图定位待核对'))
                    for f in outcome.get('failures',[]):
                        if f.get('category') in ['budget','authentication','permission','unsupported_image','dependency']:dependency_error=f['reason']
                else:
                    unverified=any(r.get('state')!='verified' for r in q.get('figure_records',[]))
                    q.update(processing_status='review' if unverified else 'complete',processing_reason='嵌入图片归属尚未核对' if unverified else '',review_status='pending' if q.get('issues') or unverified else 'approved',answer_status='源题已保存',import_owned_revision=baseline+1)
                    if unverified:failures.append(dict(question_id=qid,reason=q['processing_reason']))
                    store.save_question(q,baseline,image_only=True)
            except Exception as exc:
                # Cancellation must escape the per-question recovery handler:
                # marking every remaining draft incomplete would be a late write.
                if cancel.is_set():raise
                failures.append(dict(question_id=qid,reason=str(exc)[:300],category=getattr(exc,'category','system')))
                mark_incomplete(qid,baseline,str(exc)[:300])
                if getattr(exc,'category','') in ['budget','authentication','permission','unsupported_image','dependency']:dependency_error=str(exc)[:300]
        if cancel.is_set():raise ValueError('任务已取消，已保存的题目和检查点保留')
        if task['bundle'].get('native_docx') and task['bundle'].get('native_services'):
            from .native_import_services import run as native_services
            failures.extend(native_services(task,taskdir,cfg,cancel,progress))
            if cancel.is_set():raise ValueError('任务已取消，已保存的题目和检查点保留')
        task.update(status='partial' if failures else 'succeeded',failures=failures)
        if cfg['provider']=='local_docx':
            task['coverage']=dict(status='complete',total_questions=len(ids),basis='explicit-native-word-structure')
            if task.get('native_services'):
                selected='、'.join(label for key,label in [('light_review','质量审查'),('generate_solution','答案解析')] if task['bundle']['native_services'].get(key))
                progress('Word 原文已导入，共 '+str(len(ids))+' 道题；'+('部分附加处理未完成，详情见记录' if failures else selected+'处理已完成'))
            else:progress('Word 导入完成，共 '+str(len(ids))+' 道题；'+('旧公式已恢复为可编辑公式，费用见记录' if meta.get('application_requests',0) else '文字、公式和原图已保留，本次无 API 费用'))
            return
        progress('导入结束，已保留 '+str(len(ids))+' 道题；技术异常 '+str(len(failures))+' 项。文字与图片状态请分别查看；材料总题数尚未确认')
    except Exception as exc:
        task.update(status='cancelled' if cancel.is_set() else ('partial' if task.get('question_ids') else 'failed'),error=str(exc)[:500],error_category=getattr(exc,'category','system'),evidence_available=True)
        progress('处理未完成，已保存成果和来源证据保留；'+str(exc)[:180])
    finally:
        task['finished_at']=time.time();task['request_budget']=snapshot(cfg)
        store.put('tasks',id,task)
