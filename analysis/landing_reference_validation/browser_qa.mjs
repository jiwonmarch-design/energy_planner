import { mkdir, writeFile } from "node:fs/promises";

const baseUrl = "http://127.0.0.1:8765";
const cdpUrl = "http://127.0.0.1:9231";
const outputDir = new URL("./", import.meta.url);
await mkdir(outputDir, { recursive: true });

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
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
};
const waitFor = async (expression, timeout = 10_000) => {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return true;
    await wait(100);
  }
  return false;
};
const screenshot = async (name) => {
  const metrics = await send("Page.getLayoutMetrics");
  const width = Math.ceil(metrics.cssContentSize.width);
  const height = Math.ceil(metrics.cssContentSize.height);
  const result = await send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: { x: 0, y: 0, width, height, scale: 1 },
  });
  await writeFile(new URL(name, outputDir), Buffer.from(result.data, "base64"));
};

await send("Page.enable");
await send("Runtime.enable");
const checks = [];
const record = (name, passed, details) => checks.push({ name, status: passed ? "PASS" : "FAIL", details });

for (const [width, height] of [[1440, 900], [390, 844], [320, 844]]) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await send("Page.navigate", { url: `${baseUrl}/` });
  await waitFor("document.readyState === 'complete' && document.querySelectorAll('#landing-wave circle').length > 100");
  await wait(350);

  const state = await evaluate(`(() => ({
    route: location.pathname,
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    activeNav: document.querySelector('.primary-nav [aria-current="page"]')?.getAttribute('href') || '',
    headline: document.getElementById('hero-title')?.innerText || '',
    waveDots: document.querySelectorAll('#landing-wave circle').length,
    workspaceHref: document.getElementById('home-primary-cta')?.getAttribute('href') || '',
    dashboardHref: document.querySelector('.landing-button.secondary')?.getAttribute('href') || '',
    sampleBadge: document.querySelector('.landing-sample-badge')?.textContent.trim() || '',
    sampleNotice: document.querySelector('.landing-demo-notice')?.textContent.trim() || '',
    hiddenPages: [...document.querySelectorAll('[data-page]:not([data-page="/"])')].every((node) => node.hidden),
    navMinHeight: Math.round(document.querySelector('.primary-nav a')?.getBoundingClientRect().height || 0),
    primaryMinHeight: Math.round(document.getElementById('home-primary-cta')?.getBoundingClientRect().height || 0)
  }))()`);
  record(`landing_${width}_route_and_copy`, state.route === "/" && state.activeNav === "/" && state.headline.includes("더 나은 결정을"), state);
  record(`landing_${width}_interactive_wave`, state.waveDots > 100, { waveDots: state.waveDots });
  record(`landing_${width}_routing`, state.workspaceHref === "/workspace" && state.dashboardHref === "/dashboard", { workspaceHref: state.workspaceHref, dashboardHref: state.dashboardHref });
  record(`landing_${width}_sample_disclosure`, state.sampleBadge.includes("예시") && state.sampleNotice.includes("실제 예측 결과가 아닙니다"), { sampleBadge: state.sampleBadge, sampleNotice: state.sampleNotice });
  record(`landing_${width}_no_overflow`, state.scrollWidth === state.viewport, { viewport: state.viewport, scrollWidth: state.scrollWidth });
  record(`landing_${width}_app_pages_preserved`, state.hiddenPages, { hiddenPages: state.hiddenPages });
  if (width < 700) record(`landing_${width}_touch_targets`, state.navMinHeight >= 44 && state.primaryMinHeight >= 44, { navMinHeight: state.navMinHeight, primaryMinHeight: state.primaryMinHeight });

  await evaluate("document.querySelector('[data-landing-step=\"2\"]').click(); true");
  const step = await evaluate(`({
    selected: document.querySelector('[data-landing-step="2"]').getAttribute('aria-selected'),
    content: document.getElementById('landing-step-content').innerText
  })`);
  record(`landing_${width}_step_interaction`, step.selected === "true" && step.content.includes("XGBoost 학습 및 평가"), step);

  await evaluate("document.querySelector('[data-landing-view=\"history\"]').click(); true");
  const chart = await evaluate(`({
    active: document.querySelector('[data-landing-view="history"]').classList.contains('is-active'),
    paths: document.querySelectorAll('#landing-chart path').length,
    axis: document.getElementById('landing-axis-start').textContent
  })`);
  record(`landing_${width}_chart_interaction`, chart.active && chart.paths === 1 && chart.axis.includes("10월 30일"), chart);
  await screenshot(`landing-reference-${width}.png`);
}

await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: `${baseUrl}/` });
await waitFor("document.readyState === 'complete'");
await evaluate("document.querySelector('.landing-button.secondary').click(); true");
const dashboardNavigation = await waitFor("location.pathname === '/dashboard' && !document.getElementById('dashboard-page').hidden");
record("dashboard_cta_navigation", dashboardNavigation, { route: await evaluate("location.pathname") });
await send("Page.navigate", { url: `${baseUrl}/` });
await waitFor("document.readyState === 'complete'");
await evaluate("document.getElementById('home-primary-cta').click(); true");
const workspaceNavigation = await waitFor("location.pathname === '/workspace' && !document.getElementById('workspace-page').hidden");
record("workspace_cta_navigation", workspaceNavigation, { route: await evaluate("location.pathname") });

await send("Page.navigate", { url: `${baseUrl}/workspace` });
await waitFor("document.readyState === 'complete'");
const workspace = await evaluate(`({
  route: location.pathname,
  visible: !document.getElementById('workspace-page').hidden,
  fileInput: Boolean(document.getElementById('csv-file')),
  diagnoseButton: Boolean(document.getElementById('analyze'))
})`);
record("workspace_route_regression", workspace.route === "/workspace" && workspace.visible && workspace.fileInput && workspace.diagnoseButton, workspace);

const results = {
  executed_at: new Date().toISOString(),
  browser: "Chrome headless actual browser",
  checks,
  summary: { pass: checks.filter((item) => item.status === "PASS").length, fail: checks.filter((item) => item.status === "FAIL").length },
};
await writeFile(new URL("browser_results.json", outputDir), `${JSON.stringify(results, null, 2)}\n`, "utf8");
console.log(JSON.stringify(results, null, 2));
socket.close();
