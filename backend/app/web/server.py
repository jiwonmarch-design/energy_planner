"""Local HTTP server for the Energy Planner MVP. No external deployment."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from backend.app.ml.contracts import PipelineError
from backend.app.web.service import TrainingJobManager, analyze_csv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
MANAGER = TrainingJobManager(PROJECT_ROOT / "artifacts" / "web_jobs")
SPA_ROUTES = {"/", "/workspace", "/dashboard"}


def resolve_frontend_target(path: str) -> Path | None:
    """Resolve static assets and known History API routes without a broad fallback."""

    relative = "index.html" if path in SPA_ROUTES else path.lstrip("/")
    target = (FRONTEND_ROOT / relative).resolve()
    frontend_root = FRONTEND_ROOT.resolve()
    if frontend_root not in target.parents and target != frontend_root:
        return None
    return target if target.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "EnergyPlannerLocal/0.1"

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _request_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 30 * 1024 * 1024:
            raise ValueError("요청 본문 크기가 유효하지 않습니다.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/training-jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            try:
                self._json(HTTPStatus.OK, MANAGER.get(job_id).public())
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "energy-planner-local"})
            return
        target = resolve_frontend_target(path)
        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            value = self._request_json()
            if path == "/api/quality":
                result = analyze_csv(
                    value.get("csv_text", ""),
                    building_timezone=value.get("building_timezone", ""),
                    source_timezone_mode=value.get("source_timezone_mode"),
                    warning_approved=bool(value.get("warning_approved", False)),
                )
                self._json(HTTPStatus.OK, result)
                return
            if path == "/api/training-jobs":
                job = MANAGER.submit(
                    building_id=None,
                    csv_text=value.get("csv_text", ""),
                    building_timezone=value.get("building_timezone", ""),
                    source_timezone_mode=value.get("source_timezone_mode"),
                    warning_approved=bool(value.get("warning_approved", False)),
                )
                self._json(HTTPStatus.ACCEPTED, job.public())
                return
            if path.startswith("/api/predictions/"):
                job_id = path.rsplit("/", 1)[-1]
                self._json(HTTPStatus.OK, MANAGER.predict(job_id, value.get("csv_text", "")))
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "지원하지 않는 API입니다."})
        except (PipelineError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "type": type(exc).__name__})
        except Exception as exc:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "서버 처리 중 오류가 발생했습니다.", "type": type(exc).__name__},
            )

    def log_message(self, message: str, *args) -> None:
        print(f"[web] {self.address_string()} {message % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Energy Planner local URL: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
