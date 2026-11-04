const state = {
  csvText: "",
  fileName: "",
  analysis: null,
  job: null,
  poll: null,
  fileToken: "",
  analysisSignature: "",
  jobContext: null,
  predictionComplete: false,
  warningRequired: false,
  observationDays: null,
  qualityRequestId: 0,
  viewedStep: 1,
  stepStatuses: { 1: "current", 2: "waiting", 3: "waiting" },
  aiAnalysisAvailable: false,
  aiAnalysisModel: "",
  aiAnalysisComplete: false,
  jobRecovered: false,
};

const $ = (id) => document.getElementById(id);
const fileInput = $("csv-file");
const drop = $("drop-zone");
const error = $("form-error");
const jobSessionKey = "energy-planner.active-job.v1";

function fmt(number, digits = 1) {
  return Number(number).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function scrollToSection(id, { smooth = true, updateHistory = true } = {}) {
  const target = $(id);
  if (!target) return;
  const nextLocation = id === "top" ? "/" : `/#${id}`;
  if (updateHistory && `${location.pathname}${location.hash}` !== nextLocation) {
    history.pushState({}, "", nextLocation);
  }
  const stickyOffset = window.matchMedia("(max-width: 800px)").matches ? 126 : 145;
  const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - stickyOffset);
  window.scrollTo({
    top,
    behavior: smooth && !window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "auto",
  });
}

document.addEventListener("click", (event) => {
  const control = event.target.closest("[data-scroll-target]");
  if (!control || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  scrollToSection(control.dataset.scrollTarget);
});

if ("scrollRestoration" in history) history.scrollRestoration = "manual";
window.addEventListener("popstate", () => {
  scrollToSection(location.hash.slice(1) || "top", { smooth: false, updateHistory: false });
});

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
  document.querySelectorAll("[data-workflow-step]").forEach((step) => {
    const number = Number(step.dataset.workflowStep);
    if (number === 4) return;
    const status = state.stepStatuses[number] || "waiting";
    step.dataset.status = status;
    step.dataset.statusLabel = statusLabel(status);
  });
}

function switchWorkspaceStep(number, { scroll = true } = {}) {
  state.viewedStep = Math.min(3, Math.max(1, number));
  renderWorkspaceSteps();
  if (scroll) {
    const panel = document.querySelector(`[data-step-panel="${state.viewedStep}"]`);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    panel?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    panel?.focus({ preventScroll: true });
  }
}

function setWorkspaceState(statuses, viewedStep = state.viewedStep) {
  state.stepStatuses = { ...state.stepStatuses, ...statuses };
  state.viewedStep = viewedStep;
  renderWorkspaceSteps();
  updateNextAction();
}

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
  $("training-progress").hidden = false;
  $("workspace-model-results").hidden = true;
  $("workspace-job-status").textContent = "학습 대기";
  $("workspace-job-status").removeAttribute("data-status");
  $("train").disabled = true;
  $("train").textContent = "XGBoost 학습 시작 ↗";
  setTrainingProgress(0, message);
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
  $("quality-heading-status").textContent = "진단 대기";
  $("quality-heading-status").className = "status";
  $("train").disabled = true;
}

function resetAIAnalysis() {
  state.aiAnalysisComplete = false;
  $("ai-analysis-result").hidden = true;
  $("ai-summary").textContent = "";
  $("ai-peak").textContent = "";
  $("ai-patterns").replaceChildren();
  $("ai-cautions").replaceChildren();
}

function resetDashboardPrediction() {
  $("dashboard-gate").hidden = false;
  $("dashboard-results").hidden = true;
  $("total-forecast").textContent = "—";
  $("average-forecast").textContent = "예측 실행 전";
  $("peak-forecast").textContent = "예측 실행 전";
  $("peak-time").textContent = "예측 실행 전";
  $("forecast-reference").textContent = "예측 시작 기준: 미설정";
  $("forecast-timezone").textContent = "시간대: 미설정";
  $("forecast-table-body").replaceChildren();
  $("daily-usage-chart").innerHTML = "";
  $("period-composition-list").replaceChildren();
  $("period-donut").style.background = "conic-gradient(var(--line) 0 100%)";
  $("monthly-usage-list").replaceChildren();
  $("actual-summary-label").textContent = "예측 실행 후 표시";
  drawEmptyChart();
}

