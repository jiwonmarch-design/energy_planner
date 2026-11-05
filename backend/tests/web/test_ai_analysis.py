from __future__ import annotations

import json
import io
import socket
import ssl
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from types import SimpleNamespace

from backend.app.web.ai_analysis import (
    AIAnalysisUnavailable,
    AIAnalysisUpstreamError,
    analyze_prediction,
    analysis_status,
    _request_openai,
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
            "statistics_by_hour": [
                {
                    "timestamp": f"2026-01-01T{hour:02d}:00:00+00:00",
                    "sample_count": 8,
                    "mean_kwh": 9.5 + hour * 0.1,
                    "variance_kwh2": 0.25,
                    "standard_deviation_kwh": 0.5,
                    "minimum_kwh": 9.0 + hour * 0.1,
                    "maximum_kwh": 10.0 + hour * 0.1,
                    "range_kwh": 1.0,
                }
                for hour in range(24)
            ],
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
        "summary": "동일 요일 기준에서 벗어난 시간대가 있습니다.",
        "peak_analysis": "예상 사용량이 가장 높은 시각과 고사용 구간이 확인됩니다.",
        "comparison": "동일 요일 평균과 직전 실측 대비 차이가 나타납니다.",
        "observation_evidence_ids": {
            "summary": ["forecast_total"],
            "peak_analysis": ["forecast_peak"],
            "comparison": ["same_weekday_comparison", "previous_24h_comparison"],
        },
        "findings": [
            {
                "title": "운영 일정 확인",
                "operational_meaning": "동일 요일 범위를 벗어난 운영 신호가 있습니다.",
                "recommended_action": "해당 시간의 운영 일정을 확인하세요.",
                "evidence_ids": ["same_weekday_largest_deviation"],
                "limitation": "원인 설비는 확인할 수 없습니다.",
            }
        ],
        "no_action_reason": "조치 후보가 있으면 사용하지 않습니다.",
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
    def test_confirmed_token_limit_failure_with_larger_configured_budget(self):
        # Replay the approved live diagnostic's metadata; no network requests.
        limited = {
            "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "_http_status": 200, "output": [],
            "usage": {"input_tokens": 14206, "output_tokens": 1200, "output_tokens_details": {"reasoning_tokens": 785}},
        }
        requests = []

        def transport(payload, *_):
            requests.append(payload)
            return limited if payload["max_output_tokens"] == 1200 else valid_response()

        values = {"OPENAI_API_KEY": "mock", "OPENAI_REASONING_EFFORT": "high"}
        with self.assertLogs("backend.app.web.ai_analysis", level="WARNING"):
            with self.assertRaises(AIAnalysisUpstreamError) as raised:
                analyze_prediction(report_payload(), environ=values, transport=transport)
        self.assertEqual(raised.exception.diagnostics["incomplete_reason"], "max_output_tokens")
        self.assertEqual(len(requests), 1)  # no automatic retry
        values["OPENAI_MAX_OUTPUT_TOKENS"] = "4096"
        result = analyze_prediction(report_payload(), environ=values, transport=transport)
        self.assertEqual(requests[-1]["max_output_tokens"], 4096)
        self.assertEqual(requests[-1]["reasoning"], {"effort": "high"})
        self.assertEqual(result["ai"]["status"], "completed")
        self.assertTrue(result["recommendations"])
        self.assertEqual(analysis_status(values)["max_output_tokens"], 4096)

    def test_output_budget_is_bounded_and_invalid_value_keeps_legacy_default(self):
        for configured, expected in (("bad", 1200), ("0", 1200), ("100000", 16384), ("4096", 4096)):
            with self.subTest(configured=configured):
                self.assertEqual(analysis_status({"OPENAI_MAX_OUTPUT_TOKENS": configured})["max_output_tokens"], expected)

    def test_larger_budget_preserves_both_evidence_gates(self):
        for gate in ("observation", "action"):
            with self.subTest(gate=gate):
                response = valid_response()
                value = json.loads(response["output"][0]["content"][0]["text"])
                if gate == "observation":
                    value["observation_evidence_ids"]["summary"] = ["unknown"]
                else:
                    value["findings"][0]["evidence_ids"] = ["forecast_total"]
                response["output"][0]["content"][0]["text"] = json.dumps(value)
                with self.assertRaises(AIAnalysisUpstreamError) as raised:
                    analyze_prediction(report_payload(), environ={"OPENAI_API_KEY": "mock", "OPENAI_MAX_OUTPUT_TOKENS": "4096", "OPENAI_REASONING_EFFORT": "high"}, transport=lambda *_: response)
                self.assertEqual(raised.exception.diagnostics["stage"], "observation_evidence" if gate == "observation" else "actionable_evidence")

    def test_status_exposes_effective_nonsecret_request_settings(self):
        status = analysis_status({"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "test-model", "OPENAI_REASONING_EFFORT": "high", "OPENAI_TIMEOUT_SECONDS": "20"})
        self.assertEqual(status["max_output_tokens"], 1200)
        self.assertEqual(status["timeout_seconds"], 20)
        self.assertNotIn("secret", json.dumps(status))

    def test_http_handler_exposes_failure_stage_without_replacing_forecast(self):
        from backend.app.web.server import Handler

        error = AIAnalysisUpstreamError("incomplete", stage="response_status", diagnostics={"http_status": 200, "response_status": "incomplete", "incomplete_reason": "max_output_tokens"})
        result = {}
        handler = object.__new__(Handler)
        handler.path = "/api/ai-analysis/mock"
        handler._request_json = lambda: {}
        handler._json = lambda status, body: result.update(status=status, body=body)
        handler.log_message = lambda *_: None
        with patch("backend.app.web.server.MANAGER") as manager:
            manager.analyze_prediction.side_effect = error
            handler.do_POST()
            manager.submit.assert_not_called()
            manager.predict.assert_not_called()
        self.assertEqual(result["status"], 502)
        self.assertEqual(result["body"]["diagnostics"]["http_status"], 200)
        self.assertEqual(result["body"]["diagnostics"]["stage"], "response_status")

    def test_incomplete_response_reports_actual_reason_and_token_usage(self):
        response = {
            "_http_status": 200,
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {"output_tokens": 1200, "output_tokens_details": {"reasoning_tokens": 1200}},
            # Even complete-looking text must not bypass the incomplete gate.
            "output": valid_response()["output"],
        }
        with self.assertLogs("backend.app.web.ai_analysis", level="WARNING") as logged:
            with self.assertRaises(AIAnalysisUpstreamError) as raised:
                analyze_prediction(report_payload(), environ={"OPENAI_API_KEY": "secret-never-log", "OPENAI_REASONING_EFFORT": "high"}, transport=lambda *_: response)
        self.assertEqual(raised.exception.diagnostics["stage"], "response_status")
        self.assertEqual(raised.exception.diagnostics["http_status"], 200)
        self.assertEqual(raised.exception.diagnostics["incomplete_reason"], "max_output_tokens")
        self.assertEqual(raised.exception.diagnostics["reasoning_tokens"], 1200)
        self.assertIn("max_output_tokens", str(raised.exception))
        self.assertNotIn("secret-never-log", str(logged.output))
        self.assertNotIn("operational_candidates", str(logged.output))

    def test_non_token_incomplete_reason_is_preserved_without_retry(self):
        calls = []

        def transport(*_):
            calls.append(True)
            return {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}, "output": []}

        with self.assertLogs("backend.app.web.ai_analysis", level="WARNING"):
            with self.assertRaises(AIAnalysisUpstreamError) as raised:
                analyze_prediction(report_payload(), environ={"OPENAI_API_KEY": "mock"}, transport=transport)
        self.assertEqual(raised.exception.diagnostics["incomplete_reason"], "content_filter")
        self.assertEqual(len(calls), 1)

    def test_http_error_keeps_status_and_code_without_error_message_or_key(self):
        body = json.dumps({"error": {"code": "invalid_api_key", "message": "secret-never-log private-input"}}).encode()
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 401, "Unauthorized", {}, io.BytesIO(body))
        with patch("backend.app.web.ai_analysis.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AIAnalysisUpstreamError) as raised:
                _request_openai({}, "secret-never-log", 20)
        self.assertEqual(raised.exception.diagnostics["stage"], "http_error")
        self.assertEqual(raised.exception.diagnostics["http_status"], 401)
        self.assertEqual(raised.exception.diagnostics["error_code"], "invalid_api_key")
        self.assertNotIn("secret-never-log", str(raised.exception))

    def test_http_429_preserves_documented_safe_billing_code(self):
        body = json.dumps({
            "error": {
                "code": "credit_balance_exhausted",
                "message": "private billing detail",
            }
        }).encode()
        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/responses", 429, "Too Many Requests", {}, io.BytesIO(body)
        )
        with patch("backend.app.web.ai_analysis.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AIAnalysisUpstreamError) as raised:
                _request_openai({}, "secret-never-log", 20)
        self.assertEqual(raised.exception.diagnostics["http_status"], 429)
        self.assertEqual(raised.exception.diagnostics["error_code"], "credit_balance_exhausted")
        self.assertNotIn("private billing detail", str(raised.exception))

    def test_transport_failures_keep_only_safe_reason_categories(self):
        cases = (
            (urllib.error.URLError(TimeoutError("private timeout detail")), "timeout"),
            (urllib.error.URLError(socket.gaierror("private dns detail")), "dns"),
            (urllib.error.URLError(ssl.SSLError("private tls detail")), "tls"),
            (urllib.error.URLError(ConnectionRefusedError("private connection detail")), "connection"),
        )
        for failure, expected in cases:
            with self.subTest(expected=expected):
                with patch("backend.app.web.ai_analysis.urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(AIAnalysisUpstreamError) as raised:
                        _request_openai({}, "secret-never-log", 20)
                self.assertEqual(raised.exception.diagnostics["stage"], "transport")
                self.assertEqual(raised.exception.diagnostics["transport_reason"], expected)
                self.assertEqual(raised.exception.diagnostics["timeout_seconds"], 20)
                self.assertNotIn("private", str(raised.exception))
                self.assertNotIn("secret-never-log", str(raised.exception))
        self.assertNotIn("private-input", str(raised.exception.diagnostics))

    def test_observations_use_allowed_evidence_without_action_candidates(self):
        report = report_payload()
        report["operational_candidates"] = []
        report["recommendations"] = []
        response = valid_response()
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["findings"] = []
        value["summary"] = " 전일 기준과 동일 요일 기준의 변화 폭이 다릅니다."
        response["output"][0]["content"][0]["text"] = json.dumps(value)
        captured = {}

        def transport(payload, *_):
            captured.update(json.loads(payload["input"][1]["content"].split("\n\n", 1)[1]))
            return response

        result = analyze_prediction(report, environ={"OPENAI_API_KEY": "mock"}, transport=transport)
        self.assertEqual(captured["actionable_evidence_ids"], [])
        self.assertIn("previous_24h_comparison", captured["allowed_evidence_ids"])
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["summary"], report["summary"])
        self.assertEqual(result["summary_ai_interpretation"], value["summary"])
        self.assertEqual(result["comparison"]["ai_interpretation"], value["comparison"])

    def test_observation_unknown_evidence_is_rejected(self):
        response = valid_response()
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["observation_evidence_ids"]["comparison"] = ["invented"]
        response["output"][0]["content"][0]["text"] = json.dumps(value)
        with self.assertRaisesRegex(AIAnalysisUpstreamError, "운영 관찰"):
            analyze_prediction(report_payload(), environ={"OPENAI_API_KEY": "mock"}, transport=lambda *_: response)

    def test_uncited_observation_falls_back_to_server_facts(self):
        response = valid_response()
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["observation_evidence_ids"]["peak_analysis"] = []
        response["output"][0]["content"][0]["text"] = json.dumps(value)
        report = report_payload()
        result = analyze_prediction(report, environ={"OPENAI_API_KEY": "mock"}, transport=lambda *_: response)
        self.assertEqual(result["peak_analysis"]["ai_interpretation"], "")
        self.assertEqual(result["peak_analysis"]["observation"], report["peak_analysis"]["observation"])

    def test_peak_history_requires_samples_and_defers_habitual_peak_claim(self):
        prediction = prediction_payload()
        job = SimpleNamespace(selected_model="xgboost")
        report = build_analysis_report(prediction, job)
        self.assertEqual(report["peak_analysis"]["historical_context"]["sample_count"], 8)
        self.assertIn("평소 사용 범위", report["peak_analysis"]["observation"])
        prediction["same_weekday_baseline"]["statistics_by_hour"][-1]["sample_count"] = 1
        report = build_analysis_report(prediction, job)
        self.assertEqual(report["peak_analysis"]["historical_context"]["status"], "insufficient")
        self.assertIn("확인할 수 없습니다", report["peak_analysis"]["observation"])
        self.assertNotIn("peak_historical_context", {item["id"] for item in report["evidence"]})

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
        self.assertEqual(report["comparison"]["variability"]["status"], "insufficient")
        self.assertTrue(any("자료가 부족" in item for item in report["limitations"]))

    def test_local_report_calculates_operational_decision_metrics(self):
        report = report_payload()
        self.assertEqual(len(report["comparison"]["hourly_differences"]), 24)
        first = report["comparison"]["hourly_differences"][0]
        self.assertEqual(first["absolute_difference_kwh"], 0.5)
        self.assertAlmostEqual(first["difference_percent"], 0.5 / 9.5 * 100.0)
        self.assertEqual(first["baseline_variance_kwh2"], 0.25)
        self.assertTrue(first["outside_historical_range"] is False)
        self.assertEqual(report["comparison"]["variability"]["status"], "available")
        self.assertEqual(report["comparison"]["variability"]["average_variance_kwh2"], 0.25)
        self.assertEqual(report["comparison"]["variability"]["maximum_range_kwh"], 1.0)
        self.assertTrue(report["peak_analysis"]["high_usage_segments"])
        self.assertIsNotNone(report["peak_analysis"]["peak_segment_share_percent"])
        self.assertEqual(len(report["previous_24h_comparison"]["hourly_differences"]), 24)
        self.assertEqual(len(report["previous_24h_comparison"]["major_change_hours"]), 3)
        evidence_ids = {item["id"] for item in report["evidence"]}
        self.assertIn("same_weekday_largest_deviation", evidence_ids)
        self.assertIn("previous_24h_largest_change", evidence_ids)
        self.assertIn("peak_period_share", evidence_ids)

    def test_business_report_uses_requested_ordering_terms_and_accuracy_copy(self):
        report = report_payload()
        self.assertIn("다음 24시간 예상 사용량", report["summary"])
        self.assertIn("어제 같은 시간대", report["summary"])
        self.assertIn("최근 8주 같은 요일 평균", report["summary"])
        self.assertIn("평소 사용 범위", report["peak_analysis"]["observation"])
        self.assertIn("과거 검증에서 확인된 평균 오차율", report["model_quality"]["business_summary"])
        self.assertNotIn("단정할 수 없습니다", report["summary"] + report["peak_analysis"]["observation"])

    def test_past_forecast_is_marked_as_historical_validation(self):
        report = report_payload()
        self.assertEqual(report["metadata"]["report_purpose"], "historical_validation")
        self.assertEqual(report["metadata"]["report_purpose_label"], "과거 데이터 검증 결과")
        self.assertTrue(any("현재 운영 계획으로 사용할 수 없습니다" in item for item in report["limitations"]))

    def test_small_total_change_and_usual_peak_soften_action_title(self):
        prediction = prediction_payload()
        prediction["timestamps"] = [
            f"2099-01-01T{hour:02d}:00:00+00:00" for hour in range(24)
        ]
        values = [float(value) for value in range(1, 25)]
        prediction["predictions_kwh"] = values
        prediction["history_kwh"] = values
        prediction["actual_summary"]["total_24h_kwh"] = sum(values)
        prediction["same_weekday_baseline"]["values_kwh"] = values
        prediction["same_weekday_baseline"]["total_kwh"] = sum(values)
        for index, item in enumerate(prediction["same_weekday_baseline"]["statistics_by_hour"]):
            value = values[index]
            item.update(
                mean_kwh=value,
                variance_kwh2=1.0,
                standard_deviation_kwh=1.0,
                minimum_kwh=value - 2.0,
                maximum_kwh=value + 2.0,
                range_kwh=4.0,
            )
        report = build_analysis_report(prediction, SimpleNamespace(selected_model="xgboost"))
        self.assertTrue(report["recommendations"])
        self.assertEqual(report["decision"]["tone"], "calm_attention")
        self.assertEqual(report["decision"]["title"], "큰 이상 신호는 없지만 일부 시간대를 확인하세요")
        self.assertIn("오후 6시~오후 11시", report["summary"])

    def test_large_relative_change_keeps_small_absolute_change_visible(self):
        prediction = prediction_payload()
        prediction["predictions_kwh"] = [0.02] * 24
        prediction["history_kwh"] = [0.01] * 24
        prediction["actual_summary"]["total_24h_kwh"] = 0.24
        prediction["same_weekday_baseline"]["values_kwh"] = [0.02] * 24
        prediction["same_weekday_baseline"]["total_kwh"] = 0.48
        for item in prediction["same_weekday_baseline"]["statistics_by_hour"]:
            item.update(
                mean_kwh=0.02,
                variance_kwh2=0.000025,
                standard_deviation_kwh=0.005,
                minimum_kwh=0.01,
                maximum_kwh=0.03,
                range_kwh=0.02,
            )
        report = build_analysis_report(prediction, SimpleNamespace(selected_model="xgboost"))
        self.assertIn("100.0%(0.24kWh)", report["summary"])
        previous_action = next(
            item for item in report["recommendations"]
            if "previous_24h_largest_change" in item["evidence_ids"]
        )
        self.assertIn("0.010kWh(100.0%)", previous_action["reason"])

    def test_local_report_does_not_invent_action_when_changes_are_flat(self):
        prediction = prediction_payload()
        prediction["predictions_kwh"] = [10.0] * 24
        prediction["history_kwh"] = [10.0] * 24
        prediction["actual_summary"]["total_24h_kwh"] = 240.0
        prediction["same_weekday_baseline"]["values_kwh"] = [10.0] * 24
        prediction["same_weekday_baseline"]["total_kwh"] = 240.0
        for item in prediction["same_weekday_baseline"]["statistics_by_hour"]:
            item.update(
                mean_kwh=10.0,
                variance_kwh2=0.25,
                standard_deviation_kwh=0.5,
                minimum_kwh=9.0,
                maximum_kwh=11.0,
                range_kwh=2.0,
            )
        job = SimpleNamespace(
            selected_model="xgboost",
            validation_metrics={"xgboost": {"mae": 1.0, "wape": 0.1}},
            test_metrics={"xgboost": {"mae": 1.2, "wape": 0.12}},
        )
        report = build_analysis_report(prediction, job)
        self.assertEqual(report["operational_candidates"], [])
        self.assertEqual(report["recommendations"], [])
        self.assertTrue(report["no_action_reason"])
        self.assertNotIn("임의로", report["no_action_reason"])

    def test_missing_key_is_disabled_without_affecting_forecast(self):
        self.assertFalse(analysis_status({})["enabled"])
        with self.assertRaisesRegex(AIAnalysisUnavailable, "OPENAI_API_KEY"):
            analyze_prediction(report_payload(), environ={})

    def test_reasoning_effort_is_reported_and_sent_when_configured(self):
        captured = {}

        def transport(payload, api_key, timeout):
            captured.update(payload=payload, api_key=api_key, timeout=timeout)
            return valid_response()

        environ = {
            "OPENAI_API_KEY": "test-secret",
            "OPENAI_MODEL": "test-model",
            "OPENAI_REASONING_EFFORT": "high",
        }
        status = analysis_status(environ)
        result = analyze_prediction(report_payload(), environ=environ, transport=transport)

        self.assertEqual(status["reasoning_effort"], "high")
        self.assertEqual(captured["payload"]["reasoning"], {"effort": "high"})
        self.assertEqual(result["ai"]["model"], "test-model")

    def test_reasoning_field_is_omitted_when_not_configured(self):
        captured = {}

        def transport(payload, api_key, timeout):
            captured.update(payload=payload, api_key=api_key, timeout=timeout)
            return valid_response()

        analyze_prediction(
            report_payload(),
            environ={"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"},
            transport=transport,
        )

        self.assertNotIn("reasoning", captured["payload"])

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
        self.assertIn("actionable_evidence_ids", serialized)
        self.assertIn("operational_candidates", serialized)
        self.assertEqual(captured["api_key"], "test-secret")
        self.assertEqual(result["source"], "local_quantitative_analysis")
        self.assertEqual(result["ai"]["source"], "openai")
        self.assertEqual(result["ai"]["model"], "test-model")
        self.assertEqual(
            result["recommendations"][0]["evidence_ids"],
            ["same_weekday_largest_deviation"],
        )

    def test_invalid_upstream_shape_is_reported(self):
        with self.assertRaises(AIAnalysisUpstreamError):
            analyze_prediction(
                report_payload(),
                environ={"OPENAI_API_KEY": "test-secret"},
                transport=lambda *_: {"status": "completed", "output": []},
            )

    def test_ai_finding_must_use_actionable_server_evidence(self):
        response = valid_response()
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["findings"][0]["evidence_ids"] = ["forecast_total"]
        response["output"][0]["content"][0]["text"] = json.dumps(value, ensure_ascii=False)
        with self.assertRaisesRegex(AIAnalysisUpstreamError, "조치 후보"):
            analyze_prediction(
                report_payload(),
                environ={"OPENAI_API_KEY": "test-secret"},
                transport=lambda *_: response,
            )

    def test_ai_returns_no_action_when_python_finds_no_candidate(self):
        report = report_payload()
        report["operational_candidates"] = []
        report["recommendations"] = []
        report["no_action_reason"] = "확인된 유의미한 변화가 없습니다."
        response = valid_response()
        value = json.loads(response["output"][0]["content"][0]["text"])
        value["findings"] = []
        value["no_action_reason"] = "확인된 운영 신호가 없어 추가 조치를 권고하지 않습니다."
        response["output"][0]["content"][0]["text"] = json.dumps(value, ensure_ascii=False)
        result = analyze_prediction(
            report,
            environ={"OPENAI_API_KEY": "test-secret"},
            transport=lambda *_: response,
        )
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["no_action_reason"], report["no_action_reason"])
        self.assertIn("권고하지 않습니다", result["ai_no_action_reason"])

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

    def test_manager_limits_paid_calls_then_returns_local_report_without_training(self):
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
            fallback = manager.analyze_prediction("job-a", "local-csv")
            self.assertEqual(fallback["ai"], {
                "status": "fallback",
                "source": "local",
                "reason": "analysis_call_limit",
            })
            self.assertIn("summary", fallback)
        self.assertEqual(len(calls), 3)

    def test_manager_returns_local_report_when_openai_is_rate_limited(self):
        with tempfile.TemporaryDirectory() as temporary:
            error = AIAnalysisUpstreamError(
                "rate limited",
                stage="http_error",
                diagnostics={"http_status": 429, "error_code": "credit_balance_exhausted"},
            )
            def rate_limited(_report):
                raise error
            manager = TrainingJobManager(
                temporary,
                pipeline=lambda *_args, **_kwargs: self.fail("training must not run"),
                ai_analyzer=rate_limited,
            )
            manager._jobs["job-a"] = TrainingJob(
                job_id="job-a", building_id="building-a", status="COMPLETED",
                run_dir="unused", selected_model="xgboost",
                validation_metrics={"xgboost": {"mae": 1.0, "wape": 0.1}},
                test_metrics={"xgboost": {"mae": 1.2, "wape": 0.12}},
            )
            manager.predict = lambda job_id, csv_text: prediction_payload()  # type: ignore[method-assign]
            result = manager.analyze_prediction("job-a", "local-csv")
            self.assertEqual(result["ai"]["status"], "fallback")
            self.assertEqual(result["ai"]["reason"], "upstream_error")
            self.assertEqual(result["ai"]["diagnostics"]["http_status"], 429)
            self.assertEqual(result["summary"], report_payload()["summary"])


if __name__ == "__main__":
    unittest.main()
