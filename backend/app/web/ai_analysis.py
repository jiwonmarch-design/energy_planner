"""Optional OpenAI-powered explanation of already-computed forecasts.

The numerical forecast always comes from the selected local model. This module
sends only a small forecast summary to the Responses API and never receives the
uploaded CSV or trains a model.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from statistics import fmean
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
        "peak_interpretation": {"type": "string"},
        "patterns": {"type": "array", "items": {"type": "string"}},
        "cautions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "peak_interpretation", "patterns", "cautions"],
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
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
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


def _forecast_context(prediction: Mapping[str, Any]) -> dict[str, Any]:
    values = [float(value) for value in prediction.get("predictions_kwh", [])]
    timestamps = [str(value) for value in prediction.get("timestamps", [])]
    history = [float(value) for value in prediction.get("history_kwh", [])]
    if len(values) != 24 or len(timestamps) != 24:
        raise ValueError("AI 분석에는 완전한 24시간 예측이 필요합니다.")
    if not history:
        raise ValueError("AI 분석에는 최근 실측 요약이 필요합니다.")
    peak_index = max(range(24), key=values.__getitem__)
    low_index = min(range(24), key=values.__getitem__)
    periods = []
    for start in range(0, 24, 6):
        segment = values[start : start + 6]
        periods.append(
            {
                "forecast_hours": f"+{start + 1}~+{start + 6}",
                "average_kwh": round(fmean(segment), 4),
            }
        )
    return {
        "forecast_origin": prediction.get("forecast_origin"),
        "model_kind": prediction.get("model_kind"),
        "total_kwh": round(sum(values), 4),
        "average_hourly_kwh": round(fmean(values), 4),
        "peak": {"timestamp": timestamps[peak_index], "kwh": round(values[peak_index], 4)},
        "minimum": {"timestamp": timestamps[low_index], "kwh": round(values[low_index], 4)},
        "recent_history_12h": {
            "count": len(history),
            "average_kwh": round(fmean(history), 4),
            "minimum_kwh": round(min(history), 4),
            "maximum_kwh": round(max(history), 4),
        },
        "six_hour_periods": periods,
        "hourly_forecast": [
            {"timestamp": timestamp, "kwh": round(value, 4)}
            for timestamp, value in zip(timestamps, values, strict=True)
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
    if set(value) != set(ANALYSIS_SCHEMA["required"]):
        raise AIAnalysisUpstreamError("OpenAI API 분석 결과의 필드가 올바르지 않습니다.")
    if not isinstance(value["summary"], str) or not isinstance(value["peak_interpretation"], str):
        raise AIAnalysisUpstreamError("OpenAI API 분석 문구의 형식이 올바르지 않습니다.")
    if not all(isinstance(item, str) for item in value["patterns"] + value["cautions"]):
        raise AIAnalysisUpstreamError("OpenAI API 분석 목록의 형식이 올바르지 않습니다.")
    return value


def analyze_prediction(
    prediction: Mapping[str, Any],
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
    context = _forecast_context(prediction)
    prompt = (
        "다음 JSON은 건물 전력 예측 모델이 만든 관측 가능한 수치입니다. "
        "제공된 수치만 사용해 한국어로 설명하세요. 날씨, 설비 가동, 요금제, 원인처럼 "
        "제공되지 않은 사실은 단정하지 마세요. 관찰과 가능한 해석을 분리하고, "
        "예측은 불확실하다는 주의사항을 포함하세요.\n\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )
    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": 700,
        "input": [
            {
                "role": "system",
                "content": "전력 예측 수치를 과장 없이 설명하는 데이터 분석가입니다.",
            },
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "energy_forecast_analysis",
                "strict": True,
                "schema": ANALYSIS_SCHEMA,
            }
        },
    }
    response = (transport or _request_openai)(payload, api_key, _safe_timeout(values))
    analysis = _parse_structured_response(response)
    return {
        **analysis,
        "model": model,
        "source": "openai",
        "forecast_run_id": prediction.get("run_id"),
    }
