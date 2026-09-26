import React,{useEffect,useState} from 'react';
import {sourcePictureUrl} from './SourcePicture';

function SourcePreview({sourceId,entry}:any){
 const url=sourcePictureUrl(sourceId,entry?.asset),asset=entry?.asset||'';
 const [text,setText]=useState(''),[error,setError]=useState('');
 useEffect(()=>{setText('');setError('');if(!url||! /\.txt$/i.test(asset))return;
  const controller=new AbortController();
  fetch(url,{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error('原件暂时无法读取');return r.text()}).then(t=>{if(!controller.signal.aborted)setText(t)}).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
  return()=>controller.abort();
 },[url,asset]);
 if(!url)return <p className="source-preview-note">原件暂时无法读取</p>;
 if(error)return <p role="alert" className="source-preview-note">{error}</p>;
 if(/\.(png|jpe?g|gif|webp|svg)$/i.test(asset))return <div className="source-preview-image"><img src={url} alt={entry.label||(entry.page?'第 '+entry.page+' 页原件':'来源原件')} onError={()=>setError('原件暂时无法读取')}/></div>;
 if(/\.pdf$/i.test(asset))return <iframe className="source-preview-pdf" title="来源 PDF 预览" src={url+(Number.isInteger(entry.page)&&entry.page>0?'#page='+entry.page:'')}/>;
 if(/\.txt$/i.test(asset))return <pre className="source-preview-text">{text||'正在读取原件…'}</pre>;
 return <p className="source-preview-note">此格式暂不支持页内预览。<a href={url} download={asset}>下载原件</a></p>;
}

function SourceEvidence({sourceId,entries}:any){
 const [open,setOpen]=useState(false),[selected,setSelected]=useState(0);
 const index=Math.min(selected,Math.max(0,entries.length-1));
 if(!entries.length)return null;
 return <details className="source-evidence" onClick={e=>e.stopPropagation()} onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary>{open?'收起原件':'查看原件'}</summary>
  {open&&<div className="source-evidence-body">
   <div className="source-evidence-toolbar"><small>原始材料 · 供核对</small>{entries.length>1&&<label>页面<select aria-label="切换来源页面" value={index} onChange={e=>setSelected(Number(e.target.value))}>{entries.map((entry:any,i:number)=><option key={i} value={i}>{entry.label||(entry.page?'第 '+entry.page+' 页':'原件 '+(i+1))}</option>)}</select></label>}</div>
   {entries[index]?.label&&<p className="source-preview-note">{entries[index].label} · {entries[index].status}</p>}
   <SourcePreview key={sourceId+':'+entries[index]?.asset+':'+index} sourceId={sourceId} entry={entries[index]}/>
  </div>}
 </details>;
}
export function ProcessingStatus({question:q,onFigure}:any){
 if(q.figure_workflow_version===2){const names:any={ready:'可用',needs_review:'待审核',incomplete:'不完整',needs_manual_crop:'需要手动裁剪',needs_recrop_from_source:'需要从原文重截',failed:'来源无法恢复'};return <div className="figure-workflow-status"><p>{q.validation_cohort&&<small>{q.validation_cohort==='new'?'新流程回归':'历史坏图分流'} · 原题 Q{q.original_number}<br/></small>}文字：{names[q.content_status]} · {q.directly_usable?'本题可直接使用':'本题尚需人工处理'}</p>{q.solution_status&&<p>答案解析：{({ready:'已生成',disabled:'未开启',needs_generation:'待生成',needs_retry:'正在重试',needs_review:'待核对',failed:'生成失败'} as any)[q.solution_status]}{q.solution_attempts?.length>1&&` · 已求解 ${q.solution_attempts.length} 次`}</p>}{q.figure_records?.map((f:any)=><div className="figure-status-row" key={f.figure_id}><span>{f.position.startsWith('options/')?'选项 '+String.fromCharCode(65+Number(f.position.split('/')[1])):'题图'}：{names[f.figure_status]}</span>{f.figure_status!=='ready'&&f.figure_status!=='failed'&&onFigure&&<button onClick={()=>onFigure(f)}>{f.figure_status==='needs_recrop_from_source'?'从原文重新截取':'手动裁剪'}</button>}</div>)}{q.missing_required_figure&&onFigure&&<div className="figure-status-row"><span>题干必要图片尚未独立保存</span><button onClick={()=>onFigure({figure_id:'new-stem-image'})}>从原文补截题干图片</button></div>}</div>}

 const status=({saved:'已保存 · 后处理未完成',incomplete:'已保存 · 未完成',review:'已保存 · 待审核',complete:'已保存'} as any)[q.processing_status];
 return status&&(q.processing_status!=='complete'||q.processing_reason)?<p className="processing-status" role="status">{status}{q.processing_reason?'：'+q.processing_reason:''}</p>:null;
}
export function QuestionSourceEvidence({question:q}:any){
 return q.source_evidence?.length>0?<div className="workspace-source-evidence"><SourceEvidence key={q.id+':'+q.revision} sourceId={q.source?.id} entries={q.source_evidence}/></div>:null;
}
export function TaskEvidence({task}:any){
 const [evidence,setEvidence]=useState<any>(null);const [error,setError]=useState('');
 if(!task.evidence_available)return null;
 return <details onToggle={async e=>{if(e.currentTarget.open&&!evidence){try{const r=await fetch('/api/tasks/'+task.id+'/evidence');if(!r.ok)throw Error('暂无法读取证据');setEvidence(await r.json())}catch(x:any){setError(x.message)}}}}><summary>查看已保留的返回与来源</summary><p>{error||evidence?.error}</p>{evidence?.assets?.length>0&&<SourceEvidence sourceId={evidence.source_id} entries={evidence.assets.map((asset:string)=>({asset}))}/>}<pre style={{whiteSpace:'pre-wrap',maxHeight:260,overflow:'auto'}}>{evidence?.raw}</pre>{evidence?.truncated&&<p>显示前十万字符，完整返回仍保存在任务目录。</p>}</details>;
}
