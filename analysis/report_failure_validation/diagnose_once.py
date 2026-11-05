"""One explicitly approved API diagnostic; store safe metadata only."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from backend.app.web import ai_analysis
from backend.app.web.analysis_report import build_analysis_report
from backend.app.web.local_env import load_env_file

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = Path(__file__).with_name("live-diagnostic-once.json")


def main():
    if DESTINATION.exists():
        raise RuntimeError("The approved single diagnostic has already been recorded; refusing another call")
    snapshot = json.loads((ROOT / "analysis/report_observation_validation/before.json").read_text(encoding="utf-8"))
    prior = snapshot["report"]["model_quality"]
    selected = prior["selected_model"]
    job = SimpleNamespace(
        selected_model=selected,
        validation_metrics={selected: prior["validation"], **prior["baseline_validation"]},
        test_metrics={selected: prior["test"]},
    )
    report = build_analysis_report(snapshot["prediction"], job)
    values = os.environ.copy()
    load_env_file(ROOT / ".env", environ=values)
    settings = ai_analysis.analysis_status(values)
    with urlopen("http://127.0.0.1:8765/api/health", timeout=5) as response:
        active = json.loads(response.read())["ai_analysis"]
    for name in ("model", "reasoning_effort", "max_output_tokens", "timeout_seconds"):
        if settings[name] != active[name]:
            raise RuntimeError(f"Diagnostic settings do not match the active server: {name}")
    if settings["max_output_tokens"] != 1200 or settings["reasoning_effort"] != "high":
        raise RuntimeError("The approved diagnostic is limited to 1200 tokens/high")
    record = {"calls": 0, "settings": {key: value for key, value in settings.items() if key != "enabled"}}

    def transport(payload, api_key, timeout):
        if record["calls"]:
            raise RuntimeError("Only one paid request is authorized")
        record["calls"] += 1
        response = ai_analysis._request_openai(payload, api_key, timeout)
        record.update(ai_analysis._response_diagnostics(response))
        return response

    try:
        ai_analysis.analyze_prediction(report, environ=values, transport=transport)
        record["validation"] = "passed"
    except ai_analysis.AIAnalysisUpstreamError as exc:
        record.update(exc.diagnostics)
        record["validation"] = "failed"
    finally:
        if record["calls"]:
            with DESTINATION.open("x", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
            print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
