"""D import adapter into existing tasks, questions, assets and human review."""
import copy,hashlib,json,os,shutil,time,uuid
from pathlib import Path
import fitz
from . import store,tasks
from .work_queue import submission_lock,pool
from . import d_shadow,d_stream
from .d_region_adapter import check,dump
VERSION=d_stream.VERSION
# New submissions must not reuse results produced before the Region/table/carry
# fixes. Keep the execution version stable so historical retries retain routing.
PIPELINE_REVISION='20260923-native-figure-integrity-v6'
SINGLE_READ_PIPELINES={'d-bank-3-single-read',VERSION}

def method(value='A'):
    if value not in ['A','D']:raise ValueError('请选择 A 方法或 D 方法')
    return value

def identity(row):return row.get('import_method') or row.get('bundle',{}).get('import_method') or 'A'

def submit(raw,name,subject,start=1,end=0,selected_pages=None,request_id=None,generate_solution=None,request_profile=None):
    ext=Path(name).suffix.lower()
    from .d_pure import PROFILE,LEGACY
    from .d_light import PROFILE as LIGHT
    request_profile=request_profile or os.environ.get('QUESTION_BANK_PDF_IMPORT_PROFILE',PROFILE)
    if request_profile not in [PROFILE,LEGACY,LIGHT]:raise ValueError('Unknown PDF import profile')
    if generate_solution is None:generate_solution=request_profile==LEGACY
    if type(generate_solution) is not bool:raise ValueError("generate_solution必须为布尔值")
    if subject not in ['数学','物理']:raise ValueError('不支持的学科')
    ext=Path(name).suffix.lower()
    if ext not in ['.pdf','.png','.jpg','.jpeg']:raise ValueError('图像输入支持 PDF / PNG / JPG')
    if not raw or len(raw)>100*1024*1024:raise ValueError('文件为空或超过100MB')
    if ext=='.pdf':
        with fitz.open(stream=raw,filetype='pdf') as pdf:
            if pdf.needs_pass:raise ValueError('不支持加密PDF')
            end=end or len(pdf)
            if start<1 or end<start or end>len(pdf):raise ValueError('物理页码范围无效')
            pages=selected_pages if selected_pages is not None else list(range(start,end+1))
            if not pages or any(type(n)is not int or n<1 or n>len(pdf) for n in pages):raise ValueError('物理页码范围无效')
            pages=sorted(set(pages))
    else:pages=[1]
    sid=hashlib.sha256(raw).hexdigest()
    key=hashlib.sha256(json.dumps([VERSION,PIPELINE_REVISION,sid,subject,pages,ext,request_id,generate_solution,request_profile]).encode()).hexdigest()
    with submission_lock:
        for task in store.all_rows('tasks'):
            if task.get('key')==key:
                if task.get('status') in ['queued','running']:return task
                ids=task.get('question_ids',[])
                if ids and all(store.get('questions',qid) is not None for qid in ids):return task
        folder=store.DATA/'sources'/sid;folder.mkdir(parents=True,exist_ok=True);original='original'+ext
        if not (folder/original).exists():(folder/original).write_bytes(raw)
        task=dict(id=uuid.uuid4().hex,key=key,unit_key=key,import_method='D',import_pipeline=VERSION,import_pipeline_revision=PIPELINE_REVISION,generate_solution=generate_solution,d_request_profile=request_profile,status='queued',created_at=time.time(),pid=os.getpid(),stage='导入：排队等待',progress_log=[],question_ids=[],saved_count=0,
            bundle=dict(source_id=sid,sha256=sid,original=original,display_name=name,subject=subject,pages=pages,import_method='D'),provider_config=dict(tasks.config(),provider='opencode',import_method='D'))
        store.put('tasks',task['id'],task);tasks.cancellations[task['id']]=store.TaskCancellation();pool.submit(run,task['id']);return task

