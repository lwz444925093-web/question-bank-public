"""Optional CNY ceiling for an isolated validation run, never a daily user quota.

Reserve the uncached peak-price upper bound before each direct request. Failed
or interrupted requests keep that reservation: absence of usage is not free.
"""
import fcntl,json,os,time,uuid,math
from pathlib import Path

def path():
    value=os.environ.get('QUESTION_BANK_VALIDATION_BUDGET')
    return Path(value) if value else None

def update(fn):
    target=path()
    if target is None:return None
    with target.open('r+') as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        data=json.load(f);result=fn(data)
        f.seek(0);json.dump(data,f,ensure_ascii=False,indent=2);f.truncate();f.flush();os.fsync(f.fileno())
        return result

def reserve(payload):
    if path() is None:return None
    if payload.get('model')!='deepseek-flash':raise ValueError('本轮预算护栏仅支持已核价的 DeepSeek Flash')
    # Byte count overestimates text tokens. Official vision ceiling is 1024 per
    # image. Add message framing and double the input bound for conservatism.
    text_bytes=0;images=0
    for message in payload['messages']:
        content=message.get('content','')
        if isinstance(content,str):text_bytes+=len(content.encode())
        else:
            for part in content:
                if part.get('type')=='text':text_bytes+=len(part.get('text','').encode())
                elif part.get('type')=='image_url':images+=1
                else:raise ValueError('本轮预算无法估算该输入类型，未发出请求')
    maximum=payload.get('max_tokens',32768)
    if type(maximum) is not int or maximum<=0:raise ValueError('本轮预算要求正整数输出上限，未发出请求')
    if payload.get('n',1)!=1 or any(payload.get(k) for k in ['tools','functions','response_format','max_completion_tokens']):raise ValueError('本轮预算无法估算额外输出或工具结构，未发出请求')
    payload['max_tokens']=min(maximum,32768)
    bound=math.ceil(((text_bytes+images*1024+4096)*2*2+payload['max_tokens']*8))/1_000_000
    def write(data):
        amounts=[r.get('settled_cny',r['reserved_cny']) for r in data['requests']]
        limit=data.get('limit_cny')
        if type(limit) not in [int,float] or not math.isfinite(limit) or limit<=0 or any(type(v) not in [int,float] or not math.isfinite(v) or v<0 for v in amounts):raise ValueError('预算记录无效，未发出请求')
        charged=sum(amounts)
        if data.get('closed'):raise ValueError('今晚验证已结束，付费请求已关闭')
        if charged+bound>data['limit_cny']:raise ValueError('本轮 API 预算不足，结果已保留，未发出请求')
        ident=uuid.uuid4().hex
        data['requests'].append(dict(id=ident,started_at=time.time(),reserved_cny=bound,state='reserved',max_tokens=payload['max_tokens']))
        return ident
    return update(write)

def settle(ident,meta):
    if ident is None:return
    cost=meta.get('cost_cny_estimate')
    if cost is not None and (type(cost) not in [int,float] or not math.isfinite(cost) or cost<0):
        meta['cost_cny_estimate']=None;meta['budget_warning']='用量费用无效，保留整笔预算预占';cost=None
    def write(data):
        row=next(r for r in data['requests'] if r['id']==ident)
        row.update(state='usage_known' if meta.get('cost_cny_estimate') is not None else 'unknown_reserved',finished_at=time.time(),error=meta.get('error'),usage=meta.get('usage'))
        if meta.get('cost_cny_estimate') is not None:
            row['settled_cny']=max(row.get('settled_cny',0),meta['cost_cny_estimate'])
            if row['settled_cny']>row['reserved_cny']:data['closed']=True
    update(write)

def guard_cli():
    if path() is not None:
        raise ValueError('本轮隔离验收仅开放可计量的 PDF 识别与轻量审查；该操作未发出付费请求，原内容已保留')
