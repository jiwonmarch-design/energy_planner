const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist in app.js`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`${name} closing brace not found`);
}

function fmt(value, digits = 1) {
  return Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

eval(functionSource("metricNumber"));
eval(functionSource("modelDisplayName"));
eval(functionSource("selectionReason"));

assert.equal(modelDisplayName("xgboost"), "XGBoost");
assert.equal(modelDisplayName("patchtst"), "PatchTST");
assert.equal(modelDisplayName("xgboost_patchtst_50_50"), "XGBoost + PatchTST 50:50");
assert.equal(modelDisplayName("last_24h"), "직전 24시간 반복");
assert.equal(modelDisplayName("last_168h"), "지난주 같은 시간 반복");

const metrics = (selected, selectedMae) => ({
  selected_model: selected,
  validation_metrics: {
    [selected]: { mae: selectedMae },
    last_24h: { mae: 12 },
    last_168h: { mae: 10 },
  },
});

assert.equal(
  selectionReason(metrics("xgboost", 9.18)),
  "검증에서 기준 예측보다 평균 오차를 8.2% 줄였습니다.",
);
assert.equal(
  selectionReason(metrics("patchtst", 8)),
  "검증에서 기준 예측보다 평균 오차를 20% 줄였습니다.",
);
assert.equal(
  selectionReason(metrics("xgboost_patchtst_50_50", 7.5)),
  "검증에서 기준 예측보다 평균 오차를 25% 줄였습니다.",
);
assert.equal(
  selectionReason({ selected_model: "last_24h" }),
  "학습 모델이 채택 기준을 충족하지 않아 직전 24시간의 사용량을 사용합니다.",
);
assert.equal(
  selectionReason({ selected_model: "last_168h" }),
  "학습 모델이 채택 기준을 충족하지 않아 지난주 같은 시간의 사용량을 사용합니다.",
);
assert.equal(
  selectionReason({ selected_model: "patchtst", validation_metrics: {} }),
  "검증 성능과 채택 기준을 충족해 이 예측 방식을 사용합니다.",
);

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "..", "reference-system.css"), "utf8");
assert.match(html, /채택된 예측 방식/);
assert.match(html, /id="workspace-selection-reason"/);
assert.match(css, /\.model-results[^}]*border-left:\s*4px solid var\(--blue\)/s);
assert.match(css, /\.model-results[^}]*background:\s*#edf2ff/s);
assert.match(source, /\$\("training-evaluation-details"\)\.open = false;/);

console.log("selection-card: 16/16 PASS");

if (process.env.SAVED_JOB_PATH) {
  const savedJob = JSON.parse(fs.readFileSync(process.env.SAVED_JOB_PATH, "utf8"));
  assert.equal(savedJob.status, "COMPLETED");
  const savedReason = selectionReason(savedJob);
  assert.notEqual(savedReason, "저장된 검증 결과에서 채택 이유를 확인할 수 없습니다.");
  console.log(`saved-job: ${savedJob.selected_model} | ${savedReason}`);
}
