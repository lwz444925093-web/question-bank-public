"""Do not add a second label when a part already starts with that label.

Only explicit text markers qualify. No source text or math is removed.
"""
import re


def _key(label):
    label = str(label or '').strip().translate(str.maketrans('（）．', '().'))
    if re.fullmatch(r'[①-⑳]', label):
        return str(ord(label) - ord('①') + 1)
    match = re.fullmatch(r'\((\d+)\)|(\d+)[.、]?|([A-H])[.、)]?', label)
    return next((value for value in match.groups() if value is not None), None) if match else None


def part_display_label(part):
    """Preserve original body markers, adding only an absent external label."""
    label = str(part.get('label') or '')
    blocks = part.get('blocks') or []
    if not blocks or blocks[0].get('kind') != 'paragraph':
        return label
    text = ''
    for span in blocks[0].get('spans', []):
        if span.get('kind') != 'text':
            break
        text += span.get('text', '')
    # A bare leading digit/letter may be question content. Require parentheses,
    # a circled number, or punctuation, with a prose/space boundary afterwards.
    match = re.match(r'^\s*([①-⑳]|(?:[（(]\d+[）)]|\d+[.．、]|[A-H][.．、)）])(?=$|\s|[\u3400-\u9fff]))', text)
    key = _key(label)
    return '' if key is not None and match and _key(match[1]) == key else label
