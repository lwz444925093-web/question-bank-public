"""Conservative, lossless native Word import for explicit question documents.

This is a source adapter, not an OCR or solving model. Unsupported layouts return
an explicit reason and retain the existing model route with the original assets.
"""
import copy
import hashlib
import json
import re
import time
from pathlib import Path
from collections import Counter

from .model import Extracted
from .docx_lecture import prepare_lecture

VERSION = 'native-numbered-docx-v5-lecture-boundaries'
ASSET = re.compile(r'WORDASSET(\d+)END')
NUMBER = re.compile(r'^\s*(?:(?P<simple>[A-Za-z]?\d{1,4})[.．、](?!\d)|[【\[]?(?P<example>(?:例|例题|练习|变式)\s*\d{1,3})[】\]]?\s*[：:.．、]?)\s*')
OPTION = re.compile(r'(?<!\S)([A-H])(?:[.．]|、(?![A-Za-z]))\s*')
SUBQUESTION = re.compile(r'^\s*([（(]\s*\d{1,2}\s*[)）])\s*')
ANSWER = re.compile(r'^\s*(?:【(?P<bracket>答案|解析|分析|解答)】|(?P<plain>答案|解析|分析|解答)\s*[：:])\s*')
SECTION = re.compile(r'^(?:[一二三四五六七八九十]+[、．.]|第[ⅠⅡⅢIVX一二三四五六七八九十\d]+[卷部分]|知识点\s*\d)')


class Unsupported(ValueError):
    pass


def block(kind='paragraph', **fields):
    return dict(kind=kind, spans=fields.get('spans', []), latex=fields.get('latex', ''),
                rows=fields.get('rows', []), shapes=[], asset=fields.get('asset', ''))


def merge_spans(spans):
    result = []
    for span in spans:
        if not span['text']:
            continue
        if result and result[-1]['kind'] == span['kind'] == 'text':
            result[-1]['text'] += span['text']
        else:
            result.append(dict(span))
    return result


def native_math(value):
    # Pandoc can retain an empty-base OMML superscript inside the actual
    # degree exponent. MathLive then emits an invalid one-child <msup>.
    # Remove only this redundant wrapper, preserving the angle and its value.
    return re.sub(r'\^\{\s*\{\s*\^\s*\\circ\s*\}\s*\}', lambda match: r'^{\circ}', value)


def normalize_word_scripts(ast):
    """Turn explicit letter subscripts into math without guessing plain text.

    The copied AST is the source of both extraction and conservation counts.
    Unsupported bases remain untouched and follow the existing safe fallback.
    """
    def detach_letter(node):
        if node.get('t') == 'Str':
            match = re.search(r'(?<![A-Za-z])([A-Z]{2,4}|[A-Za-z])$', node['c'])
            if match:
                prefix = node['c'][:match.start()]
                return (dict(t='Str', c=prefix) if prefix else None), match[1]
        if node.get('t') in ('Emph', 'Strong', 'Underline') and node['c']:
            remaining, base = detach_letter(node['c'][-1])
            if base:
                items = node['c'][:-1] + ([remaining] if remaining else [])
                return (dict(node, c=items) if items else None), base
        return node, None

    def visit(value):
        if isinstance(value, dict):
            return {k: visit(v) if k == 'c' else copy.deepcopy(v) for k, v in value.items()}
        if not isinstance(value, list): return value
        output = []
        for original in value:
            node = visit(original)
            if isinstance(node, dict) and node.get('t') in ('Superscript', 'Subscript'):
                parts = node.get('c', [])
                text = ''.join(p.get('c', '') for p in parts if p.get('t') == 'Str')
                text = text.translate(str.maketrans({'－': '-', '–': '-', '−': '-', '﹣': '-'}))
                if parts and all(p.get('t') == 'Str' for p in parts):
                    node['c'] = [dict(t='Str', c=text)]
                    if re.fullmatch(r'[A-Za-z0-9.+\-=()]+', text) and re.search('[A-Za-z.]', text) and output:
                        remaining, base = detach_letter(output[-1]) if isinstance(output[-1], dict) else (None, None)
                        if base:
                            output.pop()
                            if remaining: output.append(remaining)
                            marker = '^' if node['t'] == 'Superscript' else '_'
                            if len(base) > 1: base = r'\mathrm{' + base + '}'
                            node = dict(t='Math', c=[dict(t='InlineMath'), base + marker + '{' + text + '}'])
            output.append(node)
        return output
    return dict(ast, blocks=visit(ast['blocks']))


