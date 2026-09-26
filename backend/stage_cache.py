"""Only callers that have validated business output may commit a cache entry."""
import hashlib,json
from pathlib import Path
from . import store
from .contracts import VERSION
VERSION_KEY='stage-v1'
def key(bundle,cfg,schema,instruction):
 value={k:v for k,v in bundle.items() if not k.startswith('_') and k not in ['images','display_name','session_title']}
 images=[]
 for name in bundle.get('images',[]):
  p=Path(name)
  if not p.is_file():return None
  images.append(hashlib.sha256(p.read_bytes()).hexdigest())
 model={k:cfg.get(k) for k in ['provider','model','reasoning']}
 return hashlib.sha256(json.dumps([VERSION_KEY,VERSION,value,images,model,schema,instruction],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def get(bundle,cfg,schema,instruction):
 cache_key=key(bundle,cfg,schema,instruction)
 return store.get('cache','stage-'+cache_key) if cache_key else None
def put(bundle,cfg,schema,instruction,text,meta):
 cache_key=key(bundle,cfg,schema,instruction)
 if cache_key:store.put('cache','stage-'+cache_key,dict(text=text,meta=meta))
