// Publish fully completed, approved questions immediately, even while sibling
// questions are importing. Unfinished drafts still wait for processing.
export function completedImportQuestions(questions:any[], jobs:any[]) {
 const activeIds = new Set<string>();
 const activeUnits = new Set<string>();
 for (const job of jobs) {
  const bundle = job.bundle || {};
  if (!['queued','running'].includes(job.status) || job.review_task || bundle.operation || bundle.question_ids) continue;
  for (const id of job.question_ids || []) activeIds.add(id);
  for (const key of [job.key, job.unit_key]) if (key) activeUnits.add(key);
 }
 return questions.filter(q => {
  if (q.processing_status==='complete' && q.solution_status==='ready' && q.review_status==='approved') return true;
  if (activeIds.has(q.id) || (q.import_unit && activeUnits.has(q.import_unit))) return false;
  // A failed/cancelled import can leave unprocessed drafts behind. Keep these
  // in the import task for retry instead of presenting them as manual review.
  if (q.import_unit && (['saved','incomplete'].includes(q.processing_status) ||
      ['needs_generation','needs_retry'].includes(q.solution_status))) return false;
  return true;
 });
}
