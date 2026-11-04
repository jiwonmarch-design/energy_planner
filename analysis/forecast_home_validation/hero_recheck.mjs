import fs from "node:fs";
import path from "node:path";

const outputDir = path.resolve("analysis/forecast_home_validation");
const targets = await fetch("http://127.0.0.1:9232/json/list").then((response) => response.json());
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("Chrome page target not found");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
const pending = new Map();
const errors = [];
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.text);
  if (!message.id || !pending.has(message.id)) return;
  const handlers = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) handlers.reject(new Error(message.error.message));
  else handlers.resolve(message.result);
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++sequence;
  pending.set(id, { resolve, reject });
  socket.send(JSON.stringify({ id, method, params }));
});
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function evaluate(expression) {
  const response = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}
async function waitFor(expression, timeout = 10_000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return true;
    await pause(150);
  }
  return false;
}
async function load(width, height) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await send("Page.navigate", { url: "http://127.0.0.1:8765/" });
  await waitFor("document.readyState === 'complete'");
  await pause(700);
}
async function screenshot(name) {
  const value = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(path.join(outputDir, name), Buffer.from(value.data, "base64"));
}
const checks = [];
const record = (name, pass, details) => checks.push({ name, status: pass ? "PASS" : "FAIL", details });
await send("Page.enable");
await send("Runtime.enable");

for (const [width, height] of [[1440, 900], [390, 844], [320, 844]]) {
  await load(width, height);
  const state = await evaluate(`(() => {
    const title = document.getElementById('hero-title');
    const energy = document.getElementById('brand-energy-toggle');
    window.scrollTo(9999, window.scrollY);
    const horizontalScroll = window.scrollX;
    window.scrollTo(0, window.scrollY);
    return {
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      horizontalScroll,
      titleOverflow: title.scrollWidth > title.clientWidth,
      title: title.textContent.replace(/\\s+/g, ' ').trim(),
      energyColor: getComputedStyle(energy).color,
      plannerColor: getComputedStyle(document.querySelector('.brand-planner')).color,
      primaryHeight: Math.round(document.getElementById('home-primary-cta').getBoundingClientRect().height),
      energyTag: energy.tagName,
      tabIndex: energy.tabIndex
    };
  })()`);
  record(`responsive_${width}`, state.horizontalScroll === 0 && !state.titleOverflow, state);
  record(`brand_${width}`, /Energy\s*Planner\s*mini/.test(state.title) && state.energyColor !== state.plannerColor, state);
  record(`accessibility_${width}`, state.energyTag === "BUTTON" && state.tabIndex === 0 && state.primaryHeight >= 44, state);
  await screenshot(`forecast-home-recheck-${width}.png`);
}

await load(1440, 900);
const uploadOrder = await evaluate(`(() => {
  const panels = [...document.querySelector('.upload-input-grid').children];
  return {
    first: panels[0]?.className || '',
    second: panels[1]?.className || '',
    firstLeft: Math.round(panels[0]?.getBoundingClientRect().left || 0),
    secondLeft: Math.round(panels[1]?.getBoundingClientRect().left || 0)
  };
})()`);
record("timezone_before_upload", uploadOrder.first.includes("timezone-panel") && uploadOrder.second.includes("upload-panel") && uploadOrder.firstLeft < uploadOrder.secondLeft, uploadOrder);
const clickState = await evaluate(`(() => {
  const control = document.getElementById('brand-energy-toggle');
  control.click();
  return { pressed: control.getAttribute('aria-pressed'), active: document.getElementById('landing-home').classList.contains('brand-curve-on') };
})()`);
record("click_toggle", clickState.pressed === "true" && clickState.active, clickState);
await evaluate("document.getElementById('brand-energy-toggle').focus(); true");
await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
const keyState = await evaluate(`({
  pressed: document.getElementById('brand-energy-toggle').getAttribute('aria-pressed'),
  active: document.getElementById('landing-home').classList.contains('brand-curve-on'),
  focused: document.activeElement === document.getElementById('brand-energy-toggle')
})`);
record("keyboard_toggle", keyState.pressed === "false" && !keyState.active && keyState.focused, keyState);

await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
const motion = await evaluate(`({
  past: getComputedStyle(document.querySelector('.brand-curve-past')).transitionDuration,
  future: getComputedStyle(document.querySelector('.brand-curve-future')).transitionDuration
})`);
record("reduced_motion", motion.past === "0s" && motion.future === "0s", motion);
await send("Emulation.setEmulatedMedia", { features: [] });

const primary = await evaluate(`(() => {
  const link = document.getElementById('home-primary-cta');
  link.click();
  return { hash: location.hash, target: link.dataset.scrollTarget };
})()`);
record("primary_cta", primary.hash === `#${primary.target}` && ["upload", "dashboard"].includes(primary.target), primary);
await evaluate("document.querySelector('.topnav a[href=\"#upload\"]').click(); true");
record("header_analysis_link", await waitFor("location.hash === '#upload'"), { hash: await evaluate("location.hash") });
await evaluate("document.querySelector('.topnav a[href=\"#dashboard\"]').click(); true");
record("header_dashboard_link", await waitFor("location.hash === '#dashboard'"), { hash: await evaluate("location.hash") });
await pause(500);
const dashboardLayout = await evaluate(`(() => {
  const dashboard = document.getElementById('dashboard');
  return {
    sectionTop: Math.round(dashboard.getBoundingClientRect().top),
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    cards: dashboard.querySelectorAll('.panel').length
  };
})()`);
record("dashboard_layout", dashboardLayout.scrollWidth === dashboardLayout.viewport && dashboardLayout.cards >= 6, dashboardLayout);
await screenshot("reference-dashboard-empty-1440.png");
record("runtime_errors", errors.length === 0, errors);

const results = {
  executed_at: new Date().toISOString(),
  browser: "Chrome 156 headless via CDP",
  checks,
  summary: { pass: checks.filter((item) => item.status === "PASS").length, fail: checks.filter((item) => item.status === "FAIL").length },
};
fs.writeFileSync(path.join(outputDir, "hero_recheck_results.json"), `${JSON.stringify(results, null, 2)}\n`);
console.log(JSON.stringify(results, null, 2));
socket.close();
