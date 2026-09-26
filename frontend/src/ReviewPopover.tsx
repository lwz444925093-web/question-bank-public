import React,{useEffect,useRef,useState} from 'react';
import {reviewTaskNotice,usableReviewProposal,isSolutionTarget} from './solutionState';
import {InlineText} from './InlineText';
import {reviewMessages} from './reviewMessages';
const presets:Record<string,string[]>={
 question:['对照原始材料重新解析本题，准确还原题干、公式、选项和小问，保持题意不变，不修改答案和解析。','对照原始材料检查题目是否完整，核对条件、公式、选项、小问和题图标注；补回可确认的遗漏，无法确认的内容列出说明。','检查并规范题目的文字、数学符号、公式和编号格式，修正识别或排版错误，保持题意不变。'],
 solution:['根据本题及我补充的提示，重新生成答案和解析。按小问分别给出结果与推导步骤，确保答案、解析相互一致，保留题目和图片不变。'],
 image:['将选中的图片转换为清晰的 SVG 矢量图，忠实保留原图的字母、刻度、线条、虚实线、连接关系和相对位置，不增删内容，不补画解题辅助线。']
};
const presetLabels:Record<string,string[]>={question:['重新识别本题','检查是否完整','整理文字与公式'],solution:['生成答案与解析'],image:['转为清晰矢量图']};
const labels:Record<string,string>={question:'题目',answer:'答案',explanation:'解析',solution:'答案与解析',image:'图片'};
export function ReviewPopover({question:q,field,dirty,onSubmitted,onPreview}:any){
 const [open,O]=useState(false),[drafts,D]=useState<Record<string,string>>({}),[busy,B]=useState(false),[task,T]=useState<any>(null),[error,E]=useState(''),[loading,L]=useState(false);
 const root=useRef<HTMLDivElement>(null),sending=useRef(false);
 const promptField=['answer','explanation'].includes(field)?'solution':field;
 const comment=drafts[promptField]??presets[promptField][0];
 const blocks=[...(q.stem||[]),...[...(q.options||[]),...(q.subquestions||[])].flatMap((p:any)=>p.blocks||[])];
 const images=Array.from(new Set<string>(blocks.filter((b:any)=>b.kind==='image').map((b:any)=>b.asset)));
 const [selected,A]=useState<string[]>(images);
 useEffect(()=>{A(images)},[q.revision]);
 useEffect(()=>{if(!open)return;const close=(e:PointerEvent)=>{if(!root.current?.contains(e.target as Node))O(false)};document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close)},[open]);
 useEffect(()=>{
  if(!open)return;let active=true,timer:ReturnType<typeof setTimeout>;const controller=new AbortController();L(true);
  const poll=async()=>{let retry=false;try{const r=await fetch('/api/questions/'+q.id+'/review/latest',{signal:controller.signal});if(!r.ok)throw Error('无法读取复核状态');const data=await r.json();if(active){T(data);E('');retry=!!data&&['running','queued'].includes(data.status)}}catch(e:any){if(active){E(e.message);retry=true}}finally{if(active){L(false);if(retry)timer=setTimeout(poll,5000)}}};
  void poll();return()=>{active=false;controller.abort();clearTimeout(timer)}
 },[open,q.id,task?.id,task?.status]);
 const working=task&&['queued','running'].includes(task.status);
 const notice=reviewTaskNotice(task,q.revision);
 const previewReady=usableReviewProposal(task)&&task.revision===q.revision;
 const send=async()=>{if(sending.current)return;sending.current=true;B(true);E('');try{
  const target=['answer','explanation'].includes(field)?'本次一起生成或修订答案和解析，保证两者一致，保留题目和图片；疑点列入复核意见。':field==='image'?'仅修改选中的图片，保留题目、答案与解析。':`本次仅审核和修订${labels[field]}，保留其他部分和图片；相关疑点列入复核意见。`;
  const r=await fetch('/api/questions/'+q.id+'/review/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:q.revision,target_field:['answer','explanation'].includes(field)?'solution':field,scope:field==='image'?'image':'question',assets:field==='image'?selected:[],comment:target+'\n'+comment.trim()})});const data=await r.json();if(!r.ok)throw Error(data.detail||'提交失败');T(data);onSubmitted?.();
 }catch(e:any){E(e.message)}finally{sending.current=false;B(false)}};
 return <div ref={root} className="review-popover" onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();O(false)}}}>
  <button className={'review-ai-icon'+(open?' active':'')} aria-label="AI 复核助手" aria-expanded={open} aria-haspopup="dialog" onClick={()=>O(!open)} title="AI 复核"><svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" fill="currentColor"/></svg><span>AI</span></button>
  {open&&<div className="review-popover-panel" role="dialog" aria-label={labels[promptField]+' AI 复核'}><header><strong>AI 复核 · {labels[promptField]}</strong><button aria-label="关闭 AI 复核" onClick={()=>O(false)}>×</button></header>
   <div className="review-preset-list">{presets[promptField].map((text,i)=><button key={text} disabled={busy} aria-pressed={comment===text} onClick={()=>D(old=>({...old,[promptField]:text}))}>{presetLabels[promptField][i]}</button>)}</div>
   {field==='image'&&<div className="review-popover-images">{images.map((asset,i)=><label key={asset}><input type="checkbox" checked={selected.includes(asset)} disabled={busy} onChange={e=>A(e.target.checked?[...selected,asset]:selected.filter(a=>a!==asset))}/>图片 {i+1}</label>)}{!images.length&&<p>本题没有可复核的图片。</p>}</div>}
   <textarea aria-label="AI 复核要求" maxLength={3600} value={comment} disabled={busy} onChange={e=>D(old=>({...old,[promptField]:e.target.value}))}/>
   {dirty&&<p className="warning">请先保存正文修改，再发送复核。</p>}
   <button className={previewReady?'':'primary'} disabled={busy||loading||working||dirty||!comment.trim()||(field==='image'&&!selected.length)} onClick={send}>{busy?'正在发送…':working?'后台处理中…':previewReady?'重新生成':promptField==='solution'?'生成答案和解析':'开始复核'}</button>
   {previewReady&&onPreview&&<button className="primary" disabled={dirty} onClick={()=>onPreview(task)}>查看生成结果</button>}
   {notice.text&&<p role={notice.error?'alert':'status'} className={notice.error?'review-task-notice error':'review-task-notice'}><InlineText text={notice.text}/></p>}
   {usableReviewProposal(task)&&isSolutionTarget(task.target_field)&&task.question.solution_status==='needs_review'&&reviewMessages(task.question.solution_issues||[]).map((text:string,i:number)=><p key={i} className="review-task-notice"><InlineText text={text}/></p>)}
   {error&&<p role="alert">{error}</p>}
  </div>}
 </div>
}
