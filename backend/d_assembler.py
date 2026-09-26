"""Deterministic D-to-existing Question adapter. No persistence or image edits."""
import copy,re,uuid
from .model import Extracted,paragraph

def text_blocks(text):
    # Preserve all characters. Only explicit math delimiters change representation.
    if not text:return []
    blocks=[]
    for line in text.splitlines():
        if not line:continue
        spans=[];cursor=0
        for m in re.finditer(r'\\\((.*?)\\\)|\\\[(.*?)\\\]|\$\$(.*?)\$\$|(?<!\\)\$([^$\n]+)\$',line):
            if m.start()>cursor:spans.append(dict(kind='text',text=line[cursor:m.start()]))
            spans.append(dict(kind='math',text=next(x for x in m.groups() if x is not None)));cursor=m.end()
        if cursor<len(line):spans.append(dict(kind='text',text=line[cursor:]))
        b=paragraph('');b['spans']=spans;blocks.append(b)
    return blocks

def condition_key(text):
    """A literal condition key, with only unambiguous symbol spelling changes.

    This is deliberately not symbolic simplification: values, operators,
    subscripts, grouping and signs keep their identity.
    """
    value=''.join(text.split()).strip('，,。；;')
    value=re.sub(r'\\angle(?![A-Za-z])','∠',value)
    # Whitespace after LaTeX commands was removed above; match the command
    # before its conventional upper-case vertex name as well.
    value=re.sub(r'\\angle(?=[A-Z])','∠',value)
    value=re.sub(r'\^\{\\circ\}|\^\\circ\b|\\degree\b','°',value)
    for command,symbol in [('leq','≤'),('le','≤'),('geq','≥'),('ge','≥'),('neq','≠'),('ne','≠')]:
        value=re.sub(r'\\'+command+r'(?![a-z])',symbol,value)
    if not re.search(r'[=<>≤≥≠]',value) or re.search(r'[\u4e00-\u9fff]',value):return None
    return value if 3<=len(value)<=160 else None

def associated_blocks(text,existing,dedupe_conditions=False):
    """Suppress exact repeated source paragraphs, retaining short diagram labels.

    Never rewrite mathematical expressions or deduplicate a short point name
    merely because the same letter occurs somewhere in the question.
    """
    existing_keys={tuple((s['kind'],''.join(s['text'].split())) for s in b.get('spans',[])) for b in existing if b.get('kind')=='paragraph'}
    conditions=set()
    if dedupe_conditions:
        for block in existing:
            if block.get('kind')=='equation':units=[block.get('latex','')]
            elif block.get('kind')=='paragraph':
                spans=block.get('spans',[])
                units=[s['text'] for s in spans if s['kind']=='math']
                # Plain-text conditions are compared as entire clauses, never
                # as substrings (AB=3 must not match AB=30 or XAB=3).
                units+=re.split(r'[，,。；;]', ''.join(s['text'] for s in spans if s['kind'] in ['math','text']))
            else:continue
            conditions.update(key for unit in units if (key:=condition_key(unit)))
    kept=[]
    for block in text_blocks(text):
        key=tuple((s['kind'],''.join(s['text'].split())) for s in block['spans'])
        if sum(len(v) for _,v in key)>=6 and key in existing_keys:continue
        condition=condition_key(''.join(s['text'] for s in block['spans'])) if dedupe_conditions else None
        if condition and condition in conditions:continue
        kept.append(block);existing_keys.add(key)
    return kept

def without_repeated_subquestion_tail(text,subquestions):
    """Drop only a complete, numbered, verbatim duplicate at the stem's end."""
    if not subquestions or any(not s.get('number','').strip() or not s.get('text','').strip() for s in subquestions):return text
    if len({s['number'] for s in subquestions})!=len(subquestions):return text
    tail=''.join(''.join((s['number']+s['text']).split()) for s in subquestions)
    indices=[i for i,c in enumerate(text) if not c.isspace()]
    compact=''.join(text[i] for i in indices)
    if not tail or not compact.endswith(tail) or len(compact)<=len(tail):return text
    start=indices[len(compact)-len(tail)]
    # An embedded quoted condition is not a standalone list of subquestions.
    if text[text.rfind('\n',0,start)+1:start].strip():return text
    return text[:start].rstrip()

