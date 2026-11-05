"""Optional OpenAI narrative for a locally calculated forecast report.

The numerical forecast and every displayed fact are computed by Python. This
module sends only structured aggregates to the Responses API; it never receives
the uploaded CSV, API key, or a prompt that asks it to calculate a value.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_OUTPUT_TOKENS = 1200
LOGGER = logging.getLogger(__name__)


class AIAnalysisUnavailable(RuntimeError):
    """The optional analysis feature is not configured."""


class AIAnalysisUpstreamError(RuntimeError):
    """The optional upstream analysis request failed or returned invalid data."""

    def __init__(self, message: str, *, stage: str = "response_parse", diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = {"stage": stage, **(diagnostics or {})}


def _response_diagnostics(response: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlisted metadata only: never retain prompts, output text or headers."""
    status = response.get("status")
    details = response.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, Mapping) else None
    error = response.get("error")
    code = error.get("code") if isinstance(error, Mapping) else None
    known_codes = {
        "server_error", "rate_limit_exceeded", "invalid_prompt", "invalid_api_key",
        "insufficient_quota", "model_not_found", "context_length_exceeded",
        "invalid_value", "unsupported_value", "permission_denied", "content_policy_violation",
    }
    diagnostics = {
        "response_status": status if status in {None, "completed", "incomplete", "failed", "cancelled", "queued", "in_progress"} else "unknown",
        "incomplete_reason": reason if reason in {None, "max_output_tokens", "content_filter"} else "unknown",
        "error_code": code if code is None or code in known_codes else "unknown",
    }
    usage = response.get("usage")
    if isinstance(usage, Mapping):
        for name in ("input_tokens", "output_tokens"):
            count = usage.get(name)
            if isinstance(count, int) and count >= 0:
                diagnostics[name] = count
        output_details = usage.get("output_tokens_details")
        count = output_details.get("reasoning_tokens") if isinstance(output_details, Mapping) else None
        if isinstance(count, int) and count >= 0:
            diagnostics["reasoning_tokens"] = count
    http_status = response.get("_http_status")
    if isinstance(http_status, int) and 100 <= http_status <= 599:
        diagnostics["http_status"] = http_status
    return diagnostics


def _limitation_categories(text: str) -> set[str]:
    categories = (
        ("equipment", ("설비", "원인")),
        ("cost", ("요금", "비용", "절감 금액", "절감액")),
        ("power", ("최대수요전력", "kW")),
        ("history", ("같은 요일", "과거 표본", "비교 자료")),
        ("historical_report", ("과거 데이터 검증", "운영 계획")),
        ("accuracy", ("검증 결과", "오차율", "정확")),
    )
    matches = {
        name for name, keywords in categories
        if any(keyword in text for keyword in keywords)
    }
    return matches or {re.sub(r"\s+", " ", text).strip()}


def _deduplicate_limitations(items: list[str]) -> list[str]:
    result: list[str] = []
    seen_categories: set[str] = set()
    for item in items:
        categories = _limitation_categories(item)
        if not item.strip() or categories & seen_categories:
            continue
        seen_categories.update(categories)
        result.append(item)
    return result


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "peak_analysis": {"type": "string"},
        "comparison": {"type": "string"},
        "observation_evidence_ids": {
            "type": "object",
            "properties": {
                field: {"type": "array", "items": {"type": "string"}}
                for field in ("summary", "peak_analysis", "comparison")
            },
            "required": ["summary", "peak_analysis", "comparison"],
            "additionalProperties": False,
        },
        "findings": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "operational_meaning": {"type": "string"},
                    "recommended_action": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "limitation": {"type": "string"},
                },
                "required": [
                    "title",
                    "operational_meaning",
                    "recommended_action",
                    "evidence_ids",
                    "limitation",
                ],
                "additionalProperties": False,
            },
        },
        "no_action_reason": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "model_quality": {"type": "string"},
    },
    "required": [
        "summary",
        "peak_analysis",
        "comparison",
        "observation_evidence_ids",
        "findings",
        "no_action_reason",
        "limitations",
        "model_quality",
    ],
    "additionalProperties": False,
}


