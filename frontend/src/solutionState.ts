// Keep solution previews, persisted answers, and unsaved editor drafts distinct.
const solutionFields={answer:['original_answer','ai_answer','human_answer','source_answer','answer_edited','answer_is_complete','answer_status'],explanation:['original_explanation','ai_explanation','human_explanation','source_explanation','explanation_edited']};
const solutionMetadata=['solution_status','solution_attempts','solution_issues','solution_differences'];
export const isSolutionTarget=(target:string)=>['answer','explanation','solution'].includes(target);

export function solutionBlocks(q:any,field:'answer'|'explanation'):any[]{
 if(q?.[field+'_edited']||(field==='answer'&&q?.answer_is_complete)||q?.['human_'+field]?.length)return q?.['human_'+field]||[];
 return q?.['ai_'+field]?.length?q['ai_'+field]:q?.['original_'+field]||[];
}
function hasContent(blocks:any[]):boolean{
 return Array.isArray(blocks)&&blocks.some(b=>b.kind==='equation'?!!b.latex?.trim():b.kind==='image'?!!b.asset:b.kind==='geometry'?!!b.shapes?.length:b.kind==='table'?(b.rows||[]).flat(2).some((s:any)=>!!s.text?.trim()||s.kind==='image'):b.spans?.some((s:any)=>!!s.text?.trim()||s.kind==='image'));
}
export function usableReviewProposal(task:any):boolean{
 if(task?.status!=='ready'||!task.question)return false;
 if(!isSolutionTarget(task.target_field))return true;
 if(['failed','needs_retry','incomplete','unavailable_due_to_source_issue'].includes(task.question.solution_status))return false;
 return (task.target_field==='solution'?['answer','explanation']:[task.target_field]).every(field=>hasContent(solutionBlocks(task.question,field as 'answer'|'explanation')));
}
export function reviewTaskNotice(task:any,currentRevision?:number):{text:string,error:boolean}{
 if(!task)return {text:'',error:false};
 const solution=isSolutionTarget(task.target_field),name=solution?'答案解析':'修改预览';
 if(task.status==='failed')return {text:(solution?'答案解析生成失败':'复核失败')+'：'+(task.error||'本次未返回完整结果，请重试。'),error:true};
 if(task.status==='interrupted'||task.status==='cancelled')return {text:task.status==='interrupted'?'任务已中断，可重新提交。':'任务已停止。',error:true};
 if(task.status==='ready'){
  if(currentRevision!==undefined&&task.revision!==currentRevision)return {text:'题目已有新版本，本次预览已过期，请重新提交。',error:true};
  if(!usableReviewProposal(task))return {text:'答案或解析未生成完整，本次结果无法采用。可重新生成。',error:true};
  return {text:name+(solution&&task.question.solution_status==='needs_review'?'已生成，但存在疑点，请核对后再采用。':'已就绪，请查看新版本后采用。'),error:false};
 }
 if(task.status==='applied')return {text:name+'已采用。',error:false};
 return {text:task.status==='queued'?'已提交，等待处理。':task.status==='running'?(solution?'正在生成答案解析…':'正在复核…'):'',error:false};
}
export function withSolutions(version:any,current:any){
 const result={...version};
 for(const [field,keys] of Object.entries(solutionFields)){
  if(version?.__solutionTarget===field||version?.__solutionTarget==='solution')continue;
  for(const key of keys){if(current&&key in current)result[key]=current[key];else delete result[key]}
 }
 if(!isSolutionTarget(version?.__solutionTarget))for(const key of solutionMetadata){if(current&&key in current)result[key]=current[key];else delete result[key]}
 return result;
}
export type SolutionDraft={baseRevision:number,question:any};
export function currentSolutionDraft(draft:SolutionDraft|undefined,current:any){return draft?.baseRevision===current?.revision?draft.question:current}
