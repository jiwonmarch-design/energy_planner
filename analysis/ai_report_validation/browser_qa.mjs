import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.ENERGY_PLANNER_QA_BASE_URL || "http://127.0.0.1:8765";
const cdpUrl = process.env.ENERGY_PLANNER_QA_CDP_URL || "http://127.0.0.1:9232";
const jobId = process.env.ENERGY_PLANNER_QA_JOB_ID;
if (!/^[0-9a-f]{32}$/.test(jobId || "")) throw new Error("ENERGY_PLANNER_QA_JOB_ID is required");
const outputDir = path.resolve("analysis/ai_report_validation");
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
  await pause(120);
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
await evaluate("sessionStorage.removeItem('energy-planner.active-job.v1');location.reload();true");
await waitFor("document.readyState === 'complete'");
const initial = await evaluate(`({reportHidden:document.getElementById('ai-report').hidden,aiDisabled:document.getElementById('ai-analyze').disabled,htmlDisabled:document.getElementById('download-report-html').disabled,printDisabled:document.getElementById('print-report').disabled,status:document.getElementById('ai-analysis-status').textContent})`);
record("initial_report_state", initial.reportHidden && initial.aiDisabled && initial.htmlDisabled && initial.printDisabled && initial.status.includes("24시간 예측"), initial);
await evaluate(`sessionStorage.setItem("energy-planner.active-job.v1",JSON.stringify({jobId:"${jobId}",context:{timezone:"Asia/Seoul",fileToken:"ai-report-qa"}}));location.reload();true`);
await waitFor("document.readyState === 'complete'");
const recovered = await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED' && !document.getElementById('run-prediction').hidden", 15_000);
record("completed_job_recovered", recovered, await evaluate("document.getElementById('workspace-job-status').textContent"));
await evaluate("document.getElementById('run-prediction').click();true");
const reportReady = await waitFor("!document.getElementById('ai-report').hidden && window.state?.analysisReport !== null", 30_000).catch(() => false);
const actualReady = reportReady || await waitFor("!document.getElementById('ai-report').hidden && document.querySelectorAll('#report-recommendations li').length > 0", 30_000);
record("local_report_without_ai_dependency", actualReady, await evaluate("document.getElementById('ai-analysis-status').textContent"));
await evaluate("document.documentElement.style.scrollBehavior='auto';true");

const reportState = await evaluate(`(() => ({
  source: document.getElementById('report-source-badge').textContent,
  total: document.getElementById('report-total').textContent,
  peak: document.getElementById('report-peak').textContent,
  comparison: document.getElementById('report-comparison').textContent,
  dataPeriod: document.getElementById('report-data-period').textContent,
  forecastPeriod: document.getElementById('report-forecast-period').textContent,
  recommendations: document.querySelectorAll('#report-recommendations li').length,
  limitations: document.querySelectorAll('#report-limitations li').length,
  chartLines: document.querySelectorAll('#report-chart polyline').length,
  baselineVisible: !document.getElementById('report-baseline-legend').hidden,
  validationMae: document.getElementById('report-validation-mae').textContent,
  testWape: document.getElementById('report-test-wape').textContent,
  htmlEnabled: !document.getElementById('download-report-html').disabled,
  printEnabled: !document.getElementById('print-report').disabled,
  overflow: document.documentElement.scrollWidth-document.documentElement.clientWidth,
}))()`);
record("report_structure_and_real_metrics", reportState.total.includes("kWh") && /오[전후]/.test(reportState.peak) && reportState.recommendations >= 1 && reportState.recommendations <= 3 && reportState.limitations >= 2 && reportState.validationMae !== "미확인" && reportState.testWape !== "미확인", reportState);
record("same_weekday_real_baseline", reportState.chartLines === 2 && reportState.baselineVisible && !reportState.comparison.includes("비교 불가"), reportState);
record("download_controls_and_desktop_layout", reportState.htmlEnabled && reportState.printEnabled && reportState.overflow === 0, reportState);

const interaction = await evaluate(`(() => {
  const svg=document.getElementById('report-chart'),rect=svg.getBoundingClientRect();
  svg.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:rect.left+rect.width*.55,clientY:rect.top+100,pointerType:'mouse'}));
  const hover={visible:!document.getElementById('report-chart-tooltip').hidden,text:document.getElementById('report-chart-tooltip').textContent};
  document.getElementById('report-baseline-toggle').click();
  const off={checked:document.getElementById('report-baseline-toggle').checked,lines:svg.querySelectorAll('polyline').length};
  document.getElementById('report-baseline-toggle').click();
  return {hover,off,onLines:svg.querySelectorAll('polyline').length};
})()`);
record("chart_hover_click_and_toggle", interaction.hover.visible && interaction.hover.text.includes("예측") && interaction.hover.text.includes("동일 요일") && !interaction.off.checked && interaction.off.lines === 1 && interaction.onLines === 2, interaction);

await evaluate("document.getElementById('report-hour-slider').focus();document.getElementById('report-hour-slider').value='8';document.getElementById('report-hour-slider').dispatchEvent(new Event('input',{bubbles:true}));true");
await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 });
const slider = await evaluate(`({value:document.getElementById('report-hour-slider').value,output:document.getElementById('report-selected-value').textContent,focused:document.activeElement.id})`);
record("chart_keyboard_slider", slider.value === "9" && slider.output.includes("차이") && slider.focused === "report-hour-slider", slider);

