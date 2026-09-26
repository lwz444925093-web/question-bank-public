"""One crop, one quality decision, then human routing. No automatic recropping."""
import copy,json,hashlib,time,re,shutil
from pathlib import Path
from typing import Literal
from . import store
from .model import Strict
from .figure_state import image_slots,block_at

VERSION=2
FIGURE_STATUSES={'ready','needs_manual_crop','needs_recrop_from_source','failed'}

class QualityCheck(Strict):
    asset:str
    belongs_to_question:bool
    complete:bool
    critical_labels_present:bool
    contains_other_question_content:bool
    extra_content:Literal['none','minor','excessive']
    reason:str
class QualityChecks(Strict):
    checks:list[QualityCheck]

QUALITY_INSTRUCTION='''逐一对照原始页面与最终实际裁图，检查指定题目/选项，不解题、不修改题干。
每个figures.asset恰好返回一次check。图外孤立标签、箭头、虚线、弧线、单位、刻度也属于必要内容。
belongs_to_question表示该图包含并对应指定题目/选项的图；complete表示所有必要图形内容完整；critical_labels_present表示必要标签齐全。
contains_other_question_content必须检查邻题的题干、数字条件、选项以及图形；即使本题图完整，夹带这些内容也必须为true。
extra_content：none表示图及必要标注以外没有需清理内容；minor表示白边、页脚、少量本题重复文字或容易区分且不影响作答的少量邻近内容；excessive表示整页、大量正文或容易与本题混淆的邻题、相邻选项内容。即使contains_other_question_content=true，少量且不影响使用的邻近内容仍应为minor。
完整但多截文字不应谎报complete=false。确实截断或无法确认完整性则complete=false，说明缺少什么及方向。图配错不得belongs_to_question=true。
reason说明源页对应图、已核对标签及缺陷证据。不要因为流程成功就认为图片合格，不要因白边推断图完整。
只判断，不提议重新调用模型，不输出修图、解题或重绘内容。'''


def classify(check,source_available=True,current_available=True):
    if not source_available and not current_available:
        return 'failed','source_unavailable'
    if check is None:
        return ('needs_recrop_from_source','incomplete') if source_available else ('needs_manual_crop','excessive_context')
    c=check.model_dump() if hasattr(check,'model_dump') else check
    if not c.get('complete') or not c.get('critical_labels_present') or not c.get('belongs_to_question'):
        return ('needs_recrop_from_source','incomplete') if source_available else ('failed','source_unavailable')
    if c.get('extra_content')=='excessive' or (c.get('contains_other_question_content') and c.get('extra_content')!='minor'):
        return 'needs_manual_crop','excessive_context'
    # Cosmetic padding or repeated labels do not affect usability.
    if c.get('extra_content')=='minor':return 'ready',None
    return 'ready',None


def split_import_issues(issues):
    content=[];figures=[]
    for issue in issues:
        figure_only=bool(re.search('裁切|裁剪|裁图|图槽|题图定位|配图',issue)) and not re.search('公式|表达式|负号|正号|指数|根号|分母|读错|题干缺失',issue)
        (figures if figure_only else content).append(issue)
    return content,figures


def ensure(q,content_status=None):
    """Explicit new-workflow initialization; not a historical bulk migration."""
    q['figure_workflow_version']=VERSION
    if 'content_status' not in q:
        from .review_policy import split_issues
        original=q.get('source_snapshot',q)
        issues=split_issues(original.get('issues',[]))[0]
        issues,figure_issues=split_import_issues(issues)
        q['figure_import_issues']=figure_issues
        q['content_issues']=list(issues)
        q['content_status']=content_status or ('needs_review' if issues else 'ready')
    return sync(q)