def cross_page_guard(q,assets,allowed_pages,continuation_mode=False):
    warnings=[];pages=q['source_pages']
    if any(p not in allowed_pages for p in pages) or len(set(pages))!=len(pages):warnings.append('cross_page_inconsistent')
    if (len(pages)>2 and not continuation_mode) or (pages and sorted(pages)!=list(range(min(pages),max(pages)+1))):warnings.append('cross_page_inconsistent')
    for asset in assets:
        if not set(asset['source_pages'])<=set(pages):warnings.append('cross_page_inconsistent')
    state=q['cross_page_status']
    if state in ['cross_page_uncertain','starts_on_page_continues_next'] or (state=='continues_from_previous' and len(pages)==1):warnings.append('cross_page_uncertain')
    if state=='complete_on_page' and len(pages)!=1:warnings.append('cross_page_inconsistent')
    return list(dict.fromkeys(warnings))

def reconcile_cross_page(q,assets,links,allowed_pages):
    """A named figure on the adjacent input page can complete its named question."""
    foreign=[a for a in assets if not set(a['source_pages'])<=set(q['source_pages'])]
    pages=sorted(set(q['source_pages'])|{p for a in assets for p in a['source_pages']})
    number=str(q.get('source_number') or '').strip()
    if not foreign or not number or q['cross_page_status']!='complete_on_page':return
    if len(pages)!=2 or pages[1]-pages[0]!=1 or not set(pages)<=set(allowed_pages):return
    label=re.compile(r'第\s*'+re.escape(number)+r'\s*题')
    for asset in foreign:
        link=links[asset['asset_id']]
        # Require an explicit matching figure caption, not mere page proximity.
        if not any(label.fullmatch(text.strip()) for text in link.get('associated_text',[])):return
    q['source_pages']=pages
    q['cross_page_status']='continues_from_previous'

