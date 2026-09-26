export const LIBRARY_PAGE_SIZE=30;

export function libraryPage(total:number,requested:number,focusIndex=-1){
 const pages=Math.max(1,Math.ceil(total/LIBRARY_PAGE_SIZE));
 const wanted=focusIndex>=0?Math.floor(focusIndex/LIBRARY_PAGE_SIZE):requested;
 const page=Math.max(0,Math.min(pages-1,Number.isFinite(wanted)?Math.floor(wanted):0));
 const start=page*LIBRARY_PAGE_SIZE;
 return {page,pages,start,end:Math.min(total,start+LIBRARY_PAGE_SIZE),total};
}
