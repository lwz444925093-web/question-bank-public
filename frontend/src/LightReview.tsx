import React,{useEffect,useState,useRef} from 'react';
import {createPortal} from 'react-dom';
import {reviewMessages} from './reviewMessages';
import {InlineText} from './InlineText';
async function request(path:string,body?:any,method='POST'){const r=await fetch('/api/light-review'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.detail||'请求失败');return d}
export type LightReviewSettingState={loading:boolean,error:string,retry:()=>void};
export function useLightReviewSetting():[boolean,(v:boolean)=>void,LightReviewSettingState]{
 const [enabled,E]=useState(true),version=useRef(0),saved=useRef(true),pending=useRef(Promise.resolve());
 const [state,STATE]=useState({loading:true,error:''});
 const load=async()=>{STATE({loading:true,error:''});try{const d=await request('/settings');if(typeof d.enabled!=='boolean')throw Error('默认设置格式无效');saved.current=d.enabled;if(version.current===0)E(d.enabled);STATE({loading:false,error:''})}catch(e:any){STATE({loading:false,error:'无法读取上传默认设置，请重试。'})}};
 useEffect(()=>{pending.current=load()},[]);
 return [enabled,(v:boolean)=>{const change=++version.current;E(v);pending.current=pending.current.then(async()=>{try{const d=await request('/settings',{enabled:v},'PUT');saved.current=d.enabled??v}catch(e:any){if(version.current===change){E(saved.current);window.alert('设置未保存：'+e.message)}}})},{...state,retry:()=>{pending.current=pending.current.then(load)}}];
}
const labels:any={usable:'可入库',usable_with_cleanup:'可入库 · 可整理',needs_review:'需人工审核',incomplete:'内容不完整'};
export function LightReviewBatch({subject,pendingCount,onChanged,onBack,selectedIds,onResults,onQuestion}:{onQuestion?:(id:string)=>void,subject:string,pendingCount:number,selectedIds:string[],onResults:(rows:any[])=>void,onChanged:()=>Promise<void>,onBack:()=>void}){
 const actionLock=useRef(false);
 const[t,T]=useState<any>(null),[busy,B]=useState(false),[error,E]=useState(''),[confirm,C]=useState(false),[showResults,SR]=useState(false),[filter,F]=useState('all'),[message,M]=useState('');
 useEffect(()=>{let live=true;T(null);E('');C(false);SR(false);M('');request('/latest?subject='+encodeURIComponent(subject)).then(d=>{if(live)T(d)}).catch(e=>{if(live)E(e.message)});return()=>{live=false}},[subject]);
 useEffect(()=>{onResults(t?.results||[])},[t]);
 const dialog=useRef<HTMLDivElement>(null);
 const modal=confirm||showResults;
 useEffect(()=>{if(!modal)return;const prior=document.activeElement as HTMLElement;const overflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.current?.focus();const key=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy){C(false);SR(false)}if(e.key==='Tab'){const els=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],select')||[]);if(!els.length){e.preventDefault();return}const first=els[0],last=els[els.length-1];if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last.focus()}else if(!e.shiftKey&&(document.activeElement===last||document.activeElement===dialog.current)){e.preventDefault();first.focus()}}};document.addEventListener('keydown',key);return()=>{document.body.style.overflow=overflow;document.removeEventListener('keydown',key);prior?.focus()}},[modal,busy]);
 const active=t&&['running','queued'].includes(t.status);
 useEffect(()=>{
  if(!active)return;let live=true,timer:ReturnType<typeof setTimeout>;
  const update=async()=>{let again=true;try{const d=await request('/'+t.id);if(live){T(d);E('');again=['running','queued'].includes(d.status)}}catch(e:any){if(live)E(e.message)}finally{if(live&&again)timer=setTimeout(update,5000)}};
  timer=setTimeout(update,5000);return()=>{live=false;clearTimeout(timer)}
 },[t?.id,active]);
 const passed=(t?.results||[]).filter((r:any)=>r.eligible&&!t.confirmed_ids?.includes(r.id));
 const targets=selectedIds.length?passed.filter((r:any)=>selectedIds.includes(r.id)):passed;
 async function start(){if(actionLock.current)return;actionLock.current=true;B(true);E('');M('');C(false);try{T(await request('',{subject}))}catch(e:any){E(e.message)}finally{actionLock.current=false;B(false)}}
 async function apply(){if(actionLock.current)return;actionLock.current=true;B(true);E('');try{const d=await request('/'+t.id+'/confirm',{confirmed:true,question_ids:targets.map((r:any)=>r.id)});T(d.task);C(false);M(`已入库 ${d.saved_ids.length} 题${d.skipped_ids.length?'；'+d.skipped_ids.length+' 题已修改或移除，需重新审查':''}`);await onChanged()}catch(e:any){E(e.message)}finally{actionLock.current=false;B(false)}}

 const results=t?.results||[],remaining=results.filter((r:any)=>!r.eligible),shown=(confirm?targets:results).filter((r:any)=>filter==='all'||(filter==='pass'?r.eligible:!r.eligible));
 const close=()=>{if(!busy){C(false);SR(false)}};
 return <div className="review-toolbar-wrap"><div className="review-toolbar"><div className="review-toolbar-actions"><button onClick={onBack}>← 导入详情</button><button disabled={busy||active||!pendingCount} onClick={start}>{active?'审查中…':t?'重新轻量审查':'轻量审查'}</button>{results.length>0&&<button onClick={()=>{F('all');SR(true)}}>查看结果</button>}</div><div className="review-toolbar-status" role="status">{t?<><span>{active?'已审查':t.status==='succeeded'?'审查完成':'审查未完成'} {results.length}/{t.total}</span>{t.cost!=null&&<span>约 ¥{t.cost.toFixed(4)}</span>}{!active&&<>{t.reused_count>0&&<span>复用已审查结果 {t.reused_count} 题</span>}<span className="review-count-good">{passed.length} 题可入库</span><span>{remaining.length} 题需处理</span></>}</>:<span>{subject} · {pendingCount} 题待审核</span>}</div>{!active&&(passed.length>0||selectedIds.length>0)&&<button className="review-import-primary" disabled={!targets.length} onClick={()=>{F('all');E('');C(true)}}>{selectedIds.length?'选中入库':'批量入库'} {targets.length} 题</button>}</div>
 {t?.error&&<p className="review-toolbar-error" role="alert">{t.error}</p>}{error&&!modal&&<p className="review-toolbar-error" role="alert">{error}</p>}{message&&<p className="review-toolbar-message" role="status">{message}</p>}
 {modal&&createPortal(<div className="review-batch-backdrop" onClick={e=>{if(e.target===e.currentTarget)close()}}><div className="review-batch-dialog" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="review-batch-title"><header><div><h2 id="review-batch-title">{confirm?'确认批量入库':'轻量审查结果'}</h2><p>{confirm?'仅移入下列审查通过的题目，未通过或未选中的题目保留待处理。':`已审查 ${results.length} 道题，可点击题号查看原题。`}</p></div><button aria-label="关闭审查弹窗" disabled={busy} onClick={close}>×</button></header><div className="review-batch-summary"><span><b>{confirm?targets.length:passed.length}</b> {confirm?'本次入库':'待入库'}</span><span><b>{remaining.length}</b> 需处理</span>{t.confirmed_ids?.length>0&&<span><b>{t.confirmed_ids.length}</b> 已入库</span>}</div>
 {!confirm&&<div className="review-batch-filters">{[['all','全部'],['pass','审查通过'],['review','需处理']].map(([v,l])=><button key={v} aria-pressed={filter===v} onClick={()=>F(v)}>{l}</button>)}</div>}
 <div className="review-batch-list">{shown.map((r:any)=><div className="review-batch-row" key={r.id}><div><a href={'#question-'+r.id} onClick={e=>{if(onQuestion){e.preventDefault();close();onQuestion(r.id)}else close()}}>{r.label}</a><span className={r.eligible?'review-count-good':'review-count-warn'}>{t.confirmed_ids?.includes(r.id)?'已入库':labels[r.state]||r.state}</span></div>{reviewMessages(r.issues||[]).map((text:string,i:number)=><p key={'issue'+i}><InlineText text={text}/></p>)}{reviewMessages(r.cleanup||[]).map((text:string,i:number)=><p key={'cleanup'+i} className="review-cleanup"><InlineText text={text}/></p>)}</div>)}{!shown.length&&<p className="review-list-empty">暂无题目</p>}</div><footer>{error&&<p role="alert">{error}</p>}{confirm&&<p>题目如在审查后被编辑，将自动跳过，不会覆盖你的修改。</p>}<div><button disabled={busy} onClick={close}>{confirm?'暂不入库':'关闭'}</button>{confirm&&<button className="review-import-primary" disabled={busy||!targets.length} onClick={apply}>{busy?'正在入库…':`确认入库 ${targets.length} 题`}</button>}</div></footer></div></div>,document.body)}</div>
}
