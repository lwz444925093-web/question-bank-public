export function materialProgress(f:any){
 const total=Number(f.total_pages)||0;
 const count=(pages:any[])=>new Set((pages||[]).filter(p=>Number.isInteger(p)&&p>0&&p<=total)).size;
 const done=count(f.completed_pages),retained=count(f.retained_pages),submitted=count(f.submitted_pages);
 const detail=f.kind==='PDF'&&total?`明确完成 ${done}/${total} 页 · 有题记录 ${retained}/${total} 页 · 已提交 ${submitted}/${total} 页`: `${f.question_count||0} 道题`;
 if(f.file_error)return {key:'incomplete',label:'文件读取异常',detail};
 if(f.status==='processing')return {key:'processing',label:'处理中',detail};
 if(f.kind==='PDF'&&total){
  if(done===total)return {key:'complete',label:f.question_count?'全部导入':'全部解析 · 无题目',detail};
  if(done>0 || retained>0){
   if(retained===total)return {key:'uncertain',label:'完整性待确认',detail};
   return {key:'partial',label:'部分导入',detail};
  }
 }
 if(f.question_count>0)return {key:'uncertain',label:'完整性待确认',detail};
 if(f.status==='not_imported')return {key:'not_imported',label:'未导入',detail};
 return {key:'incomplete',label:'尚未完成导入',detail};
}
