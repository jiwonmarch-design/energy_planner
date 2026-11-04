import fs from "node:fs";
import path from "node:path";

const baseUrl = process.env.ENERGY_PLANNER_QA_BASE_URL || "http://127.0.0.1:8765";
const cdpUrl = process.env.ENERGY_PLANNER_QA_CDP_URL || "http://127.0.0.1:9232";
const outputDir = path.resolve("analysis/data_preparation_validation");
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
await goto(`${baseUrl}/`);
await evaluate("sessionStorage.removeItem('energy-planner.active-job.v1');location.reload();true");
await waitFor("document.readyState === 'complete'");

const initial = await evaluate(`(() => ({
  steps: document.querySelectorAll('[data-workflow-step]').length,
  panels: document.querySelectorAll('[data-step-panel]').length,
  hasOldQualitySection: Boolean(document.getElementById('quality')),
  qualityInsideUpload: document.getElementById('upload').contains(document.getElementById('quality-result')),
  title: document.getElementById('upload-title').textContent,
  status: document.getElementById('quality-heading-status').textContent,
  buttonDisabled: document.getElementById('analyze').disabled,
  awaitingHeight: Math.round(document.getElementById('empty-state').getBoundingClientRect().height),
  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
}))()`);
record("initial_combined_data_preparation", initial.steps === 5 && initial.panels === 5 && !initial.hasOldQualitySection && initial.qualityInsideUpload && initial.title.includes("업로드 및 품질 진단") && initial.status === "업로드 대기" && initial.buttonDisabled && initial.awaitingHeight < 180 && initial.overflow === 0, initial);
await evaluate("document.getElementById('upload').scrollIntoView();true");
await screenshot("combined-initial-1440.png", true);

const selected = await evaluate(`(async () => {
  const start = Date.UTC(2025, 0, 1, 0, 0, 0);
  const rows = ['timestamp,kwh'];
  for (let index = 0; index < 24 * 180; index += 1) {
    const timestamp = new Date(start + index * 3600000).toISOString().replace('.000Z', 'Z');
    const value = 100 + 18 * Math.sin(index / 24 * Math.PI * 2) + (index % 7) * 1.5;
    rows.push(timestamp + ',' + value.toFixed(3));
  }
  const file = new File([rows.join('\\n')], 'quality-pass-180-days.csv', { type: 'text/csv', lastModified: 1 });
  await readFile(file);
  return {
    enabled: !document.getElementById('analyze').disabled,
    status: document.getElementById('quality-heading-status').textContent,
    title: document.getElementById('quality-empty-title').textContent,
    preview: !document.getElementById('quality-preview').hidden,
    sameSection: document.getElementById('upload').contains(document.getElementById('quality-preview')),
  };
})()`);
record("file_selection_prepares_inline_diagnosis", selected.enabled && selected.status === "진단 대기" && selected.title.includes("진단") && selected.preview && selected.sameSection, selected);

await evaluate("document.getElementById('analyze').click();true");
const loading = await waitFor("document.getElementById('upload').getAttribute('aria-busy') === 'true'", 3_000);
const completed = await waitFor("!document.getElementById('quality-result').hidden", 30_000);
const result = await evaluate(`(() => ({
  loadingObserved: ${loading},
  cards: document.querySelectorAll('#quality-cards .metric-card').length,
  details: document.querySelectorAll('#quality-detail-list .detail-row').length,
  nextVisible: !document.getElementById('quality-next-actions').hidden,
  buttonText: document.getElementById('analyze').textContent.trim(),
  status: document.getElementById('quality-heading-status').textContent,
  focused: document.activeElement === document.getElementById('quality-result-title'),
  trainingEnabled: !document.getElementById('train').disabled,
  firstStepStatus: document.querySelector('[data-workflow-step="1"]').dataset.status,
  secondStepStatus: document.querySelector('[data-workflow-step="2"]').dataset.status,
  sameSection: document.getElementById('upload').contains(document.getElementById('quality-result')),
}))()`);
record("diagnosis_renders_inline_and_unlocks_training", completed && result.loadingObserved && result.cards === 4 && result.details === 4 && result.nextVisible && result.buttonText === "데이터 품질 다시 진단하기" && result.status === "PASS" && result.focused && result.trainingEnabled && result.firstStepStatus === "complete" && result.secondStepStatus === "current" && result.sameSection, result);
await screenshot("combined-result-1440.png", true);

await viewport(390, 844);
const mobile390 = await evaluate(`(() => ({
  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  minButton: Math.min(...[...document.querySelectorAll('.btn,.step-button')].filter((item) => item.offsetParent !== null).map((item) => item.getBoundingClientRect().height)),
  resultVisible: !document.getElementById('quality-result').hidden,
}))()`);
record("mobile_390_layout", mobile390.overflow === 0 && mobile390.minButton >= 44 && mobile390.resultVisible, mobile390);
await screenshot("combined-result-390.png", true);

await viewport(320, 844);
const mobile320 = await evaluate(`(() => ({
  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  minButton: Math.min(...[...document.querySelectorAll('.btn,.step-button')].filter((item) => item.offsetParent !== null).map((item) => item.getBoundingClientRect().height)),
}))()`);
record("mobile_320_layout", mobile320.overflow === 0 && mobile320.minButton >= 44, mobile320);
await screenshot("combined-result-320.png", true);

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
