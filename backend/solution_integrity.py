"""Readable answer content checks shared by generation and manual adoption."""

def has_content(blocks):
    def spans_content(spans):
        return any(s.get('kind') in ['text','math'] and str(s.get('text') or '').strip() for s in spans)
    for block in blocks or []:
        kind=block.get('kind')
        if kind=='equation' and str(block.get('latex') or '').strip():return True
        if kind=='paragraph' and spans_content(block.get('spans',[])):return True
        if kind=='table' and any(spans_content(cell) for row in block.get('rows',[]) for cell in row):return True
    return False


def solution_complete(solution,status,fields=('answer','explanation')):
    return status in ['ready','needs_review'] and all(has_content(solution.get(field,[])) for field in fields)
