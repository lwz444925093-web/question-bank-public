"""Question/figure revisions preserve solutions unless that field is explicitly edited."""
import copy
ANSWER_FIELDS=('original_answer','ai_answer','human_answer','source_answer','answer_edited','answer_is_complete','answer_status')
EXPLANATION_FIELDS=('original_explanation','ai_explanation','human_explanation','source_explanation','explanation_edited')
def preserve_solutions(target,current,edited_field=None):
 for fields,name in [(ANSWER_FIELDS,'answer'),(EXPLANATION_FIELDS,'explanation')]:
  if edited_field in (name,'solution'):continue
  for key in fields:
   if key in current:target[key]=copy.deepcopy(current[key])
   else:target.pop(key,None)
 if edited_field not in ('answer','explanation','solution'):
  for key in ['solution_status','solution_attempts','solution_issues','solution_differences']:
   if key in current:target[key]=copy.deepcopy(current[key])
   else:target.pop(key,None)
 return target
