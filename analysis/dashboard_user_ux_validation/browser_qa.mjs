import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.ENERGY_PLANNER_QA_BASE_URL || "http://127.0.0.1:8765";
const cdpUrl = process.env.ENERGY_PLANNER_QA_CDP_URL || "http://127.0.0.1:9232";
const completedJobId = process.env.ENERGY_PLANNER_QA_JOB_ID;
if (!/^[0-9a-f]{32}$/.test(completedJobId || "")) {
  throw new Error("ENERGY_PLANNER_QA_JOB_ID must identify an existing completed local job");
}
const outputDir = path.resolve("analysis/dashboard_user_ux_validation");
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

async function waitFor(expression, timeout = 20_000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return true;
    await pause(150);
  }
  return false;
}

async function goto(url) {
  await send("Page.navigate", { url });
  if (!await waitFor("document.readyState === 'complete'")) throw new Error(`Navigation timed out: ${url}`);
}

async function viewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await pause(100);
}

async function screenshot(name) {
  const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
}

const checks = [];
function record(name, passed, details) {
  checks.push({ name, status: passed ? "PASS" : "FAIL", details });
}

await send("Page.enable");
await send("Runtime.enable");
await send("DOM.enable");
await viewport(1440, 1000);
await goto(`${baseUrl}/`);
await evaluate("sessionStorage.removeItem('energy-planner.active-job.v1'); location.reload(); true");
await waitFor("document.readyState === 'complete'");
await evaluate("document.documentElement.style.scrollBehavior = 'auto'; true");

const initial = await evaluate(`(() => {
  const primary = document.getElementById("home-primary-cta");
  const dashboard = document.getElementById("dashboard");
  const heading = dashboard.querySelector(".dashboard-heading").getBoundingClientRect();
  const body = dashboard.querySelector(".section-body").getBoundingClientRect();
  return {
    ctaText: document.getElementById("home-cta-label").textContent.trim(),
    ctaTarget: primary.dataset.scrollTarget,
    heroActionLinks: document.querySelectorAll("#landing-home > .actions a").length,
    gateVisible: !document.getElementById("dashboard-gate").hidden,
    resultsHidden: document.getElementById("dashboard-results").hidden,
    gateAction: document.getElementById("dashboard-empty-action").textContent.trim(),
    gateTarget: document.getElementById("dashboard-empty-action").dataset.target,
    headingWidth: Math.round(heading.width),
    bodyWidth: Math.round(body.width),
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
})()`);
record(
  "initial_state_and_cta_roles",
  initial.ctaText === "CSV로 예측 시작하기"
    && initial.ctaTarget === "upload"
    && initial.heroActionLinks === 1
    && initial.gateVisible
    && initial.resultsHidden
    && initial.gateAction === "CSV로 예측 시작하기"
    && initial.gateTarget === "upload",
  initial,
);
record("dashboard_full_width_initial", Math.abs(initial.headingWidth - initial.bodyWidth) <= 2 && initial.overflow === 0, initial);
await evaluate("document.getElementById('dashboard').scrollIntoView({ block: 'start' }); true");
await pause(200);
await screenshot("dashboard-initial-1440.png");

await evaluate(`sessionStorage.setItem("energy-planner.active-job.v1", JSON.stringify({
  jobId: "${completedJobId}",
  context: { timezone: "Asia/Seoul", fileToken: "browser-qa-completed-job" }
})); location.reload(); true`);
await waitFor("document.readyState === 'complete'");
await evaluate("document.documentElement.style.scrollBehavior = 'auto'; true");
const recovered = await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED' && !document.getElementById('run-prediction').hidden", 15_000);
record("completed_job_recovered", recovered, {
  status: await evaluate("document.getElementById('workspace-job-status').dataset.status || ''"),
});
await evaluate("document.getElementById('run-prediction').click(); true");
const predicted = await waitFor("!document.getElementById('dashboard-results').hidden && document.getElementById('forecast-period').textContent.length > 0", 30_000);
record("prediction_completed", predicted, {
  error: await evaluate("document.getElementById('dashboard-error').textContent"),
});

