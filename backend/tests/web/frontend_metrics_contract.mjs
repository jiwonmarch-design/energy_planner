import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("frontend/app.js", "utf8");
const html = fs.readFileSync("frontend/index.html", "utf8");
const start = source.indexOf("function metricNumber(metric, key)");
const end = source.indexOf("function renderPredictionOverview", start);
assert.ok(start >= 0 && end > start, "metric renderers must be discoverable");

class FakeNode {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName;
    this.id = id;
    this.children = [];
    this.textContent = "";
    this.className = "";
    this.scope = "";
  }

  append(...nodes) {
    this.children.push(...nodes);
  }

  replaceChildren(...nodes) {
    this.children = nodes.flatMap((node) => node?.isFragment ? node.children : [node]);
  }
}

const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeNode("div", id));
  return elements.get(id);
};
const document = {
  createElement: (name) => new FakeNode(name),
  createDocumentFragment: () => Object.assign(new FakeNode("fragment"), { isFragment: true }),
};
const context = {
  document,
  state: { predictionResult: { run_id: "latest-run" } },
  $: element,
  fmt: (value, digits = 1) => new Intl.NumberFormat("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value),
  modelDisplayName: (name) => ({
    xgboost: "XGBoost",
    last_24h: "직전 24시간 반복",
    last_168h: "지난주 같은 시간 반복",
  })[name] || name,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

const latestMetric = {
  mae: 0.7053490342064337,
  wape: 0.29531701698863305,
  rmse: 1.0566222601295283,
  peak_mae: 1.0799115137620405,
  peak_time_error_hours: 4.181818181818182,
};
const latestJob = {
  selected_model: "xgboost",
  validation_metrics: {
    xgboost: latestMetric,
    last_24h: latestMetric,
    last_168h: latestMetric,
  },
  test_metrics: {
    xgboost: latestMetric,
    last_24h: latestMetric,
    last_168h: latestMetric,
  },
};

element("training-evaluation-details").open = true;
context.renderCompletedTrainingMetrics(latestJob);
context.renderForecastValidation(latestJob, "latest-run");

assert.equal(element("training-evaluation-details").open, false);
assert.equal(element("workspace-selected-model").textContent, "XGBoost 선택");
assert.equal(element("workspace-validation-body").children.length, 3);
assert.equal(element("workspace-test-body").children.length, 3);
assert.equal(element("dashboard-test-wape").textContent, "29.5%");
assert.equal(element("dashboard-test-peak-mae").textContent, "1.08 kWh");
assert.equal(element("dashboard-test-peak-time").textContent, "4.2 h");
assert.equal(element("dashboard-test-rmse").textContent, "1.06 kWh");

const legacyMetric = { mae: 1.2, wape: 0.12 };
assert.equal(context.metricDisplay(legacyMetric, "rmse"), "평가 결과 없음");
assert.equal(context.metricDisplay(legacyMetric, "peak_mae"), "평가 결과 없음");
assert.equal(context.metricDisplay(legacyMetric, "peak_time_error_hours"), "평가 결과 없음");

assert.match(html, /Validation 모델 선택 결과/);
assert.match(html, /Test 최종 평가 결과/);
assert.match(html, /<details id="training-evaluation-details" class="training-evaluation-details">/);
assert.match(html, /상세 평가 지표 보기/);
assert.match(html, /과거 예측 성능 보기/);
assert.match(html, /예상 피크 사용량/);
assert.match(html, /4\. 과거 예측 오차/);
assert.match(source, /const clone = \$\("ai-report"\)\.cloneNode\(true\)/);
assert.match(source, /window\.print\(\)/);

console.log("frontend metrics contract: latest + legacy scenarios PASS");