def inline_spans(inlines):
    result = []
    for item in inlines:
        kind, content = item['t'], item.get('c')
        if kind == 'Str': result.append(dict(kind='text', text=content))
        elif kind in ('Space', 'SoftBreak'): result.append(dict(kind='text', text=' '))
        elif kind == 'LineBreak': result.append(dict(kind='text', text='\n'))
        elif kind == 'Image':
            attrs=dict(content[0][2]);asset=content[2][0]
            if attrs.get('data-native-equation')!='1' or not re.fullmatch(r'docx-(?:native5-)?image-\d+\.png',asset):raise Unsupported('未识别的行内图片')
            result.append(dict(kind='image',text=asset,width=float(attrs['width']),height=float(attrs['height'])))
        elif kind == 'Math': result.append(dict(kind='math', text=native_math(content[1])))
        elif kind in ('Strong', 'Emph', 'Underline', 'Strikeout', 'SmallCaps'):
            result.extend(inline_spans(content))
        elif kind in ('Span', 'Link'):
            result.extend(inline_spans(content[1]))
        elif kind in ('Superscript', 'Subscript'):
            value = ''.join(s['text'] for s in inline_spans(content))
            if not re.fullmatch(r'[0-9+\-=()]+', value):
                raise Unsupported('存在需要保留排版的特殊上下标')
            alphabet = '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾' if kind == 'Superscript' else '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎'
            result.append(dict(kind='text', text=value.translate(str.maketrans('0123456789+-=()', alphabet))))
        elif kind == 'Quoted':
            result.append(dict(kind='text', text='“'))
            result.extend(inline_spans(content[1])); result.append(dict(kind='text', text='”'))
        else:
            raise Unsupported('存在暂不支持直接复制的 Word 元素：' + kind)
    return merge_spans(result)


def slice_spans(spans, start=0, end=None):
    """Offsets count source characters, preserving every untouched math span."""
    end = sum(len(s['text']) for s in spans) if end is None else end
    result, offset = [], 0
    for span in spans:
        left, right = max(0, start-offset), min(len(span['text']), end-offset)
        if left < right:
            if span['kind'] in ('math','image') and (left != 0 or right != len(span['text'])):
                raise Unsupported('题号或选项边界与公式相交')
            result.append(dict(span, text=span['text'][left:right]))
        offset += len(span['text'])
    return merge_spans(result)


def paragraphs(inlines, assets):
    spans = inline_spans(inlines)
    result, pending = [], []
    # Image sentinels are replaced inside text spans, never guessed from OCR.
    for span in spans:
        if span['kind'] != 'text': pending.append(span); continue
        cursor = 0
        for match in ASSET.finditer(span['text']):
            pending.extend([dict(kind='text', text=span['text'][cursor:match.start()])])
            if any(s['text'].strip() for s in pending):
                result.append(block(spans=merge_spans(pending)))
            pending = []
            index = int(match[1])
            if index >= len(assets): raise Unsupported('图片标记未对应源文件')
            result.append(block('image', asset=assets[index])); cursor = match.end()
        pending.append(dict(kind='text', text=span['text'][cursor:]))
    if any(s['text'].strip() for s in pending): result.append(block(spans=merge_spans(pending)))
    return result


def cell_blocks(cell, assets):
    if cell[2:4] != [1, 1]: raise Unsupported('表格含合并单元格，需保留原表关系')
    return convert_blocks(cell[4], assets)


def table_rows(node, assets):
    content = node['c']
    if content[1][1]: raise Unsupported('表格附有独立标题')
    source_rows = content[3][1] + [r for body in content[4] for r in body[2]+body[3]] + content[5][1]
    return [[cell_blocks(cell, assets) for cell in row[1]] for row in source_rows]


def convert_blocks(nodes, assets):
    result = []
    for node in nodes:
        kind, content = node['t'], node.get('c')
        if kind in ('Para', 'Plain'): result.extend(paragraphs(content, assets))
        elif kind == 'BlockQuote': result.extend(convert_blocks(content, assets))
        elif kind == 'Table': result.extend(convert_table(node, assets))
        else: raise Unsupported('单元格或正文含复杂布局：' + kind)
    return result


