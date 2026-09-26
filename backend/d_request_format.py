"""Opt-in historical envelope/overview request construction; no task semantics."""
import base64,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

FORMAT='historical_envelope_overview_v1'

def overview(original,output):
    original=Path(original)
    source=next((p for p in original.parents if (p/'result.json').exists()),None)
    if source is None:raise ValueError('Missing frozen Region result for overview')
    result=json.loads((source/'result.json').read_text())
    if (source/result['page']['original']).resolve()!=original.resolve():raise ValueError('Overview source mismatch')
    regions=result['regions']
    with Image.open(original) as src:im=src.convert('RGB')
    w,h=im.size;canvas=Image.new('RGB',(w+600,max(h,len(regions)*24+70)),'white');canvas.paste(im,(0,0))
    d=ImageDraw.Draw(canvas);font=ImageFont.truetype('/System/Library/Fonts/Monaco.ttf',13)
    colors={'text':'#2563eb','figure_candidate':'#d93a43','table':'#00885a','unknown':'#b1832d','raster_group':'#765ab0','raster_page_parent':'#765ab0'}
    for i,r in enumerate(regions):
        b=r['safe_pixel_bbox'];color=colors[r['type']];label='R'+str(r['reading_order_hint']).zfill(2)
        d.rectangle(b,outline=color,width=2)
        d.rectangle([b[0],max(0,b[1]-17),b[0]+38,max(0,b[1]-17)+17],fill='white')
        d.text((b[0],max(0,b[1]-17)),label,font=font,fill=color)
        d.text((w+12,35+i*24),label+' '+r['region_id'],font=font,fill=color)
    d.text((w+12,10),'Display label -> exact existing region_id',font=font,fill='black')
    # Overview is layout guidance only; full-resolution original stays untouched.
    canvas.thumbnail((3072,3072),Image.Resampling.LANCZOS)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);canvas.save(output)
    return output

def historical_payload(material,images,folder,prompt,schema):
    if len(images)!=len(material['pages'])+len(material['asset_catalog']):raise ValueError('Request image count mismatch')
    content=[];manifest=[];folder=Path(folder)
    def attach(path,kind,page=None,asset_id=None):
        path=Path(path)
        content.extend([{'type':'text','text':'Called the Read tool with the following input: '+json.dumps({'filePath':str(path)},ensure_ascii=False,separators=(',',':'))},
                        {'type':'text','text':'Image read successfully'},
                        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()}}])
        manifest.append(dict(kind=kind,page=page,asset_id=asset_id,path=str(path)))
    for p,path in zip(material['pages'],images):
        attach(path,'original_full_page',page=p['page'])
        attach(overview(path,folder/'request-inputs'/('page-'+str(p['page']))/'overview.png'),'region_overview',page=p['page'])
    for a,path in zip(material['asset_catalog'],images[len(material['pages']):]):attach(path,'fixed_asset',asset_id=a['asset_id'])
    content.append({'type':'text','text':prompt+'\nSchema:'+json.dumps(schema,ensure_ascii=False)+'\n\n'+json.dumps(material,ensure_ascii=False)})
    system=Path(__file__).with_name('d_historical_envelope.txt').read_text()
    return dict(model='deepseek-flash',messages=[dict(role='system',content=system),dict(role='user',content=content)],reasoning_effort='low',stream=False),manifest
