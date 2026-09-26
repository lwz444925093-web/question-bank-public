"""One metered request for solving; keep the configured model and source input."""
import hashlib,io,json,time
from pathlib import Path
from .opencode_import import OpenCodeProvider

def image_references(value,path='question'):
    if isinstance(value,dict):
        if value.get('kind')=='image':
            asset=value.get('asset') or value.get('text')
            if asset:yield dict(asset=asset,position=path)
        for key,child in value.items():yield from image_references(child,path+'/'+key)
    elif isinstance(value,list):
        for i,child in enumerate(value):yield from image_references(child,path+'/'+str(i))


def prepare_images(bundle,taskdir):
    """Bind current assets to attachments; rasterize locally before any API call."""
    from PIL import Image,ImageOps
    from .export_images import svg_png
    paths=[Path(p) for p in bundle.get('images',[])]
    refs=list(image_references(bundle.get('question',{})))
    missing={r['asset'] for r in refs}-{p.name for p in paths}
    if missing:raise ValueError('必要题图或公式图片缺失，未请求答案生成：'+'、'.join(sorted(missing)))
    images=[];catalog=[];evidence=[]
    for i,path in enumerate(paths):
        raw=path.read_bytes();original_sha=hashlib.sha256(raw).hexdigest()
        if path.suffix.lower()=='.svg':raw=svg_png(raw)
        try:
            with Image.open(io.BytesIO(raw)) as im:
                im=ImageOps.exif_transpose(im).convert('RGBA')
                canvas=Image.new('RGBA',im.size,'white');canvas.alpha_composite(im)
                out=Path(taskdir)/f'question-image-{i+1}.png';canvas.convert('RGB').save(out,format='PNG')
        except Exception as exc:raise ValueError('题图无法读取，未请求答案生成：'+path.name) from exc
        aid='question-image-'+str(i+1)
        catalog.append(dict(asset_id=aid,asset=path.name,positions=[r['position'] for r in refs if r['asset']==path.name],role='current_question_image'))
        evidence.append(dict(asset=path.name,source_sha256=original_sha,attachment=out.name,attachment_sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
        images.append(out)
    (Path(taskdir)/'image-inputs.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    return images,catalog

class SolutionProvider(OpenCodeProvider):
    @property
    def metered_http(self):
        return (self.config.get('model') or 'deepseek/deepseek-flash') in ['deepseek/deepseek-flash','deepseek-flash']

    def _request(self,bundle,taskdir,schema,instruction,cancel=None,progress=None):
        if not self.metered_http:return super()._request(bundle,taskdir,schema,instruction,cancel,progress)
        from .d_text_reader import read
        taskdir=Path(taskdir);taskdir.mkdir(parents=True,exist_ok=True);started=time.time();usage={}
        try:
            images,catalog=prepare_images(bundle,taskdir)
            material={k:v for k,v in bundle.items() if k!='images'}
            material.update(source_file=bundle.get('display_name','题目'),pages=[],asset_catalog=catalog)
            if progress:progress('正在生成答案和解析')
            raw,meta=read(material,images,taskdir,cancel,timeout=self.config.get('timeout_seconds',180),prompt=instruction,schema=schema,max_tokens=16384)
        finally:
            metrics=taskdir/'metrics.json'
            if metrics.exists():
                usage=json.loads(metrics.read_text())
            else:usage=dict(request_count=0,cost_cny_estimate=0,cost_estimate=dict(amount=0,currency='CNY',estimated=True),wall_seconds=time.time()-started)
            usage.update(provider='deepseek',operation='solution_only',model='deepseek-flash',seconds=round(usage.get('wall_seconds',0),3),application_requests=usage.get('request_count',0),model_calls=usage.get('request_count',0),model_calls_observability='direct_http')
            (taskdir/'usage.json').write_text(json.dumps(usage,ensure_ascii=False))
        meta.update(usage)
        (taskdir/'final.json').write_text(raw)
        return raw,meta
