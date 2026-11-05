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
        "당신은 일반적인 절전 조언자가 아니라 전력 운영 의사결정 분석가입니다. "
        "운영 관찰과 조치 권고를 구분하세요. summary, peak_analysis, comparison은 운영 관찰입니다. "
        "관찰에는 allowed_evidence_ids의 전일 대비·동일 요일 대비·시간별 변동 범위를 사용할 수 있습니다. "
        "각 관찰의 근거 ID를 observation_evidence_ids의 같은 이름 필드에 넣으세요. 근거가 없으면 판단 보류를 명시하세요. "
        "summary는 운영 판단의 이유를 간결하게 설명하고, 비교 기준이 다른 두 증감률을 함께 해석하세요. "
        "감소 자체를 이상이나 절감 효과로 단정하지 마세요. peak_analysis는 historical_context와 observation을 따르고, "
        "피크 시각이 평소에도 높은 시간이라는 주장은 과거 표본·평균 순위만으로 확정하지 마세요. "
        "comparison은 직전 실측과 동일 요일 기준의 차이를 설명하세요. 관찰 문장에 실행 조치를 권고하지 마세요. "
        "숫자를 새로 계산하거나 추정하지 말고 조치 권고인 findings는 Python이 만든 operational_candidates만 검토하세요. "
        "문장에는 새로운 금액·비율·정확도·피크 수치를 만들지 마세요. "
        "수치 정보는 화면의 서버 근거가 별도로 표시하므로 문장에는 아라비아 숫자를 전혀 쓰지 마세요. "
        "설비별 데이터가 없으므로 특정 설비·원인·절감 효과·비용을 단정하거나 보장하지 마세요. "
        "findings는 중요도 순 최대 세 개이며 각 항목에 정량 근거 ID, 운영상 의미, 확인 또는 실행할 조치, 한계를 포함하세요. "
        "findings의 evidence_ids에는 actionable_evidence_ids만 넣고 최소 한 개의 근거를 사용하세요. "
        "operational_candidates가 비어 있거나 의미 있는 변화가 없으면 findings를 빈 배열로 두고 no_action_reason에 불필요한 조치를 권고하지 않는 이유를 작성하세요. "
        "후보가 없어도 근거 있는 운영 관찰은 작성하세요. 추가 조치 없음 문구를 summary와 no_action_reason에서 반복하지 마세요. "
        "실제 요금제가 없으므로 경제적 효과를 확정적으로 표현하지 마세요. "
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
                "content": "서버가 확인한 운영 신호만 선별하고 일반론을 배제하는 전력 운영 의사결정 분석가입니다.",
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
    response = (transport or _request_openai)(payload, api_key, _safe_timeout(values))
    analysis = _parse_structured_response(response)
    for field, evidence_ids in analysis["observation_evidence_ids"].items():
        if not set(evidence_ids).issubset(allowed_evidence_ids):
            raise AIAnalysisUpstreamError("OpenAI API 운영 관찰에 확인되지 않은 근거가 포함되었습니다.")
        if not evidence_ids:
            # An uncited interpretation falls back to the local observation.
            analysis[field] = ""
    for item in analysis["findings"]:
        evidence_ids = set(item["evidence_ids"])
        if not evidence_ids or not evidence_ids.issubset(actionable_evidence_ids):
            raise AIAnalysisUpstreamError("OpenAI API 핵심 발견에 조치 후보가 아닌 근거가 포함되었습니다.")
        if not evidence_ids.issubset(allowed_evidence_ids):
            raise AIAnalysisUpstreamError("OpenAI API 핵심 발견에 확인되지 않은 근거가 포함되었습니다.")

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
    limitations = list(dict.fromkeys([*report.get("limitations", []), *safe_limitations]))
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
    recommendations = [
        {
            "priority": index + 1,
            "title": item["title"],
            "action": item["recommended_action"],
            "reason": item["operational_meaning"],
            "evidence_ids": item["evidence_ids"],
            "caveat": item["limitation"],
        }
        for index, item in enumerate(safe_findings[:3])
    ]
    local_recommendations = report.get("recommendations", [])
    if not recommendations and actionable_evidence_ids:
        recommendations = local_recommendations
    safe_no_action_reason = (
        analysis["no_action_reason"]
        if not contains_number(analysis["no_action_reason"])
        else report.get("no_action_reason", "")
    )
    return {
        **report,
        "summary": analysis["summary"] if analysis["summary"].strip() and not contains_number(analysis["summary"]) else report["summary"],
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
        "recommendations": recommendations or report.get("recommendations", []),
        "ai_findings": safe_findings,
        "no_action_reason": (
            "" if recommendations else safe_no_action_reason or report.get("no_action_reason", "")
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
