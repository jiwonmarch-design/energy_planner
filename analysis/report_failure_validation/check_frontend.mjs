// Execute the real failure handler and state renderer with a minimal DOM double.
// This verifies state preservation, not browser layout.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const source = fs.readFileSync("frontend/app.js", "utf8");
const index = fs.readFileSync("frontend/index.html", "utf8");
const functions = source.slice(source.indexOf("function updateNextAction()"), source.indexOf("function estimateObservationDays("))
  + source.slice(source.indexOf("async function generateAIReport()"), source.indexOf('$("ai-analyze").onclick'));
const checks = [];
for (const existingReport of [false, true]) {
  for (const failure of ["status=incomplete, reason=max_output_tokens", "JSON parsing failure", "observation evidence rejected", "action evidence rejected"]) {
    const nodes = new Map();
    const $ = (id) => {
      assert(index.includes(`id="${id}"`), id);
      if (!nodes.has(id)) nodes.set(id, {
        hidden: false, textContent: "", innerHTML: "", dataset: {},
        setAttribute(key, value) { this[key] = value; },
        removeAttribute(key) { delete this[key]; },
      });
      return nodes.get(id);
    };
    const prediction = {timestamps: ["2025-09-30T15:00:00+00:00"], predictions_kwh: [7852.8501], building_timezone: "Asia/Seoul"};
    const priorReport = existingReport ? {summary: "existing report"} : null;
    const state = {predictionComplete: true, predictionResult: prediction, job: {job_id: "mock", status: "COMPLETED"}, jobRecovered: true, aiAnalysisAvailable: true, analysisReport: priorReport, stepStatuses: {}};
    $("forecast-chart").innerHTML = "existing-chart";
    $("total-forecast").textContent = "175,940.9 kWh";
    $("report-summary").textContent = existingReport ? "existing report" : "";
    const context = vm.createContext({state, $, analysisIsCurrent: () => false, contextsMatch: () => true, currentContext: () => ({}), setDashboardReadiness: () => {}, renderWorkspaceSteps: () => {}, forecastPeriodText: () => "2025-10-01", requestBody: () => ({}), api: async () => { throw new Error(failure); }, renderAnalysisReport: () => { throw new Error("failed requests must not render a replacement"); }});
    vm.runInContext(functions, context);
    await vm.runInContext("generateAIReport()", context);
    assert.equal(state.predictionResult, prediction);
    assert.equal(state.predictionComplete, true);
    assert.equal(state.analysisReport, priorReport);
    assert.equal($("dashboard-results").hidden, false);
    assert.equal($("forecast-chart").innerHTML, "existing-chart");
    assert.equal($("total-forecast").textContent, "175,940.9 kWh");
    assert.equal($("report-summary").textContent, existingReport ? "existing report" : "");
    assert.equal(state.reportRequestInProgress, false);
    assert.equal($("report-status").dataset.status, "FAILED");
    assert.equal($("ai-analyze").disabled, false);
    checks.push({existingReport, failure, predictionAndReportPreserved: true, retryEnabled: true});
  }
}
fs.writeFileSync("analysis/report_failure_validation/frontend-results.json", JSON.stringify({method:"real handlers with DOM double; not visual verification", checks}, null, 2));
console.log(`${checks.length} failure-state checks PASS`);
