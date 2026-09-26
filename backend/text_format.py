"""Lossless paragraph splitting and conservative recovery of explicit mathematics.

Only complete, locally exportable formulas become editable math spans. Ordinary
words/labels are not inferred as formulas, and incomplete source text is retained.
"""
import copy
import re
from functools import lru_cache


def math_notation(value):
 for chars,operator in [('₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎','_'),('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾','^')]:
  translation=str.maketrans(chars,'0123456789+-=()')
  value=re.sub('['+chars+']+',lambda m:operator+'{'+m[0].translate(translation)+'}',value)
 return value


# Chinese is accepted only in an explicitly marked index or a TeX text group.
# Otherwise it terminates the candidate so prose can never enter a formula.
_ATOM=r'(?:\\(?:text|mathrm)\{[^{}\n]*\}|[_^]\{[\u4e00-\u9fff]+\}|_[\u4e00-\u9fff]|\\[A-Za-z]+|[A-Za-z0-9\\=+*/^_{}()[\].,<>|:;!\-\t ₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾∠≤≥≠°×÷′\'])'
_EXPLICIT=re.compile(
 r'(?<!\\)\$\$[^$]+?\$\$|(?<!\\)\$[^$\n]+?\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]'
 r'|\\begin\{cases\}[\s\S]*?\\end\{cases\}'
 r'|(?<![A-Za-z0-9\\])'+_ATOM+'+'
)
_MARKER=re.compile(r'\\[A-Za-z]+|[A-Za-z0-9)}\]][_^](?:\{|[A-Za-z0-9\u4e00-\u9fff+-])|[₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]')
_FRAGMENT=re.compile(r'\\(?:frac|dfrac|tfrac|sqrt|begin)\b')


def _brace_balance(value):
 depth=0
 for match in re.finditer(r'(?<!\\)[{}]',value):
  depth+=1 if match[0]=='{' else -1
  if depth<0:return -1
 return depth


def _canonical_indices(value):
 def replace(match):
  operator,chinese,one,ascii_value=match.groups()
  return operator+'{'+(r'\text{'+(chinese or one)+'}' if chinese or one else ascii_value)+'}'
 return re.sub(r'([_^])(?:\{([\u4e00-\u9fff]+)\}|([\u4e00-\u9fff])|([+-]?\d+|[A-Za-z]\d*))',replace,math_notation(value))


@lru_cache(maxsize=2048)
def _valid_math(value):
 if not value.strip() or len(value)>4000 or _brace_balance(value)!=0:return False
 # A plain file_name or English phrase containing x^2 is not a math run.
 words=re.sub(r'\\(?:text|mathrm)\{[^{}]*\}|\\(?:begin|end)\{[^{}]*\}|\\[A-Za-z]+','',value)
 if any(len(word)>3 and not word.isupper() and word not in {'arcsin','arccos','arctan'} for word in re.findall(r'[A-Za-z]+',words)):return False
 try:
  # Pandoc is already used for Word export. It checks complete fractions,
  # indices, environments and supported commands without a model request.
  from .exporter import math_xml
  math_xml(value)
  return True
 except Exception:return False


def _text_math_spans(span):
 text=span['text'];result=[];cursor=0
 for match in _EXPLICIT.finditer(text):
  raw=match[0];offset=match.start();value=raw
  delimited=False
  for opening,closing in [('$$','$$'),('$','$'),(r'\(',r'\)'),(r'\[',r'\]')]:
   if raw.startswith(opening) and raw.endswith(closing):
    value=raw[len(opening):-len(closing)];delimited=True;break
  if not delimited:
   # Keep surrounding spaces and sentence punctuation as ordinary text.
   left=len(value)-len(value.lstrip());offset+=left;value=value.lstrip()
   value=value.rstrip(' \t.,;:')
   blank=re.search(r'\s*_{2,}$',value)
   if blank:value=value[:blank.start()]
   # Do not turn a leading question number into part of the formula.
   number=re.match(r'\d+\.(?=\s*[A-Za-z\\])\s*|\(\d+\)\s+(?=[A-Za-z\\])',value)
   if number:offset+=number.end();value=value[number.end():]
  if not _MARKER.search(value) and not delimited:continue
  canonical=_canonical_indices(value)
  if not _valid_math(canonical):continue
  end=match.end() if delimited else offset+len(value)
  if offset>cursor:result.append(dict(span,text=text[cursor:offset]))
  result.append(dict(kind='math',text=canonical))
  cursor=end
 if cursor<len(text):result.append(dict(span,text=text[cursor:]))
 return result or [copy.deepcopy(span)]


