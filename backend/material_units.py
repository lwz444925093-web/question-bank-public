"""Safe, explicit numbered TXT boundaries; ambiguous/shared material stays unsplit."""
import re,hashlib,copy
VERSION='numbered-txt-v1'
def plan(bundle,size=8):
 text=bundle.get('text','')
 if bundle.get('original','').lower().endswith('.txt') and not bundle.get('images'):
  matches=list(re.finditer(r'(?m)^\s*(\d{1,3})[.．、](?!\d)\s*',text))
  numbers=[int(m[1]) for m in matches]
  reliable=len(matches)>size and len(set(numbers))==len(numbers) and numbers==sorted(numbers)
  if reliable and not re.search(r'阅读.{0,8}材料|根据上述|共用.{0,6}材料|回答.{0,5}[～~至].{0,5}题',text):
   result=[];context=text[:matches[0].start()]
   for start in range(0,len(matches),size):
    stop=min(start+size,len(matches));left=matches[start].start();right=matches[stop].start() if stop<len(matches) else len(text)
    unit=copy.deepcopy(bundle);unit['text']=context+text[left:right];unit['source_range']=dict(start=left,end=right,numbers=numbers[start:stop],algorithm=VERSION)
    unit['unit_id']=hashlib.sha256((VERSION+str(left)+':'+str(right)+text[left:right]).encode()).hexdigest()[:16]
    result.append(unit)
   return result
 return [bundle]
