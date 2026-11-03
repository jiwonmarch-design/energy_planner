import fs from "node:fs";
import path from "node:path";

const baseUrl = "http://127.0.0.1:8765";
const outputDir = path.resolve("analysis/phase9_web_qa/workspace_wizard");
const fixture = path.join(outputDir, "qa_complete_180_days.csv");
fs.mkdirSync(outputDir, { recursive: true });

const rows = ["timestamp,kwh"];
const origin = Date.parse("2026-01-01T00:00:00Z");
for (let hour = 0; hour < 180 * 24; hour += 1) {
  const timestamp = new Date(origin + hour * 3_600_000).toISOString().replace(".000Z", "").replace("Z", "");
  const kwh = 12 + 2.5 * Math.sin((2 * Math.PI * (hour % 24)) / 24) + (hour % 7) * 0.08;
  rows.push(`${timestamp},${kwh.toFixed(3)}`);
}
fs.writeFileSync(fixture, rows.join("\n"));

let tabs = await fetch("http://127.0.0.1:9228/json/list").then((response) => response.json());
let target = tabs.find((tab) => tab.type === "page" && tab.url.startsWith(baseUrl));
if (!target) {
  target = await fetch(`http://127.0.0.1:9228/json/new?${encodeURIComponent(`${baseUrl}/workspace`)}`, { method: "PUT" }).then((response) => response.json());
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

async function waitFor(expression, timeout = 12_000) {
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
await goto(`${baseUrl}/workspace`);
const initial = await evaluate(`(() => ({
  route: location.pathname,
  position: document.getElementById('wizard-position').textContent.trim(),
  visiblePanels: [...document.querySelectorAll('[data-step-panel]')].filter((panel) => !panel.hidden).map((panel) => panel.dataset.stepPanel),
  previousDisabled: document.getElementById('wizard-previous').disabled,
  overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth
}))()`);
record(results, "W01-initial", initial.route === "/workspace" && initial.position === "1 / 3" && initial.visiblePanels.join() === "1" && initial.previousDisabled && !initial.overflow, initial);
await screenshot("workspace-step1-1440.png");

await evaluate("document.getElementById('wizard-next').click()");
const stepTwo = await evaluate(`(() => ({
  position: document.getElementById('wizard-position').textContent.trim(),
  visiblePanels: [...document.querySelectorAll('[data-step-panel]')].filter((panel) => !panel.hidden).map((panel) => panel.dataset.stepPanel),
  focused: document.activeElement.id,
  analyzeDisabled: document.getElementById('analyze').disabled
}))()`);
record(results, "W02-manual-step", stepTwo.position === "2 / 3" && stepTwo.visiblePanels.join() === "2" && stepTwo.focused === "quality-panel" && stepTwo.analyzeDisabled, stepTwo);

await evaluate("document.getElementById('wizard-next').click()");
const stepThree = await evaluate(`(() => ({
  position: document.getElementById('wizard-position').textContent.trim(),
  visiblePanels: [...document.querySelectorAll('[data-step-panel]')].filter((panel) => !panel.hidden).map((panel) => panel.dataset.stepPanel),
  nextDisabled: document.getElementById('wizard-next').disabled,
  trainDisabled: document.getElementById('train').disabled
}))()`);
record(results, "W03-locked-action", stepThree.position === "3 / 3" && stepThree.visiblePanels.join() === "3" && stepThree.nextDisabled && stepThree.trainDisabled, stepThree);

await evaluate("document.getElementById('wizard-previous').click()");
await evaluate("document.getElementById('wizard-previous').click()");
await selectFile(fixture.replaceAll("\\", "/"));
const selected = await evaluate(`(() => ({
  position: document.getElementById('wizard-position').textContent.trim(),
  visiblePanels: [...document.querySelectorAll('[data-step-panel]')].filter((panel) => !panel.hidden).map((panel) => panel.dataset.stepPanel),
  analyzeEnabled: !document.getElementById('analyze').disabled,
  file: document.getElementById('selected-file-name').textContent.trim()
}))()`);
record(results, "W04-file-to-quality", selected.position === "2 / 3" && selected.visiblePanels.join() === "2" && selected.analyzeEnabled && selected.file === path.basename(fixture), selected);

await evaluate("document.getElementById('analyze').click()");
await waitFor("!document.getElementById('quality-result').hidden");
const diagnosed = await evaluate(`(() => ({
  status: document.getElementById('status-badge').textContent.trim(),
  splitVisible: !document.getElementById('quality-split-results').hidden,
  splitCards: document.querySelectorAll('#quality-split-results .split-grid > div').length,
  position: document.getElementById('wizard-position').textContent.trim(),
  trainEnabled: !document.getElementById('train').disabled,
  stepThreeStatus: document.querySelector('[data-workspace-step="3"]').dataset.status
}))()`);
record(results, "W05-quality-result", diagnosed.status === "PASS" && diagnosed.splitVisible && diagnosed.splitCards === 3 && diagnosed.position === "2 / 3" && diagnosed.trainEnabled && diagnosed.stepThreeStatus === "current", diagnosed);
await screenshot("workspace-quality-1440.png");

await evaluate("document.getElementById('wizard-next').click()");
const trainingReady = await evaluate(`(() => ({
  visiblePanels: [...document.querySelectorAll('[data-step-panel]')].filter((panel) => !panel.hidden).map((panel) => panel.dataset.stepPanel),
  trainEnabled: !document.getElementById('train').disabled,
  predictionHidden: document.getElementById('workspace-run-prediction').hidden,
  summary: document.getElementById('workspace-prediction-summary').textContent.trim()
}))()`);
record(results, "W06-training-ready", trainingReady.visiblePanels.join() === "3" && trainingReady.trainEnabled && trainingReady.predictionHidden && trainingReady.summary.includes("실행 전"), trainingReady);
await screenshot("workspace-step3-1440.png");

for (const width of [390, 320]) {
  await viewport(width, 844);
  const responsive = await evaluate(`(() => {
    const buttons = [...document.querySelectorAll('.wizard-navigation .button')];
    return {
      width: ${width},
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      buttonHeights: buttons.map((button) => Math.round(button.getBoundingClientRect().height)),
      panelWidth: Math.round(document.querySelector('[data-step-panel="3"]').getBoundingClientRect().width),
      viewportWidth: document.documentElement.clientWidth
    };
  })()`);
  record(results, `W07-responsive-${width}`, !responsive.overflow && responsive.buttonHeights.every((height) => height >= 44) && responsive.panelWidth <= responsive.viewportWidth, responsive);
  await screenshot(`workspace-step3-${width}.png`);
}

await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
const reducedMotion = await evaluate("getComputedStyle(document.querySelector('.progress-track span')).animationName");
record(results, "W08-reduced-motion", reducedMotion === "none", { animationName: reducedMotion });

fs.writeFileSync(path.join(outputDir, "browser_qa_results.json"), JSON.stringify(results, null, 2));
fs.rmSync(fixture, { force: true });
socket.close();

const failed = results.filter((result) => result.status === "FAIL");
console.log(JSON.stringify({ passed: results.length - failed.length, failed: failed.length, results }, null, 2));
if (failed.length) process.exitCode = 1;
