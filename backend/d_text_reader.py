"""One traceable DeepSeek HTTP request per supplied segment, no retries or tools."""
import asyncio,base64,json,os,time
from pathlib import Path
import httpx
from .d_contract import Output,PROMPT
from .d_region_adapter import dump,check
from .costs import flash_cost

def credentials():
    # Match the already verified D/OpenCode credential route explicitly.
    path=Path.home()/'.local/share/opencode/auth.json'
    key=json.loads(path.read_text()).get('deepseek',{}).get('key') if path.is_file() else None
    if not key:raise ValueError('DeepSeek credential unavailable')
    return key

async def _request(payload,key,cancel,timeout):
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=25),trust_env=False) as client:
        task=asyncio.create_task(client.post('https://api.deepseek.com/chat/completions',headers={'Authorization':'Bearer '+key},json=payload))
        started=time.monotonic()
        try:
            while not task.done():
                check(cancel)
                if time.monotonic()-started>timeout:raise TimeoutError('d_text_reader_timeout')
                await asyncio.wait({task},timeout=.2)
            check(cancel)
            return await task
        finally:
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

def read(material,images,folder,cancel=None,timeout=600,*,prompt=None,schema=None,request_format="current",thinking=None,max_tokens=None):
    wall_started=time.time();request_started=None
    prompt=PROMPT if prompt is None else prompt;schema=Output.model_json_schema() if schema is None else schema
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);check(cancel);key=credentials()
    content=[dict(type='text',text=json.dumps(material,ensure_ascii=False))]
    labels=[{'kind':'original_full_page','page':p['page']} for p in material['pages']]+[{'kind':'fixed_asset','asset_id':a['asset_id']} for a in material['asset_catalog']]
    # One original image may be referenced by many questions. Send its bytes
    # once, retaining every label so question/asset provenance stays intact.
    unique={}
    for path,label in zip(images,labels):
        image_key=str(Path(path).resolve())
        unique.setdefault(image_key,[]).append(label)
    for path,aliases in unique.items():
        label=aliases[0] if len(aliases)==1 else {'same_image_labels':aliases}
        content.append(dict(type='text',text=json.dumps(label,ensure_ascii=False)))
        content.append(dict(type='image_url',image_url={'url':'data:image/png;base64,'+base64.b64encode(Path(path).read_bytes()).decode()}))
    payload=dict(model='deepseek-flash',messages=[dict(role='system',content=prompt+'\nSchema:'+json.dumps(schema,ensure_ascii=False)),dict(role='user',content=content)],reasoning_effort='low',stream=False)
    if request_format != 'current':
        from .d_request_format import FORMAT,historical_payload
        if request_format != FORMAT:raise ValueError('Unknown D request format')
        payload,manifest=historical_payload(material,images,folder,prompt,schema)
        dump(folder/'request-images.json',manifest)
    if thinking is False:
        payload.pop('reasoning_effort',None);payload['thinking']={'type':'disabled'}
    if max_tokens is not None:payload['max_tokens']=max_tokens
    dump(folder/'request.json',payload);dump(folder/'material.json',material);dump(folder/'schema.json',schema);(folder/'prompt.txt').write_text(prompt)
    started=time.time();meta=dict(operation='d_full_page_text_and_assignment',request_count=0,input_tokens=None,output_tokens=None,reasoning_tokens=None,cost_cny_estimate=None,started_at=started,model='deepseek-flash',transport='DeepSeek via existing OpenCode credential',images=[str(p) for p in images],locate=0,verify=0,recrop=0)
    meta.update(source_file=material.get('source_file'),pages=[p['page'] for p in material['pages']],carry_range=sorted({p for c in material.get('carry_forward',[]) for p in c['question']['source_pages']}),request_type='single_page_with_carry' if material.get('carry_forward') else 'single_page' if len(material['pages'])==1 else 'legacy_pair',contains_full_page=bool(material['pages']),uses_carry=bool(material.get('carry_forward')),retry=bool(material.get('request_context',{}).get('retry')),retry_reason=material.get('request_context',{}).get('retry_reason'))
    budget_id=None
    try:
        from .validation_budget import reserve
        budget_id=reserve(payload)
        dump(folder/'request.json',payload)
        check(cancel);meta['request_count']=1;dump(folder/'metrics.json',meta)
        request_started=time.time()
        response=asyncio.run(_request(payload,key,cancel,timeout));meta['http_seconds']=time.time()-request_started;meta['http_status']=response.status_code
        (folder/'response.json').write_text(response.text)
        if response.status_code!=200:raise ValueError('deepseek_http_'+str(response.status_code))
        body=response.json();usage=body.get('usage',{});meta['usage']=usage
        cached=usage.get('prompt_cache_hit_tokens',0);reason=usage.get('completion_tokens_details',{}).get('reasoning_tokens',0)
        output=usage.get('completion_tokens');total_input=usage.get('prompt_tokens')
        meta.update(input_tokens=total_input,output_tokens=output,reasoning_tokens=reason)
        valid_usage=all(type(v) is int and v>=0 for v in [output,total_input,cached,reason]) and cached<=total_input and reason<=output
        if valid_usage:
            estimate=flash_cost(dict(input=total_input-cached,output=max(0,output-reason),reasoning=reason,cache={'read':cached}),started)
            meta.update(cost_cny_estimate=estimate['amount'],cost_estimate=estimate)
        choices=body.get('choices',[])
        if len(choices)!=1:raise ValueError('invalid_model_choices')
        choice=choices[0];meta['finish_reason']=choice.get('finish_reason')
        raw=choice['message'].get('content') or '';(folder/'raw.txt').write_text(raw)
        # Truncated text may still yield independently valid partial questions.
        if choice.get('finish_reason')!='stop':meta['warning']='model_output_incomplete'
        check(cancel)
        return raw,meta
    except Exception as exc:meta['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        from .validation_budget import settle
        try:settle(budget_id,meta)
        finally:
            meta.setdefault('http_seconds',time.time()-request_started if request_started is not None else 0);meta['wall_seconds']=time.time()-wall_started;dump(folder/'metrics.json',meta)