function invalidateAnalysis(message = "입력이 변경되어 재검증이 필요합니다.") {
  const hadAnalysis = Boolean(state.analysis);
  state.qualityRequestId += 1;
  $("quality").removeAttribute("aria-busy");
  updateAnalyzeAvailability();
  $("analyze").textContent = "데이터 품질 진단하기";
  state.predictionComplete = false;
  resetAIAnalysis();
  resetDashboardPrediction();
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

function setDashboardReadiness(key, status, label, description) {
  const item = document.querySelector(`[data-readiness-key="${key}"]`);
  if (!item) return;
  item.dataset.state = status;
  item.querySelector(".readiness-state").textContent = label;
  if (description) item.querySelector(".readiness-copy small").textContent = description;
}

function updateNextAction() {
  const completed = state.job?.status === "COMPLETED";
  const running = ["QUEUED", "RUNNING"].includes(state.job?.status);
  const failed = state.job?.status === "FAILED";
  const currentAnalysis = analysisIsCurrent();
  const contextMatches = contextsMatch(state.jobContext, currentContext());
  const hasInput = Boolean(state.csvText) || state.jobRecovered;
  const qualityReady = currentAnalysis || state.jobRecovered;
  const canPredict = completed && (
    (Boolean(state.csvText) && currentAnalysis && contextMatches)
    || (!state.csvText && state.jobRecovered)
  );
  const homeCta = $("home-primary-cta");
  const homeLabel = $("home-cta-label");
  let homeTarget = "upload";
  let homeText = "전력 분석 시작";

  if (completed) {
    homeTarget = canPredict ? "dashboard" : "upload";
    homeText = canPredict ? "24시간 예측 실행" : "예측 입력 준비하기";
  } else if (running) {
    homeTarget = "training";
    homeText = "학습 상태 확인";
  } else if (currentAnalysis && state.analysis.training_eligible) {
    homeTarget = "training";
    homeText = "모델 학습 계속하기";
  } else if (state.csvText) {
    homeTarget = "quality";
    homeText = "품질 진단 계속하기";
  }

  homeCta.href = `#${homeTarget}`;
  homeCta.dataset.scrollTarget = homeTarget;
  homeLabel.textContent = homeText;

  setDashboardReadiness(
    "upload",
    hasInput ? "complete" : "current",
    hasInput ? "완료" : "현재 단계",
    state.jobRecovered ? "저장된 학습 입력을 사용합니다." : hasInput ? "선택된 시간별 CSV가 준비되었습니다." : "시간별 전력 사용량 CSV를 선택해 주세요.",
  );
  setDashboardReadiness(
    "quality",
    qualityReady ? "complete" : state.csvText ? "current" : "waiting",
    qualityReady ? "완료" : state.csvText ? "다음 단계" : "대기",
    qualityReady ? "예측에 필요한 데이터 품질 기준을 확인했습니다." : state.csvText ? "업로드한 CSV의 품질을 진단해 주세요." : "CSV 업로드 후 진단할 수 있습니다.",
  );
  setDashboardReadiness(
    "training",
    completed ? "complete" : running ? "in-progress" : failed ? "fail" : currentAnalysis && state.analysis?.training_eligible ? "current" : "waiting",
    completed ? "완료" : running ? "진행 중" : failed ? "확인 필요" : currentAnalysis && state.analysis?.training_eligible ? "다음 단계" : "대기",
    completed ? "저장된 모델과 평가 결과가 준비되었습니다." : running ? "XGBoost와 기준 모델을 평가하고 있습니다." : failed ? "오류를 확인한 뒤 같은 버튼으로 다시 시작할 수 있습니다." : currentAnalysis && state.analysis?.training_eligible ? "XGBoost 모델 학습을 시작해 주세요." : "품질 진단 통과 후 학습할 수 있습니다.",
  );
  setDashboardReadiness(
    "prediction",
    state.predictionComplete ? "complete" : canPredict ? "ready" : "waiting",
    state.predictionComplete ? "완료" : canPredict ? "실행 가능" : "대기",
    state.predictionComplete ? "실제 24시간 예측 결과를 생성했습니다." : canPredict ? "준비된 모델로 24시간 예측을 실행할 수 있습니다." : "모델 학습 완료 후 실행할 수 있습니다.",
  );

  let gateTitle = "예측 결과를 만들기 위한 준비가 필요합니다.";
  let gateDescription = "CSV 업로드부터 모델 학습까지 순서대로 완료하면 실제 예측 결과가 표시됩니다.";
  let gateActionTarget = "upload";
  let gateActionText = "CSV 업로드 시작";
  if (running) {
    gateTitle = "모델 학습이 진행 중입니다.";
    gateDescription = "학습이 완료되면 이 화면에서 24시간 예측을 실행할 수 있습니다.";
    gateActionTarget = "training";
    gateActionText = "학습 진행 상태 보기";
  } else if (failed) {
    gateTitle = "모델 학습 상태를 확인해 주세요.";
    gateDescription = "학습 오류 안내를 확인한 뒤 XGBoost 학습을 다시 시작할 수 있습니다.";
    gateActionTarget = "training";
    gateActionText = "학습 상태 확인";
  } else if (completed && canPredict) {
    gateTitle = "24시간 예측을 실행할 준비가 완료되었습니다.";
    gateDescription = "저장된 모델과 최신 168시간 입력으로 실제 예측 결과를 생성합니다.";
  } else if (completed) {
    gateTitle = "예측 입력을 다시 확인해 주세요.";
    gateDescription = "저장된 모델은 준비됐지만 현재 CSV 입력을 다시 진단해야 합니다.";
    gateActionText = "예측 입력 준비";
  } else if (currentAnalysis && state.analysis?.training_eligible) {
    gateTitle = "XGBoost 모델 학습을 시작해 주세요.";
    gateDescription = "데이터 품질 진단을 통과했습니다. 학습이 완료되면 예측을 실행할 수 있습니다.";
    gateActionTarget = "training";
    gateActionText = "모델 학습으로 이동";
  } else if (state.csvText) {
    gateTitle = "업로드한 CSV의 품질을 확인해 주세요.";
    gateDescription = "필수 컬럼, 관측 기간과 시간 연속성을 확인한 뒤 모델을 학습합니다.";
    gateActionTarget = "quality";
    gateActionText = "품질 진단으로 이동";
  }
  $("dashboard-gate-title").textContent = gateTitle;
  $("dashboard-gate-description").textContent = gateDescription;
  const gateAction = $("dashboard-empty-action");
  const showPredictionAction = completed && canPredict && !state.predictionComplete;
  gateAction.hidden = showPredictionAction;
  gateAction.dataset.target = gateActionTarget;
  gateAction.textContent = gateActionText;
  $("run-prediction").hidden = !showPredictionAction;
  $("run-prediction").disabled = !canPredict;
  $("dashboard-gate").hidden = state.predictionComplete;
  $("dashboard-results").hidden = !state.predictionComplete;

  const dashboardStatus = $("job-status");
  dashboardStatus.removeAttribute("data-status");
  if (state.predictionComplete) {
    dashboardStatus.textContent = "예측 완료";
    dashboardStatus.dataset.status = "COMPLETED";
  } else if (canPredict) {
    dashboardStatus.textContent = "예측 준비 완료";
    dashboardStatus.dataset.status = "READY";
  } else if (running) {
    dashboardStatus.textContent = "모델 학습 중";
    dashboardStatus.dataset.status = "RUNNING";
  } else if (failed) {
    dashboardStatus.textContent = "학습 확인 필요";
    dashboardStatus.dataset.status = "FAILED";
  } else {
    dashboardStatus.textContent = "준비 필요";
  }

  $("ai-analyze").disabled = !state.predictionComplete || !state.aiAnalysisAvailable;
  if (!state.aiAnalysisAvailable) {
    $("ai-analysis-status").textContent = "OPENAI_API_KEY가 설정되지 않아 AI 해석은 비활성화되어 있습니다. 기본 예측 기능은 정상적으로 사용할 수 있습니다.";
  } else if (!state.predictionComplete) {
    $("ai-analysis-status").textContent = "24시간 예측을 먼저 실행해 주세요.";
  } else if (!state.aiAnalysisComplete) {
    $("ai-analysis-status").textContent = `AI 해석을 실행할 수 있습니다${state.aiAnalysisModel ? ` · ${state.aiAnalysisModel}` : ""}.`;
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
  state.jobRecovered = false;
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
  resetAIAnalysis();
  resetDashboardPrediction();
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
  resetAIAnalysis();
  resetDashboardPrediction();
  clearTimeModeError();
  if (state.analysis || state.analysisSignature) invalidateAnalysis();
  else {
    state.qualityRequestId += 1;
    $("quality").removeAttribute("aria-busy");
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
  $("quality").removeAttribute("aria-busy");
  $("selected-file-state").textContent = "품질 진단 완료 · 서버 저장 모델과는 별도 상태";
  const quality = result.quality;
  state.warningRequired = Boolean(result.split?.warning_limited_experiment);
  $("warning-approval").hidden = !state.warningRequired;
  const badge = $("status-badge");
  badge.textContent = quality.status;
  badge.className = `status ${quality.status.toLowerCase()}`;
  const headingBadge = $("quality-heading-status");
  headingBadge.textContent = quality.status;
  headingBadge.className = `status ${quality.status.toLowerCase()}`;
  $("eligibility").textContent = result.training_eligible
    ? "모델 학습을 시작할 수 있습니다."
    : quality.status === "WARNING"
      ? "학습은 가능하지만 제한 실험 동의와 재진단이 필요합니다."
      : "현재 데이터로는 모델을 학습할 수 없습니다.";
  const continuityRate = quality.expected_hours > 0
    ? quality.observed_hours / quality.expected_hours
    : 0;
  const eligibilityLabel = result.training_eligible
    ? quality.status === "WARNING" ? "확인 필요" : "적합"
    : "부적합";
  const cards = [
    ["관측 기간", `${fmt(quality.elapsed_days, 0)}일`, quality.elapsed_days >= 180 ? "권장 기간 충족" : "최소 90일"],
    ["결측률", `${fmt(quality.missing_rate * 100, 2)}%`, `연속 누락 최대 ${fmt(quality.max_consecutive_missing_hours, 0)}시간`],
    ["시간 연속성", `${fmt(continuityRate * 100, 2)}%`, `${fmt(quality.observed_hours, 0)} / ${fmt(quality.expected_hours, 0)}시간`],
    ["학습 적합성", eligibilityLabel, result.training_eligible ? "시간순 학습 가능" : "차단 사유 확인"],
  ];
  $("quality-cards").innerHTML = cards
    .map(([label, value, foot]) => `<div class="metric-card"><span>${label}</span><strong>${value}</strong><small>${foot}</small></div>`)
    .join("");
  const observationState = quality.elapsed_days >= 180 ? "pass" : quality.elapsed_days >= 90 ? "warning" : "fail";
  const observationText = quality.elapsed_days >= 180 ? "통과" : quality.elapsed_days >= 90 ? "최소 기간 충족 · 확인 필요" : "90일 미만";
  const inputWindowState = quality.latest_168_complete ? "pass" : "fail";
  const splitState = result.split ? "pass" : "fail";
  const details = [
    ["필수 컬럼 및 형식", result.contract_status === "PASS" ? "통과" : "확인 필요", result.contract_status === "PASS" ? "pass" : "fail"],
    ["최소 관측 기간", observationText, observationState],
    ["입력용 168시간 구간", quality.latest_168_complete ? "통과" : "최신 구간 불완전", inputWindowState],
    ["시간순 Train / Validation / Test 분리", result.split ? "가능" : "분리 불가", splitState],
  ];
  const checkIcon = '<svg class="detail-state-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="m4 10.5 3.5 3.5L16 5.5"/></svg>';
  $("quality-detail-list").innerHTML = details
    .map(([label, value, detailState]) => `<div class="detail-row"><span>${label}</span><strong class="detail-state" data-state="${detailState}">${detailState === "pass" ? checkIcon : ""}<span>${value}</span></strong></div>`)
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
  setTrainingProgress(0, result.training_eligible
    ? "품질 진단을 통과했습니다. XGBoost 모델 학습을 시작할 수 있습니다."
    : "품질 진단의 차단 사유를 해결한 뒤 다시 진단해 주세요.");
  $("workspace-job-status").textContent = result.training_eligible ? "학습 준비 완료" : "학습 불가";
  $("workspace-job-status").dataset.status = result.training_eligible ? "READY" : "BLOCKED";
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
  $("quality").setAttribute("aria-busy", "true");
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
    $("quality").removeAttribute("aria-busy");
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
  $("training-progress").hidden = false;
  setTrainingProgress(2, "서버에 학습 작업을 등록하고 있습니다.");
  setWorkspaceState({ 1: "complete", 2: state.stepStatuses[2], 3: "in-progress" }, 3);
  try {
    state.job = await api("/api/training-jobs", requestBody());
    state.jobRecovered = false;
    state.jobContext = currentContext();
    sessionStorage.setItem(jobSessionKey, JSON.stringify({ jobId: state.job.job_id, context: state.jobContext }));
    renderJob(state.job);
    state.poll = setInterval(pollJob, 2000);
  } catch (caught) {
    error.textContent = `모델 학습을 시작하지 못했습니다: ${caught.message} 품질 진단 결과와 제한 실험 동의를 확인해 주세요.`;
    setWorkspaceState({ 1: "complete", 2: state.stepStatuses[2], 3: "fail" }, 3);
    setTrainingProgress(0, "학습을 시작하지 못했습니다. 입력과 서버 상태를 확인한 뒤 다시 시도해 주세요.");
    $("train").disabled = !analysisIsCurrent();
    $("workspace-job-status").textContent = "학습 시작 실패";
    $("workspace-job-status").dataset.status = "FAILED";
  }
}

$("train").onclick = startTraining;

function setTrainingProgress(percent, message) {
  const value = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
  $("training-stage").textContent = message;
  $("training-percent").textContent = `${value}%`;
  $("training-progress-fill").style.width = `${value}%`;
  const progressbar = $("training-progressbar");
  progressbar.setAttribute("aria-valuenow", String(value));
  progressbar.setAttribute("aria-valuetext", `${message} ${value}%`);
}

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
  if (["QUEUED", "RUNNING"].includes(job.status)) {
    $("training-progress").hidden = false;
    setTrainingProgress(job.progress_percent, job.progress_message);
    $("workspace-model-results").hidden = true;
    $("train").disabled = true;
    setWorkspaceState({ 1: "complete", 2: "complete", 3: "in-progress" }, 3);
    updateNextAction();
    return;
  }
  if (job.status === "FAILED") {
    $("training-progress").hidden = false;
    setTrainingProgress(job.progress_percent ?? 0, job.error || "학습에 실패했습니다. 입력과 서버 로그를 확인해 주세요.");
    $("train").disabled = !analysisIsCurrent();
    error.textContent = job.error ? `모델 학습을 완료하지 못했습니다: ${job.error}` : "모델 학습을 완료하지 못했습니다. 입력 데이터와 서버 로그를 확인한 뒤 다시 시도하세요.";
    setWorkspaceState({ 1: "complete", 2: "complete", 3: "fail" }, 3);
    updateNextAction();
  }
  if (!completed) return;

  setWorkspaceState({ 1: "complete", 2: "complete", 3: "complete" }, 3);
  $("training-progress").hidden = false;
  setTrainingProgress(job.progress_percent ?? 100, job.progress_message);
  $("train").disabled = true;
  $("workspace-model-results").hidden = false;
  const names = { xgboost: "xgboost", last_24h: "last-24h", last_168h: "last-168h" };
  Object.entries(names).forEach(([key, id]) => {
    const metric = job.validation_metrics?.[key];
    $("workspace-metric-" + id).textContent = metricText(metric);
    $("workspace-model-" + id).classList.toggle("selected", job.selected_model === key);
  });
  const selectedTest = job.test_metrics?.[job.selected_model];
  $("test-evaluation-note").textContent = selectedTest
    ? `Validation 선택 모델 ${job.selected_model} · Test는 모델 선택에 사용하지 않으며 최종 평가만 수행 · ${metricText(selectedTest)}`
    : "Test는 Validation에서 선택한 모델의 최종 성능 확인에만 사용합니다.";
  $("selected-model").textContent = job.selected_model || "—";
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

$("dashboard-empty-action").onclick = () => scrollToSection($("dashboard-empty-action").dataset.target || "upload");

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
    state.jobRecovered = state.job.status === "COMPLETED" && !state.csvText;
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
    if (location.hash === "#dashboard") {
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

function renderForecastTable(timestamps, values) {
  const fragment = document.createDocumentFragment();
  timestamps.forEach((timestamp, index) => {
    const row = document.createElement("tr");
    const time = document.createElement("td");
    const amount = document.createElement("td");
    time.textContent = displayTime(timestamp);
    amount.textContent = `${fmt(values[index], 2)} kWh`;
    row.append(time, amount);
    fragment.append(row);
  });
  $("forecast-table-body").replaceChildren(fragment);
}

function drawDailyUsage(values) {
  const svg = $("daily-usage-chart");
  if (!values.length) {
    svg.innerHTML = "";
    return;
  }
  const width = 520;
  const height = 240;
  const baseline = 194;
  const max = Math.max(...values.map((item) => item.kwh), 0.001);
  const barWidth = 48;
  const gap = 20;
  const bars = values.map((item, index) => {
    const barHeight = (item.kwh / max) * 144;
    const x = 24 + index * (barWidth + gap);
    const y = baseline - barHeight;
    const label = item.date.slice(5);
    return `<g data-usage-bar="${index}" tabindex="0" role="img" aria-label="${item.date} ${fmt(item.kwh, 1)} kWh"><rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="3" fill="#2855da"><title>${item.date}: ${fmt(item.kwh, 1)} kWh</title></rect><text x="${x + barWidth / 2}" y="216" text-anchor="middle" fill="#66738a" font-size="11">${label}</text></g>`;
  }).join("");
  svg.innerHTML = `<line x1="18" y1="${baseline}" x2="502" y2="${baseline}" stroke="#bac3cc"/>${bars}`;
  svg.querySelectorAll("[data-usage-bar]").forEach((bar) => {
    const item = values[Number(bar.dataset.usageBar)];
    const show = (event) => showUsageTooltip(event, `${item.date} · ${fmt(item.kwh, 1)} kWh`);
    bar.addEventListener("pointermove", show);
    bar.addEventListener("focus", show);
    bar.addEventListener("click", show);
  });
  svg.addEventListener("pointerleave", hideUsageTooltip);
}

function showUsageTooltip(event, text) {
  const tooltip = $("usage-tooltip");
  const panel = tooltip?.parentElement;
  if (!tooltip || !panel) return;
  const sourceRect = event.currentTarget?.getBoundingClientRect?.() || panel.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const clientX = Number.isFinite(event.clientX) && event.clientX ? event.clientX : sourceRect.left + sourceRect.width / 2;
  const clientY = Number.isFinite(event.clientY) && event.clientY ? event.clientY : sourceRect.top;
  tooltip.textContent = text;
  tooltip.hidden = false;
  tooltip.style.left = `${Math.max(8, Math.min(panel.clientWidth - tooltip.offsetWidth - 8, clientX - panelRect.left + 10))}px`;
  tooltip.style.top = `${Math.max(8, clientY - panelRect.top - tooltip.offsetHeight - 10)}px`;
}

function hideUsageTooltip() {
  const tooltip = $("usage-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function renderPeriodComposition(values) {
  const colors = ["#204ed5", "#35bee4", "#b8e85b", "#17212c"];
  let cursor = 0;
  const stops = values.map((item, index) => {
    const start = cursor;
    cursor += item.share * 100;
    return `${colors[index]} ${start}% ${cursor}%`;
  });
  const donut = $("period-donut");
  donut.style.background = `conic-gradient(${stops.join(",")})`;
  donut.setAttribute("aria-label", values.map((item) => `${item.label} ${fmt(item.share * 100, 1)}%`).join(", "));
  donut.tabIndex = 0;
  const donutItemAtPointer = (event) => {
    const rect = donut.getBoundingClientRect();
    const angle = (Math.atan2(event.clientY - (rect.top + rect.height / 2), event.clientX - (rect.left + rect.width / 2)) * 180 / Math.PI + 450) % 360;
    let cursorShare = 0;
    return values.find((item) => {
      cursorShare += item.share * 360;
      return angle <= cursorShare;
    }) || values.at(-1);
  };
  donut.onpointermove = (event) => {
    const item = donutItemAtPointer(event);
    showUsageTooltip(event, `${item.label} · ${fmt(item.share * 100, 1)}%`);
  };
  donut.onclick = donut.onpointermove;
  donut.onfocus = (event) => {
    const item = values[0];
    if (item) showUsageTooltip(event, `${item.label} · ${fmt(item.share * 100, 1)}%`);
  };
  donut.onpointerleave = hideUsageTooltip;
  donut.onblur = hideUsageTooltip;
  const fragment = document.createDocumentFragment();
  values.forEach((item, index) => {
    const row = document.createElement("li");
    const swatch = document.createElement("i");
    const label = document.createElement("span");
    const value = document.createElement("strong");
    swatch.style.background = colors[index];
    label.textContent = item.label;
    value.textContent = `${fmt(item.share * 100, 1)}%`;
    row.tabIndex = 0;
    row.addEventListener("pointerenter", (event) => showUsageTooltip(event, `${item.label} · ${value.textContent}`));
    row.addEventListener("focus", (event) => showUsageTooltip(event, `${item.label} · ${value.textContent}`));
    row.addEventListener("pointerleave", hideUsageTooltip);
    row.addEventListener("blur", hideUsageTooltip);
    row.append(swatch, label, value);
    fragment.append(row);
  });
  $("period-composition-list").replaceChildren(fragment);
}

function renderMonthlyUsage(values) {
  const fragment = document.createDocumentFragment();
  values.forEach((item) => {
    const card = document.createElement("div");
    card.className = "monthly-usage-item";
    const label = document.createElement("span");
    const value = document.createElement("strong");
    label.textContent = item.month;
    value.textContent = `${fmt(item.kwh, 1)} kWh`;
    card.append(label, value);
    fragment.append(card);
  });
  $("monthly-usage-list").replaceChildren(fragment);
}

async function runPrediction() {
  const dashboardButton = $("run-prediction");
  const sourceError = $("dashboard-error");
  const dashboardGate = $("dashboard-gate");
  $("dashboard-error").hidden = true;
  $("dashboard-error").textContent = "";
  resetAIAnalysis();
  dashboardButton.disabled = true;
  dashboardButton.textContent = "예측 중…";
  dashboardGate.setAttribute("aria-busy", "true");
  $("dashboard-gate-title").textContent = "24시간 예측을 생성하고 있습니다.";
  $("dashboard-gate-description").textContent = "저장된 모델과 최신 입력을 확인한 뒤 결과 화면으로 전환합니다.";
  try {
    const result = await api(`/api/predictions/${state.job.job_id}`, requestBody());
    drawPredictionChart(result.history_kwh, result.predictions_kwh, result.timestamps);
    $("total-forecast").innerHTML = `${fmt(result.total_kwh)} <small>kWh</small>`;
    $("average-forecast").textContent = `${fmt(result.average_kwh, 2)} kWh`;
    $("peak-forecast").textContent = `${fmt(result.peak_kwh)} kWh`;
    $("peak-time").textContent = displayTime(result.peak_timestamp);
    $("forecast-reference").textContent = `예측 시작 기준: ${displayTime(result.forecast_origin)}`;
    $("forecast-timezone").textContent = `시간대: ${$("timezone").value.trim()}`;
    $("sample-tag").textContent = "실제 예측 결과";
    $("sample-note").textContent = `학습 기록 ${result.run_id} · ${result.model_kind} · 저장된 모델로 생성한 실제 예측`;
    renderForecastTable(result.timestamps, result.predictions_kwh);
    drawDailyUsage(result.recent_daily_usage || []);
    renderPeriodComposition(result.period_composition || []);
    renderMonthlyUsage(result.recent_monthly_usage || []);
    $("actual-summary-label").textContent = `최근 24시간 ${fmt(result.actual_summary.total_24h_kwh, 1)} kWh`;
    $("workspace-prediction-summary").textContent = `예측 완료 · 총 ${fmt(result.total_kwh)} kWh · 최대 ${fmt(result.peak_kwh)} kWh · 피크 ${displayTime(result.peak_timestamp)}`;
    state.predictionComplete = true;
    updateNextAction();
  } catch (caught) {
    const message = `예측에 실패했습니다: ${caught.message} 입력 CSV와 시간대를 확인한 뒤 다시 시도하세요.`;
    sourceError.hidden = false;
    sourceError.textContent = message;
  } finally {
    dashboardButton.textContent = "24시간 예측 실행";
    dashboardGate.removeAttribute("aria-busy");
    updateNextAction();
  }
}

$("run-prediction").onclick = runPrediction;

function renderTextList(target, values) {
  const fragment = document.createDocumentFragment();
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    fragment.append(item);
  });
  target.replaceChildren(fragment);
}

$("ai-analyze").onclick = async () => {
  const button = $("ai-analyze");
  if (!state.predictionComplete || !state.job?.job_id) return;
  button.disabled = true;
  button.textContent = "AI 분석 중…";
  $("ai-analysis-status").textContent = "예측 수치의 패턴을 해석하고 있습니다. 모델 예측에는 영향을 주지 않습니다.";
  try {
    const result = await api(`/api/ai-analysis/${state.job.job_id}`, requestBody());
    $("ai-summary").textContent = result.summary;
    $("ai-peak").textContent = result.peak_interpretation;
    renderTextList($("ai-patterns"), result.patterns);
    renderTextList($("ai-cautions"), result.cautions);
    $("ai-analysis-result").hidden = false;
    $("ai-analysis-status").textContent = `AI 해석 완료 · ${result.model}`;
    state.aiAnalysisComplete = true;
  } catch (caught) {
    $("ai-analysis-result").hidden = true;
    $("ai-analysis-status").textContent = `AI 해석을 완료하지 못했습니다. ${caught.message} 24시간 예측 결과는 그대로 유지됩니다.`;
  } finally {
    button.textContent = "AI 분석하기";
    updateNextAction();
  }
};

async function loadCapabilities() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error("health check failed");
    const health = await response.json();
    state.aiAnalysisAvailable = Boolean(health.ai_analysis?.enabled);
    state.aiAnalysisModel = health.ai_analysis?.model || "";
  } catch {
    state.aiAnalysisAvailable = false;
    state.aiAnalysisModel = "";
  }
  updateNextAction();
}

function drawPredictionChart(history, forecast, timestamps = []) {
  const svg = $("forecast-chart");
  const tooltip = $("forecast-tooltip");
  const all = [...history, ...forecast];
  const width = 680;
  const height = 210;
  const padding = 28;
  const max = Math.max(...all);
  const min = Math.min(...all);
  const range = Math.max(max - min, 0.001);
  const pointCoordinates = (value, index) => [
    padding + (index * (width - 2 * padding)) / (all.length - 1),
    height - padding - ((value - min) * (height - 2 * padding)) / range,
  ];
  const point = (value, index) => pointCoordinates(value, index).join(",");
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (tick) =>
        `<line x1="${padding}" y1="${padding + tick * (height - 2 * padding)}" x2="${width - padding}" y2="${padding + tick * (height - 2 * padding)}" stroke="#e4e7df"/>`,
    )
    .join("");
  const historyPoints = history.map(point).join(" ");
  const forecastPoints = forecast.map((value, index) => point(value, index + history.length)).join(" ");
  const forecastDots = forecast.map((value, index) => {
    const [cx, cy] = pointCoordinates(value, index + history.length);
    return `<circle cx="${cx}" cy="${cy}" r="4" fill="#204ed5" tabindex="0"><title>+${index + 1}시간: ${fmt(value, 2)} kWh</title></circle>`;
  }).join("");
  svg.innerHTML = `<g transform="translate(10,20)">${grid}<polyline points="${historyPoints}" fill="none" stroke="#a3aea7" stroke-width="3"/><polyline points="${forecastPoints}" fill="none" stroke="#2855da" stroke-width="4" stroke-dasharray="8 7" stroke-linecap="round" stroke-linejoin="round"/>${forecastDots}<line id="forecast-hover-guide" x1="0" x2="0" y1="${padding}" y2="${height - padding}" stroke="#2855da" stroke-width="1.5" stroke-dasharray="5 5" visibility="hidden"/><circle id="forecast-hover-point" cx="0" cy="0" r="6" fill="#fff" stroke="#2855da" stroke-width="3" visibility="hidden"/><text x="${padding}" y="240" fill="#69756e" font-size="11">24시간 전</text><text x="310" y="240" fill="#69756e" font-size="11">현재</text><text x="610" y="240" fill="#69756e" font-size="11">+24h</text></g>`;
  svg.setAttribute("aria-label", `과거 24시간 실측과 향후 24시간 예측 그래프. 예측 최저 ${fmt(min, 1)} kWh, 최고 ${fmt(max, 1)} kWh`);
  const showTooltip = (event) => {
    if (!tooltip) return;
    const rect = svg.getBoundingClientRect();
    const viewX = ((event.clientX - rect.left) / rect.width) * 720;
    const chartX = Math.max(padding, Math.min(width - padding, viewX - 10));
    const index = Math.max(0, Math.min(all.length - 1, Math.round(((chartX - padding) / (width - 2 * padding)) * (all.length - 1))));
    const isForecast = index >= history.length;
    const relativeIndex = isForecast ? index - history.length + 1 : history.length - index;
    let timeLabel = isForecast ? `예측 +${relativeIndex}시간` : `과거 ${relativeIndex}시간 전`;
    if (timestamps.length && timestamps[0]) {
      const timestamp = isForecast
        ? timestamps[index - history.length]
        : new Date(new Date(timestamps[0]).getTime() - relativeIndex * 3_600_000).toISOString();
      timeLabel = displayTime(timestamp);
    }
    tooltip.textContent = `${timeLabel} · ${fmt(all[index], 2)} kWh`;
    tooltip.hidden = false;
    const [pointX, pointY] = pointCoordinates(all[index], index);
    const guide = $("forecast-hover-guide");
    const activePoint = $("forecast-hover-point");
    guide.setAttribute("x1", pointX);
    guide.setAttribute("x2", pointX);
    guide.setAttribute("visibility", "visible");
    activePoint.setAttribute("cx", pointX);
    activePoint.setAttribute("cy", pointY);
    activePoint.setAttribute("visibility", "visible");
    const wrap = tooltip.parentElement;
    const localX = event.clientX - wrap.getBoundingClientRect().left;
    tooltip.style.left = `${Math.max(8, Math.min(wrap.clientWidth - tooltip.offsetWidth - 8, localX + 10))}px`;
    tooltip.style.top = "8px";
  };
  svg.onpointermove = showTooltip;
  svg.onclick = showTooltip;
  svg.onpointerleave = () => {
    if (tooltip) tooltip.hidden = true;
    $("forecast-hover-guide")?.setAttribute("visibility", "hidden");
    $("forecast-hover-point")?.setAttribute("visibility", "hidden");
  };
}