const result = await evaluate(`(() => ({
  period: document.getElementById("forecast-period").textContent.trim(),
  narrative: document.getElementById("forecast-narrative").textContent.trim(),
  total: document.getElementById("total-forecast").textContent.trim(),
  change: document.getElementById("forecast-change").textContent.trim(),
  peakTime: document.getElementById("peak-time").textContent.trim(),
  peakValue: document.getElementById("peak-forecast").textContent.trim(),
  wape: document.getElementById("test-wape").textContent.trim(),
  lastObservation: document.getElementById("data-last-observation").textContent.trim(),
  timezone: document.getElementById("forecast-timezone").textContent.trim(),
  metricCards: document.querySelectorAll(".forecast-stats > .metric").length,
  yAxis: [...document.querySelectorAll("#forecast-chart text")].some((node) => node.textContent.includes("사용량 (kWh)")),
  xTicks: [...document.querySelectorAll("#forecast-chart text")].filter((node) => /시$/.test(node.textContent)).length,
  peakLabel: document.querySelector("#forecast-chart .peak-label text")?.textContent || "",
  tableRows: document.querySelectorAll("#forecast-table-body tr").length,
  topHasRawModel: [...document.querySelectorAll(".forecast-summary, .forecast-stats")].some((node) => /xgboost/i.test(node.textContent)),
  homeCta: document.getElementById("home-cta-label").textContent.trim(),
  homeTarget: document.getElementById("home-primary-cta").dataset.scrollTarget,
  newCsvVisible: !document.getElementById("dashboard-new-csv").hidden,
  aiEnabled: !document.getElementById("ai-analyze").disabled,
  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
}) )()`);
record("dynamic_forecast_period", result.period === "예측 대상 2026.11.01 (일) 00:00–23:00", result.period);
record("decision_summary_and_three_metrics", result.narrative.includes("11월 1일") && result.narrative.includes("직전 24시간") && result.total.includes("kWh") && /[↓↑→]/.test(result.change) && result.metricCards === 3, result);
record("test_wape_and_peak", result.wape === "5.1%" && /오[전후]/.test(result.peakTime) && result.peakValue.includes("kWh"), result);
record("timezone_and_last_observation", result.lastObservation.includes("2026.10.31 (토) 23:00") && result.timezone.includes("Asia/Seoul"), result);
record("chart_axes_peak_and_table", result.yAxis && result.xTicks >= 4 && result.peakLabel.includes("kWh") && result.tableRows === 24, result);
record("result_cta_and_ai_contract", result.homeCta === "예측 결과 보기" && result.homeTarget === "dashboard" && result.newCsvVisible && result.aiEnabled && !result.topHasRawModel, result);
record("desktop_no_horizontal_overflow", result.overflow === 0, result.overflow);

const help = await evaluate(`(() => {
  const details = document.querySelector(".metric-help");
  details.open = true;
  return { open: details.open, text: document.getElementById("test-wape-help").textContent };
})()`);
record("wape_help_disclosure", help.open && help.text.includes("과거 Test 구간") && help.text.includes("보장하는 수치는 아닙니다"), help);

const comparison = await evaluate(`(() => {
  const toggle = document.getElementById("compare-previous");
  toggle.click();
  const svg = document.getElementById("forecast-chart");
  const rect = svg.getBoundingClientRect();
  svg.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, clientX: rect.left + rect.width * .5, clientY: rect.top + rect.height * .5 }));
  return {
    checked: toggle.checked,
    historyLegendVisible: !document.getElementById("history-legend").hidden,
    aria: svg.getAttribute("aria-label"),
    tooltipVisible: !document.getElementById("forecast-tooltip").hidden,
    tooltip: document.getElementById("forecast-tooltip").textContent,
    guideX: document.getElementById("forecast-hover-guide").getAttribute("x1"),
  };
})()`);
record("previous_day_toggle_and_hover", comparison.checked && comparison.historyLegendVisible && comparison.aria.includes("직전 24시간") && comparison.tooltipVisible && comparison.tooltip.includes("예측 사용량") && comparison.tooltip.includes("직전 24시간"), comparison);

