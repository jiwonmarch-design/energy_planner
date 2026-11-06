import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const baseUrl = "http://127.0.0.1:8765";
const port = 9236;
const cdpUrl = `http://127.0.0.1:${port}`;
const outputDir = path.resolve("analysis/home_first_visit_validation");
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "energy-planner-home-guide-"));
fs.mkdirSync(outputDir, { recursive: true });
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [
  "--headless=new",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "--disable-gpu",
  "--no-first-run",
  "--window-size=1440,900",
  "about:blank",
], { stdio: "ignore", windowsHide: true });

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function fetchJson(url, timeout = 10_000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    try { return await fetch(url).then((response) => response.json()); } catch {}
    await pause(100);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

let socket;
try {
  const targets = await fetchJson(`${cdpUrl}/json/list`);
  const target = targets.find((item) => item.type === "page");
  if (!target) throw new Error("Chrome page target not found");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  let sequence = 0;
  const pending = new Map();
  const runtimeErrors = [];
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") runtimeErrors.push(message.params.exceptionDetails.text);
    if (!message.id || !pending.has(message.id)) return;
    const callbacks = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callbacks.reject(new Error(message.error.message));
    else callbacks.resolve(message.result);
  });
  const send = (method, params = {}) => {
    const id = ++sequence;
    socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  };
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  const waitFor = async (expression, timeout = 10_000) => {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      if (await evaluate(expression)) return true;
      await pause(100);
    }
    return false;
  };
  const viewport = (width, height) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  const screenshot = async (name) => {
    const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    fs.writeFileSync(path.join(outputDir, name), Buffer.from(result.data, "base64"));
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await viewport(1440, 900);
  await send("Page.navigate", { url: `${baseUrl}/#top` });
  if (!await waitFor("document.readyState === 'complete' && document.querySelectorAll('.home-guide-tab').length === 4")) {
    throw new Error("Energy Planner page did not finish loading");
  }

  const checks = [];
  const record = (name, passed, details) => checks.push({ name, status: passed ? "PASS" : "FAIL", details });
  const expected = [
    ["01 에너지 플래너", "에너지가 언제 얼마나 필요할지 예상하고, 사용 계획을 세우는 도구입니다."],
    ["02 데이터 준비", "건물 한 곳의 시간별 전력 기록을 올립니다."],
    ["03 예측 보기", "앞으로 24시간 중 전기를 가장 많이 쓸 시간을 확인합니다."],
    ["04 운영에 활용", "전기를 많이 쓰는 작업의 시간을 옮겨봅니다."],
  ];
  const initial = await evaluate(`(() => {
    const tabs = [...document.querySelectorAll('.home-guide-tab')];
    const visible = [...document.querySelectorAll('.home-guide-panel')].filter((panel) => !panel.hidden);
    return { labels: tabs.map((tab) => tab.textContent.trim()), selected: tabs.map((tab) => tab.getAttribute('aria-selected')), visible: visible.map((panel) => panel.id), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  })()`);
  record("default_first_tab", initial.selected[0] === "true" && initial.visible.join() === "home-guide-panel-1", initial);
  record("desktop_no_horizontal_overflow", initial.overflow === 0, initial);

  const heights = [];
  for (let index = 0; index < expected.length; index += 1) {
    const state = await evaluate(`(() => {
      const tab = document.querySelectorAll('.home-guide-tab')[${index}];
      tab.click();
      const panel = [...document.querySelectorAll('.home-guide-panel')].find((item) => !item.hidden);
      const copy = panel.querySelector('p');
      const lineHeight = parseFloat(getComputedStyle(copy).lineHeight);
      return { tab: tab.textContent.trim(), selected: tab.getAttribute('aria-selected'), panel: panel.id, copy: copy.textContent.trim(), visualCount: panel.querySelectorAll('[role="img"]').length, height: Math.round(panel.getBoundingClientRect().height), lines: Math.round(copy.getBoundingClientRect().height / lineHeight * 10) / 10 };
    })()`);
    heights.push(state.height);
    record(`tab_${index + 1}_content`, state.tab === expected[index][0] && state.copy === expected[index][1] && state.selected === "true" && state.visualCount === 1, state);
    record(`tab_${index + 1}_desktop_copy`, state.lines <= 1.1, state);
    await screenshot(`home-guide-${index + 1}-1440.png`);
  }
  record("desktop_stable_height", Math.max(...heights) - Math.min(...heights) <= 1, heights);

  const keyboard = await evaluate(`(() => {
    const first = document.querySelectorAll('.home-guide-tab')[0];
    first.click(); first.focus();
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    const tabs = [...document.querySelectorAll('.home-guide-tab')];
    return { active: document.activeElement?.textContent.trim(), selected: tabs.findIndex((tab) => tab.getAttribute('aria-selected') === 'true') };
  })()`);
  record("keyboard_arrow_navigation", keyboard.selected === 1 && keyboard.active === "02 데이터 준비", keyboard);

  const featurePlacement = await evaluate(`(() => ({
    hero: document.getElementById('landing-home').innerText,
    upload: document.getElementById('upload').innerText,
    training: document.getElementById('training').innerText,
    report: document.getElementById('report').innerText,
  }))()`);
  record("details_live_in_feature_screens", !/XGBoost|PatchTST|최소 90일|보고서 생성 절차/.test(featurePlacement.hero) && featurePlacement.upload.includes('최소 90일') && featurePlacement.training.includes('XGBoost') && featurePlacement.training.includes('PatchTST') && featurePlacement.report.includes('보고서 생성'), featurePlacement);

  await viewport(390, 844);
  await evaluate("document.querySelectorAll('.home-guide-tab')[0].click(); document.getElementById('top').scrollIntoView(); true");
  const mobileHeights = [];
  for (let index = 0; index < expected.length; index += 1) {
    const state = await evaluate(`(() => { document.querySelectorAll('.home-guide-tab')[${index}].click(); const panel = [...document.querySelectorAll('.home-guide-panel')].find((item) => !item.hidden); return { height: Math.round(panel.getBoundingClientRect().height), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, copyWidth: panel.querySelector('p').scrollWidth - panel.querySelector('p').clientWidth }; })()`);
    mobileHeights.push(state.height);
    record(`tab_${index + 1}_mobile_wrap`, state.overflow === 0 && state.copyWidth === 0, state);
  }
  record("mobile_stable_height", Math.max(...mobileHeights) - Math.min(...mobileHeights) <= 1, mobileHeights);
  await screenshot("home-guide-4-390.png");

  await viewport(844, 390);
  const landscape = await evaluate(`(() => {
    document.querySelectorAll('.home-guide-tab')[2].click();
    const tabs = [...document.querySelectorAll('.home-guide-tab')];
    return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, minTabHeight: Math.min(...tabs.map((tab) => tab.getBoundingClientRect().height)), visiblePanel: [...document.querySelectorAll('.home-guide-panel')].find((panel) => !panel.hidden)?.id };
  })()`);
  record("phone_landscape_layout", landscape.overflow === 0 && landscape.minTabHeight >= 44 && landscape.visiblePanel === "home-guide-panel-3", landscape);
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  const reducedMotion = await evaluate(`(() => { const tab = document.querySelector('.home-guide-tab'); return { transition: getComputedStyle(tab).transitionDuration, animation: getComputedStyle(tab).animationDuration }; })()`);
  record("reduced_motion", reducedMotion.transition === "0s" && reducedMotion.animation === "0s", reducedMotion);
  record("runtime_errors", runtimeErrors.length === 0, runtimeErrors);

  fs.writeFileSync(path.join(outputDir, "browser_results.json"), `${JSON.stringify(checks, null, 2)}\n`);
  const failed = checks.filter((item) => item.status === "FAIL");
  console.log(JSON.stringify({ passed: checks.length - failed.length, failed: failed.length, checks }, null, 2));
  if (failed.length) process.exitCode = 1;
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  chrome.kill();
  await Promise.race([
    new Promise((resolve) => chrome.once("exit", resolve)),
    pause(2_000),
  ]);
  try {
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
  } catch {
    // Windows can retain a short-lived lock after headless Chrome exits. The
    // isolated profile contains only this validation session and stays in the
    // operating system temp directory for normal cleanup.
  }
}
