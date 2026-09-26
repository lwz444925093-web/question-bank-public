"""Application requests, persisted shared budgets and content-free audit records.

OpenCode steps are observable; their exact underlying model-call count is not.
No fallback provider or implicit resubmission lives in this boundary.
"""
import copy,hashlib,json,time,uuid,threading,re
from pathlib import Path
from . import store

_request_slots=threading.BoundedSemaphore(2)

DEFAULTS={'task_requests':48,'question_requests':6,'internal_steps':96,'request_steps':8,'format_repairs':1,'recrops':0}
class RequestFailure(ValueError):
 def __init__(self,message,category='system'):
  super().__init__(message);self.category=category

def policy(config):
 value=dict(DEFAULTS)
 settings=store.ROOT/'request_limits.json'
 configured=json.loads(settings.read_text()) if settings.is_file() else {}
 configured.update(config.get('request_limits',{}))
 value.update({k:int(v) for k,v in configured.items() if k in DEFAULTS})
 if any(v<0 for v in value.values()):raise ValueError('请求预算不得为负数')
 return value

def configure(config,task_id):
 result=dict(config);result.setdefault('_budget_id',task_id);return result

def snapshot(config):return store.get('settings','budget-'+config['_budget_id']) or {}

def targets(bundle):
 q=bundle.get('question',{})
 return list(dict.fromkeys([str(x.get('id') or x.get('question_id')) for x in bundle.get('questions',[]) if x.get('id') or x.get('question_id')]+([str(q['id'])] if q.get('id') else [])+[str(x['question_id']) for x in bundle.get('figures',[]) if x.get('question_id')]))

def reserve(config,bundle):
 key='budget-'+config['_budget_id'];limits=policy(config);ids=targets(bundle)
 # SQLite transaction rather than per-thread memory: parallel callers cannot overspend.
 with store.conn() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT body FROM settings WHERE id=?',(key,)).fetchone()
  b=json.loads(row[0]) if row else dict(application_requests=0,question_requests={},observed_internal_steps=0,model_calls=None,model_calls_observability='unobservable',limits=limits)
  limits=b['limits'] # Retried/subsequent calls cannot reset or silently raise budgets.
  if b['application_requests']>=limits['task_requests']:raise RequestFailure('任务请求预算耗尽，已有结果已保留','budget')
  if b['observed_internal_steps']>=limits['internal_steps']:raise RequestFailure('任务内部步骤预算耗尽','budget')
  if len(ids)==1 and b['question_requests'].get(ids[0],0)>=limits['question_requests']:raise RequestFailure('该题请求预算耗尽，转人工核对','budget')
  op=operation(bundle)
  if op=='format_repair':
   fingerprint=hashlib.sha256(str(bundle.get('previous_result','')).encode()).hexdigest()
   repairs=b.setdefault('repair_responses',{})
   if repairs.get(fingerprint,0)>=min(1,limits['format_repairs']):raise RequestFailure('该响应已尝试格式修复，停止重复返工','budget')
   repairs[fingerprint]=repairs.get(fingerprint,0)+1
  if op=='recrop':
   retry_keys=[qid+':'+fid for qid in ids for fid in bundle.get('target_figure_ids',[])]
   retries=b.setdefault('figure_recrops',{})
   if not retry_keys:raise RequestFailure('重裁缺少稳定题图身份','identity')
   if any(retries.get(k,0)>=min(1,limits['recrops']) for k in retry_keys):raise RequestFailure('该图片已尝试自动重裁，停止重复返工','budget')
   for retry_key in retry_keys:retries[retry_key]=retries.get(retry_key,0)+1
  b['application_requests']+=1
  if len(ids)==1:b['question_requests'][ids[0]]=b['question_requests'].get(ids[0],0)+1
  c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(b)))
 return b

def record_steps(config,count):
 key='budget-'+config['_budget_id']
 with store.conn() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT body FROM settings WHERE id=?',(key,)).fetchone()
  b=json.loads(row[0]);b['observed_internal_steps']+=count
  c.execute('UPDATE settings SET body=? WHERE id=?',(json.dumps(b),key))
 return b['observed_internal_steps']<=b['limits']['internal_steps']

