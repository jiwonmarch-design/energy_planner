import fs from "node:fs";
import path from "node:path";

const baseUrl = "http://127.0.0.1:8765";
const outputDir = path.resolve("analysis/integrated_mvp_validation");
const fixture = path.join(outputDir, "synthetic_180_days.csv");
fs.mkdirSync(outputDir, { recursive: true });

const rows = ["timestamp,kwh"];
const origin = Date.parse("2026-01-01T00:00:00Z");
for (let hour = 0; hour < 180 * 24; hour += 1) {
  const timestamp = new Date(origin + hour * 3_600_000).toISOString();
  const value = 18 + 4 * Math.sin((2 * Math.PI * (hour % 24)) / 24) + 2 * Math.sin((2 * Math.PI * (hour % 168)) / 168) + (hour % 168 < 120 ? 2 : 0);
  rows.push(`${timestamp},${value.toFixed(4)}`);
}
fs.writeFileSync(fixture, rows.join("\n"));

let tabs = await fetch("http://127.0.0.1:9229/json/list").then((response) => response.json());
let target = tabs.find((tab) => tab.type === "page" && tab.url.startsWith(baseUrl));
if (!target) {
  target = await fetch(`http://127.0.0.1:9229/json/new?${encodeURIComponent(baseUrl)}`, { method: "PUT" }).then((response) => response.json());
}

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
  const callbacks = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) callbacks.reject(new Error(message.error.message));
  else callbacks.resolve(message.result);
});

function send(method, params = {}) {
  const id = ++sequence;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression, timeout = 15_000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await pause(200);
  }
  throw new Error(`Timed out: ${expression}`);
}
async function goto(url) {
  await send("Page.navigate", { url });
  await waitFor("document.readyState === 'complete'");
}
async function viewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
}
async function screenshot(name, fullPage = false) {
  const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: fullPage });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
}
async function selectFile(filePath) {
  const document = await send("DOM.getDocument", { depth: 1 });
  const input = await send("DOM.querySelector", { nodeId: document.root.nodeId, selector: "#csv-file" });
  await send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [filePath] });
  await evaluate("document.getElementById('csv-file').dispatchEvent(new Event('change', { bubbles: true }))");
  await waitFor("!document.getElementById('file-info').hidden");
}
function record(results, id, condition, details) {
  results.push({ id, status: condition ? "PASS" : "FAIL", details });
}

await send("Page.enable");
await send("Runtime.enable");
await send("DOM.enable");
const results = [];

await viewport(1440, 900);
await goto(`${baseUrl}/`);
const home = await evaluate(`(() => ({
  route: location.pathname,
  waveLoaded: document.querySelector('.hero-wave-halftone').complete && document.querySelector('.hero-wave-halftone').naturalWidth > 0,
  rollbackHidden: document.querySelector('.hero-contour-desktop').hidden,
  overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
}))()`);
record(results, "I01-home-wave", home.route === "/" && home.waveLoaded && home.rollbackHidden && !home.overflow, home);
await screenshot("home-wave-1440.png");

await goto(`${baseUrl}/guide`);
const guide = await evaluate(`(() => ({
  route: location.pathname,
  current: document.querySelector('a[aria-current="page"]')?.getAttribute('href'),
  sections: document.querySelectorAll('.guide-section').length,
  faq: document.querySelectorAll('.guide-faq details').length,
  overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
}))()`);
record(results, "I02-guide-route", guide.route === "/guide" && guide.current === "/guide" && guide.sections === 6 && guide.faq === 4 && !guide.overflow, guide);
await screenshot("guide-1440.png");

await goto(`${baseUrl}/workspace`);
await selectFile(fixture.replaceAll("\\", "/"));
await evaluate("document.getElementById('analyze').click()");
await waitFor("!document.getElementById('quality-result').hidden");
const quality = await evaluate(`(() => ({
  status: document.getElementById('status-badge').textContent.trim(),
  eligible: !document.getElementById('train').disabled,
  splitCards: document.querySelectorAll('#quality-split-results .split-grid > div').length
}))()`);
record(results, "I03-quality", quality.status === "PASS" && quality.eligible && quality.splitCards === 3, quality);

await evaluate("document.getElementById('wizard-next').click()");
const trainingStartedAt = Date.now();
await evaluate("document.getElementById('train').click()");
await waitFor("['QUEUED','RUNNING'].includes(document.getElementById('workspace-job-status').dataset.status)");
const activeJob = await evaluate("JSON.parse(sessionStorage.getItem('energy-planner.active-job.v1'))");
record(results, "I04-training-start", Boolean(activeJob?.jobId), activeJob);

