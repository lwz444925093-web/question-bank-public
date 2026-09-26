import React from 'react';
export function NativeEquation({span,source}:any){return <img className="native-inline-equation" alt="原文公式" src={'/api/source/'+source?.id+'/'+encodeURIComponent(span.text)} style={{width:(span.width||12)/12+'em',height:(span.height||12)/12+'em'}}/>}
