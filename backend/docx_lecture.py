"""Explicit lecture boundaries, with no inference from page layout or models.

Annotations preserve the source AST and its formula/image conservation checks.
Question identity uses the printed group and number, never its running position.
"""
import copy
import re
from dataclasses import dataclass


HEADINGS = {'学习目标', '思维导图', '知识梳理', '题型精讲', '强化训练'}
LABELED = re.compile(r'^\s*【(?P<group>典型例题|对点训练)\s*(?P<number>\d{1,3})】\s*')
NUMBERED = re.compile(r'^\s*(?P<number>\d{1,3})[.．、](?!\d)\s*')
CONTEXTUAL_NUMBER = re.compile(r'^\s*(?P<number>\d{1,3})(?:[.．、]|\s+)\s*')
TYPE_HEADING = re.compile(r'^\s*【题型[一二三四五六七八九十\d]+】[^。；]{0,80}\s*$')
PRACTICE_HEADINGS = {'【基础强化】', '【素养提升】', '【能力培优】'}


def node_text(node):
    """Read only paragraph/header text; tables cannot become fake headings."""
    if node['t'] == 'BlockQuote' and len(node['c']) == 1:
        return node_text(node['c'][0])
    if node['t'] not in ('Para', 'Plain', 'Header'):
        return ''
    inlines = node['c'][2] if node['t'] == 'Header' else node['c']

    def text(value):
        if isinstance(value, list):
            return ''.join(text(v) for v in value)
        if not isinstance(value, dict):
            return ''
        kind, content = value['t'], value.get('c')
        if kind == 'Str': return content
        if kind in ('Space', 'SoftBreak', 'LineBreak'): return ' '
        if kind in ('Math', 'Image'): return '\ufffc'
        if kind in ('Span', 'Link'): return text(content[1])
        return text(content)
    return text(inlines)


def heading(node):
    text = re.sub(r'WORDASSET\d+END', '', node_text(node))
    text = re.sub(r'[\s0-9０-９]', '', text)
    return text if text in HEADINGS else ''


def blank(node):
    return node['t'] in ('Para', 'Plain') and not node.get('c')


@dataclass
class LecturePlan:
    blocks: list
    retained: list


def prepare_lecture(nodes):
    """Activate only for an ordered, explicit theory/examples/practice layout.

    Other Word documents retain their existing conservative parser. Ambiguous
    sections or numbering cause a fallback, rather than partial adoption.
    """
    headings = [(i, heading(n)) for i, n in enumerate(nodes) if heading(n)]
    positions = {name: [i for i, h in headings if h == name] for name in HEADINGS}
    if not all(positions[name] for name in ('知识梳理', '题型精讲', '强化训练')):
        return None
    if any(len(positions[name]) != 1 for name in ('题型精讲', '强化训练')):
        raise ValueError('讲义包含重复训练章节，需核对题目边界')
    examples, practice = positions['题型精讲'][0], positions['强化训练'][0]
    if not max(positions['知识梳理']) < examples < practice:
        raise ValueError('讲义章节顺序不明确，需核对知识点和练习范围')

    kept, retained = [], []
    counts = {'典型例题': 0, '对点训练': 0, '强化训练': 0}
    section, has_question = '题型精讲', False
    for index, source in enumerate(nodes):
        text, label = node_text(source), heading(source)
        if index <= examples:
            retained.append(source)
            continue
        if label:
            if label != '强化训练':
                raise ValueError('练习中夹有其他讲义章节，需核对材料边界')
            retained.append(source)
            section, has_question = '强化训练', False
            continue
        if index < practice and TYPE_HEADING.fullmatch(text):
            retained.append(source)
            section, has_question = text.strip(), False
            continue
        if index > practice and text.strip() in PRACTICE_HEADINGS:
            retained.append(source)
            section, has_question = '强化训练 · ' + text.strip('【】 '), False
            continue
        match = LABELED.match(text) if index < practice else NUMBERED.match(text)
        if index >= practice and not match:
            candidate = CONTEXTUAL_NUMBER.match(text)
            if candidate and int(candidate['number']) == counts['强化训练'] + 1:
                # A year/quantity after the delimiter, or a missing delimiter
                # (Word whitespace may have collapsed to one space),
                # is accepted only inside the explicit practice section, in
                # sequence, with a question cue and a following numbered item.
                following = next((m for n in nodes[index+1:]
                                  if (m := CONTEXTUAL_NUMBER.match(node_text(n)))), None)
                cue = re.search(r'[?？＿_]|[（(]\s*[)）]|下列|求证|求|判断', text[candidate.end():])
                if cue:
                    if not following or int(following['number']) != int(candidate['number']) + 1:
                        raise ValueError('强化训练题号边界不明确，未合并到上一题')
                    match = candidate
        if match:
            group = match['group'] if index < practice else '强化训练'
            number = int(match['number'])
            if number != counts[group] + 1:
                raise ValueError(f'{group}题号不连续或重复：期望{counts[group]+1}，实际{number}')
            counts[group] = number
            node = copy.deepcopy(source)
            node['_lecture_number'] = group + str(number)
            node['_lecture_prefix_end'] = match.end()
            node['_lecture_section'] = section
            kept.append(node)
            has_question = True
        elif not has_question:
            if blank(source) or (source['t'] in ('Para', 'Plain') and not text.strip()):
                retained.append(source)
            else:
                raise ValueError('讲义练习前含未确定归属的材料，未作为知识点丢弃')
        else:
            kept.append(copy.deepcopy(source))
    if not all(counts.values()):
        raise ValueError('讲义练习分组不完整，需核对原文')
    return LecturePlan(kept, retained)
