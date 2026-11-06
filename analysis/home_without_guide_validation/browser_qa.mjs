import fs from "node:fs";

// Reuse the established isolated Chrome launcher and the original home checks.
const launcherSource = fs.readFileSync("analysis/home_first_visit_validation/browser_qa.mjs", "utf8");
let launcher = launcherSource.split("let socket;")[0]
  .replaceAll("analysis/home_first_visit_validation", "analysis/home_without_guide_validation");
let checks = fs.readFileSync("analysis/forecast_home_validation/hero_recheck.mjs", "utf8")
  .split("const primary =")[0]
  .replaceAll("analysis/forecast_home_validation", "analysis/home_without_guide_validation")
  .replaceAll(":9232", ":9236");
checks += `
const noGuide = await evaluate('document.querySelectorAll(".home-guide").length === 0');
record('presentation_guide_absent', noGuide, { noGuide });
record('runtime_errors', errors.length === 0, errors);
fs.writeFileSync(path.join(outputDir, 'browser_results.json'), JSON.stringify(checks, null, 2));
console.log(JSON.stringify({pass: checks.filter(x => x.status === 'PASS').length, fail: checks.filter(x => x.status === 'FAIL').length, checks}, null, 2));
socket.close();
if (checks.some(x => x.status === 'FAIL')) process.exitCode = 1;
`;
launcher += `
try {
  await fetchJson(cdpUrl + '/json/list');
  await import('data:text/javascript;base64,' + Buffer.from(${JSON.stringify(checks)}).toString('base64'));
} finally { chrome.kill(); }
`;
try {
  await import("data:text/javascript;base64," + Buffer.from(launcher).toString("base64"));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
