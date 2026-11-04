from __future__ import annotations

import json
import tempfile
import unittest
from types import SimpleNamespace

from backend.app.ml.contracts import EligibilityError
from backend.app.web.ai_analysis import (
    AIAnalysisUnavailable,
    AIAnalysisUpstreamError,
    analyze_prediction,
    analysis_status,
)
from backend.app.web.analysis_report import build_analysis_report
from backend.app.web.service import TrainingJob, TrainingJobManager


def prediction_payload() -> dict:
    return {
        "run_id": "safe-run-id",
        "model_kind": "xgboost",
        "forecast_origin": "2026-01-01T00:00:00+00:00",
        "timestamps": [f"2026-01-01T{hour:02d}:00:00+00:00" for hour in range(24)],
        "predictions_kwh": [10.0 + hour * 0.25 for hour in range(24)],
        "history_kwh": [9.0 + hour * 0.1 for hour in range(24)],
        "actual_summary": {"total_24h_kwh": 240.0},
        "same_weekday_baseline": {
            "status": "available",
            "method": "최근 최대 8주 동일 요일·시간 실측 평균",
            "values_kwh": [9.5 + hour * 0.1 for hour in range(24)],
            "sample_counts": [8] * 24,
            "total_kwh": sum(9.5 + hour * 0.1 for hour in range(24)),
        },
        "data_period": {
            "start": "2025-07-01T00:00:00+00:00",
            "end": "2025-12-31T23:00:00+00:00",
            "rows": 4416,
        },
        "building_timezone": "UTC",
    }


def report_payload() -> dict:
    job = SimpleNamespace(
        selected_model="xgboost",
        validation_metrics={
            "xgboost": {"mae": 1.0, "wape": 0.1},
            "last_24h": {"mae": 2.0, "wape": 0.2},
        },
        test_metrics={"xgboost": {"mae": 1.2, "wape": 0.12}},
    )
    return build_analysis_report(prediction_payload(), job)


def valid_response() -> dict:
    value = {
        "summary": "예상 피크 시간의 운영 일정을 우선 확인하세요.",
        "peak_analysis": "피크 전후의 동시 사용 일정을 확인할 필요가 있습니다.",
        "comparison": "동일 요일 기준과 차이가 큰 시간대를 확인하세요.",
        "recommendations": [
            {
                "title": "운영 일정 확인",
                "action": "피크 시간의 예약 운전을 확인하세요.",
                "reason": "예상 피크 근거가 있습니다.",
                "evidence_ids": ["forecast_peak"],
                "caveat": "원인 설비는 확인할 수 없습니다.",
            }
        ],
        "limitations": ["설비별 원인은 확인할 수 없습니다."],
        "model_quality": "검증 오차를 함께 고려하세요.",
    }
    return {
        "status": "completed",
        "output": [
            {"content": [{"type": "output_text", "text": json.dumps(value, ensure_ascii=False)}]}
        ],
    }


class AIAnalysisCases(unittest.TestCase):
    def test_local_report_marks_missing_comparison_and_model_quality(self):
        prediction = prediction_payload()
        prediction["same_weekday_baseline"] = {
            "status": "insufficient",
            "method": "최근 최대 8주 동일 요일·시간 실측 평균",
            "values_kwh": [],
            "sample_counts": [1] * 24,
            "total_kwh": None,
        }
        job = SimpleNamespace(selected_model="xgboost", validation_metrics={}, test_metrics={})
        report = build_analysis_report(prediction, job)
        self.assertEqual(report["comparison"]["status"], "insufficient")
        self.assertEqual(report["chart"]["same_weekday_baseline_kwh"], [])
        self.assertIsNone(report["model_quality"]["test"]["wape"])
        self.assertTrue(any("표본" in item for item in report["limitations"]))

    def test_missing_key_is_disabled_without_affecting_forecast(self):
        self.assertFalse(analysis_status({})["enabled"])
        with self.assertRaisesRegex(AIAnalysisUnavailable, "OPENAI_API_KEY"):
            analyze_prediction(report_payload(), environ={})

    def test_only_forecast_summary_is_sent_and_structured_result_is_returned(self):
        captured = {}

        def transport(payload, api_key, timeout):
            captured.update(payload=payload, api_key=api_key, timeout=timeout)
            return valid_response()

        result = analyze_prediction(
            report_payload(),
            environ={"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"},
            transport=transport,
        )
        serialized = json.dumps(captured["payload"], ensure_ascii=False)
        self.assertNotIn("test-secret", serialized)
        self.assertNotIn("csv_text", serialized)
        self.assertIn("hourly_comparison", serialized)
        self.assertIn("allowed_evidence_ids", serialized)
        self.assertEqual(captured["api_key"], "test-secret")
        self.assertEqual(result["source"], "local_quantitative_analysis")
        self.assertEqual(result["ai"]["source"], "openai")
        self.assertEqual(result["ai"]["model"], "test-model")
        self.assertEqual(result["recommendations"][0]["evidence_ids"], ["forecast_peak"])

    def test_invalid_upstream_shape_is_reported(self):
        with self.assertRaises(AIAnalysisUpstreamError):
            analyze_prediction(
                report_payload(),
                environ={"OPENAI_API_KEY": "test-secret"},
                transport=lambda *_: {"status": "completed", "output": []},
            )

    def test_ai_narrative_cannot_introduce_numeric_claims(self):
        response = valid_response()
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["summary"] = "확인되지 않은 절감률은 99%입니다."
        response["output"][0]["content"][0]["text"] = json.dumps(value, ensure_ascii=False)
        report = report_payload()
        result = analyze_prediction(
            report,
            environ={"OPENAI_API_KEY": "test-secret"},
            transport=lambda *_: response,
        )
        self.assertEqual(result["summary"], report["summary"])
        self.assertTrue(result["ai"]["numeric_filter_applied"])

    def test_manager_limits_manual_analysis_calls_and_never_trains(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(
                temporary,
                pipeline=lambda *_args, **_kwargs: self.fail("training must not run"),
                ai_analyzer=lambda report: calls.append(report) or {"summary": "ok"},
            )
            manager._jobs["job-a"] = TrainingJob(
                job_id="job-a",
                building_id="building-a",
                status="COMPLETED",
                run_dir="unused",
                selected_model="xgboost",
                validation_metrics={"xgboost": {"mae": 1.0, "wape": 0.1}},
                test_metrics={"xgboost": {"mae": 1.2, "wape": 0.12}},
            )
            manager.predict = lambda job_id, csv_text: prediction_payload()  # type: ignore[method-assign]
            for _ in range(3):
                self.assertEqual(manager.analyze_prediction("job-a", "local-csv"), {"summary": "ok"})
            with self.assertRaises(EligibilityError):
                manager.analyze_prediction("job-a", "local-csv")
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
