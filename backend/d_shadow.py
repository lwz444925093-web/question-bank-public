"""Isolated import staging: never imports store, tasks, or the old model pipeline."""
import hashlib,json,os,threading,time,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .d_region_adapter import VERSION,dump,check,prepare_source,detect,asset_builder
from .d_recovery import recover
from .d_assembler import assemble
from .d_text_reader import read
ROOT=Path(__file__).resolve().parents[1]
SHADOW_ROOT=Path(os.environ.get('QUESTION_BANK_D_SHADOW_ROOT',ROOT/'work/d-shadow'))
POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='d-shadow')
LOCK=threading.RLock();CANCEL={}
TRANSPORT_BLOCKED=threading.Event()

def folder_for(run_id):
    if len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id):raise ValueError('invalid_shadow_id')
    return SHADOW_ROOT/run_id

def get(run_id):
    file=folder_for(run_id)/'result.json'
    if not file.is_file():raise ValueError('shadow_import_not_found')
    return json.loads(file.read_text())

def submit(raw,name,subject,start=1,end=0):
    if subject not in ['数学','物理']:raise ValueError('unsupported_subject')
    key=hashlib.sha256(raw+json.dumps([VERSION,Path(name).suffix.lower(),subject,start,end]).encode()).hexdigest()
    with LOCK:
        SHADOW_ROOT.mkdir(parents=True,exist_ok=True)
        for file in SHADOW_ROOT.glob('*/result.json'):
            try:old=json.loads(file.read_text())
            except (ValueError,OSError):continue
            if old.get('key')==key:
                # Unknown outcome on process restart is retained, never auto reissued.
                if old['status'] in ['queued','running'] and old['id'] not in CANCEL:
                    old.update(status='interrupted',error='server_restart_no_automatic_retry');dump(file,old)
                return old|dict(duplicate=True)
        run_id=uuid.uuid4().hex;folder=folder_for(run_id);folder.mkdir()
        record=dict(id=run_id,key=key,version=VERSION,mode='d_shadow',status='queued',display_name=name,subject=subject,created_at=time.time(),questions=[],pages=[],assets=[],errors=[],production_db_writes=0,review_url='/d-shadow/?id='+run_id)
        dump(folder/'result.json',record);CANCEL[run_id]=threading.Event()
        POOL.submit(run,record,raw,name,subject,start,end,CANCEL[run_id])
        return record

def cancel(run_id):
    with LOCK:
        record=get(run_id)
        if record['status'] in ['queued','running']:
            if run_id in CANCEL:CANCEL[run_id].set()
            record['cancel_requested']=True;dump(folder_for(run_id)/'result.json',record)
        return record

