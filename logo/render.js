const {chromium}=require('playwright');const fs=require('fs');
(async()=>{const svg=fs.readFileSync('logo.svg','utf8');const b=await chromium.launch();
for(const [n,sz] of [['logo-1024.png',1024],['apple-touch-icon.png',180]]){
 const p=await b.newPage({viewport:{width:sz,height:sz}});
 await p.setContent('<body style="margin:0">'+svg.replace('width="512" height="512"','width="'+sz+'" height="'+sz+'"')+'</body>');
 await p.screenshot({path:n});await p.close();}
await b.close();})();
