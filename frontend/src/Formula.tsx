import {mathNotation} from './mathNotation';
import React from 'react';
import {readableMathML} from './readableMathML';
const cache=new Map<string,string>();
let cacheBytes=0;
function mathMarkup(value:string){
 const key=mathNotation(value);const old=cache.get(key);
 if(old!==undefined){cache.delete(key);cache.set(key,old);return old;}
 const markup=readableMathML(key);const bytes=2*(key.length+markup.length);
 if(bytes<=2*1024*1024){
  while(cache.size&&(cache.size>=1000||cacheBytes+bytes>2*1024*1024)){
   const first=cache.keys().next().value!;cacheBytes-=2*(first.length+cache.get(first)!.length);cache.delete(first);
  }
  cache.set(key,markup);cacheBytes+=bytes;
 }
 return markup;
}
export const Formula=React.memo(function Formula({value}:any){
 const markup=mathMarkup(value);
 return <span className="formula-preview" aria-label={'公式 '+value}>{React.createElement('math',{xmlns:'http://www.w3.org/1998/Math/MathML',dangerouslySetInnerHTML:{__html:markup}})}</span>;
});
