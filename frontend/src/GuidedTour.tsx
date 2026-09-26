import React,{useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
const steps=[
 {target:'[data-guide="import"]',title:'打开材料入口',body:'点击高亮的 OpenCode 状态按钮，打开导入与任务窗口。'},
 {target:'[data-guide="close-import"]',title:'找到上传的位置',body:'窗口左侧查看文件导入情况，中间拖入文件，右侧查看任务。现在点击“关闭详情”，继续体验题库；本次无需上传。'},
 {target:'[data-guide="library"]',title:'进入题库',body:'点击“题库”，浏览已审核通过的题目。'},
 {target:'[data-guide="answer"]',title:'展开一份答案',body:'点击高亮按钮查看简明作答；旁边的“查看解析”提供完整说明。'},
 {target:'[data-guide="edit"]',title:'打开编辑区',body:'点击“编辑 / 人工复核”，题目留在左侧，右侧可以修改正文和图片。'},
 {target:'.workspace-source-evidence summary, [data-guide="source"]',title:'核对来源',body:'点击这里展开原件，对照题干、公式、图中标号。原件不会被修改。'},
 {target:'[data-guide="ai-review"]',title:'找到 AI 修改入口',body:'点击“AI 复核”。可指定某张图并填写意见，生成预览后再决定是否采用；现在不用提交。'},
 {target:'[data-guide="library"]',title:'返回题库选题',body:'点击顶部“题库”，收起编辑区。'},
 {target:'[data-guide="select"]:not(:checked)',title:'勾选一道题',body:'勾选高亮题目的复选框，把它加入本次编排。待审核题目不能加入。'},
 {target:'[data-guide="export"]',title:'进入编排',body:'点击“编排与导出”。左侧调整顺序，中间查看试卷，右侧修改导出参数。'},
 {target:'[data-guide="preview"]',title:'生成实际分页',body:'点击“生成分页预览”。生成后可以翻页检查并下载 Word；这里不调用 AI。',wait:'.rendered-page'}
];
export function GuidedTour({onClose}: {onClose:()=>void}){
 const[step,S]=useState(0),[skipped,SKIP]=useState(0),[rect,R]=useState<DOMRect|null>(null),[working,W]=useState(false);
 const done=step>=steps.length,current=steps[step];
 useEffect(()=>{const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.stopImmediatePropagation();onClose()}};document.addEventListener('keydown',key,true);return()=>document.removeEventListener('keydown',key,true)},[onClose]);
 useEffect(()=>{
  R(null);W(false);if(done)return;
  let target:HTMLElement|null=null,scrolled=false,clicked=false,advanced=false;
  const advance=()=>{if(!advanced){advanced=true;S(v=>v+1)}};
  const click=()=>{if(target?.matches(':disabled'))return;if(current.wait){clicked=true;W(true)}else{setTimeout(advance,50)}};
  const update=()=>{
   const next=Array.from(document.querySelectorAll<HTMLElement>(current.target)).find(e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0)||null;
   if(next!==target){target?.removeEventListener('click',click);target=next;target?.addEventListener('click',click)}
   if(target){if(!scrolled){target.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});scrolled=true}const b=target.getBoundingClientRect();R(b)}else R(null);
   const rendered=current.wait?document.querySelector<HTMLImageElement>(current.wait):null;
   if(clicked&&rendered?.complete&&rendered.naturalWidth>0&&!target?.matches(':disabled')&&!document.querySelector('.paged-export [role="alert"]'))advance();
  };
  update();const timer=setInterval(update,250);window.addEventListener('resize',update);window.addEventListener('scroll',update,true);
  return()=>{advanced=true;clearInterval(timer);target?.removeEventListener('click',click);window.removeEventListener('resize',update);window.removeEventListener('scroll',update,true)};
 },[step,done]);
 const w=window.innerWidth,h=window.innerHeight,pad=7;
 const x=rect?Math.max(0,rect.left-pad):0,y=rect?Math.max(0,rect.top-pad):0,right=rect?Math.min(w,rect.right+pad):w,bottom=rect?Math.min(h,rect.bottom+pad):h;
 const width=Math.min(344,w-24),left=rect?Math.max(12,Math.min(w-width-12,x)):Math.max(12,(w-width)/2),top=rect?(bottom+245<h?bottom+12:Math.max(12,y-245)):Math.max(12,(h-250)/2);
 return createPortal(<div className="guided-tour">
 {rect&&!done?<><div className="tour-shade" style={{left:0,top:0,width:w,height:y}}/><div className="tour-shade" style={{left:0,top:y,width:x,height:bottom-y}}/><div className="tour-shade" style={{left:right,top:y,width:w-right,height:bottom-y}}/><div className="tour-shade" style={{left:0,top:bottom,width:w,height:h-bottom}}/><div className="tour-highlight" style={{left:x,top:y,width:right-x,height:bottom-y}}/></>:<div className="tour-shade" style={{inset:0}}/>}
 <section role="dialog" aria-label="新手任务引导" className="tour-card" style={{left,top,width}}><div className="tour-card-top"><small>{done?'体验结束':`新手任务 ${step+1} / ${steps.length}`}</small><button onClick={onClose} aria-label="退出使用引导">✕</button></div><h3>{done?'你已经走过主要操作流程':current.title}</h3><p aria-live="polite">{done?`完成 ${steps.length-skipped} 项操作${skipped?'，跳过 '+skipped+' 项':''}。可以继续编排，也可以随时从仪表盘重新体验。`:current.body}</p>{!done&&!rect&&<p className="tour-unavailable">当前没有可操作的对象。可先跳过这一步，之后再来体验。</p>}{working&&<p role="status">等待分页结果；若生成失败，可退出引导查看错误。</p>}<div className="tour-progress"><span style={{width:(done?100:step/steps.length*100)+'%'}}/></div><div className="tour-card-actions">{done?<button className="primary" onClick={onClose}>完成引导</button>:<><small>{rect?'请点击高亮位置继续':'需要先有对应的题目或原件'}</small><button onClick={()=>{SKIP(n=>n+1);S(n=>n+1)}}>跳过此步</button></>}</div></section></div>,document.body);
}
