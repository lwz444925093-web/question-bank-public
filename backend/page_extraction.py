"""Explicit page completion, independent of figure postprocessing and question counts."""
def completed(result,bundle):
    requested=set(bundle.get('pages',[])); rows=result.get('page_extractions',[])
    counts={p:sum(p in q.get('pages',[]) for q in result.get('questions',[])) for p in requested}
    done=[];empty=[]
    for row in rows:
        p=row.get('page');n=row.get('question_count')
        if p not in requested or sum(x.get('page')==p for x in rows)!=1:continue
        if type(n) is not int or n!=counts[p]:continue
        if row.get('status')=='no_questions' and n==0:done.append(p);empty.append(p)
        elif row.get('status')=='complete' and n>0:done.append(p)
    return dict(completed_pages=sorted(done),empty_pages=sorted(empty),basis='explicit-page-report-v1')

def recorded(task,total=None):
    from .material_catalog import pages
    record=task.get('page_extraction') or {}
    if record.get('basis')!='explicit-page-report-v1':return set()
    return pages(record.get('completed_pages'),total)&pages(task.get('bundle',{}).get('pages'),total)
