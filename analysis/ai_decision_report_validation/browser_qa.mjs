import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.ENERGY_PLANNER_QA_BASE_URL || "http://127.0.0.1:8766";
const cdpUrl = process.env.ENERGY_PLANNER_QA_CDP_URL || "http://127.0.0.1:9232";
const jobId = process.env.ENERGY_PLANNER_QA_JOB_ID;
if (!/^[0-9a-f]{32}$/.test(jobId || "")) throw new Error("ENERGY_PLANNER_QA_JOB_ID is required");
const outputDir = path.resolve("analysis/ai_decision_report_validation");
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
  if (message.method === "Runtime.exceptionThrown") {
    const details = message.params.exceptionDetails;
    runtimeErrors.push(details.exception?.description || details.text);
  }
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
await goto(`${baseUrl}/#report`);
await evaluate(`sessionStorage.setItem("energy-planner.active-job.v1",JSON.stringify({jobId:"${jobId}",context:{timezone:"Asia/Seoul",fileToken:"decision-report-qa"}}));location.reload();true`);
const recovered = await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED' && !document.getElementById('run-prediction').hidden", 15_000);
record("completed_job_recovered", recovered, await evaluate("document.getElementById('workspace-job-status').textContent"));

await evaluate("document.getElementById('run-prediction').click();true");
const predictionReady = await waitFor("!document.getElementById('dashboard-results').hidden && !document.getElementById('ai-analyze').disabled", 30_000);
record("prediction_ready", predictionReady, await evaluate("document.getElementById('forecast-period').textContent"));

await evaluate("document.getElementById('ai-analyze').click();true");
const reportReady = await waitFor("!document.getElementById('report-preview').hidden && document.getElementById('report-status').textContent === '완료'", 60_000);
const reportState = await evaluate(`(() => {
  const report=state.analysisReport;
  const tags=[...document.querySelectorAll('#report-recommendations .recommendation-evidence span')].map((item)=>item.textContent);
  const evidenceCounts=[...document.querySelectorAll('#report-recommendations li')].map((item)=>[...item.querySelectorAll('.recommendation-evidence span')].filter((tag)=>/[0-9]/.test(tag.textContent)).length);
  return {
    version:report?.version,
    aiStatus:report?.ai?.status,
    findings:report?.ai_findings?.length,
    recommendations:report?.recommendations?.length,
    candidates:report?.operational_candidates?.length,
    comparisonHours:report?.comparison?.hourly_differences?.length,
    varianceStatus:report?.comparison?.variability?.status,
    previousHours:report?.previous_24h_comparison?.hourly_differences?.length,
    highSegments:report?.peak_analysis?.high_usage_segments?.length,
    peakShare:report?.peak_analysis?.peak_segment_share_percent,
    heading:document.getElementById('report-recommendations-title').textContent,
    testMae:document.getElementById('report-test-mae').textContent,
    tags,
    quantitativeTags:tags.filter((value)=>/[0-9]/.test(value)).length,
    evidenceCounts,
    overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
  };
})()`);
record("quantitative_decision_report", reportReady && reportState.version === 2 && reportState.aiStatus === "completed" && reportState.findings >= 1 && reportState.findings <= 3 && reportState.recommendations === reportState.findings && reportState.candidates >= reportState.findings && reportState.comparisonHours === 24 && reportState.varianceStatus === "available" && reportState.previousHours === 24 && reportState.highSegments >= 1 && Number.isFinite(reportState.peakShare) && reportState.heading === "핵심 발견 및 운영 결정" && reportState.testMae !== "미확인" && reportState.quantitativeTags >= reportState.recommendations && reportState.evidenceCounts.every((count)=>count >= 1) && reportState.overflow === 0, reportState);

const standalone = await evaluate("buildStandaloneReportHtml(state.analysisReport)");
const standaloneState = {
  hasKey: standalone.includes("OPENAI_API_KEY"),
  hasCsv: standalone.includes("csv_text"),
  hasHeading: standalone.includes("핵심 발견 및 운영 결정"),
  hasTestMae: standalone.includes("과거 Test MAE"),
  bytes: Buffer.byteLength(standalone),
};
record("standalone_report_preserves_security_and_content", !standaloneState.hasKey && !standaloneState.hasCsv && standaloneState.hasHeading && standaloneState.hasTestMae, standaloneState);

await evaluate("document.getElementById('report').scrollIntoView();true");
await screenshot("decision-report-1440.png", true);
await viewport(390, 844);
const mobile = await evaluate(`({
  overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
  previewVisible:!document.getElementById('report-preview').hidden,
  minButton:Math.min(...[...document.querySelectorAll('.btn,.step-button')].filter((item)=>item.offsetParent!==null).map((item)=>item.getBoundingClientRect().height)),
})`);
record("mobile_report_layout", mobile.overflow === 0 && mobile.previewVisible && mobile.minButton >= 44, mobile);
await screenshot("decision-report-390.png", true);

record("no_console_or_runtime_errors", runtimeErrors.length === 0 && consoleErrors.length === 0, { runtimeErrors, consoleErrors });
const summary = {
  generated_at: new Date().toISOString(),
  checks,
  pass: checks.filter((item) => item.status === "PASS").length,
  fail: checks.filter((item) => item.status === "FAIL").length,
};
fs.writeFileSync(path.join(outputDir, "browser_results.json"), JSON.stringify(summary, null, 2));
socket.close();
console.log(JSON.stringify(summary, null, 2));
if (summary.fail) process.exitCode = 1;
