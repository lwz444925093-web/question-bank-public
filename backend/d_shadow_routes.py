from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path
from . import d_shadow
router=APIRouter()
@router.get('/api/d-shadow')
def list_runs():
    import json
    return [{k:v for k,v in json.loads(p.read_text()).items() if k not in ['questions','assets','source','metrics']} for p in sorted(d_shadow.SHADOW_ROOT.glob('*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)]
@router.get('/api/d-shadow/{run_id}')
def result(run_id:str):return d_shadow.get(run_id)
@router.post('/api/d-shadow/{run_id}/cancel')
def cancel(run_id:str):return d_shadow.cancel(run_id)
@router.post('/api/d-shadow/{run_id}/questions/{qid}/review')
def review(run_id:str,qid:str,data:dict):return d_shadow.annotate(run_id,qid,data)
@router.get('/api/d-shadow/{run_id}/artifacts/{path:path}')
def artifact(run_id:str,path:str):return FileResponse(d_shadow.artifact(run_id,path))
@router.get('/d-shadow/')
def viewer():return FileResponse(Path(__file__).with_name('d_shadow.html'))
@router.get('/d-shadow/report')
def report():return FileResponse(Path(__file__).resolve().parents[1]/'reports/d-integration-20260920/REPORT.html')