function drawEmptyChart() {
  const svg = $("forecast-chart");
  const grid = [54, 94, 134, 174, 214]
    .map((y) => `<line x1="42" y1="${y}" x2="678" y2="${y}" stroke="#e4e7df"/>`)
    .join("");
  svg.innerHTML = `${grid}<text class="empty-chart-label" x="360" y="126">아직 실행된 예측이 없습니다.</text><text class="empty-chart-help" x="360" y="150">저장된 모델이 없다면 CSV를 업로드하고 모델을 먼저 준비해 주세요.</text>`;
}

function initIntegratedNavigation() {
  const buttons = [...document.querySelectorAll("[data-integrated-target]")];
  if (!buttons.length) return;
  const targets = buttons.map((button) => $(button.dataset.integratedTarget)).filter(Boolean);
  const activate = (id) => {
    buttons.forEach((button) => {
      const active = button.dataset.integratedTarget === id;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
  };
  buttons.forEach((button) => button.addEventListener("click", () => {
    const target = $(button.dataset.integratedTarget);
    if (!target) return;
    scrollToSection(button.dataset.integratedTarget);
    activate(button.dataset.integratedTarget);
  }));
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
      if (visible) activate(visible.target.id);
    }, { rootMargin: "-145px 0px -55% 0px", threshold: [0.05, 0.25, 0.5] });
    targets.forEach((target) => observer.observe(target));
  }
}