await evaluate("document.getElementById('forecast-hour-slider').focus(); document.getElementById('forecast-hour-slider').value = '10'; document.getElementById('forecast-hour-slider').dispatchEvent(new Event('input', { bubbles: true })); true");
await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39, nativeVirtualKeyCode: 39 });
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39, nativeVirtualKeyCode: 39 });
const slider = await evaluate(`({
  value: document.getElementById("forecast-hour-slider").value,
  output: document.getElementById("forecast-selected-value").textContent,
  ariaValue: document.getElementById("forecast-hour-slider").getAttribute("aria-valuetext"),
  focused: document.activeElement.id,
})`);
record("keyboard_and_touch_slider", slider.value === "11" && slider.output.includes("예상") && slider.output.includes("직전 24시간") && slider.ariaValue.includes("kWh") && slider.focused === "forecast-hour-slider", slider);

const details = await evaluate(`(() => {
  const panel = document.getElementById("forecast-validation-details");
  panel.open = true;
  return {
    open: panel.open,
    model: document.getElementById("dashboard-selected-model").textContent,
    rows: document.querySelectorAll("#dashboard-validation-body tr").length,
    selectedCopy: document.querySelector("#dashboard-validation-body tr.selected")?.textContent || "",
  };
})()`);
record("validation_details", details.open && details.model === "XGBoost" && details.rows === 3 && details.selectedCopy.includes("이번 예측에 사용"), details);

await evaluate("document.getElementById('dashboard').scrollIntoView({ block: 'start' }); true");
await pause(250);
await screenshot("dashboard-result-1440.png");
await evaluate("document.querySelector('.chart-panel').scrollIntoView({ block: 'start' }); true");
await pause(120);
await screenshot("dashboard-chart-1440.png");

for (const width of [390, 320]) {
  await viewport(width, 900);
  await evaluate("document.getElementById('dashboard').scrollIntoView({ block: 'start' }); true");
  await pause(300);
  const mobile = await evaluate(`(() => {
    const slider = document.getElementById("forecast-hour-slider");
    const toggle = document.querySelector(".series-toggle");
    const chart = document.getElementById("forecast-chart");
    return {
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      cards: document.querySelectorAll(".forecast-stats > .metric").length,
      chartHeight: Math.round(chart.getBoundingClientRect().height),
      sliderHeight: Math.round(slider.getBoundingClientRect().height),
      toggleHeight: Math.round(toggle.getBoundingClientRect().height),
      svgWidth: chart.viewBox.baseVal.width,
      headingVisible: document.getElementById("forecast-period").getClientRects().length > 0,
    };
  })()`);
  record(`mobile_${width}_layout`, mobile.viewport === mobile.scrollWidth && mobile.cards === 3 && mobile.chartHeight >= 220 && mobile.sliderHeight >= 44 && mobile.toggleHeight >= 44 && mobile.svgWidth === 560 && mobile.headingVisible, mobile);
  await screenshot(`dashboard-result-${width}.png`);
  await evaluate("document.querySelector('.chart-panel').scrollIntoView({ block: 'start' }); true");
  await pause(120);
  await screenshot(`dashboard-chart-${width}.png`);
}

await viewport(1440, 1000);
const beforeNavigation = await evaluate("document.getElementById('total-forecast').textContent");
await evaluate("document.getElementById('dashboard-new-csv').click(); true");
await pause(150);
const navigation = await evaluate(`({
  hash: location.hash,
  total: document.getElementById("total-forecast").textContent,
  resultsVisible: !document.getElementById("dashboard-results").hidden,
})`);
record("new_csv_navigation_preserves_completed_result", navigation.hash === "#upload" && navigation.total === beforeNavigation && navigation.resultsVisible, navigation);

record("runtime_console_clean", runtimeErrors.length === 0 && consoleErrors.length === 0, { runtimeErrors, consoleErrors });
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  total: checks.length,
  passed: checks.filter((item) => item.status === "PASS").length,
  failed: checks.filter((item) => item.status === "FAIL").length,
  checks,
};
fs.writeFileSync(path.join(outputDir, "browser_results.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
socket.close();