def sync(q):
    if q.get('figure_workflow_version')!=VERSION:return q
    prior=q.get('figure_records',[]);records=[]
    for slot in image_slots(q):
        record=next((r for r in prior if r.get('figure_id')==slot['figure_id'] and r.get('asset')==slot['asset']),{})
        status=record.get('figure_status','needs_recrop_from_source')
        if status not in FIGURE_STATUSES:status='needs_recrop_from_source'
        records.append(dict(record,figure_id=slot['figure_id'],position=slot['position'],asset=slot['asset'],figure_status=status,state='verified' if status=='ready' else 'unverified'))
    q['figure_records']=records
    states=[r['figure_status'] for r in records]
    stem_text=''.join(s.get('text','') for b in q.get('stem',[]) for s in b.get('spans',[]))
    missing_stem=bool(re.search('如图|图示|图中',stem_text)) and not any(b.get('kind') in ['image','geometry'] for b in q.get('stem',[]))
    facts=q.get('delivery_check') or {}
    # In the fixed-asset delivery contract, option-only diagrams are valid.
    # Keep the explicit missing-asset flag and all actual figure issues.
    if facts.get('required_assets_present') is True and facts.get('content_complete') is True and records:
        missing_stem=False
    q['missing_required_figure']=not q.get('manual_full_review',False) and bool(q.get('missing_required_figure') or missing_stem)
    if q.get('missing_required_figure'):states.append('needs_recrop_from_source')
    q['figure_status']=next((s for s in ['failed','needs_recrop_from_source','needs_manual_crop'] if s in states),'ready')
    # A concrete contradiction cannot be waved through by a contradictory
    # model status='ready'. Positive observations remain informational.
    from .review_policy import has_material_issue
    material_issues=[text for text in q.get('content_issues',[]) if has_material_issue(text)]
    q['directly_usable']=q.get('content_status')=='ready' and not material_issues and all(s=='ready' for s in states)
    reasons=list(q.get('content_issues',[]) if q.get('content_status')!='ready' else material_issues)
    if q.get('missing_required_figure'):reasons.append('缺少作答所需的题图或表格，请对照原页补全。')
    for record in records:
        if record['figure_status']=='ready':continue
        detail=record.get('quality_error') or (record.get('quality_check') or {}).get('reason')
        reasons.append(detail or {'needs_manual_crop':'配图含有较多无关内容，需要核对裁图。','needs_recrop_from_source':'配图归属、完整性或必要标注尚未通过检查。','failed':'配图来源无法恢复。'}.get(record['figure_status'],'配图需要核对。'))
    # Optional answer generation cannot invalidate an otherwise complete source
    # question. Its failures stay in solution_status/solution_issues instead.
    if q.get('continuation_status')=='pending_continuation' or (q.get('import_pipeline')=='d-bank-4-carry-forward' and q.get('context_closed') is not True):
        q['directly_usable']=False
        reasons.append('跨页题的上下文尚未闭合，请补全前后页内容')
    q['review_reasons']=list(dict.fromkeys(reasons))
    q['review_status']='approved' if q['directly_usable'] else 'pending'
    q['processing_status']='complete' if q['directly_usable'] else 'review'
    if q.get('d_import_profile')=='pure_d_light_review_v1' and (q.get('content_status')=='incomplete' or q.get('continuation_status')=='pending_continuation'):
        q['processing_status']='incomplete'
        q['delivery_status']='incomplete'
    q['processing_reason']='' if q['directly_usable'] else ('文字待核对' if q.get('content_status')!='ready' else '图片需要人工处理；文字已保留')
    return q


def can_use(q):
    if q.get('figure_workflow_version')==VERSION:return sync(copy.deepcopy(q))['directly_usable']
    return q.get('review_status')=='approved' and q.get('processing_status') not in ['saved','incomplete'] and all(s['state']=='verified' for s in image_slots(q))


def source_available(q):
    folder=store.DATA/'sources'/q['source']['id']
    return (folder/'original.pdf').is_file() or (folder/'image.png').is_file() or any((folder/s['asset']).is_file() for s in image_slots(q.get('source_snapshot',{}))) or any((folder/s['asset']).is_file() for s in q.get('source_evidence',[]) if s.get('asset') and str(s['asset']).startswith(('page-','image','original.')))


