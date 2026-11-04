import { writeFile } from "node:fs/promises";

const baseUrl = "http://127.0.0.1:8765";
const outputDir = new URL("./", import.meta.url);
const tabs = await fetch("http://127.0.0.1:9229/json/list").then((response) => response.json());
const target = tabs.find((tab) => tab.type === "page" && tab.url.startsWith(baseUrl));
if (!target) throw new Error("Energy Planner browser target was not found");

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let requestId = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const resolve = pending.get(message.id);
  if (!resolve) return;
  pending.delete(message.id);
  resolve(message.result);
});
const send = (method, params = {}) => new Promise((resolve) => {
  const id = ++requestId;
  pending.set(id, resolve);
  socket.send(JSON.stringify({ id, method, params }));
});
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const evaluate = async (expression) => {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true });
  return result.result.value;
};
const waitFor = async (expression, timeout = 15_000) => {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return true;
    await wait(200);
  }
  return false;
};
const screenshot = async (name) => {
  const image = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(new URL(name, outputDir), Buffer.from(image.data, "base64"));
};

await send("Page.enable");
await send("Runtime.enable");
const checks = [];
const record = (name, passed, details) => checks.push({ name, status: passed ? "PASS" : "FAIL", details });

for (const width of [390, 320]) {
  await send("Emulation.setDeviceMetricsOverride", {
    width,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });

  await send("Page.navigate", { url: `${baseUrl}/guide` });
  await waitFor("document.readyState === 'complete'");
  await wait(400);
  const guide = await evaluate(`(() => ({
    route: location.pathname,
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    navHeight: document.querySelector('.primary-nav a')?.getBoundingClientRect().height || 0,
    active: document.querySelector('.primary-nav a[aria-current="page"]')?.getAttribute('href') || ''
  }))()`);
  record(`guide_${width}_direct_route`, guide.route === "/guide" && guide.active === "/guide", guide);
  record(`guide_${width}_no_horizontal_overflow`, guide.scrollWidth === guide.viewport, guide);
  record(`guide_${width}_touch_target`, guide.navHeight >= 44, guide);
  await screenshot(`guide-postfix-${width}.png`);

  await send("Page.navigate", { url: `${baseUrl}/dashboard` });
  await waitFor("document.readyState === 'complete'");
  const recovered = await waitFor("document.getElementById('job-status')?.dataset.status === 'COMPLETED'");
  const predictionReady = await waitFor("document.getElementById('run-prediction') && !document.getElementById('run-prediction').disabled");
  if (width === 390 && recovered && predictionReady) {
    await evaluate("document.getElementById('run-prediction').click(); true");
    await waitFor("document.querySelectorAll('#forecast-table-body tr').length === 24", 30_000);
  }
  const dashboard = await evaluate(`(() => ({
    route: location.pathname,
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    jobStatus: document.getElementById('job-status')?.dataset.status || '',
    predictionEnabled: !document.getElementById('run-prediction')?.disabled,
    forecastRows: document.querySelectorAll('#forecast-table-body tr').length,
    resultKind: document.getElementById('sample-tag')?.textContent.trim() || '',
    aiDisabled: Boolean(document.getElementById('ai-analyze')?.disabled),
    chartWidth: Math.ceil(document.getElementById('forecast-chart')?.getBoundingClientRect().width || 0)
  }))()`);
  record(`dashboard_${width}_restart_recovery`, recovered && dashboard.jobStatus === "COMPLETED", dashboard);
  record(`dashboard_${width}_prediction_available`, predictionReady && dashboard.predictionEnabled, dashboard);
  record(`dashboard_${width}_no_horizontal_overflow`, dashboard.scrollWidth === dashboard.viewport, dashboard);
  record(`dashboard_${width}_chart_fits`, dashboard.chartWidth <= dashboard.viewport, dashboard);
  if (width === 390) {
    record("dashboard_prediction_24_rows", dashboard.forecastRows === 24, dashboard);
    record("dashboard_ai_missing_key_safe_state", dashboard.aiDisabled, dashboard);
  }
  await screenshot(`dashboard-postfix-${width}.png`);
}

const result = {
  executed_at: new Date().toISOString(),
  browser: "Chrome CDP actual browser session",
  training_reexecuted: false,
  checks,
  summary: {
    pass: checks.filter((item) => item.status === "PASS").length,
    fail: checks.filter((item) => item.status === "FAIL").length,
  },
};
await writeFile(new URL("post_fix_browser_results.json", outputDir), JSON.stringify(result, null, 2) + "\n", "utf8");
console.log(JSON.stringify(result, null, 2));
socket.close();
