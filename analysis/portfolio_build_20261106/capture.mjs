import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawn} from 'node:child_process';

const out = path.resolve('analysis/portfolio_build_20261106');
fs.mkdirSync(out, {recursive:true});
const jobs = fs.readdirSync('artifacts/web_jobs/_jobs').filter(n=>n.endsWith('.json'))
  .map(n=>JSON.parse(fs.readFileSync(path.join('artifacts/web_jobs/_jobs',n),'utf8')))
  .filter(j=>j.status==='COMPLETED' && j.run_dir && fs.existsSync(j.run_dir))
  .sort((a,b)=>(b.completed_at || b.created_at || '').localeCompare(a.completed_at || a.created_at || ''));
if(!jobs.length) throw new Error('No completed saved training job');
const job = jobs.find(j=>j.selected_model==='xgboost' && j.validation_metrics?.patchtst) || jobs[0];
const profile = fs.mkdtempSync(path.join(os.tmpdir(),'energy-portfolio-'));
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',[
  '--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=9241',
  '--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
const delay = ms=>new Promise(r=>setTimeout(r,ms));
let socket;
try{
  let targets;
  for(let i=0;i<60;i++){try{targets=await fetch('http://127.0.0.1:9241/json/list').then(r=>r.json());break;}catch{await delay(100);}}
  socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise(r=>socket.addEventListener('open',r,{once:true}));
  let seq=0; const waiting=new Map(); const errors=[];
  socket.addEventListener('message',e=>{const m=JSON.parse(e.data); if(m.method==='Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text); if(m.id&&waiting.has(m.id)){const p=waiting.get(m.id);waiting.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}});
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;waiting.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1080,deviceScaleFactor:1,mobile:false});
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await send('Page.navigate',{url:'http://127.0.0.1:8765/'});
  for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete' && typeof runPrediction==='function'"))break;await delay(100);}
  const capture=async(name,selector,bottomSelector)=>{
    const clip=await evaluate('(()=>{const e=document.querySelector('+JSON.stringify(selector)+');const r=e.getBoundingClientRect();const bottom='+ (bottomSelector?'document.querySelector('+JSON.stringify(bottomSelector)+').getBoundingClientRect().bottom':'r.bottom')+';return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:bottom-r.top,scale:1};})()');
    const r=await send('Page.captureScreenshot',{format:'png',clip,captureBeyondViewport:true});
    fs.writeFileSync(path.join(out,name),Buffer.from(r.data,'base64'));
  };
  const design=await evaluate("(()=>{const s=getComputedStyle(document.documentElement);return {palette:Object.fromEntries(['blue','blue-deep','blue-soft','ink','sub','line','bg','paper','success','danger'].map(k=>[k,s.getPropertyValue('--'+k).trim()])),bodyFont:getComputedStyle(document.body).fontFamily,heroFont:getComputedStyle(document.querySelector('.brand-title')).fontFamily,heroText:document.getElementById('hero-title').textContent,description:document.querySelector('.brand-description').textContent};})()");
  await evaluate("document.getElementById('brand-energy-toggle').click();true");
  await capture('home-current.png','#landing-home');
  await evaluate('(async()=>{sessionStorage.setItem(jobSessionKey,JSON.stringify({jobId:'+JSON.stringify(job.job_id)+',context:{timezone:'+JSON.stringify(job.building_timezone||'Asia/Seoul')+'}})); await recoverJob(); await runPrediction(); return true;})()');
  const prediction=await evaluate("state.predictionResult ? {run_id:state.predictionResult.run_id,model:state.predictionResult.model_kind,timestamps:state.predictionResult.timestamps,total_kwh:state.predictionResult.total_kwh,peak_kwh:state.predictionResult.peak_kwh,peak_timestamp:state.predictionResult.peak_timestamp,retrained:state.predictionResult.retrained} : {error:document.getElementById('dashboard-error').textContent}");
  if(!prediction.timestamps)throw new Error(JSON.stringify(prediction));
  await capture('forecast-current.png','#dashboard','#dashboard .chart-panel');
  await capture('forecast-core.png','#dashboard .forecast-stats','#forecast-chart');
  await capture('selection-current.png','#workspace-model-results');
  const simulation=await evaluate("(()=>{const r=state.predictionResult;const f=r.predictions_kwh.map(Number);const from=f.indexOf(Math.max(...f));let to=r.timestamps.findIndex(t=>Number(localDateParts(t,r.building_timezone).hour)===18);if(to<0||to===from)to=(from+3)%24;document.getElementById('simulator-from').value=String(from);document.getElementById('simulator-to').value=String(to);document.getElementById('simulator-kwh').value=String(Math.min(1,Math.round(f[from]*0.2*10)/10));document.getElementById('simulator-from-rate').value='180';document.getElementById('simulator-to-rate').value='110';updateSimulator();return {...state.simulatorSnapshot,fromTime:r.timestamps[from],toTime:r.timestamps[to]};})()");
  await capture('simulator-current.png','#simulator','#simulator .simulator-chart-panel');
  await capture('simulator-chart-current.png','#simulator .simulator-chart-panel');
  await capture('simulator-controls.png','#simulator-workspace','#simulator .simulator-results');
  fs.writeFileSync(path.join(out,'capture-evidence.json'),JSON.stringify({captured_at:new Date().toISOString(),url:'http://127.0.0.1:8765/',design,job:{job_id:job.job_id,run_dir:job.run_dir,selected_model:job.selected_model},prediction,simulation,errors,training_requests:0,external_ai_requests:0},null,2));
  console.log(JSON.stringify({design,job_id:job.job_id,selected:job.selected_model,simulation,errors},null,2));
}finally{socket?.close();chrome.kill();}
