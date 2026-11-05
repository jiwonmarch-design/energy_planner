// DOM-contract validation for the business report preview, HTML export and print path.
// This uses mock report data only and does not call OpenAI or launch a browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");

class Element {
  constructor(tag, attrs = {}) {
    this.tag = tag; this.attrs = attrs; this.children = []; this.text = "";
    this.checked = "checked" in attrs; this.value = attrs.value || ""; this.dataset = {};
  }
  get id() { return this.attrs.id; }
  get type() { return this.attrs.type; }
  set className(value) { this.attrs.class = value; }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(value) { if (value) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((node) => typeof node === "string" ? node : node.textContent).join(""); }
  get visibleText() { return this.hidden ? "" : this.text + this.children.map((node) => typeof node === "string" ? node : node.visibleText).join(" "); }
  append(...nodes) { for (const node of nodes) { if (node?.tag === "fragment") this.append(...node.children); else { this.children.push(node); if (typeof node !== "string") node.parentElement = this; } } }
  replaceChildren(...nodes) { this.children = []; this.text = ""; this.append(...nodes); }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; }
  querySelectorAll(tag) { return this.children.flatMap((node) => typeof node === "string" ? [] : [...(node.tag === tag ? [node] : []), ...node.querySelectorAll(tag)]); }
  cloneNode() { const node = new Element(this.tag, {...this.attrs}); node.text = this.text; node.checked = this.checked; node.value = this.value; node.dataset = {...this.dataset}; node.append(...this.children.map((child) => typeof child === "string" ? child : child.cloneNode())); return node; }
  get outerHTML() { const attrs = Object.entries(this.attrs).map(([key, value]) => ` ${key}="${escape(value)}"`).join(""); const start = `<${this.tag}${attrs}>`; if (["input", "br", "hr"].includes(this.tag)) return start; return start + escape(this.text) + this.children.map((node) => typeof node === "string" ? node : node.outerHTML).join("") + `</${this.tag}>`; }
}

