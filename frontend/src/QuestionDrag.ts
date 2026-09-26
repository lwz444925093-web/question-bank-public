import type {DragEvent} from 'react';
let cleanup: (()=>void)|undefined;
/** A lightweight pointer companion; never snapshot the full question DOM. */
export function startQuestionDrag(event:DragEvent<HTMLElement>,id:string){
 cleanup?.();
 const card=event.currentTarget.closest('article');
 const chip=document.createElement('div');chip.className='question-drag-chip';chip.setAttribute('aria-hidden','true');
 const title=document.createElement('strong');title.textContent=card?.querySelector('.question-title')?.textContent||'题目';
 const hint=document.createElement('span');hint.textContent='拖到分类，添加归属';chip.append(title,hint);
 chip.style.left=event.clientX+16+'px';chip.style.top=event.clientY+14+'px';document.body.append(chip);
 const ghost=document.createElement('canvas');ghost.width=1;ghost.height=1;ghost.style.cssText='position:fixed;left:0;top:0;pointer-events:none';document.body.append(ghost);
 event.dataTransfer.setData('application/x-question-bank-ids',JSON.stringify([id]));event.dataTransfer.effectAllowed='copy';event.dataTransfer.setDragImage(ghost,0,0);
 card?.classList.add('question-drag-origin');document.body.classList.add('question-dragging');
 let target:Element|null=null;
 const move=(e:globalThis.DragEvent)=>{if(!e.clientX&&!e.clientY)return;chip.style.left=e.clientX+16+'px';chip.style.top=e.clientY+14+'px';const next=(e.target as Element)?.closest?.('.category-row')||null;if(next!==target){target?.classList.remove('category-drop-target');target=next;target?.classList.add('category-drop-target');}chip.classList.toggle('over-category',!!target);};
 const finish=()=>{document.removeEventListener('dragover',move,true);document.removeEventListener('dragend',finish,true);document.removeEventListener('drop',finish,true);window.removeEventListener('blur',finish);target?.classList.remove('category-drop-target');card?.classList.remove('question-drag-origin');document.body.classList.remove('question-dragging');chip.remove();ghost.remove();cleanup=undefined;};
 cleanup=finish;document.addEventListener('dragover',move,true);document.addEventListener('dragend',finish,true);document.addEventListener('drop',finish,true);window.addEventListener('blur',finish);
}
