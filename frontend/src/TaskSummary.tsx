import React,{useState,useEffect} from 'react';
const labels:any={queued:'排队中',running:'处理中',succeeded:'处理结束',partial:'部分未完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'};
export function taskResultLabel(t:any){
 const o=t.import_outcomes;
 const reviewedComplete=t.completion_state==='completed_with_review'&&t.page_extraction?.incomplete_pages?.length===0&&!t.unresolved_page_segments?.length;
 if(o)return (['queued','running'].includes(t.status)?labels[t.status]:reviewedComplete?'导入完成，部分题待审核':t.status==='succeeded'?'导入完成':'导入未全部完成，已保留结果')+'，'+(o.figures.needs_manual_crop+o.figures.needs_recrop_from_source+o.figures.failed+o.missing_figures)+' 张图片需要处理 · '+o.directly_usable+' 题可直接使用';
 const c=t.question_outcomes;
 if(!c)return labels[t.status]||t.status;
 if(!c.known)return (t.status==='failed'?'任务失败':labels[t.status]||t.status)+' · 题数未确定';
 return (['queued','running'].includes(t.status)?labels[t.status]+' · ':'')+`${c.approved} 题通过 · ${c.pending} 题待审核 · ${c.failed} 题失败`+(c.unavailable?` · ${c.unavailable} 题已移除`:'')+(c.unresolved_batch?' · 部分题数未确定':'');
}
export function TaskCost({task:t,compact=false}:any){
 const[c,C]=useState(t.task_cost),[stale,STALE]=useState(false);
 useEffect(()=>{C(t.task_cost)},[t.id,t.task_cost]);
 useEffect(()=>{
  if(!['queued','running'].includes(t.status))return;
  let stopped=false,timer:ReturnType<typeof setTimeout>;const controller=new AbortController();
  const update=async()=>{if(document.hidden){timer=setTimeout(update,5000);return}let active=true;try{
   const response=await fetch(`/api/tasks/${t.id}/cost`,{signal:controller.signal});
   if(!response.ok)throw Error('费用更新失败');
   const data=await response.json();if(stopped)return;C(data.task_cost);STALE(false);active=['queued','running'].includes(data.status);
  }catch{if(!stopped)STALE(true)}finally{if(!stopped&&active)timer=setTimeout(update,5000)}};
  void update();return()=>{stopped=true;controller.abort();clearTimeout(timer)};
 },[t.id,t.status]);
 if(!c)return compact?<small>花费：未记录</small>:null;
 if(compact)return <small>花费：{c.amount!=null?'¥'+Number(c.amount).toFixed(4):'待返回'}{c.missing_calls>0?'（部分费用未知）':''}</small>;
 return <small className="task-individual-cost">{c.amount!=null?'已记录 ¥'+c.amount.toFixed(4):'费用待返回'} · {c.observed_calls||0} 次已统计{c.pending_calls>0?` · ${c.pending_calls} 次等待返回`:''}{c.missing_calls>0?` · ${c.missing_calls} 次费用未知`:''}{stale?' · 更新暂时失败':''}</small>
}
export function TaskElapsed({task:t}:any){
 const [now,NOW]=useState(Date.now()/1000);
 useEffect(()=>{if(t.status!=='running'||t.finished_at)return;const timer=setInterval(()=>NOW(Date.now()/1000),1000);return()=>clearInterval(timer)},[t.status,t.finished_at]);
 return <>{Math.max(0,Math.floor((t.finished_at||now)-t.started_at))} 秒</>;
}
export function TaskSummary({task:t}:any){
 const start=t.started_at||t.created_at;
 const time=(v:number)=>new Date(v*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
 const text=(start?time(start):'时间未记录')+(t.finished_at?' → '+time(t.finished_at):t.status==='running'?' → 进行中':t.status==='queued'?' · 等待开始':'');
 const title=(t.bundle?.subject||'数学')+' · '+(t.bundle?.display_name||'题目处理任务');
 return <summary className="task-row-summary"><span className="task-row-name" title={title}>{title}</span><span className="task-row-meta"><time title={text}>{text}</time><strong className={'task-row-status '+t.status}>{taskResultLabel(t)}</strong>{t.started_at&&(t.finished_at||t.status==='running')&&<small>{t.finished_at?'耗时':'已用时'} <TaskElapsed task={t}/></small>}<TaskCost task={t}/></span></summary>;
}

export function ImportOutcomes({task:t}:any){const o=t.import_outcomes;if(!o)return null;return <div className="import-outcomes"><b>已发现 {o.discovered} 道题</b><p>文字：可用 {o.content.ready}/{o.discovered} · 待审核 {o.content.needs_review} · 不完整 {o.content.incomplete}</p><p>图片：可直接使用 {o.figures.ready} · 手动裁剪 {o.figures.needs_manual_crop} · 从原文重截 {o.figures.needs_recrop_from_source+o.missing_figures} · 来源无法恢复 {o.figures.failed}</p><p>需要人工图片处理 {o.needs_figure_work} 题</p></div>}

export function UnresolvedSegments({task:t,onRetry,busy=false}:any){
 const segments=t.unresolved_page_segments||[];
 if(!segments.length)return null;
 return <div className="unresolved-segments"><b>以下页段未完成</b>{segments.map((s:any,i:number)=><p key={i}>第 {s.pages.join('、')} 页：{s.reason} <button disabled={busy||['queued','running'].includes(t.status)} onClick={()=>onRetry(s.pages)}>{busy?'正在提交…':'仅重跑此页段'}</button></p>)}</div>;
}

export function HistoryRecord({task:t}:any){
 const c=t.question_outcomes;
 const status=c?.known?`${c.approved}通过 · ${c.pending}待审 · ${c.failed}失败`+(c.unavailable?` · ${c.unavailable}已移除`:'')+(c.unresolved_batch?' · 题数待定':''):labels[t.status]||'题数未确定';
 const fullStatus=(c?.known&&['running','queued','partial','failed','interrupted','cancelled'].includes(t.status)?labels[t.status]+' · 当前 ':'')+status;
 const date=t.created_at||t.started_at;
 const time=date?new Date(date*1000).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'时间未记录';
 const name=t.bundle?.display_name||'题目处理任务';
 return <article className="history-record">
 <div className="history-line history-line-title"><h3 title={name}>{name}</h3><time title={time}>{time}</time></div>
 <div className="history-line history-line-details"><small>耗时 {t.started_at&&(t.finished_at||t.status==='running')?<TaskElapsed task={t}/>:t.status==='queued'?'等待':'未记录'}</small><TaskCost task={t} compact/><span title={fullStatus} className={'task-row-status '+t.status}>{fullStatus}</span></div>
 </article>;
}
