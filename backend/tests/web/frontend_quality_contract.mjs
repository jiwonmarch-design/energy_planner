import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("frontend/app.js", "utf8");
const renderStart = source.indexOf("function renderQuality(result)");
const renderEnd = source.indexOf('$("analyze").onclick', renderStart);
assert.ok(renderStart >= 0 && renderEnd > renderStart, "quality renderer must be discoverable");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      hidden: false,
      disabled: false,
      textContent: "",
      innerHTML: "",
      className: "",
      dataset: {},
      style: {},
      removeAttribute() {},
      setAttribute() {},
      focus() {},
      scrollIntoView() {},
    });
  }
  return elements.get(id);
}

const context = {
  state: { stepStatuses: {}, csvText: "fixture", fileName: "fixture.csv" },
  $: element,
  fmt: (value) => new Intl.NumberFormat("ko-KR").format(value),
  inputSignature: () => "fixture",
  setTrainingProgress: () => {},
  setWorkspaceState: () => {},
  jobStepStatus: () => "waiting",
  requestAnimationFrame: (callback) => callback(),
  window: { matchMedia: () => ({ matches: true }) },
};
vm.createContext(context);
vm.runInContext(source.slice(renderStart, renderEnd), context);

const sufficientWarning = {
  contract_status: "PASS",
  quality: {
    status: "WARNING",
    reason_codes: ["WARNING_MAX_GAP_OVER_24_HOURS"],
    elapsed_days: 180,
    expected_hours: 4320,
    observed_hours: 4295,
    missing_rate: 25 / 4320,
    max_consecutive_missing_hours: 25,
    latest_168_complete: true,
  },
  training_status: "PASS",
  training_eligible: true,
  training_blockers: [],
  split: {
    train_start: "2025-01-01T00:00:00+00:00",
    train_end: "2025-05-01T00:00:00+00:00",
    validation_start: "2025-05-01T00:00:00+00:00",
    validation_end: "2025-05-31T00:00:00+00:00",
    test_start: "2025-05-31T00:00:00+00:00",
    test_end: "2025-06-30T00:00:00+00:00",
    validation_days: 30,
    test_days: 30,
    warning_limited_experiment: false,
  },
  sample_availability: {
    status: "PASS",
    reason_codes: [],
    splits: {
      train: { valid_count: 2641, excluded_count: 216, minimum_required: 1000 },
      validation: {
        valid_count: 697,
        excluded_count: 0,
        minimum_required: 168,
        evaluation: { valid_count: 30, excluded_count: 0, minimum_required: 12 },
      },
      test: { valid_count: 30, excluded_count: 0, minimum_required: 12 },
    },
  },
};

context.renderQuality(sufficientWarning);
assert.equal(element("status-badge").textContent, "WARNING");
assert.equal(element("train").disabled, false);
assert.match(element("quality-cards").innerHTML, /학습 적합성[\s\S]*PASS/);
assert.match(element("reason-list").innerHTML, /192시간 표본만 제외/);
assert.match(element("quality-split-results").innerHTML, /유효 2,641개 · 제외 216개/);
assert.match(element("quality-split-results").innerHTML, /비중복 평가 유효 30개/);

const insufficientValidation = structuredClone(sufficientWarning);
insufficientValidation.training_status = "FAIL";
insufficientValidation.training_eligible = false;
insufficientValidation.training_blockers = ["FAIL_MINIMUM_VALIDATION_DENSE_SAMPLES_168"];
insufficientValidation.sample_availability.status = "FAIL";
insufficientValidation.sample_availability.reason_codes = [
  "FAIL_MINIMUM_VALIDATION_DENSE_SAMPLES_168",
];
insufficientValidation.sample_availability.splits.validation.valid_count = 0;
insufficientValidation.sample_availability.splits.validation.excluded_count = 697;

context.renderQuality(insufficientValidation);
assert.equal(element("train").disabled, true);
assert.match(element("quality-cards").innerHTML, /학습 적합성[\s\S]*FAIL/);
assert.match(element("quality-detail-list").innerHTML, /유효 표본 부족/);
assert.match(element("reason-list").innerHTML, /최소 168개보다 적습니다/);

console.log("frontend quality contract: 2 scenarios PASS");
