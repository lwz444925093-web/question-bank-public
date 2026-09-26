import {convertLatexToMathMl} from 'mathlive';
// MathLive's MathML exporter drops some accents and their operands. Preserve
// those groups explicitly; the source LaTeX remains unchanged for editing.
export function readableMathML(latex:string):string{
 const accents:Record<string,[string,string]>={overline:['mover','¯'],underline:['munder','_'],widehat:['mover','^'],widetilde:['mover','~'],overrightarrow:['mover','→'],overleftarrow:['mover','←'],overleftrightarrow:['mover','↔']};
 const slots:string[]=[];let prepared='',cursor=0;
 const pattern=/\\(overline|underline|widehat|widetilde|overrightarrow|overleftarrow|overleftrightarrow)\s*\{/g;
 let match:RegExpExecArray|null;
 while((match=pattern.exec(latex))){
  let depth=1,end=pattern.lastIndex;
  for(;end<latex.length&&depth;end++){if(latex[end]==='\\'){end++;continue}if(latex[end]==='{')depth++;if(latex[end]==='}')depth--}
  if(depth)break;
  const [tag,mark]=accents[match[1]],body=readableMathML(latex.slice(pattern.lastIndex,end-1));
  const token='QBACCENT'+slots.length+'END';slots.push(`<${tag} ${tag==='munder'?'accentunder':'accent'}="true"><mrow>${body}</mrow><mo stretchy="true">${mark}</mo></${tag}>`);
  prepared+=latex.slice(cursor,match.index)+'\\text{'+token+'}';cursor=end;pattern.lastIndex=end;
 }
 prepared+=latex.slice(cursor);
 return convertLatexToMathMl(prepared).replace(/<mtext\s*>QBACCENT(\d+)END<\/mtext>/g,(_,i)=>slots[Number(i)]);
}
