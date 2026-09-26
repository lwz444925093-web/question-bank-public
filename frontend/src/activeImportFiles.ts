export function isFileImportTask(job:any){
 const b=job.bundle||{};
 return ['queued','running'].includes(job.status)&&!job.review_task&&!b.operation&&!b.question_ids&&!!b.original&&!!(b.source_id||b.sha256);
}
// Parent and child jobs for the same source share one row; subjects stay distinct.
export function activeImportFiles(jobs:any[],questions:any[]){
 const files=new Map<string,{key:string,id:string,name:string,subject:string,running:boolean,approved:number,pending:number}>();
 for(const job of jobs){
  if(!isFileImportTask(job))continue;
  const b=job.bundle,id=b.source_id||b.sha256,subject=b.subject||'数学',key=subject+':'+id,previous=files.get(key);
  files.set(key,{key,id,subject,name:previous?.name||b.display_name||b.original,running:!!previous?.running||job.status==='running',approved:0,pending:0});
 }
 for(const q of questions){
  const file=files.get((q.subject||'数学')+':'+q.source?.id);if(!file)continue;
  if(q.review_status==='approved')file.approved++;else file.pending++;
 }
 return [...files.values()];
}
