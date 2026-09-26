"""Retain absent tail figures and conservatively join explicitly numbered orphans."""
import copy
import re
from .d_light import MINOR

TAIL_NOTE='页尾题引用的配图未出现在本页，保留前文等待下一页确认'
JOIN_REVIEW='相邻页明确题号的配图已补入，请核对合并后的图文与关键标注。'


def source_figure_absent(question):
    facts=question.get('delivery_check') or {}
    issues=(question.get('quality_issues') or [])+facts.get('issues',[])
    rows=[i for i in issues if i.get('code')=='missing_asset']
    if not rows and facts.get('required_assets_present') is not False:return False
    # Asset-linked defects belong to an existing image, not an absent next-page
    # figure. The caller also rejects any assignment to this question.
    if any(i.get('asset_ids') for i in issues):return False
    if any(i.get('code') in {'missing_critical_label','missing_image_structure','missing_table_information','image_text_conflict','wrong_assignment'} for i in issues):return False
    notes=question.get('issues',[])+[i.get('detail','') for i in rows]
    if any(re.search(r'裁[切剪图]|截断|截掉|被截|固定(?:图片|图像|图|asset)|本页(?:题)?图(?:形)?(?:存在|可见)',text) for text in notes):return False
    # A structured missing-asset finding and an explicit stem reference are
    # enough to retain unfinished context. Do not rely on the model choosing a
    # particular phrase such as "完整原页未见"; carry is not quality approval.
    if rows and re.search(r'如[下左右上]?图|图中|图示|[下左右]图|如[下]?表|表中|下表',question.get('question_text','')):return True
    # Legacy delivery facts may lack an explicit reference in their stem.
    return any(re.search(r'(?:本页|当前页|完整原页|原页|页面)[^，,。；;]{0,24}(?:未提供|未见|没有|无对应|未包含)[^，,。；;]{0,24}(?:配图|题图|图形|图表|图片)',text)
               or re.search(r'(?:配图|题图|图形|图表)[^，,。；;]{0,12}(?:不在|未出现在)(?:本页|当前页|原页)',text)
               for text in notes)


def join_numbered_orphan(output,incoming,assets,current):
    """Recover only a unique next-page numbered figure, keeping a review gate.

    This is a local attachment, not a claim of merged visual QA. Complete
    model-returned continuations retain the ordinary semantic/closure path.
    """
    byasset={a['asset_id']:a for a in assets}
    for carry in incoming:
        prior=carry['question'];number=str(prior.get('source_number') or '').strip()
        if not number or prior.get('source_pages')!=[current-1] or TAIL_NOTE not in prior.get('issues',[]):continue
        if carry.get('assets') or carry.get('asset_assignments'):continue
        if sum(str(c['question'].get('source_number') or '').strip()==number for c in incoming)!=1:continue
        if any(q.get('continuation_of')==carry['carry_id'] or q.get('question_id')==prior['question_id'] or str(q.get('source_number') or '').strip()==number for q in output['questions']):continue
        quality=prior.get('quality_issues')
        if not isinstance(quality,list) or not any(i['code']=='missing_asset' for i in quality):continue
        if any(i['code'] not in MINOR|{'missing_asset'} for i in quality):continue
        if any(i['code']=='missing_asset' and i.get('asset_ids') for i in quality):continue
        if any(note!=TAIL_NOTE for note in prior.get('issues',[])):continue
        caption=re.compile(r'第\s*'+re.escape(number)+r'\s*题')
        matches=[]
        for link in output['asset_assignments']:
            a=byasset.get(link['asset_id'])
            if not a or a.get('source_pages')!=[current] or a.get('asset_type')!='figure':continue
            if link['semantic_role']!='unassigned' or link.get('question_id') is not None:continue
            if any(caption.fullmatch(t.strip()) for t in link.get('associated_text',[])):matches.append(link)
        if len(matches)!=1:continue
        link=matches[0]
        if sum(l['asset_id']==link['asset_id'] for l in output['asset_assignments'])!=1:continue
        merged=copy.deepcopy(prior)
        merged.update(source_pages=[current-1,current],cross_page_status='continues_from_previous',context_closed=True,continuation_of=carry['carry_id'])
        merged['issues']=[i for i in merged['issues'] if i!=TAIL_NOTE]
        merged['quality_issues']=[i for i in quality if i['code']!='missing_asset']
        merged['_local_asset_join']=dict(basis='unique-numbered-adjacent-orphan',asset_id=link['asset_id'],source_pages=[current-1,current],source_number=number,
            previous_missing_issues=copy.deepcopy(quality),original_assignment=copy.deepcopy(link),merged_quality_checked=False)
        link.update(question_id=merged['question_id'],semantic_role='stem_support',option_label=None,reason='本地补关联：相邻前页缺图末题与唯一明确题号图注一致。')
        output['questions'].insert(0,merged)


def retain_join_review(question,raw):
    evidence=raw.get('_local_asset_join')
    if not evidence:return
    question.update(local_asset_join=copy.deepcopy(evidence),content_status='needs_review',delivery_status='needs_review',draft_status='needs_review',quality_check_status='pending')
    question['content_issues']=list(dict.fromkeys(question.get('content_issues',[])+[JOIN_REVIEW]))
    question['issues']=list(question['content_issues'])
    for record in question['figure_records']:
        if record.get('asset_id')==evidence['asset_id']:
            record.update(quality_check_status='pending',delivery_basis='local-numbered-adjacent-asset-link',original_status='unverified')
