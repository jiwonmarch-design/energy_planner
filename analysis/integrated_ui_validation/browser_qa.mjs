import fs from "node:fs";
import path from "node:path";

const baseUrl = "http://127.0.0.1:8765";
const cdpUrl = "http://127.0.0.1:9231";
const outputDir = path.resolve(process.env.QA_OUTPUT_DIR || "analysis/integrated_ui_validation");
const fixture = path.join(outputDir, "synthetic_180_days.csv");
fs.mkdirSync(outputDir, { recursive: true });

const rows = ["timestamp,kwh"];
const origin = Date.parse("2026-01-01T00:00:00Z");
for (let hour = 0; hour < 180 * 24; hour += 1) {
  const value = 18 + 4 * Math.sin((2 * Math.PI * (hour % 24)) / 24) + 2 * Math.sin((2 * Math.PI * (hour % 168)) / 168);
  rows.push(`${new Date(origin + hour * 3_600_000).toISOString()},${value.toFixed(4)}`);
}
fs.writeFileSync(fixture, rows.join("\n"));

const targets = await fetch(`${cdpUrl}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("Chrome page target not found");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let requestId = 0;
const pending = new Map();
const consoleErrors = [];
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Runtime.exceptionThrown") consoleErrors.push(message.params.exceptionDetails?.text || "Uncaught exception");
  if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") consoleErrors.push(message.params.args?.map((item) => item.value || item.description).join(" ") || "console.error");
  const callbacks = pending.get(message.id);
  if (!callbacks) return;
  pending.delete(message.id);
  if (message.error) callbacks.reject(new Error(message.error.message));
  else callbacks.resolve(message.result);
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++requestId;
  pending.set(id, { resolve, reject });
  socket.send(JSON.stringify({ id, method, params }));
});
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const evaluate = async (expression) => {
  const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
};
const waitFor = async (expression, timeout = 15_000) => {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await wait(100);
  }
  throw new Error(`Timed out: ${expression}`);
};
const screenshot = async (name) => {
  const metrics = await send("Page.getLayoutMetrics");
  const { width, height } = metrics.cssContentSize;
  const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width, height, scale: 1 } });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
};
const record = (results, name, passed, details) => results.push({ name, status: passed ? "PASS" : "FAIL", details });

await send("Page.enable");
await send("Runtime.enable");
await send("DOM.enable");
const results = [];

for (const [width, height] of [[1440, 900], [390, 844], [320, 844]]) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await send("Page.navigate", { url: `${baseUrl}/` });
  await waitFor("document.readyState === 'complete' && document.querySelectorAll('#landing-wave circle').length > 100");
  await wait(250);
  const layout = await evaluate(`(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    steps: document.querySelectorAll('[data-integrated-target]').length,
    guideLinks: [...document.querySelectorAll('.primary-nav a')].filter((link) => link.textContent.includes('Guide')).length,
    fakeKpisVisible: [...document.querySelectorAll('.landing-kpis')].some((node) => node.getClientRects().length > 0),
    panelsVisible: [...document.querySelectorAll('[data-step-panel]')].every((node) => !node.hidden && getComputedStyle(node).display !== 'none'),
    touchTargets: Math.min(...[...document.querySelectorAll('.primary-nav a, .integrated-step')].map((node) => node.getBoundingClientRect().height))
    ,bodyBackground: getComputedStyle(document.body).backgroundColor
    ,cardBackground: getComputedStyle(document.querySelector('.ivory-upload-card')).backgroundColor
    ,heroHeight: Math.round(document.getElementById('landing-home').getBoundingClientRect().height)
    ,waveDots: document.querySelectorAll('#landing-wave circle').length
    ,offenders: [...document.querySelectorAll('body *')].map((node) => { const rect = node.getBoundingClientRect(); return {tag: node.tagName, id: node.id, className: String(node.className || ''), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width)}; }).filter((item) => item.right > document.documentElement.clientWidth + 1 || item.left < -1).slice(0, 8)
  }))()`);
  const heroMatches = width > 800 ? layout.heroHeight >= 345 && layout.heroHeight <= 370 : layout.heroHeight >= 430;
  record(results, `layout-${width}`, layout.scrollWidth === layout.viewport && layout.steps === 4 && layout.guideLinks === 0 && !layout.fakeKpisVisible && layout.panelsVisible && layout.touchTargets >= 44 && layout.bodyBackground === 'rgb(248, 247, 243)' && layout.cardBackground === 'rgb(255, 255, 255)' && layout.waveDots === 1056 && heroMatches, layout);
  await screenshot(`integrated-${width}.png`);
}

await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: `${baseUrl}/workspace` });
await waitFor("document.readyState === 'complete'");
const documentNode = await send("DOM.getDocument", { depth: 1 });
const inputNode = await send("DOM.querySelector", { nodeId: documentNode.root.nodeId, selector: "#csv-file" });
await send("DOM.setFileInputFiles", { nodeId: inputNode.nodeId, files: [fixture.replaceAll("\\", "/")] });
await evaluate("document.getElementById('csv-file').dispatchEvent(new Event('change', { bubbles: true }))");
await waitFor("!document.getElementById('file-info').hidden && !document.getElementById('analyze').disabled");
await evaluate("document.getElementById('analyze').click()");
await waitFor("!document.getElementById('quality-result').hidden");
const quality = await evaluate(`(() => ({
  route: location.pathname,
  status: document.getElementById('status-badge').textContent.trim(),
  trainEnabled: !document.getElementById('train').disabled,
  fileDeleteVisible: !document.getElementById('clear-file').hidden,
  dashboardEmpty: document.getElementById('total-forecast').textContent.trim() === '—',
  fakeNoticeVisible: [...document.querySelectorAll('.landing-demo-notice')].some((node) => node.getClientRects().length > 0)
}))()`);
record(results, "real-quality-api", quality.status === "PASS" && quality.trainEnabled && quality.fileDeleteVisible && quality.dashboardEmpty && !quality.fakeNoticeVisible, quality);

await evaluate("document.querySelector('[data-integrated-target=\"dashboard-page\"]').click()");
await waitFor("location.pathname === '/dashboard'");
const navigation = await evaluate(`(() => ({
  route: location.pathname,
  activeStep: document.querySelector('.integrated-step[aria-current="step"]')?.dataset.integratedTarget,
  modelState: document.getElementById('model-state').textContent.trim(),
  trainingStatus: document.getElementById('workspace-job-status').textContent.trim()
}))()`);
record(results, "sticky-navigation", navigation.route === "/dashboard" && navigation.activeStep === "dashboard-page", navigation);

await evaluate("document.getElementById('clear-file').click()");
await waitFor("document.getElementById('file-info').hidden");
const cleared = await evaluate(`(() => ({ fileInfoHidden: document.getElementById('file-info').hidden, analyzeDisabled: document.getElementById('analyze').disabled, qualityHidden: document.getElementById('quality-result').hidden }))()`);
record(results, "file-delete-reset", cleared.fileInfoHidden && cleared.analyzeDisabled && cleared.qualityHidden, cleared);

await evaluate(`(() => {
  drawPredictionChart(Array.from({length: 24}, (_, index) => 10 + index / 10), Array.from({length: 24}, (_, index) => 12 + index / 8));
  const chart = document.getElementById('forecast-chart');
  const rect = chart.getBoundingClientRect();
  chart.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: rect.left + rect.width * 0.75, clientY: rect.top + 40 }));
})()`);
const tooltip = await evaluate(`(() => ({
  visible: !document.getElementById('forecast-tooltip').hidden,
  text: document.getElementById('forecast-tooltip').textContent.trim()
}))()`);
record(results, "forecast-hover-tooltip", tooltip.visible && tooltip.text.includes("kWh") && tooltip.text.includes("예측"), tooltip);
await evaluate("drawEmptyChart()");

await evaluate(`(() => {
  renderPeriodComposition([
    {label: '00–05시', share: .2}, {label: '06–11시', share: .3}, {label: '12–17시', share: .35}, {label: '18–23시', share: .15}
  ]);
  const donut = document.getElementById('period-donut');
  const rect = donut.getBoundingClientRect();
  donut.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: rect.right - 4, clientY: rect.top + rect.height / 2 }));
})()`);
const usageTooltip = await evaluate(`(() => ({
  visible: !document.getElementById('usage-tooltip').hidden,
  text: document.getElementById('usage-tooltip').textContent.trim()
}))()`);
record(results, "usage-hover-tooltip", usageTooltip.visible && usageTooltip.text.includes("%"), usageTooltip);
await evaluate("hideUsageTooltip()");
record(results, "console-errors", consoleErrors.length === 0, consoleErrors);

const payload = { generatedAt: new Date().toISOString(), results };
fs.writeFileSync(path.join(outputDir, "browser_qa_results.json"), JSON.stringify(payload, null, 2));
fs.rmSync(fixture, { force: true });
socket.close();
const failed = results.filter((result) => result.status === "FAIL");
console.log(JSON.stringify({ passed: results.length - failed.length, failed: failed.length, results }, null, 2));
if (failed.length) process.exitCode = 1;