def operation(bundle):
 if bundle.get('_operation'):return bundle['_operation']
 if 'previous_result' in bundle:return 'format_repair'
 if 'figures' in bundle:return 'verify_figures'
 if 'previous_regions' in bundle:return 'recrop'
 if 'overlays' in bundle:return 'inspect_overlays'
 if 'questions' in bundle:return 'locate_figures'
 if 'question' in bundle:return 'modify_question'
 return 'extract_source'

ALLOWED={'extract_source':['source_question_fields'],'format_repair':['structure_only'],
 'locate_figures':['figure_id','position','page','box'],'recrop':['page','box'],
 'verify_figures':['checks'],'inspect_overlays':['overlays'],
 'modify_question':['user_requested_fields'],'redraw_figure':['svg','note','issues'],
 'solve':['ai_answer','ai_explanation']}

ALLOWED.update(extract_locate=['source_question_fields','initial_figures'],verify_solve=['content_check','figure_checks','solution','solution_check'],content_solve=['content_check','solution','solution_check'],solution_only=['solution','solution_check'])

def call(provider,bundle,taskdir,schema,instruction,cancel=None,progress=None):
 from .validation_budget import guard_cli
 if not getattr(provider,'metered_http',False):guard_cli()
 cfg=provider.config
 cfg.setdefault('_budget_id','standalone-'+uuid.uuid4().hex)
 taskdir=Path(taskdir);taskdir.mkdir(parents=True,exist_ok=True)
 op=operation(bundle)
 from .contracts import CONTRACTS,VERSION
 instruction=CONTRACTS.get('locate_figures' if op=='recrop' else op,'')+'\n'+instruction
 ids=targets(bundle);started=time.monotonic();error=None;attempt=None;meta={}
 from . import run_ledger
 contract={'prompt_version':VERSION,'operation':op,'target_question_ids':ids,'target_figure_ids':bundle.get('target_figure_ids') or list(dict.fromkeys(f['figure_id'] for f in bundle.get('figures',[])+[slot for q in bundle.get('questions',[]) for slot in q.get('figure_slots',[])] if f.get('figure_id'))),
  'baseline_versions':{q['id']:q.get('revision') for q in bundle.get('questions',[])+([bundle['question']] if bundle.get('question') else []) if q.get('id')},
  'allowed_fields':bundle.get('_allowed_fields',ALLOWED.get(op,[])),
  'acceptance':'不得改动范围外源内容，不得丢题或丢图；只返回本操作的完整结构化结果，不回传request_contract。'}
 material={k:v for k,v in bundle.items() if not k.startswith('_')};material['request_contract']=contract
 try:
  with _request_slots:
   if cancel and cancel.is_set():raise RequestFailure('任务已取消','cancelled')
   reserve(cfg,bundle)
   attempt=run_ledger.reserve(cfg.get('model') or 'configured-default',role=cfg.get('provider','opencode'))
   raw,meta=provider._request(material,taskdir,schema,instruction+'\n本次请求边界：'+json.dumps(contract,ensure_ascii=False),cancel,progress)
  (taskdir/'response.private.txt').write_text(raw)
  meta=dict(meta,application_requests=1,model_calls=meta.get('model_calls'),model_calls_observability=meta.get('model_calls_observability','unobservable'))
  return raw,meta
 except Exception as exc:
  error=getattr(exc,'category','system');raise
 finally:
  run_ledger.finish(attempt,status='failed' if error else 'succeeded',error_category=error,seconds=round(time.monotonic()-started,3),session_id=meta.get('session_id'),observed_steps=meta.get('observed_internal_steps'),model_calls=meta.get('model_calls'))
  b=snapshot(cfg)
  audit={'task_id':cfg['_budget_id'],'operation':op,'question_ids':ids,'figure_ids':contract['target_figure_ids'],
   'prompt_version':VERSION,'schema_hash':hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),'model':cfg.get('model','deepseek/deepseek-flash'),'error_category':error,
   'application_requests':b.get('application_requests',0),'remaining_task_requests':max(0,b.get('limits',policy(cfg))['task_requests']-b.get('application_requests',0)),
   'question_requests':b.get('question_requests',{}),'observed_internal_steps':b.get('observed_internal_steps',0),
   'model_calls':meta.get('model_calls'),'model_calls_observability':meta.get('model_calls_observability','unobservable'),'seconds':round(time.monotonic()-started,3)}
  (taskdir/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))

