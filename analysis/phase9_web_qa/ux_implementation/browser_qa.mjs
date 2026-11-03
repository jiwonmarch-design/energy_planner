import fs from "node:fs";
import path from "node:path";

const baseUrl = "http://127.0.0.1:8765";
const mainCsv = "C:/Users/aicam/Downloads/energy_planner_test_office_2026-04_to_2026-10.csv";
const replacementCsv = path.resolve("analysis/phase9_web_qa/ux_implementation/qa_replacement.csv").replaceAll("\\", "/");
const outputDir = path.resolve("analysis/phase9_web_qa/ux_implementation");
const warningCsv = path.join(outputDir, "qa_warning_100_days.csv").replaceAll("\\", "/");
const failCsv = path.join(outputDir, "qa_fail_30_days.csv").replaceAll("\\", "/");
function writeHourlyFixture(filePath, days) {
  const rows = ["timestamp,kwh"];
  const origin = Date.parse("2026-01-01T00:00:00Z");
  for (let hour = 0; hour < days * 24; hour += 1) {
    const stamp = new Date(origin + hour * 3_600_000).toISOString().replace(".000Z", "");
    rows.push(`${stamp},${(8 + (hour % 24) * 0.1 + (hour % 7) * 0.03).toFixed(3)}`);
  }
  fs.writeFileSync(filePath, rows.join("\n"));
}
writeHourlyFixture(warningCsv, 100);
writeHourlyFixture(failCsv, 30);
const tabs = await fetch("http://127.0.0.1:9228/json/list").then((response) => response.json());
const target = tabs.find((tab) => tab.type === "page" && tab.url.startsWith(baseUrl));
if (!target) throw new Error("Energy Planner CDP tab was not found");

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
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
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

async function waitFor(expression, timeout = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return;
    await pause(100);
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

async function screenshot(name) {
  const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
}

async function selectFile(filePath) {
  const document = await send("DOM.getDocument", { depth: 1 });
  const input = await send("DOM.querySelector", { nodeId: document.root.nodeId, selector: "#csv-file" });
  await send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [filePath] });
  await evaluate("document.getElementById('csv-file').dispatchEvent(new Event('change', {bubbles:true}))");
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
await goto(`${baseUrl}/workspace`);
const initial = await evaluate(`(() => ({
  route: location.pathname,
  dropVisible: !document.getElementById('drop-zone').hidden,
  cardHidden: document.getElementById('file-info').hidden,
  analyzeDisabled: document.getElementById('analyze').disabled,
  qualityTitle: document.getElementById('quality-empty-title').textContent.trim(),
  overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
}))()`);
record(results, "T01", initial.route === "/workspace" && initial.dropVisible && initial.cardHidden && initial.analyzeDisabled && !initial.overflow, initial);
await screenshot("workspace-empty-1440.png");

await selectFile(mainCsv);
const selected = await evaluate(`(() => ({
  dropHidden: document.getElementById('drop-zone').hidden,
  cardVisible: !document.getElementById('file-info').hidden,
  fileName: document.getElementById('selected-file-name').textContent,
  changeLabel: document.getElementById('change-file').textContent.trim(),
  clearLabel: document.getElementById('clear-file').textContent.trim(),
  analyzeEnabled: !document.getElementById('analyze').disabled,
  panelState: document.getElementById('empty-state').dataset.panelState
}))()`);
record(results, "T02", selected.dropHidden && selected.cardVisible && selected.fileName.includes("energy_planner_test_office") && selected.analyzeEnabled && selected.panelState === "selected", selected);
await screenshot("workspace-selected-1440.png");

await selectFile(replacementCsv);
const changed = await evaluate(`(() => ({
  fileName: document.getElementById('selected-file-name').textContent,
  error: document.getElementById('form-error').textContent,
  qualityVisible: !document.getElementById('quality-result').hidden
}))()`);
record(results, "T03", changed.fileName === "qa_replacement.csv" && changed.error === "" && !changed.qualityVisible, changed);

await evaluate("document.getElementById('clear-file').click()");
const cleared = await evaluate(`(() => ({
  dropVisible: !document.getElementById('drop-zone').hidden,
  cardHidden: document.getElementById('file-info').hidden,
  inputValue: document.getElementById('csv-file').value,
  analyzeDisabled: document.getElementById('analyze').disabled,
  qualityTitle: document.getElementById('quality-empty-title').textContent.trim()
}))()`);
record(results, "T04", cleared.dropVisible && cleared.cardHidden && cleared.inputValue === "" && cleared.analyzeDisabled && cleared.qualityTitle.includes("CSV"), cleared);