def finish(q,records,checks,error='',localizations=1):
    q=copy.deepcopy(q);ensure(q);old_revision=q['revision'];folder=store.DATA/'sources'/q['source']['id']
    previous={r['figure_id']:r for r in q['figure_records']}
    lookup={c['asset']:c for c in checks}
    for record in records:
        slot=next((s for s in image_slots(q) if s['figure_id']==record['figure_id']),None)
        if not slot and not image_slots(q) and record.get('position')=='stem/'+str(len(q['stem'])):
            slot=dict(figure_id=record['figure_id'],position=record['position'],asset='')
            q['stem'].append(dict(kind='image',asset=record['asset'],spans=[],latex='',rows=[],shapes=[]))
        elif not slot:continue
        else:block_at(q,slot['position'])['asset']=record['asset']
        check=lookup.get(record['asset'])
        status,issue=classify(check,source_available(q),(folder/record['asset']).is_file())
        previous[record['figure_id']]=dict(record,figure_status=status,figure_issue=issue,quality_check=check,quality_error=error,previous_asset=slot['asset'],confirmation='automatic_quality_check' if status=='ready' else None)
    q['figure_records']=list(previous.values())
    for slot in image_slots(q):
        rec=previous.get(slot['figure_id'],dict(slot))
        if rec.get('quality_check') is None and not rec.get('manual_crop'):
            # A retained whole source page can be trimmed by hand. Never certify it.
            whole=slot['asset'].startswith('page-') or slot['asset']=='image.png'
            status,issue=('needs_manual_crop','excessive_context') if whole and (folder/slot['asset']).is_file() else classify(None,source_available(q),(folder/slot['asset']).is_file())
            rec.update(figure_status=status,figure_issue=issue,quality_error=error or '没有可靠的质量判断，保留来源并交人工')
        previous[slot['figure_id']]=rec
    q['figure_records']=[guard_record(r,folder) for r in previous.values()];q['missing_required_figure']=not bool(image_slots(q))
    q['automatic_figure_rounds']=dict(localizations=localizations,quality_judgments=1 if checks else 0,recrops=0)
    q['import_owned_revision']=old_revision+1
    return store.save_question(sync(q),old_revision,image_only=True)


def rebuild_once(bundle,taskdir,cfg,cancel,progress):
    from .diagrams import request_diagram_result,DiagramPlan,INSTRUCTION,apply_plan,combine_meta
    taskdir=Path(taskdir);taskdir.mkdir(parents=True,exist_ok=True)
    cfg=dict(cfg,request_limits={**cfg.get('request_limits',{}),'recrops':0,'format_repairs':0})
    metas=[];updates=[];checks=[];error=''
    progress('首次定位与裁图；不合格图片转人工，不自动重裁')
    try:
        material=dict(bundle,vision_candidates=False,_operation='locate_figures')
        if bundle.get('native_embedded'):
            for expected in bundle['questions']:
                q=store.get('questions',expected['id'])
                native=[];folder=store.DATA/'sources'/bundle['source_id']
                for slot in image_slots(q):
                    original=slot['asset'];digest=hashlib.sha256((folder/original).read_bytes()).hexdigest()
                    asset='native-'+slot['figure_id']+'-'+digest[:12]+Path(original).suffix
                    if not (folder/asset).is_file():shutil.copyfile(folder/original,folder/asset)
                    elif hashlib.sha256((folder/asset).read_bytes()).hexdigest()!=digest:raise ValueError('原生图片副本内容变化，未覆盖')
                    native.append(dict(slot,asset=asset,page=None,box=None,original_asset=original,original_hash=digest,baseline_revision=q['revision']))
                updates.append((q,native))
        else:
            plan,meta=request_diagram_result(material,taskdir/'locate',cfg,cancel,progress,DiagramPlan,INSTRUCTION)
            metas.append(meta)
            updates=apply_plan(material,plan,'initial-'+hashlib.sha256(str(taskdir).encode()).hexdigest()[:8],cancel,progress,dry_run=True)
        folder=store.DATA/'sources'/bundle['source_id'];figures=[];images=[]
        for q,records in updates:
            for record in records:
                src='page-'+str(record['page'])+'.png' if (folder/'original.pdf').is_file() else 'image.png'
                if bundle.get('native_embedded'):src=record['original_asset']
                images.extend([str(folder/src),str(folder/record['asset'])])
                figures.append(dict(question_id=q['id'],question_number=q['original_number'],figure_id=record['figure_id'],position=record['position'],asset=record['asset'],page=record['page'],box=record['box'],source_page=src))
        if figures:
            progress('一次质量判断：归属、完整性、必要标签与邻题内容')
            quality=dict(source_id=bundle['source_id'],original=bundle['original'],images=list(dict.fromkeys(images)),questions=bundle['questions'],figures=figures,_operation='verify_figures')
            verdict,meta=request_diagram_result(quality,taskdir/'quality',cfg,cancel,progress,QualityChecks,QUALITY_INSTRUCTION)
            metas.append(meta);checks=verdict.model_dump()['checks']
            if len(checks)!=len(figures) or len({c['asset'] for c in checks})!=len(checks) or {c['asset'] for c in checks}!={f['asset'] for f in figures}:
                checks=[]
                raise ValueError('质量判断未逐一对应所有图片，保留首次裁图并转人工')
    except Exception as exc:
        if cancel and cancel.is_set():raise
        error=str(exc)[:500]
    by_id={q['id']:records for q,records in updates};saved=[]
    for expected in bundle['questions']:
        if cancel and cancel.is_set():raise ValueError('任务已取消')
        q=store.get('questions',expected['id'])
        if q is None or q['revision']!=expected['revision']:raise ValueError('题目版本已变化，未覆盖')
        saved.append(finish(q,by_id.get(q['id'],[]),checks,error,localizations=0 if bundle.get('native_embedded') else 1))
    report=dict(question_ids=[q['id'] for q in saved],unresolved_question_ids=[q['id'] for q in saved if not q['directly_usable']],failures=[],figures=sum(len(q['figure_records']) for q in saved),redrawn=0,automatic_recrops=0,quality_error=error)
    (taskdir/'routing.json').write_text(json.dumps(dict(result=report,questions=saved),ensure_ascii=False,indent=2))
    return report,combine_meta(metas) if metas else dict(seconds=0,cost='未取得完整用量')

