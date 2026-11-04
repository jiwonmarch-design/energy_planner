import fs from "node:fs";
import path from "node:path";

const baseUrl = "http://127.0.0.1:8765";
const cdpUrl = "http://127.0.0.1:9232";
const outputDir = path.resolve("analysis/forecast_home_validation");
const fixture = path.join(outputDir, "synthetic_180_days.csv");
fs.mkdirSync(outputDir, { recursive: true });

const rows = ["timestamp,kwh"];
const origin = Date.parse("2026-01-01T00:00:00Z");
for (let hour = 0; hour < 180 * 24; hour += 1) {
  const daily = 4.5 * Math.sin((2 * Math.PI * (hour % 24)) / 24);
  const weekly = 2.2 * Math.sin((2 * Math.PI * (hour % 168)) / 168);
  const occupied = hour % 24 >= 8 && hour % 24 <= 19 ? 4 : 0;
  rows.push(`${new Date(origin + hour * 3_600_000).toISOString()},${(24 + daily + weekly + occupied).toFixed(4)}`);
}
if (!fs.existsSync(fixture)) fs.writeFileSync(fixture, rows.join("\n"));

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
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Runtime.exceptionThrown") runtimeErrors.push(message.params.exceptionDetails.text);
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
    await pause(200);
  }
  return false;
}
async function goto(url) {
  await send("Page.navigate", { url });
  if (!await waitFor("document.readyState === 'complete'")) throw new Error(`Navigation timed out: ${url}`);
}
async function viewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
}
async function screenshot(name) {
  const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
}
async function selectFile(filePath) {
  const document = await send("DOM.getDocument", { depth: 1 });
  const input = await send("DOM.querySelector", { nodeId: document.root.nodeId, selector: "#csv-file" });
  await send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [filePath] });
  await evaluate("document.getElementById('csv-file').dispatchEvent(new Event('change', { bubbles: true })); true");
  return waitFor("!document.getElementById('file-info').hidden");
}

const checks = [];
const record = (name, passed, details) => checks.push({ name, status: passed ? "PASS" : "FAIL", details });
await send("Page.enable");
await send("Runtime.enable");
await send("DOM.enable");

for (const [width, height] of [[1440, 900], [390, 844], [320, 844]]) {
  await viewport(width, height);
  await goto(`${baseUrl}/`);
  await pause(250);
  const hero = await evaluate(`(() => {
    const title = document.getElementById('hero-title');
    const energy = document.getElementById('brand-energy-toggle');
    return {
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      titleOverflow: title.scrollWidth > title.clientWidth,
      title: title.textContent.replace(/\\s+/g, ' ').trim(),
      energyColor: getComputedStyle(energy).color,
      plannerColor: getComputedStyle(document.querySelector('.brand-planner')).color,
      mini: document.querySelector('.brand-mini').textContent,
      buttonHeight: Math.round(document.getElementById('home-primary-cta').getBoundingClientRect().height),
      energyTag: energy.tagName,
      curveDisclosure: document.querySelector('.brand-curve').getAttribute('aria-label')
    };
  })()`);
  record(`hero_${width}_layout`, hero.scrollWidth === hero.viewport && !hero.titleOverflow, hero);
  record(`hero_${width}_brand`, /Energy\s*Planner\s*mini/.test(hero.title) && hero.mini === "mini" && hero.energyColor !== hero.plannerColor, hero);
  record(`hero_${width}_accessibility`, hero.energyTag === "BUTTON" && hero.curveDisclosure.includes("실제 데이터 또는 모델 예측값이 아닙니다"), hero);
  if (width <= 390) record(`hero_${width}_touch_target`, hero.buttonHeight >= 44, { buttonHeight: hero.buttonHeight });
  await screenshot(`forecast-home-${width}.png`);
}

