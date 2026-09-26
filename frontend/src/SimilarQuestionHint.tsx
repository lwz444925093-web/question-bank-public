import {MergeQuestions} from './DuplicateTools';
import React,{useEffect,useRef,useState,useId} from 'react';

export function SimilarQuestionHint({question,catalogKey,render,onChanged}:any){
 const anchor=useRef<HTMLDivElement>(null),tipId=useId();
 const [visible,V]=useState(false),[result,R]=useState<any>(null),[open,O]=useState(false);
 useEffect(()=>{
  const observer=new IntersectionObserver(entries=>V(entries.some(e=>e.isIntersecting)),{rootMargin:'160px'});
  if(anchor.current)observer.observe(anchor.current);
  return()=>observer.disconnect();
 },[]);
 useEffect(()=>{R(null);O(false)},[question.id,question.revision,catalogKey]);
 useEffect(()=>{
  if(!visible||result)return;
  const controller=new AbortController();
  fetch('/api/questions/'+question.id+'/similar',{signal:controller.signal})
   .then(r=>{if(!r.ok)throw Error('读取失败');return r.json()})
   .then(R).catch(()=>{});
  return()=>controller.abort();
 },[visible,question.id,question.revision,catalogKey,result]);
 const candidates=result?.candidates||[];
 return <div ref={anchor} className="similar-question-hint" onClick={e=>e.stopPropagation()}
  

  onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();O(false)}}}>
  {candidates.length>0&&<><button type="button" className="similar-question-dot"
   aria-label={`相似题提醒：${candidates.length} 道`} aria-expanded={open} aria-describedby={open?tipId:undefined}
   onClick={()=>O(!open)}><span/></button>
   {open&&<div className="similar-question-tooltip" id={tipId} role="dialog" aria-label="相似题对照">
    <div className="preview-heading"><strong>相似题 · {candidates.length} 道</strong><button onClick={()=>O(false)}>关闭</button></div>
    {candidates.map((c:any)=><div className="similar-question-candidate" key={c.id}>
     <b>{c.question.question_type}{c.question.bank_number||c.original_number||'未编号'}</b>
     <small>{c.kind} · 相似分数 {c.score}</small>
     <small>来源：{c.question.source?.file||'未记录'}{c.question.pages?.length?` · 第 ${c.question.pages.join('、')} 页`:''}</small>
     <div className="similar-question-content">{render([...(c.question.stem||[]),...[...(c.question.options||[]),...(c.question.subquestions||[])].flatMap(p=>p.blocks||[])],c.question)}</div>
     <small>{(c.reason||[]).join('；')}</small><MergeQuestions left={question} right={c.question} onChanged={onChanged}/>
    </div>)}
   </div>}
  </>}
 </div>
}