def prepare_material(qid):
    q=store.get('questions',qid);folder=store.DATA/'sources'/q['source']['id']
    if (folder/'original.pdf').is_file() or (folder/'image.png').is_file():
        from .diagrams import prepare_rebuild
        return prepare_rebuild(q['source']['id'],q.get('subject','数学'),[qid])
    # DOCX native image assets already have exact source membership. Reuse those
    # pixels, and perform the quality decision once; no guessed page coordinates.
    slots=image_slots(q)
    material=dict(source_id=q['source']['id'],original=q['source']['file'],pages=q.get('pages',[]),native_embedded=True,crop_only=True,questions=[dict(id=qid,number=q['original_number'],revision=q['revision'],stem=q['stem'],options=q.get('options',[]),subquestions=q.get('subquestions',[]),pages=q.get('pages',[]),figure_slots=slots)])
    return material

def source_continuation_edges(record,folder):
    """Corroborate a cut long stroke against pixels just outside the saved box.

    Ink touching an edge alone is not enough. Use the exact source raster origin
    and the unchanged DPI to show that the same stroke continues beyond it.
    """
    from PIL import Image
    from .diagrams import crop_long_stroke_edges
    from .vision_inputs import render_region,padded_box
    path=Path(folder)/record['asset'];view=record.get('source_render')
    if not path.is_file() or not view or not record.get('box'):return []
    edges=crop_long_stroke_edges(path)
    if not edges:return []
    box=record['box'];size=view['page_size'];unit=1 if view['source_kind']=='pdf' else min(size)/595
    expanded=render_region(folder,record['page'],padded_box(box,size,8*unit),'figure_asset',dpi=view.get('dpi') or 288)
    with Image.open(path) as im,Image.open(expanded['path']) as context:
        im=im.convert('L');context=context.convert('L');w,h=im.size
        ox=round(view['pixel_origin'][0]-expanded['pixel_origin'][0]);oy=round(view['pixel_origin'][1]-expanded['pixel_origin'][1]);cw,ch=context.size
        if ox<0 or oy<0 or ox+w>cw or oy+h>ch:return []
        hits=[]
        for edge in edges:
            pairs=[]
            if edge=='上' and oy>=2:pairs=[((x,0),(ox+x,oy-2)) for x in range(w)]
            if edge=='下' and oy+h+1<ch:pairs=[((x,h-1),(ox+x,oy+h+1)) for x in range(w)]
            if edge=='左' and ox>=2:pairs=[((0,y),(ox-2,oy+y)) for y in range(h)]
            if edge=='右' and ox+w+1<cw:pairs=[((w-1,y),(ox+w+1,oy+y)) for y in range(h)]
            if sum(im.getpixel(a)<100 and context.getpixel(b)<100 for a,b in pairs)>=2:hits.append(edge)
    return hits


def guard_record(record,folder):
    if record.get('confirmation') in ['user_crop_saved','user_review_approved']:return record
    edges=source_continuation_edges(record,folder)
    if edges:
        record['automatic_quality_status_before_local_guard']=record.get('figure_status')
        record.update(figure_status='needs_recrop_from_source',figure_issue='incomplete',local_quality_evidence=dict(kind='long_stroke_continues_in_original_source',edges=edges),local_quality_reason='裁图'+ '、'.join(edges)+'边界的长线在原文中仍有延伸，无法排除本图截断，保守转原文重截（可能涉及相邻图）')
    return record