def run(record,raw,name,subject,start,end,cancel,reader=None,folder=None,on_update=None,selected_pages=None,reuse_calls=False,delivery=False):
    folder=Path(folder) if folder is not None else folder_for(record['id']);started=time.time();reader=reader or read
    if delivery:
        from .d_delivery import recover as recover_output,build as assemble_output
        from .d_delivery_contract import PROMPT,Output
    else:recover_output,assemble_output=recover,assemble
    def save():
        with LOCK:
            record['updated_at']=time.time();dump(folder/'result.json',record)
        if on_update:on_update(record)
    try:
        check(cancel);record['status']='running';save()
        source,pdf=prepare_source(raw,name,folder/'source',start,end);source.update(subject=subject,import_id=record['id']);record['source']=source;save()
        if source.get('unsupported'):record['errors'].append(source['unsupported']);record['status']='incomplete';return
        if selected_pages is not None:
            if not set(selected_pages)<=set(source['pages']):raise ValueError('invalid_selected_pages')
            source['pages']=list(selected_pages)
        region_start=time.monotonic();units=[]
        composite_path=Path(__file__).with_name('d_locked_composites.json')
        registry=json.loads(composite_path.read_text()) if composite_path.exists() else {}
        for n in source['pages']:
            check(cancel);pagefolder=folder/'regions'/str(n)
            try:
                result=detect(pdf,n,source['source_id'],pagefolder,cancel)
                page=result['page'];assets=asset_builder(result['regions'],pagefolder,registry.get(source['source_id'],{}).get(str(n),[]))
                page['region_path']=str(pagefolder);record['pages'].append(page);record['assets'].extend(assets);units.append((page,assets));save()
            except InterruptedError:raise
            except Exception as exc:
                record['errors'].append(dict(page=n,warning='unsupported_page',error=str(exc)));save()
        record['region_seconds']=time.monotonic()-region_start
        # Non-overlapping adjacent pairs: no semantic merge inferred from printed numbers.
        while units:
            check(cancel);batch=[units.pop(0)]
            if units and units[0][0]['page']==batch[0][0]['page']+1:batch.append(units.pop(0))
            pages=[p['page'] for p,_ in batch];assets=[a for _,aa in batch for a in aa];callfolder=folder/'calls'/('-'.join(map(str,pages)))
            material=dict(subject=subject,source_pages=pages,pages=[dict(page=p['page'],original=p['original'],classification=p['classification']) for p,_ in batch],asset_catalog=[{k:v for k,v in a.items() if k not in ['path','warnings']} for a in assets])
            images=[Path(p['region_path'])/p['original'] for p,_ in batch]+[Path(a['path']) for a in assets]
            try:
                if reuse_calls and (callfolder/'raw.txt').is_file() and (callfolder/'metrics.json').is_file():
                    raw_reply=(callfolder/'raw.txt').read_text();meta=json.loads((callfolder/'metrics.json').read_text())
                else:
                    if reader is read and TRANSPORT_BLOCKED.is_set():raise ValueError('transport_blocked_by_previous_auth_or_quota_failure')
                    if delivery and (callfolder/'metrics.json').exists():raise ValueError('请求已发出但结果不完整，请核对日志；不会自动重发原页')
                    record['active_call']=dict(pages=pages,started_at=time.time());save()
                    raw_reply,meta=reader(material,images,callfolder,cancel,**(dict(prompt=PROMPT,schema=Output.model_json_schema()) if delivery else {}))
                record.pop('active_call',None)
                check(cancel);recovery=recover_output(raw_reply)
                if meta.get('warning') and recovery['status'] in ['raw_success','repaired']:
                    recovery['status']='partial';recovery['output']['issues'].append(meta['warning'])
                dump(callfolder/'recovery.json',recovery)
                assembly_source=source if record.get('mode')!='d_bank' else dict(source,import_id=record['id']+':'+','.join(map(str,pages)))
                built=assemble_output(recovery,assets,assembly_source,pages,0 if record.get('mode')=='d_bank' else len(record['questions']))
                record['questions'].extend(built['questions']);record.setdefault('units',[]).append(dict(pages=pages,recovery=recovery['status'],**{k:v for k,v in built.items() if k!='questions'}))
                if built['assembly_errors']:record['errors'].append(dict(pages=pages,error='assembly_validation',details=built['assembly_errors']))
                if recovery['status'] in ['partial','unrecoverable']:record['errors'].append(dict(pages=pages,error='schema_'+recovery['status']))
                if any(p['classification']=='uncertain' for p,_ in batch):
                    for q in built['questions']:
                        q['warning'].append('unsupported_page');q['issues'].append('unsupported_page');q.update(draft_status='needs_review' if q['assembly_allowed'] else 'incomplete',review_status='pending')
                save()
            except InterruptedError:raise
            except Exception as exc:
                record['errors'].append(dict(pages=pages,error=type(exc).__name__+': '+str(exc)));save()
                if any(code in str(exc) for code in ['deepseek_http_401','deepseek_http_402','deepseek_http_403','transport_blocked']):
                    TRANSPORT_BLOCKED.set();record['errors'].append(dict(unprocessed_pages=[p['page'] for p,_ in units],error='dependency_failure_no_retry'));break
        check(cancel);record['status']='incomplete' if record['errors'] else 'succeeded'
    except InterruptedError:record['status']='cancelled'
    except Exception as exc:record.update(status='failed',error=type(exc).__name__+': '+str(exc))
    finally:
        record.pop('active_call',None)
        record['wall_seconds']=time.time()-started
        metrics=[json.loads(p.read_text()) for p in (folder/'calls').glob('*/metrics.json')]
        record['metrics']=dict(requests=sum(m.get('request_count',0) for m in metrics),http_seconds=sum(m.get('http_seconds',0) for m in metrics),locate=0,verify=0,recrop=0,calls=metrics)
        for key in ['input_tokens','output_tokens','reasoning_tokens','cost_cny_estimate']:
            vals=[m.get(key) for m in metrics];record['metrics'][key]=sum(v for v in vals if v is not None) if vals and all(v is not None for v in vals) else None
        record['counts']={s:sum(q['draft_status']==s for q in record['questions']) for s in ['ready','needs_review','incomplete']}
        record['finished_at']=time.time();save()

def artifact(run_id,path):
    folder=folder_for(run_id).resolve();target=(folder/path).resolve()
    if not target.is_relative_to(folder) or not target.is_file():raise ValueError('invalid_shadow_artifact')
    # Credentials are never stored; original document and all evidence remain local.
    return target

def annotate(run_id,qid,data):
    """Versioned human notes in isolated staging, never question-table writes."""
    with LOCK:
        record=get(run_id)
        if record['status'] in ['queued','running']:raise ValueError('wait_for_import_completion')
        q=next((q for q in record['questions'] if q['id']==qid),None)
        if q is None:raise ValueError('question_not_found')
        if data.get('revision')!=q['revision']:raise ValueError('revision_conflict')
        note=data.get('note','')
        if not isinstance(note,str) or len(note)>10000:raise ValueError('invalid_note')
        q.setdefault('review_history',[]).append(dict(revision=q['revision'],note=note,time=time.time()))
        q['review_note']=note;q['revision']+=1
        dump(folder_for(run_id)/'result.json',record);return q
