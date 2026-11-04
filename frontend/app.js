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
  stepStatuses: { 1: "current", 2: "waiting", 3: "waiting", 4: "waiting", 5: "waiting", 6: "waiting" },
  aiAnalysisAvailable: false,
  aiAnalysisModel: "",
  aiAnalysisComplete: false,
  jobRecovered: false,
  predictionResult: null,
  selectedForecastIndex: 0,
  analysisReport: null,
  reportSelectedIndex: 0,
  reportRequestInProgress: false,
  reportError: "",
  simulatorSnapshot: null,
};

const $ = (id) => document.getElementById(id);
const fileInput = $("csv-file");
const drop = $("drop-zone");
const error = $("form-error");
const jobSessionKey = "energy-planner.active-job.v1";

function fmt(number, digits = 1) {
  return Number(number).toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function localDateParts(value, timeZone) {
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));
  return Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
}

function forecastPeriodText(timestamps, timeZone) {
  if (!timestamps?.length) return "";
  const start = localDateParts(timestamps[0], timeZone);
  const end = localDateParts(timestamps.at(-1), timeZone);
  const startDate = `${start.year}.${start.month}.${start.day} (${start.weekday})`;
  const startTime = `${start.hour}:${start.minute}`;
  const endTime = `${end.hour}:${end.minute}`;
  const sameDate = start.year === end.year && start.month === end.month && start.day === end.day;
  const endLabel = sameDate ? endTime : `${end.year}.${end.month}.${end.day} (${end.weekday}) ${endTime}`;
  return `예측 대상 ${startDate} ${startTime}–${endLabel}`;
}

function formatLocalDateTime(value, timeZone) {
  const part = localDateParts(value, timeZone);
  return `${part.year}.${part.month}.${part.day} (${part.weekday}) ${part.hour}:${part.minute}`;
}

function formatMonthDay(value, timeZone) {
  return new Intl.DateTimeFormat("ko-KR", { timeZone, month: "long", day: "numeric" }).format(new Date(value));
}

function formatKoreanHour(value, timeZone) {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(value)).replace(":00", "시");
}

function formatChartTime(value, timeZone, includeDate = false) {
  const part = localDateParts(value, timeZone);
  return includeDate ? `${part.month}.${part.day} ${part.hour}시` : `${part.hour}시`;
}

function modelDisplayName(name) {
  return {
    xgboost: "XGBoost",
    last_24h: "직전 24시간 반복",
    last_168h: "지난주 같은 시간 반복",
  }[name] || name || "확인 불가";
}

function friendlyProgressMessage(message = "") {
  return message
    .replace("후보 모델 평가와 저장을 완료했습니다. 자동 승격은 하지 않았습니다.", "학습과 모델 선택을 완료했습니다.")
    .replaceAll("후보 모델", "비교 모델");
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
    ready: "준비 완료",
    complete: "완료",
    error: "오류",
    warning: "WARNING",
    fail: "FAIL",
  }[status];
}

