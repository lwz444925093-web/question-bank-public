import React from 'react';
import {LIBRARY_PAGE_SIZE} from './libraryPageWindow';
export function LibraryPagination({value,onChange,disabled=false,position='top'}:any){
 if(!value.total)return null;
 return <div className="library-pagination" role="navigation" aria-label={position==='top'?'题目分页':'题目分页（底部）'}>
  <span>第 {value.start+1}–{value.end} 题，共 {value.total} 题</span>
  <div><button disabled={disabled||value.page===0} onClick={()=>onChange(value.page-1)}>上一页</button>
  <label>第 <select aria-label={position==='top'?'选择题目页码':'选择题目页码（底部）'} value={value.page} disabled={disabled} onChange={e=>onChange(Number(e.target.value))}>{Array.from({length:value.pages},(_,i)=><option key={i} value={i}>{i+1}</option>)}</select> / {value.pages} 页</label>
  <button disabled={disabled||value.page===value.pages-1} onClick={()=>onChange(value.page+1)}>下一页</button></div>
  <small>每页 {LIBRARY_PAGE_SIZE} 题</small>
 </div>;
}