def persist(record,task,cancel):
    """Source assets are copied once. Existing question versions are never overwritten."""
    folder=store.DATA/'sources'/task['bundle']['source_id'];folder.mkdir(parents=True,exist_ok=True)
    check(cancel)
    for p in record.get('pages',[]):
        src=Path(p['region_path'])/p['original'];dst=folder/f"page-{p['page']}.png"
        if not dst.exists():shutil.copy2(src,dst)
    for asset in record.get('assets',[]):
        check(cancel);src=Path(asset['path']);dst=folder/asset['asset']
        if hashlib.sha256(src.read_bytes()).hexdigest()!=asset['pixel_sha256']:raise ValueError('Region资产校验失败')
        if dst.exists() and hashlib.sha256(dst.read_bytes()).hexdigest()!=asset['pixel_sha256']:raise ValueError('固定资产文件冲突，未覆盖')
        if not dst.exists():shutil.copy2(src,dst)
    from .figure_state import image_slots
    from .figure_workflow import sync
    ids=[]
    with store.cancellation_scope(cancel):
        for draft in record.get('questions',[]):
            check(cancel);q=copy.deepcopy(draft);qid=q['id']
            existing=store.get('questions',qid)
            recover_conflict=existing and existing.get('import_review_blocked') and existing.get('import_owned_revision')==existing['revision'] and 'cross_page_inconsistent' not in q.get('warning',[])
            resume_pending=existing and task.get('import_pipeline')==VERSION and existing.get('continuation_status')=='pending_continuation' and q.get('context_closed') is True and existing.get('import_owned_revision')==existing['revision']
            if existing and not (recover_conflict or resume_pending):ids.append(qid);continue
            page_conflict='cross_page_inconsistent' in q.get('warning',[])
            q.update(import_method='D',schema_version='1.0',created_at=time.time(),revision=0,import_unit=task['key'],import_owned_revision=(existing['revision']+1 if existing else 1),
                fixed_region_input=True,figure_workflow_version=2,content_status='needs_review',content_issues=list(q['issues']),
                ai_issues=list(q['issues']),answer_status='等待正式版核对与答案解析',solution_status='needs_generation',solution_attempts=[],solution_issues=[],
                provider_info=dict(provider='deepseek',model='deepseek-flash',method='D'),source_evidence=[dict(page=p,asset=f'page-{p}.png',status='完整原页') for p in q['source_pages']],
                d_evidence_url='/api/tasks/'+task['id']+'/d-evidence')
            integrated=task.get('import_pipeline') in SINGLE_READ_PIPELINES
            if integrated:
                for field in ['content_status','content_issues','ai_issues','issues','solution_status','solution_attempts','solution_issues','answer_status','ai_answer','ai_explanation','delivery_check','delivery_issues','knowledge']:
                    if field in draft:q[field]=copy.deepcopy(draft[field])
                q['import_pipeline']=task['import_pipeline']
                facts=q.get('delivery_check') or {}
                labels={'delivery_check_unavailable':'交付检查结果不完整，请核对','content_complete=false':'题干或小问内容不完整','options_complete=false':'选项内容不完整','required_assets_present=false':'缺少作答所需图表','text_image_consistent=false':'题文与配图存在不一致','source_issue':'原始题目存在疑点','cross_page_uncertain':'跨页内容尚未完整读取','cross_page_inconsistent':'题文与配图的来源页不一致','missing_image_asset':'缺少作答所需图片'}
                q['content_issues']=[labels.get(issue,issue.split(': ',1)[-1]) for issue in q.get('content_issues',[])]
                if not q.get('d_import_profile') and facts.get('solvable_from_current_delivery') is not True:
                    q['content_status']='needs_review'
                    q['content_issues'].append('当前题文与固定图片是否足以作答尚未确认，请核对')
                if not q.get('d_import_profile') and q.get('solution_status') not in ['ready','disabled'] and not q.get('solution_issues'):
                    q['solution_issues']=['答案解析未完整生成，请核对']
                q['issues']=list(q['content_issues'])
                q['ai_issues']=list(q.get('content_issues',[]))
            records=q['figure_records'];mapped=[]
            for slot in image_slots(q):
                prior=next((r for r in records if r['asset']==slot['asset']),{});ref=next((a for a in q['asset_refs'] if a['asset']==slot['asset']),{})
                source_pages=ref.get('source_pages',[])
                mapped.append(dict(prior,**slot,page=source_pages[0] if len(source_pages)==1 else None,source_id=q['source']['id'],source_file=q['source']['file'],original_status='accepted' if prior.get('figure_status')=='ready' else 'unverified',svg_status='absent',redrawn=False))
            if integrated:
                for r in mapped:
                    issues=[i for i in (q.get('delivery_check') or {}).get('issues',[]) if r.get('asset_id') in i.get('asset_ids',[]) and i.get('code') in {'missing_asset','wrong_assignment','image_text_conflict','missing_critical_label','missing_image_structure','missing_table_information','ambiguous_neighbor_content'}]
                    if issues:
                        r.update(figure_status='needs_recrop_from_source',original_status='unverified',quality_error='；'.join(i['detail'] for i in issues))
            q['figure_records']=mapped
            if not integrated:
                for r in mapped:r.update(figure_status='needs_recrop_from_source',original_status='unverified',quality_error='等待正式版图片检查')
            q['missing_required_figure']='missing_image_asset' in q.get('warning',[]);sync(q)
            if page_conflict:
                question_pages='、'.join(map(str,q['source_pages']))
                asset_pages='、'.join(map(str,sorted({p for a in q.get('asset_refs',[]) for p in a.get('source_pages',[])}))) or '未知'
                reason=f"题目第 {q.get('original_number') or '未知'} 题：识别页码为第 {question_pages} 页，关联配图来自第 {asset_pages} 页，页码归属不一致。请对照原文件确认；冲突配图未作为正式题图采用。"
                q.update(import_review_blocked=True,content_status='needs_review',content_issues=list(dict.fromkeys(q['content_issues']+[reason])),solution_status='needs_review',solution_issues=['来源归属未确认，自动解题已停止，等待人工处理'],answer_status='来源归属需人工确认后再生成答案解析')
                sync(q)
            saved=store.save_question(q,expected=existing['revision'] if existing else None);ids.append(saved['id'])
            task.update(question_ids=list(ids),saved_count=len(ids));store.put('tasks',task['id'],task)
    return ids

