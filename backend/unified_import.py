"""One public import route; source format chooses only the input adapter."""
from pathlib import Path
from zipfile import BadZipFile
from . import inputs,tasks,d_import

VISUAL={'.pdf','.png','.jpg','.jpeg'}
SUPPORTED=VISUAL|{'.txt','.docx'}

def submit(raw,name,subject='数学',start=1,end=0,selected_pages=None,request_id=None,generate_solution=None,request_profile=None,light_review=None):
    if subject not in ['数学','物理']:raise ValueError('不支持的学科')
    ext=Path(name).suffix.lower()
    if ext not in SUPPORTED:raise ValueError('支持 PDF、PNG、JPG、JPEG、Word DOCX、TXT；旧版 DOC 请先另存为 DOCX')
    if light_review is not None and type(light_review) is not bool:raise ValueError('轻量审查开关必须为布尔值')
    if generate_solution is not None and type(generate_solution) is not bool:raise ValueError('答案解析开关必须为布尔值')
    if ext in VISUAL and light_review is not None:
        request_profile='pure_d_light_review_v1' if light_review else 'pure_d_page_overview_v1'
    if ext in VISUAL:
        options={}
        if generate_solution is not None:options['generate_solution']=generate_solution
        if request_profile is not None:options['request_profile']=request_profile
        return d_import.submit(raw,name,subject,start,end,selected_pages=selected_pages,request_id=request_id,**options)
    if ext!='.docx' and generate_solution is False:raise ValueError("当前答案开关支持 PDF、图像和 Word 导入")
    try:bundle=inputs.prepare(raw,name,start,end,selected_pages=selected_pages)
    except BadZipFile as exc:raise ValueError('Word 文件损坏或不是有效的 DOCX，请重新另存为 DOCX') from exc
    bundle['subject']=subject
    # Native Word stays a direct source copy. Additional services are opt-in,
    # and omitted/false flags retain the historical fast path and its identity.
    if ext=='.docx' and (light_review is True or generate_solution is True):
        bundle['native_services']=dict(light_review=light_review is True,generate_solution=generate_solution is True)
    if request_id:bundle['remaining_request']=request_id
    return tasks.submit(bundle)
