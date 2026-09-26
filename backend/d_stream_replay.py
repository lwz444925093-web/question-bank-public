"""Conservative local replay after removing an unchanged orphan or renaming carry IDs.
Never reuses a response when new semantic context was added.
"""
import copy,json

def same_fragment(a,b):
 return all(a.get(k)==b.get(k) for k in ['question_id','source_pages','question_text','options','subquestions','requires_image'])

def project(old,new,output):
 old=copy.deepcopy(old);new=copy.deepcopy(new)
 for m in [old,new]:m.pop('request_context',None)
 before=old.pop('carry_forward',[]);after=new.pop('carry_forward',[])
 old_assets=old.pop('asset_catalog',[]);new_assets=new.pop('asset_catalog',[])
 if old!=new:return None
 mapping={};used=set()
 def semantic(c):return {k:v for k,v in c.items() if k not in ['carry_id','saved_id']}
 for c in after:
  matches=[(i,b) for i,b in enumerate(before) if i not in used and semantic(b)==semantic(c)]
  if len(matches)!=1:return None
  i,b=matches[0];used.add(i);mapping[b['carry_id']]=c['carry_id']
 removed=[b for i,b in enumerate(before) if i not in used]
 ids={a['asset_id'] for a in new_assets};extras={a['asset_id'] for a in old_assets}-ids
 if [a for a in old_assets if a['asset_id'] in ids]!=new_assets:return None
 out=copy.deepcopy(output);kept=[];pruned=set()
 for q in out['questions']:
  related=[c for c in removed if q.get('continuation_of')==c['carry_id'] or q['question_id']==c['question']['question_id']]
  if related:
   if q.get('context_closed') or not all(same_fragment(q,c['question']) for c in related):return None
   if set(q['source_pages'])&set(new['source_pages']):return None
   pruned.add(q['question_id']);continue
  q['continuation_of']=mapping.get(q.get('continuation_of'),q.get('continuation_of'));kept.append(q)
 if pruned&{q['question_id'] for q in kept}:return None
 for link in out['asset_assignments']:
  if link['question_id'] in pruned and link['asset_id'] not in extras:return None
  if link['asset_id'] in extras and link['question_id'] is not None and link['question_id'] not in pruned:return None
 out['questions']=kept
 out['asset_assignments']=[a for a in out['asset_assignments'] if a['asset_id'] in ids]
 return dict(output=out,removed_unchanged_orphans=sorted(pruned),carry_id_mapping=mapping)