def analysis_status(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if environ is None else environ
    enabled = bool(values.get("OPENAI_API_KEY", "").strip())
    return {
        "enabled": enabled,
        "model": values.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "reasoning_effort": values.get("OPENAI_REASONING_EFFORT", "").strip() or None,
        "max_output_tokens": _safe_max_output_tokens(values),
        "timeout_seconds": _safe_timeout(values),
    }


def _safe_timeout(values: Mapping[str, str]) -> float:
    try:
        configured = float(values.get("OPENAI_TIMEOUT_SECONDS", "20"))
    except ValueError:
        configured = 20.0
    return min(60.0, max(3.0, configured))


def _safe_max_output_tokens(values: Mapping[str, str]) -> int:
    """Budget includes reasoning and visible JSON; preserve legacy defaults."""
    try:
        configured = int(values.get("OPENAI_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
    except ValueError:
        configured = DEFAULT_MAX_OUTPUT_TOKENS
    return min(16384, max(1200, configured))


def _transport_diagnostics(exc: BaseException, timeout: float) -> dict[str, Any]:
    """Classify transport failures without retaining exception text or secrets."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, TimeoutError):
        category = "timeout"
    elif isinstance(reason, ssl.SSLError):
        category = "tls"
    elif isinstance(reason, socket.gaierror):
        category = "dns"
    elif isinstance(reason, (ConnectionError, OSError)):
        category = "connection"
    else:
        category = "unknown"
    return {"transport_reason": category, "timeout_seconds": timeout}


def _request_openai(payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise AIAnalysisUpstreamError("OpenAI API 응답 형식이 올바르지 않습니다.", stage="response_decode")
            value["_http_status"] = response.status
            return value
    except urllib.error.HTTPError as exc:
        try:
            error_response = json.loads(exc.read(8192).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_response = {}
        diagnostics = _response_diagnostics(error_response if isinstance(error_response, dict) else {})
        diagnostics["http_status"] = exc.code
        raise AIAnalysisUpstreamError(
            f"OpenAI API 요청이 거부되었습니다(HTTP {exc.code}, code={diagnostics['error_code'] or 'unknown'}).",
            stage="http_error", diagnostics=diagnostics,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        diagnostics = _transport_diagnostics(exc, timeout)
        message = (
            f"OpenAI API가 {timeout:g}초 안에 응답하지 않았습니다. 잠시 후 다시 시도하세요."
            if diagnostics["transport_reason"] == "timeout"
            else "OpenAI API에 연결하지 못했습니다. 잠시 후 다시 시도하세요."
        )
        raise AIAnalysisUpstreamError(
            message, stage="transport", diagnostics=diagnostics,
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIAnalysisUpstreamError("OpenAI API 응답을 해석하지 못했습니다.", stage="response_decode") from exc


def _report_context(report: Mapping[str, Any]) -> dict[str, Any]:
    chart = report.get("chart", {})
    timestamps = chart.get("timestamps", [])
    forecast = chart.get("forecast_kwh", [])
    baseline = chart.get("same_weekday_baseline_kwh", [])
    if len(timestamps) != 24 or len(forecast) != 24:
        raise ValueError("AI 분석에는 완전한 24시간 정량 보고서가 필요합니다.")
    evidence = report.get("evidence", [])
    operational_candidates = report.get("operational_candidates", [])
    actionable_evidence_ids = list(
        dict.fromkeys(
            evidence_id
            for candidate in operational_candidates
            for evidence_id in candidate.get("evidence_ids", [])
        )
    )
    return {
        "metadata": report.get("metadata"),
        "quantitative": report.get("quantitative"),
        "evidence": evidence,
        "allowed_evidence_ids": [item.get("id") for item in evidence],
        "actionable_evidence_ids": actionable_evidence_ids,
        "peak_analysis": report.get("peak_analysis"),
        "comparison": report.get("comparison"),
        "previous_24h_comparison": report.get("previous_24h_comparison"),
        "model_quality": report.get("model_quality"),
        "operational_candidates": operational_candidates,
        "no_action_reason": report.get("no_action_reason"),
        "observation_evidence_ids": report.get("observation_evidence_ids"),
        "hourly_comparison": [
            {
                "timestamp": timestamp,
                "forecast_kwh": value,
                "same_weekday_baseline_kwh": baseline[index] if len(baseline) == 24 else None,
                "difference_kwh": (
                    report.get("comparison", {}).get("hourly_differences", [])[index].get("difference_kwh")
                    if len(report.get("comparison", {}).get("hourly_differences", [])) == 24
                    else None
                ),
                "difference_percent": (
                    report.get("comparison", {}).get("hourly_differences", [])[index].get("difference_percent")
                    if len(report.get("comparison", {}).get("hourly_differences", [])) == 24
                    else None
                ),
            }
            for index, (timestamp, value) in enumerate(zip(timestamps, forecast, strict=True))
        ],
    }


def _parse_structured_response(response: Mapping[str, Any]) -> dict[str, Any]:
    if response.get("status") not in {None, "completed"}:
        diagnostics = _response_diagnostics(response)
        detail = f"status={diagnostics['response_status']}, reason={diagnostics['incomplete_reason'] or 'unknown'}"
        explanation = (
            "추론과 답변이 출력 토큰 한도에 도달했습니다."
            if diagnostics["incomplete_reason"] == "max_output_tokens"
            else "완료되지 않은 응답은 보고서로 사용하지 않습니다."
        )
        raise AIAnalysisUpstreamError(
            f"OpenAI API가 분석을 완료하지 못했습니다({detail}). {explanation}",
            stage="response_status", diagnostics=diagnostics,
        )
    text: str | None = None
    for output in response.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "refusal":
                raise AIAnalysisUpstreamError("OpenAI API가 분석 요청을 처리하지 않았습니다.")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                text = content["text"]
                break
        if text is not None:
            break
    if text is None:
        raise AIAnalysisUpstreamError("OpenAI API 응답에 분석 결과가 없습니다.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIAnalysisUpstreamError("OpenAI API 분석 결과가 올바른 JSON이 아닙니다.") from exc
    if not isinstance(value, dict) or set(value) != set(ANALYSIS_SCHEMA["required"]):
        raise AIAnalysisUpstreamError("OpenAI API 분석 결과의 필드가 올바르지 않습니다.")
    scalar_fields = (
        "summary",
        "peak_analysis",
        "comparison",
        "no_action_reason",
        "model_quality",
    )
    if not all(isinstance(value[field], str) for field in scalar_fields):
        raise AIAnalysisUpstreamError("OpenAI API 분석 문구의 형식이 올바르지 않습니다.")
    observations = value["observation_evidence_ids"]
    if not isinstance(observations, dict) or set(observations) != {"summary", "peak_analysis", "comparison"}:
        raise AIAnalysisUpstreamError("OpenAI API 운영 관찰 근거의 형식이 올바르지 않습니다.")
    for ids in observations.values():
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise AIAnalysisUpstreamError("OpenAI API 운영 관찰 근거의 형식이 올바르지 않습니다.")
    if not isinstance(value["limitations"], list) or not all(
        isinstance(item, str) for item in value["limitations"]
    ):
        raise AIAnalysisUpstreamError("OpenAI API 분석 목록의 형식이 올바르지 않습니다.")
    if not isinstance(value["findings"], list) or len(value["findings"]) > 3:
        raise AIAnalysisUpstreamError("OpenAI API 핵심 발견 목록은 최대 3개여야 합니다.")
    fields = {
        "title",
        "operational_meaning",
        "recommended_action",
        "evidence_ids",
        "limitation",
    }
    for item in value["findings"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise AIAnalysisUpstreamError("OpenAI API 핵심 발견 형식이 올바르지 않습니다.")
        if not all(isinstance(item[field], str) for field in fields - {"evidence_ids"}):
            raise AIAnalysisUpstreamError("OpenAI API 핵심 발견 문구의 형식이 올바르지 않습니다.")
        if not isinstance(item["evidence_ids"], list) or not all(
            isinstance(evidence_id, str) for evidence_id in item["evidence_ids"]
        ):
            raise AIAnalysisUpstreamError("OpenAI API 핵심 발견 근거의 형식이 올바르지 않습니다.")
    return value


def analyze_prediction(
    report: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    transport: Callable[[dict[str, Any], str, float], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    values = os.environ if environ is None else environ
    api_key = values.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIAnalysisUnavailable(
            "OPENAI_API_KEY가 설정되지 않아 AI 분석을 사용할 수 없습니다. 기본 예측은 정상적으로 사용할 수 있습니다."
        )
    model = values.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    context = _report_context(report)
    allowed_evidence_ids = set(context["allowed_evidence_ids"])
    actionable_evidence_ids = set(context["actionable_evidence_ids"])
    prompt = (
        "다음 JSON은 서버가 계산한 건물 전력 예측의 구조화된 정량 결과입니다. "
        "당신은 비개발자가 빠르게 읽는 사내 전력 운영 보고서를 작성합니다. "
        "결론을 문장 첫 부분에 두고 한 문장에는 하나의 판단만 쓰세요. "
        "수치의 계산과 표시는 서버가 담당하므로, 당신은 수치가 업무상 무엇을 뜻하는지만 쉬운 말로 설명하세요. "
        "운영 관찰과 조치 권고를 구분하세요. summary, peak_analysis, comparison은 운영 관찰입니다. "
        "관찰에는 allowed_evidence_ids의 전일 대비·동일 요일 대비·시간별 변동 범위를 사용할 수 있습니다. "
        "각 관찰의 근거 ID를 observation_evidence_ids의 같은 이름 필드에 넣으세요. 근거가 없으면 추정하지 말고 limitations에 한 번만 적으세요. "
        "summary는 운영 판단의 이유를 간결하게 설명하고, 비교 기준이 다른 두 증감률을 함께 해석하세요. "
        "감소 자체를 이상이나 절감 효과로 단정하지 마세요. 변화율이 커 보여도 서버가 제공한 절대 변화량을 함께 고려해 과장하지 마세요. "
        "peak_analysis는 historical_context와 observation을 따르고, "
        "피크 시각이 평소에도 높은 시간이라는 주장은 과거 표본·평균 순위만으로 확정하지 마세요. "
        "comparison은 어제 같은 시간대와 최근 8주 같은 요일 평균의 차이를 설명하세요. 관찰 문장에 실행 조치를 권고하지 마세요. "
        "숫자를 새로 계산하거나 추정하지 말고 조치 권고인 findings는 Python이 만든 operational_candidates만 검토하세요. "
        "문장에는 새로운 금액·비율·정확도·피크 수치를 만들지 마세요. "
        "수치 정보는 화면의 서버 근거가 별도로 표시하므로 문장에는 아라비아 숫자를 전혀 쓰지 마세요. "
        "설비별 데이터가 없으므로 특정 설비·원인·절감 효과·비용을 단정하거나 보장하지 마세요. "
        "findings는 중요도 순 최대 세 개이며 각 항목에 정량 근거 ID, 운영상 의미, 확인 또는 실행할 조치, 한계를 포함하세요. "
        "findings의 evidence_ids에는 actionable_evidence_ids만 넣고 최소 한 개의 근거를 사용하세요. "
        "operational_candidates가 비어 있거나 의미 있는 변화가 없으면 findings를 빈 배열로 두고 no_action_reason에 불필요한 조치를 권고하지 않는 이유를 작성하세요. "
        "후보가 없어도 근거 있는 운영 관찰은 작성하세요. 추가 조치 없음 문구를 summary와 no_action_reason에서 반복하지 마세요. "
        "'직전 실측 기간' 대신 '어제 같은 시간대', '과거 동일 요일·시간 평균' 대신 '최근 8주 같은 요일 평균', "
        "'과거 관측 범위 안' 대신 '평소 사용 범위 안', '사후 실측이 확보되면' 대신 '실제 사용량이 나온 뒤', "
        "'연속 고사용 구간' 대신 '사용량이 계속 높은 시간대'라고 쓰세요. "
        "Validation, Test, WAPE, 기준모델 같은 개발 용어는 본문에 쓰지 마세요. "
        "'단정할 수 없습니다'를 여러 항목에서 반복하지 말고 확인할 수 없는 내용은 limitations에 모으세요. "
        "실제 요금제가 없으므로 경제적 효과를 확정적으로 표현하지 마세요. "
        "확인할 수 없는 내용은 limitations에 명시하세요. 모든 문장은 한국어로 작성하세요.\n\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )
    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": _safe_max_output_tokens(values),
        "input": [
            {
                "role": "system",
                "content": "서버가 확인한 근거만 사용해 비개발자를 위한 간결한 전력 운영 업무 보고서를 작성합니다.",
            },
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "energy_operations_report",
                "strict": True,
                "schema": ANALYSIS_SCHEMA,
            }
        },
    }
    reasoning_effort = values.get("OPENAI_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    response = None
    try:
        response = (transport or _request_openai)(payload, api_key, _safe_timeout(values))
        analysis = _parse_structured_response(response)
    except AIAnalysisUpstreamError as exc:
        if isinstance(response, Mapping):
            exc.diagnostics = {**_response_diagnostics(response), **exc.diagnostics}
        # This log deliberately excludes report data, response text and auth.
        LOGGER.warning("OpenAI analysis failed: %s", json.dumps({
            **exc.diagnostics,
            "max_output_tokens": payload["max_output_tokens"],
            "reasoning_effort": reasoning_effort if reasoning_effort in {"", "none", "minimal", "low", "medium", "high", "xhigh"} else "unknown",
        }, ensure_ascii=True))
        raise
    for field, evidence_ids in analysis["observation_evidence_ids"].items():
        if not set(evidence_ids).issubset(allowed_evidence_ids):
            raise AIAnalysisUpstreamError(
                "OpenAI API 운영 관찰에 확인되지 않은 근거가 포함되었습니다.",
                stage="observation_evidence", diagnostics={
                    **_response_diagnostics(response), "field": field,
                    "rejected_evidence_count": len(set(evidence_ids) - allowed_evidence_ids),
                },
            )
        if not evidence_ids:
            # An uncited interpretation falls back to the local observation.
            analysis[field] = ""
    for item in analysis["findings"]:
        evidence_ids = set(item["evidence_ids"])
        if not evidence_ids or not evidence_ids.issubset(actionable_evidence_ids):
            raise AIAnalysisUpstreamError(
                "OpenAI API 핵심 발견에 조치 후보가 아닌 근거가 포함되었습니다.", stage="actionable_evidence",
                diagnostics={**_response_diagnostics(response), "rejected_evidence_count": len(evidence_ids - actionable_evidence_ids)},
            )
        if not evidence_ids.issubset(allowed_evidence_ids):
            raise AIAnalysisUpstreamError(
                "OpenAI API 핵심 발견에 확인되지 않은 근거가 포함되었습니다.", stage="allowed_evidence",
                diagnostics=_response_diagnostics(response),
            )

    contains_number = lambda text: bool(re.search(r"[0-9０-９]", text))
    filtered_numeric = any(
        contains_number(text)
        for text in [
            analysis["summary"],
            analysis["peak_analysis"],
            analysis["comparison"],
            analysis["no_action_reason"],
            analysis["model_quality"],
            *analysis["limitations"],
            *(
                item[field]
                for item in analysis["findings"]
                for field in (
                    "title",
                    "operational_meaning",
                    "recommended_action",
                    "limitation",
                )
            ),
        ]
    )
    safe_limitations = [item for item in analysis["limitations"] if not contains_number(item)]
    limitations = _deduplicate_limitations(
        [*report.get("limitations", []), *safe_limitations]
    )
    safe_findings = [
        item
        for item in analysis["findings"]
        if not any(
            contains_number(item[field])
            for field in (
                "title",
                "operational_meaning",
                "recommended_action",
                "limitation",
            )
        )
    ]
    local_recommendations = report.get("recommendations", [])
    return {
        **report,
        # The server owns every visible numerical sentence. AI text is optional
        # supporting interpretation and can never replace those facts.
        "summary_ai_interpretation": (
            analysis["summary"]
            if analysis["summary"].strip() and not contains_number(analysis["summary"])
            else ""
        ),
        "observation_evidence_ids": {
            field: ids if analysis[field].strip() and not contains_number(analysis[field])
            else report.get("observation_evidence_ids", {}).get(field, [])
            for field, ids in analysis["observation_evidence_ids"].items()
        },
        "peak_analysis": {
            **report.get("peak_analysis", {}),
            "ai_interpretation": (
                analysis["peak_analysis"]
                if analysis["peak_analysis"].strip() and not contains_number(analysis["peak_analysis"])
                else ""
            ),
        },
        "comparison": {
            **report.get("comparison", {}),
            "ai_interpretation": (
                analysis["comparison"]
                if analysis["comparison"].strip() and not contains_number(analysis["comparison"])
                else ""
            ),
        },
        "recommendations": local_recommendations,
        "ai_findings": safe_findings,
        "no_action_reason": (
            "" if local_recommendations else report.get("no_action_reason", "")
        ),
        "ai_no_action_reason": (
            analysis["no_action_reason"]
            if not contains_number(analysis["no_action_reason"])
            else ""
        ),
        "limitations": limitations,
        "model_quality": {
            **report.get("model_quality", {}),
            "ai_interpretation": (
                analysis["model_quality"]
                if not contains_number(analysis["model_quality"])
                else report.get("model_quality", {}).get("note")
            ),
        },
        "ai": {
            "status": "completed",
            "model": model,
            "source": "openai",
            "numeric_filter_applied": filtered_numeric,
        },
    }