def format_spans(spans):
 """Recover math without changing text, crossing images, or guessing operands."""
 result=[];i=0
 while i<len(spans):
  span={k:v for k,v in spans[i].items() if not (k in {'width','height'} and v is None)};value=span.get('text','')
  if span['kind']=='image':result.append(copy.deepcopy(span));i+=1;continue
  # Old imports sometimes split the denominator into an independent math
  # span. Join only when all braces close and the complete result validates.
  if span['kind']=='text' and _FRAGMENT.search(value) and _brace_balance(value)>0:
   j=i
   while _brace_balance(value)>0 and j+1<len(spans) and spans[j+1]['kind'] in {'text','math'}:
    j+=1;value+=spans[j].get('text','')
   if j>i and _brace_balance(value)==0:
    recovered=_text_math_spans(dict(span,text=value))
    if any(s['kind']=='math' for s in recovered) and not any(s['kind']=='text' and _FRAGMENT.search(s['text']) for s in recovered):result.extend(recovered);i=j+1;continue
  if span['kind']=='math':
   # A few legacy editor spans tagged ordinary Chinese prose as math.
   if not value.strip() or re.fullmatch(r'[\u4e00-\u9fff\s，。；：！？、（）“”‘’…]+',value):
    if value:result.append(dict(span,kind='text'))
   else:
    left=len(value)-len(value.lstrip());right=len(value.rstrip())
    if left:result.append(dict(kind='text',text=value[:left]))
    result.append(dict(span,text=math_notation(value[left:right])))
    if right<len(value):result.append(dict(kind='text',text=value[right:]))
  else:result.extend(_text_math_spans(span))
  i+=1
 return result


def format_blocks(blocks):
 result=[]
 for original in blocks:
  b=copy.deepcopy(original)
  if b['kind']=='equation':
   if not b.get('latex','').strip():continue
   b['latex']=math_notation(b['latex'].strip())
  if b['kind']=='table':b['rows']=[[format_spans(cell) for cell in row] for row in b['rows']]
  if b['kind']!='paragraph':result.append(b);continue
  segments=[[]]
  for span in format_spans(b['spans']):
   if span['kind']!='text':segments[-1].append(span);continue
   for index,line in enumerate(span['text'].split('\n')):
    if index:segments.append([])
    if line:segments[-1].append(dict(span,text=line))
  for spans in segments:
   if spans:result.append(dict(b,spans=spans))
 return result


def format_question_content(question):
 """Return a normalized reading/editing copy; never write or change review state."""
 q=copy.deepcopy(question)
 for key in ['stem','ai_answer','ai_explanation','human_answer','human_explanation','source_answer','source_explanation','original_answer','original_explanation']:
  if key in q:q[key]=format_blocks(q[key])
 for key in ['options','subquestions']:
  if key in q:q[key]=[{**part,'blocks':format_blocks(part['blocks'])} for part in q[key]]
 from .table_normalize import normalize as normalize_tables
 if normalize_tables(q):
  # Reliable native table cells may have just been recovered as plain text.
  if 'stem' in q:q['stem']=format_blocks(q['stem'])
  for key in ['options','subquestions']:
   if key in q:q[key]=[{**part,'blocks':format_blocks(part['blocks'])} for part in q[key]]
 return q