await selectFile(mainCsv);
await evaluate(`(() => {
  const id = document.getElementById('building-id'); id.value='qa-office'; id.dispatchEvent(new Event('input',{bubbles:true}));
  const mode = document.getElementById('timezone-mode'); mode.value='explicit_offset'; mode.dispatchEvent(new Event('change',{bubbles:true}));
  document.getElementById('analyze').click();
})()`);
await waitFor("document.getElementById('form-error').textContent.includes('UTC 오프셋')");
const offsetError = await evaluate(`(() => ({
  formError: document.getElementById('form-error').textContent,
  fieldError: document.getElementById('timezone-mode-error').textContent,
  fieldInvalid: document.getElementById('timezone-mode').getAttribute('aria-invalid'),
  focused: document.activeElement.id
}))()`);
record(results, "T06", offsetError.formError.includes("UTC 오프셋") && offsetError.formError.includes("시간대 정보가 없는 현지 시각") && offsetError.fieldInvalid === "true" && offsetError.focused === "timezone-mode", offsetError);
await screenshot("workspace-offset-error-1440.png");

await evaluate(`(() => {
  const mode = document.getElementById('timezone-mode'); mode.value='iana_civil_time'; mode.dispatchEvent(new Event('change',{bubbles:true}));
  document.getElementById('analyze').click();
})()`);
await waitFor("!document.getElementById('quality-result').hidden", 12000);
const diagnosed = await evaluate(`(() => ({
  status: document.getElementById('status-badge').textContent.trim(),
  fieldErrorHidden: document.getElementById('timezone-mode-error').hidden,
  fileState: document.getElementById('selected-file-state').textContent,
  trainDisabled: document.getElementById('train').disabled
}))()`);
record(results, "T05", ["PASS", "WARNING", "FAIL"].includes(diagnosed.status) && diagnosed.fieldErrorHidden && diagnosed.fileState.includes("품질 진단 완료"), diagnosed);
record(results, "T07", diagnosed.fieldErrorHidden && ["PASS", "WARNING", "FAIL"].includes(diagnosed.status), diagnosed);
await screenshot("workspace-quality-pass-1440.png");

await goto(`${baseUrl}/workspace`);
await selectFile(warningCsv);
await evaluate(`(() => {
  const id = document.getElementById('building-id'); id.value='qa-warning'; id.dispatchEvent(new Event('input',{bubbles:true}));
  document.getElementById('analyze').click();
})()`);
await waitFor("!document.getElementById('quality-result').hidden", 12000);
const warningState = await evaluate(`(() => ({
  status: document.getElementById('status-badge').textContent.trim(),
  approvalVisible: !document.getElementById('warning-approval').hidden,
  trainDisabled: document.getElementById('train').disabled,
  eligibility: document.getElementById('eligibility').textContent.trim()
}))()`);
record(results, "T09-WARNING", warningState.status === "WARNING" && warningState.approvalVisible && warningState.trainDisabled, warningState);

await goto(`${baseUrl}/workspace`);
await selectFile(failCsv);
await evaluate(`(() => {
  const id = document.getElementById('building-id'); id.value='qa-fail'; id.dispatchEvent(new Event('input',{bubbles:true}));
  document.getElementById('analyze').click();
})()`);
await waitFor("!document.getElementById('quality-result').hidden", 12000);
const failState = await evaluate(`(() => ({
  status: document.getElementById('status-badge').textContent.trim(),
  approvalHidden: document.getElementById('warning-approval').hidden,
  trainDisabled: document.getElementById('train').disabled,
  eligibility: document.getElementById('eligibility').textContent.trim()
}))()`);
record(results, "T09-FAIL", failState.status === "FAIL" && failState.approvalHidden && failState.trainDisabled, failState);

await goto(`${baseUrl}/workspace`);
await selectFile(mainCsv);
await evaluate(`(() => {
  const id = document.getElementById('building-id'); id.value='qa-race'; id.dispatchEvent(new Event('input',{bubbles:true}));
  const originalFetch = window.fetch.bind(window);
  window.fetch = (...args) => new Promise((resolve, reject) => setTimeout(() => originalFetch(...args).then(resolve,reject), 700));
  document.getElementById('analyze').click();
  document.getElementById('clear-file').click();
})()`);
await pause(1400);
const race = await evaluate(`(() => ({
  cardHidden: document.getElementById('file-info').hidden,
  qualityHidden: document.getElementById('quality-result').hidden,
  analyzeDisabled: document.getElementById('analyze').disabled,
  title: document.getElementById('quality-empty-title').textContent.trim()
}))()`);
record(results, "T08", race.cardHidden && race.qualityHidden && race.analyzeDisabled && race.title.includes("CSV"), race);

