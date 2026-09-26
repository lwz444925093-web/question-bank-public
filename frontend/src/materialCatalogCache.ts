type Entry={data:any,updatedAt:number};
const cache=new Map<string,Entry>();
const pending=new Map<string,Promise<Entry>>();
const prefix='material-catalog-v1:';
let generation=0;
export function catalogKey(subject:string,directory:string|null=null,recursive=true){return JSON.stringify([subject,directory,recursive])}
export function cachedCatalog(key:string):Entry|undefined{
 if(cache.has(key))return cache.get(key);
 try{const raw=sessionStorage.getItem(prefix+key);if(raw){const entry=JSON.parse(raw);if(entry?.data?.files&&typeof entry.updatedAt==='number'){cache.set(key,entry);return entry}}}catch{}
}
export function loadCatalog(subject:string,directory:string|null=null,recursive=true,force=false):Promise<Entry>{
 const key=catalogKey(subject,directory,recursive),inflight=pending.get(key);
 if(inflight)return inflight;
 const old=cachedCatalog(key);
 if(!force&&old&&Date.now()-old.updatedAt<10000)return Promise.resolve(old);
 const params=new URLSearchParams({subject,recursive:String(recursive)});if(directory!==null)params.set('directory',directory);
 const request=(async()=>{
  for(;;){
   const startedAt=generation;
   const r=await fetch('/api/materials?'+params);const data=await r.json();if(!r.ok)throw Error(data.detail||'无法读取文件列表');
   // A mutation while this read was running makes its response obsolete.
   // All callers share the follow-up read, so one refresh is sufficient.
   if(startedAt!==generation)continue;
   const entry={data,updatedAt:Date.now()};cache.set(key,entry);
   try{sessionStorage.setItem(prefix+key,JSON.stringify(entry))}catch{}
   return entry;
  }
 })();
 pending.set(key,request);
 void request.finally(()=>{if(pending.get(key)===request)pending.delete(key)}).catch(()=>{});
 return request;
}

export function invalidateCatalog(){
 generation++;
 for(const entry of cache.values())entry.updatedAt=0;
 try{for(let i=0;i<sessionStorage.length;i++){const key=sessionStorage.key(i);if(key?.startsWith(prefix)){const value=JSON.parse(sessionStorage.getItem(key)||'null');if(value){value.updatedAt=0;sessionStorage.setItem(key,JSON.stringify(value))}}}}catch{}
}
