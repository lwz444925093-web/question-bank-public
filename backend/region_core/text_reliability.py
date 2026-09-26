"""Local Unicode/font-mapping signals. Geometry survives unreliable semantics."""
import unicodedata
from collections import Counter


def assess_text(objects,possible_ocr=False):
    texts=[o['text'] for o in objects if o['kind']=='text'];text=''.join(texts)
    chars=[c for c in text if not c.isspace()];n=len(chars)
    counts=Counter()
    for c in chars:
        code=ord(c);cat=unicodedata.category(c)
        counts['control']+=cat in ('Cc','Cf','Cs')
        counts['replacement_private']+=c=='\ufffd' or cat=='Co'
        counts['suspicious_latin1']+=(0x80<=code<=0xbf and c not in '°±²³µ·¹¼½¾©®')
        counts['reasonable']+=(c.isalnum() or cat.startswith(('P','S')) or c in '°′″') and not ((0x80<=code<=0xbf and c not in '°±²³µ·¹¼½¾©®') or cat=='Co')
    bad=(counts['control']+counts['replacement_private']+counts['suspicious_latin1'])/max(n,1)
    printable=sum(c.isprintable() for c in chars)/max(n,1)
    repetition=max(Counter(chars).values(),default=0)/max(n,1)
    reliable=bool(n) and bad<.035 and printable>.97 and not (n>50 and repetition>.55) and not possible_ocr
    warnings=[]
    if not n:warnings.append('no native text geometry; no OCR attempted')
    if bad>=.035 or printable<=.97:warnings.append('encoding/control/private-use anomaly; strings excluded from semantic attachment rules')
    if possible_ocr:warnings.append('text over a dominant raster may be OCR; semantics treated conservatively')
    return dict(text_geometry_available=bool(n),text_semantics_reliable=reliable,
                method='Unicode heuristics, not OCR or language recognition',character_count=n,
                abnormal_ratio=bad,printable_ratio=printable,reasonable_ratio=counts['reasonable']/max(n,1),
                dominant_character_ratio=repetition,counts=dict(counts),warnings=warnings)
