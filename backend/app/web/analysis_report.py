"""Deterministic, privacy-preserving analysis for a completed forecast.

All numerical facts in the report are calculated locally.  The optional LLM
layer may rewrite the narrative, but it is never asked to calculate a value.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo


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
        "rmse": _number(value.get("rmse")),
        "peak_mae": _number(value.get("peak_mae")),
        "peak_time_error_hours": _number(value.get("peak_time_error_hours")),
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


def _business_hour(timestamp: str, timezone: str) -> str:
    hour = datetime.fromisoformat(timestamp).astimezone(ZoneInfo(timezone)).hour
    if hour == 0:
        return "자정"
    if hour < 12:
        return f"오전 {hour}시"
    if hour == 12:
        return "정오"
    return f"오후 {hour - 12}시"


def _format_kwh(value: float) -> str:
    absolute = abs(value)
    digits = 3 if absolute < 0.1 else 2 if absolute < 1.0 else 1
    return f"{absolute:,.{digits}f}"


def _change_sentence(
    *, label: str, change_percent: float | None, difference_kwh: float | None
) -> str | None:
    if change_percent is None or difference_kwh is None:
        return None
    if abs(change_percent) < 0.05:
        return f"{label}과 거의 같습니다"
    direction = "높습니다" if change_percent > 0 else "낮습니다"
    return (
        f"{label}보다 {abs(change_percent):.1f}%({_format_kwh(difference_kwh)}kWh) "
        f"{direction}"
    )


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
    previous_difference = total - previous_total if previous_total is not None else None
    baseline = dict(prediction.get("same_weekday_baseline") or {})
    baseline_values = baseline.get("values_kwh") or []
    baseline_available = baseline.get("status") == "available" and len(baseline_values) == 24
    baseline_total = _number(baseline.get("total_kwh")) if baseline_available else None
    baseline_change = _pct_change(total, baseline_total)
    baseline_difference = total - baseline_total if baseline_total is not None else None
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
                "label": "사용량이 계속 높은 시간대의 비중",
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
                "label": "어제 같은 시간대 대비",
                "value": previous_change,
                "unit": "%",
                "reference_value": previous_total,
                "reference_unit": "kWh",
                "basis": "업로드 데이터에서 확인한 어제 같은 시간대의 실측 합계와 비교",
            }
        )
    if baseline_available:
        evidence.append(
            {
                "id": "same_weekday_comparison",
                "label": "최근 8주 같은 요일 평균 대비",
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
                "label": "최근 8주 같은 요일 평균 대비 가장 큰 시간별 차이",
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
                "basis": "최근 최대 8주 같은 요일·시간 평균과의 절대 차이가 가장 큰 시각",
            }
        )
    if major_previous_changes:
        largest_previous_change = major_previous_changes[0]
        evidence.append(
            {
                "id": "previous_24h_largest_change",
                "label": "어제 같은 시간 대비 가장 큰 시간별 변화",
                "value": largest_previous_change["difference_kwh"],
                "unit": "kWh",
                "absolute_value": largest_previous_change["absolute_difference_kwh"],
                "relative_percent": largest_previous_change["difference_percent"],
                "timestamp": largest_previous_change["timestamp"],
                "reference_value": largest_previous_change["previous_kwh"],
                "reference_unit": "kWh",
                "basis": "예측 24시간과 어제 같은 시간대의 실측값을 시간별로 비교",
            }
        )
    if selected_test["wape"] is not None:
        evidence.append(
            {
                "id": "test_wape",
                "label": "과거 검증에서 확인된 평균 오차율",
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
            baseline_hour = _business_hour(
                largest_baseline_deviation["timestamp"],
                prediction.get("building_timezone") or "UTC",
            )
            baseline_delta = largest_baseline_deviation["difference_kwh"]
            baseline_relative = largest_baseline_deviation["difference_percent"]
            operational_candidates.append(
                {
                    "signal_id": "same_weekday_deviation",
                    "importance_score": 300.0 + (relative or 0.0),
                    "time_label": baseline_hour,
                    "title": f"{baseline_hour} 운영 일정을 확인하세요",
                    "action": f"{baseline_hour}의 작업이나 가동 일정이 최근 같은 요일과 달라졌는지 확인하세요. 실제 사용량이 나온 뒤 예측과 비교하세요.",
                    "reason": (
                        f"최근 8주 같은 요일 평균과 {_format_kwh(baseline_delta)}kWh"
                        + (
                            f"({abs(baseline_relative):.1f}%) 차이가 납니다."
                            if baseline_relative is not None else " 차이가 납니다."
                        )
                    ),
                    "evidence_ids": ["same_weekday_largest_deviation"],
                    "caveat": "비교 결과만으로 원인 설비를 알 수 없습니다.",
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
            segment_start = _business_hour(
                peak_segment["start_timestamp"], prediction.get("building_timezone") or "UTC"
            )
            segment_end = _business_hour(
                peak_segment["end_timestamp"], prediction.get("building_timezone") or "UTC"
            )
            operational_candidates.append(
                {
                    "signal_id": "concentrated_peak_period",
                    "importance_score": 200.0 + peak_to_average_ratio * 10.0,
                    "time_label": f"{segment_start}~{segment_end}",
                    "title": f"{segment_start}부터 {segment_end}까지 운영 일정을 확인하세요",
                    "action": "이 시간대에 여러 작업이 동시에 시작되는지 확인하세요. 가능하면 일부 작업의 시작 시간을 나누는 방안을 검토하세요.",
                    "reason": "하루 예상 사용량이 사용량이 계속 높은 시간대에 상대적으로 집중되어 있습니다.",
                    "evidence_ids": ["forecast_peak", "peak_period_share"],
                    "caveat": "시간당 사용량만으로 최대수요전력이나 비용 절감액을 계산할 수 없습니다.",
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
            previous_hour = _business_hour(
                largest_previous["timestamp"], prediction.get("building_timezone") or "UTC"
            )
            previous_delta = largest_previous["difference_kwh"]
            operational_candidates.append(
                {
                    "signal_id": "previous_day_change",
                    "importance_score": 100.0 + previous_relative,
                    "time_label": previous_hour,
                    "title": f"{previous_hour}의 작업 일정을 확인하세요",
                    "action": f"{previous_hour}에 어제와 다른 작업이나 가동 일정이 있는지 확인하세요. 실제 사용량이 나온 뒤 예측과 비교하세요.",
                    "reason": f"어제 같은 시간보다 {_format_kwh(previous_delta)}kWh({previous_relative:.1f}%) 차이가 납니다.",
                    "evidence_ids": ["previous_24h_largest_change"],
                    "caveat": "어제와 오늘은 요일·날씨·근무 조건이 다를 수 있습니다.",
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
        "큰 이상 신호는 없습니다. 현재 운영 계획을 유지하면서 실제 사용량 흐름을 확인하세요."
        if not recommendations
        else ""
    )

    limitations = [
        "설비별 사용량과 실제 전기요금 정보가 없어 증가 원인이나 절감 금액을 계산할 수 없습니다.",
        "시간당 사용량(kWh)은 전기요금에 사용하는 최대수요전력(kW)과 다른 값입니다.",
    ]
    if not baseline_available:
        limitations.append("최근 8주 같은 요일 자료가 부족해 평소 사용량과 비교할 수 없습니다.")
    elif not statistics_available:
        limitations.append("최근 8주 같은 요일의 변동 범위 정보가 없어 평소 범위인지 확인할 수 없습니다.")
    if not previous_hourly_available:
        limitations.append("어제 같은 시간대의 전체 실측값이 없어 시간별 변화를 비교할 수 없습니다.")
    if selected_test["wape"] is None:
        limitations.append("과거 검증 결과가 없어 예측 오차 수준을 표시할 수 없습니다.")

    if baseline_change is None:
        comparison_text = "최근 8주 같은 요일 자료가 부족해 비교할 수 없습니다."
    else:
        direction = "높게" if baseline_change > 0 else "낮게" if baseline_change < 0 else "같게"
        comparison_text = f"최근 8주 같은 요일 평균보다 {abs(baseline_change):.1f}% {direction} 예상됩니다."

    # Observations explain existing comparisons; they do not change action gates.
    comparison_ids = []
    comparison_parts = []
    for change, label, evidence_id in (
        (previous_change, "어제 같은 시간대", "previous_24h_comparison"),
        (baseline_change, "최근 8주 같은 요일 평균", "same_weekday_comparison"),
    ):
        if change is not None:
            direction = "증가" if change > 0 else "감소" if change < 0 else "변화 없음"
            comparison_parts.append(f"{label} 대비 {abs(change):.1f}% {direction}")
            comparison_ids.append(evidence_id)
    comparison_observation = "; ".join(comparison_parts) + "." if comparison_parts else comparison_text
    comparison_observation += " 두 비교값은 기준이 다르므로 함께 확인해야 합니다."

    peak_label = _business_hour(timestamps[peak_index], prediction.get("building_timezone") or "UTC")
    peak_history = baseline_statistics[peak_index] if statistics_available else {}
    sample_count = int(peak_history.get("sample_count") or 0)
    historical_mean = _number(peak_history.get("mean_kwh"))
    historical_min = _number(peak_history.get("minimum_kwh"))
    historical_max = _number(peak_history.get("maximum_kwh"))
    historical_means = [_number(item.get("mean_kwh")) for item in baseline_statistics]
    peak_context_available = (
        sample_count >= 2 and historical_mean is not None
        and historical_min is not None and historical_max is not None
        and len(historical_means) == 24 and all(value is not None for value in historical_means)
    )
    historical_rank = None
    peak_ids = ["forecast_peak"]
    if peak_context_available:
        historical_rank = 1 + sum(value > historical_mean for value in historical_means)
        peak_in_historical_range = historical_min <= values[peak_index] <= historical_max
        peak_range_text = "평소 사용 범위 안에 있습니다" if peak_in_historical_range else "평소 사용 범위를 벗어납니다"
        peak_observation = (
            f"전력 사용이 가장 많을 것으로 예상되는 시간은 {peak_label}이며, "
            f"예상 사용량은 {values[peak_index]:,.1f}kWh입니다. "
            f"최근 8주 같은 요일의 {peak_label} 사용량은 "
            f"{historical_min:,.1f}~{historical_max:,.1f}kWh였으므로 {peak_range_text}."
        )
        evidence.append({
            "id": "peak_historical_context",
            "label": "사용량이 가장 높은 시간의 최근 8주 같은 요일 자료",
            "timestamp": timestamps[peak_index],
            "value": historical_mean,
            "unit": "kWh",
            "sample_count": sample_count,
            "historical_mean_rank": historical_rank,
            "historical_minimum_kwh": historical_min,
            "historical_maximum_kwh": historical_max,
            "forecast_kwh": values[peak_index],
            "basis": "최근 최대 8개 같은 요일 표본의 평균·범위와 24개 시간 평균 순위",
        })
        peak_ids.append("peak_historical_context")
    else:
        peak_in_historical_range = None
        peak_observation = (
            f"전력 사용이 가장 많을 것으로 예상되는 시간은 {peak_label}이며, "
            f"예상 사용량은 {values[peak_index]:,.1f}kWh입니다. "
            "최근 같은 요일의 비교 자료가 부족해 평소 사용 범위인지는 확인할 수 없습니다."
        )

    generated_at = datetime.now(UTC)
    forecast_period_end = datetime.fromisoformat(timestamps[-1]) + timedelta(hours=1)
    is_historical = forecast_period_end <= generated_at
    if is_historical:
        limitations.append(
            "예측 대상 기간이 이미 지나 현재 운영 계획으로 사용할 수 없습니다. 과거 데이터 검증 결과로만 확인하세요."
        )

    summary_parts = [f"다음 24시간 예상 사용량은 {total:,.1f}kWh입니다."]
    previous_sentence = _change_sentence(
        label="어제 같은 시간대",
        change_percent=previous_change,
        difference_kwh=previous_difference,
    )
    baseline_sentence = _change_sentence(
        label="최근 8주 같은 요일 평균",
        change_percent=baseline_change,
        difference_kwh=baseline_difference,
    )
    if previous_sentence:
        summary_parts.append(previous_sentence + ".")
    if baseline_sentence:
        summary_parts.append(baseline_sentence + ".")

    available_total_changes = [
        abs(change) for change in (previous_change, baseline_change) if change is not None
    ]
    total_changes_are_moderate = (
        bool(available_total_changes) and max(available_total_changes) < 20.0
    )
    softened_action = (
        bool(recommendations)
        and total_changes_are_moderate
        and peak_in_historical_range is True
    )
    attention_times = list(dict.fromkeys(
        item.get("time_label") for item in recommendations if item.get("time_label")
    ))
    attention_target = (
        f"{attention_times[0]}와 {attention_times[1]}"
        if len(attention_times) >= 2
        else attention_times[0] if attention_times
        else "일부 시간대"
    )
    if softened_action:
        decision_title = "큰 이상 신호는 없지만 일부 시간대를 확인하세요"
        judgment_sentence = f"평소와 큰 차이는 아니지만, {attention_target} 운영 일정을 확인해볼 필요가 있습니다."
    elif recommendations:
        decision_title = "확인이 필요한 시간대가 있습니다"
        judgment_sentence = f"평소와 차이가 큰 시간대가 있어 {attention_target} 운영 일정을 확인해볼 필요가 있습니다."
    else:
        decision_title = "큰 이상 신호는 없습니다"
        judgment_sentence = "평소와 큰 차이는 아니므로 현재 운영 계획을 유지해도 됩니다."

    if is_historical:
        decision_title = f"과거 데이터 검증 결과 · {decision_title}"
        if softened_action:
            summary_parts.append(
                f"평소와 큰 차이는 아니지만, 당시 {attention_target} 운영 일정은 확인 대상이었습니다."
            )
        elif recommendations:
            summary_parts.append(
                f"평소와 차이가 큰 시간대가 있어 당시 {attention_target} 운영 일정은 확인 대상이었습니다."
            )
        else:
            summary_parts.append("당시 기준으로 평소와 큰 차이는 아니었습니다.")
        if not recommendations:
            no_action_reason = "당시 서버의 조치 기준을 충족한 시간대는 없었습니다."
    else:
        summary_parts.append(judgment_sentence)

    summary = " ".join(summary_parts)
    accuracy_parts: list[str] = []
    if selected_test["mae"] is not None:
        accuracy_parts.append(
            "과거 테스트에서 시간당 사용량은 실제와 평균 "
            f"{selected_test['mae']:.2f} kWh 차이가 났습니다."
        )
    if (
        selected_test["peak_mae"] is not None
        and selected_test["peak_time_error_hours"] is not None
    ):
        accuracy_parts.append(
            "24시간 중 가장 많이 쓴 시간의 사용량은 평균 "
            f"{selected_test['peak_mae']:.2f} kWh, 그 시점은 평균 "
            f"{selected_test['peak_time_error_hours']:.1f}시간 차이가 났습니다."
        )
    elif selected_test["peak_mae"] is not None:
        accuracy_parts.append(
            "24시간 중 가장 많이 쓴 시간의 사용량은 실제와 평균 "
            f"{selected_test['peak_mae']:.2f} kWh 차이가 났습니다."
        )
    elif selected_test["peak_time_error_hours"] is not None:
        accuracy_parts.append(
            "24시간 중 가장 많이 쓴 시점은 실제와 평균 "
            f"{selected_test['peak_time_error_hours']:.1f}시간 차이가 났습니다."
        )
    if not accuracy_parts:
        accuracy_summary = (
            "과거 테스트 결과가 없어 시간당 사용량과 피크 오차를 확인할 수 없습니다. "
            "예상 사용량은 운영 일정을 점검하는 참고 자료로만 활용하세요."
        )
    else:
        accuracy_summary = " ".join(accuracy_parts)

    observation_evidence_ids = {
        "summary": ["forecast_total", *comparison_ids],
        "comparison": comparison_ids,
        "peak_analysis": peak_ids,
    }

    return {
        "version": 4,
        "source": "local_quantitative_analysis",
        "summary": summary,
        "decision": {
            "status": "action_available" if recommendations else "no_action",
            "title": decision_title,
            "tone": "calm_attention" if softened_action else (
                "attention" if recommendations else "stable"
            ),
        },
        "observation_evidence_ids": observation_evidence_ids,
        "evidence": evidence,
        "peak_analysis": {
            "timestamp": timestamps[peak_index],
            "kwh": values[peak_index],
            "finding": "24개 시간별 예측값 중 가장 높은 시점입니다.",
            "observation": peak_observation,
            "historical_context": {
                "status": "available" if peak_context_available else "insufficient",
                "sample_count": sample_count,
                "mean_kwh": historical_mean,
                "minimum_kwh": historical_min,
                "maximum_kwh": historical_max,
                "mean_rank_among_24_hours": historical_rank,
                "within_usual_range": peak_in_historical_range,
            },
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
            "observation": comparison_observation,
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
            "business_summary": accuracy_summary,
        },
        "quantitative": {
            "total_kwh": total,
            "average_hourly_kwh": average,
            "peak_kwh": values[peak_index],
            "peak_timestamp": timestamps[peak_index],
            "previous_24h_total_kwh": previous_total,
            "previous_24h_change_percent": previous_change,
            "previous_24h_difference_kwh": previous_difference,
            "same_weekday_total_kwh": baseline_total,
            "same_weekday_change_percent": baseline_change,
            "same_weekday_difference_kwh": baseline_difference,
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
            "generated_at_utc": generated_at.isoformat(),
            "data_start": prediction.get("data_period", {}).get("start"),
            "data_end": prediction.get("data_period", {}).get("end"),
            "data_rows": prediction.get("data_period", {}).get("rows"),
            "forecast_start": timestamps[0],
            "forecast_end": timestamps[-1],
            "building_timezone": prediction.get("building_timezone"),
            "run_id": prediction.get("run_id"),
            "model_kind": selected_model or prediction.get("model_kind"),
            "report_purpose": "historical_validation" if is_historical else "operations_plan",
            "report_purpose_label": "과거 데이터 검증 결과" if is_historical else "운영 계획 참고",
            "analysis_basis": "로컬 Python 정량 계산 + 선택형 OpenAI 문장 분석",
        },
    }
