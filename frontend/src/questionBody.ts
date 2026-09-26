const textOf=(b:any)=>b.kind==='paragraph'?(b.spans||[]).map((s:any)=>s.text).join(''):b.kind==='equation'?b.latex:null;
function comparable(v:string){return v.normalize('NFKC').replace(/\\(?:begin|end)\{cases\}/g,'').replace(/\\(?:dfrac|frac)\{([^{}]+)\}\{([^{}]+)\}/g,(_,a,b)=>`(${a})/${/^\w+$/.test(b)?b:`(${b})`}`).replace(/\\(?:geq|ge)\b/g,'≥').replace(/\\(?:leq|le)\b/g,'≤').replace(/\\[()\[\]]|\$|\\\\|[\s{},，;；。]/g,'');}
function labelKey(value:string){
 const label=value.trim().replace(/[（）．]/g,c=>({'（':'(','）':')','．':'.'}[c]!));
 if(/^[①-⑳]$/.test(label))return String(label.charCodeAt(0)-'①'.charCodeAt(0)+1);
 const m=label.match(/^\((\d+)\)$|^(\d+)[.、]?$|^([A-H])[.、)]?$/);
 return m?m.slice(1).find(x=>x!==undefined):undefined;
}
export function partDisplayLabel(part:any){
 const label=String(part.label||''),first=part.blocks?.[0];if(first?.kind!=='paragraph')return label;
 let text='';for(const span of first.spans||[]){if(span.kind!=='text')break;text+=span.text||'';}
 // Keep the complete source body. Suppress only an extra generated marker,
 // never a bare digit/letter that could be content or a mathematical prefix.
 const m=text.match(/^\s*([①-⑳]|(?:[（(]\d+[）)]|\d+[.．、]|[A-H][.．、)）])(?=$|\s|[\u3400-\u9fff]))/),key=labelKey(label);
 return key!==undefined&&m&&labelKey(m[1])===key?'':label;
}
export function questionBody(q:any){
 // Suppress a duplicated numbered paragraph only when all its content matches.
 const stem=(q.stem||[]).filter((b:any)=>{
  const text=textOf(b);if(text===null)return true;
  return !(q.subquestions||[]).some((p:any)=>{
   const label=String(p.label||'').normalize('NFKC'), normalized=text.normalize('NFKC').trim();
   if(!/^\(\d+\)$/.test(label)||!normalized.startsWith(label)||!p.blocks?.length)return false;
   const contents=p.blocks.map(textOf);if(contents.some((x:any)=>x===null))return false;
   return comparable(normalized.slice(label.length))===comparable(contents.join(''));
  });
 });
 return [...stem,...[...(q.options||[]),...(q.subquestions||[])].flatMap((p:any)=>{
  const displayLabel=partDisplayLabel(p);if(!displayLabel)return p.blocks||[];
  const label={kind:'text',text:displayLabel+' '};const [first,...rest]=p.blocks||[];
  if(!first)return [{kind:'paragraph',spans:[label]}];
  if(first.kind==='paragraph')return [{...first,spans:[label,...first.spans]},...rest];
  if(first.kind==='equation')return [{kind:'paragraph',spans:[label,{kind:'math',text:first.latex}]},...rest];
  return [{kind:'paragraph',spans:[label]},...p.blocks];
 })];
}
