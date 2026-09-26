"""Explicit opt-in staging entry point, with the existing editing/revision UI."""
from .d_delivery import assert_staging
assert_staging()  # Must precede app import (and all initialization writes).
from .app import app
from . import store
from .d_delivery_runner import submit
from fastapi import UploadFile,File,Form,HTTPException
from fastapi.responses import JSONResponse
import json
# Replace only staging upload/retry routes; old app/process remains untouched.
app.router.routes[:]=[r for r in app.router.routes if not (getattr(r,'path','')=='/api/import' and 'POST' in getattr(r,'methods',set()))]
@app.post('/api/import')
async def upload(file:UploadFile=File(...),subject:str=Form('数学'),start:int=Form(1),end:int=Form(0),method:str=Form('D')):
 if method!='D':raise ValueError('此隔离服务只运行 D；A 对照在全部 D 测试结束后离线进行')
 return submit(await file.read(),file.filename or 'source.pdf',subject,start,end)
@app.get('/api/d-delivery/{tid}')
def result(tid:str):
 if len(tid)!=32 or any(c not in '0123456789abcdef' for c in tid):raise HTTPException(404)
 path=store.DATA/'tasks'/tid/'delivery/result.json'
 if not path.is_file():raise HTTPException(404)
 return json.loads(path.read_text())
@app.middleware('http')
async def staging_scope(request,call_next):
 if request.method not in ['GET','HEAD','OPTIONS']:
  path=request.url.path
  if path.startswith('/api/materials/') or path.startswith('/api/figures/') or path=='/api/text' or path.endswith('/retry'):
   return JSONResponse({'detail':'本轮 staging 禁止旧导入/视觉重处理及整页重试'},status_code=403)
 return await call_next(request)
# Static / mount must remain last so the added API routes resolve.
app.router.routes.sort(key=lambda r:getattr(r,'path',None)=='')
