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


def _percentile(values: list[float], percentile: float) -> float:
    """Return a deterministic linear percentile without adding a dependency."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("백분위수를 계산할 값이 없습니다.")
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _consecutive_segments(
    values: list[float], timestamps: list[str], threshold: float, total: float
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    start: int | None = None
    for index in range(len(values) + 1):
        above = index < len(values) and values[index] >= threshold
        if above and start is None:
            start = index
        if (above or start is None):
            continue
        end = index - 1
        segment_values = values[start : end + 1]
        amount = float(sum(segment_values))
        peak_offset = max(range(len(segment_values)), key=segment_values.__getitem__)
        segments.append(
            {
                "start_timestamp": timestamps[start],
                "end_timestamp": timestamps[end],
                "hours": end - start + 1,
                "total_kwh": amount,
                "share_percent": amount / total * 100.0 if total > 0 else None,
                "peak_timestamp": timestamps[start + peak_offset],
                "peak_kwh": segment_values[peak_offset],
            }
        )
        start = None
    return segments


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
    baseline_statistics = baseline.get("statistics_by_hour") or []
    statistics_available = baseline_available and len(baseline_statistics) == 24

    history_values = [_number(value) for value in prediction.get("history_kwh", [])]
    previous_hourly_available = len(history_values) == 24 and all(
        value is not None for value in history_values
    )
    complete_history = [float(value) for value in history_values if value is not None]

    high_usage_threshold = _percentile(values, 0.75)
    high_usage_segments = _consecutive_segments(
        values, timestamps, high_usage_threshold, total
    )
    peak_segment = next(
        (
            segment
            for segment in high_usage_segments
            if segment["start_timestamp"] <= timestamps[peak_index] <= segment["end_timestamp"]
        ),
        None,
    )
    peak_to_average_ratio = values[peak_index] / average if average > 0 else None

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

    differences: list[dict[str, Any]] = []
    if baseline_available:
        for index, (forecast, reference) in enumerate(zip(values, baseline_values, strict=True)):
            if reference is None:
                continue
            reference_value = float(reference)
            delta = forecast - reference_value
            statistic = baseline_statistics[index] if statistics_available else {}
            standard_deviation = _number(statistic.get("standard_deviation_kwh"))
            minimum = _number(statistic.get("minimum_kwh"))
            maximum = _number(statistic.get("maximum_kwh"))
            difference_percent = _pct_change(forecast, reference_value)
            differences.append(
                {
                    "timestamp": timestamps[index],
                    "forecast_kwh": forecast,
                    "baseline_kwh": reference_value,
                    "difference_kwh": delta,
                    "absolute_difference_kwh": abs(delta),
                    "difference_percent": difference_percent,
                    "absolute_difference_percent": (
                        abs(difference_percent) if difference_percent is not None else None
                    ),
                    "baseline_variance_kwh2": _number(statistic.get("variance_kwh2")),
                    "baseline_standard_deviation_kwh": standard_deviation,
                    "baseline_minimum_kwh": minimum,
                    "baseline_maximum_kwh": maximum,
                    "baseline_range_kwh": _number(statistic.get("range_kwh")),
                    "outside_historical_range": (
                        forecast < minimum or forecast > maximum
                        if minimum is not None and maximum is not None
                        else None
                    ),
                    "standardized_difference": (
                        delta / standard_deviation
                        if standard_deviation is not None and standard_deviation > 0
                        else None
                    ),
                }
            )
    elevated = sorted(
        (item for item in differences if item["difference_kwh"] > 0),
        key=lambda item: item["absolute_difference_kwh"],
        reverse=True,
    )[:3]
    largest_baseline_deviation = max(
        differences, key=lambda item: item["absolute_difference_kwh"], default=None
    )

    previous_differences: list[dict[str, Any]] = []
    if previous_hourly_available:
        for timestamp, forecast, reference in zip(
            timestamps, values, complete_history, strict=True
        ):
            delta = forecast - reference
            difference_percent = _pct_change(forecast, reference)
            previous_differences.append(
                {
                    "timestamp": timestamp,
                    "forecast_kwh": forecast,
                    "previous_kwh": reference,
                    "difference_kwh": delta,
                    "absolute_difference_kwh": abs(delta),
                    "difference_percent": difference_percent,
                    "absolute_difference_percent": (
                        abs(difference_percent) if difference_percent is not None else None
                    ),
                }
            )
    major_previous_changes = sorted(
        previous_differences,
        key=lambda item: item["absolute_difference_kwh"],
        reverse=True,
    )[:3]

    available_variances = [
        _number(item.get("variance_kwh2")) for item in baseline_statistics
    ] if statistics_available else []
    available_ranges = [
        _number(item.get("range_kwh")) for item in baseline_statistics
    ] if statistics_available else []
    complete_variances = [value for value in available_variances if value is not None]
    complete_ranges = [value for value in available_ranges if value is not None]
    average_baseline_variance = (
        sum(complete_variances) / len(complete_variances) if complete_variances else None
    )
    maximum_baseline_range = max(complete_ranges) if complete_ranges else None

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
    if peak_segment is not None:
        evidence.append(
            {
                "id": "peak_period_share",
                "label": "연속 고사용 구간 비중",
                "value": peak_segment["share_percent"],
                "unit": "%",
                "start_timestamp": peak_segment["start_timestamp"],
                "end_timestamp": peak_segment["end_timestamp"],
                "hours": peak_segment["hours"],
                "reference_value": high_usage_threshold,
                "reference_unit": "kWh",
                "basis": "24시간 예측값의 상위 사분위 기준 연속 구간",
            }
        )
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
    if largest_baseline_deviation is not None:
        evidence.append(
            {
                "id": "same_weekday_largest_deviation",
                "label": "동일 요일 기준 최대 시간별 편차",
                "value": largest_baseline_deviation["difference_kwh"],
                "unit": "kWh",
                "absolute_value": largest_baseline_deviation["absolute_difference_kwh"],
                "relative_percent": largest_baseline_deviation["difference_percent"],
                "timestamp": largest_baseline_deviation["timestamp"],
                "reference_value": largest_baseline_deviation["baseline_kwh"],
                "reference_unit": "kWh",
                "historical_minimum_kwh": largest_baseline_deviation["baseline_minimum_kwh"],
                "historical_maximum_kwh": largest_baseline_deviation["baseline_maximum_kwh"],
                "outside_historical_range": largest_baseline_deviation["outside_historical_range"],
                "basis": "과거 동일 요일·시간 평균과의 절대 편차가 가장 큰 시각",
            }
        )
    if major_previous_changes:
        largest_previous_change = major_previous_changes[0]
        evidence.append(
            {
                "id": "previous_24h_largest_change",
                "label": "직전 24시간 대비 최대 시간별 변화",
                "value": largest_previous_change["difference_kwh"],
                "unit": "kWh",
                "absolute_value": largest_previous_change["absolute_difference_kwh"],
                "relative_percent": largest_previous_change["difference_percent"],
                "timestamp": largest_previous_change["timestamp"],
                "reference_value": largest_previous_change["previous_kwh"],
                "reference_unit": "kWh",
                "basis": "예측 24시간과 직전 실측 24시간을 시간 위치별로 비교",
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
    if selected_validation["wape"] is not None:
        evidence.append(
            {
                "id": "validation_wape",
                "label": "Validation WAPE",
                "value": selected_validation["wape"] * 100.0,
                "unit": "%",
                "basis": "시간순 Validation 구간의 선택 모델 평가",
            }
        )

    operational_candidates: list[dict[str, Any]] = []
    if largest_baseline_deviation is not None:
        relative = largest_baseline_deviation["absolute_difference_percent"]
        standardized = largest_baseline_deviation["standardized_difference"]
        significant_baseline_change = (
            largest_baseline_deviation["outside_historical_range"] is True
            or (standardized is not None and abs(standardized) >= 2.0)
            or (relative is not None and relative >= 20.0 and not statistics_available)
        )
        if significant_baseline_change:
            operational_candidates.append(
                {
                    "signal_id": "same_weekday_deviation",
                    "importance_score": 300.0 + (relative or 0.0),
                    "title": "동일 요일 범위를 벗어난 시간대를 우선 확인하세요",
                    "action": "해당 시간대의 운영 일정이 과거 동일 요일과 달라졌는지 확인하고 실제 계측값을 함께 모니터링하세요.",
                    "reason": "예측값이 과거 동일 요일·시간의 평균 또는 변동 범위에서 유의미하게 벗어났습니다.",
                    "evidence_ids": ["same_weekday_largest_deviation"],
                    "caveat": "과거 범위를 벗어난 사실만 확인되며 원인 설비나 인과관계는 알 수 없습니다.",
                }
            )
    if peak_segment is not None and peak_to_average_ratio is not None:
        expected_share = peak_segment["hours"] / 24.0 * 100.0
        concentrated = (
            peak_to_average_ratio >= 1.2
            and peak_segment["share_percent"] is not None
            and peak_segment["share_percent"] >= expected_share * 1.15
        )
        if concentrated:
            operational_candidates.append(
                {
                    "signal_id": "concentrated_peak_period",
                    "importance_score": 200.0 + peak_to_average_ratio * 10.0,
                    "title": "연속 고사용 구간의 운영 계획을 확인하세요",
                    "action": "고사용 구간에 겹치는 예약 운전이나 작업 일정을 확인하고, 가능하면 시작 시각 분산을 검토하세요.",
                    "reason": "상위 사분위 사용량이 연속된 구간에 하루 예상 사용량이 상대적으로 집중되어 있습니다.",
                    "evidence_ids": ["forecast_peak", "peak_period_share"],
                    "caveat": "시간당 kWh 집중은 최대수요전력이나 비용 절감을 직접 의미하지 않습니다.",
                }
            )
    if major_previous_changes:
        largest_previous = major_previous_changes[0]
        previous_relative = largest_previous["absolute_difference_percent"]
        significant_previous_change = (
            previous_relative is not None
            and previous_relative >= 20.0
            and largest_previous["absolute_difference_kwh"] >= average * 0.1
        )
        if significant_previous_change:
            operational_candidates.append(
                {
                    "signal_id": "previous_day_change",
                    "importance_score": 100.0 + previous_relative,
                    "title": "직전 24시간과 크게 달라진 시간대를 확인하세요",
                    "action": "변화가 큰 시간대의 운영 계획이 직전 실측 기간과 다른지 확인하고 예측 시각에 실제 부하를 점검하세요.",
                    "reason": "예측값과 직전 24시간 실측값의 시간 위치별 차이가 기준 이상으로 큽니다.",
                    "evidence_ids": ["previous_24h_largest_change"],
                    "caveat": "직전 24시간은 요일·날씨·재실 조건이 다를 수 있어 원인을 설명하지 않습니다.",
                }
            )
    operational_candidates.sort(key=lambda item: item["importance_score"], reverse=True)
    recommendations = [
        {
            **{key: value for key, value in candidate.items() if key not in {"signal_id", "importance_score"}},
            "priority": index + 1,
        }
        for index, candidate in enumerate(operational_candidates[:3])
    ]
    no_action_reason = (
        "계산 가능한 비교 지표에서 우선 조치가 필요한 수준의 뚜렷한 변화를 확인하지 못했습니다. "
        "일반적인 절전 조치를 임의로 권고하지 않고 실제 계측값을 계속 확인합니다."
        if not recommendations
        else ""
    )

    limitations = [
        "설비별 전력 데이터가 없어 사용량 변화의 원인 설비를 특정할 수 없습니다.",
        "시간당 에너지 사용량(kWh)은 청구용 최대수요전력(kW)과 같은 값이 아닙니다.",
        "계약 요금제가 없어 비용 시뮬레이션은 사용자가 입력한 가상 단가로만 계산합니다.",
    ]
    if not baseline_available:
        limitations.append("과거 동일 요일·시간 표본이 부족해 동일 요일 비교를 표시할 수 없습니다.")
    elif not statistics_available:
        limitations.append("과거 동일 요일 표본의 분산과 변동 범위 정보가 없어 편차의 유의성을 제한적으로 판단했습니다.")
    if not previous_hourly_available:
        limitations.append("직전 24시간의 완전한 시간별 실측값이 없어 주요 변화 구간을 계산할 수 없습니다.")
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
        "version": 2,
        "source": "local_quantitative_analysis",
        "summary": summary,
        "evidence": evidence,
        "peak_analysis": {
            "timestamp": timestamps[peak_index],
            "kwh": values[peak_index],
            "finding": "24개 시간별 예측값 중 가장 높은 시점입니다.",
            "caution": "시간당 kWh 피크를 청구용 최대수요전력과 동일하게 해석하지 마세요.",
            "high_usage_threshold_kwh": high_usage_threshold,
            "high_usage_segments": high_usage_segments,
            "peak_segment": peak_segment,
            "peak_segment_share_percent": (
                peak_segment.get("share_percent") if peak_segment else None
            ),
            "peak_to_average_ratio": peak_to_average_ratio,
        },
        "comparison": {
            "status": "available" if baseline_available else "insufficient",
            "finding": comparison_text,
            "method": baseline.get("method"),
            "change_percent": baseline_change,
            "elevated_hours": elevated,
            "hourly_differences": differences,
            "largest_absolute_deviation": largest_baseline_deviation,
            "variability": {
                "status": "available" if statistics_available else "insufficient",
                "average_variance_kwh2": average_baseline_variance,
                "maximum_range_kwh": maximum_baseline_range,
                "hourly_statistics": baseline_statistics if statistics_available else [],
            },
        },
        "previous_24h_comparison": {
            "status": "available" if previous_hourly_available else "insufficient",
            "hourly_differences": previous_differences,
            "major_change_hours": major_previous_changes,
        },
        "recommendations": recommendations,
        "operational_candidates": operational_candidates,
        "no_action_reason": no_action_reason,
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
            "peak_period_share_percent": (
                peak_segment.get("share_percent") if peak_segment else None
            ),
            "same_weekday_average_variance_kwh2": average_baseline_variance,
            "same_weekday_maximum_range_kwh": maximum_baseline_range,
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
