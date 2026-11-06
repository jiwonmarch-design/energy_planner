import fs from "node:fs";
import { execFileSync } from "node:child_process";

async function previewChecks({ evaluate, record, send, screenshot }) {
  const initial = await evaluate("(() => { const d = document.getElementById('service-preview'); const hero = document.getElementById('top'); const menu = document.querySelector('.sticky-steps'); return { open: d.open, label: d.querySelector('summary').textContent.trim(), height: d.getBoundingClientRect().height, afterHero: hero.compareDocumentPosition(d) & Node.DOCUMENT_POSITION_FOLLOWING, beforeMenu: d.compareDocumentPosition(menu) & Node.DOCUMENT_POSITION_FOLLOWING, heroHeight: hero.getBoundingClientRect().height }; })()");
  record("default_collapsed_one_line", !initial.open && initial.height <= 56 && initial.label === "처음 이용하시나요? 서비스 미리보기 ▾", initial);
  record("between_curve_and_steps", Boolean(initial.afterHero && initial.beforeMenu), initial);
  record("hero_markup_unchanged", true, { sameAs: "8684a2f" });
  const click = async (selector) => {
    const expression = "(() => { const el = document.querySelector(" + JSON.stringify(selector) + "); el.scrollIntoView({block: 'center', behavior: 'instant'}); const r = el.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()";
    const point = await evaluate(expression);
    await send("Input.dispatchMouseEvent", {type: "mousePressed", button: "left", clickCount: 1, ...point});
    await send("Input.dispatchMouseEvent", {type: "mouseReleased", button: "left", clickCount: 1, ...point});
  };
  await click("#service-preview > summary");
  const opened = await evaluate("({ open: document.getElementById('service-preview').open, selected: document.querySelector('.service-preview-tabs [aria-selected=\"true\"]').id, heroHeight: document.getElementById('top').getBoundingClientRect().height })");
  record("open_defaults_to_01", opened.open && opened.selected === "preview-tab-1", opened);
  record("hero_geometry_unchanged", opened.heroHeight === initial.heroHeight, opened);
  const labels = await evaluate("[...document.querySelectorAll('.service-preview-tabs button')].map(tab => tab.textContent)");
  const expectedLabels = ["01 에너지 플래너", "02 데이터 준비", "03 모델 학습·비교", "04 예측 보기", "05 운영에 활용"];
  record("five_tab_order", JSON.stringify(labels) === JSON.stringify(expectedLabels), labels);
  const headings = ["에너지 플래너란?", "계량기 하나의 시간별 CSV", "이 건물의 전력 기록으로 모델을 새로 학습하고, 검증에서 오차가 가장 적었던 예측 방식을 선택합니다.", "향후 24시간 전력 사용량", "피크 시간에 잡힌 작업을 옮긴다면?"];
  const heights = [];
  for (let index = 0; index < 5; index++) {
    await click("#preview-tab-" + (index + 1));
    const result = await evaluate("(() => { const active = [...document.querySelectorAll('.service-preview-panel')].filter(p => !p.hidden); return { count: active.length, heading: active[0].querySelector('h3, .service-preview-training-copy').textContent, id: active[0].id, height: document.querySelector('.service-preview-card').getBoundingClientRect().height }; })()");
    heights.push(result.height);
    const headingMatches = result.heading === headings[index] || (index === 1 && result.heading === "건물 한 곳의 시간별 CSV");
    record("tab_" + (index + 1), result.count === 1 && headingMatches && result.id === "preview-panel-" + (index + 1), result);
  }
  record("tab_height_stable", Math.max(...heights) - Math.min(...heights) <= 1, heights);
  await click("#preview-tab-3");
  const training = await evaluate("(() => { const p = document.getElementById('preview-panel-3'); return {children: p.children.length, flow: [...p.querySelectorAll('.service-preview-training-flow strong')].map(s => s.textContent), text: p.textContent}; })()");
  record("training_copy_and_flow_only", training.children === 2 && JSON.stringify(training.flow) === JSON.stringify(["건물 데이터로 학습", "여러 예측 방식 비교", "검증 오차가 가장 낮은 방식 선택"]), training);
  await screenshot("preview-training-1440.png");
  await send("Input.dispatchKeyEvent", {type: "keyDown", key: "End", code: "End", windowsVirtualKeyCode: 35});
  await send("Input.dispatchKeyEvent", {type: "keyUp", key: "End", code: "End", windowsVirtualKeyCode: 35});
  record("keyboard_end_selects_05", await evaluate("document.activeElement.id === 'preview-tab-5' && document.getElementById('preview-tab-5').getAttribute('aria-selected') === 'true'"), {});
  await click("#preview-tab-1");
  await screenshot("preview-open-1440.png");
  await click("#service-preview > summary");
  const closed = await evaluate("({open: document.getElementById('service-preview').open, height: document.getElementById('service-preview').getBoundingClientRect().height})");
  record("same_control_closes", !closed.open && closed.height === initial.height, closed);
  await screenshot("preview-closed-1440.png");
  await click("#service-preview > summary");
  record("same_control_reopens", await evaluate("document.getElementById('service-preview').open"), {});
  for (const width of [390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", {width, height: 844, deviceScaleFactor: 1, mobile: true});
    const sizes = [];
    for (let index = 1; index <= 5; index++) {
      await click("#preview-tab-" + index);
      const result = await evaluate("(() => { const intro = document.querySelector('.service-preview-intro').getBoundingClientRect(); const card = document.querySelector('.service-preview-card').getBoundingClientRect(); const panel = document.getElementById('preview-panel-" + index + "'); return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, panelOverflow: panel.scrollWidth - panel.clientWidth, stacked: card.top >= intro.bottom, height: card.height }; })()");
      sizes.push(result.height);
      record("mobile_" + width + "_tab_" + index, result.overflow === 0 && result.panelOverflow === 0 && result.stacked, result);
    }
    record("mobile_" + width + "_stable_height", Math.max(...sizes) - Math.min(...sizes) <= 1, sizes);
    await click("#preview-tab-3");
    await screenshot("preview-open-" + width + ".png");
  }
  await evaluate("document.body.classList.add('print-ai-report'); true");
  await send("Emulation.setEmulatedMedia", {media: "print"});
  record("report_print_excludes_home_preview", await evaluate("getComputedStyle(document.querySelector('.service-preview-wrap')).display === 'none'"), {});
  await send("Emulation.setEmulatedMedia", {media: "screen"});
  await evaluate("document.body.classList.remove('print-ai-report'); true");
}

const previousHtml = execFileSync("git", ["show", "8684a2f:frontend/index.html"], { encoding: "utf8" });
const currentHtml = fs.readFileSync("frontend/index.html", "utf8");
const hero = (html) => html.match(/<section class="hero[\s\S]*?<\/div><\/section>/)?.[0].replaceAll("\r\n", "\n");
if (hero(previousHtml) !== hero(currentHtml)) throw new Error("Existing hero markup changed");

// Reuse the existing isolated launcher and original hero interaction checks.
let launcher = fs.readFileSync("analysis/home_first_visit_validation/browser_qa.mjs", "utf8")
  .split("let socket;")[0].replaceAll("analysis/home_first_visit_validation", "analysis/service_preview_training_validation");
let checks = fs.readFileSync("analysis/forecast_home_validation/hero_recheck.mjs", "utf8")
  .split("const primary =")[0].replaceAll("analysis/forecast_home_validation", "analysis/service_preview_training_validation")
  .replaceAll(":9232", ":9236");
checks += "\n await (" + previewChecks.toString() + ")({ evaluate, record, send, screenshot });\n";
checks += "record('runtime_errors', errors.length === 0, errors);\n";
checks += "fs.writeFileSync(path.join(outputDir, 'browser_results.json'), JSON.stringify(checks, null, 2));\n";
checks += "const failed = checks.filter(x => x.status === 'FAIL'); console.log(JSON.stringify({pass: checks.length - failed.length, fail: failed.length, failed}, null, 2)); socket.close(); if (failed.length) process.exitCode = 1;\n";
launcher += "try { await fetchJson(cdpUrl + '/json/list'); await import('data:text/javascript;base64,' + Buffer.from(" + JSON.stringify(checks) + ").toString('base64')); } finally { chrome.kill(); }";
try {
  await import("data:text/javascript;base64," + Buffer.from(launcher).toString("base64"));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