def strip_fences(raw):
 text=raw.strip()
 if text.startswith('```json\n') and text.endswith('\n```'):return text[8:-4]
 if text.startswith('```\n') and text.endswith('\n```'):return text[4:-4]
 return text

def unique_pairs(pairs):
 result={}
 for key,value in pairs:
  if key in result:raise RequestFailure('JSON包含重复键：'+key,'structure')
  result[key]=value
 return result

def json_payload(raw):
 # Whole-document parsing only. Never hunt for a convenient pair of braces.
 return json.loads(strip_fences(raw),object_pairs_hook=unique_pairs)

def source_identity(payload):
 """Reliable identity + immutable source values; independent of model issues/types."""
 if not isinstance(payload,dict) or not isinstance(payload.get('questions'),list):raise RequestFailure('原返回无法可靠识别候选清单，保留证据待恢复','structure')
 result=[]
 def values(x):
  if isinstance(x,dict):return {k:values(v) for k,v in x.items() if k not in ['kind']}
  if isinstance(x,list):return [values(v) for v in x]
  return x
 for q in payload['questions']:
  if not isinstance(q,dict) or not isinstance(q.get('original_number'),str) or not isinstance(q.get('stem'),list):raise RequestFailure('原返回无法可靠识别候选题，保留证据待恢复','structure')
  fields={k:q.get(k) for k in ['original_number','pages','stem','options','subquestions','original_answer','original_explanation']}
  result.append(values(fields))
 return result

def assert_identity(before,after):
 if source_identity(before)!=source_identity(after):raise RequestFailure('格式修复改变候选题身份、源内容或图片映射，未采用','identity')

# --- Bounded, semantics-preserving JSON syntax repair (extraction only) ---

def _string_mask(text):
 """True at positions inside a string literal; the opening quote stays outside."""
 mask=[False]*len(text);inside=False;i=0
 while i<len(text):
  char=text[i]
  if not inside:
   if char=='"':inside=True
   i+=1;continue
  mask[i]=True
  if char=='\\' and i+1<len(text):mask[i+1]=True;i+=2;continue
  if char=='"':inside=False
  i+=1
 return mask

def _sub_outside_strings(pattern,replacement,text):
 """Apply a rule only when its match starts outside any string literal."""
 mask=_string_mask(text);count=0
 def apply(match):
  nonlocal count
  if mask[match.start()]:return match.group(0)
  count+=1;return match.expand(replacement)
 return pattern.subn(apply,text)[0],count

def _tokens_survive_deduplication(before,after):
 """after must equal before with only exact duplicate tokens dropped."""
 if before is None:return False
 index=0;last=None
 for token in after:
  while index<len(before) and before[index]!=token:
   if before[index]!=last:return False
   index+=1
  if index>=len(before):return False
  last=token;index+=1
 while index<len(before):
  if before[index]!=last:return False
  index+=1
 return True

_DUPLICATED_TRIPLE=re.compile(r'("(?:[^"\\]|\\.)*")\s*,\s*\1\s*,\s*\1\s*:')
_DUPLICATED_KEY=re.compile(r'("(?:[^"\\]|\\.)*")\s*\1\s*:')
_TRAILING_COMMA=re.compile(r',(\s*[}\]])')
_LEADING_COMMA=re.compile(r'([{\[])(\s*),')
_DOUBLE_COLON=re.compile(r':(\s*):')

