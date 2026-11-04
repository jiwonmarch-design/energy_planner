import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.ENERGY_PLANNER_QA_BASE_URL || "http://127.0.0.1:8765";
const cdpUrl = process.env.ENERGY_PLANNER_QA_CDP_URL || "http://127.0.0.1:9232";
const jobId = process.env.ENERGY_PLANNER_QA_JOB_ID;
if (!/^[0-9a-f]{32}$/.test(jobId || "")) throw new Error("ENERGY_PLANNER_QA_JOB_ID is required");
const outputDir = path.resolve("analysis/six_step_report_validation");
fs.mkdirSync(outputDir, { recursive: true });

const targets = await fetch(`${cdpUrl}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("Chrome page target not found");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
const pending = new Map();
const runtimeErrors = [];
const consoleErrors = [];
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Runtime.exceptionThrown") runtimeErrors.push(message.params.exceptionDetails.text);
  if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
    consoleErrors.push(message.params.args.map((item) => item.value || item.description || "").join(" "));
  }
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
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function evaluate(expression) {
  const response = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}
async function waitFor(expression, timeout = 30_000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await evaluate(expression)) return true;
    await pause(150);
  }
  return false;
}
async function goto(url) {
  await send("Page.navigate", { url });
  if (!await waitFor("document.readyState === 'complete'")) throw new Error(`navigation timeout: ${url}`);
}
async function viewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await pause(150);
}
async function screenshot(name, captureBeyondViewport = false) {
  const image = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(image.data, "base64"));
}
const checks = [];
function record(name, passed, details) {
  checks.push({ name, status: passed ? "PASS" : "FAIL", details });
}

await send("Page.enable");
await send("Runtime.enable");
await viewport(1440, 1000);
await goto(`${baseUrl}/`);
await evaluate("sessionStorage.removeItem('energy-planner.active-job.v1');performance.clearResourceTimings();location.reload();true");
await waitFor("document.readyState === 'complete'");
const initial = await evaluate(`(() => ({
  steps: document.querySelectorAll('[data-workflow-step]').length,
  sections: ['upload','quality','training','dashboard','report','simulator'].every(id=>document.getElementById(id)),
  reportHidden: document.getElementById('report-preview').hidden,
  reportDisabled: document.getElementById('ai-analyze').disabled,
  simulatorGate: !document.getElementById('simulator-gate').hidden,
  aiCalls: performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/ai-analysis/')).length,
  overflow: document.documentElement.scrollWidth-document.documentElement.clientWidth,
}))()`);
record("initial_six_step_state", initial.steps === 6 && initial.sections && initial.reportHidden && initial.reportDisabled && initial.simulatorGate && initial.aiCalls === 0 && initial.overflow === 0, initial);

await evaluate(`sessionStorage.setItem("energy-planner.active-job.v1",JSON.stringify({jobId:"${jobId}",context:{timezone:"Asia/Seoul",fileToken:"six-step-qa"}}));location.reload();true`);
await waitFor("document.readyState === 'complete'");
const recovered = await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED' && !document.getElementById('run-prediction').hidden", 15_000);
record("completed_job_recovered", recovered, await evaluate("document.getElementById('workspace-job-status').textContent"));

await evaluate("performance.clearResourceTimings();document.getElementById('run-prediction').click();true");
const predictionReady = await waitFor("!document.getElementById('dashboard-results').hidden && !document.getElementById('simulator-workspace').hidden", 30_000);
const postPrediction = await evaluate(`(() => ({
  forecastPeriod: document.getElementById('forecast-period').textContent,
  dashboardStatus: document.getElementById('job-status').textContent,
  reportStatus: document.getElementById('report-status').textContent,
  reportHidden: document.getElementById('report-preview').hidden,
  reportEnabled: !document.getElementById('ai-analyze').disabled,
  simulatorStatus: document.getElementById('simulator-status').textContent,
  simulatorVisible: !document.getElementById('simulator-workspace').hidden,
  aiCalls: performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/ai-analysis/')).length,
}))()`);
record("prediction_enables_optional_steps", predictionReady && postPrediction.forecastPeriod.startsWith("예측 대상") && postPrediction.dashboardStatus === "예측 완료" && postPrediction.reportStatus === "준비 완료" && postPrediction.reportHidden && postPrediction.reportEnabled && postPrediction.simulatorStatus === "준비 완료" && postPrediction.simulatorVisible && postPrediction.aiCalls === 0, postPrediction);

const simulator = await evaluate(`(() => {
  const amount=document.getElementById('simulator-kwh');
  document.getElementById('simulator-from').value='0';
  document.getElementById('simulator-to').value='1';
  amount.value=String(Math.min(1,Number(amount.max)));
  document.getElementById('simulator-from-rate').value='120';
  document.getElementById('simulator-to-rate').value='80';
  document.getElementById('simulator-to-rate').dispatchEvent(new Event('input',{bubbles:true}));
  return {
    max:Number(amount.max),
    lines:document.querySelectorAll('#simulator-chart polyline').length,
    markers:document.querySelectorAll('#simulator-chart circle').length,
    before:document.getElementById('simulator-before').textContent,
    after:document.getElementById('simulator-after').textContent,
    saving:document.getElementById('simulator-saving').textContent,
    peakBefore:document.getElementById('simulator-peak-before').textContent,
    peakAfter:document.getElementById('simulator-peak-after').textContent,
    status:document.getElementById('simulator-status').textContent,
  };
})()`);
record("simulator_independent_live_calculation", simulator.max > 0 && simulator.lines === 2 && simulator.markers === 2 && simulator.before.includes("원") && simulator.after.includes("원") && simulator.saving.includes("원") && simulator.peakBefore.includes("kWh") && simulator.peakAfter.includes("kWh") && simulator.status === "완료", simulator);
const capped = await evaluate(`(() => {const input=document.getElementById('simulator-kwh');input.value=String(Number(input.max)+1);input.dispatchEvent(new Event('input',{bubbles:true}));return {max:Number(input.max),errorHidden:document.getElementById('simulator-error').hidden,error:document.getElementById('simulator-error').textContent};})()`);
record("simulator_source_load_cap", !capped.errorHidden && capped.error.includes("넘을 수 없습니다"), capped);

await evaluate("document.getElementById('ai-analyze').click();true");
const generating = await waitFor("!document.getElementById('report-generation-progress').hidden", 3_000);
const reportReady = await waitFor("!document.getElementById('report-preview').hidden && !document.getElementById('ai-report').hidden && document.getElementById('report-status').textContent === '완료'", 60_000);
const report = await evaluate(`(() => ({
  generating:${generating},
  status:document.getElementById('report-status').textContent,
  source:document.getElementById('report-source-badge').textContent,
  summary:document.getElementById('report-summary').textContent,
  recommendations:document.querySelectorAll('#report-recommendations li').length,
  limitations:document.querySelectorAll('#report-limitations li').length,
  lines:document.querySelectorAll('#report-chart polyline').length,
  htmlEnabled:!document.getElementById('download-report-html').disabled,
  printEnabled:!document.getElementById('print-report').disabled,
  model:document.getElementById('report-model').textContent,
  wape:document.getElementById('report-test-wape').textContent,
}))()`);
record("real_ai_report_generation", reportReady && report.generating && report.status === "완료" && report.source.includes("AI") && report.summary.length > 20 && report.recommendations >= 1 && report.recommendations <= 3 && report.limitations >= 1 && report.lines >= 1 && report.htmlEnabled && report.printEnabled && report.model === "XGBoost" && report.wape !== "미확인", report);

const regeneration = await evaluate(`(async()=>{
  const original=window.fetch;
  const payload=state.analysisReport;
  window.fetch=(url,options)=>String(url).includes('/api/ai-analysis/')?new Promise(resolve=>setTimeout(()=>resolve(new Response(JSON.stringify(payload),{status:200,headers:{'Content-Type':'application/json'}})),600)):original(url,options);
  document.getElementById('regenerate-report').click();
  const visibleDuring=!document.getElementById('report-preview').hidden&&!document.getElementById('ai-report').hidden;
  await new Promise(resolve=>setTimeout(resolve,800));
  window.fetch=original;
  return {visibleDuring,status:document.getElementById('report-status').textContent,previewVisible:!document.getElementById('report-preview').hidden};
})()`);
record("regeneration_keeps_previous_preview", regeneration.visibleDuring && regeneration.previewVisible && regeneration.status === "완료", regeneration);

const standalone = await evaluate("buildStandaloneReportHtml(state.analysisReport)");
const standalonePath = path.join(outputDir, "standalone-report.html");
fs.writeFileSync(standalonePath, standalone, "utf8");
record("standalone_html_security", !standalone.includes("OPENAI_API_KEY") && !standalone.includes("csvText") && !standalone.includes("simulator-kwh") && standalone.includes("report-data"), { bytes: Buffer.byteLength(standalone), containsReportData: standalone.includes("report-data") });
await goto(`file:///${standalonePath.replaceAll("\\", "/")}`);
const standaloneReady = await waitFor("document.querySelectorAll('#report-chart polyline').length >= 1", 10_000);
const standaloneState = await evaluate(`({lines:document.querySelectorAll('#report-chart polyline').length,summary:document.getElementById('report-summary').textContent,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth})`);
record("standalone_html_offline_interaction", standaloneReady && standaloneState.lines >= 1 && standaloneState.summary === report.summary && standaloneState.overflow === 0, standaloneState);
await screenshot("standalone-1440.png", true);

await viewport(390, 844);
await goto(`${baseUrl}/#simulator`);
await waitFor("document.readyState === 'complete'");
const mobile390 = await evaluate(`({overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,steps:document.querySelectorAll('[data-workflow-step]').length,minButton:Math.min(...[...document.querySelectorAll('.btn,.step-button')].filter(x=>x.offsetParent!==null).map(x=>x.getBoundingClientRect().height))})`);
record("mobile_390_no_overflow", mobile390.overflow === 0 && mobile390.steps === 6 && mobile390.minButton >= 44, mobile390);
await screenshot("six-step-390.png", true);
await viewport(320, 844);
const mobile320 = await evaluate(`({overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,minButton:Math.min(...[...document.querySelectorAll('.btn,.step-button')].filter(x=>x.offsetParent!==null).map(x=>x.getBoundingClientRect().height))})`);
record("mobile_320_no_overflow", mobile320.overflow === 0 && mobile320.minButton >= 44, mobile320);
await screenshot("six-step-320.png", true);

await viewport(1440, 1000);
await goto(`${baseUrl}/#report`);
await waitFor("document.readyState === 'complete'");
await evaluate(`sessionStorage.setItem("energy-planner.active-job.v1",JSON.stringify({jobId:"${jobId}",context:{timezone:"Asia/Seoul",fileToken:"six-step-qa"}}));location.reload();true`);
await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED'", 15_000);
await evaluate("document.getElementById('run-prediction').click();true");
await waitFor("!document.getElementById('simulator-workspace').hidden", 30_000);
await screenshot("six-step-1440.png", true);

record("no_console_or_runtime_errors", runtimeErrors.length === 0 && consoleErrors.length === 0, { runtimeErrors, consoleErrors });
const summary = { generated_at: new Date().toISOString(), checks, pass: checks.filter((item) => item.status === "PASS").length, fail: checks.filter((item) => item.status === "FAIL").length };
fs.writeFileSync(path.join(outputDir, "browser_results.json"), JSON.stringify(summary, null, 2));
socket.close();
console.log(JSON.stringify(summary, null, 2));
if (summary.fail) process.exitCode = 1;
