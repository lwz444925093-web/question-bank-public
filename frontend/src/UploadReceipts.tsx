import React,{useEffect,useState} from 'react';
const key='bank-upload-receipts-v1';
const live=new Set<string>();
function read(){try{return JSON.parse(localStorage.getItem(key)||'[]') as any[]}catch{return []}}
export function uploadReceipt(name:string){const id=crypto.randomUUID();live.add(id);updateReceipt(id,{name,created:Date.now(),state:'sending'});return id}
export function updateReceipt(id:string,changes:any){if(changes.state&&changes.state!=='sending')live.delete(id);const rows=read();const old=rows.find(r=>r.id===id)||{id};const next=[{...old,...changes},...rows.filter(r=>r.id!==id)].slice(0,200);try{localStorage.setItem(key,JSON.stringify(next))}catch{}window.dispatchEvent(new Event('upload-receipts-changed'))}
export function UploadReceipts({tasks}:{tasks:any[]}){
 const [rows,SET]=useState(read);
 useEffect(()=>{const change=()=>SET(read());window.addEventListener('upload-receipts-changed',change);window.addEventListener('storage',change);return()=>{window.removeEventListener('upload-receipts-changed',change);window.removeEventListener('storage',change)}},[]);
 return <>{rows.filter(r=>!r.taskId||!tasks.some(t=>t.id===r.taskId)).map(r=><article className="history-record" key={r.id}><div className="history-line history-line-title"><h3 title={r.name}>{r.name}</h3><time>{new Date(r.created).toLocaleString('zh-CN',{hour12:false})}</time></div><div className="history-line history-line-details"><small>耗时 {r.finished?Math.max(0,Math.round((r.finished-r.created)/1000))+' 秒':'—'}</small><small>花费：未记录</small><span className={'task-row-status '+(r.state==='failed'?'failed':'queued')} title={r.error||''}>{r.state==='failed'?'提交失败：'+r.error:r.state==='submitted'?'已提交，等待同步':live.has(r.id)?'正在上传':'提交结果待确认'}</span></div></article>)}</>;
}
