import React,{useEffect,useState} from 'react';
export function ImportPreview({file}:{file:File}){
 const [url,U]=useState(''),[text,T]=useState(''),[doc,D]=useState<any>(null),[error,E]=useState(''),[loading,L]=useState(true);
 useEffect(()=>{
  const previewBlob=/\.pdf$/i.test(file.name)?file.slice(0,file.size,'application/pdf'):file;
  const url=URL.createObjectURL(previewBlob),controller=new AbortController();U(url);T('');D(null);E('');L(true);
  if(/\.txt$/i.test(file.name))file.text().then(t=>{if(!controller.signal.aborted){T(t);L(false)}}).catch(()=>{if(!controller.signal.aborted){E('文字暂时无法读取，请关闭后重新打开。');L(false)}});
  if(/\.docx$/i.test(file.name)){
   const data=new FormData();data.append('file',file);
   fetch('/api/import/preview',{method:'POST',body:data,signal:controller.signal}).then(async r=>{
    const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Word 预览暂时无法读取，请关闭后重新打开。');
    if(!controller.signal.aborted){D(d);L(false)}
   }).catch(e=>{if(!controller.signal.aborted){E(e.message==='Failed to fetch'?'连接中断，请关闭后重新打开文件。':e.message);L(false)}});
  }
  return()=>{controller.abort();URL.revokeObjectURL(url)};
 },[file]);
 return <div className="import-file-preview"><h2>{file.name}</h2>{error?<p role="alert">{error}</p>:/\.pdf$/i.test(file.name)?<iframe title="PDF 文件预览" src={url}/>:/\.(png|jpe?g)$/i.test(file.name)?<img alt={file.name} src={url}/>: /\.txt$/i.test(file.name)?loading?<p role="status">正在读取文字…</p>:text?<pre>{text}</pre>:<p>此文件没有文字内容。</p>:/\.docx$/i.test(file.name)?loading?<p role="status">正在读取 Word 预览…</p>:doc?.html?<div className="native-word-preview question-content" dangerouslySetInnerHTML={{__html:doc.html}}/>:<p>此文件没有可预览的内容。</p>:<p>此格式暂不支持预览。</p>}</div>;
}
