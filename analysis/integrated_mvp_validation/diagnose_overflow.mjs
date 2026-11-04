const tabs = await fetch("http://127.0.0.1:9229/json/list").then((response) => response.json());
const target = tabs.find((tab) => tab.type === "page" && tab.url.startsWith("http://127.0.0.1:8765"));
if (!target) throw new Error("Energy Planner tab not found");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let id = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!pending.has(message.id)) return;
  pending.get(message.id)(message.result);
  pending.delete(message.id);
});
const send = (method, params = {}) => new Promise((resolve) => {
  const requestId = ++id;
  pending.set(requestId, resolve);
  socket.send(JSON.stringify({ id: requestId, method, params }));
});
const width = Number(process.argv[2] || 320);
await send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: true });
await send("Page.navigate", { url: "http://127.0.0.1:8765/dashboard" });
await new Promise((resolve) => setTimeout(resolve, 800));
if (process.argv.includes("--predict")) {
  await send("Runtime.evaluate", {
    expression: "document.getElementById('run-prediction').click()",
  });
  const started = Date.now();
  while (Date.now() - started < 30_000) {
    const state = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: "document.getElementById('sample-tag').textContent.includes('실제 예측 결과')",
    });
    if (state.result.value) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}
const result = await send("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    jobStatus: document.getElementById('job-status')?.dataset.status || '',
    predictionButton: {
      hidden: document.getElementById('run-prediction')?.hidden,
      disabled: document.getElementById('run-prediction')?.disabled
    },
    predictionResult: {
      tag: document.getElementById('sample-tag')?.textContent || '',
      rows: document.querySelectorAll('#forecast-table-body tr').length,
      total: document.getElementById('total-forecast')?.textContent.trim() || ''
    },
    offenders: [...document.querySelectorAll('body *')].map((node) => {
      const rect = node.getBoundingClientRect();
      return { tag: node.tagName, id: node.id, className: String(node.className || ''), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width), scrollWidth: node.scrollWidth };
    }).filter((item) => item.right > document.documentElement.clientWidth + 1 || item.left < -1).sort((a, b) => b.right - a.right).slice(0, 20)
  }))()`,
});
console.log(JSON.stringify(result.result.value, null, 2));
socket.close();
