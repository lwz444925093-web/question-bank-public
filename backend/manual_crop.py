"""User-directed, local-only crop previews. No model calls or automatic retries."""
import copy,hashlib,json,math,re,uuid,io
from PIL import Image
from . import store
from .figure_state import image_slots,block_at

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def context(qid,revision=None):
 q=store.get('questions',qid)
 if not q:raise ValueError('题目不存在')
 if revision is not None and q['revision']!=revision:raise ValueError('题目已有新版本，请重新打开裁切工具')
 sid=q.get('source',{}).get('id','')
 if not re.fullmatch('[a-f0-9]{64}',sid):raise ValueError('题目缺少有效来源')
 return q,store.DATA/'sources'/sid

def figure_record(q,slot):
 records=q.get('figure_records',[])
 exact=next((r for r in records if r.get('figure_id')==slot['figure_id'] or (r.get('asset')==slot['asset'] and r.get('position')==slot['position'])),None)
 if exact is not None:return exact
 matches=[r for r in records if r.get('asset')==slot['asset']]
 return matches[0] if len(matches)==1 else {}

def choices(qid):
 q,folder=context(qid);result=[]
 pdf_pages=[]
 if (folder/'original.pdf').is_file():
  import fitz
  with fitz.open(folder/'original.pdf') as doc:pdf_pages=list(range(1,len(doc)+1))
 slots=image_slots(q)
 if not slots or q.get('missing_required_figure'):
  asset=next((f'page-{p}.png' for p in q.get('pages',[]) if (folder/f'page-{p}.png').is_file()),None)
  if not asset:asset=next((name for name in ['image.png','original.png','original.jpg']+[v['asset'] for v in image_slots(q.get('source_snapshot',{}))] if (folder/name).is_file()),None)
  if asset:slots=slots+[dict(figure_id='new-stem-image',position='stem/'+str(len(q.get('stem',[]))),asset=asset,adding=True)]
 for slot in slots:
  record=figure_record(q,slot);assets=[]
  def add(asset,label,role,page=None):
   if not asset or not re.fullmatch(r'[^./\\][^/\\]*\.(png|jpg|jpeg|webp|svg)',asset,re.I) or not (folder/asset).is_file():return
   old=next((a for a in assets if a['asset']==asset),None)
   if old:
    if role not in old['roles']:old['roles'].append(role)
    if page:old['page']=page
   else:assets.append(dict(asset=asset,label=label,roles=[role],page=page))
  add(slot['asset'],'当前保存图片','current',record.get('page'))
  if record.get('redrawn') and q.get('figure_workflow_version')!=2:add(record.get('original_asset'),'原始裁图','source',record.get('page'))
  if q.get('figure_workflow_version')!=2:add(record.get('crop_source'),'裁剪来源','source',record.get('page'))
  pages=q.get('pages',[]) or q.get('source',{}).get('pages',[])
  if (folder/'original.pdf').is_file():
   from .vision_inputs import region_asset_name
   for page in pdf_pages:
    asset=region_asset_name(page,[0,0,1000,1000],'page_context',288)
    assets.append(dict(asset=asset,label=f'原文第 {page} 页',roles=['source'],page=page,url=f'/api/questions/{qid}/crop/source/{page}'))
  else:
   for page in pages:add(f'page-{page}.png',f'原文第 {page} 页','source',page)
   for name in ['original.png','original.jpg','original.jpeg','image.png']:add(name,'原始上传图片','source',1)
   # DOCX embedded images remain traceable through the initial source snapshot.
   for v in image_slots(q.get('source_snapshot',{})):add(v['asset'],'原始文档图片','source',record.get('page'))
   for e in q.get('source_evidence',[]):add(e.get('asset'),'来源图片','source',e.get('page'))
  result.append(dict(slot,figure_status='needs_recrop_from_source' if slot.get('adding') else record.get('figure_status','needs_manual_crop'),figure_issue=record.get('figure_issue'),choices=assets,old_box=record.get('source_box',None if record.get('manual_crop') else record.get('box')),old_page=record.get('page'),source_regions=q.get('source_regions',[]),original_asset=record.get('original_asset'),source_available=any('source' in a['roles'] for a in assets)))
 history=q.get('manual_crop_history',[])
 can_undo=bool(history and history[-1].get('revision')==q['revision']-1 and not history[-1].get('undo'))
 return dict(revision=q['revision'],figures=result,can_undo=can_undo)

