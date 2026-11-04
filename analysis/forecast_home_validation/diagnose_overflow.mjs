const targets = await fetch("http://127.0.0.1:9232/json/list").then((response) => response.json());
const target = targets.find((item) => item.type === "page");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let id = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const value = JSON.parse(event.data);
  if (!value.id || !pending.has(value.id)) return;
  pending.get(value.id)(value.result);
  pending.delete(value.id);
});
const send = (method, params = {}) => new Promise((resolve) => {
  const next = ++id;
  pending.set(next, resolve);
  socket.send(JSON.stringify({ id: next, method, params }));
});
const width = Number(process.argv[2] || 390);
await send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: true });
await send("Page.navigate", { url: "http://127.0.0.1:8765/" });
await new Promise((resolve) => setTimeout(resolve, 1200));
const result = await send("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    stepLayout: (() => {
      const nav = document.querySelector('.sticky-steps');
      const inner = document.querySelector('.steps-inner');
      return {
        nav: { rect: nav.getBoundingClientRect().toJSON(), overflowX: getComputedStyle(nav).overflowX },
        inner: { rect: inner.getBoundingClientRect().toJSON(), overflowX: getComputedStyle(inner).overflowX, scrollWidth: inner.scrollWidth, clientWidth: inner.clientWidth }
      };
    })(),
    offenders: [...document.querySelectorAll('body *')].map((node) => {
      const rect = node.getBoundingClientRect();
      return { tag: node.tagName, id: node.id, className: String(node.className || ''), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width), text: (node.textContent || '').trim().slice(0, 80) };
    }).filter((item) => item.right > document.documentElement.clientWidth + 1 || item.left < -1).sort((a, b) => b.right - a.right).slice(0, 30)
  }))()`,
});
console.log(JSON.stringify(result.result.value, null, 2));
socket.close();
