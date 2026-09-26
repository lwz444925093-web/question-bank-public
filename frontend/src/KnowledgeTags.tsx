import React,{useState} from 'react';
export function KnowledgeTags({value=[],onChange}:any){
 const [newTag,N]=useState('');
 const add=()=>{const tags=newTag.split(/[,，\n]/).map(t=>t.trim()).filter(Boolean);if(tags.length)onChange(Array.from(new Set([...value.map((t:string)=>t.trim()).filter(Boolean),...tags])));N('')};
 return <section className="knowledge-tags-editor" aria-label="编辑知识点标签"><h3>知识点标签</h3>
  <div className="knowledge-tag-list">{value.map((tag:string,i:number)=><div className="knowledge-edit-tag" key={i}>
   <input aria-label={'知识点标签 '+(i+1)} value={tag} size={Math.max(4,Math.min(18,tag.length*2))} placeholder="标签名称" onChange={e=>onChange(value.map((t:string,j:number)=>i===j?e.target.value:t))}/>
   <button type="button" aria-label={'删除标签 '+tag} onClick={()=>onChange(value.filter((_:string,j:number)=>i!==j))}>×</button>
  </div>)}</div>
  <div className="knowledge-tag-add"><input aria-label="添加知识点标签" placeholder="添加标签，回车确认" value={newTag} onChange={e=>N(e.target.value)} onBlur={add} onKeyDown={e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();add()}}}/><button type="button" disabled={!newTag.trim()} onMouseDown={e=>e.preventDefault()} onClick={add}>添加</button></div>
 </section>
}
