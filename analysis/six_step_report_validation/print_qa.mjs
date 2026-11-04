import fs from "node:fs";
import path from "node:path";

const cdpUrl = process.env.ENERGY_PLANNER_QA_CDP_URL || "http://127.0.0.1:9232";
const jobId = process.env.ENERGY_PLANNER_QA_JOB_ID;
if (!/^[0-9a-f]{32}$/.test(jobId || "")) throw new Error("ENERGY_PLANNER_QA_JOB_ID is required");
const targets = await fetch(`${cdpUrl}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page" && item.url.startsWith("http://127.0.0.1:8765"));
if (!target) throw new Error("Energy Planner Chrome target not found");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const callback = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) callback.reject(new Error(message.error.message));
  else callback.resolve(message.result);
});
function send(method, params = {}) {
  const id = ++sequence;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
async function evaluate(expression) {
  const response = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}
await send("Page.enable");
await send("Runtime.enable");
await send("Page.reload", { ignoreCache: true });
for (let attempt = 0; attempt < 100; attempt += 1) {
  if (await evaluate("document.readyState === 'complete'")) break;
  await new Promise((resolve) => setTimeout(resolve, 100));
}
const failureRetry = await evaluate(`(async()=>{
  const original=window.fetch;
  const report=await original('/api/analysis-report/${jobId}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({timezone:'Asia/Seoul'})}).then(r=>r.json());
  state.analysisReport=report;state.aiAnalysisComplete=true;state.aiAnalysisAvailable=true;state.predictionComplete=true;state.predictionResult={timestamps:report.chart.timestamps,building_timezone:report.metadata.building_timezone};state.job={job_id:'${jobId}',status:'COMPLETED'};renderAnalysisReport(report);updateNextAction();
  window.fetch=(url,options)=>String(url).includes('/api/ai-analysis/')?Promise.resolve(new Response(JSON.stringify({error:'의도한 QA 오류'}),{status:502,headers:{'Content-Type':'application/json'}})):original(url,options);
  document.getElementById('regenerate-report').click();
  for(let i=0;i<50&&state.reportRequestInProgress;i+=1)await new Promise(resolve=>setTimeout(resolve,50));
  const failure={status:document.getElementById('report-status').textContent,previewVisible:!document.getElementById('report-preview').hidden,retryEnabled:!document.getElementById('regenerate-report').disabled};
  window.fetch=(url,options)=>String(url).includes('/api/ai-analysis/')?Promise.resolve(new Response(JSON.stringify(report),{status:200,headers:{'Content-Type':'application/json'}})):original(url,options);
  document.getElementById('regenerate-report').click();
  for(let i=0;i<50&&state.reportRequestInProgress;i+=1)await new Promise(resolve=>setTimeout(resolve,50));
  const retry={status:document.getElementById('report-status').textContent,previewVisible:!document.getElementById('report-preview').hidden};
  window.fetch=original;document.body.classList.add('print-ai-report');
  return {failure,retry};
})()`);
if (failureRetry.failure.status !== "오류" || !failureRetry.failure.previewVisible || !failureRetry.failure.retryEnabled || failureRetry.retry.status !== "완료" || !failureRetry.retry.previewVisible) {
  throw new Error(`report failure/retry state invalid: ${JSON.stringify(failureRetry)}`);
}
console.log(JSON.stringify({ reportFailureRetry: failureRetry }));
const pdf = await send("Page.printToPDF", {
  printBackground: true,
  preferCSSPageSize: true,
  marginTop: 0,
  marginBottom: 0,
  marginLeft: 0,
  marginRight: 0,
});
const output = path.resolve("tmp/pdfs/six-step-report.pdf");
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, Buffer.from(pdf.data, "base64"));
await evaluate("document.body.classList.remove('print-ai-report');true");
socket.close();
console.log(output);
