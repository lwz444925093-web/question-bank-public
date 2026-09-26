"""Conservative E recovery promoted without any candidate/evaluation runtime."""
import json,re
from pydantic import ValidationError
from .d_contract import Output, Question, Assignment, Page

def unique(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError('duplicate JSON key: '+k)
        out[k]=v
    return out

def escape_math_strings(text):
    """Repair single backslashes only inside explicit, matched LaTeX delimiters.

    Handle the whole formula: JSON accepts \\f and \\t but would silently turn
    frac/times into control characters. Already escaped pairs stay untouched.
    """
    strings=re.compile(r'"(?:\\.|[^"\\])*"',re.S)
    math=re.compile(r'(?<!\\)\\\(.*?(?<!\\)\\\)|(?<!\\)\\\[.*?(?<!\\)\\\]',re.S)
    def formula(match):
        return re.sub(r'\\+.',lambda m: m[0] if len(m[0][:-1])%2==0 or m[0][-1]=='"' else '\\'+m[0],match[0],flags=re.S)
    return strings.sub(lambda m:math.sub(formula,m[0]),text)

def repair_syntax(raw):
    text=raw.strip();edits=[]
    if text.startswith('```') and text.endswith('```'):
        text=text[text.find('\n')+1:-3].strip();edits.append('remove_code_fence')
    escaped=escape_math_strings(text)
    if escaped!=text:text=escaped;edits.append('escape_latex_math_backslashes')
    # Strip external prose only if exactly one independently valid JSON object exists.
    if not text.startswith('{'):
        start=text.find('{')
        if start>=0:
            try:
                value,end=json.JSONDecoder(object_pairs_hook=unique).raw_decode(text,start)
                if isinstance(value,dict) and not any(c in text[end:] for c in '{}[]'):
                    text=text[start:end];edits.append('remove_external_text')
            except ValueError:pass
    else:
        try:
            _,end=json.JSONDecoder(object_pairs_hook=unique).raw_decode(text)
            if text[end:].strip() and not any(c in text[end:] for c in '{}[]'):
                text=text[:end];edits.append('remove_external_text')
        except ValueError:pass
    output=[];stack=[];quoted=False;escaped=False
    for i,c in enumerate(text):
        if quoted:
            output.append(c)
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
        elif c=='"':quoted=True;output.append(c)
        elif c in '{[':stack.append(c);output.append(c)
        elif c in '}]':
            if not stack or stack[-1]!={'}':'{',']':'['}[c]:return text,edits+['ambiguous_no_repair']
            stack.pop();output.append(c)
        elif c==',' and text[i+1:].lstrip().startswith(('}',']')):edits.append('remove_trailing_comma')
        elif c==')' and text[i+1:].lstrip().startswith(('}',']')):edits.append('remove_non_json_closing_parenthesis')
        else:output.append(c)
    if not quoted and stack:
        output.extend('}' if c=='{' else ']' for c in reversed(stack));edits.append('append_missing_closers')
    return ''.join(output),edits

def array_objects(raw,key):
    depth=0;i=0;decoder=json.JSONDecoder(object_pairs_hook=unique)
    while i<len(raw):
        c=raw[i]
        if c=='"':
            try:value,end=decoder.raw_decode(raw,i)
            except ValueError:return
            j=end
            while j<len(raw) and raw[j].isspace():j+=1
            if depth==1 and value==key and raw[j:j+1]==':':
                j+=1
                while j<len(raw) and raw[j].isspace():j+=1
                if raw[j:j+1]!='[':return
                i=j+1
                while i<len(raw):
                    while i<len(raw) and (raw[i].isspace() or raw[i]==','):i+=1
                    if raw[i:i+1]==']':return
                    try:value,i=decoder.raw_decode(raw,i)
                    except ValueError:return
                    if isinstance(value,dict):yield value
                return
            i=end;continue
        if c in '{[':depth+=1
        elif c in '}]':depth-=1
        i+=1

def recover(raw):
    errors=[];repaired,edits=repair_syntax(raw)
    for label,text in [('raw_success',raw),('repaired',repaired)]:
        try:return dict(status=label,output=Output.model_validate(json.loads(text,object_pairs_hook=unique)).model_dump(),edits=[] if label=='raw_success' else edits)
        except (ValueError,ValidationError) as exc:errors.append(str(exc)[:1000])
    output={}
    for key,model in [('questions',Question),('asset_assignments',Assignment),('page_extractions',Page)]:
        output[key]=[]
        for value in array_objects(repaired,key):
            try:output[key].append(model.model_validate(value).model_dump())
            except ValidationError:pass
    output['issues']=['schema_partial_recovery']
    return dict(status='partial' if output['questions'] else 'unrecoverable',output=output,edits=edits,errors=errors)
