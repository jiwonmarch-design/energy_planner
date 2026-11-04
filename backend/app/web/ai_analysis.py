"""Optional OpenAI narrative for a locally calculated forecast report.

The numerical forecast and every displayed fact are computed by Python. This
module sends only structured aggregates to the Responses API; it never receives
the uploaded CSV, API key, or a prompt that asks it to calculate a value.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o-mini"


class AIAnalysisUnavailable(RuntimeError):
    """The optional analysis feature is not configured."""


class AIAnalysisUpstreamError(RuntimeError):
    """The optional upstream analysis request failed or returned invalid data."""


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "peak_analysis": {"type": "string"},
        "comparison": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "caveat": {"type": "string"},
                },
                "required": ["title", "action", "reason", "evidence_ids", "caveat"],
                "additionalProperties": False,
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
        "model_quality": {"type": "string"},
    },
    "required": [
        "summary",
        "peak_analysis",
        "comparison",
        "recommendations",
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
    }


def _safe_timeout(values: Mapping[str, str]) -> float:
    try:
        configured = float(values.get("OPENAI_TIMEOUT_SECONDS", "20"))
    except ValueError:
        configured = 20.0
    return min(60.0, max(3.0, configured))


def _request_openai(payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AIAnalysisUpstreamError(
            f"OpenAI API 요청이 거부되었습니다(HTTP {exc.code}). 키와 사용 한도를 확인하세요."
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AIAnalysisUpstreamError(
            "OpenAI API에 연결하지 못했습니다. 잠시 후 다시 시도하세요."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AIAnalysisUpstreamError("OpenAI API 응답을 해석하지 못했습니다.") from exc


def _report_context(report: Mapping[str, Any]) -> dict[str, Any]:
    chart = report.get("chart", {})
    timestamps = chart.get("timestamps", [])
    forecast = chart.get("forecast_kwh", [])
    baseline = chart.get("same_weekday_baseline_kwh", [])
    if len(timestamps) != 24 or len(forecast) != 24:
        raise ValueError("AI 분석에는 완전한 24시간 정량 보고서가 필요합니다.")
    evidence = report.get("evidence", [])
    return {
        "metadata": report.get("metadata"),
        "quantitative": report.get("quantitative"),
        "evidence": evidence,
        "allowed_evidence_ids": [item.get("id") for item in evidence],
        "peak_analysis": report.get("peak_analysis"),
        "comparison": report.get("comparison"),
        "model_quality": report.get("model_quality"),
        "hourly_comparison": [
            {
                "timestamp": timestamp,
                "forecast_kwh": value,
                "same_weekday_baseline_kwh": baseline[index] if len(baseline) == 24 else None,
            }
            for index, (timestamp, value) in enumerate(zip(timestamps, forecast, strict=True))
        ],
    }


def _parse_structured_response(response: Mapping[str, Any]) -> dict[str, Any]:
    if response.get("status") not in {None, "completed"}:
        raise AIAnalysisUpstreamError("OpenAI API가 분석을 완료하지 못했습니다.")
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
    scalar_fields = ("summary", "peak_analysis", "comparison", "model_quality")
    if not all(isinstance(value[field], str) for field in scalar_fields):
        raise AIAnalysisUpstreamError("OpenAI API 분석 문구의 형식이 올바르지 않습니다.")
    if not isinstance(value["limitations"], list) or not all(
        isinstance(item, str) for item in value["limitations"]
    ):
        raise AIAnalysisUpstreamError("OpenAI API 분석 목록의 형식이 올바르지 않습니다.")
    if not isinstance(value["recommendations"], list) or len(value["recommendations"]) > 3:
        raise AIAnalysisUpstreamError("OpenAI API 권고 목록은 최대 3개여야 합니다.")
    fields = {"title", "action", "reason", "evidence_ids", "caveat"}
    for item in value["recommendations"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise AIAnalysisUpstreamError("OpenAI API 권고 형식이 올바르지 않습니다.")
        if not all(isinstance(item[field], str) for field in fields - {"evidence_ids"}):
            raise AIAnalysisUpstreamError("OpenAI API 권고 문구의 형식이 올바르지 않습니다.")
        if not isinstance(item["evidence_ids"], list) or not all(
            isinstance(evidence_id, str) for evidence_id in item["evidence_ids"]
        ):
            raise AIAnalysisUpstreamError("OpenAI API 권고 근거의 형식이 올바르지 않습니다.")
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
    prompt = (
        "다음 JSON은 서버가 계산한 건물 전력 예측의 구조화된 정량 결과입니다. "
        "숫자를 새로 계산하거나 추정하지 말고, 제공된 evidence의 id만 근거로 사용하세요. "
        "문장에는 새로운 금액·비율·정확도·피크 수치를 만들지 마세요. "
        "수치 정보는 화면의 서버 근거가 별도로 표시하므로 문장에는 아라비아 숫자를 전혀 쓰지 마세요. "
        "설비별 데이터가 없으므로 특정 설비나 원인을 단정하지 말고 절약을 보장하지 마세요. "
        "실행 권고는 중요도 순 최대 3개로 작성하고 evidence_ids에는 allowed_evidence_ids만 넣으세요. "
        "확인할 수 없는 내용은 limitations에 명시하세요. 모든 문장은 한국어로 작성하세요.\n\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )
    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": 1200,
        "input": [
            {
                "role": "system",
                "content": "제공된 근거 ID만 인용하고 수치를 재계산하지 않는 전력 운영 분석가입니다.",
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
    response = (transport or _request_openai)(payload, api_key, _safe_timeout(values))
    analysis = _parse_structured_response(response)
    for item in analysis["recommendations"]:
        if not set(item["evidence_ids"]).issubset(allowed_evidence_ids):
            raise AIAnalysisUpstreamError("OpenAI API 권고에 확인되지 않은 근거가 포함되었습니다.")

    contains_number = lambda text: bool(re.search(r"[0-9０-９]", text))
    filtered_numeric = any(
        contains_number(text)
        for text in [
            analysis["summary"],
            analysis["peak_analysis"],
            analysis["comparison"],
            analysis["model_quality"],
            *analysis["limitations"],
            *(
                item[field]
                for item in analysis["recommendations"]
                for field in ("title", "action", "reason", "caveat")
            ),
        ]
    )
    safe_limitations = [item for item in analysis["limitations"] if not contains_number(item)]
    limitations = list(dict.fromkeys([*report.get("limitations", []), *safe_limitations]))
    safe_recommendations = [
        item
        for item in analysis["recommendations"]
        if not any(contains_number(item[field]) for field in ("title", "action", "reason", "caveat"))
    ]
    recommendations = [
        {**item, "priority": index + 1}
        for index, item in enumerate(safe_recommendations[:3])
    ]
    return {
        **report,
        "summary": analysis["summary"] if not contains_number(analysis["summary"]) else report["summary"],
        "peak_analysis": {
            **report.get("peak_analysis", {}),
            "ai_interpretation": (
                analysis["peak_analysis"]
                if not contains_number(analysis["peak_analysis"])
                else report.get("peak_analysis", {}).get("finding")
            ),
        },
        "comparison": {
            **report.get("comparison", {}),
            "ai_interpretation": (
                analysis["comparison"]
                if not contains_number(analysis["comparison"])
                else report.get("comparison", {}).get("finding")
            ),
        },
        "recommendations": recommendations or report.get("recommendations", []),
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