await viewport(1440, 900);
await goto(`${baseUrl}/`);
const initialInteraction = await evaluate(`(() => {
  const button = document.getElementById('brand-energy-toggle');
  button.click();
  return { pressed: button.getAttribute('aria-pressed'), active: document.getElementById('landing-home').classList.contains('brand-curve-on') };
})()`);
record("hero_click_pins_curve", initialInteraction.pressed === "true" && initialInteraction.active, initialInteraction);
await evaluate("document.getElementById('brand-energy-toggle').focus(); true");
await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
const keyboardInteraction = await evaluate(`({
  pressed: document.getElementById('brand-energy-toggle').getAttribute('aria-pressed'),
  active: document.getElementById('landing-home').classList.contains('brand-curve-on')
})`);
record("hero_keyboard_toggles_curve", keyboardInteraction.pressed === "false" && !keyboardInteraction.active, keyboardInteraction);

await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
const reducedMotion = await evaluate(`(() => {
  const past = document.querySelector('.brand-curve-past');
  const future = document.querySelector('.brand-curve-future');
  return { past: getComputedStyle(past).transitionDuration, future: getComputedStyle(future).transitionDuration };
})()`);
record("hero_reduced_motion", reducedMotion.past === "0s" && reducedMotion.future === "0s", reducedMotion);
await send("Emulation.setEmulatedMedia", { features: [] });

const cta = await evaluate(`(() => {
  document.getElementById('home-primary-cta').click();
  return { hash: location.hash, target: document.getElementById('home-primary-cta').dataset.scrollTarget };
})()`);
record("hero_primary_cta", ["#upload", "#dashboard"].includes(cta.hash) && cta.hash === `#${cta.target}`, cta);
await evaluate("document.querySelector('.topnav a[href=\"#dashboard\"]').click(); true");
record("header_dashboard_navigation", await waitFor("location.hash === '#dashboard'"), { hash: await evaluate("location.hash") });

await evaluate("document.querySelector('.topnav a[href=\"#upload\"]').click(); true");
record("csv_file_selected", await selectFile(fixture), { fixture });
await evaluate("document.getElementById('analyze').click(); true");
const diagnosed = await waitFor("!document.getElementById('quality-result').hidden && !document.getElementById('train').disabled", 30_000);
const quality = await evaluate(`({
  status: document.getElementById('status-badge').textContent,
  eligibility: document.getElementById('eligibility').textContent,
  trainEnabled: !document.getElementById('train').disabled,
  metricCards: document.querySelectorAll('#quality-cards .metric-card').length,
  detailRows: document.querySelectorAll('#quality-detail-list .detail-row').length,
  detailLabels: [...document.querySelectorAll('#quality-detail-list .detail-state')].map((node) => node.textContent.trim()),
  passIcons: document.querySelectorAll('#quality-detail-list .detail-state[data-state="pass"] .detail-state-icon').length,
  stepBarBorderTop: getComputedStyle(document.querySelector('.sticky-steps')).borderTopWidth,
  stepBarBorderBottom: getComputedStyle(document.querySelector('.sticky-steps')).borderBottomWidth,
  completedStepShadow: getComputedStyle(document.querySelector('.step-button[data-status="complete"]')).boxShadow,
  workflowBorderBottom: getComputedStyle(document.getElementById('quality')).borderBottomWidth,
  heroAccentLine: getComputedStyle(document.querySelector('.hero'), '::after').content
})`);
record("real_csv_quality_flow", diagnosed && quality.trainEnabled && quality.status === "PASS" && quality.metricCards === 4 && quality.detailRows === 4 && quality.passIcons === 4 && quality.detailLabels.join('|') === "통과|통과|통과|가능" && quality.stepBarBorderTop === "0px" && quality.stepBarBorderBottom === "1px" && quality.completedStepShadow === "none" && quality.workflowBorderBottom === "0px" && quality.heroAccentLine === "none", quality);
await evaluate("document.documentElement.style.scrollBehavior = 'auto'; document.getElementById('quality').scrollIntoView({ block: 'start' }); true");
await pause(350);
await screenshot("forecast-quality-1440.png");

