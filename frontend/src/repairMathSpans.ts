type Span={kind:string;text:string};
// Restore only explicit TeX split across spans; never infer missing operands.
export function repairMathSpans(spans:Span[]):Span[]{
 const out:Span[]=[];
 const balance=(s:string)=>[...s].reduce((n,c)=>n+(c==='{'?1:c==='}'?-1:0),0);
 for(let i=0;i<spans.length;i++){
  const first=spans[i];let value=first.text||'';
  if(/\\(?:frac|dfrac|sqrt)\b/.test(value)&&balance(value)>0){
   let j=i;
   while(balance(value)>0&&j+1<spans.length)value+=spans[++j].text||'';
   if(balance(value)===0){out.push({kind:'text',text:value});i=j;continue;}
  }
  out.push(first);
 }
 return out;
}