def convert_table(node, assets):
    rows = table_rows(node, assets)
    # A single row used to place content next to a picture has no row/column
    # value matrix. Preserve cell reading order and keep side illustrations in
    # the question stem; rectangular data tables remain editable table blocks.
    if len(rows) == 1 and any(b['kind'] in ('image', 'source_table') for cell in rows[0] for b in cell):
        result = []
        for cell in rows[0]:
            has_options = any(option_parts(b) for b in cell)
            for item in cell:
                result.append(dict(item, _force_stem=not has_options))
        return result
    return [dict(kind='source_table', rows=rows)]


def plain(b):
    return ''.join(s['text'] for s in b.get('spans', [])) if b['kind'] == 'paragraph' else ''


def strip_prefix(b, match):
    return dict(b, spans=slice_spans(b['spans'], match.end()))


def nonempty(b):
    return b['kind'] != 'paragraph' or any(s['text'].strip() for s in b['spans'])


def option_parts(b):
    if b['kind'] != 'paragraph': return None
    text = plain(b); matches = list(OPTION.finditer(text))
    if not matches or text[:matches[0].start()].strip(): return None
    parts = []
    for index, match in enumerate(matches):
        right = matches[index+1].start() if index+1 < len(matches) else len(text)
        item = block(spans=slice_spans(b['spans'], match.end(), right))
        parts.append(dict(label=match[1], blocks=[item] if nonempty(item) else []))
    return parts


def equipment_list(question):
    """A source-declared equipment inventory is shared experimental context."""
    text = '\n'.join(plain(b) for b in question['stem'])
    return bool(re.search(r'(?:现有|提供|给定|所用).{0,45}器材|器材.{0,15}(?:可选|选用|供选择)', text))


def table_block(rows):
    output = []
    for row in rows:
        cells = []
        for blocks in row:
            spans = []
            for index, item in enumerate(blocks):
                if item['kind'] != 'paragraph': raise Unsupported('表格中包含图片或嵌套元素')
                if index: spans.append(dict(kind='text', text='\n'))
                spans.extend(item['spans'])
            cells.append(merge_spans(spans))
        output.append(cells)
    if not output or not output[0] or len({len(r) for r in output}) != 1:
        raise Unsupported('表格不是完整矩形')
    return block('table', rows=output)


def new_question(number, subject, section):
    return dict(original_number=number, subject=subject, grade='', question_type='未分类',
                knowledge=[], difficulty='未标注', stem=[], options=[], subquestions=[],
                original_answer=[], original_explanation=[], ai_answer=[], ai_explanation=[],
                pitfalls=[], issues=[], pages=[], review_notes=['原生 Word 本地复制；未调用模型生成答案或知识点'] + (['原文章节：'+section] if section else []),
                review_tags=[], source_regions=[])


