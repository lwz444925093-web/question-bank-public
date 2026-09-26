"""Render an immutable exported DOCX into cached, individually served pages."""
import json, subprocess, threading, shutil
from pathlib import Path
from . import store
_lock = threading.Lock()

def render(id):
    if len(id)!=32 or any(c not in '0123456789abcdef' for c in id) or not store.get('exports',id):
        raise ValueError('导出文件不存在')
    folder=store.DATA/'exports'/(id+'-preview')
    manifest=folder/'manifest.json'
    with _lock:
        if manifest.exists(): return json.loads(manifest.read_text())
        folder.mkdir(exist_ok=True)
        try:
            subprocess.run(['sh',str(store.ROOT/'scripts/render.sh'),str(store.DATA/'exports'/(id+'.docx')),str(folder)],capture_output=True,timeout=180,check=True)
            pages=sorted(folder.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
            if not pages: raise ValueError('没有生成预览页面')
            result={'id':id,'url':'/api/export/'+id,'pages':['/api/export/'+id+'/preview/'+str(i+1) for i in range(len(pages))]}
            manifest.write_text(json.dumps(result))
            return result
        except Exception as e:
            shutil.rmtree(folder,ignore_errors=True)
            raise ValueError('分页预览生成失败，请重试。'+str(e)[:200])
