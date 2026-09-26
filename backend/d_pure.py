"""Pure D transcription contract; no generated solutions, metadata or QA facts."""
import json,copy
from .d_contract import Strict,Assignment,Page
from .d_stream_contract import Transcription
from .d_recovery import repair_syntax,unique,array_objects
from typing import Optional
from pathlib import Path

PROFILE='pure_d_page_overview_v1'
LEGACY='legacy_full'
class Question(Transcription):
 continuation_of:Optional[str]
 context_closed:bool
class Output(Strict):
 questions:list[Question]
 asset_assignments:list[Assignment]
 page_extractions:list[Page]
 issues:list[str]
from .d_boundary import PROMPT as BOUNDARY_PROMPT
PROMPT=Path(__file__).with_name('d_pure_prompt.txt').read_text()+BOUNDARY_PROMPT

def recover(raw):
 repaired,edits=repair_syntax(raw)
 for status,text in [('raw_success',raw),('repaired',repaired)]:
  try:return dict(status=status,output=Output.model_validate(json.loads(text,object_pairs_hook=unique)).model_dump(),edits=[] if status=='raw_success' else edits)
  except ValueError:pass
 out=dict(questions=[],asset_assignments=[],page_extractions=[],issues=[])
 for key,model in [('questions',Question),('asset_assignments',Assignment),('page_extractions',Page)]:
  for item in array_objects(repaired,key):
   try:out[key].append(model.model_validate(item).model_dump())
   except ValueError:pass
 return dict(status='partial' if out['questions'] else 'unrecoverable',output=out,edits=edits)


def presentation_questions(questions):
 """Wrap standalone bare formula fields only; never change carry/source text."""
 import re
 rows=copy.deepcopy(questions)
 def present(text):
  # No prose, existing delimiters or guessed mathematical content.
  if re.search(r'[\u4e00-\u9fff]|\\[([]|\$',text):return text
  if re.search(r'\\(?:frac|sqrt)\b|\^',text) and re.fullmatch(r'[A-Za-z0-9\\{}^_+−=·×÷*/().,;<>≤≥ \-]+',text):
   return r'\('+text+r'\)'
  return text
 for row in rows:
  row['question_text']=present(row['question_text'])
  for key in ['options','subquestions']:
   for part in row[key]:part['text']=present(part['text'])
 return rows
