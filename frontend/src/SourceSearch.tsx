import {useId,useState} from 'react';
export type SourceOption={id:string,name:string,approved:number,pending:number,processing:number,time:number};
export function sourceOptions(questions:any[],visible:any[],jobs:any[],subject:string){
 const files=new Map<string,SourceOption>(),published=new Set(visible.map(q=>q.id));
 const ensure=(id:string,name:string,time:number)=>{let f=files.get(id);if(!f){f={id,name,approved:0,pending:0,processing:0,time};files.set(id,f)}f.time=Math.max(f.time,time);return f};
 for(const q of questions){if(subject&&(q.subject||'数学')!==subject)continue;const f=ensure(q.source?.id||q.source?.file||'__no_source__',q.source?.display_name||q.source?.file||'未提供来源',q.created_at||0);if(!published.has(q.id))f.processing++;else if(q.review_status==='approved')f.approved++;else f.pending++}
 for(const j of jobs){const b=j.bundle||{};if(!['queued','running'].includes(j.status)||j.review_task||b.operation||b.question_ids||!b.original||(subject&&(b.subject||'数学')!==subject))continue;const id=b.source_id||b.sha256;if(id){const f=ensure(id,b.display_name||b.original,j.created_at||0);if(!f.approved&&!f.pending&&!f.processing)f.processing=1}}
 return [...files.values()].sort((a,b)=>b.time-a.time||a.name.localeCompare(b.name,'zh-CN'));
}
export function SourceSearch({files,value,onChange}:{files:SourceOption[],value:string,onChange:(id:string)=>void}){
 const id=useId(),[open,O]=useState(false),[query,Q]=useState(''),[active,A]=useState(0);
 const selected=files.find(f=>f.id===value),matches=files.filter(f=>f.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
 const options=[{id:'',name:'全部来源文件',approved:0,pending:0,processing:0,time:0},...matches];
 const choose=(key:string)=>{onChange(key);O(false);Q('')};
 return <div className="source-file-filter">来源文件<div className="source-search" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))O(false)}}><input role="combobox" aria-label="搜索来源文件" aria-expanded={open} aria-controls={id} aria-autocomplete="list" aria-activedescendant={open?id+'-'+Math.min(active,options.length-1):undefined} value={open?query:selected?.name||''} placeholder="全部来源文件 · 输入文件名搜索" title={selected?.name} onFocus={()=>{O(true);Q('');A(0)}} onChange={e=>{Q(e.target.value);O(true);A(0)}} onKeyDown={e=>{if(e.key==='Escape'){O(false);return}if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();O(true);A(i=>Math.max(0,Math.min(options.length-1,i+(e.key==='ArrowDown'?1:-1))))}if(e.key==='Enter'&&open){e.preventDefault();choose(options[Math.min(active,options.length-1)].id)}}}/>{open&&<div id={id} role="listbox" aria-label="来源文件搜索结果" className="source-search-options">{options.map((f,i)=><button type="button" role="option" id={id+'-'+i} aria-selected={value===f.id} key={f.id} className={active===i?'active':''} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(f.id)} title={f.name}><span>{f.name}</span>{f.id&&<small>{f.approved} 题已入库 · {f.pending} 题待审核{f.processing>0?' · 导入处理中':''}</small>}</button>)}{!matches.length&&<p>没有匹配的来源文件</p>}</div>}</div></div>
}
