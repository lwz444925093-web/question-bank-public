import sharp from 'sharp';
const chunks=[];
for await (const chunk of process.stdin) chunks.push(chunk);
const png=await sharp(Buffer.concat(chunks),{density:240,limitInputPixels:40000000}).resize({width:2400,height:2400,fit:'inside',withoutEnlargement:true}).png().toBuffer();
process.stdout.write(png);
