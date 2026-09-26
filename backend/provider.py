import json, subprocess, time, hashlib, threading
from pathlib import Path
from .model import ParseResult
PROMPT_VERSION="source-extraction-phase1-v1"
class ProviderError(Exception): pass
class DeepSeekProvider:
    capabilities={'text':False,'image':False,'structured':False}
    def parse(self,*args,**kwargs): raise ProviderError('DeepSeek 未实现且未启用')
class CodexCliProvider:
    capabilities={'text':True,'image':True,'structured':True}
    def __init__(self,root,config): self.root=Path(root); self.config=config
    def key(self,bundle):
        return hashlib.sha256(json.dumps([bundle,'codex',self.config,PROMPT_VERSION,'1.0'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def parse(self,bundle,taskdir,cancel=None,progress=None):
        from .request_boundary import call,RequestFailure
        from .opencode_import import SOURCE_PROMPT
        outer=self
        class Transport:
            config=outer.config
            def _request(self,material,directory,schema,instruction,cancel,progress):
                parsed,meta=outer._parse(material,directory,cancel,progress)
                return json.dumps(parsed,ensure_ascii=False),meta
        try:raw,meta=call(Transport(),bundle,taskdir,ParseResult.model_json_schema(),SOURCE_PROMPT,cancel,progress)
        except RequestFailure as exc:
            error=ProviderError(str(exc));error.category=exc.category;raise error from exc
        return json.loads(raw),meta
    def _parse(self,bundle,taskdir,cancel=None,progress=None):
        progress=progress or (lambda text: None)
        taskdir=Path(taskdir); taskdir.mkdir(parents=True,exist_ok=True)
        schema=taskdir/'schema.json'; schema.write_text(json.dumps(ParseResult.model_json_schema()))
        out=taskdir/'final.json'
        from .opencode_import import SOURCE_PROMPT
        prompt=SOURCE_PROMPT+'\n'+json.dumps(bundle,ensure_ascii=False)
        cmd=[self.config.get('executable','codex'),'exec','--skip-git-repo-check','--ephemeral','-s','read-only','-C',str(taskdir),'--output-schema',str(schema),'-o',str(out),'--json']
        if self.config.get('model'): cmd+=['-m',self.config['model']]
        if self.config.get('reasoning'): cmd+=['-c','model_reasoning_effort='+json.dumps(self.config['reasoning'])]
        for image in bundle.get('images',[]): cmd+=['-i',image]
        for feature in ['shell_tool','unified_exec','apps','plugins','hooks','browser_use','computer_use','image_generation','in_app_browser','multi_agent','multi_agent_v2','chronicle','skill_search','workspace_dependencies','unbounded_connection_retries']:
            cmd+=['--disable',feature]
        cmd+=['-c','web_search="disabled"','-']
        progress('调用 AI：区分知识点与题目，提取题目及答案解析')
        start=time.monotonic(); last_update=start
        with (taskdir/'events.private.jsonl').open('w') as events, (taskdir/'stderr.private.log').open('w') as err:
            proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=events,stderr=err,text=True)
            proc.stdin.write(prompt); proc.stdin.close()
            while proc.poll() is None:
                if cancel and cancel.is_set(): proc.terminate(); proc.wait(timeout=10); raise ProviderError('任务已取消')
                if time.monotonic()-start>self.config.get('timeout_seconds',300): proc.terminate(); proc.wait(timeout=10); raise ProviderError('Codex 超时')
                if time.monotonic()-last_update>=15:
                    progress('AI 正在处理，已等待 '+str(int(time.monotonic()-start))+' 秒（尚未返回最终结果）'); last_update=time.monotonic()
                time.sleep(.2)
        if proc.returncode:
            error_text=(taskdir/'stderr.private.log').read_text(errors='replace')+(taskdir/'events.private.jsonl').read_text(errors='replace')
            if any(token in error_text.lower() for token in ['quota','usage limit','rate limit','insufficient_quota']):
                from . import store
                usage=store.get('settings','usage') or {'calls':0}; usage['stopped']=True; store.put('settings','usage',usage)
            raise ProviderError('Codex 退出码 '+str(proc.returncode)+'；检查本机登录、配额和沙箱权限。私有错误日志保存在任务目录，不公开返回。')
        progress('AI 已返回，校验题目结构、公式与来源')
        from .opencode_import import validate_parse_output
        raw=out.read_text()
        (taskdir/'extraction-raw.private.txt').write_text(raw)
        try:result=validate_parse_output(raw,bundle)
        except ValueError as exc:raise ProviderError('模型最终输出校验失败，原返回已保存：'+str(exc)[:200]) from exc
        usage='未提供'
        model=self.config.get('model') or '继承本机配置，未提供实际模型'
        for line in (taskdir/'events.private.jsonl').read_text().splitlines():
            try:
                event=json.loads(line)
                if isinstance(event.get('model'),str): model=event['model']
                if isinstance(event.get('usage'),dict): usage=event['usage']
            except ValueError: pass
        return result.model_dump(),dict(provider='codex',model=model,seconds=round(time.monotonic()-start,2),tokens=usage,cost='未提供')