function parse(html) {
  const root = new Element("document"), stack = [root];
  for (const token of html.match(/<[^>]+>|[^<]+/g)) {
    if (token.startsWith("</")) { stack.pop(); continue; }
    if (token.startsWith("<!")) continue;
    if (!token.startsWith("<")) { stack.at(-1).append(token); continue; }
    const tag = token.match(/^<([\w-]+)/)[1];
    const attrs = {};
    for (const match of token.slice(tag.length + 1, -1).matchAll(/([\w:-]+)(?:="([^"]*)")?/g)) attrs[match[1]] = match[2] || "";
    const node = new Element(tag, attrs); stack.at(-1).append(node);
    if (!["input", "meta", "link", "br", "hr"].includes(tag) && !token.endsWith("/>")) stack.push(node);
  }
  return root;
}

const source = fs.readFileSync("frontend/app.js", "utf8");
function declaration(name) {
  const start = source.indexOf(`function ${name}(`);
  assert(start >= 0, name);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  return source.slice(start, next < 0 ? source.length : start + 1 + next);
}

const index = fs.readFileSync("frontend/index.html", "utf8");
const article = index.slice(index.indexOf('<article id="ai-report"'), index.indexOf("</article>", index.indexOf('<article id="ai-report"')) + 10);
const timestamps = Array.from({length: 24}, (_, hour) => `2025-10-01T${String(hour).padStart(2, "0")}:00:00+09:00`);

function fixture({action = false, historical = false, tiny = false} = {}) {
  const recommendation = {
    title: "오전 7시 운영 일정을 확인하세요",
    action: "예정된 조기 작업이나 가동 일정이 있는지 확인하세요.",
    reason: tiny ? "어제 같은 시간보다 0.010kWh(100.0%) 차이가 납니다." : "어제 같은 시간보다 1.1kWh(22.0%) 차이가 납니다.",
    evidence_ids: ["previous_24h_largest_change"], caveat: "원인 설비는 알 수 없습니다.", priority: 1,
  };
  return {
    source: "local_quantitative_analysis",
    summary: tiny
      ? "다음 24시간 예상 사용량은 0.5kWh입니다. 어제 같은 시간대보다 100.0%(0.24kWh) 높습니다."
      : "다음 24시간 예상 사용량은 77.3kWh입니다. 어제 같은 시간대보다 1.7%(1.3kWh) 높습니다. 최근 8주 같은 요일 평균보다 3.0%(2.3kWh) 높습니다.",
    summary_ai_interpretation: "두 비교 기준 모두 큰 운영 이상보다는 일정 확인이 필요한 수준입니다.",
    decision: {title: action ? "큰 이상 신호는 없지만 일부 시간대를 확인하세요" : "큰 이상 신호는 없습니다", tone: action ? "calm_attention" : "stable"},
    observation_evidence_ids: {summary: ["forecast_total"], comparison: ["previous_24h_comparison"], peak_analysis: ["forecast_peak"]},
    evidence: [
      {id: "forecast_total", label: "24시간 예상 사용량", value: tiny ? 0.48 : 77.3, unit: "kWh"},
      {id: "forecast_peak", label: "예상 피크", value: 5.7, unit: "kWh", timestamp: timestamps[11]},
      {id: "previous_24h_comparison", label: "어제 같은 시간대 대비", value: tiny ? 100 : 1.7, unit: "%"},
      {id: "previous_24h_largest_change", label: "어제 같은 시간 대비 가장 큰 시간별 변화", value: tiny ? 0.01 : 1.1, relative_percent: tiny ? 100 : 22, unit: "kWh", timestamp: timestamps[7]},
    ],
    comparison: {observation: "어제 같은 시간대와 최근 8주 같은 요일 평균을 함께 확인했습니다.", ai_interpretation: "서로 다른 두 비교 기준을 함께 보면 큰 이상 신호는 아닙니다."},
    peak_analysis: {observation: "전력 사용이 가장 많을 것으로 예상되는 시간은 오전 11시이며, 예상 사용량은 5.7kWh입니다. 최근 8주 같은 요일의 오전 11시 사용량은 4.4~6.1kWh였으므로 평소 사용 범위 안에 있습니다.", ai_interpretation: "평소에도 사용량이 높은 편인 시간대입니다."},
    recommendations: action ? [recommendation] : [],
    no_action_reason: action ? "" : "큰 이상 신호는 없습니다. 현재 운영 계획을 유지하면서 실제 사용량 흐름을 확인하세요.",
    limitations: ["설비별 사용량과 실제 전기요금 정보가 없어 증가 원인이나 절감 금액을 계산할 수 없습니다.", ...(historical ? ["예측 대상 기간이 이미 지나 현재 운영 계획으로 사용할 수 없습니다. 과거 데이터 검증 결과로만 확인하세요."] : [])],
    model_quality: {selected_model: "xgboost", validation: {mae: 0.4, wape: 0.2}, test: {mae: 0.5, wape: 0.257}, baseline_validation: {last_24h: {mae: 0.7, wape: 0.3}}, mae_improvement_vs_best_baseline_percent: 42.9, business_summary: "이 모델의 과거 검증에서 확인된 평균 오차율은 25.7%입니다. 정확한 사용량을 확정하는 값보다, 사용량이 높아질 시간대를 미리 확인하는 참고 자료로 활용하세요.", note: "Validation으로 모델을 선택하고 Test는 독립적인 최종 평가에만 사용했습니다."},
    quantitative: {total_kwh: tiny ? 0.48 : 77.3, peak_kwh: 5.7, peak_timestamp: timestamps[11], previous_24h_change_percent: tiny ? 100 : 1.7, previous_24h_difference_kwh: tiny ? 0.24 : 1.3, same_weekday_change_percent: 3.0},
    chart: {timestamps, forecast_kwh: Array(24).fill(3), same_weekday_baseline_kwh: Array(24).fill(2.9), baseline_status: "available", baseline_method: "최근 최대 8주 동일 요일·시간 실측 평균"},
    metadata: {building_timezone: "Asia/Seoul", generated_at_utc: "2026-11-05T00:00:00+00:00", data_start: timestamps[0], data_end: timestamps[23], data_rows: 2160, forecast_start: timestamps[0], forecast_end: timestamps[23], report_purpose: historical ? "historical_validation" : "operations_plan", report_purpose_label: historical ? "과거 데이터 검증 결과" : "운영 계획 참고"},
    ai: {status: "completed"},
  };
}

const results = [];
for (const scenario of [
  {name: "action", options: {action: true}},
  {name: "no_action", options: {}},
  {name: "historical", options: {historical: true}},
  {name: "large_relative_small_absolute", options: {action: true, tiny: true}},
]) {
  const report = fixture(scenario.options);
  const tree = parse(article);
  const collect = (node) => node.children.flatMap((child) => typeof child === "string" ? [] : [child, ...collect(child)]);
  const elements = tree.querySelectorAll("article").flatMap((node) => [node, ...collect(node)]);
  const byId = Object.fromEntries(elements.filter((node) => node.id).map((node) => [node.id, node]));
  for (const id of ["report-preview", "download-report-html", "print-report", "regenerate-report"]) byId[id] = new Element("div", {id});
  function $(id) { assert(byId[id], id); return byId[id]; }
  const context = vm.createContext({
    $, document: {createElement: (tag) => new Element(tag), createDocumentFragment: () => new Element("fragment")},
    state: {}, Intl, Number, String, JSON, Math,
    fmt: (number, digits = 1) => Number(number).toLocaleString("ko-KR", {maximumFractionDigits: digits}),
    formatLocalDateTime: (value, timeZone) => new Intl.DateTimeFormat("ko-KR", {timeZone, dateStyle: "short", timeStyle: "short"}).format(new Date(value)),
    formatKoreanHour: (value, timeZone) => new Intl.DateTimeFormat("ko-KR", {timeZone, hour: "numeric"}).format(new Date(value)),
    forecastPeriodText: () => "예측 대상 저장 결과", modelDisplayName: (value) => value,
    renderTextList: (node, list) => { node.textContent = list.join(" / "); }, drawReportChart: () => {},
  });
  for (const name of ["fmtKwhDifference", "percentText", "metricValue", "evidenceLabel", "renderRecommendations", "renderAnalysisReport", "safeJsonForHtml", "buildStandaloneReportHtml"]) vm.runInContext(declaration(name), context);
  context.report = report;
  vm.runInContext("renderAnalysisReport(report)", context);
  const html = vm.runInContext("buildStandaloneReportHtml(report)", context);
  const visible = $("ai-report").visibleText;
  const headings = ["1. 핵심 판단", "2. 사용량이 가장 높은 시간", "3. 지금 확인할 사항", "4. 예측 정확도", "5. 참고사항 및 한계", "6. 기술 지표 상세 보기"];
  let cursor = -1;
  for (const heading of headings) { const next = visible.indexOf(heading); assert(next > cursor, heading); cursor = next; }
  for (const text of [report.summary, report.peak_analysis.observation, report.model_quality.business_summary, ...report.limitations]) assert(html.includes(escape(text)), text);
  assert.equal($("report-actions-section").hidden, false);
  assert.equal($("report-no-action").hidden, scenario.options.action === true);
  assert.equal($("report-purpose-badge").textContent, report.metadata.report_purpose_label);
  if (scenario.options.tiny) assert(visible.includes("100.0%(0.24kWh)"));
  assert(html.includes(".report-technical>*{display:block!important}"));
  if (scenario.name === "action") {
    fs.writeFileSync("analysis/business_report_validation/standalone-report.html", html);
  }
  results.push({scenario: scenario.name, status: "PASS", previewAndHtmlTextMatch: true, printUsesSameArticle: true});
}

const printFunction = declaration("printAnalysisReport");
assert(printFunction.includes("window.print()"));
assert(!printFunction.includes("cloneNode"));
const generationFunction = declaration("generateAIReport");
assert(generationFunction.includes("/api/analysis-report/"));
assert(generationFunction.includes("서버가 계산한 수치와 기본 문장"));
fs.writeFileSync("analysis/business_report_validation/results.json", JSON.stringify({method: "mock DOM contract", results}, null, 2));
console.log(JSON.stringify(results));