def parse_ast(ast, assets, subject='数学', legacy_previews=0, source_issues=None):
    """Return a safe complete result, or a structured fallback reason."""
    started = time.monotonic()
    try:
        if legacy_previews: raise Unsupported('含 MathType 旧公式预览，需要识别后恢复行内公式')
        if source_issues: raise Unsupported('；'.join(source_issues))
        ast = normalize_word_scripts(ast)
        questions, current, section, destination, in_instructions = [], None, '', None, False
        numbers, copied_assets, copied_formulas = set(), [], []
        source_items = []; retained_intro = []; in_theory = False; seen_question_heading = False
        lecture = prepare_lecture(ast['blocks'])
        input_nodes = lecture.blocks if lecture else ast['blocks']
        if lecture: retained_intro.extend(lecture.retained)
        exam_intro=not lecture and any(re.search(r'高考|高等学校招生.*考试',json.dumps(n,ensure_ascii=False)) for n in ast['blocks'][:3])
        intro_end=next((i for i,n in enumerate(ast['blocks']) if n['t'] in ('Para','Plain') and SECTION.match(''.join(x['text'] for x in inline_spans(n['c']))) and re.search('选择|单选|多选|填空|解答',json.dumps(n,ensure_ascii=False))),0) if exam_intro else 0
        exam_instructions=False
        for node_index,node in enumerate(input_nodes):
            if node.get('_lecture_number'):
                source_items.append(dict(kind='section', text=node['_lecture_section']))
                inlines = node['c'][2] if node['t'] == 'Header' else node['c']
                converted = paragraphs(inlines, assets)
                if not converted or converted[0]['kind'] != 'paragraph':
                    raise Unsupported('讲义题号没有明确正文')
                converted[0]['_lecture_number'] = node['_lecture_number']
                converted[0]['_lecture_prefix_end'] = node['_lecture_prefix_end']
                source_items.extend(converted)
                continue
            if node_index<intro_end:retained_intro.append(node);continue
            intro_text=''.join(s['text'] for s in inline_spans(node['c'])) if node['t'] in ('Para','Plain') else ''
            if exam_intro and intro_text.strip() in ('注意事项：','注意事项:'):
                exam_instructions=True
            if exam_instructions:
                if SECTION.match(intro_text):exam_instructions=False
                else:retained_intro.append(node);continue
            heading_text = ''.join(s['text'] for s in inline_spans(node['c'][2])) if node['t'] == 'Header' else ''
            heading_question = re.fullmatch(r'(.*?)\s*题\s*(\d{1,3})\s*', heading_text)
            if heading_text.strip() == '知识梳理':
                if seen_question_heading:raise Unsupported('题目之间夹有知识讲解，需核对材料边界')
                in_theory = True
            paragraph_text = ''.join(s['text'] for s in inline_spans(node['c'])) if node['t'] in ('Para','Plain') else ''
            if NUMBER.match(paragraph_text) or node['t']=='OrderedList':
                if in_theory:raise Unsupported('知识梳理中含编号内容，需核对是否为练习题')
                seen_question_heading = True
            if heading_question:
                in_theory = False; seen_question_heading = True
                source_items.append(dict(kind='section', text=heading_question[1]))
                source_items.append(block(spans=[dict(kind='text', text=heading_question[2]+'. ')]))
                continue
            if in_theory:
                retained_intro.append(node); continue
            if node['t'] == 'Header':
                text = ''.join(s['text'] for s in inline_spans(node['c'][2]))
                # Numbered headings can themselves be question starts.
                if NUMBER.match(text): source_items.extend(paragraphs(node['c'][2], assets))
                else: source_items.append({'kind':'section', 'text':text})
            elif node['t'] == 'Table': source_items.extend(convert_table(node, assets))
            elif node['t'] == 'OrderedList':
                attrs, items = node['c']
                if attrs[1]['t'] != 'Decimal' or attrs[2]['t'] not in ('Period','DefaultDelim'):
                    raise Unsupported('存在不能确定题号层级的自动编号')
                for number, item in enumerate(items, attrs[0]):
                    converted = convert_blocks(item, assets)
                    if not converted or converted[0]['kind'] != 'paragraph': raise Unsupported('自动编号没有明确正文')
                    converted[0]['spans'].insert(0, dict(kind='text', text=str(number)+'. '))
                    source_items.extend(converted)
            elif node['t'] == 'BlockQuote': source_items.extend(convert_blocks(node['c'], assets))
            else: source_items.extend(convert_blocks([node], assets))
        for item in source_items:
            kind, text = item['kind'], plain(item)
            force_stem = item.pop('_force_stem', False)
            if re.search(r'【[^】]*第\s*\d+\s*题】', text): raise Unsupported('存在带来源名称的题号，需要核对题目边界')
            # A drawing can split "11. 造型[image]可以做成…" immediately
            # after 造型. Only an explicit 题型 label is a section heading;
            # a question fragment ending in 型 must retain its number.
            if re.fullmatch(r'\s*\d+[.．、]\s*(?:题型[^。；：]{0,12}|[^。；：]{1,10}题型)\s*', text):
                section=text; continue
            if kind == 'section' or (text and SECTION.match(text) and len(text) < 130):
                section = item.get('text', text); in_instructions = False
                continue
            if text.strip() in ('说明：','说明:', '注意事项：','注意事项:') and not current:
                in_instructions = True; continue
            if in_instructions and not current:
                # Exam instructions must end in a visible section heading.
                continue
            match = NUMBER.match(text)
            lecture_number = item.pop('_lecture_number', None)
            lecture_prefix_end = item.pop('_lecture_prefix_end', None)
            if match or lecture_number:
                number = lecture_number or re.sub(r'\s+', '', match['simple'] or match['example'])
                if number in numbers: raise Unsupported('题号重复，可能含多个章节或文末答案')
                numbers.add(number); current = new_question(number, subject, section); questions.append(current)
                destination = current['stem']
                item = dict(item, spans=slice_spans(item['spans'], lecture_prefix_end)) if lecture_number else strip_prefix(item, match)
                text = plain(item)
                if '填空' in section: current['question_type'] = '填空题'
                elif any(s in section for s in ('解答','计算','证明','实验')): current['question_type'] = '解答题'
            if current is None:
                # Only a short, explicit document heading may be omitted. Unknown
                # preamble can contain shared material, so it must take the fallback.
                compact = re.sub(r'\s+', '', text)
                if kind == 'paragraph' and len(compact) < 100 and re.search(r'(试题|试卷|笔试|测试|练习题|考试时间|满分)', compact): continue
                if kind == 'paragraph' and not text.strip(): continue
                raise Unsupported('首题前含共享材料或讲义内容，无法确定适用范围')
            if force_stem: destination=current['stem']
            if kind == 'source_table':
                cells = [cell for row in item['rows'] for cell in row]
                parts = []
                for cell in cells:
                    first = option_parts(cell[0]) if cell else None
                    if not first or len(first) != 1: parts = []; break
                    parts.append(dict(label=first[0]['label'], blocks=first[0]['blocks']+cell[1:]))
                if parts and destination is current['stem'] and not equipment_list(current) and ''.join(p['label'] for p in parts) == 'ABCDEFGH'[:len(parts)]:
                    current['options'].extend(parts); destination = current['options'][-1]['blocks']
                else: destination.append(table_block(item['rows']))
                continue
            answer = ANSWER.match(text)
            if answer:
                label = answer['bracket'] or answer['plain']
                target='original_answer' if label == '答案' else 'original_explanation'
                if current[target]: raise Unsupported('同一题出现重复答案或解析标记，需核对是否漏分题')
                destination = current['original_answer' if label == '答案' else 'original_explanation']
                item = strip_prefix(item, answer); text = plain(item)
            elif destination is not current['original_answer'] and destination is not current['original_explanation']:
                parts = option_parts(item)
                sub = SUBQUESTION.match(text)
                if parts and not current['subquestions'] and not equipment_list(current):
                    current['options'].extend(parts); destination = current['options'][-1]['blocks']; continue
                if sub:
                    part = dict(label=sub[1], blocks=[]); current['subquestions'].append(part)
                    destination = part['blocks']; item = strip_prefix(item, sub)
            if nonempty(item): destination.append(item)
        if not questions: raise Unsupported('没有找到明确的题号')
        for q in questions:
            if not q['stem'] and not q['subquestions']: raise Unsupported('题号后缺少正文')
            labels = ''.join(p['label'] for p in q['options'])
            if labels and (len(labels) < 2 or labels != 'ABCDEFGH'[:len(labels)]):
                raise Unsupported('第 '+q['original_number']+' 题选项编号不完整或重复：'+labels)
            if labels:
                explicit_multiple = re.match(r'^\s*[（(]\s*多选\s*[)）]', plain(q['stem'][0])) if q['stem'] else None
                q['question_type'] = '多选题' if explicit_multiple or '多项' in '\n'.join(q['review_notes']) else '选择题'
            elif q['subquestions'] and q['question_type'] == '未分类': q['question_type'] = '解答题'
            groups = [q[k] for k in ('stem','original_answer','original_explanation')]
            groups += [p['blocks'] for p in q['options']+q['subquestions']]
            for group in groups:
                for b in group:
                    if b['kind'] == 'image': copied_assets.append(b['asset'])
                    copied_assets.extend(s['text'] for s in b['spans'] if s['kind']=='image')
                    copied_assets.extend(s['text'] for row in b['rows'] for cell in row for s in cell if s['kind']=='image')
                    formulas = [s['text'] for s in b['spans'] if s['kind'] == 'math']
                    formulas += [s['text'] for row in b['rows'] for cell in row for s in cell if s['kind'] == 'math']
                    from .exporter import math_xml
                    for formula in formulas: math_xml(formula)
                    copied_formulas.extend(formulas)
            Extracted.model_validate(q)
        intro_image_list=[assets[int(m[1])] for m in ASSET.finditer(json.dumps(retained_intro, ensure_ascii=False))]
        def inline_images(value):
            if isinstance(value,dict):
                if value.get('t')=='Image':return [value['c'][2][0]]
                return inline_images(value.get('c',[]))
            if isinstance(value,list):return [a for x in value for a in inline_images(x)]
            return []
        intro_image_list+=inline_images(retained_intro)
        intro_assets=set(intro_image_list)
        copied_assets_expected=inline_images(ast['blocks'])
        source_image_list=[assets[int(m[1])] for m in ASSET.finditer(json.dumps(ast['blocks'], ensure_ascii=False))]
        source_image_list+=copied_assets_expected
        def math_values(value):
            if isinstance(value,dict):
                if value.get('t')=='Math':return [native_math(value['c'][1])]
                return math_values(value.get('c',[]))
            if isinstance(value,list):return [formula for item in value for formula in math_values(item)]
            return []
        if Counter(copied_formulas)+Counter(math_values(retained_intro))!=Counter(math_values(ast['blocks'])):
            raise Unsupported('公式数量或内容未完整对应到题目，保留原文待核对')
        if Counter(copied_assets)+Counter(intro_image_list)!=Counter(source_image_list):
            raise Unsupported('图片出现次数未完整对应到题目，保留原图待核对')
        if set(copied_assets) | intro_assets != set(assets): raise Unsupported('存在尚未归属到题目的图片，未丢弃源图')
        return dict(eligible=True, version=VERSION, seconds=round(time.monotonic()-started, 4),
                    question_count=len(questions), retained_non_question_blocks=len(retained_intro), retained_non_question_assets=sorted(intro_assets), source_math_count=len(math_values(ast['blocks'])), question_math_count=len(copied_formulas), source_image_occurrences=len(source_image_list), question_image_occurrences=len(copied_assets), result=dict(schema_version='1.0', questions=questions, page_extractions=[]))
    except (Unsupported, ValueError, KeyError, IndexError, TypeError) as exc:
        return dict(eligible=False, version=VERSION, reason=str(exc)[:250], seconds=round(time.monotonic()-started, 4))