def source_page(qid,page):
 q,folder=context(qid)
 from .vision_inputs import render_region
 if not (folder/'original.pdf').is_file():raise ValueError('没有可翻页的原始 PDF')
 import fitz
 with fitz.open(folder/'original.pdf') as doc:
  if not 1<=page<=len(doc):raise ValueError('原文页码超出范围')
 return render_region(folder,page,[0,0,1000,1000],'page_context',dpi=288)['path']


def preview(qid,data):
 q,folder=context(qid,data.get('revision'))
 if data.get('revision') is None:raise ValueError('缺少基线版本')
 slot=next((s for s in choices(qid)['figures'] if s['figure_id']==data.get('figure_id')),None)
 if not slot or data.get('asset') not in [a['asset'] for a in slot['choices']]:raise ValueError('图片不属于指定题图或来源')
 selected=next(a for a in slot['choices'] if a['asset']==data['asset'])
 mode=data.get('mode','source' if 'source' in selected['roles'] and ('current' not in selected['roles'] or slot['figure_status']=='needs_recrop_from_source') else 'current')
 if mode not in ['current','source'] or mode not in selected['roles']:raise ValueError('裁剪来源与操作不符')
 if slot['figure_status']=='needs_recrop_from_source' and mode!='source':raise ValueError('图片已截断，必须从原文重新截取')
 box=data.get('box')
 if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):raise ValueError('裁切坐标无效')
 x1,y1,x2,y2=box
 if not (0<=x1<x2<=1000 and 0<=y1<y2<=1000):raise ValueError('裁切范围须位于图片内且宽高大于零')
 if selected.get('url'):
  source_page(qid,selected['page'])
 path=folder/data['asset'];token=uuid.uuid4().hex;asset='manual-crop-'+token+'.png'
 from .export_images import image_data
 raw,_,_=image_data(q['source'],data['asset'])
 with Image.open(io.BytesIO(raw)) as im:
  w,h=im.size;pixels=(math.floor(x1*w/1000),math.floor(y1*h/1000),math.ceil(x2*w/1000),math.ceil(y2*h/1000))
  if pixels[2]-pixels[0]<8 or pixels[3]-pixels[1]<8:raise ValueError('裁切区域过小')
  im.crop(pixels).convert('RGB').save(folder/asset)
 record=figure_record(q,slot)
 source_box=box if mode=='source' else None
 if mode=='current':
  parent_box=record.get('source_box',None if record.get('manual_crop') else record.get('box'))
  if parent_box:
   px,py,ex,ey=parent_box;source_box=[px+box[0]*(ex-px)/1000,py+box[1]*(ey-py)/1000,px+box[2]*(ex-px)/1000,py+box[3]*(ey-py)/1000]
 meta=dict(source_box=source_box,id=token,question_id=qid,revision=q['revision'],figure_id=slot['figure_id'],position=slot['position'],old_asset=slot['asset'],old_hash=digest(folder/slot['asset']),source_asset=data['asset'],source_hash=digest(path),box=box,dimensions=[w,h],asset=asset,content_hash=digest(folder/asset),mode=mode,page=selected.get('page'),source_id=q['source']['id'],source_file=q['source'].get('file',''),baseline_revision=q['revision'])
 target=store.DATA/'crop_previews';target.mkdir(exist_ok=True)
 (target/(token+'.json')).write_text(json.dumps(meta,ensure_ascii=False))
 return meta

