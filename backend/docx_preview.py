"""Safe native DOCX flow preview: paragraphs, tables, inline formulas and images."""
import json,subprocess,re
from lxml import etree,html
import pypandoc

def render(bundle):
    ast=bundle.get('preview_ast')
    if not ast:raise ValueError('Word预览结构缺失，请重新读取文件')
    def pictures(value):
        if isinstance(value,list):
            out=[]
            for item in value:
                if isinstance(item,dict) and item.get('t')=='Str':
                    text=item['c'];cursor=0
                    for m in re.finditer(r'WORDASSET(\d+)END',text):
                        if m.start()>cursor:out.append({'t':'Str','c':text[cursor:m.start()]})
                        out.append({'t':'Image','c':[['',[],[]],[],[bundle['assets'][int(m[1])],'']]});cursor=m.end()
                    if cursor:
                        if cursor<len(text):out.append({'t':'Str','c':text[cursor:]})
                    else:out.append(item)
                else:out.append(pictures(item))
            return out
        if isinstance(value,dict):return {k:pictures(v) for k,v in value.items()}
        return value
    ast=pictures(ast)
    proc=subprocess.run([pypandoc.get_pandoc_path(),'-f','json','-t','html','--mathml'],input=json.dumps(ast).encode(),capture_output=True,timeout=30)
    if proc.returncode:raise ValueError('Word网页预览生成失败')
    root=html.fragment_fromstring(proc.stdout.decode(),create_parent='div')
    allowed=set('div p span strong em u s sup sub table caption thead tbody tfoot tr td th colgroup col ol ul li h1 h2 h3 h4 h5 h6 br img math semantics annotation mrow mi mn mo mtext mspace mfrac msqrt mroot msub msup msubsup munder mover munderover mtable mtr mtd mfenced mpadded mstyle menclose'.split())
    assets=set(bundle['assets'])
    for node in list(root.iter()):
        tag=etree.QName(node).localname if isinstance(node.tag,str) else ''
        if tag not in allowed:
            if tag in ('script','style','iframe','object'):node.drop_tree()
            else:node.drop_tag()
            continue
        old=dict(node.attrib);node.attrib.clear()
        if tag=='img':
            asset=old.get('src','')
            if asset not in assets:node.drop_tree();continue
            node.set('src','/api/source/'+bundle['source_id']+'/'+asset)
            if old.get('data-native-equation')=='1':
                node.set('class','native-inline-equation');node.set('alt','原文公式')
                width=float(old['width']);height=float(old['height'])
                node.set('style',f'width:{width/12}em;height:{height/12}em')
            else:node.set('class','native-word-picture');node.set('alt','原文题图')
        elif tag in ('td','th'):
            for key in ('colspan','rowspan'):
                if old.get(key,'').isdigit():node.set(key,old[key])
        elif tag=='ol' and old.get('start','').isdigit():node.set('start',old['start'])
        elif tag=='math':node.set('xmlns','http://www.w3.org/1998/Math/MathML')
        elif tag in ('mo','mstyle','mspace','mover','munder','munderover'):
            for key in ('stretchy','accent','accentunder','displaystyle','scriptlevel','width'):
                if key in old and len(old[key])<25:node.set(key,old[key])
    return etree.tostring(root,encoding='unicode',method='html')