await goto(`${baseUrl}/workspace`);
const stepNavigation = await evaluate(`(async () => {
  let fetchCount = 0;
  const originalFetch = window.fetch.bind(window);
  window.fetch = (...args) => { fetchCount += 1; return originalFetch(...args); };
  document.querySelector('[data-workspace-step="3"]').click();
  await new Promise(resolve => setTimeout(resolve, 50));
  return {
    fetchCount,
    viewedStep: document.querySelector('[data-workspace-step="3"]').getAttribute('aria-current'),
    guidance: document.getElementById('workspace-next-title').textContent.trim()
  };
})()`);
record(results, "T12", stepNavigation.fetchCount === 0 && stepNavigation.viewedStep === "step" && stepNavigation.guidance.includes("품질"), stepNavigation);

const accessibility = await evaluate(`(() => ({
  buildingLabel: document.getElementById('building-id').labels?.length || 0,
  timezoneLabel: document.getElementById('timezone').labels?.length || 0,
  modeLabel: document.getElementById('timezone-mode').labels?.length || 0,
  fileAria: document.getElementById('drop-zone').getAttribute('aria-label'),
  livePanel: document.getElementById('quality-panel').getAttribute('aria-live')
}))()`);
record(results, "T14", accessibility.buildingLabel > 0 && accessibility.timezoneLabel > 0 && accessibility.modeLabel > 0 && accessibility.fileAria && accessibility.livePanel === "polite", accessibility);

for (const width of [390, 320]) {
  await viewport(width, 844);
  await goto(`${baseUrl}/workspace`);
  await selectFile(mainCsv);
  const layout = await evaluate(`(() => ({
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    fileCardWidth: document.getElementById('file-info').getBoundingClientRect().width,
    viewport: document.documentElement.clientWidth,
    minButton: Math.min(...[...document.querySelectorAll('#file-info button')].map(x => x.getBoundingClientRect().height))
  }))()`);
  record(results, `T13-${width}`, !layout.overflow && layout.fileCardWidth <= layout.viewport && layout.minButton >= 44, layout);
  await screenshot(`workspace-selected-${width}.png`);
}

await viewport(1440, 900);
for (const route of ["/", "/workspace", "/dashboard"]) {
  await goto(baseUrl + route);
  const routeState = await evaluate(`(() => ({
    path: location.pathname,
    current: document.querySelector('[data-route-link][aria-current="page"]')?.getAttribute('href'),
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
  }))()`);
  record(results, `T10-${route}`, routeState.path === route && routeState.current === route && !routeState.overflow, routeState);
}
await goto(`${baseUrl}/`);
await evaluate("document.querySelector('[data-route-link][href=\"/workspace\"]').click()");
await waitFor("location.pathname === '/workspace'");
await evaluate("history.back()");
await waitFor("location.pathname === '/'");
await evaluate("history.forward()");
await waitFor("location.pathname === '/workspace'");
await send("Page.reload", { ignoreCache: true });
await waitFor("document.readyState === 'complete' && location.pathname === '/workspace'");
const historyState = await evaluate(`(() => ({
  path: location.pathname,
  current: document.querySelector('[data-route-link][aria-current="page"]')?.getAttribute('href')
}))()`);
record(results, "T10-history-refresh", historyState.path === "/workspace" && historyState.current === "/workspace", historyState);
await goto(`${baseUrl}/dashboard`);
const dashboard = await evaluate(`(() => ({
  emptyActionVisible: !document.getElementById('dashboard-empty-action').hidden,
  returnHidden: document.getElementById('return-workspace').hidden,
  predictionHidden: document.getElementById('run-prediction').hidden,
  total: document.getElementById('total-forecast').textContent.trim()
}))()`);
record(results, "T11", dashboard.emptyActionVisible && dashboard.returnHidden && dashboard.predictionHidden && dashboard.total === "—", dashboard);

const summary = {
  pass: results.filter((item) => item.status === "PASS").length,
  fail: results.filter((item) => item.status === "FAIL").length,
  results,
};
fs.writeFileSync(path.join(outputDir, "browser_qa_results.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
socket.close();