const simulator = await evaluate(`(() => {
  const forecast=state.analysisReport.chart.forecast_kwh;
  document.getElementById('simulator-from').value='0';document.getElementById('simulator-to').value='1';
  document.getElementById('simulator-kwh').value=String(Math.min(10,forecast[0]/2));
  document.getElementById('simulator-from-rate').value='120';document.getElementById('simulator-to-rate').value='80';
  document.getElementById('simulator-to-rate').dispatchEvent(new Event('input',{bubbles:true}));
  return {amount:Number(document.getElementById('simulator-kwh').value),before:document.getElementById('simulator-before').textContent,after:document.getElementById('simulator-after').textContent,saving:document.getElementById('simulator-saving').textContent,effect:document.getElementById('simulator-load-effect').textContent,errorHidden:document.getElementById('simulator-error').hidden};
})()`);
const expectedBefore = simulator.amount * 120;
const expectedAfter = simulator.amount * 80;
record("simulator_calculation", simulator.errorHidden && simulator.before.replace(/[^0-9]/g, "") === String(Math.round(expectedBefore)) && simulator.after.replace(/[^0-9]/g, "") === String(Math.round(expectedAfter)) && simulator.saving.includes(String(Math.round(expectedBefore - expectedAfter))) && simulator.effect.includes("최대수요전력"), simulator);

await evaluate("document.querySelector('.ai-analysis-panel').scrollIntoView({block:'start'});true");
await pause(250);
await screenshot("ai-report-1440.png");
for (const width of [390, 320]) {
  await viewport(width, 900);
  await evaluate("document.querySelector('.ai-analysis-panel').scrollIntoView({block:'start'});true");
  await pause(250);
  const mobile = await evaluate(`({viewport:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll('.report-actions .btn')].every(b=>b.getBoundingClientRect().height>=44),chart:document.getElementById('report-chart').getBoundingClientRect().height,simulatorColumns:getComputedStyle(document.querySelector('.simulator-grid')).gridTemplateColumns})`);
  record(`mobile_${width}_layout`, mobile.viewport === mobile.scrollWidth && mobile.buttons && mobile.chart >= 220 && !mobile.simulatorColumns.includes(" "), mobile);
  await screenshot(`ai-report-${width}.png`);
}

await viewport(1440, 1000);
const html = await evaluate("buildStandaloneReportHtml(state.analysisReport)");
const htmlPath = path.join(outputDir, "standalone-report.html");
fs.writeFileSync(htmlPath, html, "utf8");
record("standalone_html_privacy", !html.includes("OPENAI_API_KEY") && !html.includes("csv_text") && !html.includes("Authorization: Bearer") && !html.includes("http://127.0.0.1"), { bytes: Buffer.byteLength(html), rawCsvMarkers: html.includes("csv_text") });

await evaluate("document.body.classList.add('print-ai-report');true");
const pdf = await send("Page.printToPDF", { printBackground: true, preferCSSPageSize: true });
fs.writeFileSync(path.join(outputDir, "report-print.pdf"), Buffer.from(pdf.data, "base64"));
await evaluate("document.body.classList.remove('print-ai-report');true");
record("pdf_generated", Buffer.from(pdf.data, "base64").length > 10_000, Buffer.from(pdf.data, "base64").length);

await goto(`file:///${path.join(outputDir, "report-print.pdf").replaceAll("\\", "/")}`);
await pause(1500);
await screenshot("pdf-viewer-page1.png");
for (const [page, y] of [[2, 350], [3, 550]]) {
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: 150, y, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: 150, y, button: "left", clickCount: 1 });
  await pause(400);
  await screenshot(`pdf-viewer-page${page}.png`);
}

await goto(`file:///${htmlPath.replaceAll("\\", "/")}`);
const standaloneReady = await waitFor("document.querySelectorAll('#report-chart polyline').length >= 2 && document.getElementById('simulator-from').options.length === 24", 10_000);
const standalone = await evaluate(`(() => {document.getElementById('report-baseline-toggle').click();const off=document.querySelectorAll('#report-chart polyline').length;const amount=document.getElementById('simulator-kwh');amount.value='1';document.getElementById('simulator-from-rate').value='120';document.getElementById('simulator-to-rate').value='80';amount.dispatchEvent(new Event('input',{bubbles:true}));return {off,amount:amount.value,cost:document.getElementById('simulator-after').textContent,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth}})()`);
record("standalone_html_interactive", standaloneReady && standalone.off === 1 && standalone.cost.includes("80") && standalone.overflow === 0, standalone);
await evaluate("window.scrollTo(0,0);true");
await pause(150);
await screenshot("standalone-1440.png");

record("runtime_console_clean", runtimeErrors.length === 0 && consoleErrors.length === 0, { runtimeErrors, consoleErrors });
const report = { generatedAt: new Date().toISOString(), total: checks.length, passed: checks.filter((item) => item.status === "PASS").length, failed: checks.filter((item) => item.status === "FAIL").length, checks };
fs.writeFileSync(path.join(outputDir, "browser_results.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
socket.close();
