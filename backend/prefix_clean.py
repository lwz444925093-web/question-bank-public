"""Conservative, local and reversible display-prefix derivation; never edits sources."""
import copy,hashlib,json,re
VERSION='prefix-v3'
FIELDS=['stem','options','subquestions','figure_records']
def digest(q):
 return hashlib.sha256(json.dumps({k:q.get(k,[]) for k in FIELDS},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
_HEADING = re.compile(r'^(?:第[一二三四五六七八九十ⅠⅡⅢⅣIVX１２３４1234]+卷(?:[（(][^()（）]*[）)])?|[一二三四五六七八九十]+[、.．](?:单项选择题|多项选择题|选择题|填空题|解答题|计算题|证明题|实验题|综合题)(?:[（(][^()（）]*[）)])?)$')

def clean_exam_headings(q):
    blocks=q.get('stem',[])
    count=0
    for block in blocks:
        spans=block.get('spans',[])
        if block.get('kind')!='paragraph' or not spans or any(s.get('kind')!='text' for s in spans):break
        text=''.join(s.get('text','') for s in spans)
        if not _HEADING.fullmatch(re.sub(r'\s+','',text)):break
        count+=1
    if not count or count==len(blocks):return False
    q['stem']=blocks[count:]
    records=[]
    for r in q.get('figure_records',[]):
        r=dict(r);match=re.fullmatch(r'stem/(\d+)',r.get('position',''))
        if match:r['position']='stem/'+str(int(match[1])-count)
        records.append(r)
    if 'figure_records' in q:q['figure_records']=records
    return True

def preview(q):
 result=copy.deepcopy(q);changes=[];metadata=[]
 if clean_exam_headings(result):
  changes.append(dict(position="stem",category="exam_heading",before=copy.deepcopy(q.get("stem",[])),after=copy.deepcopy(result["stem"])))
 groups=[('stem',result.get('stem',[]),False)]
 groups.extend(('subquestions/'+str(i)+'/blocks',part['blocks'],True) for i,part in enumerate(result.get('subquestions',[])))
 for location,blocks,subquestion in groups:
  if not blocks or blocks[0].get('kind')!='paragraph':continue
  spans=blocks[0]['spans'];prefix=''
  for span in spans:
   if span['kind']!='text':break
   prefix+=span['text']
  rest=prefix;removed=[]
  for _ in range(4):
   match=None;category=''
   if not subquestion:
    candidate=re.match(r'^\s*(\d{1,3})[．、.](?!\d)\s*',rest)
    number=str(q.get('original_number',''))
    labelled=re.fullmatch(r'(?:中考真题|典型习题|热身练习|练习|例题|例|问题)\s*(\d{1,3})',number)
    if candidate and candidate[1]==(labelled[1] if labelled else number):match=candidate;category='original_number'
   if not match:
    match=re.match(r'^\s*[（(](?:本小题|本题)?(?:满分)?\s*(\d+(?:\.\d+)?)\s*分[）)]\s*',rest);category='score'
   if not match and not subquestion:
    candidate=re.match(r'^\s*[【\[]([^】\]\n]{2,70})[】\]]\s*',rest)
    if candidate and re.search(r'中学|期中|期末|中考|高考|模拟|考试',candidate[1]) and not re.search(r'已知|求|计算|有\d|每',candidate[1]):match=candidate;category='source_label'
   if not match:break
   removed.append(dict(category=category,text=match[0],value=match[1],rule=VERSION,basis='题首明确编号/赋分括号/来源标签'))
   rest=rest[len(match[0]):]
  count=len(prefix)-len(rest)
  # Never erase the entire available paragraph: ambiguous empty content stays intact.
  if count and (rest.strip() or any(s.get('kind')!='text' and s.get('text','').strip() for s in spans)):
   remaining=count
   for index,span in enumerate(spans):
    if span['kind']!='text' or not remaining:break
    length=min(remaining,len(span['text']));span['text']=span['text'][length:];remaining-=length
   changes.append(dict(position=location+'/0',removed=removed,before=prefix,after=rest));metadata.extend(removed)
 if not changes:return dict(changed=False,question=result,changes=[])
 before={k:copy.deepcopy(q.get(k,[])) for k in FIELDS}
 result['prefix_cleaning']=dict(version=VERSION,baseline_revision=q.get('revision',0),before=before,before_hash=digest(q),after_hash=digest(result),changes=changes,metadata=metadata)
 return dict(changed=True,question=result,changes=changes)
def undo(q):
 record=q.get('prefix_cleaning')
 if not record:raise ValueError('本题没有可撤销的前缀清洗')
 if digest(q)!=record['after_hash']:raise ValueError('正文已修改，不能用旧清洗记录覆盖；请在历史版本中核对')
 result=copy.deepcopy(q);result.update(copy.deepcopy(record['before']));result.pop('prefix_cleaning',None)
 result.setdefault('prefix_cleaning_history',[]).append(dict(record,action='undo'))
 return result
