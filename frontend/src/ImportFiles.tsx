import {uploadReceipt,updateReceipt} from './UploadReceipts';
import React,{useEffect,useRef,useState} from 'react';
import {collectDropFiles} from './dropFiles';
import type {LightReviewSettingState} from './LightReview';

export function ImportFiles({onDone,subject,onPreview,lightReview,reviewSetting}:{lightReview:boolean,reviewSetting?:LightReviewSettingState,onDone:()=>Promise<void>,subject:string,onPreview:(file:File|null)=>void}){
 const [generateSolution,GS]=useState(false),[review,REVIEW]=useState(lightReview),[settings,SETTINGS]=useState(false);
 const [files,F]=useState<File[]>([]),[busy,B]=useState(false),[drag,D]=useState(false),[logs,L]=useState<string[]>([]);
 const [pageMode,PAGES]=useState('all'),[start,S]=useState(1),[end,E]=useState('');
 const host=useRef<HTMLDivElement>(null),picker=useRef<HTMLInputElement>(null),settingsHeading=useRef<HTMLHeadingElement>(null),uploadButton=useRef<HTMLButtonElement>(null);
 const lock=useRef(false),fileQueue=useRef<File[]>([]);fileQueue.current=files;
 const hasPdf=files.some(f=>/\.pdf$/i.test(f.name)),hasReviewOptions=files.some(f=>/\.(pdf|docx|png|jpe?g)$/i.test(f.name)),lastPage=end===''?0:Number(end);
 const validPages=pageMode==='all'||(Number.isInteger(start)&&start>=1&&(end===''||(Number.isInteger(lastPage)&&lastPage>=start)));
 const settingsAvailable=!hasReviewOptions||(!reviewSetting?.loading&&!reviewSetting?.error);
 useEffect(()=>{const prevent=(e:DragEvent)=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files'))e.preventDefault()};window.addEventListener('dragover',prevent);window.addEventListener('drop',prevent);return()=>{window.removeEventListener('dragover',prevent);window.removeEventListener('drop',prevent)}},[]);
 useEffect(()=>REVIEW(lightReview),[lightReview]);
 useEffect(()=>{if(settings){settingsHeading.current?.focus({preventScroll:true});settingsHeading.current?.scrollIntoView({block:'nearest'})}},[settings]);
 function closeSettings(){SETTINGS(false);requestAnimationFrame(()=>uploadButton.current?.focus({preventScroll:true}))}
 function add(list:File[]){
  const errors:string[]=[],next=[...fileQueue.current];
  for(const f of list){
   if(!/\.(txt|pdf|png|jpe?g|docx)$/i.test(f.name)){errors.push(f.name+(/\.doc$/i.test(f.name)?'：请先在 Word 中另存为 DOCX。':'：暂不支持此格式。'));continue}
   if(next.some(x=>x.name===f.name&&x.size===f.size&&x.lastModified===f.lastModified))continue;
   if(next.length>=200){errors.push('每次最多 200 个文件，请分批上传。');break}
   next.push(f);
  }
  fileQueue.current=next;F(next);if(next.length)onPreview(next[next.length-1]);
  L(errors.length?errors:list.length?[]:['未读取到文件，请点击“选择文件”重试。']);
 }
 useEffect(()=>{
  const page=host.current?.closest('.material-current-panel');if(!page)return;let depth=0;
  const isFiles=(e:DragEvent)=>Array.from(e.dataTransfer?.types||[]).some(t=>t==='Files'||t==='application/x-question-material');
  const clear=()=>{depth=0;D(false);page.classList.remove('file-drag-active')};
  const enter=(event:Event)=>{const e=event as DragEvent;if(!isFiles(e))return;e.preventDefault();e.stopPropagation();depth++;if(!lock.current){D(true);page.classList.add('file-drag-active')}};
  const over=(event:Event)=>{const e=event as DragEvent;if(!isFiles(e))return;e.preventDefault();e.stopPropagation();if(e.dataTransfer)e.dataTransfer.dropEffect=lock.current?'none':'copy'};
  const leave=(event:Event)=>{const e=event as DragEvent;if(!isFiles(e))return;e.stopPropagation();if(--depth<=0)clear()};
  const drop=(event:Event)=>{
   const e=event as DragEvent;if(!isFiles(e))return;e.preventDefault();e.stopPropagation();clear();if(lock.current||!e.dataTransfer)return;
   const internal=e.dataTransfer.getData('application/x-question-material');
   const reading=internal?(async()=>{const item=JSON.parse(internal);if(typeof item.path!=='string'||typeof item.name!=='string')throw Error('文件信息无效');const response=await fetch('/api/materials/file?path='+encodeURIComponent(item.path));if(!response.ok)throw Error('读取文件失败');const blob=await response.blob();return [new File([blob],item.name,{type:/\.pdf$/i.test(item.name)?'application/pdf':blob.type,lastModified:0})]})():collectDropFiles(e.dataTransfer);
   L(['正在读取文件…']);reading.then(add).catch(err=>L(['无法读取文件：'+(err.message||'请点击“选择文件”重试。')]));
  };
  page.addEventListener('dragenter',enter,true);page.addEventListener('dragover',over,true);page.addEventListener('dragleave',leave,true);page.addEventListener('drop',drop,true);
  return()=>{page.removeEventListener('dragenter',enter,true);page.removeEventListener('dragover',over,true);page.removeEventListener('dragleave',leave,true);page.removeEventListener('drop',drop,true);page.classList.remove('file-drag-active')};
 },[onPreview]);
 async function upload(){
  if(lock.current||!files.length||(hasPdf&&!validPages)||!settingsAvailable)return;
  lock.current=true;SETTINGS(false);B(true);L([]);const failed:File[]=[],errors:string[]=[];let submitted=0;
  try{
   for(const [index,f] of files.entries()){
    const receipt=uploadReceipt(f.name);
    try{
     const data=new FormData();L([`正在上传 ${index+1}/${files.length}：${f.name}`]);data.append('file',f);data.append('subject',subject);
     if(/\.pdf$/i.test(f.name)){data.append('start',String(pageMode==='all'?1:start));data.append('end',String(pageMode==='all'?0:lastPage));}
     if(/\.(pdf|docx|png|jpe?g)$/i.test(f.name)){data.append('generate_solution',String(generateSolution));data.append('light_review',String(review));}
     const r=await fetch('/api/import',{method:'POST',body:data}),d=await r.json();
     if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||'上传失败'));
     updateReceipt(receipt,{state:'submitted',taskId:d.id||d.task_id,finished:Date.now()});submitted++;
    }catch(e:any){const message=e.message==='Failed to fetch'?'连接中断，请检查服务后重试。':e.message;updateReceipt(receipt,{state:'failed',error:message,finished:Date.now()});failed.push(f);errors.push(f.name+'：'+message)}
   }
   fileQueue.current=failed;F(failed);onPreview(failed[failed.length-1]||null);
   L([...(submitted?[`已提交 ${submitted} 个文件，可在当前状态和历史记录中查看。`]:[]),...errors]);
   await onDone();
  }catch{L(x=>[...x,'任务列表暂未更新，请点击历史记录中的“刷新”。'])}
  finally{lock.current=false;B(false)}
 }
 return <div ref={host} className="import-file-controls" aria-busy={busy}>
  {!files.length?<button type="button" className={'drop-zone compact-drop-zone'+(drag?' dragging':'')} disabled={busy} onClick={()=>picker.current?.click()}><strong>拖入文件，或点击选择文件</strong><span>也可将左侧文件拖到此栏 · 支持批量导入</span></button>:<div className="upload-queue-heading"><strong>待上传 · {files.length} 个文件</strong><button disabled={busy} onClick={()=>picker.current?.click()}>添加文件</button></div>}
  <input hidden ref={picker} type="file" multiple accept=".txt,.pdf,.png,.jpg,.jpeg,.docx" onChange={e=>{add(Array.from(e.target.files||[]));e.target.value=''}}/>
  {files.length>0&&<div className="upload-list upload-queue">{files.map((f,i)=><div key={i}><button title={f.name} onClick={()=>onPreview(f)}>{f.name}</button><button disabled={busy} aria-label={'移除 '+f.name} onClick={()=>{const next=fileQueue.current.filter((_,j)=>j!==i);fileQueue.current=next;F(next);onPreview(next[next.length-1]||null);if(!next.length){SETTINGS(false);L([])}}}>移除</button></div>)}</div>}
  {files.length>0&&!settings&&<button ref={uploadButton} className="primary" disabled={busy} onClick={()=>SETTINGS(true)}>{busy?'正在上传…':'上传（'+files.length+' 个文件）'}</button>}
  {settings&&<section className="upload-settings" aria-label="上传参数" onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();closeSettings()}}}>
   <h3 ref={settingsHeading} tabIndex={-1}>上传参数</h3><p>{files.length} 个文件 · {subject}题库</p>
   {hasPdf&&<>
    <label>PDF 页码<select aria-label="PDF 页码范围" value={pageMode} onChange={e=>PAGES(e.target.value)}><option value="all">全部页</option><option value="custom">指定页码</option></select></label>
    {pageMode==='custom'&&<><div className="upload-page-range"><label>从第<input type="number" aria-label="PDF 起页" min={1} value={start} onChange={e=>S(+e.target.value)}/>页</label><label>到第<input type="number" aria-label="PDF 末页" min={start} placeholder="最后一页" value={end} onChange={e=>E(e.target.value)}/>页</label></div>{files.filter(f=>/\.pdf$/i.test(f.name)).length>1&&<small>此页码范围应用于本次所有 PDF。</small>}</>}
    {!validPages&&<p role="alert">请填写有效页码，末页不能小于起页。</p>}
   </>}
   {hasReviewOptions&&<>
    {files.some(f=>/\.txt$/i.test(f.name))&&<small>以下两个选项适用于 PDF、Word 和图片。</small>}
    <label><input type="checkbox" checked={review} disabled={!settingsAvailable} onChange={e=>REVIEW(e.target.checked)}/>质量审查</label>
    <label><input type="checkbox" checked={generateSolution} onChange={e=>GS(e.target.checked)}/>生成答案和解析</label>
    {review&&generateSolution&&<small>先审查题目，再为审查通过的题目生成答案解析。</small>}
    {reviewSetting?.loading&&<p role="status">正在读取上传设置…</p>}
    {reviewSetting?.error&&<p role="alert">{reviewSetting.error} <button onClick={reviewSetting.retry}>重试</button></p>}
   </>}
   <div className="upload-settings-actions"><button className="primary" disabled={busy||(hasPdf&&!validPages)||!settingsAvailable} onClick={upload}>确认上传</button><button disabled={busy} onClick={closeSettings}>取消</button></div>
  </section>}
  {!files.length&&!busy&&<small className="upload-format-note">支持 PDF、DOCX、JPG、PNG 和 TXT</small>}
  {logs.length>0&&<div role="status" className="upload-list upload-messages">{logs.map((x,i)=><p key={i}>{x}</p>)}</div>}
 </div>;
}
