const state = {
  csvText: "",
  fileName: "",
  analysis: null,
  job: null,
  poll: null,
  route: "/",
  fileToken: "",
  analysisSignature: "",
  jobContext: null,
  predictionComplete: false,
  warningRequired: false,
  observationDays: null,
  qualityRequestId: 0,
  viewedStep: 1,
  stepStatuses: { 1: "current", 2: "waiting", 3: "waiting" },
};

const $ = (id) => document.getElementById(id);
const fileInput = $("csv-file");
const drop = $("drop-zone");
const error = $("form-error");
const routes = new Set(["/", "/workspace", "/dashboard"]);
const jobSessionKey = "energy-planner.active-job.v1";

function fmt(number, digits = 1) {
  return Number(number).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function normalizeRoute(pathname) {
  const normalized = pathname !== "/" ? pathname.replace(/\/$/, "") : pathname;
  return routes.has(normalized) ? normalized : "/";
}

function renderRoute(path, { scroll = true } = {}) {
  state.route = normalizeRoute(path);
  document.body.dataset.route = state.route === "/" ? "home" : state.route.slice(1);
  document.querySelectorAll("[data-page]").forEach((page) => {
    page.hidden = page.dataset.page !== state.route;
  });
  document.querySelectorAll("[data-route-link]").forEach((link) => {
    const active = new URL(link.href, location.origin).pathname === state.route;
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const titles = {
    "/": "Energy Planner",
    "/workspace": "Workspace · Energy Planner",
    "/dashboard": "Dashboard · Energy Planner",
  };
  document.title = titles[state.route];
  updateNextAction();
  if (scroll) window.scrollTo({ top: 0, behavior: "auto" });
}

function navigate(path, { replace = false, scroll = true } = {}) {
  const route = normalizeRoute(path);
  if (location.pathname !== route) {
    history[replace ? "replaceState" : "pushState"]({}, "", route);
  }
  renderRoute(route, { scroll });
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("[data-route-link]");
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const url = new URL(link.href, location.origin);
  if (url.origin !== location.origin) return;
  event.preventDefault();
  navigate(url.pathname);
});

window.addEventListener("popstate", () => renderRoute(location.pathname));

function statusLabel(status) {
  return {
    waiting: "대기",
    current: "현재 단계",
    "in-progress": "진행 중",
    complete: "완료",
    warning: "WARNING",
    fail: "FAIL",
  }[status];
}

function renderWorkspaceSteps() {
  document.querySelectorAll("[data-workspace-step]").forEach((step) => {
    const number = Number(step.dataset.workspaceStep);
    const status = state.stepStatuses[number] || "waiting";
    step.className = `workflow-step status-${status}${number === state.viewedStep ? " is-viewed" : ""}`;
    step.dataset.status = status;
    step.dataset.statusLabel = statusLabel(status);
    if (number === state.viewedStep) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  });
  document.querySelectorAll("[data-step-panel]").forEach((panel) => {
    panel.hidden = Number(panel.dataset.stepPanel) !== state.viewedStep;
  });
  $("wizard-previous").disabled = state.viewedStep === 1;
  $("wizard-next").disabled = state.viewedStep === 3;
  $("wizard-next").textContent = state.viewedStep === 2 ? "XGBoost 학습 단계" : "다음 단계";
  $("wizard-position").textContent = `${state.viewedStep} / 3`;
}

function switchWorkspaceStep(number, { scroll = true } = {}) {
  state.viewedStep = Math.min(3, Math.max(1, number));
  renderWorkspaceSteps();
  if (scroll && state.route === "/workspace") {
    const panel = document.querySelector(`[data-step-panel="${state.viewedStep}"]`);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    panel.focus({ preventScroll: true });
  }
}

function setWorkspaceState(statuses, viewedStep = state.viewedStep) {
  state.stepStatuses = { ...state.stepStatuses, ...statuses };
  state.viewedStep = viewedStep;
  renderWorkspaceSteps();
  updateNextAction();
}

document.querySelectorAll("[data-workspace-step]").forEach((step) => {
  step.addEventListener("click", (event) => {
    event.preventDefault();
    const number = Number(step.dataset.workspaceStep);
    switchWorkspaceStep(number);
  });
});

$("wizard-previous").addEventListener("click", () => switchWorkspaceStep(state.viewedStep - 1));
$("wizard-next").addEventListener("click", () => switchWorkspaceStep(state.viewedStep + 1));

function currentContext() {
  return {
    timezone: $("timezone").value.trim(),
    fileToken: state.fileToken,
  };
}

function contextsMatch(left, right) {
  return Boolean(left && right) && left.timezone === right.timezone && left.fileToken === right.fileToken;
}

function inputSignature() {
  return JSON.stringify({
    ...currentContext(),
    warningApproved: $("warning-approved").checked,
    fileToken: state.fileToken,
  });
}

function analysisIsCurrent() {
  return Boolean(state.analysis && state.analysisSignature && state.analysisSignature === inputSignature());
}

function jobStepStatus() {
  if (!state.job) return "waiting";
  if (state.jobContext && state.fileToken && !contextsMatch(state.jobContext, currentContext())) return "waiting";
  if (["QUEUED", "RUNNING"].includes(state.job.status)) return "in-progress";
  if (state.job.status === "COMPLETED") return "complete";
  if (state.job.status === "FAILED") return "fail";
  return "waiting";
}

function updateAnalyzeAvailability() {
  const approvalMissing = state.warningRequired && !$("warning-approved").checked;
  $("analyze").disabled = !state.csvText || approvalMissing;
}

function resetTrainingView(message = "STEP 02 품질 진단을 통과하면 학습을 시작할 수 있습니다.") {
  $("training-progress").hidden = true;
  $("workspace-model-results").hidden = true;
  $("retry-training").hidden = true;
  $("open-dashboard").hidden = true;
  $("training-placeholder").hidden = false;
  $("training-placeholder").textContent = message;
  $("workspace-job-status").textContent = "학습 대기";
  $("workspace-job-status").removeAttribute("data-status");
  $("train").disabled = true;
  $("workspace-run-prediction").hidden = true;
  $("workspace-prediction-summary").textContent = "24시간 예측 실행 전입니다.";
}

function resetQualityPanel(message) {
  state.analysis = null;
  state.analysisSignature = "";
  $("quality-result").hidden = true;
  $("quality-split-results").hidden = true;
  $("quality-split-results").innerHTML = "";
  $("empty-state").hidden = false;
  const empty = $("empty-state");
  empty.dataset.panelState = state.csvText ? "selected" : "empty";
  $("quality-empty-title").textContent = message;
  $("quality-empty-copy").textContent = state.csvText
    ? "변경된 입력으로 파일 형식, 누락된 시간과 학습 가능 여부를 다시 확인하세요."
    : "왼쪽에서 시간별 전력 사용량 CSV를 선택해 주세요.";
  $("quality-preview").hidden = !state.csvText;
  $("quality-preview-file").textContent = state.fileName || "확인 전";
  $("quality-preview-file").title = state.fileName || "";
  $("warning-approval").hidden = !state.warningRequired;
  $("train").disabled = true;
}

function invalidateAnalysis(message = "입력이 변경되어 재검증이 필요합니다.") {
  const hadAnalysis = Boolean(state.analysis);
  state.qualityRequestId += 1;
  $("quality-panel").removeAttribute("aria-busy");
  updateAnalyzeAvailability();
  $("analyze").textContent = "데이터 품질 진단하기";
  state.predictionComplete = false;
  resetQualityPanel(message);
  resetTrainingView();
  const hasFile = Boolean(state.csvText);
  setWorkspaceState(
    {
      1: hasFile ? "complete" : "current",
      2: hasFile ? "current" : "waiting",
      3: jobStepStatus(),
    },
    hasFile ? 2 : 1,
  );
  if (hadAnalysis) error.textContent = "입력 설정이 변경되어 이전 품질 진단 결과를 사용할 수 없습니다. 다시 진단해 주세요.";
}

function updateNextAction() {
  const completed = state.job?.status === "COMPLETED";
  const running = ["QUEUED", "RUNNING"].includes(state.job?.status);
  const currentAnalysis = analysisIsCurrent();
  const contextMatches = contextsMatch(state.jobContext, currentContext());
  const canPredict = completed && Boolean(state.csvText) && currentAnalysis && contextMatches;
  const homeCta = $("home-primary-cta");
  const homeLabel = $("home-cta-label");
  let homePath = "/workspace";
  let homeText = "CSV 업로드 시작";

  if (completed) {
    homePath = canPredict ? "/dashboard" : "/workspace";
    homeText = canPredict ? "24시간 예측 실행" : "예측 입력 준비하기";
  } else if (running) {
    homePath = "/dashboard";
    homeText = "학습 상태 확인";
  } else if (currentAnalysis && state.analysis.training_eligible) {
    homePath = "/workspace";
    homeText = "모델 학습 계속하기";
  } else if (state.csvText) {
    homePath = "/workspace";
    homeText = "품질 진단 계속하기";
  }

  homeCta.href = homePath;
  homeLabel.textContent = homeText;
  $("dashboard-empty-action").hidden = completed;
  $("dashboard-empty-action").textContent = running ? "데이터 분석에서 학습 상태 확인" : "CSV 업로드하러 가기";
  $("return-workspace").hidden = !completed;
  $("open-dashboard").hidden = !completed;
  $("run-prediction").hidden = !completed;
  $("run-prediction").disabled = !canPredict;
  $("workspace-run-prediction").hidden = !completed;
  $("workspace-run-prediction").disabled = !canPredict;
  if (completed && !state.predictionComplete) {
    $("sample-tag").textContent = canPredict ? "예측 실행 전" : "CSV 재검증 필요";
    $("sample-note").textContent = canPredict
      ? "저장된 모델이 준비되었습니다. ‘24시간 예측 실행’을 눌러 실제 결과를 생성하세요."
      : "저장된 모델은 확인했지만 예측 입력이 없습니다. 데이터 분석에서 CSV를 다시 진단해 주세요.";
  }
}

function estimateObservationDays(csvText) {
  const lines = csvText.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) return null;
  const headers = lines[0].split(",").map((value) => value.trim().replace(/^"|"$/g, ""));
  const timestampIndex = headers.indexOf("timestamp");
  if (timestampIndex < 0) return null;
  const timestamps = lines.slice(1).map((line) => {
    const raw = line.split(",")[timestampIndex]?.trim().replace(/^"|"$/g, "");
    const value = Date.parse(raw);
    return Number.isFinite(value) ? value : null;
  }).filter((value) => value !== null);
  if (timestamps.length < 2) return null;
  return (Math.max(...timestamps) - Math.min(...timestamps) + 60 * 60 * 1000) / 86400000;
}

async function readFile(file) {
  error.textContent = "";
  clearTimeModeError();
  if (!file || !file.name.toLowerCase().endsWith(".csv")) throw new Error("CSV 파일만 선택할 수 있습니다.");
  if (file.size > 25 * 1024 * 1024) throw new Error("CSV는 25MB 이하여야 합니다.");
  state.csvText = await file.text();
  state.fileName = file.name;
  state.fileToken = `${file.name}:${file.size}:${file.lastModified}`;
  state.observationDays = estimateObservationDays(state.csvText);
  state.warningRequired = Number.isFinite(state.observationDays) && state.observationDays >= 90 && state.observationDays < 180;
  $("warning-approved").checked = false;
  $("warning-approval").hidden = !state.warningRequired;
  drop.hidden = true;
  $("file-info").hidden = false;
  $("selected-file-name").textContent = file.name;
  $("selected-file-name").title = file.name;
  $("selected-file-meta").textContent = `${fmt(file.size / 1024)}KB · 브라우저에서 선택됨`;
  $("selected-file-state").textContent = "아직 서버에 전송되지 않음 · 품질 진단 전";
  invalidateAnalysis("선택한 파일의 품질 진단을 실행해 주세요.");
  updateAnalyzeAvailability();
}

function clearSelectedFile() {
  state.qualityRequestId += 1;
  state.csvText = "";
  state.fileName = "";
  state.fileToken = "";
  state.analysis = null;
  state.analysisSignature = "";
  state.warningRequired = false;
  state.observationDays = null;
  state.predictionComplete = false;
  fileInput.value = "";
  drop.hidden = false;
  $("file-info").hidden = true;
  $("selected-file-name").textContent = "";
  $("selected-file-meta").textContent = "";
  $("selected-file-state").textContent = "";
  $("warning-approved").checked = false;
  $("warning-approval").hidden = true;
  $("analyze").disabled = true;
  error.textContent = "";
  clearTimeModeError();
  resetQualityPanel("CSV를 먼저 선택해 주세요.");
  resetTrainingView();
  setWorkspaceState({ 1: "current", 2: "waiting", 3: jobStepStatus() }, 1);
}

function validateRequiredInputs() {
  if (!state.csvText) return "CSV 파일을 선택해 주세요.";
  if (!$("timezone").value.trim()) return "건물의 시간대를 입력해 주세요. 예: Asia/Seoul";
  try {
    new Intl.DateTimeFormat("ko-KR", { timeZone: $("timezone").value.trim() }).format();
  } catch {
    return "건물의 시간대가 올바른 IANA 식별자가 아닙니다. 목록에서 선택하거나 Asia/Seoul 형식으로 입력해 주세요.";
  }
  return "";
}

function clearTimeModeError() {
  // Timestamp offset mode is inferred by the server.
}

function qualityErrorDetails(message) {
  const mappings = [
    [/explicit_offset mode requires an offset in every timestamp/i, "일부 timestamp의 UTC 오프셋 형식이 올바르지 않습니다. 모든 행의 표기 방식을 통일해 주세요.", false],
    [/offset-aware and offset-naive timestamps cannot be mixed/i, "오프셋이 있는 시각과 없는 시각이 섞여 있습니다. CSV의 timestamp 형식을 한 가지 방식으로 통일해 주세요.", true],
    [/unknown IANA timezone/i, "건물의 시간대를 확인할 수 없습니다. Asia/Seoul 같은 IANA 식별자를 선택해 주세요.", false],
    [/timestamp cannot be resolved/i, "선택한 시간대에서 해석할 수 없는 시각이 있습니다. DST 중복·누락 시각과 CSV 시간대를 확인해 주세요.", true],
    [/missing required columns/i, "필수 열이 없습니다. 첫 행에 timestamp와 kwh 열을 포함해 주세요.", false],
    [/timestamp and kwh cannot be blank/i, "timestamp 또는 kwh에 빈 값이 있습니다. 원본 계측값을 확인해 주세요.", false],
    [/kwh must contain finite numeric values/i, "kwh에 숫자가 아닌 값, NaN 또는 Inf가 있습니다. 0 이상의 유한한 숫자로 준비해 주세요.", false],
    [/kwh cannot be negative/i, "kwh에 음수 값이 있습니다. 시간별 소비 에너지량이 0 이상인지 확인해 주세요.", false],
    [/invalid timestamp|timestamp cannot be NaT/i, "해석할 수 없는 timestamp가 있습니다. ISO 8601 날짜·시각 형식을 확인해 주세요.", false],
    [/timestamps must be aligned to exact hours/i, "정각이 아닌 timestamp가 있습니다. 분과 초가 00인 1시간 단위 시각으로 준비해 주세요.", false],
    [/duplicate physical timestamps/i, "같은 실제 시각의 행이 중복되었습니다. 중복 timestamp를 확인해 주세요.", false],
    [/timestamps must be strictly increasing/i, "timestamp가 시간순으로 정렬되어 있지 않습니다. 오래된 시각부터 오름차순으로 준비해 주세요.", false],
    [/input cadence violates the one-hour contract|input cadence is not hourly/i, "timestamp 간격이 1시간 규격과 맞지 않습니다. 30분·불규칙 간격이 없는지 확인해 주세요.", false],
    [/CSV를 읽을 수 없습니다|CSV 내용이 비어 있습니다/i, "CSV를 읽을 수 없습니다. UTF-8 인코딩, 헤더와 파일 내용을 확인해 주세요.", false],
  ];
  const matched = mappings.find(([pattern]) => pattern.test(message));
  return matched ? { message: matched[1], timeMode: matched[2] } : { message: `${message} 파일 형식과 입력 설정을 확인한 뒤 다시 시도하세요.`, timeMode: false };
}

$("choose-file").onclick = (event) => {
  event.stopPropagation();
  fileInput.click();
};
$("change-file").onclick = () => fileInput.click();
$("clear-file").onclick = clearSelectedFile;
drop.onclick = () => fileInput.click();
drop.onkeydown = (event) => {
  if (event.key === "Enter" || event.key === " ") fileInput.click();
};
fileInput.onchange = () => {
  const [file] = fileInput.files;
  if (!file) return;
  readFile(file).catch((caught) => (error.textContent = caught.message));
};
["dragenter", "dragover"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("dragging");
  }),
);
["dragleave", "drop"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("dragging");
  }),
);
drop.addEventListener("drop", (event) =>
  readFile(event.dataTransfer.files[0]).catch((caught) => (error.textContent = caught.message)),
);

