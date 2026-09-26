"""Promote only explicit numeric probability distributions, never math matrices."""
import re
from fractions import Fraction


def number(value):
    value=value.strip()
    if re.fullmatch(r'[+-]?\d+(?:\.\d+)?',value):return Fraction(value)
    match=re.fullmatch(r'\\(?:d?frac)\{([+-]?\d+)\}\{([1-9]\d*)\}',value)
    if match:return Fraction(int(match[1]),int(match[2]))
    raise ValueError('not a numeric cell')


def probability_array(latex, context):
    if not ('随机变量' in context and '分布' in context):return None
    match=re.fullmatch(r'\s*\\begin\{array\}\{([lcr|]+)\}([\s\S]*?)\\end\{array\}\s*',latex)
    if not match or r'\hline' not in match[2]:return None
    rows=[[v.strip() for v in row.split('&')] for row in match[2].replace(r'\hline','').split(r'\\')]
    columns=sum(c in 'lcr' for c in match[1])
    if not (len(rows)==2 and 2<=columns<=20 and all(len(row)==columns for row in rows)):return None
    if not re.fullmatch(r'[A-Za-z]|\\(?:xi|eta|zeta)',rows[0][0]) or rows[1][0]!='P':return None
    try:
        values=[number(v) for v in rows[0][1:]]
        probabilities=[number(v) for v in rows[1][1:]]
    except ValueError:return None
    if len(set(values))!=len(values) or any(p<0 or p>1 for p in probabilities) or sum(probabilities)!=1:return None
    return [[[dict(kind='math',text=value)] for value in row] for row in rows]


def normalize_probability_tables(blocks):
    changed=False;replacement=[]
    for block in blocks:
        if block.get('kind')!='paragraph':replacement.append(block);continue
        context=''.join(s.get('text','') for s in block.get('spans',[]) if s.get('kind')=='text')
        run=[]
        for span in block.get('spans',[]):
            rows=probability_array(span.get('text',''),context) if span.get('kind')=='math' else None
            if rows is None:run.append(span);continue
            if run:replacement.append(dict(block,spans=run));run=[]
            replacement.append(dict(kind='table',spans=[],rows=rows,latex='',shapes=[],asset=''));changed=True
        if run:replacement.append(dict(block,spans=run))
        elif not block.get('spans'):replacement.append(block)
    if changed:blocks[:]=replacement
    return changed
