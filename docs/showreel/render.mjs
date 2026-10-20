import puppeteer from 'puppeteer-core';
import {pathToFileURL} from 'url';
import {mkdirSync,writeFileSync,rmSync} from 'fs';
const FPS=30,out=process.argv[2]||'frames';
rmSync(out,{recursive:true,force:true});mkdirSync(out);
const b=await puppeteer.launch({executablePath:process.env.CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:'new',args:['--force-device-scale-factor=1']});
const p=await b.newPage();await p.setViewport({width:1920,height:1080});
p.on('pageerror',e=>console.log('ERR',e.message));
await p.goto(pathToFileURL(process.cwd()+'/index.html').href);await p.evaluate(()=>document.fonts.ready);
const DUR=await p.evaluate(()=>window.DUR);
for(let i=0;i<FPS*DUR;i++){await p.evaluate(t=>render(t),i/FPS);writeFileSync(`${out}/f${String(i).padStart(4,'0')}.png`,await p.screenshot({type:'png'}));}
await b.close();