def assemble(recovery,assets,source,unit_pages,offset=0,continuation_mode=False):
    data=recovery['output'];byasset={a['asset_id']:a for a in assets};links={};errors=[];qs=data['questions'];ids=[q['question_id'] for q in qs]
    if len(set(ids))!=len(ids):errors.append('duplicate_question_id')
    for link in data['asset_assignments']:
        aid=link['asset_id']
        if aid not in byasset:errors.append('unknown_asset:'+aid);continue
        if aid in links:errors.append('duplicate_asset_assignment:'+aid);continue
        if link['semantic_role']=='unassigned':
            if link['question_id'] is not None or not link['reason'].strip():errors.append('invalid_unassigned:'+aid)
        elif link['question_id'] not in ids:errors.append('unknown_question_reference:'+aid)
        links[aid]=link
    for aid in byasset:
        if aid not in links:errors.append('missing_asset_assignment:'+aid)
    coverage=data.get('page_extractions',[])
    if len(coverage)!=len(unit_pages) or {p['page'] for p in coverage}!=set(unit_pages):errors.append('page_coverage_unconfirmed')
    if any(p['status']=='incomplete' for p in coverage):errors.append('page_coverage_incomplete')
    if any(p['status']=='no_questions' and any(p['page'] in q['source_pages'] for q in qs) for p in coverage):errors.append('page_coverage_inconsistent')
    drafts=[]
    for index,original in enumerate(qs):
        q=copy.deepcopy(original);assigned=[byasset[aid] for aid,l in links.items() if l['question_id']==q['question_id'] and l['semantic_role']!='unassigned']
        reconcile_cross_page(q,assigned,links,unit_pages)
        # Batch-wide warnings belong to the task; only explicitly targeted
        # diagnostics may be inherited by an individual question.
        number=str(q.get('source_number') or '').strip()
        targeted=[w for w in data.get('issues',[]) if number and re.search(r'第\s*'+re.escape(number)+r'\s*题',w)]
        all_issues=q['issues']+targeted
        # Printed-number absence is provenance, never a content blocker.
        number_notes=[w for w in all_issues if re.search('未显示原印刷题号|未标明题号',w) and not re.search('题干缺|文字缺|截断|无法辨认',w)]
        warnings=list(dict.fromkeys([w for w in all_issues if w not in number_notes]+errors+cross_page_guard(q,assigned,unit_pages,continuation_mode)))
        if recovery['status'] in ['partial','unrecoverable']:warnings.append('schema_partial_recovery')
        if not q['question_text'].strip():warnings.append('missing_question_text')
        if (q['requires_image'] or re.search('如图|图中|示意图|图象',q['question_text'])) and not assigned:warnings.append('missing_image_asset')
        stem=text_blocks(without_repeated_subquestion_tail(q['question_text'],q['subquestions']));options=[dict(label=o['label'],blocks=text_blocks(o['text'])) for o in q['options']];subs=[dict(label=s['number'],blocks=text_blocks(s['text'])) for s in q['subquestions']]
        if len({o['label'] for o in options})!=len(options):warnings.append('duplicate_option_label')
        records=[];associated=[];refs=[]
        for a in assigned:
            link=links[a['asset_id']];warnings.extend(a.get('warnings',[]));role=link['semantic_role']
            # Page mismatch blocks formal attachment; preserve evidence as a rejected link.
            ref={**a,'semantic_role':role,'associated_text':link['associated_text'],'png_contains_associated_text':'not_claimed'}
            refs.append(ref)
            if not set(a['source_pages'])<=set(q['source_pages']):continue
            blocks=stem
            if role=='option':
                matches=[o for o in options if o['label']==link['option_label']]
                if len(matches)!=1:warnings.append('invalid_option_reference:'+a['asset_id']);continue
                blocks=matches[0]['blocks']
            block=paragraph('');block.update(kind='image',spans=[],asset=a['asset']);blocks.append(block)
            for text in link['associated_text']:
                added=associated_blocks(text,blocks,dedupe_conditions=role!='option')
                associated.append(dict(asset_id=a['asset_id'],text=text,origin='full_page',png_contains_text='not_claimed',displayed=bool(added)))
                blocks.extend(added)
            records.append(dict(asset=a['asset'],original_asset=a['asset'],content_hash=a['pixel_sha256'],asset_id=a['asset_id'],asset_type=a['asset_type'],semantic_role=role,source_pages=a['source_pages'],region_ids=a['region_ids'],figure_status='needs_manual_crop' if a['warnings'] else 'ready',figure_issue='uncertain' if a['warnings'] else None,automatic_recrops=0))
        warnings=list(dict.fromkeys(warnings));fatal=any(w in warnings for w in ['cross_page_inconsistent','missing_question_text','duplicate_question_id'])
        status='incomplete' if fatal else ('needs_review' if warnings else 'ready')
        order=offset+index+1;qid=uuid.uuid5(uuid.NAMESPACE_URL,source['import_id']+':'+str(order)).hex
        extracted=dict(original_number=q.get('source_number') or '',subject=source['subject'],grade='',question_type='选择题' if options else '解答题',knowledge=[],difficulty='',stem=stem,options=options,subquestions=subs,original_answer=[],original_explanation=[],ai_answer=[],ai_explanation=[],pitfalls=[],issues=warnings,pages=q['source_pages'])
        from .table_normalize import normalize
        table_context=dict(extracted,asset_refs=refs,figure_records=records)
        normalize(table_context)
        extracted={k:table_context[k] for k in extracted};records=table_context['figure_records']
        extracted=Extracted.model_validate(extracted).model_dump()
        drafts.append(extracted|dict(id=qid,internal_question_id=qid,source_order=order,source_number=q.get('source_number'),source_pages=q['source_pages'],cross_page_status=q['cross_page_status'],draft_status=status,assembly_allowed=not fatal,review_status='approved' if status=='ready' else 'pending',processing_status='complete' if status=='ready' else 'review',source_number_notes=number_notes,revision=1,human_answer=[],human_explanation=[],source=dict(id=source['source_id'],file=source['original'],display_name=source['display_name'],pages=q['source_pages']),figure_records=records,asset_refs=refs,associated_text=associated,warning=warnings,solution_status='needs_generation',source_snapshot=copy.deepcopy(extracted),raw_transcription=q))
    return dict(questions=drafts,assembly_errors=errors,unassigned_assets=[l for l in links.values() if l['semantic_role']=='unassigned'],page_extractions=coverage)