let trainingCompleted = await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED'", 5_000);
if (!trainingCompleted) {
  await evaluate("document.getElementById('train').click(); true");
  const progressObserved = await waitFor("Number(document.getElementById('training-progressbar').getAttribute('aria-valuenow')) > 5 && Number(document.getElementById('training-progressbar').getAttribute('aria-valuenow')) < 100", 30_000);
  const activeProgress = await evaluate(`({
    visible: !document.getElementById('training-progress').hidden,
    value: Number(document.getElementById('training-progressbar').getAttribute('aria-valuenow')),
    percent: document.getElementById('training-percent').textContent,
    buttons: document.querySelectorAll('#training-actions button').length
  })`);
  record("determinate_training_progress", progressObserved && activeProgress.visible && activeProgress.value > 5 && activeProgress.value < 100 && activeProgress.buttons === 1, activeProgress);
  trainingCompleted = await waitFor("document.getElementById('workspace-job-status').dataset.status === 'COMPLETED'", 240_000);
}
const training = await evaluate(`({
  status: document.getElementById('workspace-job-status').dataset.status || '',
  resultsVisible: !document.getElementById('workspace-model-results').hidden,
  testPolicy: document.getElementById('test-evaluation-note').textContent,
  progressVisible: !document.getElementById('training-progress').hidden,
  progressValue: Number(document.getElementById('training-progressbar').getAttribute('aria-valuenow')),
  progressPercent: document.getElementById('training-percent').textContent,
  trainingButtons: document.querySelectorAll('#training-actions button').length,
  predictionVisible: !document.getElementById('run-prediction').hidden
})`);
record("xgboost_training_and_evaluation", trainingCompleted && training.resultsVisible && training.testPolicy.includes("Test는 모델 선택에 사용하지 않으며") && training.progressVisible && training.progressValue === 100 && training.progressPercent === "100%" && training.trainingButtons === 1 && training.predictionVisible, training);
await evaluate("document.documentElement.style.scrollBehavior = 'auto'; document.getElementById('training').scrollIntoView({ block: 'start' }); true");
await pause(350);
await screenshot("forecast-training-1440.png");

if (trainingCompleted) {
  await evaluate("document.getElementById('run-prediction').click(); true");
  const predicted = await waitFor("document.getElementById('total-forecast').textContent !== '—'", 45_000);
  const dashboard = await evaluate(`({
    total: document.getElementById('total-forecast').textContent,
    model: document.getElementById('selected-model').textContent,
    tag: document.getElementById('sample-tag').textContent,
    points: document.querySelectorAll('#forecast-chart circle').length,
    aiStatus: document.getElementById('ai-analysis-status').textContent
  })`);
  record("saved_model_prediction_dashboard", predicted && dashboard.total !== "—" && dashboard.tag.includes("실제"), dashboard);
  await evaluate("document.getElementById('dashboard').scrollIntoView({ behavior: 'auto', block: 'start' }); true");
  await pause(350);
  await screenshot("forecast-dashboard-1440.png");
  for (const width of [390, 320]) {
    await viewport(width, 844);
    await evaluate("document.documentElement.style.scrollBehavior = 'auto'; document.getElementById('dashboard').scrollIntoView({ block: 'start' }); true");
    await pause(200);
    const mobileDashboard = await evaluate(`({
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      total: document.getElementById('total-forecast').textContent,
      cards: document.querySelectorAll('#dashboard .panel').length
    })`);
    record(`dashboard_${width}_layout`, mobileDashboard.viewport === mobileDashboard.scrollWidth && mobileDashboard.total !== "—" && mobileDashboard.cards >= 6, mobileDashboard);
    await screenshot(`forecast-dashboard-${width}.png`);
  }
}

record("runtime_console_errors", runtimeErrors.length === 0, runtimeErrors);
const results = {
  executed_at: new Date().toISOString(),
  browser: "Chrome 156 headless via CDP",
  fixture: "synthetic_180_days.csv",
  checks,
  summary: {
    pass: checks.filter((item) => item.status === "PASS").length,
    fail: checks.filter((item) => item.status === "FAIL").length,
  },
};
fs.writeFileSync(path.join(outputDir, "browser_results.json"), `${JSON.stringify(results, null, 2)}\n`);
console.log(JSON.stringify(results, null, 2));
socket.close();