def import_meta(metrics,folder,seconds):
    """Count each recognition/answer request once; unknown usage is not free."""
    calls=[]
    for group in Path(folder).iterdir() if Path(folder).is_dir() else []:
        if not group.is_dir() or not group.name.startswith(('solution-','solution-recovery-','verify-solve-')):continue
        parents={p.parent for name in ['usage.json','metrics.json','audit.json'] for p in group.rglob(name)}
        for parent in sorted(parents):
            paths=[parent/name for name in ['usage.json','metrics.json','audit.json']]
            existing=next(p for p in paths if p.is_file())
            try:row=json.loads(existing.read_text())
            except (ValueError,OSError):row={}
            if existing.name=='audit.json':
                # Audit request counts are cumulative, never add them per call.
                count=0 if row.get('error_category')=='budget' else 1
            else:count=row.get('request_count',row.get('application_requests',1))
            estimate=row.get('cost_cny_estimate')
            if estimate is None:estimate=(row.get('cost_estimate') or {}).get('amount')
            if not isinstance(estimate,(int,float)) or estimate<0:estimate=None
            calls.append(dict(evidence_path=str(existing.relative_to(folder)),request_count=count,cost_cny_estimate=estimate,
                seconds=row.get('seconds',row.get('wall_seconds',0)),operation=row.get('operation','solution_only')))
    known=metrics.get('known_cost_cny',metrics.get('cost_cny_estimate')) or 0
    unknown=metrics.get('unknown_cost_calls',int(bool(metrics.get('requests')) and metrics.get('cost_cny_estimate') is None))
    if 'calls' in metrics:
        unknown=sum(c.get('request_count',1)>0 and c.get('cost_cny_estimate') is None for c in metrics['calls'])
    known+=sum(c['cost_cny_estimate'] for c in calls if c['cost_cny_estimate'] is not None)
    unknown+=sum(c['request_count']>0 and c['cost_cny_estimate'] is None for c in calls)
    cost=None if unknown else known
    return dict(provider='DeepSeek · 图文识别'+('与答案解析' if calls else ''),seconds=seconds,
        application_requests=metrics.get('requests',0)+sum(c['request_count'] for c in calls),
        cost='费用未知' if cost is None else f'约 ¥{cost:.4f}',
        cost_estimate=None if cost is None else dict(amount=cost,currency='CNY',estimated=True),
        known_cost_cny=known,unknown_cost_calls=unknown,postprocessing_calls=calls)


