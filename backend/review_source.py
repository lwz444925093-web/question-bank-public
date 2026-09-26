"""Local original-document evidence for reviewing saved Word/TXT questions."""
import hashlib,json,re
from pathlib import Path


def assets_in(value):
    if isinstance(value,dict):
        if value.get('kind')=='image':
            asset=value.get('asset') or value.get('text')
            if asset:yield asset
        for child in value.values():yield from assets_in(child)
    elif isinstance(value,list):
        for child in value:yield from assets_in(child)


def source_context(q,folder):
    """Return only evidence actually retained from the input, never current text."""
    original=(Path(folder)/q['source'].get('file','')).resolve()
    if original.suffix.lower() not in ['.docx','.txt']:return None,[],[]
    if not original.is_relative_to(Path(folder).resolve()) or not original.is_file():
        return None,[],['原文件不可用，无法完成来源对照']
    digest=hashlib.sha256(original.read_bytes()).hexdigest()
    context=dict(original=original.name,source_sha256=digest)
    if original.suffix.lower()=='.txt':
        from .inputs import decode_text
        text=decode_text(original.read_bytes());number=str(q.get('original_number') or '').strip()
        headings=list(re.finditer(r'(?m)^\s*(\d+)[.．、]\s*',text))
        matches=[i for i,m in enumerate(headings) if m[1]==number]
        if len(matches)==1:
            i=matches[0];text=text[headings[i].start():headings[i+1].start() if i+1<len(headings) else len(text)]
        return dict(context,kind='original_text',scope='question' if len(matches)==1 else 'whole_file',text=text),[],[]
    cache=Path(folder)/'native-word-extraction.json'
    if cache.is_file():
        try:
            data=json.loads(cache.read_text())
            if data.get('source_sha256')!=digest:
                return None,[],['原文件已变化，需重新读取后再对照审查']
            if data.get('source_sha256')==digest:
                result=data.get('result',{});native=result.get('docx_local',{})
                matches=[row for row in native.get('result',{}).get('questions',[]) if str(row.get('original_number'))==str(q.get('original_number'))]
                if len(matches)==1:
                    row={k:matches[0].get(k,[]) for k in ['original_number','stem','options','subquestions']}
                    return dict(context,kind='native_word_structure',scope='question',question=row),list(dict.fromkeys(assets_in(row))),[]
                if result.get('text'):
                    text=result['text'];assets=list(dict.fromkeys(re.findall(r'!\[[^\]]*\]\(([^)]+)\)',text)))
                    return dict(context,kind='native_word_text',scope='whole_file',text=text),assets,[]
        except (ValueError,KeyError,TypeError):pass
    # Older native imports retained an excerpt, but not always the full local
    # extraction. Label its scope honestly instead of substituting edited text.
    if q.get('native_source_excerpt'):
        text=q['native_source_excerpt']
        assets=list(dict.fromkeys(re.findall(r'!\[[^\]]*\]\(([^)]+)\)',text)))
        return dict(context,kind='retained_source_excerpt',scope='question_excerpt',text=text,
            limitation='仅有导入时保留的原文片段，不能据此确认原文件范围内是否还存在遗漏'),assets,[]
    return None,[],['缺少可对照的 Word 原文，请重新读取原文件后再审查']
