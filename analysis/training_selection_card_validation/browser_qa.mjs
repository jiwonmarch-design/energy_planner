import fs from "node:fs";
import path from "node:path";

const baseUrl = "http://127.0.0.1:8765";
const cdpUrl = "http://127.0.0.1:9235";
const outputDir = path.resolve("analysis/training_selection_card_validation");
fs.mkdirSync(outputDir, { recursive: true });

const completedJobs = fs.readdirSync("artifacts/web_jobs/_jobs")
  .filter((name) => name.endsWith(".json"))
  .map((name) => {
    const filePath = path.resolve("artifacts/web_jobs/_jobs", name);
    return { filePath, modified: fs.statSync(filePath).mtimeMs, job: JSON.parse(fs.readFileSync(filePath, "utf8")) };
  })
  .filter(({ job }) => job.status === "COMPLETED")
  .sort((left, right) => right.modified - left.modified);
if (!completedJobs.length) throw new Error("Completed saved job not found");
const savedJob = completedJobs[0].job;

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
async function waitFor(expression, timeout = 10_000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return true;
    await pause(100);
  }
  return false;
}
async function viewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
}
async function screenshot(name) {
  const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
}

await send("Page.enable");
await send("Runtime.enable");
await viewport(1440, 900);
await send("Page.navigate", { url: `${baseUrl}/#training` });
if (!await waitFor("document.readyState === 'complete' && typeof renderCompletedTrainingMetrics === 'function'")) {
  throw new Error("Energy Planner page did not finish loading");
}

async function render(job) {
  return evaluate(`(() => {
    const job = ${JSON.stringify(job)};
    document.getElementById('workspace-model-results').hidden = false;
    renderCompletedTrainingMetrics(job);
    document.getElementById('workspace-model-results').scrollIntoView({ block: 'center' });
    const card = document.getElementById('workspace-model-results');
    const model = document.getElementById('workspace-selected-model');
    const reason = document.getElementById('workspace-selection-reason');
    const label = card.querySelector('.training-selection-label');
    const style = getComputedStyle(card);
    return {
      model: model.textContent,
      reason: reason.textContent,
      detailsOpen: document.getElementById('training-evaluation-details').open,
      background: style.backgroundColor,
      borderLeftWidth: style.borderLeftWidth,
      borderLeftColor: style.borderLeftColor,
      modelFontSize: parseFloat(getComputedStyle(model).fontSize),
      reasonFontSize: parseFloat(getComputedStyle(reason).fontSize),
      labelFontSize: parseFloat(getComputedStyle(label).fontSize),
      viewportWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  })()`);
}

const checks = [];
function record(name, passed, details) {
  checks.push({ name, status: passed ? "PASS" : "FAIL", details });
}

const saved = await render(savedJob);
const savedBaselineMae = Math.min(
  savedJob.validation_metrics.last_24h.mae,
  savedJob.validation_metrics.last_168h.mae,
);
const savedImprovement = (
  (savedBaselineMae - savedJob.validation_metrics[savedJob.selected_model].mae)
  / savedBaselineMae
) * 100;
const savedImprovementText = savedImprovement.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
record(
  "saved_result_first",
  saved.model === "XGBoost" && saved.reason.includes(`${savedImprovementText}%`),
  { jobId: savedJob.job_id, selectedModel: savedJob.selected_model, savedImprovement, ...saved },
);
record(
  "card_visual_hierarchy",
  saved.background === "rgb(237, 242, 255)"
    && saved.borderLeftWidth === "4px"
    && saved.modelFontSize > saved.reasonFontSize
    && saved.modelFontSize > saved.labelFontSize,
  saved,
);
record("details_default_closed", saved.detailsOpen === false, saved);
await pause(150);
await screenshot("selection-card-saved-xgboost-1440.png");

const baseMetrics = {
  last_24h: { mae: 12 },
  last_168h: { mae: 10 },
  xgboost: { mae: 9.18 },
  patchtst: { mae: 8 },
  xgboost_patchtst_50_50: { mae: 7.5 },
};
const expected = {
  xgboost: ["XGBoost", "8.2%"],
  patchtst: ["PatchTST", "20%"],
  xgboost_patchtst_50_50: ["XGBoost + PatchTST 50:50", "25%"],
  last_24h: ["직전 24시간 반복", "직전 24시간의 사용량"],
  last_168h: ["지난주 같은 시간 반복", "지난주 같은 시간의 사용량"],
};
for (const [selectedModel, [name, reasonPart]] of Object.entries(expected)) {
  const value = await render({
    selected_model: selectedModel,
    validation_metrics: baseMetrics,
    test_metrics: baseMetrics,
  });
  record(
    `copy_${selectedModel}`,
    value.model === name && value.reason.includes(reasonPart) && value.detailsOpen === false,
    value,
  );
}

await viewport(390, 844);
const mobile = await render(savedJob);
record("mobile_no_horizontal_overflow", mobile.scrollWidth === mobile.viewportWidth, mobile);
await pause(150);
await screenshot("selection-card-saved-xgboost-390.png");

record("runtime_errors", runtimeErrors.length === 0, runtimeErrors);
fs.writeFileSync(path.join(outputDir, "browser_results.json"), JSON.stringify(checks, null, 2));
socket.close();

const failed = checks.filter((item) => item.status === "FAIL");
console.log(JSON.stringify({ passed: checks.length - failed.length, failed: failed.length, checks }, null, 2));
if (failed.length) process.exitCode = 1;