def run(task_id,reader=None):
    task=store.get('tasks',task_id);cancel=tasks.cancellations[task_id];bundle=task['bundle'];folder=store.DATA/'tasks'/task_id/'d-stage'
    record=dict(id=task_id,mode='d_bank',status='queued',questions=[],pages=[],assets=[],errors=[],created_at=task['created_at'])
    last=''
    def progress(r):
        nonlocal last
        msg=f"导入：已分析 {len(r['pages'])}/{len(bundle['pages'])} 页，已结构化 {len(r['questions'])} 条"
        active=r.get('active_call')
        if active:msg=f"导入：本地分割完成，正在请求第 {'、'.join(map(str,active['pages']))} 页，等待 API 返回"
        task['stage']=msg
        if msg!=last:task.setdefault('progress_log',[]).append(dict(time=time.time(),text=msg));last=msg
        store.put('tasks',task_id,task)
    try:
        task.update(status='running',started_at=time.time(),pid=os.getpid());store.put('tasks',task_id,task)
        raw=(store.DATA/'sources'/bundle['source_id']/bundle['original']).read_bytes()
        args=(record,raw,bundle['display_name'],bundle['subject'],min(bundle['pages']),max(bundle['pages']),cancel)
        light=task.get('d_request_profile')=='pure_d_light_review_v1' and task.get('import_pipeline')==VERSION
        pure=task.get('d_request_profile') in ['pure_d_page_overview_v1','pure_d_light_review_v1'] and task.get('import_pipeline')==VERSION
        if pure and reader is None:
            from .d_text_reader import read
            def reader(*a,**kw):return read(*a,request_format='historical_envelope_overview_v1',**kw)
        if task.get('import_pipeline')==VERSION:
            # Review stays in the transcription call; answer generation is a
            # separate bounded call only after the saved question passes review.
            d_stream.run(*args,reader=reader,folder=folder,on_update=progress,selected_pages=bundle['pages'],retry_pages=task.pop('retry_pages',[]),generate_solution=False if light else task.get('generate_solution',True),pure_d=pure,light_review=light)
            task.update(unresolved_page_segments=record.get('unresolved_segments',[]),page_extraction=record.get('page_extraction',{}),completion_state=record['status'])
        else:
            d_shadow.run(*args,reader=reader,folder=folder,on_update=progress,selected_pages=bundle['pages'],reuse_calls=True,delivery=task.get('import_pipeline') in SINGLE_READ_PIPELINES)
        check(cancel)
        if record['status']=='failed' and not record.get('questions'):raise ValueError(record.get('error','D 处理失败'))
        if light and task.get('generate_solution'):
            for q in record.get('questions',[]):
                q['generate_solution']=True
                if q.get('directly_usable') and q.get('context_closed') and not q.get('extraction_issues'):
                    q.update(solution_status='needs_generation',answer_status='质量审查通过，答案解析待生成')
                else:q['answer_status']='请先补齐或核对题目，再生成答案解析'
        ids=persist(record,task,cancel);check(cancel)
        from .verify_solve import complete_question
        from .request_boundary import configure,snapshot
        cfg=configure(dict(task.get('provider_config') or tasks.config(),provider='opencode'),task_id)
        task['provider_config']=cfg
        failures=[]
        def check_progress(text,session_id=None):
            task['stage']='导入：'+text
            task.setdefault('progress_log',[]).append(dict(time=time.time(),text=task['stage']))
            store.put('tasks',task_id,task)
        if task.get('import_pipeline') in SINGLE_READ_PIPELINES:
            with store.cancellation_scope(cancel):
                from .verify_solve import continue_solutions,save_attempts
                for qid in ids:
                    check(cancel);q=store.get('questions',qid)
                    if not q or q.get('import_owned_revision')!=q['revision'] or q.get('import_review_blocked'):continue
                    if pure:
                        if task.get('generate_solution') and q.get('solution_status')=='needs_generation' and q.get('context_closed') and not q.get('extraction_issues') and (not light or q.get('directly_usable')):
                            try:
                                from .verify_solve import start_solution_only
                                solved=start_solution_only(q,store.DATA/'tasks'/task_id/('solution-'+qid),cfg,cancel,check_progress)
                                if solved.get('solution_status')!='ready':failures.append(dict(question_id=qid,reason='答案解析尚未通过检查，题目内容已保留'))
                            except Exception as exc:
                                check(cancel);failures.append(dict(question_id=qid,reason=str(exc)[:300]))
                                current=store.get('questions',qid)
                                if current and current['revision']==q['revision']:
                                    current.update(solution_status='failed',solution_issues=['答案解析生成未完成，请稍后重试'],answer_status='答案解析未生成完成',import_owned_revision=current['revision']+1)
                                    store.save_question(current,expected=current['revision'],image_only=True)
                        continue
                    # Only a complete, checked delivery may retry a failed answer.
                    # Missing/ambiguous conditions need human review, not more guessing.
                    if task.get('generate_solution',True) and q.get('solution_status')=='failed' and q.get('content_status')=='ready' and (q.get('delivery_check') or {}).get('solvable_from_current_delivery') is True:
                        taskdir=store.DATA/'tasks'/task_id/('solution-recovery-'+qid)
                        taskdir.mkdir(parents=True,exist_ok=True)
                        try:
                            attempts=q.get('solution_attempts') or [dict(attempt=1,kind='single_read_delivery',baseline_revision=q['revision'],solution=dict(answer=q.get('ai_answer',[]),explanation=q.get('ai_explanation',[])),solution_check=dict(status='failed',issues=q.get('solution_issues',[])),meta={})]
                            if not q.get('solution_attempts'):q=save_attempts(q,attempts)
                            continue_solutions(q,taskdir,cfg,cancel,check_progress)
                        except Exception as exc:
                            check(cancel);failures.append(dict(question_id=qid,reason=str(exc)[:300]))
        if task.get('import_pipeline') not in SINGLE_READ_PIPELINES:
            with store.cancellation_scope(cancel):
                for index,qid in enumerate(ids):
                    check(cancel);q=store.get('questions',qid)
                    if q and q.get('import_review_blocked'):
                        failures.append(dict(question_id=qid,reason='来源页码归属冲突，已转入待审核'));continue
                    if not q or q.get('import_owned_revision')!=q['revision']:
                        failures.append(dict(question_id=qid,reason='存在人工修订，未覆盖'));continue
                    check_progress(f'正式版核对与答案解析 {index+1}/{len(ids)}')
                    try:complete_question(qid,store.DATA/'tasks'/task_id/('verify-solve-'+qid),cfg,cancel,check_progress)
                    except Exception as exc:
                        check(cancel);failures.append(dict(question_id=qid,reason=str(exc)[:300]))
                        latest=store.get('questions',qid)
                        if latest and latest['revision']==q['revision']:tasks.mark_incomplete(qid,q['revision'],str(exc)[:300])
        task['failures']=failures;task['request_budget']=snapshot(cfg)
        coverage=[p for u in record.get('units',[]) if not u.get('assembly_errors') and u.get('recovery') in ['raw_success','repaired'] for p in u.get('page_extractions',[])]
        # Cross-page fragments and incomplete drafts do not count as finished pages.
        incomplete={p for q in record['questions'] if q.get('draft_status')=='incomplete' or 'cross_page_uncertain' in q.get('warning',[]) for p in q['source_pages']}
        completed=[p['page'] for p in coverage if p['status']=='complete' and p['page'] not in incomplete]
        empty=[p['page'] for p in coverage if p['status']=='no_questions']
        task.update(question_ids=ids,saved_count=len(ids),status='partial' if failures or record.get('errors') or incomplete or task.get('blocked_drafts') else 'succeeded',
            page_extraction=dict(basis='explicit-page-report-v1',completed_pages=sorted(set(completed+empty)),empty_pages=empty,incomplete_pages=sorted(incomplete),pages=coverage),
            coverage=dict(status='unconfirmed',total_questions=None),d_counts=record.get('counts',{}),d_metrics=record.get('metrics',{}),d_errors=record.get('errors',[]))
        if task.get('import_pipeline')==VERSION:
            task.update(page_extraction=record['page_extraction'],unresolved_page_segments=record['unresolved_segments'],completion_state=record['status'])
            if record['status']!='succeeded':task['status']='partial'
        task['stage']=f'导入处理结束，已保存 {len(ids)} 条；轻量审查完成，按具体问题分流' if light else f'导入处理结束，已保存 {len(ids)} 条；纯D转录完成，质量检查未执行' if pure else f'导入处理结束，已保存 {len(ids)} 条；识别、核对与答案解析已完成，有疑问的内容进入现有审核'
        if pure and task.get('generate_solution'):
            ready=sum((store.get('questions',qid) or {}).get('solution_status')=='ready' for qid in ids)
            task['stage']+=f'；{ready} 题已生成答案解析'
        if record.get('errors'):task['error']='；'.join(str(e) for e in record['errors'])[:500]
    except Exception as exc:task.update(status='cancelled' if cancel.is_set() else ('partial' if task.get('question_ids') else 'failed'),error=str(exc)[:500])
    finally:
        if task.get('import_pipeline')==VERSION:
            task.update(page_extraction=record.get('page_extraction',{}),unresolved_page_segments=record.get('unresolved_segments',[]),completion_state=record.get('status'))
        metrics=record.get('metrics',{});task['d_metrics']=metrics
        task['finished_at']=time.time()
        task['meta']=import_meta(metrics,folder.parent,task['finished_at']-task.get('started_at',task['finished_at']))
        # Keep terminal evidence outside SQLite when its write fails, and log the
        # exception: executor Futures otherwise hide failures from the server log.
        dump(folder.parent/'terminal-task.json',task)
        try:store.put('tasks',task_id,task)
        except Exception:
            __import__('logging').getLogger(__name__).exception('Cannot persist terminal state for import %s',task_id)
            raise

def retry(task,pages=None):
    with submission_lock:
        latest=store.get('tasks',task['id'])
        if latest['status'] not in ['failed','partial','cancelled','interrupted']:raise ValueError('当前任务不能重试')
        if latest.get('import_pipeline')==VERSION:
            allowed={p for segment in latest.get('unresolved_page_segments',[]) for p in segment['pages']}
            if pages is not None:
                if not pages or any(type(p) is not int for p in pages) or not set(pages)<=allowed:raise ValueError('请选择本任务未完成的页段')
                latest['retry_pages']=sorted(set(pages))
            else:latest['retry_pages']=[] # Local replay only; unknown requests are never blindly resent.
        d_shadow.TRANSPORT_BLOCKED.clear()
        latest.update(status='queued',error='',stage='导入：人工重试（复用已返回内容）');latest.pop('finished_at',None)
        store.put('tasks',task['id'],latest);tasks.cancellations[task['id']]=store.TaskCancellation();pool.submit(run,task['id']);return latest
