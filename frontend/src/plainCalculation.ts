// Presentation only, for explicitly labelled calculations with unambiguous / operands.
export function plainCalculation(text:string):string|null {
 if(!/^[\s\da-zA-Z()+\-*/÷×²³^.=]+$/.test(text)||!text.includes('/')||!text.trim())return null;
 function convert(s:string):string{
  s=s.trim();let depth=0;const top:number[]=[];
  for(let i=0;i<s.length;i++){if(s[i]==='(')depth++;else if(s[i]===')')depth--;else if(!depth)top.push(i);if(depth<0)throw Error();}if(depth)throw Error();
  // A printed division sign separates the written fractions on either side.
  for(const ops of ['÷','+-','*/×']){const i=[...top].reverse().find(i=>i>0&&ops.includes(s[i])&&!'+-*/÷×^'.includes(s[i-1]));if(i!==undefined){const a=s.slice(0,i),b=s.slice(i+1);if(!b.trim())throw Error();if(s[i]==='/')return `\\frac{${ungroup(a)}}{${ungroup(b)}}`;return convert(a)+({'÷':'\\div ','×':'\\times ','*':'\\cdot '}[s[i]]||s[i])+convert(b);}}
  if(s.startsWith('(')&&s.endsWith(')'))return '\\left('+convert(s.slice(1,-1))+'\\right)';
  if(!/^[\s\da-zA-Z²³^.]+$/.test(s))throw Error();return s.replace(/²/g,'^{2}').replace(/³/g,'^{3}');
 }
 function ungroup(s:string):string{const c=convert(s);return c.startsWith('\\left(')&&c.endsWith('\\right)')?c.slice(6,-7):c;}
 try{return convert(text)}catch{return null}
}