function renderWorkspaceSteps() {
  document.querySelectorAll("[data-workflow-step]").forEach((step) => {
    const number = Number(step.dataset.workflowStep);
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
  state.analysisReport = null;
  state.reportSelectedIndex = 0;
  state.reportRequestInProgress = false;
  state.reportError = "";
  $("ai-report").hidden = true;
  $("report-preview").hidden = true;
  $("report-generation-progress").hidden = true;
  $("report-recommendations").replaceChildren();
  $("report-limitations").replaceChildren();
  $("download-report-html").disabled = true;
  $("print-report").disabled = true;
  $("regenerate-report").disabled = true;
  $("report-hour-slider").value = "0";
  $("report-selected-value").textContent = "예측 결과를 선택해 확인하세요.";
  $("report-target-period").textContent = "24시간 예측을 먼저 실행해 주세요.";
  $("ai-analysis-status").textContent = "24시간 예측 결과가 준비되면 생성할 수 있습니다.";
}

function resetSimulator() {
  state.simulatorSnapshot = null;
  $("simulator-gate").hidden = false;
  $("simulator-workspace").hidden = true;
  $("simulator-error").hidden = true;
  $("simulator-before").textContent = "단가 입력 필요";
  $("simulator-after").textContent = "단가 입력 필요";
  $("simulator-saving").textContent = "—";
  $("simulator-peak-before").textContent = "—";
  $("simulator-peak-after").textContent = "—";
  $("simulator-load-effect").textContent = "이동할 사용량과 단가를 입력하면 시간대별 부하 변화를 계산합니다.";
  $("simulator-chart").replaceChildren();
}

function resetDashboardPrediction() {
  state.predictionResult = null;
  state.selectedForecastIndex = 0;
  $("dashboard-gate").hidden = false;
  $("dashboard-results").hidden = true;
  $("total-forecast").textContent = "—";
  $("forecast-change").textContent = "직전 24시간과 비교 전";
  $("peak-forecast").textContent = "사용량 계산 전";
  $("peak-time").textContent = "예측 전";
  $("test-wape").textContent = "—";
  $("test-wape-help").textContent = "과거 Test 구간의 평가 결과를 불러오고 있습니다.";
  $("forecast-period").textContent = "";
  $("forecast-period").hidden = true;
  $("forecast-narrative").textContent = "예측 결과를 요약하고 있습니다.";
  $("data-last-observation").textContent = "데이터 마지막 시점: 미설정";
  $("forecast-timezone").textContent = "시간대: 미설정";
  $("forecast-table-body").replaceChildren();
  $("compare-previous").checked = false;
  $("forecast-hour-slider").value = "0";
  $("forecast-selected-value").textContent = "예측 결과를 선택해 확인하세요.";
  $("history-legend").hidden = true;
  $("dashboard-validation-body").replaceChildren();
  $("dashboard-selected-model").textContent = "—";
  $("dashboard-test-wape").textContent = "—";
  $("dashboard-run-id").textContent = "—";
  $("daily-usage-chart").innerHTML = "";
  $("period-composition-list").replaceChildren();
  $("period-donut").style.background = "conic-gradient(var(--line) 0 100%)";
  $("monthly-usage-list").replaceChildren();
  $("actual-summary-label").textContent = "예측 실행 후 표시";
  drawEmptyChart();
  resetAIAnalysis();
  resetSimulator();
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
  let homeText = "CSV로 예측 시작하기";

  if (state.predictionComplete) {
    homeTarget = "dashboard";
    homeText = "예측 결과 보기";
  } else if (completed) {
    homeTarget = canPredict ? "dashboard" : "upload";
    homeText = canPredict ? "예측 실행 준비하기" : "예측 입력 준비하기";
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
  let gateActionText = "CSV로 예측 시작하기";
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
  $("dashboard-new-csv").hidden = !state.predictionComplete;

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

  const reportReady = state.predictionComplete && state.aiAnalysisAvailable;
  $("ai-analyze").disabled = !reportReady || state.reportRequestInProgress;
  $("regenerate-report").disabled = !state.analysisReport || !reportReady || state.reportRequestInProgress;
  $("download-report-html").disabled = !state.analysisReport;
  $("print-report").disabled = !state.analysisReport;
  $("report-generation-progress").hidden = !state.reportRequestInProgress;
  $("report-target-period").textContent = state.predictionComplete
    ? forecastPeriodText(state.predictionResult?.timestamps, state.predictionResult?.building_timezone || "UTC")
    : "24시간 예측을 먼저 실행해 주세요.";
  const reportStatus = $("report-status");
  reportStatus.removeAttribute("data-status");
  if (state.reportRequestInProgress) {
    reportStatus.textContent = "진행 중";
    reportStatus.dataset.status = "RUNNING";
    $("ai-analysis-status").textContent = state.analysisReport
      ? "기존 보고서를 유지한 채 새 보고서를 생성하고 있습니다."
      : "정량 근거를 확인하고 AI 운영 해석을 생성하고 있습니다.";
  } else if (state.reportError) {
    reportStatus.textContent = "오류";
    reportStatus.dataset.status = "FAILED";
    $("ai-analysis-status").textContent = `${state.reportError} 예측 결과는 그대로 유지됩니다. 다시 시도할 수 있습니다.`;
  } else if (state.aiAnalysisComplete) {
    reportStatus.textContent = "완료";
    reportStatus.dataset.status = "COMPLETED";
    $("ai-analysis-status").textContent = `보고서 생성 완료${state.aiAnalysisModel ? ` · ${state.aiAnalysisModel}` : ""}`;
  } else if (!state.predictionComplete) {
    reportStatus.textContent = "대기";
    $("ai-analysis-status").textContent = "24시간 예측 결과가 준비되면 생성할 수 있습니다.";
  } else if (!state.aiAnalysisAvailable) {
    reportStatus.textContent = "설정 필요";
    $("ai-analysis-status").textContent = "서버의 OPENAI_API_KEY를 확인한 뒤 서버를 다시 시작해 주세요.";
  } else {
    reportStatus.textContent = "준비 완료";
    reportStatus.dataset.status = "READY";
    $("ai-analysis-status").textContent = "버튼을 누르면 현재 예측 결과로 보고서를 생성합니다. 페이지를 여는 것만으로 API를 호출하지 않습니다.";
  }

  const simulatorStatus = $("simulator-status");
  simulatorStatus.removeAttribute("data-status");
  simulatorStatus.textContent = state.predictionComplete ? (state.simulatorSnapshot ? "완료" : "준비 완료") : "대기";
  if (state.predictionComplete) simulatorStatus.dataset.status = state.simulatorSnapshot ? "COMPLETED" : "READY";
  state.stepStatuses[4] = state.predictionComplete ? "complete" : canPredict ? "ready" : running ? "in-progress" : failed ? "error" : "waiting";
  state.stepStatuses[5] = state.reportRequestInProgress ? "in-progress" : state.reportError ? "error" : state.aiAnalysisComplete ? "complete" : state.predictionComplete ? "ready" : "waiting";
  state.stepStatuses[6] = state.predictionComplete ? (state.simulatorSnapshot ? "complete" : "ready") : "waiting";
  renderWorkspaceSteps();
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
  $("selected-file-state").textContent = "선택한 파일로 진단을 완료했습니다";
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

function renderForecastValidation(job, runId = state.predictionResult?.run_id) {
  if (!job) return;
  const selectedTest = job.test_metrics?.[job.selected_model];
  const wape = Number.isFinite(selectedTest?.wape) ? selectedTest.wape * 100 : null;
  const wapeText = wape === null ? "확인 불가" : `${fmt(wape, 1)}%`;
  $("test-wape").textContent = wapeText;
  $("dashboard-test-wape").textContent = wapeText;
  $("dashboard-selected-model").textContent = modelDisplayName(job.selected_model);
  $("dashboard-run-id").textContent = runId || "예측 실행 후 표시";
  $("test-wape-help").textContent = wape === null
    ? "학습에 사용하지 않은 과거 Test 구간의 WAPE를 확인할 수 없습니다. 이번 예측의 오차 범위를 임의로 추정하지 않습니다."
    : `학습에 사용하지 않은 과거 Test 구간에서, 총 실제 사용량 대비 절대 오차 합계가 ${fmt(wape, 1)}%였습니다. 이번 예측값의 ±${fmt(wape, 1)}% 범위를 보장하는 수치는 아닙니다.`;

  const fragment = document.createDocumentFragment();
  ["xgboost", "last_24h", "last_168h"].forEach((name) => {
    const row = document.createElement("tr");
    if (job.selected_model === name) row.className = "selected";
    const model = document.createElement("td");
    const metric = document.createElement("td");
    const result = document.createElement("td");
    model.textContent = modelDisplayName(name);
    metric.textContent = metricText(job.validation_metrics?.[name]);
    result.textContent = job.selected_model === name ? "이번 예측에 사용" : "비교 기준";
    row.append(model, metric, result);
    fragment.append(row);
  });
  $("dashboard-validation-body").replaceChildren(fragment);
}

function renderPredictionOverview(result) {
  const timeZone = result.building_timezone || $("timezone").value.trim() || "UTC";
  const actualTotal = Number(result.actual_summary?.total_24h_kwh);
  const forecastTotal = Number(result.total_kwh);
  const changePercent = actualTotal > 0 ? ((forecastTotal - actualTotal) / actualTotal) * 100 : null;
  const period = forecastPeriodText(result.timestamps, timeZone);
  $("forecast-period").textContent = period;
  $("forecast-period").hidden = !period;
  $("total-forecast").innerHTML = `${fmt(forecastTotal)} <small>kWh</small>`;
  $("peak-time").textContent = formatKoreanHour(result.peak_timestamp, timeZone);
  $("peak-forecast").textContent = `${fmt(result.peak_kwh)} kWh 예상`;
  $("data-last-observation").textContent = `데이터 마지막 시점: ${formatLocalDateTime(result.history_timestamps?.at(-1) || result.forecast_origin, timeZone)}`;
  $("forecast-timezone").textContent = `시간대: ${timeZone}`;

  let comparisonSentence = "직전 24시간 실측 합계가 0kWh여서 증감률은 계산할 수 없습니다";
  if (changePercent !== null) {
    const decreased = changePercent < 0;
    const direction = decreased ? "감소" : changePercent > 0 ? "증가" : "변화 없음";
    const arrow = decreased ? "↓" : changePercent > 0 ? "↑" : "→";
    $("forecast-change").textContent = `${arrow} 직전 24시간보다 ${fmt(Math.abs(changePercent), 1)}% ${direction} 예상`;
    comparisonSentence = changePercent === 0
      ? "직전 24시간과 같은 수준이며"
      : `직전 24시간보다 약 ${fmt(Math.abs(changePercent), 1)}% ${decreased ? "적으며" : "많으며"}`;
  } else {
    $("forecast-change").textContent = "직전 24시간 실측이 0kWh여서 증감률 계산 불가";
  }
  $("forecast-narrative").textContent = `${formatMonthDay(result.timestamps[0], timeZone)} 예상 사용량은 ${fmt(forecastTotal)}kWh입니다. ${comparisonSentence}, 가장 많이 사용할 것으로 예상되는 시간은 ${formatKoreanHour(result.peak_timestamp, timeZone)}입니다.`;
  $("sample-note").textContent = "학습과 모델 선택을 완료했습니다. 저장된 결과로 이번 예측을 생성했습니다.";
  renderForecastValidation(state.job, result.run_id);
}

function renderJob(job) {
  const chip = $("job-status");
  const progressMessage = friendlyProgressMessage(job.progress_message);
  chip.textContent = `${jobStatusText(job.status)} · ${progressMessage}`;
  chip.dataset.status = job.status;
  const workspaceChip = $("workspace-job-status");
  workspaceChip.textContent = `${jobStatusText(job.status)} · ${progressMessage}`;
  workspaceChip.dataset.status = job.status;
  const completed = job.status === "COMPLETED";
  if (["QUEUED", "RUNNING"].includes(job.status)) {
    $("training-progress").hidden = false;
    setTrainingProgress(job.progress_percent, progressMessage);
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
  setTrainingProgress(job.progress_percent ?? 100, progressMessage);
  $("train").disabled = true;
  $("workspace-model-results").hidden = false;
  const names = { xgboost: "xgboost", last_24h: "last-24h", last_168h: "last-168h" };
  Object.entries(names).forEach(([key, id]) => {
    const metric = job.validation_metrics?.[key];
    $("workspace-metric-" + id).textContent = metricText(metric);
    $("workspace-model-" + id).classList.toggle("selected", job.selected_model === key);
    $("workspace-result-" + id).textContent = job.selected_model === key ? "이번 예측에 사용" : "비교 기준";
  });
  const selectedTest = job.test_metrics?.[job.selected_model];
  $("test-evaluation-note").textContent = selectedTest
    ? `Validation에서 ${modelDisplayName(job.selected_model)} 선택 · Test는 모델 선택에 사용하지 않고 최종 평가만 수행 · ${metricText(selectedTest)}`
    : "Test는 Validation에서 선택한 모델의 최종 성능 확인에만 사용합니다.";
  renderForecastValidation(job);
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

function displayTime(value, timeZone = state.predictionResult?.building_timezone || $("timezone").value.trim() || "UTC") {
  return formatLocalDateTime(value, timeZone);
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

function percentText(value, unavailable = "미확인") {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return unavailable;
  const number = Number(value);
  if (number === 0) return "변화 없음";
  return `${number > 0 ? "↑" : "↓"} ${fmt(Math.abs(number), 1)}%`;
}

function metricValue(metric, key, unit) {
  if (metric?.[key] === null || metric?.[key] === undefined) return "미확인";
  const value = Number(metric[key]);
  return Number.isFinite(value) ? `${fmt(key === "wape" ? value * 100 : value, 1)}${unit}` : "미확인";
}

function evidenceLabel(report, evidenceId) {
  return report.evidence?.find((item) => item.id === evidenceId)?.label || evidenceId;
}

function renderRecommendations(report) {
  const fragment = document.createDocumentFragment();
  (report.recommendations || []).slice(0, 3).forEach((recommendation) => {
    const item = document.createElement("li");
    const copy = document.createElement("div");
    copy.className = "recommendation-copy";
    const title = document.createElement("h6");
    const action = document.createElement("p");
    const reason = document.createElement("p");
    const caveat = document.createElement("p");
    const evidence = document.createElement("div");
    title.textContent = recommendation.title;
    action.className = "recommendation-action";
    action.textContent = recommendation.action;
    reason.textContent = `근거: ${recommendation.reason}`;
    caveat.textContent = `주의: ${recommendation.caveat}`;
    evidence.className = "recommendation-evidence";
    (recommendation.evidence_ids || []).forEach((id) => {
      const tag = document.createElement("span");
      tag.textContent = evidenceLabel(report, id);
      evidence.append(tag);
    });
    copy.append(title, action, reason, caveat, evidence);
    item.append(copy);
    fragment.append(item);
  });
  $("report-recommendations").replaceChildren(fragment);
}

function setupSimulatorOptions(result) {
  if (!result?.predictions_kwh?.length) {
    resetSimulator();
    return;
  }
  const timeZone = result.building_timezone || "UTC";
  const timestamps = result.timestamps || [];
  [$("simulator-from"), $("simulator-to")].forEach((select, selectIndex) => {
    const fragment = document.createDocumentFragment();
    timestamps.forEach((timestamp, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = formatLocalDateTime(timestamp, timeZone);
      fragment.append(option);
    });
    select.replaceChildren(fragment);
    select.value = String(selectIndex ? Math.min(1, timestamps.length - 1) : 0);
  });
  $("simulator-kwh").value = "0";
  $("simulator-from-rate").value = "";
  $("simulator-to-rate").value = "";
  $("simulator-gate").hidden = true;
  $("simulator-workspace").hidden = false;
  updateSimulator();
}

function drawSimulatorChart(forecast, adjusted, fromIndex, toIndex) {
  const svg = $("simulator-chart");
  const result = state.predictionResult;
  if (!result || forecast.length !== 24 || adjusted.length !== 24) {
    svg.replaceChildren();
    return;
  }
  const timestamps = result.timestamps;
  const timeZone = result.building_timezone || "UTC";
  const compact = window.matchMedia("(max-width: 700px)").matches;
  const width = compact ? 560 : 960;
  const height = compact ? 400 : 340;
  const left = compact ? 90 : 78;
  const right = 24;
  const top = 34;
  const bottom = compact ? 72 : 58;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const axisMax = Math.max(...forecast, ...adjusted, 1) * 1.12;
  const point = (value, index) => [left + index * plotWidth / 23, top + plotHeight - value / axisMax * plotHeight];
  const points = (series) => series.map((value, index) => point(value, index).join(",")).join(" ");
  const yGrid = Array.from({ length: 5 }, (_, index) => {
    const y = top + index * plotHeight / 4;
    const value = axisMax * (1 - index / 4);
    return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="#dedbd3"/><text x="${left - 10}" y="${y + 4}" text-anchor="end" fill="#657184" font-size="${compact ? 16 : 11}">${fmt(value, 0)}</text>`;
  }).join("");
  const xTicks = [0, 6, 12, 18, 23].map((index) => {
    const [x] = point(0, index);
    return `<text x="${x}" y="${height - 20}" text-anchor="middle" fill="#657184" font-size="${compact ? 16 : 11}">${formatChartTime(timestamps[index], timeZone, index === 0)}</text>`;
  }).join("");
  const [fromX, fromY] = point(adjusted[fromIndex], fromIndex);
  const [toX, toY] = point(adjusted[toIndex], toIndex);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = `<g aria-hidden="true">${yGrid}${xTicks}<text x="${compact ? 24 : 18}" y="${top + plotHeight / 2}" transform="rotate(-90 ${compact ? 24 : 18} ${top + plotHeight / 2})" text-anchor="middle" fill="#4f5c70" font-size="${compact ? 16 : 11}" font-weight="700">사용량 (kWh)</text><polyline points="${points(forecast)}" fill="none" stroke="#737e8d" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><polyline points="${points(adjusted)}" fill="none" stroke="#1f4fdb" stroke-width="4" stroke-dasharray="9 7" stroke-linecap="round" stroke-linejoin="round"/><circle cx="${fromX}" cy="${fromY}" r="7" fill="#fffdf8" stroke="#a93434" stroke-width="4"/><circle cx="${toX}" cy="${toY}" r="7" fill="#fffdf8" stroke="#087a55" stroke-width="4"/></g>`;
  svg.setAttribute("aria-label", `변경 전후 24시간 예상 사용량 비교. ${formatLocalDateTime(timestamps[fromIndex], timeZone)}에서 사용량이 감소하고 ${formatLocalDateTime(timestamps[toIndex], timeZone)}에서 증가합니다.`);
}

function updateSimulator() {
  const result = state.predictionResult;
  if (!result?.predictions_kwh?.length) return;
  const amount = Number($("simulator-kwh").value);
  const fromIndex = Number($("simulator-from").value);
  const toIndex = Number($("simulator-to").value);
  const fromRate = Number($("simulator-from-rate").value);
  const toRate = Number($("simulator-to-rate").value);
  const forecast = result.predictions_kwh.map(Number);
  const sourceLoad = forecast[fromIndex];
  $("simulator-kwh").max = Number.isFinite(sourceLoad) ? String(sourceLoad) : "0";
  $("simulator-kwh-help").textContent = Number.isFinite(sourceLoad)
    ? `이 시간의 예측 사용량 ${fmt(sourceLoad, 1)}kWh 이내`
    : "기존 시간의 예측 사용량 이내";
  const errorTarget = $("simulator-error");
  errorTarget.hidden = true;
  errorTarget.textContent = "";
  if (fromIndex === toIndex) {
    errorTarget.hidden = false;
    errorTarget.textContent = "기존 시간대와 변경 시간대를 다르게 선택해 주세요.";
  } else if (!Number.isFinite(amount) || amount < 0) {
    errorTarget.hidden = false;
    errorTarget.textContent = "이동할 사용량은 0 이상의 숫자로 입력해 주세요.";
  } else if (Number.isFinite(sourceLoad) && amount > sourceLoad) {
    errorTarget.hidden = false;
    errorTarget.textContent = `이동할 사용량은 기존 시간의 예상 사용량 ${fmt(sourceLoad, 1)}kWh를 넘을 수 없습니다.`;
  }
  const ratesReady = $("simulator-from-rate").value !== "" && $("simulator-to-rate").value !== ""
    && Number.isFinite(fromRate) && Number.isFinite(toRate) && fromRate >= 0 && toRate >= 0;
  const scenarioValid = errorTarget.hidden && Number.isFinite(amount);
  const adjusted = [...forecast];
  if (scenarioValid) {
    adjusted[fromIndex] -= amount;
    adjusted[toIndex] += amount;
  }
  drawSimulatorChart(forecast, adjusted, fromIndex, toIndex);
  const beforePeak = Math.max(...forecast);
  const afterPeak = Math.max(...adjusted);
  $("simulator-peak-before").textContent = `${fmt(beforePeak, 1)} kWh`;
  $("simulator-peak-after").textContent = `${fmt(afterPeak, 1)} kWh`;
  const valid = scenarioValid && ratesReady;
  if (!valid) {
    $("simulator-before").textContent = ratesReady ? "입력 확인 필요" : "단가 입력 필요";
    $("simulator-after").textContent = ratesReady ? "입력 확인 필요" : "단가 입력 필요";
    $("simulator-saving").textContent = "—";
    $("simulator-load-effect").textContent = scenarioValid
      ? `부하 변화는 그래프에 반영했습니다. 비용 비교를 위해 두 시간 단가를 입력해 주세요.`
      : "입력을 확인하면 시간대별 부하 변화를 계산합니다.";
    state.simulatorSnapshot = null;
    updateNextAction();
    return;
  }
  const beforeCost = amount * fromRate;
  const afterCost = amount * toRate;
  const saving = beforeCost - afterCost;
  $("simulator-before").textContent = `${fmt(beforeCost, 0)}원`;
  $("simulator-after").textContent = `${fmt(afterCost, 0)}원`;
  $("simulator-saving").textContent = `${saving >= 0 ? "↓" : "↑"} ${fmt(Math.abs(saving), 0)}원`;
  $("simulator-load-effect").textContent = `시간당 예상 피크는 ${fmt(beforePeak, 1)}kWh에서 ${fmt(afterPeak, 1)}kWh로 변합니다. 실제 최대수요전력 요금 계산은 아닙니다.`;
  state.simulatorSnapshot = { amount, fromIndex, toIndex, fromRate, toRate, beforeCost, afterCost, saving, beforePeak, afterPeak };
  updateNextAction();
}

function renderAnalysisReport(report) {
  const timeZone = report.metadata?.building_timezone || "UTC";
  const quantitative = report.quantitative || {};
  const quality = report.model_quality || {};
  $("ai-report").hidden = false;
  $("report-source-badge").textContent = report.ai?.status === "completed" ? "로컬 수치 + AI 운영 해석" : "로컬 정량 분석";
  $("report-summary").textContent = report.summary || "확인 가능한 정량 결과를 표시합니다.";
  $("report-generated-at").textContent = formatLocalDateTime(report.metadata.generated_at_utc, timeZone);
  $("report-data-period").textContent = report.metadata.data_start && report.metadata.data_end
    ? `${formatLocalDateTime(report.metadata.data_start, timeZone)}–${formatLocalDateTime(report.metadata.data_end, timeZone)} · ${fmt(report.metadata.data_rows, 0)}시간`
    : "미확인";
  $("report-forecast-period").textContent = forecastPeriodText(report.chart.timestamps, timeZone).replace(/^예측 대상\s*/, "");
  $("report-total").textContent = `${fmt(quantitative.total_kwh, 1)} kWh`;
  $("report-total-change").textContent = quantitative.previous_24h_change_percent !== null && quantitative.previous_24h_change_percent !== undefined && Number.isFinite(Number(quantitative.previous_24h_change_percent))
    ? `직전 24시간 대비 ${percentText(quantitative.previous_24h_change_percent)}`
    : "직전 24시간 비교 미확인";
  $("report-peak").textContent = formatKoreanHour(quantitative.peak_timestamp, timeZone);
  $("report-peak-value").textContent = `${fmt(quantitative.peak_kwh, 1)} kWh 예상`;
  $("report-comparison").textContent = percentText(quantitative.same_weekday_change_percent, "비교 불가");
  $("report-comparison-basis").textContent = report.chart.baseline_status === "available"
    ? report.chart.baseline_method
    : "동일 요일 실제 표본 부족";
  $("report-priority-action").textContent = report.recommendations?.[0]?.action || "예상 피크 시간의 운영 일정을 확인하세요.";

  renderRecommendations(report);
  renderTextList($("report-limitations"), report.limitations || []);
  $("report-validation-mae").textContent = metricValue(quality.validation, "mae", " kWh");
  $("report-validation-wape").textContent = metricValue(quality.validation, "wape", "%");
  $("report-test-wape").textContent = metricValue(quality.test, "wape", "%");
  $("report-baseline-performance").textContent = quality.mae_improvement_vs_best_baseline_percent !== null && quality.mae_improvement_vs_best_baseline_percent !== undefined && Number.isFinite(Number(quality.mae_improvement_vs_best_baseline_percent))
    ? `Validation MAE ${percentText(-quality.mae_improvement_vs_best_baseline_percent)} 개선`
    : "직접 비교 미확인";
  $("report-model").textContent = modelDisplayName(quality.selected_model);
  $("report-chart-description").textContent = report.chart.baseline_status === "available"
    ? `예측값과 ${report.chart.baseline_method}을 비교합니다.`
    : "동일 요일 실제 표본이 부족해 예측값만 표시합니다.";
  $("report-baseline-toggle").disabled = report.chart.baseline_status !== "available";
  $("report-baseline-toggle").checked = report.chart.baseline_status === "available";
  $("report-baseline-legend").hidden = report.chart.baseline_status !== "available";
  state.reportSelectedIndex = 0;
  drawReportChart(report);
  $("report-preview").hidden = false;
  $("download-report-html").disabled = false;
  $("print-report").disabled = false;
  $("regenerate-report").disabled = false;
}

function updateReportSelection(index, { showTooltip = false } = {}) {
  const report = state.analysisReport;
  if (!report) return;
  const forecast = report.chart.forecast_kwh.map(Number);
  const baseline = (report.chart.same_weekday_baseline_kwh || []).map(Number);
  const safeIndex = Math.max(0, Math.min(forecast.length - 1, Number(index) || 0));
  const timeZone = report.metadata.building_timezone || "UTC";
  const showBaseline = $("report-baseline-toggle").checked && baseline.length === 24;
  const difference = showBaseline ? forecast[safeIndex] - baseline[safeIndex] : null;
  state.reportSelectedIndex = safeIndex;
  $("report-hour-slider").value = String(safeIndex);
  $("report-hour-slider").setAttribute("aria-valuetext", `${formatLocalDateTime(report.chart.timestamps[safeIndex], timeZone)}, 예측 ${fmt(forecast[safeIndex], 1)} kWh`);
  $("report-selected-value").textContent = `${formatLocalDateTime(report.chart.timestamps[safeIndex], timeZone)} · 예측 ${fmt(forecast[safeIndex], 1)} kWh${showBaseline ? ` · 동일 요일 ${fmt(baseline[safeIndex], 1)} kWh · 차이 ${difference >= 0 ? "+" : ""}${fmt(difference, 1)} kWh` : ""}`;
  const point = document.querySelector(`[data-report-index="${safeIndex}"]`);
  const guide = $("report-hover-guide");
  const active = $("report-hover-point");
  if (point && guide && active) {
    const x = point.getAttribute("cx");
    const y = point.getAttribute("cy");
    guide.setAttribute("x1", x);
    guide.setAttribute("x2", x);
    active.setAttribute("cx", x);
    active.setAttribute("cy", y);
  }
  const tooltip = $("report-chart-tooltip");
  if (!showTooltip || !point) {
    tooltip.hidden = true;
    return;
  }
  tooltip.textContent = $("report-selected-value").textContent;
  tooltip.hidden = false;
  const chart = $("report-chart");
  const rect = chart.getBoundingClientRect();
  const localX = (Number(point.getAttribute("cx")) / (chart.viewBox.baseVal.width || 960)) * rect.width;
  tooltip.style.left = `${Math.max(8, Math.min(tooltip.parentElement.clientWidth - tooltip.offsetWidth - 8, localX + 12))}px`;
  tooltip.style.top = "10px";
}

function drawReportChart(report) {
  const svg = $("report-chart");
  const forecast = report.chart.forecast_kwh.map(Number);
  const baseline = (report.chart.same_weekday_baseline_kwh || []).map(Number);
  const showBaseline = $("report-baseline-toggle").checked && baseline.length === 24;
  const timestamps = report.chart.timestamps;
  const timeZone = report.metadata.building_timezone || "UTC";
  const compact = window.matchMedia("(max-width: 700px)").matches;
  const width = compact ? 560 : 960;
  const height = compact ? 400 : 340;
  const left = compact ? 90 : 78;
  const right = 24;
  const top = 34;
  const bottom = compact ? 72 : 58;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const values = showBaseline ? [...forecast, ...baseline] : forecast;
  const axisMax = Math.max(...values, 1) * 1.12;
  const point = (value, index) => [left + index * plotWidth / 23, top + plotHeight - value / axisMax * plotHeight];
  const points = (series) => series.map((value, index) => point(value, index).join(",")).join(" ");
  const yGrid = Array.from({ length: 5 }, (_, index) => {
    const y = top + index * plotHeight / 4;
    const value = axisMax * (1 - index / 4);
    return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="#dedbd3"/><text x="${left - 10}" y="${y + 4}" text-anchor="end" fill="#657184" font-size="${compact ? 16 : 11}">${fmt(value, 0)}</text>`;
  }).join("");
  const xTicks = [0, 6, 12, 18, 23].map((index) => {
    const [x] = point(0, index);
    return `<text x="${x}" y="${height - 20}" text-anchor="middle" fill="#657184" font-size="${compact ? 16 : 11}">${formatChartTime(timestamps[index], timeZone, index === 0)}</text>`;
  }).join("");
  const baselineLine = showBaseline ? `<polyline points="${points(baseline)}" fill="none" stroke="#737e8d" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` : "";
  const dots = forecast.map((value, index) => {
    const [cx, cy] = point(value, index);
    return `<circle data-report-index="${index}" cx="${cx}" cy="${cy}" r="3.5" fill="#1f4fdb"/>`;
  }).join("");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = `<g aria-hidden="true">${yGrid}${xTicks}<text x="${compact ? 24 : 18}" y="${top + plotHeight / 2}" transform="rotate(-90 ${compact ? 24 : 18} ${top + plotHeight / 2})" text-anchor="middle" fill="#4f5c70" font-size="${compact ? 16 : 11}" font-weight="700">사용량 (kWh)</text>${baselineLine}<polyline points="${points(forecast)}" fill="none" stroke="#1f4fdb" stroke-width="4" stroke-dasharray="9 7" stroke-linecap="round" stroke-linejoin="round"/>${dots}<line id="report-hover-guide" x1="${left}" x2="${left}" y1="${top}" y2="${top + plotHeight}" stroke="#1f4fdb" stroke-width="1.5" stroke-dasharray="4 5"/><circle id="report-hover-point" cx="${left}" cy="${top + plotHeight}" r="6" fill="#fffdf8" stroke="#1f4fdb" stroke-width="3"/></g>`;
  svg.setAttribute("aria-label", showBaseline ? "24시간 예측과 과거 동일 요일 시간별 평균 비교 그래프" : "24시간 예측 그래프. 동일 요일 비교 자료는 부족합니다.");
  $("report-baseline-legend").hidden = !showBaseline;
  const select = (event) => {
    const rect = svg.getBoundingClientRect();
    const viewX = (event.clientX - rect.left) / rect.width * width;
    const index = Math.round((Math.max(left, Math.min(width - right, viewX)) - left) / plotWidth * 23);
    updateReportSelection(index, { showTooltip: true });
  };
  svg.onpointermove = select;
  svg.onclick = select;
  svg.onpointerleave = () => { $("report-chart-tooltip").hidden = true; };
  updateReportSelection(state.reportSelectedIndex);
}

async function runPrediction() {
  const dashboardButton = $("run-prediction");
  const sourceError = $("dashboard-error");
  const dashboardGate = $("dashboard-gate");
  $("dashboard-error").hidden = true;
  $("dashboard-error").textContent = "";
  resetAIAnalysis();
  resetSimulator();
  dashboardButton.disabled = true;
  dashboardButton.textContent = "예측 중…";
  dashboardGate.setAttribute("aria-busy", "true");
  $("dashboard-gate-title").textContent = "24시간 예측을 생성하고 있습니다.";
  $("dashboard-gate-description").textContent = "저장된 모델과 최신 입력을 확인한 뒤 결과 화면으로 전환합니다.";
  try {
    const result = await api(`/api/predictions/${state.job.job_id}`, requestBody());
    state.predictionResult = result;
    state.selectedForecastIndex = 0;
    renderPredictionOverview(result);
    drawPredictionChart(result);
    renderForecastTable(result.timestamps, result.predictions_kwh);
    drawDailyUsage(result.recent_daily_usage || []);
    renderPeriodComposition(result.period_composition || []);
    renderMonthlyUsage(result.recent_monthly_usage || []);
    $("actual-summary-label").textContent = `최근 24시간 ${fmt(result.actual_summary.total_24h_kwh, 1)} kWh`;
    $("workspace-prediction-summary").textContent = `예측 완료 · 총 ${fmt(result.total_kwh)} kWh · 최대 ${fmt(result.peak_kwh)} kWh · 피크 ${formatLocalDateTime(result.peak_timestamp, result.building_timezone || $("timezone").value.trim())}`;
    state.predictionComplete = true;
    setupSimulatorOptions(result);
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

async function generateAIReport() {
  const button = $("ai-analyze");
  if (!state.predictionComplete || !state.job?.job_id) return;
  state.reportRequestInProgress = true;
  state.reportError = "";
  $("report").setAttribute("aria-busy", "true");
  button.textContent = "보고서 생성 중…";
  $("regenerate-report").textContent = "보고서 생성 중…";
  updateNextAction();
  try {
    const result = await api(`/api/ai-analysis/${state.job.job_id}`, requestBody());
    state.analysisReport = result;
    state.aiAnalysisComplete = true;
    renderAnalysisReport(result);
  } catch (caught) {
    state.reportError = `AI 보고서를 생성하지 못했습니다. ${caught.message}`;
  } finally {
    state.reportRequestInProgress = false;
    $("report").removeAttribute("aria-busy");
    button.textContent = "AI 전력 운영 보고서 생성";
    $("regenerate-report").textContent = "보고서 다시 생성";
    updateNextAction();
  }
}

$("ai-analyze").onclick = generateAIReport;
$("regenerate-report").onclick = generateAIReport;

function safeJsonForHtml(value) {
  return JSON.stringify(value)
    .replaceAll("<", "\\u003c")
    .replaceAll(">", "\\u003e")
    .replaceAll("&", "\\u0026")
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
}

function reportFileStem(report) {
  const part = localDateParts(report.metadata.forecast_start, report.metadata.building_timezone || "UTC");
  return `energy-planner-report-${part.year}${part.month}${part.day}`;
}

function buildStandaloneReportHtml(report) {
  const clone = $("ai-report").cloneNode(true);
  clone.removeAttribute("hidden");
  clone.querySelectorAll("input").forEach((input) => {
    const source = $(input.id);
    if (input.type === "checkbox") {
      if (source?.checked) input.setAttribute("checked", "");
      else input.removeAttribute("checked");
    } else {
      input.setAttribute("value", source?.value ?? input.value);
    }
  });
  clone.querySelectorAll("select").forEach((select) => {
    const selectedValue = $(select.id)?.value ?? select.value;
    [...select.options].forEach((option) => {
      if (option.value === selectedValue) option.setAttribute("selected", "");
      else option.removeAttribute("selected");
    });
  });
  const snapshot = { report };
  const css = `
    :root{--ink:#10213d;--sub:#596579;--line:#d8d5cd;--bg:#f3f0e8;--paper:#fffdf8;--blue:#1f4fdb;--success:#087a55;--danger:#a93434}
    *{box-sizing:border-box}html{color-scheme:light}body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,"Malgun Gothic",sans-serif;line-height:1.55}main{width:min(1120px,calc(100% - 32px));margin:28px auto;background:var(--paper);border:1px solid var(--line);padding:32px}button,input,select{font:inherit}button,input,select{min-height:44px}.ai-report{display:block}.report-cover{display:grid;grid-template-columns:1.35fr .65fr;gap:32px;padding-bottom:26px;border-bottom:1px solid var(--line)}.report-badge{display:inline-block;border:1px solid #b9c9f5;background:#e9efff;color:var(--blue);padding:5px 8px;font-size:11px;font-weight:700}.report-cover h4{font-size:34px;margin:14px 0 8px}.report-cover p{margin:0}.report-meta{margin:0;border-top:1px solid var(--line)}.report-meta>div,.quality-grid dl>div{display:grid;grid-template-columns:100px 1fr;gap:12px;border-bottom:1px solid var(--line);padding:9px 0}.report-meta dt,.quality-grid dt{color:var(--sub);font-size:12px}.report-meta dd,.quality-grid dd{margin:0;font-size:12px;font-weight:700}.report-section{padding:28px 0;border-bottom:1px solid var(--line)}.report-section h5{margin:0 0 14px;font-size:20px}.report-section-heading{display:flex;justify-content:space-between;gap:16px}.report-section-heading p{color:var(--sub);font-size:12px}.report-metrics,.simulator-results{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line)}.report-metrics>div,.simulator-results>div{padding:16px;border-right:1px solid var(--line)}.report-metrics span,.report-metrics small,.simulator-results span{display:block;color:var(--sub);font-size:11px}.report-metrics strong,.simulator-results strong{display:block;margin:6px 0;font-size:22px}.report-priority{padding:14px;background:#edf2ff}.chart-wrap{position:relative}.report-chart{display:block;width:100%;height:auto}.tooltip{position:absolute;top:8px;z-index:2;max-width:340px;background:var(--ink);color:#fff;padding:8px;font-size:11px}.chart-legend{display:flex;gap:18px;color:var(--sub);font-size:12px}.chart-legend i{display:inline-block;width:20px;height:3px;margin-right:6px}.chart-legend .forecast{background:repeating-linear-gradient(90deg,var(--blue) 0 7px,transparent 7px 11px)}.chart-legend .baseline{background:#737e8d}.forecast-scrubber{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;margin-top:14px}.forecast-scrubber input{width:100%}.forecast-scrubber output{grid-column:2;color:var(--sub);font-size:12px}.recommendation-list{list-style:none;padding:0;border-top:1px solid var(--line)}.recommendation-list li{padding:16px 0;border-bottom:1px solid var(--line)}.recommendation-copy h6{font-size:15px;margin:0 0 6px}.recommendation-copy p{margin:4px 0;color:var(--sub);font-size:12px}.recommendation-action{color:var(--ink)!important;font-weight:700}.recommendation-evidence span{display:inline-block;border:1px solid #b9c9f5;padding:3px 6px;margin:4px 4px 0 0;font-size:10px}.simulator-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.simulator-grid label{font-size:11px;color:var(--sub)}.simulator-grid input,.simulator-grid select{width:100%;margin-top:5px;border:1px solid var(--line);background:#fff;padding:8px}.simulator-results{margin-top:16px}.simulator-results p{grid-column:1/-1;margin:0;border-top:1px solid var(--line);padding:12px;font-size:12px}.simulator-saving strong{color:var(--success)}.inline-error{border-left:3px solid var(--danger);background:#fde8e5;color:var(--danger);padding:10px;margin-bottom:10px}.quality-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}.quality-grid dl{margin:0}.quality-grid ul{color:var(--sub);font-size:12px}.muted{color:var(--sub);font-size:12px}.status{border:1px solid var(--line);padding:6px 9px;font-size:11px}.report-privacy{display:none}.report-footer{margin-top:22px;color:var(--sub);font-size:11px;text-align:center}.series-toggle{display:flex;align-items:center;gap:7px}.series-toggle input{width:18px}.ai-footer-actions{display:none}
    @media(max-width:720px){main{width:100%;margin:0;border:0;padding:18px}.report-cover,.quality-grid{grid-template-columns:1fr}.report-metrics,.simulator-results,.simulator-grid{grid-template-columns:1fr}.report-metrics>div,.simulator-results>div{border-right:0;border-bottom:1px solid var(--line)}.report-section-heading{display:block}.forecast-scrubber{grid-template-columns:1fr}.forecast-scrubber output{grid-column:1}}
    @media print{@page{size:A4;margin:13mm}body{background:#fff}main{width:100%;margin:0;border:0;padding:0}.report-section{break-inside:avoid;padding:18px 0}.simulator-grid,.series-toggle,.forecast-scrubber{display:none}.report-chart{max-height:76mm}.recommendation-list li{break-inside:avoid}}
  `;
  const script = `
    const payload=JSON.parse(document.getElementById('report-data').textContent);const report=payload.report;const $=id=>document.getElementById(id);const nf=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:1});
    const timeZone=report.metadata.building_timezone||'UTC';const formatTime=v=>new Intl.DateTimeFormat('ko-KR',{timeZone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(v));
    function draw(){const svg=$('report-chart'),f=report.chart.forecast_kwh.map(Number),b=(report.chart.same_weekday_baseline_kwh||[]).map(Number),show=$('report-baseline-toggle').checked&&b.length===24,w=960,h=340,l=78,r=24,t=34,bt=58,pw=w-l-r,ph=h-t-bt,max=Math.max(...f,...(show?b:[]),1)*1.12,p=(v,i)=>[l+i*pw/23,t+ph-v/max*ph],pts=s=>s.map((v,i)=>p(v,i).join(',')).join(' ');let grid='';for(let i=0;i<5;i++){const y=t+i*ph/4;grid+='<line x1="'+l+'" y1="'+y+'" x2="'+(w-r)+'" y2="'+y+'" stroke="#dedbd3"/><text x="'+(l-10)+'" y="'+(y+4)+'" text-anchor="end" fill="#657184" font-size="11">'+nf.format(max*(1-i/4))+'</text>'}const base=show?'<polyline points="'+pts(b)+'" fill="none" stroke="#737e8d" stroke-width="3"/>':'';const dots=f.map((v,i)=>{const q=p(v,i);return '<circle data-i="'+i+'" cx="'+q[0]+'" cy="'+q[1]+'" r="4" fill="#1f4fdb"/>'}).join('');svg.innerHTML='<g aria-hidden="true">'+grid+base+'<polyline points="'+pts(f)+'" fill="none" stroke="#1f4fdb" stroke-width="4" stroke-dasharray="9 7"/>'+dots+'<line id="guide" x1="'+l+'" x2="'+l+'" y1="'+t+'" y2="'+(t+ph)+'" stroke="#1f4fdb" stroke-dasharray="4 5"/></g>';$('report-baseline-legend').hidden=!show;const pick=e=>{const rect=svg.getBoundingClientRect(),x=(e.clientX-rect.left)/rect.width*w,i=Math.round((Math.max(l,Math.min(w-r,x))-l)/pw*23);select(i,true)};svg.onpointermove=pick;svg.onclick=pick;svg.onpointerleave=()=>{$('report-chart-tooltip').hidden=true};select(Number($('report-hour-slider').value)||0,false)}
    function select(i,tip){const f=report.chart.forecast_kwh.map(Number),b=(report.chart.same_weekday_baseline_kwh||[]).map(Number),show=$('report-baseline-toggle').checked&&b.length===24;i=Math.max(0,Math.min(23,i));$('report-hour-slider').value=String(i);let text=formatTime(report.chart.timestamps[i])+' · 예측 '+nf.format(f[i])+' kWh';if(show)text+=' · 동일 요일 '+nf.format(b[i])+' kWh · 차이 '+nf.format(f[i]-b[i])+' kWh';$('report-selected-value').textContent=text;const point=document.querySelector('[data-i="'+i+'"]'),guide=$('guide');if(point&&guide){guide.setAttribute('x1',point.getAttribute('cx'));guide.setAttribute('x2',point.getAttribute('cx'))}const tt=$('report-chart-tooltip');tt.textContent=text;tt.hidden=!tip}
    $('report-baseline-toggle').addEventListener('change',draw);$('report-hour-slider').addEventListener('input',e=>select(Number(e.target.value),false));draw();
  `;
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f3f0e8"><title>Energy Planner 전력 운영 분석 보고서</title><style>${css}</style></head><body><main><h1 style="font-size:16px;margin:0 0 22px">Energy Planner · 전력 운영 분석 보고서</h1>${clone.outerHTML}<p class="report-footer">이 파일에는 원본 CSV와 OpenAI API 키가 포함되지 않습니다.</p></main><script id="report-data" type="application/json">${safeJsonForHtml(snapshot)}</script><script>${script}</script></body></html>`;
}

function downloadStandaloneReport() {
  if (!state.analysisReport) return;
  try {
    const html = buildStandaloneReportHtml(state.analysisReport);
    const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${reportFileStem(state.analysisReport)}.html`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (caught) {
    $("ai-analysis-status").textContent = `HTML 보고서를 만들지 못했습니다. ${caught.message}`;
  }
}

function printAnalysisReport() {
  if (!state.analysisReport) return;
  document.body.classList.add("print-ai-report");
  window.print();
}

$("report-baseline-toggle").addEventListener("change", () => {
  if (state.analysisReport) drawReportChart(state.analysisReport);
});
$("report-hour-slider").addEventListener("input", (event) => updateReportSelection(Number(event.currentTarget.value)));
["simulator-kwh", "simulator-from", "simulator-to", "simulator-from-rate", "simulator-to-rate"].forEach((id) => {
  $(id).addEventListener("input", updateSimulator);
  $(id).addEventListener("change", updateSimulator);
});
$("download-report-html").addEventListener("click", downloadStandaloneReport);
$("print-report").addEventListener("click", printAnalysisReport);
window.addEventListener("afterprint", () => document.body.classList.remove("print-ai-report"));

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

function updateForecastSelection(index, { showTooltip = false } = {}) {
  const result = state.predictionResult;
  if (!result?.predictions_kwh?.length) return;
  const safeIndex = Math.max(0, Math.min(result.predictions_kwh.length - 1, Number(index) || 0));
  state.selectedForecastIndex = safeIndex;
  const timeZone = result.building_timezone || $("timezone").value.trim() || "UTC";
  const forecastValue = result.predictions_kwh[safeIndex];
  const compare = $("compare-previous").checked;
  const previousValue = result.history_kwh?.[safeIndex];
  const previousTime = result.history_timestamps?.[safeIndex];
  const forecastTime = result.timestamps[safeIndex];
  const slider = $("forecast-hour-slider");
  slider.value = String(safeIndex);
  slider.setAttribute("aria-valuetext", `${formatLocalDateTime(forecastTime, timeZone)}, 예상 ${fmt(forecastValue, 1)} kWh`);
  $("forecast-selected-value").textContent = `${formatLocalDateTime(forecastTime, timeZone)} · 예상 ${fmt(forecastValue, 1)} kWh${compare && Number.isFinite(previousValue) ? ` · 직전 24시간 ${fmt(previousValue, 1)} kWh` : ""}`;

  const point = document.querySelector(`[data-forecast-index="${safeIndex}"]`);
  const guide = $("forecast-hover-guide");
  const activePoint = $("forecast-hover-point");
  if (point && guide && activePoint) {
    const x = point.getAttribute("cx");
    const y = point.getAttribute("cy");
    guide.setAttribute("x1", x);
    guide.setAttribute("x2", x);
    activePoint.setAttribute("cx", x);
    activePoint.setAttribute("cy", y);
  }

  const tooltip = $("forecast-tooltip");
  if (!showTooltip || !tooltip || !point) {
    if (tooltip) tooltip.hidden = true;
    return;
  }
  const lines = [
    formatLocalDateTime(forecastTime, timeZone),
    `예측 사용량 ${fmt(forecastValue, 1)} kWh`,
  ];
  if (compare && Number.isFinite(previousValue) && previousTime) {
    lines.push(`직전 24시간 (${formatLocalDateTime(previousTime, timeZone)}) ${fmt(previousValue, 1)} kWh`);
  }
  tooltip.textContent = lines.join("\n");
  tooltip.hidden = false;
  const wrap = tooltip.parentElement;
  const chart = $("forecast-chart");
  const chartRect = chart.getBoundingClientRect();
  const viewWidth = chart.viewBox.baseVal.width || 960;
  const localX = (Number(point.getAttribute("cx")) / viewWidth) * chartRect.width;
  tooltip.style.left = `${Math.max(8, Math.min(wrap.clientWidth - tooltip.offsetWidth - 8, localX + 12))}px`;
  tooltip.style.top = "10px";
}

function drawPredictionChart(result) {
  const svg = $("forecast-chart");
  const forecast = result.predictions_kwh.map(Number);
  const history = (result.history_kwh || []).map(Number);
  const timestamps = result.timestamps || [];
  const compare = $("compare-previous").checked;
  const timeZone = result.building_timezone || $("timezone").value.trim() || "UTC";
  const compact = window.matchMedia("(max-width: 700px)").matches;
  const width = compact ? 560 : 960;
  const height = compact ? 410 : 360;
  const left = compact ? 92 : 82;
  const right = compact ? 20 : 26;
  const top = compact ? 44 : 34;
  const bottom = compact ? 76 : 62;
  const axisFontSize = compact ? 17 : 12;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const visibleValues = compare ? [...forecast, ...history] : forecast;
  const dataMax = Math.max(...visibleValues, 0);
  const axisMax = dataMax > 0 ? dataMax * 1.14 : 1;
  const pointCoordinates = (value, index) => [
    left + (index * plotWidth) / Math.max(forecast.length - 1, 1),
    top + plotHeight - (value / axisMax) * plotHeight,
  ];
  const points = (values) => values.map((value, index) => pointCoordinates(value, index).join(",")).join(" ");

  const yGrid = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const y = top + ratio * plotHeight;
    const value = axisMax * (1 - ratio);
    return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="#dedbd3"/><text x="${left - 12}" y="${y + 4}" text-anchor="end" fill="#657184" font-size="${axisFontSize}">${fmt(value, value >= 100 ? 0 : 1)}</text>`;
  }).join("");
  const xTickIndexes = [0, 6, 12, 18, 23].filter((index) => index < timestamps.length);
  const xTicks = xTickIndexes.map((index) => {
    const [x] = pointCoordinates(0, index);
    const includeDate = index === 0 || localDateParts(timestamps[index], timeZone).day !== localDateParts(timestamps[Math.max(0, index - 1)], timeZone).day;
    return `<line x1="${x}" y1="${top + plotHeight}" x2="${x}" y2="${top + plotHeight + 6}" stroke="#8f99a6"/><text x="${x}" y="${height - 24}" text-anchor="middle" fill="#657184" font-size="${axisFontSize}">${formatChartTime(timestamps[index], timeZone, includeDate)}</text>`;
  }).join("");
  const historyLine = compare && history.length === forecast.length
    ? `<polyline points="${points(history)}" fill="none" stroke="#8b9691" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`
    : "";
  const forecastDots = forecast.map((value, index) => {
    const [cx, cy] = pointCoordinates(value, index);
    return `<circle data-forecast-index="${index}" cx="${cx}" cy="${cy}" r="3.5" fill="#1f4fdb"><title>${formatLocalDateTime(timestamps[index], timeZone)} · ${fmt(value, 1)} kWh</title></circle>`;
  }).join("");
  const peakIndex = forecast.indexOf(Math.max(...forecast));
  const [peakX, peakY] = pointCoordinates(forecast[peakIndex], peakIndex);
  const peakLabelWidth = compact ? 208 : 168;
  const peakLabelX = Math.max(left, Math.min(width - right - peakLabelWidth, peakX - peakLabelWidth / 2));
  const peakLabelY = Math.max(6, peakY - 34);
  const peakLabel = `${formatChartTime(timestamps[peakIndex], timeZone)} · ${fmt(forecast[peakIndex], 1)}kWh`;

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = `<g aria-hidden="true">${yGrid}${xTicks}<text x="${compact ? 24 : 20}" y="${top + plotHeight / 2}" transform="rotate(-90 ${compact ? 24 : 20} ${top + plotHeight / 2})" text-anchor="middle" fill="#4f5c70" font-size="${axisFontSize}" font-weight="700">사용량 (kWh)</text>${historyLine}<polyline points="${points(forecast)}" fill="none" stroke="#1f4fdb" stroke-width="4" stroke-dasharray="9 7" stroke-linecap="round" stroke-linejoin="round"/>${forecastDots}<line id="forecast-hover-guide" x1="${left}" x2="${left}" y1="${top}" y2="${top + plotHeight}" stroke="#1f4fdb" stroke-width="1.5" stroke-dasharray="4 5"/><circle id="forecast-hover-point" cx="${left}" cy="${top + plotHeight}" r="6" fill="#fffdf8" stroke="#1f4fdb" stroke-width="3"/><g class="peak-label" transform="translate(${peakLabelX} ${peakLabelY})"><rect width="${peakLabelWidth}" height="${compact ? 34 : 26}" rx="2" fill="#10213d"/><text x="${peakLabelWidth / 2}" y="${compact ? 23 : 18}" text-anchor="middle" fill="#fff" font-size="${axisFontSize}" font-weight="700">${peakLabel}</text></g></g>`;
  svg.setAttribute("aria-label", `24시간 전력 예측 그래프. 최고 예상 사용량은 ${formatLocalDateTime(result.peak_timestamp, timeZone)} ${fmt(result.peak_kwh, 1)} kWh입니다.${compare ? " 직전 24시간 실측을 회색 실선으로 함께 표시합니다." : ""}`);
  $("history-legend").hidden = !compare;

  const selectFromPointer = (event) => {
    const rect = svg.getBoundingClientRect();
    const viewX = ((event.clientX - rect.left) / rect.width) * width;
    const index = Math.round(((Math.max(left, Math.min(width - right, viewX)) - left) / plotWidth) * (forecast.length - 1));
    updateForecastSelection(index, { showTooltip: true });
  };
  svg.onpointermove = selectFromPointer;
  svg.onclick = selectFromPointer;
  svg.onpointerleave = () => {
    $("forecast-tooltip").hidden = true;
  };
  updateForecastSelection(state.selectedForecastIndex);
}

function drawEmptyChart() {
  const svg = $("forecast-chart");
  svg.setAttribute("viewBox", "0 0 960 360");
  const grid = [52, 112, 172, 232, 292]
    .map((y) => `<line x1="82" y1="${y}" x2="934" y2="${y}" stroke="#e4e7df"/>`)
    .join("");
  svg.innerHTML = `${grid}<text class="empty-chart-label" x="508" y="164">아직 실행된 예측이 없습니다.</text><text class="empty-chart-help" x="508" y="190">CSV 품질 진단과 모델 학습을 완료하면 실제 결과를 표시합니다.</text>`;
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

$("compare-previous").addEventListener("change", () => {
  if (state.predictionResult) drawPredictionChart(state.predictionResult);
});
$("forecast-hour-slider").addEventListener("input", (event) => {
  updateForecastSelection(Number(event.currentTarget.value));
});
let forecastResizeFrame = 0;
window.addEventListener("resize", () => {
  if ((!state.predictionResult && !state.analysisReport) || forecastResizeFrame) return;
  forecastResizeFrame = requestAnimationFrame(() => {
    forecastResizeFrame = 0;
    if (state.predictionResult) drawPredictionChart(state.predictionResult);
    if (state.analysisReport) drawReportChart(state.analysisReport);
  });
});

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
