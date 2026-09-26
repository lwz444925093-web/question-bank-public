// Read File objects synchronously while the browser still exposes the drop data.
export async function collectDropFiles(data:DataTransfer):Promise<File[]> {
 const direct=Array.from(data.files||[]);
 const items=Array.from(data.items||[]);
 const files:File[]=[];const folders:any[]=[];
 for(const item of items){
  let entry:any=null;try{entry=(item as any).webkitGetAsEntry?.()}catch{}
  if(entry?.isDirectory){folders.push(entry);continue}
  const file=item.getAsFile?.();if(file)files.push(file);
 }
 if(!folders.length)return direct.length?direct:files;
 let count=files.length;
 async function walk(entry:any):Promise<void>{
  if(entry.isFile){const file:File=await new Promise((ok,no)=>entry.file(ok,no));files.push(file);if(++count>200)throw Error('请分批上传，每次最多200个文件');return}
  if(!entry.isDirectory)return;
  const reader=entry.createReader();while(true){const batch:any[]=await new Promise((ok,no)=>reader.readEntries(ok,no));if(!batch.length)break;for(const child of batch)await walk(child)}
 }
 for(const folder of folders)await walk(folder);
 return files;
}