class LocalProvider:
    def __init__(self, config=None): self.config = config or {}
    def key(self, bundle):
        identity=copy.deepcopy(bundle)
        # Cache hit flags and wall-clock measurements do not change the source.
        identity.get('docx_extraction',{}).pop('cached',None)
        identity.get('docx_local',{}).pop('seconds',None)
        return hashlib.sha256(json.dumps([VERSION, identity], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def parse(self, bundle, taskdir, cancel=None, progress=None):
        native = bundle.get('docx_local') or {}
        if not native.get('eligible'): raise ValueError('Word 本地分题没有通过完整性检查')
        if cancel and cancel.is_set(): raise ValueError('任务已取消')
        if progress: progress('Word 正在读取正文和表格，检查是否需要恢复可编辑公式')
        result = copy.deepcopy(native['result'])
        for q in result['questions']: q['subject'] = bundle.get('subject', '数学')
        from .docx_editable import spans,convert
        if any(spans(result)):
            return convert(result,bundle,Path(taskdir)/'editable-equations',cancel,progress)
        return result, dict(provider='local', model=VERSION, seconds=0 if bundle.get('docx_extraction',{}).get('cached') else native['seconds'],
                            extraction_seconds=native['seconds'], application_requests=0, cost='¥0（本地读取）',
                            cost_estimate=dict(amount=0, currency='CNY', basis='local-no-api'))


def source_excerpt(q):
    """Immutable native source for later answer generation/source comparison."""
    def spans(values):
        return ''.join('$'+s['text']+'$' if s['kind']=='math' else '![]('+s['text']+')' if s['kind']=='image' else s['text'] for s in values)
    def render(blocks):
        lines=[]
        for b in blocks:
            if b['kind']=='paragraph':lines.append(spans(b['spans']))
            elif b['kind']=='image':lines.append('![]('+b['asset']+')')
            elif b['kind']=='equation':lines.append('$$'+b['latex']+'$$')
            elif b['kind']=='table':lines.extend('| '+' | '.join(spans(cell) for cell in row)+' |' for row in b['rows'])
        return '\n\n'.join(lines)
    lines=[q['original_number']+'. '+render(q['stem'])]
    lines.extend(p['label']+' '+render(p['blocks']) for p in q['options']+q['subquestions'])
    for name,label in [('original_answer','原文答案'),('original_explanation','原文解析')]:
        if q.get(name):lines.append(label+'：'+render(q[name]))
    return '\n\n'.join(lines)
