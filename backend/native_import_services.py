"""Explicit services after copying native Word; never transcribe its source again."""
import copy
import json
import time
from . import store
from .d_region_adapter import check


def owned(q):
    return bool(q and q.get('import_owned_revision') == q.get('revision'))


def save_owned(q, **updates):
    expected = q['revision']
    q = copy.deepcopy(q)
    q.update(updates, import_owned_revision=expected + 1)
    return store.save_question(q, expected=expected, image_only=True)


def run(task, folder, cfg, cancel, progress):
    options = task['bundle']['native_services']
    if not any(options.values()):
        return []
    from . import light_review_batch as review
    from .request_boundary import configure
    from .verify_solve import start_solution_only
    service_cfg = configure(dict(cfg['native_service_config']), cfg['_budget_id'])
    service_cfg['_budget_id'] = cfg['_budget_id']
    if cfg.get('request_limits'):
        service_cfg['request_limits'] = cfg['request_limits']
    folder = folder / 'native-services'
    folder.mkdir(parents=True, exist_ok=True)
    state = dict(options=options, started_at=time.time(), status='running', review=[], solutions=[])
    task['native_services'] = state
    failures = []
    qs = []

    def fail(qid, stage, reason):
        failures.append(dict(question_id=qid, service=stage, reason=reason))

    try:
        for qid in task['question_ids']:
            check(cancel)
            q = store.get('questions', qid)
            if not owned(q):
                fail(qid, 'ownership', '题目已被修改或移除，未覆盖当前内容')
            else:
                qs.append(q)
        if options.get('light_review'):
            progress('Word 原文已保存，正在检查内容与原文件是否一致')
            reviewed = dict(results=[], calls=[])
            error = None
            try:
                reviewed = review.review_questions(qs, folder / 'quality-review', cancel=cancel,
                    progress=progress, config=service_cfg)
            except Exception as exc:
                check(cancel)
                error = str(exc)[:300]
                # Earlier successful groups remain independently adoptable.
                checkpoint = folder / 'quality-review' / 'review-results.json'
                if checkpoint.is_file():
                    reviewed = json.loads(checkpoint.read_text())
            state['review_calls'] = reviewed.get('calls', [])
            state['review_reused_count'] = reviewed.get('reused_count', 0)
            state['review_local_only_count'] = reviewed.get('local_only_count', 0)
            results = {r['id']: r for r in reviewed['results']}
            for original in qs:
                check(cancel)
                qid = original['id']
                q = store.get('questions', qid)
                result = results.get(qid)
                if not q or q['revision'] != original['revision'] or not owned(q):
                    fail(qid, 'light_review', '题目已有新版本，未采用旧版本审查结果')
                    state['review'].append(dict(id=qid, status='skipped', eligible=False))
                    continue
                stable = bool(result and result.get('evidence_key'))
                if stable:
                    try:
                        stable = review.review_cache_key(q) == result['evidence_key']
                    except (OSError, ValueError, KeyError):
                        stable = False
                if stable:
                    out = json.loads((folder / 'quality-review' / 'candidates' / (qid + '.json')).read_text())
                    if q.get('solution_attempts'):
                        for key in ['solution_status', 'solution_issues', 'answer_status']:
                            if key in q:
                                out[key] = copy.deepcopy(q[key])
                    # Upload confirmation already explicitly selected this service.
                    out['light_review_confirmation'] = dict(task_id=task['id'], confirmed_at=time.time(), mode='explicit_import_option')
                    out['revision_note'] = '按上传时选择完成质量审查，保留原题内容'
                    q = save_owned(out)
                    status = 'passed' if result['eligible'] else 'needs_review'
                    state['review'].append(dict(id=qid, status=status, eligible=result['eligible'], issues=result['issues']))
                    if not result['eligible']:
                        fail(qid, 'light_review', '；'.join(result['issues']) or '内容需要核对，未生成答案解析')
                else:
                    message = '质量审查未完成，原文已保留，请稍后重试' if error else '原文件或题目在审查期间发生变化，请重新审查'
                    q = save_owned(q, quality_check_status='failed', content_status='needs_review',
                        content_issues=list(dict.fromkeys(q.get('content_issues', []) + [message])))
                    state['review'].append(dict(id=qid, status='failed', eligible=False, error=error or message))
                    fail(qid, 'light_review', error or message)
            progress('Word 质量审查结束，通过的题目按所选参数继续处理')
        if options.get('generate_solution'):
            allowed = {r['id'] for r in state['review'] if r.get('eligible')}
            for index, original in enumerate(qs):
                check(cancel)
                qid = original['id']
                q = store.get('questions', qid)
                if not owned(q):
                    state['solutions'].append(dict(id=qid, status='skipped', reason='题目已有新版本，未生成答案'))
                    fail(qid, 'generate_solution', '题目已有新版本，未生成答案')
                    continue
                if ((options.get('light_review') and qid not in allowed) or not q.get('directly_usable')
                    or q.get('context_closed') is False or q.get('extraction_issues') or q.get('import_review_blocked')):
                    message = '题目内容尚需核对，已跳过答案解析'
                    save_owned(q, generate_solution=True, solution_status='unavailable_due_to_source_issue', solution_issues=[message])
                    state['solutions'].append(dict(id=qid, status='skipped', reason=message))
                    if not any(f['question_id'] == qid for f in failures):
                        fail(qid, 'generate_solution', message)
                    continue
                progress(f'Word 正在生成答案解析 {index + 1}/{len(qs)} 题')
                if q.get('solution_status') == 'ready' and q.get('solution_attempts'):
                    state['solutions'].append(dict(id=qid, status='ready', reused=True))
                    continue
                # Native complete questions need no visual re-extraction. An
                # explicit false/open source context was rejected above.
                q = save_owned(q, generate_solution=True, context_closed=True,
                    solution_status=q.get('solution_status') if q.get('solution_attempts') else 'needs_generation')
                try:
                    out = start_solution_only(q, folder / ('solution-' + qid), service_cfg, cancel, progress)
                    status = out.get('solution_status')
                    state['solutions'].append(dict(id=qid, status=status, issues=out.get('solution_issues', [])))
                    if status != 'ready':
                        fail(qid, 'generate_solution', '；'.join(out.get('solution_issues', [])) or '答案解析未完整生成')
                except Exception as exc:
                    check(cancel)
                    current = store.get('questions', qid)
                    if current and current['revision'] == q['revision']:
                        # Answer errors do not invalidate an intact source stem.
                        save_owned(current, solution_status='failed', solution_issues=['答案解析生成未完成，请稍后重试'], answer_status='答案解析未生成完成')
                    state['solutions'].append(dict(id=qid, status='failed', error=str(exc)[:300]))
                    fail(qid, 'generate_solution', str(exc)[:300])
        check(cancel)
        state['status'] = 'partial' if failures else 'succeeded'
        return failures
    finally:
        state['finished_at'] = time.time()
        if cancel.is_set():
            state['status'] = 'cancelled'
        elif state['status'] == 'running':
            state['status'] = 'failed'
        state['failures'] = failures
        # The history's request-file reader is also the cost authority here;
        # local formula conversion and later services must not overwrite it.
        from .task_summary import enrich
        cost = enrich([dict(task, status=state['status'])], [])[0]['task_cost']
        state['task_cost'] = cost
        meta = task.setdefault('meta', {})
        meta.update(provider='Word · 原文导入及附加服务', seconds=state['finished_at'] - task['started_at'],
            application_requests=cost['observed_calls'] + cost['missing_calls'],
            cost_estimate=dict(amount=cost['amount'], currency='CNY', estimated=True) if cost['complete'] and cost['amount'] is not None else None,
            cost=f'约 ¥{cost["amount"]:.4f}' if cost['complete'] and cost['amount'] is not None else '费用尚未完整记录')