def repair_json_syntax(raw):
 """Fix only unambiguous JSON syntax slips; never guesses content.

 Returns (repaired_text, applied_rules) when the result parses as JSON,
 otherwise (None, applied_rules). Rules are global, deterministic, applied
 strictly outside string literals, and only remove duplicate tokens or
 redundant separators, so no value can be rewritten or reinterpreted:
   - duplicated key token triple: "X","X","X": -> "X","X":
   - duplicated identical string token before a colon: "X" "X": -> "X":
   - trailing comma before a closing brace/bracket
   - leading comma right after an opening brace/bracket
   - doubled colon
 The repaired text is accepted only when it parses and its token stream is
 the original stream minus exact adjacent duplicates (content fingerprint).
 """
 text=strip_fences(raw);applied=[]
 before=content_tokens(text)
 if before is None:return None,applied
 for _ in range(10):
  changed=False
  # Observed live corruption: "X","X","X":  (duplicated key token triple) -> "X","X":
  # Never matches valid JSON: a value+key pair is "X","X": (no third token).
  text,n=_sub_outside_strings(_DUPLICATED_TRIPLE,r'\1,\1:',text)
  if n:applied.append('duplicated-key-token-triple:x'+str(n));changed=True
  # Duplicated identical string token immediately before a colon: "X" "X": -> "X":
  text,n=_sub_outside_strings(_DUPLICATED_KEY,r'\1:',text)
  if n:applied.append('duplicate-string-token-before-colon:x'+str(n));changed=True
  text,n=_sub_outside_strings(_TRAILING_COMMA,r'\1',text)
  if n:applied.append('trailing-comma:x'+str(n));changed=True
  text,n=_sub_outside_strings(_LEADING_COMMA,r'\1\2',text)
  if n:applied.append('leading-comma:x'+str(n));changed=True
  text,n=_sub_outside_strings(_DOUBLE_COLON,r':\1',text)
  if n:applied.append('double-colon:x'+str(n));changed=True
  if not changed:break
 try:
  json.loads(text,object_pairs_hook=unique_pairs)
 except ValueError:
  return None,applied
 if not _tokens_survive_deduplication(before,content_tokens(text)):
  return None,applied+['content-token-check-failed']
 return text,applied

_STRING=re.compile(r'"(?:[^"\\]|\\.)*"')
_NUMBER=re.compile(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?')
_LITERAL=re.compile(r'\b(?:true|false|null)\b')

def content_tokens(raw):
 """Ordered string/number/literal tokens for content fingerprinting.

 Returns None when a string literal is unterminated (truncation). The token
 stream is used to prove that a syntax repair did not add, drop, rename or
 rewrite any piece of content.
 """
 text=strip_fences(raw);out=[];i=0;n=len(text)
 while i<n:
  c=text[i]
  if c=='"':
   m=_STRING.match(text,i)
   if not m:return None
   out.append(m.group(0));i=m.end();continue
  if c in ' \t\r\n':i+=1;continue
  if c=='-' or c.isdigit():
   m=_NUMBER.match(text,i)
   if m:out.append(m.group(0));i=m.end();continue
   i+=1;continue
  if text.startswith(('true','false','null'),i):
   m=_LITERAL.match(text,i)
   if m:out.append(m.group(0));i=m.end();continue
  i+=1
 return out

def question_number_anchors(raw):
 return re.findall(r'"original_number"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',strip_fences(raw))

def structural_balance(raw):
 """True when all braces/brackets outside strings are matched and nested.

 A truncated document usually fails this check even when it happens to end
 with a closing bracket; such output must not be handed to a model for
 "syntax repair" because that would require inventing closing structure.
 """
 text=strip_fences(raw);stack=[];inside=False;i=0
 while i<len(text):
  char=text[i]
  if inside:
   if char=='\\' and i+1<len(text):i+=2;continue
   if char=='"':inside=False
   i+=1;continue
  if char=='"':inside=True
  elif char in '{[':stack.append(char)
  elif char in '}]':
   if not stack or (stack.pop()=='{')!=(char=='}'):return False
  i+=1
 return not stack and not inside
