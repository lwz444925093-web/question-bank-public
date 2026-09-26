import {materialProgress} from './materialProgress';
import {RemainingImport,ImportMaterial} from './RemainingImport';
import {ImportPreview} from './ImportPreview';
import React,{useEffect,useState,useRef} from 'react';
import {catalogKey,cachedCatalog,loadCatalog} from './materialCatalogCache';
function pageRange(pages:number[]=[]){
 if(!pages.length)return '无';const parts:string[]=[];let start=pages[0],end=start;
 for(const p of pages.slice(1)){if(p===end+1){end=p;continue}parts.push(start===end?String(start):`${start}–${end}`);start=end=p}
 parts.push(start===end?String(start):`${start}–${end}`);return parts.join('、');
}
const statuses:any={parsed_empty:'已解析 · 无题目',not_imported:'未导入',has_questions:'已有题目入库',history_only:'有提交记录 · 暂无题目',incomplete:'最近处理未完成',processing:'处理中'};
const taskStatuses:any={queued:'排队',running:'处理中',succeeded:'本次处理结束',partial:'部分未完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'};
function fileTooltip(f:any){
 const total=f.question_count||0,pending=f.pending_count||0;
 const count=total?`当前已入库 ${total} 题（${Math.max(0,total-pending)} 题通过，${pending} 题待审核）`:(f.tasks?.length?'当前已入库 0 题 · 有上传记录':'尚未导入题目');
 const dateLabel=f.added_at_basis==='date_added'?'加入文件夹':f.added_at_basis==='created'?'创建时间（未提供加入时间）':'文件时间（未提供加入时间）';
 return [f.path,count,f.added_at?dateLabel+'：'+new Date(f.added_at*1000).toLocaleString('zh-CN',{hour12:false}):''].filter(Boolean).join('\n');
}
export function MaterialFiles({subject,onSubmitted,lightReview,onLightReview,uploadPanel,renderHistory,stagedFile,currentPanel}: {currentPanel:React.ReactNode,stagedFile:File|null,uploadPanel:React.ReactNode,renderHistory:(file:any)=>React.ReactNode,subject:string,onSubmitted:()=>Promise<void>,lightReview:boolean,onLightReview:(v:boolean)=>void}){
 const [opened,OPEN]=useState<{name:string,file:File|null,error:string,previewUrl?:string}|null>(null);const opening=useRef<AbortController|null>(null);
 useEffect(()=>()=>opening.current?.abort(),[]);
 function closePreview(){opening.current?.abort();OPEN(null)}
 async function openFile(f:any){
  opening.current?.abort();const controller=new AbortController();opening.current=controller;OPEN({name:f.name,file:null,error:''});
  try{const response=await fetch('/api/materials/file?path='+encodeURIComponent(f.path),{signal:controller.signal});if(!response.ok)throw Error('文件读取失败');const blob=await response.blob();if(controller.signal.aborted)return;OPEN({name:f.name,file:new File([blob],f.name,{type:/\.pdf$/i.test(f.name)?'application/pdf':blob.type}),error:''})}catch(e:any){if(!controller.signal.aborted)OPEN({name:f.name,file:null,error:e.message})}
 }
 const[directory,D]=useState<string|null>(null),[recursive,R]=useState(true),[data,DATA]=useState<any>(()=>cachedCatalog(catalogKey(subject))?.data||null),[error,E]=useState(''),[loading,L]=useState(false),[tick,T]=useState(0),[query,Q]=useState(''),[filter,F]=useState('all'),[selected,SELECT]=useState<string|null>(null),[uploadFocus,UF]=useState(false);
 useEffect(()=>{if(stagedFile)UF(true)},[stagedFile]);
 useEffect(()=>{D(null);DATA(cachedCatalog(catalogKey(subject))?.data||null);Q('');F('all');SELECT(null)},[subject]);
 useEffect(()=>{const changed=()=>T(v=>v+1);window.addEventListener('bank-data-changed',changed);return()=>window.removeEventListener('bank-data-changed',changed)},[]);
 useEffect(()=>{
  let active=true;const cached=cachedCatalog(catalogKey(subject,directory,recursive));DATA(cached?.data||null);L(true);E('');
  loadCatalog(subject,directory,recursive,tick>0).then(entry=>{if(active){DATA(entry.data);E(entry.data.error||'')}}).catch(e=>{if(active)E(e.message)}).finally(()=>{if(active)L(false)});
  return()=>{active=false};
 },[subject,directory,recursive,tick]);

 const all=data?.files||[],rows=all.filter((f:any)=>(f.name+' '+f.folder).toLowerCase().includes(query.toLowerCase())&&(filter==='all'||filter===materialProgress(f).key||filter==='imported'&&f.question_count>0||filter==='none'&&f.status==='not_imported'||filter==='attention'&&(f.status==='incomplete'||f.pending_count>0||f.file_error)||filter==='running'&&f.status==='processing'));
 const file=uploadFocus?null:rows.find((f:any)=>f.path===selected)||rows[0]||null;
 const submitted=async()=>{T(v=>v+1);await onSubmitted()};
 return <div className="material-workspace">
 {opened&&<div className="modal-backdrop material-preview-backdrop" onClick={e=>{if(e.target===e.currentTarget)closePreview()}}><section className="material-preview-dialog" role="dialog" aria-modal="true" aria-label="原文件预览" onKeyDown={e=>{if(e.key==='Escape')closePreview()}}><div className="preview-heading"><h2>原文件预览</h2><button autoFocus onClick={closePreview}>关闭预览</button></div>{opened.error?<p role="alert">{opened.error}</p>:opened.previewUrl?<div className="import-file-preview"><h2>{opened.name}</h2><iframe title="Word 文件预览" src={opened.previewUrl}/></div>:opened.file?<ImportPreview file={opened.file}/>:<p role="status">正在打开 {opened.name}…</p>}</section></div>}
 <aside className="material-file-panel" aria-label="文件列表">
 <h2>文件列表 <small>{rows.length}</small></h2>
 <div className="catalog-controls"><label>目录<select aria-label="材料目录" value={directory??data?.directory??''} onChange={e=>D(e.target.value)}>{(data?.directories||['']).map((d:string)=><option key={d} value={d}>{d||data?.root_name||'导入材料'}</option>)}</select></label><label><input type="checkbox" checked={recursive} onChange={e=>R(e.target.checked)}/>包含子目录</label><button disabled={loading} onClick={()=>T(v=>v+1)}>{loading?'读取中…':'刷新'}</button></div>
 <input aria-label="搜索材料文件" placeholder="搜索文件" value={query} onChange={e=>Q(e.target.value)}/>
 {error&&<p role="alert" className="warning">{error}</p>}
 <div className="material-file-list">{rows.map((f:any)=><button key={f.path} draggable onDragStart={e=>{e.dataTransfer.effectAllowed='copy';e.dataTransfer.setData('application/x-question-material',JSON.stringify({path:f.path,name:f.name}))}} onClick={()=>void openFile(f)} title={fileTooltip(f)}>{f.name}</button>)}{!rows.length&&<p>{loading?'正在读取文件…':'没有匹配的文件'}</p>}</div>
 </aside>
 <section className="material-current-panel" aria-label="当前状态">
 <div className="material-panel-heading"><h2>当前状态</h2></div>
 {uploadPanel}
 {currentPanel}
 </section>
 <aside className="material-history-panel" aria-label="历史记录">{renderHistory(file)}</aside>
 </div>;
}
