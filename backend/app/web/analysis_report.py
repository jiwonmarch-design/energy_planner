"""Deterministic, privacy-preserving analysis for a completed forecast.

All numerical facts in the report are calculated locally.  The optional LLM
layer may rewrite the narrative, but it is never asked to calculate a value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _metric(metrics: Mapping[str, Any] | None, model: str | None) -> dict[str, float | None]:
    value = (metrics or {}).get(model or "", {})
    return {
        "mae": _number(value.get("mae")),
        "wape": _number(value.get("wape")),
    }


def _pct_change(current: float, reference: float | None) -> float | None:
    if reference is None or reference <= 0:
        return None
    return (current - reference) / reference * 100.0


def build_analysis_report(prediction: Mapping[str, Any], job: Any) -> dict[str, Any]:
    """Build a report from local prediction/job facts without any AI call."""
    values = [float(value) for value in prediction.get("predictions_kwh", [])]
    timestamps = [str(value) for value in prediction.get("timestamps", [])]
    if len(values) != 24 or len(timestamps) != 24:
        raise ValueError("분석 보고서에는 24개 시간대의 예측 결과가 필요합니다.")

    total = float(sum(values))
    average = total / len(values)
    peak_index = max(range(len(values)), key=values.__getitem__)
    previous_total = _number(prediction.get("actual_summary", {}).get("total_24h_kwh"))
    previous_change = _pct_change(total, previous_total)
    baseline = dict(prediction.get("same_weekday_baseline") or {})
    baseline_values = baseline.get("values_kwh") or []
    baseline_available = baseline.get("status") == "available" and len(baseline_values) == 24
    baseline_total = _number(baseline.get("total_kwh")) if baseline_available else None
    baseline_change = _pct_change(total, baseline_total)

    selected_model = getattr(job, "selected_model", None)
    validation_metrics = getattr(job, "validation_metrics", None) or {}
    test_metrics = getattr(job, "test_metrics", None) or {}
    selected_validation = _metric(validation_metrics, selected_model)
    selected_test = _metric(test_metrics, selected_model)

    baseline_models: dict[str, dict[str, float | None]] = {}
    for name in ("last_24h", "last_168h"):
        if name in validation_metrics:
            baseline_models[name] = _metric(validation_metrics, name)
    baseline_maes = [item["mae"] for item in baseline_models.values() if item["mae"] is not None]
    best_baseline_mae = min(baseline_maes) if baseline_maes else None
    validation_improvement = None
    if selected_validation["mae"] is not None and best_baseline_mae and best_baseline_mae > 0:
        validation_improvement = (best_baseline_mae - selected_validation["mae"]) / best_baseline_mae * 100.0

    evidence: list[dict[str, Any]] = [
        {
            "id": "forecast_total",
            "label": "24시간 예상 사용량",
            "value": total,
            "unit": "kWh",
            "basis": "저장된 모델의 24개 시간별 예측값 합계",
        },
        {
            "id": "forecast_peak",
            "label": "예상 피크",
            "value": values[peak_index],
            "unit": "kWh",
            "timestamp": timestamps[peak_index],
            "basis": "24개 예측값 중 최댓값",
        },
    ]
    if previous_total is not None:
        evidence.append(
            {
                "id": "previous_24h_comparison",
                "label": "직전 24시간 대비",
                "value": previous_change,
                "unit": "%",
                "reference_value": previous_total,
                "reference_unit": "kWh",
                "basis": "업로드 데이터의 마지막 24시간 실측 합계와 비교",
            }
        )
    if baseline_available:
        evidence.append(
            {
                "id": "same_weekday_comparison",
                "label": "과거 동일 요일 기준 대비",
                "value": baseline_change,
                "unit": "%",
                "reference_value": baseline_total,
                "reference_unit": "kWh",
                "basis": baseline.get("method"),
            }
        )
    if selected_test["wape"] is not None:
        evidence.append(
            {
                "id": "test_wape",
                "label": "과거 Test WAPE",
                "value": selected_test["wape"] * 100.0,
                "unit": "%",
                "basis": "모델 선택에 사용하지 않은 시간순 Test 구간",
            }
        )
    if selected_validation["mae"] is not None:
        evidence.append(
            {
                "id": "validation_mae",
                "label": "Validation MAE",
                "value": selected_validation["mae"],
                "unit": "kWh",
                "basis": "시간순 Validation 구간의 선택 모델 평가",
            }
        )

    differences: list[dict[str, Any]] = []
    if baseline_available:
        for index, (forecast, reference) in enumerate(zip(values, baseline_values, strict=True)):
            if reference is None:
                continue
            delta = forecast - float(reference)
            differences.append(
                {
                    "timestamp": timestamps[index],
                    "forecast_kwh": forecast,
                    "baseline_kwh": float(reference),
                    "difference_kwh": delta,
                    "difference_percent": _pct_change(forecast, float(reference)),
                }
            )
    elevated = sorted(
        (item for item in differences if item["difference_kwh"] > 0),
        key=lambda item: item["difference_kwh"],
        reverse=True,
    )[:3]

    recommendations: list[dict[str, Any]] = [
        {
            "priority": 1,
            "title": "예상 피크 시간 전후를 먼저 확인하세요",
            "action": "예상 피크 전후 1시간의 예약 운전과 동시에 시작되는 전력 사용이 있는지 확인하세요.",
            "reason": "24시간 예측 중 가장 높은 시간대를 우선 점검하는 운영 제안입니다.",
            "evidence_ids": ["forecast_peak"],
            "caveat": "설비별 데이터가 없어 특정 설비가 원인이라고 판단할 수 없습니다.",
        }
    ]
    if elevated:
        recommendations.append(
            {
                "priority": 2,
                "title": "동일 요일 기준보다 높은 시간대를 점검하세요",
                "action": "차이가 큰 시간대의 운영 일정, 재실 계획 또는 작업 계획이 평소와 다른지 확인하세요.",
                "reason": "실제 과거 동일 요일·시간 평균보다 예측값이 높은 시간대를 비교했습니다.",
                "evidence_ids": ["same_weekday_comparison"],
                "caveat": "비교선은 인과관계를 설명하지 않으며 계절·휴일 영향이 포함될 수 있습니다.",
            }
        )
    if selected_test["wape"] is not None:
        recommendations.append(
            {
                "priority": len(recommendations) + 1,
                "title": "검증 오차를 고려해 운영 여유를 두세요",
                "action": "예측값 하나를 확정 수요로 보지 말고 실제 계측값을 함께 확인해 운영 결정을 조정하세요.",
                "reason": "과거 Test 구간의 검증 오차가 확인되어 있습니다.",
                "evidence_ids": ["test_wape"],
                "caveat": "Test WAPE는 이번 예측의 오차 범위를 보장하지 않습니다.",
            }
        )
    recommendations = recommendations[:3]

    limitations = [
        "설비별 전력 데이터가 없어 사용량 변화의 원인 설비를 특정할 수 없습니다.",
        "시간당 에너지 사용량(kWh)은 청구용 최대수요전력(kW)과 같은 값이 아닙니다.",
        "계약 요금제가 없어 비용 시뮬레이션은 사용자가 입력한 가상 단가로만 계산합니다.",
    ]
    if not baseline_available:
        limitations.append("과거 동일 요일·시간 표본이 부족해 동일 요일 비교를 표시할 수 없습니다.")
    if selected_test["wape"] is None:
        limitations.append("선택 모델의 Test WAPE가 없어 검증 오차를 표시할 수 없습니다.")

    if baseline_change is None:
        comparison_text = "과거 동일 요일 비교는 필요한 실제 표본이 부족해 확인할 수 없습니다."
    else:
        direction = "높게" if baseline_change > 0 else "낮게" if baseline_change < 0 else "같게"
        comparison_text = f"과거 동일 요일·시간 평균보다 {abs(baseline_change):.1f}% {direction} 예측되었습니다."
    summary = (
        f"향후 24시간 예상 사용량은 {total:,.1f}kWh이며, "
        f"가장 높은 시간의 예상 사용량은 {values[peak_index]:,.1f}kWh입니다."
    )

    return {
        "version": 1,
        "source": "local_quantitative_analysis",
        "summary": summary,
        "evidence": evidence,
        "peak_analysis": {
            "timestamp": timestamps[peak_index],
            "kwh": values[peak_index],
            "finding": "24개 시간별 예측값 중 가장 높은 시점입니다.",
            "caution": "시간당 kWh 피크를 청구용 최대수요전력과 동일하게 해석하지 마세요.",
        },
        "comparison": {
            "status": "available" if baseline_available else "insufficient",
            "finding": comparison_text,
            "method": baseline.get("method"),
            "change_percent": baseline_change,
            "elevated_hours": elevated,
        },
        "recommendations": recommendations,
        "limitations": limitations,
        "model_quality": {
            "selected_model": selected_model,
            "validation": selected_validation,
            "test": selected_test,
            "baseline_validation": baseline_models,
            "mae_improvement_vs_best_baseline_percent": validation_improvement,
            "note": "Validation으로 모델을 선택하고 Test는 독립적인 최종 평가에만 사용했습니다.",
        },
        "quantitative": {
            "total_kwh": total,
            "average_hourly_kwh": average,
            "peak_kwh": values[peak_index],
            "peak_timestamp": timestamps[peak_index],
            "previous_24h_total_kwh": previous_total,
            "previous_24h_change_percent": previous_change,
            "same_weekday_total_kwh": baseline_total,
            "same_weekday_change_percent": baseline_change,
        },
        "chart": {
            "timestamps": timestamps,
            "forecast_kwh": values,
            "same_weekday_baseline_kwh": baseline_values if baseline_available else [],
            "baseline_status": "available" if baseline_available else "insufficient",
            "baseline_method": baseline.get("method"),
            "baseline_sample_counts": baseline.get("sample_counts", []),
        },
        "metadata": {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "data_start": prediction.get("data_period", {}).get("start"),
            "data_end": prediction.get("data_period", {}).get("end"),
            "data_rows": prediction.get("data_period", {}).get("rows"),
            "forecast_start": timestamps[0],
            "forecast_end": timestamps[-1],
            "building_timezone": prediction.get("building_timezone"),
            "run_id": prediction.get("run_id"),
            "model_kind": selected_model or prediction.get("model_kind"),
            "analysis_basis": "로컬 Python 정량 계산 + 선택형 OpenAI 문장 분석",
        },
    }
