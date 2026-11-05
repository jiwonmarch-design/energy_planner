"""Isolated UI fixture server: no training, recovery or external API routes."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent

BOOTSTRAP = """
<script>
window.addEventListener('load',async()=>{
  const scenario=new URLSearchParams(location.search).get('scenario')||'no_action';
  const report=await fetch('/fixture/'+scenario+'.json').then(r=>r.json());
  state.analysisReport=report;renderAnalysisReport(report);
  const article=document.getElementById('ai-report');
  const checks={scenario,summary:document.getElementById('report-summary').textContent,
    decision:document.getElementById('report-summary-title').textContent,
    comparison:document.getElementById('report-comparison-observation').textContent,
    peak:document.getElementById('report-peak-facts').textContent,
    actionsHidden:document.getElementById('report-actions-section').hidden,
    priorityHidden:document.getElementById('report-priority-action').parentElement.hidden,
    noActionTitleCount:article.innerText.split('추가 조치 권고 없음').length-1,
    overflow:document.documentElement.scrollWidth>innerWidth};
  const html=buildStandaloneReportHtml(report);
  checks.exportContainsSummary=html.includes(checks.summary);
  checks.exportContainsComparison=html.includes(checks.comparison);
  checks.exportContainsPeak=html.includes(checks.peak);
  await fetch('/capture/'+scenario,{method:'POST',body:JSON.stringify({checks,html})});
  if(new URLSearchParams(location.search).has('export')){document.open();document.write(html);document.close();}
  else {document.getElementById('report-preview').scrollIntoView();}
});
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            body = b'{"ai_analysis":{"enabled":false},"model_input":null}'
            kind = "application/json"
        elif path.startswith("/api/"):
            self.send_error(404)
            return
        elif path.startswith("/fixture/"):
            name = path.rsplit("/", 1)[-1]
            if name not in {"no_action.json", "action.json"}:
                self.send_error(404)
                return
            body = (OUTPUT / name).read_bytes()
            kind = "application/json"
        elif path == "/qa.html":
            body = (ROOT / "frontend/index.html").read_text(encoding="utf-8").replace("</body>", BOOTSTRAP + "</body>").encode("utf-8")
            kind = "text/html"
        else:
            name = path.lstrip("/")
            if name not in {"app.js", "reference-system.css"}:
                self.send_error(404)
                return
            body = (ROOT / "frontend" / name).read_bytes()
            kind = "text/javascript" if name.endswith(".js") else "text/css"
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        scenario = self.path.removeprefix("/capture/")
        if not self.path.startswith("/capture/") or scenario not in {"no_action", "action"}:
            self.send_error(405)
            return
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        (OUTPUT / f"{scenario}-browser.json").write_text(json.dumps(value["checks"], ensure_ascii=False, indent=2), encoding="utf-8")
        (OUTPUT / f"{scenario}-export.html").write_text(value["html"], encoding="utf-8")
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8767), Handler).serve_forever()