await evaluate("document.querySelector('a[href=\"/guide\"]').click()");
await waitFor("location.pathname === '/guide'");
await pause(500);
await evaluate("document.querySelector('a[href=\"/workspace\"]').click()");
await waitFor("location.pathname === '/workspace'");
record(results, "I05-navigation-during-training", true, { route: "/workspace", jobId: activeJob.jobId });

await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED'", 300_000);
const training = await evaluate(`(() => ({
  status: document.getElementById('workspace-job-status').dataset.status,
  selectedModel: document.getElementById('selected-model').textContent.trim(),
  runId: document.getElementById('run-id').textContent.trim(),
  metrics: ['xgboost','last-24h','last-168h'].map((id) => document.getElementById('workspace-metric-' + id).textContent.trim())
}))()`);
record(results, "I06-xgboost-training", training.status === "COMPLETED" && training.runId !== "—" && training.metrics.every((value) => value.includes("MAE")), { ...training, elapsedSeconds: (Date.now() - trainingStartedAt) / 1000 });

await evaluate("document.getElementById('open-dashboard').click()");
await waitFor("location.pathname === '/dashboard'");
await evaluate("document.getElementById('run-prediction').click()");
await waitFor("document.getElementById('sample-tag').textContent.includes('실제 예측 결과')", 30_000);
const dashboard = await evaluate(`(() => ({
  total: document.getElementById('total-forecast').textContent.trim(),
  average: document.getElementById('average-forecast').textContent.trim(),
  forecastRows: document.querySelectorAll('#forecast-table-body tr').length,
  dailyBars: document.querySelectorAll('#daily-usage-chart rect').length,
  periods: document.querySelectorAll('#period-composition-list li').length,
  months: document.querySelectorAll('#monthly-usage-list .monthly-usage-item').length,
  aiDisabled: document.getElementById('ai-analyze').disabled,
  aiStatus: document.getElementById('ai-analysis-status').textContent.trim(),
  overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
}))()`);
record(results, "I07-dashboard-prediction", dashboard.total.includes("kWh") && dashboard.average.includes("kWh") && dashboard.forecastRows === 24 && dashboard.dailyBars === 7 && dashboard.periods === 4 && dashboard.months >= 1 && !dashboard.overflow, dashboard);
record(results, "I08-ai-disabled", dashboard.aiDisabled && dashboard.aiStatus.includes("OPENAI_API_KEY"), { aiDisabled: dashboard.aiDisabled, aiStatus: dashboard.aiStatus });
await screenshot("dashboard-prediction-1440.png");

for (const width of [390, 320]) {
  await viewport(width, 844);
  await goto(`${baseUrl}/guide`);
  const guideMobile = await evaluate(`(() => ({
    width: ${width},
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    minNavHeight: Math.min(...[...document.querySelectorAll('.primary-nav a')].map((node) => node.getBoundingClientRect().height)),
    bodyFont: getComputedStyle(document.querySelector('.guide-section p')).fontSize
  }))()`);
  record(results, `I09-guide-responsive-${width}`, !guideMobile.overflow && guideMobile.minNavHeight >= 44 && parseFloat(guideMobile.bodyFont) >= 14, guideMobile);
  await screenshot(`guide-${width}.png`);
  await goto(`${baseUrl}/dashboard`);
  const dashboardMobile = await evaluate(`(() => ({
    width: ${width},
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    chartWidth: Math.round(document.getElementById('forecast-chart').getBoundingClientRect().width),
    viewportWidth: document.documentElement.clientWidth
  }))()`);
  record(results, `I10-dashboard-responsive-${width}`, !dashboardMobile.overflow && dashboardMobile.chartWidth <= dashboardMobile.viewportWidth, dashboardMobile);
  await screenshot(`dashboard-${width}.png`);
}

const resultPayload = {
  generatedAt: new Date().toISOString(),
  jobId: activeJob.jobId,
  trainingElapsedSeconds: (Date.now() - trainingStartedAt) / 1000,
  results,
};
fs.writeFileSync(path.join(outputDir, "browser_qa_results.json"), JSON.stringify(resultPayload, null, 2));
fs.rmSync(fixture, { force: true });
socket.close();
const failed = results.filter((result) => result.status === "FAIL");
console.log(JSON.stringify({ passed: results.length - failed.length, failed: failed.length, jobId: activeJob.jobId, results }, null, 2));
if (failed.length) process.exitCode = 1;
