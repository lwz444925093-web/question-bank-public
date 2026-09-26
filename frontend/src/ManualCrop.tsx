import React,{useState,useRef,useEffect} from 'react';
import {sourcePictureUrl} from './SourcePicture';
const cropChoicesCache=new Map<string,any>();
const cropChoicesPending=new Map<string,Promise<any>>();
async function loadChoices(q:any){
 const key=q.id+':'+q.revision;
 if(cropChoicesCache.has(key))return cropChoicesCache.get(key);
 if(cropChoicesPending.has(key))return cropChoicesPending.get(key)!;
 const request=(async()=>{
  const response=await fetch(`/api/questions/${q.id}/crop`);const data=await response.json();
  if(!response.ok)throw Error(data.detail||'图片处理失败');
  if(data.revision!==q.revision)throw Error('题目已有新版本，请刷新后打开图片');
  if(cropChoicesCache.size>=20)cropChoicesCache.delete(cropChoicesCache.keys().next().value!);
  cropChoicesCache.set(key,data);return data;
 })();
 cropChoicesPending.set(key,request);
 try{return await request}finally{cropChoicesPending.delete(key)}
}
export function ManualCrop({question:q,onSaved,dirty,embedded=false,selection}:any){
 const[open,O]=useState(embedded),[rows,F]=useState<any[]>([]),[index,I]=useState(0),[asset,A]=useState(''),[mode,M]=useState('current'),[box,B]=useState<number[]|null>(null),[boxes,BOXES]=useState<{asset:string,mode:string,box:number[],page?:number}[]>([]),[busy,U]=useState(false),[error,E]=useState('');
 const [loadedAsset,LOADED]=useState('');
 const start=useRef<number[]|null>(null),lock=useRef(false);
 const call=async(path:string,data?:any)=>{const r=await fetch(`/api/questions/${q.id}/crop`+path,data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{});const d=await r.json();if(!r.ok)throw Error(d.detail||'图片处理失败');return d};
 const run=async(fn:()=>Promise<void>)=>{if(lock.current)return;lock.current=true;U(true);E('');try{await fn()}catch(e:any){E(e.message)}finally{lock.current=false;U(false)}};
 const choose=(i:number,figures=rows)=>{const f=figures[i],m=f?.figure_status==='needs_recrop_from_source'?'source':'current';I(i);M(m);A((f?.choices.find((c:any)=>c.roles.includes(m)&&c.page===(f.old_page||q.source?.pages?.[0]))||f?.choices.find((c:any)=>c.roles.includes(m)))?.asset||'');B(null);BOXES([])};
 const load=()=>run(async()=>{const d=await loadChoices(q);F(d.figures);const i=d.figures.findIndex((f:any)=>f.figure_id===selection?.figure_id||f.asset===selection?.asset);choose(i<0?0:i,d.figures);O(true)});
 useEffect(()=>{if(embedded)void load()},[q.id,q.revision]);
 useEffect(()=>{if(!rows.length)return;const i=rows.findIndex(f=>f.figure_id===selection?.figure_id||f.asset===selection?.asset);if(i>=0)choose(i)},[rows,selection?.figure_id,selection?.asset]);
 const fig=rows[index],choices=fig?.choices.filter((c:any)=>c.roles.includes(mode))||[],chosen=choices.find((c:any)=>c.asset===asset);
 const switchMode=(m:string)=>{M(m);A((fig.choices.find((c:any)=>c.roles.includes(m)&&c.page===(fig.old_page||q.source?.pages?.[0]))||fig.choices.find((c:any)=>c.roles.includes(m)))?.asset||'');B(null);start.current=null};
 const pageIndex=choices.findIndex((c:any)=>c.asset===asset);
 const changePage=(next:string)=>{A(next);B(null);start.current=null};
 const point=(e:React.PointerEvent<HTMLDivElement>)=>{const r=e.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(1000,(e.clientX-r.left)/r.width*1000)),Math.max(0,Math.min(1000,(e.clientY-r.top)/r.height*1000))]};
 const rect=(p:number[])=>{const a=start.current!;return [Math.min(a[0],p[0]),Math.min(a[1],p[1]),Math.max(a[0],p[0]),Math.max(a[1],p[1])]};
 const save=()=>run(async()=>{const saved=await call('/save',{revision:q.revision,figure_id:fig.figure_id,crops:boxes.map(({asset,box,mode})=>({asset,box,mode}))});onSaved(saved);BOXES([]);B(null)});
 if(!open)return <button onClick={load}>处理题图</button>;
 const old=mode==='source'&&chosen?.page===fig?.old_page?fig?.old_box:null;
 return <section className="manual-crop" aria-label="人工图片处理"><div className="crop-header-row">{fig&&<><label>题图<select aria-label="选择题图" value={index} disabled={busy} onChange={e=>choose(+e.target.value)}>{rows.map((f,i)=><option key={f.figure_id} value={i}>{f.position.startsWith('options/')?'选项 '+String.fromCharCode(65+Number(f.position.split('/')[1])):f.position.startsWith('subquestions/')?'小问图片':'题干图片'}{rows.filter(x=>x.position.split('/')[0]===f.position.split('/')[0]).length>1&&!f.position.startsWith('options/')?' '+(i+1):''}</option>)}</select></label><label className="crop-source-toggle"><input type="checkbox" role="switch" aria-label="原文" checked={mode==='source'} disabled={busy||!fig.source_available||fig.figure_status==='needs_recrop_from_source'} onChange={e=>switchMode(e.target.checked?'source':'current')}/><span className="crop-switch-track" aria-hidden="true"/>原文</label>{mode==='source'&&choices.length>1&&<button type="button" aria-label="原文上一页" disabled={busy||pageIndex<=0} onClick={()=>changePage(choices[pageIndex-1].asset)}>←</button>}{choices.length>1&&<label>来源<select aria-label="来源页面" value={asset} disabled={busy} onChange={e=>changePage(e.target.value)}>{choices.map((c:any)=><option key={c.asset} value={c.asset}>{c.label}</option>)}</select></label>}{mode==='source'&&choices.length>1&&<button type="button" aria-label="原文下一页" disabled={busy||pageIndex<0||pageIndex>=choices.length-1} onClick={()=>changePage(choices[pageIndex+1].asset)}>→</button>}</>}<button className="primary" disabled={busy||!boxes.length||dirty} onClick={save}>{busy?'正在保存…':'保存'+(boxes.length?' '+boxes.length+' 张图片':'')}</button></div>
 {boxes.length>0&&<p className="editor-hint">已框选 {boxes.length} 张{boxes.some(c=>c.page)?' · 来源页码：'+boxes.map(c=>c.page||'当前图').join('、'):''}，切页后保留，保存时按框选顺序生成。</p>}
 {!fig?<p>{busy?"正在打开图片…":"没有可处理的题图。"}</p>:<>
 {mode==='source'&&<details><summary>查看当前错误裁图</summary><img style={{maxWidth:240,maxHeight:200,objectFit:'contain'}} src={sourcePictureUrl(q.source.id,fig.asset)} alt="当前错误裁图参考"/></details>}
 {asset?<div className="crop-stage" onPointerDown={e=>{if(busy||loadedAsset!==asset||e.button!==0)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);start.current=point(e);B(null)}} onPointerMove={e=>{if(start.current)B(rect(point(e)))}} onPointerUp={e=>{if(start.current){const next=rect(point(e));if(next[2]-next[0]>1&&next[3]-next[1]>1)BOXES(old=>[...old,{asset,mode,box:next,page:chosen?.page}]);B(null);start.current=null}}} onPointerCancel={()=>{start.current=null}}><img draggable={false} key={asset} onLoad={()=>LOADED(asset)} onError={()=>E('原文图片加载失败，请切换页面后重试')} src={chosen?.url||sourcePictureUrl(q.source.id,asset)} alt={mode==='source'?'原文页面，请拖框重新截取':'当前题图，请拖框裁剪'}/>{old&&<div className="crop-selection old-bbox" style={{left:old[0]/10+'%',top:old[1]/10+'%',width:(old[2]-old[0])/10+'%',height:(old[3]-old[1])/10+'%',borderStyle:'dashed',borderColor:'#c07a30',background:'transparent'}}><span>旧范围</span></div>}{boxes.map((crop,i)=>crop.asset===asset&&crop.mode===mode&&<div className="crop-selection" key={i} style={{left:crop.box[0]/10+'%',top:crop.box[1]/10+'%',width:(crop.box[2]-crop.box[0])/10+'%',height:(crop.box[3]-crop.box[1])/10+'%'}}><span>{i+1}</span><button type="button" className="crop-remove-box" aria-label={'删除框选 '+(i+1)} onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();BOXES(old=>old.filter((_,j)=>j!==i))}}>×</button></div>)}{box&&<div className="crop-selection" style={{left:box[0]/10+'%',top:box[1]/10+'%',width:(box[2]-box[0])/10+'%',height:(box[3]-box[1])/10+'%'}}/>}</div>:<p role="alert">没有可恢复的来源图片，请补充原始材料。</p>}
 </>}
 {dirty&&<p className="warning">请先保存正文修改，再处理图片。</p>}{error&&<p role="alert" className="warning">{error}</p>}</section>;
}
