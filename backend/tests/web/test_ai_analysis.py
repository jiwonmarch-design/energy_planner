from __future__ import annotations

import json
import tempfile
import unittest

from backend.app.ml.contracts import EligibilityError
from backend.app.web.ai_analysis import (
    AIAnalysisUnavailable,
    AIAnalysisUpstreamError,
    analyze_prediction,
    analysis_status,
)
from backend.app.web.service import TrainingJobManager


def prediction_payload() -> dict:
    return {
        "run_id": "safe-run-id",
        "model_kind": "xgboost",
        "forecast_origin": "2026-01-01T00:00:00+00:00",
        "timestamps": [f"2026-01-01T{hour:02d}:00:00+00:00" for hour in range(24)],
        "predictions_kwh": [10.0 + hour * 0.25 for hour in range(24)],
        "history_kwh": [9.0 + hour * 0.1 for hour in range(12)],
    }


def valid_response() -> dict:
    value = {
        "summary": "향후 24시간 예측 사용량은 완만하게 증가합니다.",
        "peak_interpretation": "예측 최대값은 마지막 시각에 나타납니다.",
        "patterns": ["6시간 구간 평균이 순차적으로 증가합니다."],
        "cautions": ["예측값은 실제 사용량과 다를 수 있습니다."],
    }
    return {
        "status": "completed",
        "output": [
            {"content": [{"type": "output_text", "text": json.dumps(value, ensure_ascii=False)}]}
        ],
    }


class AIAnalysisCases(unittest.TestCase):
    def test_missing_key_is_disabled_without_affecting_forecast(self):
        self.assertFalse(analysis_status({})["enabled"])
        with self.assertRaisesRegex(AIAnalysisUnavailable, "OPENAI_API_KEY"):
            analyze_prediction(prediction_payload(), environ={})

    def test_only_forecast_summary_is_sent_and_structured_result_is_returned(self):
        captured = {}

        def transport(payload, api_key, timeout):
            captured.update(payload=payload, api_key=api_key, timeout=timeout)
            return valid_response()

        result = analyze_prediction(
            prediction_payload(),
            environ={"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"},
            transport=transport,
        )
        serialized = json.dumps(captured["payload"], ensure_ascii=False)
        self.assertNotIn("test-secret", serialized)
        self.assertNotIn("csv_text", serialized)
        self.assertIn("hourly_forecast", serialized)
        self.assertEqual(captured["api_key"], "test-secret")
        self.assertEqual(result["source"], "openai")
        self.assertEqual(result["forecast_run_id"], "safe-run-id")
        self.assertEqual(result["model"], "test-model")

    def test_invalid_upstream_shape_is_reported(self):
        with self.assertRaises(AIAnalysisUpstreamError):
            analyze_prediction(
                prediction_payload(),
                environ={"OPENAI_API_KEY": "test-secret"},
                transport=lambda *_: {"status": "completed", "output": []},
            )

    def test_manager_limits_manual_analysis_calls_and_never_trains(self):
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(
                temporary,
                pipeline=lambda *_args, **_kwargs: self.fail("training must not run"),
                ai_analyzer=lambda prediction: calls.append(prediction) or {"summary": "ok"},
            )
            manager.predict = lambda job_id, csv_text: prediction_payload()  # type: ignore[method-assign]
            for _ in range(3):
                self.assertEqual(manager.analyze_prediction("job-a", "local-csv"), {"summary": "ok"})
            with self.assertRaises(EligibilityError):
                manager.analyze_prediction("job-a", "local-csv")
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
