import React from 'react';
export type Destination='library'|'review'|'import'|'export'|'settings'|'typography';
const modules:{id:Destination;title:string;description:string;symbol:string}[]=[
 {id:'import',title:'导入材料与任务',description:'上传 PDF、图片或 Word，查看处理进度与历史任务。',symbol:'＋'},
 {id:'library',title:'浏览题库',description:'查找题目、查看答案与解析，选题或进入编辑。',symbol:'▤'},
 {id:'review',title:'待审核',description:'核对存疑题目、原件和题图，确认后再入卷。',symbol:'✓'},
 {id:'export',title:'编排与导出',description:'调整选题顺序与分值，分页预览并下载 Word。',symbol:'↗'},
 {id:'typography',title:'字体与版式',description:'设置题库字体、字号和行距，也可进入回收站。',symbol:'Aa'},
 {id:'settings',title:'AI 设置',description:'调整处理入口、模型及思考深度，管理回收站。',symbol:'⚙'}
];
export function Dashboard({subject,total,approved,pending,running,selected,onNavigate,onStartGuide}:any){
 return <main className="dashboard"><section className="dashboard-hero"><div><p className="dashboard-eyebrow">教学工作台 · {subject}</p><h1>从材料到一份试卷</h1><p>导入、核对、选题与导出，都从这里开始。</p></div><button className="active" onClick={onStartGuide}>使用引导 →</button></section>
 <div className="dashboard-stats" aria-label="当前学科概况">{[['已保存题目',total],['已通过',approved],['待审核',pending],['后台运行 / 排队',running]].map(([label,n])=><div key={label}><strong>{n}</strong><span>{label}</span></div>)}</div>
 <h2 className="dashboard-section-title">常用模块</h2><div className="dashboard-modules">{modules.map(m=><button key={m.id} className="dashboard-module" onClick={()=>onNavigate(m.id)}><span className="module-symbol" aria-hidden="true">{m.symbol}</span><strong>{m.title}</strong><span>{m.description}</span><small>{m.id==='review'?pending+' 道待核对':m.id==='export'?selected+' 道已选题':'进入模块 →'}</small></button>)}</div></main>;
}