function handleInfluentialInputChange() {
  state.predictionComplete = false;
  clearTimeModeError();
  if (state.analysis || state.analysisSignature) invalidateAnalysis();
  else {
    state.qualityRequestId += 1;
    $("quality-panel").removeAttribute("aria-busy");
    updateAnalyzeAvailability();
    $("analyze").textContent = "데이터 품질 진단하기";
    if (state.csvText) {
      resetQualityPanel("입력 설정이 변경되었습니다. 다시 품질 진단해 주세요.");
      $("selected-file-state").textContent = "입력 설정 변경됨 · 다시 품질 진단 필요";
    }
    updateNextAction();
  }
}

$("timezone").addEventListener("input", handleInfluentialInputChange);
$("warning-approved").addEventListener("change", () => {
  updateAnalyzeAvailability();
  handleInfluentialInputChange();
});

async function api(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "요청을 처리하지 못했습니다.");
  return value;
}

function requestBody() {
  return {
    csv_text: state.csvText,
    building_timezone: $("timezone").value.trim(),
    warning_approved: $("warning-approved").checked,
  };
}

function renderQuality(result) {
  state.analysis = result;
  state.analysisSignature = inputSignature();
  $("empty-state").hidden = true;
  $("quality-result").hidden = false;
  $("quality-panel").removeAttribute("aria-busy");
  $("selected-file-state").textContent = "품질 진단 완료 · 서버 저장 모델과는 별도 상태";
  const quality = result.quality;
  state.warningRequired = Boolean(result.split?.warning_limited_experiment);
  $("warning-approval").hidden = !state.warningRequired;
  const badge = $("status-badge");
  badge.textContent = quality.status;
  badge.className = `status ${quality.status.toLowerCase()}`;
  $("eligibility").textContent = result.training_eligible
    ? "모델 학습을 시작할 수 있습니다."
    : quality.status === "WARNING"
      ? "학습은 가능하지만 제한 실험 동의와 재진단이 필요합니다."
      : "현재 데이터로는 모델을 학습할 수 없습니다.";
  const cards = [
    ["관측 기간", `${fmt(quality.elapsed_days, 0)}일`],
    ["누락된 시간 비율", `${fmt(quality.missing_rate * 100, 2)}%`],
    ["가장 긴 연속 누락", `${fmt(quality.max_consecutive_missing_hours, 0)}시간`],
    ["학습 가능한 168+24시간 조합", fmt(quality.complete_168_plus_24_pairs, 0)],
    ["최장 상수 구간", `${fmt(quality.longest_constant_run_hours, 0)}시간`],
    ["최신 168시간 입력", quality.latest_168_complete ? "완전" : "불완전"],
  ];
  $("quality-cards").innerHTML = cards
    .map(([label, value]) => `<div class="metric-card"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
  const reasons = [...quality.reason_codes, ...result.training_blockers];
  $("reason-list").innerHTML = (reasons.length ? reasons : ["필수 품질 기준을 충족했습니다."])
    .map((reason) => `<li>${qualityReasonText(reason)}</li>`)
    .join("");
  const split = result.split;
  const splitResults = $("quality-split-results");
  if (split) {
    splitResults.hidden = false;
    splitResults.innerHTML = `
      <h3>Train / Validation / Test 시간순 분할</h3>
      <div class="split-grid">
        <div><span>Train</span><strong>${split.train_start.slice(0, 10)} → ${split.train_end.slice(0, 10)}</strong></div>
        <div><span>Validation</span><strong>${split.validation_start.slice(0, 10)} → ${split.validation_end.slice(0, 10)}</strong><small>${split.validation_days}일</small></div>
        <div><span>Test</span><strong>${split.test_start.slice(0, 10)} → ${split.test_end.slice(0, 10)}</strong><small>${split.test_days}일</small></div>
      </div>`;
  } else {
    splitResults.hidden = true;
    splitResults.innerHTML = "";
  }
  $("train").disabled = !result.training_eligible;
  $("training-placeholder").hidden = false;
  $("training-placeholder").textContent = result.training_eligible
    ? "품질 진단을 통과했습니다. XGBoost 모델 학습을 시작할 수 있습니다."
    : "품질 진단의 차단 사유를 해결한 뒤 다시 진단해 주세요.";
  $("workspace-job-status").textContent = result.training_eligible ? "학습 준비 완료" : "학습 불가";
  $("workspace-job-status").dataset.status = result.training_eligible ? "READY" : "BLOCKED";
  $("open-dashboard").hidden = state.job?.status !== "COMPLETED";
  const qualityStatus = quality.status.toLowerCase();
  const stepTwoStatus = qualityStatus === "pass" ? "complete" : qualityStatus === "warning" ? "warning" : "fail";
  setWorkspaceState(
    { 1: "complete", 2: stepTwoStatus, 3: result.training_eligible ? "current" : jobStepStatus() },
    2,
  );
}

function qualityReasonText(code) {
  const messages = {
    FAIL_LESS_THAN_90_DAYS: "관측 기간이 90일 미만입니다. 더 긴 기간의 CSV를 업로드해 주세요.",
    WARNING_90_TO_179_DAYS_APPROVAL_REQUIRED: "관측 기간이 90~179일입니다. 제한 실험에 동의해야 학습할 수 있습니다.",
    FAIL_MISSING_RATE_OVER_5_PERCENT: "누락된 시간 비율이 5%를 초과합니다. 원본 계측 데이터를 확인해 주세요.",
    FAIL_MAX_GAP_OVER_24_HOURS: "24시간을 초과하는 연속 누락 구간이 있습니다. 원본 계측 데이터를 확인해 주세요.",
    WARNING_LONG_CONSTANT_RUN_168H: "같은 사용량이 168시간 이상 이어진 구간이 있습니다. 계량기 상태를 확인해 주세요.",
    WARNING_DOMINANT_VALUE_OVER_50_PERCENT: "한 사용량 값이 전체 데이터의 절반을 초과합니다. 계량기 비활성 여부를 확인해 주세요.",
    WARNING_SUSPECTED_METER_STATE_TRANSITION: "계량기 상태가 바뀐 것으로 의심되는 구간이 있습니다.",
    PASS_QUALITY_THRESHOLDS: "기간, 누락과 연속성에 대한 필수 품질 기준을 충족했습니다.",
    FAIL_TRAIN_ZERO_VARIANCE: "학습 구간의 사용량 변화가 없어 모델을 학습할 수 없습니다.",
    "data is not eligible for a temporal split": "시간순 학습·검증·테스트 구간을 만들 수 없습니다. 데이터 기간과 품질 기준을 확인해 주세요.",
    "90-179 day data requires explicit limited-experiment approval": "90~179일 데이터의 제한 실험 동의가 필요합니다. 아래 동의 항목을 확인한 뒤 다시 진단해 주세요.",
    "training interval is empty": "학습에 사용할 시간 구간이 없습니다. 더 긴 기간의 CSV를 업로드해 주세요.",
  };
  if (messages[code]) return messages[code];
  if (code.startsWith("FAIL_MINIMUM_")) return "학습 또는 평가에 필요한 연속 표본이 부족합니다. 누락 구간과 데이터 기간을 확인해 주세요.";
  return code.replaceAll("_", " ");
}

$("analyze").onclick = async () => {
  error.textContent = "";
  clearTimeModeError();
  const inputError = validateRequiredInputs();
  if (inputError) {
    error.textContent = inputError;
    return;
  }
  $("analyze").disabled = true;
  $("analyze").textContent = "품질 진단 중…";
  const requestId = ++state.qualityRequestId;
  const requestSignature = inputSignature();
  $("empty-state").hidden = false;
  $("quality-result").hidden = true;
  $("empty-state").dataset.panelState = "loading";
  $("quality-empty-title").textContent = "데이터 품질을 진단하고 있습니다.";
  $("quality-empty-copy").textContent = "파일 형식, 관측 기간, 누락된 시간과 학습 가능 여부를 확인합니다.";
  $("quality-preview").hidden = false;
  $("quality-panel").setAttribute("aria-busy", "true");
  $("selected-file-state").textContent = "품질 진단을 위해 로컬 서버에 전송 중";
  setWorkspaceState({ 1: "complete", 2: "in-progress", 3: jobStepStatus() }, 2);
  try {
    const result = await api("/api/quality", requestBody());
    if (requestId !== state.qualityRequestId || requestSignature !== inputSignature()) return;
    renderQuality(result);
  } catch (caught) {
    if (requestId !== state.qualityRequestId || requestSignature !== inputSignature()) return;
    const details = qualityErrorDetails(caught.message);
    error.textContent = `품질 진단을 완료하지 못했습니다: ${details.message}`;
    $("empty-state").hidden = false;
    $("quality-result").hidden = true;
    $("empty-state").dataset.panelState = "error";
    $("quality-empty-title").textContent = "품질 진단을 완료하지 못했습니다.";
    $("quality-empty-copy").textContent = details.message;
    $("selected-file-state").textContent = "진단 오류 · 파일은 브라우저에서 계속 선택된 상태";
    setWorkspaceState({ 1: "complete", 2: "fail", 3: jobStepStatus() }, 2);
  } finally {
    if (requestId !== state.qualityRequestId) return;
    $("quality-panel").removeAttribute("aria-busy");
    updateAnalyzeAvailability();
    $("analyze").textContent = "데이터 품질 진단하기";
  }
};

async function startTraining() {
  error.textContent = "";
  if (!analysisIsCurrent() || !state.analysis.training_eligible) {
    error.textContent = "현재 입력으로 품질 진단을 다시 완료한 뒤 모델 학습을 시작해 주세요.";
    return;
  }
  $("train").disabled = true;
  $("retry-training").hidden = true;
  $("training-placeholder").hidden = true;
  $("training-progress").hidden = false;
  $("training-stage").textContent = "서버에 학습 작업을 등록하고 있습니다.";
  setWorkspaceState({ 1: "complete", 2: state.stepStatuses[2], 3: "in-progress" }, 3);
  try {
    state.job = await api("/api/training-jobs", requestBody());
    state.jobContext = currentContext();
    sessionStorage.setItem(jobSessionKey, JSON.stringify({ jobId: state.job.job_id, context: state.jobContext }));
    renderJob(state.job);
    state.poll = setInterval(pollJob, 2000);
  } catch (caught) {
    error.textContent = `모델 학습을 시작하지 못했습니다: ${caught.message} 품질 진단 결과와 제한 실험 동의를 확인해 주세요.`;
    setWorkspaceState({ 1: "complete", 2: state.stepStatuses[2], 3: "fail" }, 3);
    $("training-progress").hidden = true;
    $("retry-training").hidden = false;
    $("workspace-job-status").textContent = "학습 시작 실패";
    $("workspace-job-status").dataset.status = "FAILED";
  }
}

$("train").onclick = startTraining;
$("retry-training").onclick = startTraining;

function metricText(metric) {
  if (!metric || !Number.isFinite(metric.mae)) return "평가 결과 없음";
  const wape = Number.isFinite(metric.wape) ? `${fmt(metric.wape * 100, 1)}%` : "—";
  return `MAE ${fmt(metric.mae, 3)} kWh · WAPE ${wape}`;
}

function renderJob(job) {
  const chip = $("job-status");
  chip.textContent = `${jobStatusText(job.status)} · ${job.progress_message}`;
  chip.dataset.status = job.status;
  const workspaceChip = $("workspace-job-status");
  workspaceChip.textContent = `${jobStatusText(job.status)} · ${job.progress_message}`;
  workspaceChip.dataset.status = job.status;
  const completed = job.status === "COMPLETED";
  $("open-dashboard").hidden = !completed;
  if (["QUEUED", "RUNNING"].includes(job.status)) {
    $("training-placeholder").hidden = true;
    $("training-progress").hidden = false;
    $("training-stage").textContent = job.progress_message;
    $("workspace-model-results").hidden = true;
    $("retry-training").hidden = true;
    $("train").disabled = true;
    $("model-state").textContent = "학습 진행 중";
    setWorkspaceState({ 1: "complete", 2: "complete", 3: "in-progress" }, 3);
    updateNextAction();
    return;
  }
  if (job.status === "FAILED") {
    $("training-progress").hidden = true;
    $("training-placeholder").hidden = false;
    $("training-placeholder").textContent = job.error || "학습에 실패했습니다. 입력과 서버 로그를 확인해 주세요.";
    $("retry-training").hidden = !analysisIsCurrent();
    $("train").disabled = true;
    error.textContent = job.error ? `모델 학습을 완료하지 못했습니다: ${job.error}` : "모델 학습을 완료하지 못했습니다. 입력 데이터와 서버 로그를 확인한 뒤 다시 시도하세요.";
    $("model-state").textContent = "학습 실패";
    setWorkspaceState({ 1: "complete", 2: "complete", 3: "fail" }, 3);
    updateNextAction();
  }
  if (!completed) return;

  setWorkspaceState({ 1: "complete", 2: "complete", 3: "complete" }, 3);
  $("training-progress").hidden = true;
  $("training-placeholder").hidden = true;
  $("retry-training").hidden = true;
  $("train").disabled = true;
  $("workspace-model-results").hidden = false;
  const names = { xgboost: "xgboost", last_24h: "last-24h", last_168h: "last-168h" };
  Object.entries(names).forEach(([key, id]) => {
    const metric = job.validation_metrics?.[key];
    $("metric-" + id).textContent = metricText(metric);
    $("model-" + id).classList.toggle("selected", job.selected_model === key);
    $("workspace-metric-" + id).textContent = metricText(metric);
    $("workspace-model-" + id).classList.toggle("selected", job.selected_model === key);
  });
  const selectedTest = job.test_metrics?.[job.selected_model];
  $("test-evaluation-note").textContent = selectedTest
    ? `선택 모델 ${job.selected_model} · Test 최종 평가 ${metricText(selectedTest)}`
    : "Test는 Validation에서 선택한 모델의 최종 성능 확인에만 사용합니다.";
  $("model-state").textContent = "모델 준비 완료";
  $("selected-model").textContent = job.selected_model || "—";
  $("run-id").textContent = job.run_dir ? job.run_dir.split(/[\\/]/).at(-1) : "—";
  updateNextAction();
}

function jobStatusText(status) {
  return { QUEUED: "학습 대기", RUNNING: "학습 진행 중", COMPLETED: "학습 완료", FAILED: "학습 실패" }[status] || status;
}

async function pollJob() {
  if (!state.job) return;
  try {
    const response = await fetch(`/api/training-jobs/${state.job.job_id}`);
    if (!response.ok) throw new Error("서버에서 학습 작업 상태를 확인하지 못했습니다.");
    const job = await response.json();
    state.job = job;
    renderJob(job);
    if (["COMPLETED", "FAILED"].includes(job.status)) {
      clearInterval(state.poll);
      state.poll = null;
      $("train").disabled = true;
    }
  } catch (caught) {
    clearInterval(state.poll);
    state.poll = null;
    error.textContent = caught.message;
  }
}

$("open-dashboard").onclick = () => navigate("/dashboard");
$("dashboard-empty-action").onclick = () => navigate("/workspace");
$("return-workspace").onclick = () => navigate("/workspace");

async function recoverJob() {
  let saved;
  try {
    saved = JSON.parse(sessionStorage.getItem(jobSessionKey) || "null");
  } catch {
    sessionStorage.removeItem(jobSessionKey);
    return;
  }
  if (!saved?.jobId) return;
  state.jobContext = saved.context || null;
  if (state.jobContext) {
    $("timezone").value = state.jobContext.timezone || $("timezone").value;
  }
  try {
    const response = await fetch(`/api/training-jobs/${saved.jobId}`);
    if (!response.ok) throw new Error("저장된 학습 작업을 현재 서버에서 찾을 수 없습니다.");
    state.job = await response.json();
    renderJob(state.job);
    if (["QUEUED", "RUNNING"].includes(state.job.status) && !state.poll) {
      state.poll = setInterval(pollJob, 2000);
    }
  } catch (caught) {
    sessionStorage.removeItem(jobSessionKey);
    state.job = null;
    state.jobContext = null;
    $("job-status").textContent = "진행 중인 모델 학습이 없습니다.";
    $("job-status").removeAttribute("data-status");
    updateNextAction();
    if (state.route === "/dashboard") {
      $("dashboard-error").hidden = false;
      $("dashboard-error").textContent = `${caught.message} 이 로컬 버전은 서버가 재시작되면 이전 학습 상태를 자동으로 복원할 수 없습니다. 데이터 분석에서 상태를 다시 확인해 주세요.`;
    }
  }
}

function displayTime(value) {
  return new Date(value).toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function runPrediction(source) {
  const dashboardButton = $("run-prediction");
  const workspaceButton = $("workspace-run-prediction");
  const sourceButton = source === "workspace" ? workspaceButton : dashboardButton;
  const sourceError = source === "workspace" ? error : $("dashboard-error");
  $("dashboard-error").hidden = true;
  $("dashboard-error").textContent = "";
  if (source === "workspace") error.textContent = "";
  dashboardButton.disabled = true;
  workspaceButton.disabled = true;
  sourceButton.textContent = "예측 중…";
  if (source === "workspace") $("workspace-prediction-summary").textContent = "저장된 모델로 24시간 예측을 생성하고 있습니다.";
  try {
    const result = await api(`/api/predictions/${state.job.job_id}`, requestBody());
    drawPredictionChart(result.history_kwh, result.predictions_kwh);
    $("total-forecast").innerHTML = `${fmt(result.total_kwh)} <small>kWh</small>`;
    $("peak-forecast").textContent = `${fmt(result.peak_kwh)} kWh`;
    $("peak-time").textContent = displayTime(result.peak_timestamp);
    $("forecast-reference").textContent = `예측 시작 기준: ${displayTime(result.forecast_origin)}`;
    $("forecast-timezone").textContent = `시간대: ${$("timezone").value.trim()}`;
    $("sample-tag").textContent = "실제 예측 결과";
    $("sample-note").textContent = `학습 기록 ${result.run_id} · ${result.model_kind} · 저장된 모델로 생성한 실제 예측`;
    $("workspace-prediction-summary").textContent = `예측 완료 · 총 ${fmt(result.total_kwh)} kWh · 최대 ${fmt(result.peak_kwh)} kWh · 피크 ${displayTime(result.peak_timestamp)}`;
    state.predictionComplete = true;
    updateNextAction();
  } catch (caught) {
    const message = `예측에 실패했습니다: ${caught.message} 입력 CSV와 시간대를 확인한 뒤 다시 시도하세요.`;
    sourceError.hidden = false;
    sourceError.textContent = message;
    if (source === "workspace") $("workspace-prediction-summary").textContent = "예측을 완료하지 못했습니다. 오류 안내를 확인한 뒤 다시 시도하세요.";
  } finally {
    dashboardButton.textContent = "24시간 예측 실행";
    workspaceButton.textContent = "24시간 예측 실행";
    updateNextAction();
  }
}

$("run-prediction").onclick = () => runPrediction("dashboard");
$("workspace-run-prediction").onclick = () => runPrediction("workspace");

function drawPredictionChart(history, forecast) {
  const svg = $("forecast-chart");
  const all = [...history, ...forecast];
  const width = 680;
  const height = 210;
  const padding = 28;
  const max = Math.max(...all);
  const min = Math.min(...all);
  const range = Math.max(max - min, 0.001);
  const point = (value, index) =>
    `${padding + (index * (width - 2 * padding)) / (all.length - 1)},${height - padding - ((value - min) * (height - 2 * padding)) / range}`;
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (tick) =>
        `<line x1="${padding}" y1="${padding + tick * (height - 2 * padding)}" x2="${width - padding}" y2="${padding + tick * (height - 2 * padding)}" stroke="#e4e7df"/>`,
    )
    .join("");
  const historyPoints = history.map(point).join(" ");
  const forecastPoints = forecast.map((value, index) => point(value, index + history.length)).join(" ");
  svg.innerHTML = `<g transform="translate(10,20)">${grid}<polyline points="${historyPoints}" fill="none" stroke="#a3aea7" stroke-width="3"/><polyline points="${forecastPoints}" fill="none" stroke="#235c45" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><text x="${padding}" y="240" fill="#69756e" font-size="11">12시간 전</text><text x="250" y="240" fill="#69756e" font-size="11">현재</text><text x="610" y="240" fill="#69756e" font-size="11">+24h</text></g>`;
}

function drawEmptyChart() {
  const svg = $("forecast-chart");
  const grid = [54, 94, 134, 174, 214]
    .map((y) => `<line x1="42" y1="${y}" x2="678" y2="${y}" stroke="#e4e7df"/>`)
    .join("");
  svg.innerHTML = `${grid}<text class="empty-chart-label" x="360" y="126">아직 실행된 예측이 없습니다.</text><text class="empty-chart-help" x="360" y="150">저장된 모델이 없다면 CSV를 업로드하고 모델을 먼저 준비해 주세요.</text>`;
}

drawEmptyChart();
renderWorkspaceSteps();
const initialRoute = normalizeRoute(location.pathname);
if (initialRoute !== location.pathname) history.replaceState({}, "", initialRoute);
renderRoute(initialRoute, { scroll: false });
recoverJob();
