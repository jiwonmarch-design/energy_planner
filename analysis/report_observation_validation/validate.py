"""Read an immutable run and validate reports using mock AI only."""

import json
import argparse
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

from backend.app.web.ai_analysis import analyze_prediction
from backend.app.web.analysis_report import build_analysis_report
from backend.app.web.service import TrainingJob, TrainingJobManager
from backend.tests.web.test_ai_analysis import report_payload, valid_response

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent


def saved_prediction():
    jobs = []
    for path in (ROOT / "artifacts/web_jobs/_jobs").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") == "COMPLETED" and value.get("run_dir"):
            jobs.append(value)
    value = max(jobs, key=lambda item: item.get("completed_at_utc", ""))
    job = TrainingJob(**{key: item for key, item in value.items() if key in {f.name for f in fields(TrainingJob)}})
    # Bypass job-manager construction/recovery: this inspection never writes jobs.
    reader = SimpleNamespace(get=lambda _job_id: job)
    return TrainingJobManager.predict(reader, job.job_id, ""), job


def validate():
    snapshot = json.loads((OUTPUT / "before.json").read_text(encoding="utf-8"))
    prediction = snapshot["prediction"]
    before = snapshot["report"]
    job = SimpleNamespace(
        selected_model=before["model_quality"]["selected_model"],
        validation_metrics={
            before["model_quality"]["selected_model"]: before["model_quality"]["validation"],
            **before["model_quality"]["baseline_validation"],
        },
        test_metrics={before["model_quality"]["selected_model"]: before["model_quality"]["test"]},
    )
    local = build_analysis_report(prediction, job)
    assert local["operational_candidates"] == before["operational_candidates"] == []
    assert local["quantitative"] == before["quantitative"]
    response = valid_response()
    value = json.loads(response["output"][0]["content"][0]["text"])
    value.update(
        summary="전일보다 낮게 예측되지만 동일 요일 기준과의 차이는 작습니다. 계산된 운영 신호가 기존 조치 기준에 이르지 않아 현재 계획을 바꿀 근거가 충분하지 않습니다.",
        comparison="전일 실측과 여러 주의 동일 요일 평균은 서로 다른 비교 기준입니다. 두 감소 폭의 차이만으로 이상이나 절감 효과를 단정할 수 없습니다.",
        peak_analysis="이번 예상 최고 시각이 과거에도 늘 높은 시간이었다고 보기는 어렵습니다. 과거 표본의 변동 범위가 넓어 반복적인 고사용 시간인지는 판단을 보류합니다.",
        findings=[],
        no_action_reason="계산된 운영 신호가 기존 조치 기준에 이르지 않았습니다.",
        observation_evidence_ids=local["observation_evidence_ids"],
    )
    response["output"][0]["content"][0]["text"] = json.dumps(value, ensure_ascii=False)
    no_action = analyze_prediction(local, environ={"OPENAI_API_KEY": "mock"}, transport=lambda *_: response)
    action_local = report_payload()
    action = analyze_prediction(action_local, environ={"OPENAI_API_KEY": "mock"}, transport=lambda *_: valid_response())
    assert action["operational_candidates"] == action_local["operational_candidates"]
    assert action["recommendations"] and not no_action["recommendations"]
    assert "5.0% 감소" in no_action["comparison"]["observation"]
    assert "0.5% 감소" in no_action["comparison"]["observation"]
    assert no_action["peak_analysis"]["historical_context"]["sample_count"] == 8
    for name, report in (("no_action", no_action), ("action", action)):
        (OUTPUT / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    results = {
        "external_api_calls": 0,
        "saved_run": before["metadata"]["run_id"],
        "forecast_start": before["metadata"]["forecast_start"],
        "quantitative_unchanged": True,
        "action_candidates_unchanged": True,
        "no_action_candidate_count": 0,
        "action_candidate_count": len(action["operational_candidates"]),
        "previous_percent": no_action["quantitative"]["previous_24h_change_percent"],
        "same_weekday_percent": no_action["quantitative"]["same_weekday_change_percent"],
        "peak_history": no_action["peak_analysis"]["historical_context"],
        "before_visible": [before["summary"], before["no_action_reason"], before["no_action_reason"]],
        "after_visible": [no_action["decision"]["title"], no_action["summary"], no_action["comparison"]["ai_interpretation"], no_action["comparison"]["observation"], no_action["peak_analysis"]["observation"]],
    }
    (OUTPUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-before", action="store_true")
    options = parser.parse_args()
    if not options.capture_before:
        validate()
        raise SystemExit(0)
    prediction, job = saved_prediction()
    report = build_analysis_report(prediction, job)
    snapshot = {"prediction": prediction, "report": report}
    destination = OUTPUT / "before.json"
    if destination.exists():
        raise RuntimeError("Do not overwrite the original inspection snapshot")
    destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "forecast_start": report["metadata"]["forecast_start"],
        "run_id": job.run_id if hasattr(job, "run_id") else report["metadata"]["run_id"],
        "previous_percent": report["quantitative"]["previous_24h_change_percent"],
        "same_weekday_percent": report["quantitative"]["same_weekday_change_percent"],
        "peak": report["peak_analysis"],
        "peak_history": next((item for item in report["comparison"]["variability"]["hourly_statistics"] if item["timestamp"] == report["peak_analysis"]["timestamp"]), None),
        "candidates": len(report["operational_candidates"]),
    }, ensure_ascii=False, indent=2))
