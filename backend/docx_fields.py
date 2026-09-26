"""Read-only static EQ field conversion; never evaluate Word fields or OLE."""
import re
from lxml import etree
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M='http://schemas.openxmlformats.org/officeDocument/2006/math'


def element(name,*children,**attrs):
    node=etree.Element('{'+M+'}'+name)
    for key,value in attrs.items():node.set('{'+M+'}'+key,value)
    node.extend(children);return node


def text(char):
    node=element('t');node.text=char;return element('r',node)


def _argument_chars(chars):
    """Split parentheses at top level while preserving every run's sub/sup flag."""
    parts=[[]];depth=0
    for char,style in chars:
        if char=='(' :depth+=1
        if char==')':depth-=1
        if depth<0:raise ValueError('EQ括号不匹配')
        if char==',' and depth==0:parts.append([])
        else:parts[-1].append((char,style))
    if depth:raise ValueError('EQ括号不匹配')
    return parts


def expression(chars):
    nodes=[];i=0
    while i<len(chars):
        char,style=chars[i]
        if char=='\\':
            start=i+1
            while start<len(chars) and chars[start][0].isspace():start+=1
            if start>=len(chars):raise ValueError('EQ操作符缺失')
            op=chars[start][0].lower();begin=start+1
            while begin<len(chars) and chars[begin][0].isspace():begin+=1
            aligned=op=='o' and ''.join(c for c,_ in chars[begin:begin+3]).lower()=='\\al'
            if aligned:
                begin+=3
                while begin<len(chars) and chars[begin][0].isspace():begin+=1
            if op not in ['f','r','o'] or begin>=len(chars) or chars[begin][0]!='(':raise ValueError('EQ操作符尚未支持')
            end=begin+1;depth=1
            while end<len(chars) and depth:
                if chars[end][0]=='(':depth+=1
                elif chars[end][0]==')':depth-=1
                end+=1
            if depth:raise ValueError('EQ括号不匹配')
            args=_argument_chars(chars[begin+1:end-1])
            if op=='f' and len(args)==2 and all(args):
                atom=element('f',element('num',*expression(args[0])),element('den',*expression(args[1])))
            elif op=='r' and len(args) in [1,2] and all(args):
                degree=[] if len(args)==1 else expression(args[0]);radicand=expression(args[-1])
                atom=element('rad',element('radPr',element('degHide',val='1' if not degree else '0')),element('deg',*degree),element('e',*radicand))
            elif op=='o' and aligned and len(args)==2 and all(args):
                # Nuclear notation: the source explicitly overlays superscript
                # and subscript digits before the following element symbol.
                upper=[(c,s) for c,s in args[0] if not c.isspace()]
                lower=[(c,s) for c,s in args[1] if not c.isspace()]
                if not upper or not lower or not all(c.isdigit() and s=='superscript' for c,s in upper) or not all(c.isdigit() and s=='subscript' for c,s in lower):raise ValueError('EQ叠加上下标尚未支持')
                atom=element('sSubSup',element('e'),element('sub',*[text(c) for c,_ in lower]),element('sup',*[text(c) for c,_ in upper]))
            elif op=='o' and not aligned and len(args)==2 and args[0]:
                overlay=''.join(c for c,_ in args[1])
                # This specific EQ overlay is a static overbar. Other overlays
                # are not guessed from text, nor converted to a different symbol.
                if not re.fullmatch(r'\s*\\s\s*\\up[1-9]\d*\(\s*[－−―—-]\s*\)\s*',overlay,re.I):raise ValueError('EQ叠加符号尚未支持')
                atom=element('bar',element('barPr',element('pos',val='top')),element('e',*expression(args[0])))
            else:raise ValueError('EQ参数不完整')
            nodes.append(atom);i=end;continue
        if char.isspace():i+=1;continue
        if char in ',':raise ValueError('EQ参数分隔符位置不明确')
        if style in ['subscript','superscript']:
            if not nodes:raise ValueError('EQ上下标缺少主体')
            script=[]
            while i<len(chars) and chars[i][1]==style:
                if chars[i][0] in '\\(),':break
                script.append(text(chars[i][0]));i+=1
            if not script:raise ValueError('EQ上下标格式不明确')
            nodes.append(element('sSub' if style=='subscript' else 'sSup',element('e',nodes.pop()),element('sub' if style=='subscript' else 'sup',*script)))
            continue
        nodes.append(text(char));i+=1
    if not nodes:raise ValueError('EQ内容为空')
    return nodes


def convert_field(chars):
    code=''.join(c for c,_ in chars);match=re.match(r'\s*EQ\s+',code,re.I)
    if not match:raise ValueError('不是静态EQ域')
    return element('oMath',*expression(chars[match.end():])),code


def restore_eq_fields(root):
    records=[]
    # Simple fields contain their instruction in an attribute, not visible runs.
    for field in list(root.xpath('//*[local-name()="fldSimple"]')):
        code=field.get('{'+W+'}instr','')
        if not re.match(r'\s*EQ\b',code,re.I):continue
        math,code=convert_field([(c,'') for c in code]);field.getparent().replace(field,math);records.append(code)
    for paragraph in root.xpath('//*[local-name()="p"]'):
        children=list(paragraph);i=0
        while i<len(children):
            run=children[i];begins=run.xpath('./w:fldChar[@w:fldCharType="begin"]',namespaces={'w':W})
            if not begins:i+=1;continue
            j=i+1;depth=1;chars=[];separated=False;nested=False
            while j<len(children) and depth:
                child=children[j]
                for mark in child.xpath('./w:fldChar',namespaces={'w':W}):
                    kind=mark.get('{'+W+'}fldCharType')
                    if kind=='begin':depth+=1;nested=True
                    elif kind=='end':depth-=1
                    elif kind=='separate':separated=True
                if not separated:
                    align=child.xpath('./w:rPr/w:vertAlign/@w:val',namespaces={'w':W})
                    for value in child.xpath('./w:instrText/text()',namespaces={'w':W}):chars.extend((c,align[0] if align else '') for c in value)
                j+=1
            code=''.join(c for c,_ in chars)
            if re.match(r'\s*EQ\b',code,re.I):
                if depth or nested:raise ValueError('Word旧公式域不完整或含嵌套域，未丢弃公式')
                # Never discard adjacent visible content in a mixed boundary run.
                if run.xpath('./w:t',namespaces={'w':W}) or children[j-1].xpath('./w:t',namespaces={'w':W}):raise ValueError('Word旧公式域边界不明确，未丢弃正文')
                try:math,code=convert_field(chars)
                except ValueError as exc:raise ValueError('Word旧公式尚无法完整读取，原文件已保留：'+str(exc)) from exc
                at=paragraph.index(run)
                for old in children[i:j]:paragraph.remove(old)
                paragraph.insert(at,math);records.append(code)
            i=j
    # An instruction outside a well-formed field must not vanish into Pandoc.
    if any(re.match(r'\s*EQ\b',s,re.I) for s in root.xpath('//*[local-name()="instrText"]/text()')):
        raise ValueError('Word旧公式域边界无法读取，未丢弃公式')
    return records
