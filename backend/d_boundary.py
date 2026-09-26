"""Optional previous-page tail context; never joins questions by printed number."""
import copy

PROMPT='''
页边界补充规则：carry_forward 中 boundary_candidate=true 的条目是前页最后一道已暂判完整的题，仅用于核对本页开头是否还有它的小问、图表或文字。这类条目不是强制返回的未完成题：本页没有实际续文/配图时直接省略，不要复述、不要为了返回它而标为不完整；其原有资产可标 unassigned 并说明本页无续接。其余普通 carry 仍须返回。
如果当前页顶部确实接续该候选题（例如同一情境的后续小问或配图），continuation_of 原样返回其 carry_id，完整复制前文 question_text、已有选项及小问后再补入本页内容，source_pages 包含前后页。不改写前文、不省略已有条件，不仅凭题号、相邻位置或小问编号强行合并。不能确认对应关系时保留本页残题并明确缺少哪些上下文。
'''


def candidate(saved,original,links,assets,current):
    if not saved.get('context_closed') or current not in original['source_pages']:return None
    refs={link['asset_id'] for link in links}
    return dict(carry_id='boundary-'+saved['id'],saved_id=saved['id'],boundary_candidate=True,
        question=copy.deepcopy(original),asset_assignments=copy.deepcopy(links),
        assets=[copy.deepcopy(a) for a in assets if a['asset_id'] in refs],
        source_state=dict(pages=list(original['source_pages']),context_closed=True,
            reason='前页末题，仅供本页开头续接核对；无续文时可省略'))


def has_new_content(original,prior,current,assignments,assets):
    old=prior['question']
    if any(original.get(k)!=old.get(k) for k in ['question_text','options','subquestions']):return True
    ids={a['asset_id'] for a in assets if current in a['source_pages']}
    return any(link['question_id']==original['question_id'] and link['asset_id'] in ids
        and link['semantic_role']!='unassigned' for link in assignments)


def flag_unmatched_boundary(record,incoming,output,current,returned):
    """An explicit orphan at the top makes the adjacent tail uncertain, not merged."""
    if not output['questions']:return
    first=output['questions'][0]
    orphan=not first.get('continuation_of') and not first.get('context_closed') and first['source_pages']==[current] and first['cross_page_status'] in ['continues_from_previous','cross_page_uncertain']
    if not orphan:return
    for carry in incoming:
        if not carry.get('boundary_candidate') or carry['carry_id'] in returned:continue
        old=next((q for q in record['questions'] if q['id']==carry['saved_id']),None)
        if old is None:continue
        reason='下一页开头有未能接上的续题，请核对本题是否缺少后续小问或配图。'
        old.update(context_closed=False,continuation_status='pending_continuation',draft_status='pending_continuation',
            content_status='needs_review',review_status='pending',processing_status='review',assembly_allowed=False)
        old['content_issues']=list(dict.fromkeys(old.get('content_issues',[])+[reason]))
        old['issues']=list(old['content_issues'])
        from .figure_workflow import sync
        sync(old)