function initHeroWave() {
  const wave = $("landing-wave");
  if (!wave) return;

  let markup = "";
  for (let column = 0; column < 44; column += 1) {
    for (let row = 0; row < 24; row += 1) {
      const x = column * 11.5;
      const y = row * 13 + 5 + Math.sin(column * 0.2 + row * 0.13) * 12 + Math.cos(column * 0.15) * 12;
      const radius = 0.5 + 1.65 * (0.5 + 0.5 * Math.sin(column * 0.28 + row * 0.36)) + Math.exp(-Math.pow(y - 150, 2) / 6500);
      const opacity = 0.27 + 0.62 * column / 44;
      markup += `<circle cx="${x}" cy="${y.toFixed(2)}" r="${radius.toFixed(2)}" fill="#5279ed" opacity="${opacity.toFixed(2)}"/>`;
    }
  }
  wave.innerHTML = markup;
}

function initBrandCurve() {
  const hero = $("landing-home");
  const energy = $("brand-energy-toggle");
  if (!hero || !energy) return;

  let pinned = false;
  let hovered = false;
  let focused = false;
  const render = () => {
    hero.classList.toggle("brand-curve-on", pinned || hovered || focused);
    energy.setAttribute("aria-pressed", String(pinned));
  };

  energy.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "touch") return;
    hovered = true;
    render();
  });
  energy.addEventListener("pointerleave", () => {
    hovered = false;
    render();
  });
  energy.addEventListener("focus", () => {
    focused = energy.matches(":focus-visible");
    render();
  });
  energy.addEventListener("blur", () => {
    focused = false;
    render();
  });
  energy.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    pinned = !pinned;
    focused = false;
    render();
  });
  energy.addEventListener("click", () => {
    pinned = !pinned;
    focused = false;
    render();
  });
}

drawEmptyChart();
initHeroWave();
initBrandCurve();
initIntegratedNavigation();
renderWorkspaceSteps();
if (location.hash) {
  requestAnimationFrame(() => scrollToSection(location.hash.slice(1), { smooth: false, updateHistory: false }));
}
updateNextAction();
recoverJob();
loadCapabilities();
