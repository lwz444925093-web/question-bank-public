// Canonicalize explicit Unicode indices only; do not infer missing mathematics.
export function mathNotation(value:string){
 const sub='₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎',sup='⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾',plain='0123456789+-=()';
 // MathML display fallback only; stored LaTeX stays unchanged.
 return (value||'').replace(/∠/g,'\\angle ').replace(/°/g,'^{\\circ}').replace(/\\widehat(?=\s*\{)/g,'\\hat').replace(/[₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]+/g,s=>'_{'+[...s].map(c=>plain[sub.indexOf(c)]).join('')+'}').replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾]+/g,s=>'^{'+[...s].map(c=>plain[sup.indexOf(c)]).join('')+'}');
}