def apply(qid,data):
 token=data.get('preview_id','')
 if not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('裁切预览无效')
 file=store.DATA/'crop_previews'/(token+'.json')
 if not file.is_file():raise ValueError('请先生成裁切预览')
 meta=json.loads(file.read_text())
 if meta['question_id']!=qid or data.get('revision')!=meta['revision']:raise ValueError('预览与题目版本不符')
 q,folder=context(qid,meta['revision']);q=copy.deepcopy(q)
 slots=image_slots(q)
 adding=meta['figure_id']=='new-stem-image' and meta['position']=='stem/'+str(len(q['stem']))
 if not adding and not any(s['figure_id']==meta['figure_id'] and s['position']==meta['position'] and s['asset']==meta['old_asset'] for s in slots):raise ValueError('题图对应关系已变化，请重新预览')
 for asset,key in [(meta['old_asset'],'old_hash'),(meta['source_asset'],'source_hash'),(meta['asset'],'content_hash')]:
  if not (folder/asset).is_file() or digest(folder/asset)!=meta[key]:raise ValueError('图片内容已变化，请重新预览')
 if adding:q['stem'].append(dict(kind='image',asset=meta['asset'],spans=[],latex='',rows=[],shapes=[]))
 else:block_at(q,meta['position'])['asset']=meta['asset']
 old=figure_record(q,dict(figure_id=meta['figure_id'],position=meta['position'],asset=meta['old_asset']))
 record=dict(figure_id=meta['figure_id'],position=meta['position'],asset=meta['asset'],original_asset=meta['asset'],preview_asset=meta['asset'],content_hash=meta['content_hash'],original_hash=meta['content_hash'],state='unverified',original_status='unverified',svg_status='absent',redrawn=False,note='人工裁剪已确认',figure_status='ready',figure_issue=None,previous_asset=meta['old_asset'],baseline_revision=q['revision'],crop_source=meta['source_asset'],box=meta['box'],source_box=meta.get('source_box'),dimensions=meta['dimensions'],page=meta.get('page'),manual_crop=True,manual_operation=meta.get('mode'),source_id=meta['source_id'],source_file=meta['source_file'])
 if old.get('redrawn') and meta['source_asset']==meta['old_asset']:
  record.update(redrawn=True,original_asset=old.get('original_asset'),original_hash=old.get('original_hash'),original_status=old.get('original_status','unverified'))
 q['figure_records']=[r for r in q.get('figure_records',[]) if r is not old]+[record]
 q['missing_required_figure']=False
 q.setdefault('manual_crop_history',[]).append(dict(meta,previous_record=copy.deepcopy(old),previous_issues=copy.deepcopy(q.get('issues',[]))))
 if old.get('note'):q['issues']=[s for s in q.get('issues',[]) if s!=old['note']]
 from .review_policy import accept_manual_crops
 accept_manual_crops(q)
 return store.save_question(q,meta['revision'],image_only=True)


