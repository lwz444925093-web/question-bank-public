import {plainCalculation} from './plainCalculation';
import React from 'react';
import {Formula} from './Formula';

// Render standalone coordinate variables with the same math font as fractions.
// Leave words, geometry labels and units untouched.
function prose(text:string):React.ReactNode {
 const pieces:React.ReactNode[]=[];let cursor=0;
 for(const match of text.matchAll(/(?<![A-Za-z\\])[xy](?![A-Za-z])/g)){
  const start=match.index!;pieces.push(text.slice(cursor,start));
  pieces.push(<Formula key={'variable-'+start} value={match[0]}/>);cursor=start+1;
 }
 pieces.push(text.slice(cursor));return <>{pieces}</>;
}
// Recover explicit TeX left in a text span without interpreting ordinary prose.
export function InlineText({text}:{text:string}) {
  const calc=text.match(/^(.*?计算[：:]\s*)([^；;。]+)([；;。]?)$/);
  if(calc){const latex=plainCalculation(calc[2]);if(latex)return <>{calc[1]}<Formula value={latex}/>{calc[3]}</>;}
  const pattern = /\\begin\{cases\}[\s\S]*?\\end\{cases\}|\$([^$\n]+)\$|\\\((.+?)\\\)|[A-Za-z0-9=+*/^_{}(). -]*\\(?:cdot|times|dfrac|tfrac|frac|sqrt|sin|cos|tan|angle|rho|eta|alpha|beta|theta|Delta|pi|div|pm|leq|geq)(?![A-Za-z])[A-Za-z0-9\\=+*/^_{}().<>∠≤≥≠° -]*|[A-Za-z0-9{}().+*/= -]*[A-Za-z][_^](?:\{[^{}]+\}|[0-9]+)[A-Za-z0-9_^{}().+*/= -]*/g;
  const parts:React.ReactNode[]=[];
  let cursor=0;
  for (const match of text.matchAll(pattern)) {
    const start=match.index!;
    if(start>cursor) parts.push(prose(text.slice(cursor,start)));
    let value=match[1]??match[2]??match[0].trim();
    if(value.startsWith('\\begin{cases}'))value=value.replace(/[,，]\s*(?=\\\\)/g,'');
    parts.push(<Formula key={start} value={value}/>);
    cursor=start+match[0].length;
  }
  if(cursor<text.length) parts.push(prose(text.slice(cursor)));
  return <>{parts}</>;
}
