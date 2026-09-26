import React from 'react';
import {sourcePictureUrl} from './SourcePicture';
export function SourceLink({source}:any){
 const file=source?.file||'',name=source?.display_name||file,url=sourcePictureUrl(source?.id,file);
 if(!url)return <small className="question-source">来源：原件未提供</small>;
 const ext=file.split('.').pop()?.toUpperCase()||'文件';
 return <a className="question-source" href={url} target="_blank" rel="noopener noreferrer" onClick={e=>e.stopPropagation()} title={'打开来源：'+name} aria-label={'打开来源：'+name}><span>来源：</span><span className="source-filename">{name}</span><svg width="29" height="33" viewBox="0 0 32 36" role="img" aria-label={ext+' 文件'}><path d="M5 1h15l8 8v25H5z" fill="white" stroke="currentColor"/><path d="M20 1v9h8" fill="none" stroke="currentColor"/><rect x="0" y="16" width="31" height="13" rx="2" fill={ext==='PDF'?'#c94848':'#376ba6'}/><text x="15.5" y="25" textAnchor="middle" fill="white" fontSize="8" fontFamily="Arial">{ext}</text></svg></a>;
}