def save_batch(qid,data):
 """Replace one logical image with N crops in a single optimistic transaction."""
 revision=data.get('revision')
 if revision is None:raise ValueError('缺少基线版本')
 original,folder=context(qid,revision)
 slot=next((s for s in choices(qid)['figures'] if s['figure_id']==data.get('figure_id')),None)
 if not slot:raise ValueError('题图对应关系已变化，请重新打开编辑区')
 crops=data.get('crops')
 if not isinstance(crops,list) or len(crops)>30 or any(not isinstance(c,dict) for c in crops):raise ValueError('一次最多保存 30 张裁图')
 if not crops and (data.get('delete') is not True or slot.get('adding')):raise ValueError('请先框选图片，或明确选择删除此图')
 # Render every crop before changing any question data. Any failure leaves the version untouched.
 metas=[preview(qid,dict(revision=revision,figure_id=slot['figure_id'],asset=c.get('asset'),box=c.get('box'),**({'mode':c['mode']} if 'mode' in c else {}))) for c in crops]
 q=copy.deepcopy(original)
 old_slots=image_slots(q)
 bindings=[(block_at(q,s['position']),dict(figure_record(q,s),figure_id=s['figure_id'],position=s['position'],asset=s['asset'])) for s in old_slots]
 old=figure_record(q,slot)
 parent_path,index=slot['position'].rsplit('/',1);parent=block_at(q,parent_path);index=int(index)
 template=dict(spans=[],latex='',rows=[],shapes=[]) if slot.get('adding') else parent[index]
 replaced=[];batch=uuid.uuid4().hex
 for i,meta in enumerate(metas):
  for asset,key in [(meta['old_asset'],'old_hash'),(meta['source_asset'],'source_hash'),(meta['asset'],'content_hash')]:
   if not (folder/asset).is_file() or digest(folder/asset)!=meta[key]:raise ValueError('图片内容已变化，请重新框选')
  block=dict(template,kind='image',asset=meta['asset'])
  record=dict(figure_id=slot['figure_id'] if i==0 and not slot.get('adding') else uuid.uuid4().hex[:20],asset=meta['asset'],original_asset=meta['asset'],preview_asset=meta['asset'],content_hash=meta['content_hash'],original_hash=meta['content_hash'],state='verified',original_status='accepted',svg_status='absent',redrawn=False,note='人工裁切已采用',baseline_revision=revision,crop_source=meta['source_asset'],box=meta['box'],dimensions=meta['dimensions'],page=meta.get('page'),manual_crop=True,crop_batch=batch,figure_status='ready',figure_issue=None,source_box=meta.get('source_box'),manual_operation=meta.get('mode'),source_id=meta['source_id'],source_file=meta['source_file'])
  # A split redraw has no reliable per-crop mapping to its old full original.
  # Keep source provenance, but never pair an individual crop with the entire old diagram.
  if len(metas)==1 and old.get('redrawn') and meta['source_asset']==meta['old_asset']:
   record.update(redrawn=True,original_asset=old.get('original_asset'),original_hash=old.get('original_hash'),original_status=old.get('original_status','unverified'))
  replaced.append(block);bindings.append((block,record))
 parent[index:index+(0 if slot.get('adding') else 1)]=replaced
 if slot.get('adding') and replaced:q['missing_required_figure']=False
 # Reindex by block identity, not filename: repeated images and shifted siblings stay distinct.
 positions={id(block_at(q,s['position'])):s['position'] for s in image_slots(q)}
 q['figure_records']=[dict(r,position=positions[id(b)]) for b,r in bindings if id(b) in positions]
 q.setdefault('manual_crop_history',[]).append(dict(id=batch,revision=revision,figure_id=slot['figure_id'],source_asset=slot['asset'],crops=metas,deleted=not crops,previous_record=copy.deepcopy(old),previous_issues=copy.deepcopy(q.get('issues',[]))))
 if old.get('note'):q['issues']=[s for s in q.get('issues',[]) if s!=old['note']]
 from .review_policy import accept_manual_crops
 accept_manual_crops(q)
 return store.save_question(q,revision,image_only=True)

def undo(qid,data):
 q,_=context(qid,data.get('revision'))
 history=q.get('manual_crop_history',[])
 if data.get('revision') is None or not history or history[-1].get('revision')!=q['revision']-1 or history[-1].get('undo'):
  raise ValueError('仅可撤销最近一次裁剪；后续修改不会被覆盖')
 baseline=history[-1]['revision']
 with store.conn() as c:
  row=c.execute('SELECT body FROM revisions WHERE id=? AND revision=?',(qid,baseline)).fetchone()
 if not row:raise ValueError('裁剪前版本不存在')
 previous=json.loads(row[0]);q=copy.deepcopy(q)
 for key in ['stem','options','subquestions','figure_records','figure_status','missing_required_figure']:
  if key in previous:q[key]=previous[key]
  else:q.pop(key,None)
 q['manual_crop_history'].append(dict(undo=True,revision=q['revision'],restored_revision=baseline))
 return store.save_question(q,q['revision'],image_only=True)
