// DOM-contract test for the real preview renderer and HTML export function.
// This is a small test double, not a browser or visual-layout verification.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import path from "node:path";

const output = path.resolve("analysis/report_observation_validation");
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
class Element {
  constructor(tag, attrs = {}) { this.tag = tag; this.attrs = attrs; this.children = []; this.text = ""; this.checked = "checked" in attrs; this.value = attrs.value || ""; }
  get id() { return this.attrs.id; }
  get type() { return this.attrs.type; }
  get className() { return this.attrs.class; }
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
  cloneNode() { const node = new Element(this.tag, {...this.attrs}); node.text = this.text; node.checked = this.checked; node.value = this.value; node.append(...this.children.map((child) => typeof child === "string" ? child : child.cloneNode())); return node; }
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
    const raw = token.slice(tag.length + 1, -1);
    for (const match of raw.matchAll(/([\w:-]+)(?:="([^"]*)")?/g)) attrs[match[1]] = match[2] || "";
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
const checks = [];
for (const scenario of ["no_action", "action"]) {
  const report = JSON.parse(fs.readFileSync(path.join(output, `${scenario}.json`), "utf8"));
  const tree = parse(article);
  const elements = tree.querySelectorAll("article").flatMap((node) => [node, ...collect(node)]);
  function collect(node) { return node.children.flatMap((child) => typeof child === "string" ? [] : [child, ...collect(child)]); }
  const byId = Object.fromEntries(elements.filter((node) => node.id).map((node) => [node.id, node]));
  // Report controls are outside the exported article.
  for (const id of ["report-preview", "download-report-html", "print-report", "regenerate-report"]) byId[id] = new Element("div", {id});
  const context = vm.createContext({
    $, document: { createElement: (tag) => new Element(tag), createDocumentFragment: () => new Element("fragment") },
    state: {}, Intl, Number, String, JSON, Math,
    fmt: (n, digits = 1) => Number(n).toLocaleString("ko-KR", {maximumFractionDigits: digits}),
    formatLocalDateTime: (value, timeZone) => new Intl.DateTimeFormat("ko-KR", {timeZone, dateStyle: "short", timeStyle: "short"}).format(new Date(value)),
    formatKoreanHour: (value, timeZone) => new Intl.DateTimeFormat("ko-KR", {timeZone, hour: "numeric"}).format(new Date(value)),
    forecastPeriodText: () => "예측 대상 저장 결과",
    modelDisplayName: (value) => value,
    renderTextList: (node, list) => node.textContent = list.join(" / "),
    drawReportChart: () => {},
  });
  function $(id) { assert(byId[id], id); return byId[id]; }
  for (const name of ["percentText", "metricValue", "evidenceLabel", "renderRecommendations", "renderAnalysisReport", "safeJsonForHtml", "buildStandaloneReportHtml"]) vm.runInContext(declaration(name), context);
  context.report = report;
  vm.runInContext("renderAnalysisReport(report)", context);
  const html = vm.runInContext("buildStandaloneReportHtml(report)", context);
  assert.equal($("report-summary").textContent, report.summary);
  assert.equal($("report-comparison-observation").textContent, report.comparison.ai_interpretation);
  assert.equal($("report-peak-observation").textContent, report.peak_analysis.ai_interpretation);
  assert.equal($("report-actions-section").hidden, scenario === "no_action");
  assert.equal($("report-priority-action").parentElement.hidden, scenario === "no_action");
  assert.equal(($("ai-report").visibleText.match(/추가 조치 권고 없음/g) || []).length, scenario === "no_action" ? 1 : 0);
  for (const text of [report.summary, report.comparison.ai_interpretation, report.peak_analysis.ai_interpretation, report.peak_analysis.observation]) assert(html.includes(escape(text)), text);
  assert(html.includes("[hidden]{display:none!important}"));
  assert(html.includes("@media print"));
  assert(!html.includes("OPENAI_API_KEY="));
  fs.writeFileSync(path.join(output, `${scenario}-export.html`), html);
  checks.push({scenario, status:"PASS", previewAndHtmlNarrativesMatch:true, noActionDeduplicated:true, printUsesSameArticle:true});
}
fs.writeFileSync(path.join(output,"render-results.json"), JSON.stringify({method:"DOM test double; not visual browser verification",checks},null,2));
console.log(JSON.stringify(checks));
