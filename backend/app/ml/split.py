"""Adaptive UTC split planning and frozen non-overlapping schedules."""

from __future__ import annotations

import pandas as pd

from .contracts import EligibilityError, QualityStatus, SplitPlan


def make_split_plan(
    index: pd.DatetimeIndex,
    quality_status: QualityStatus,
    *,
    warning_approved: bool = False,
) -> SplitPlan:
    if len(index) < 2 or index.tz is None:
        raise EligibilityError("a UTC timestamp range is required")
    total_hours = int((index[-1] - index[0]) / pd.Timedelta(hours=1)) + 1
    total_days = total_hours / 24.0
    if quality_status == QualityStatus.FAIL or total_days < 90:
        raise EligibilityError("data is not eligible for a temporal split")
    limited = total_days < 180
    if limited and not warning_approved:
        raise EligibilityError("90-179 day data requires explicit limited-experiment approval")
    evaluation_days = 15 if limited else 30
    test_end = index[-1] + pd.Timedelta(hours=1)
    test_start = test_end - pd.Timedelta(days=evaluation_days)
    validation_end = test_start
    validation_start = validation_end - pd.Timedelta(days=evaluation_days)
    train_start = index[0]
    train_end = validation_start
    if train_end <= train_start:
        raise EligibilityError("training interval is empty")
    return SplitPlan(
        train_start=train_start.isoformat(),
        train_end=train_end.isoformat(),
        validation_start=validation_start.isoformat(),
        validation_end=validation_end.isoformat(),
        test_start=test_start.isoformat(),
        test_end=test_end.isoformat(),
        validation_days=evaluation_days,
        test_days=evaluation_days,
        warning_limited_experiment=limited,
    )


def interval_bounds(plan: SplitPlan, name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    if name not in {"train", "validation", "test"}:
        raise ValueError(f"unknown split: {name}")
    return pd.Timestamp(getattr(plan, f"{name}_start")), pd.Timestamp(
        getattr(plan, f"{name}_end")
    )


def frozen_evaluation_origins(
    plan: SplitPlan,
    split_name: str,
    available_index: pd.DatetimeIndex,
) -> tuple[pd.DatetimeIndex, list[dict[str, str]]]:
    """Freeze daily target starts and retain only complete 168+24 contexts."""
    start, end = interval_bounds(plan, split_name)
    target_starts = pd.date_range(start, end - pd.Timedelta(hours=24), freq="24h")
    valid: list[pd.Timestamp] = []
    excluded: list[dict[str, str]] = []
    available = set(available_index)
    for target_start in target_starts:
        origin = target_start - pd.Timedelta(hours=1)
        required = pd.date_range(
            origin - pd.Timedelta(hours=167),
            target_start + pd.Timedelta(hours=23),
            freq="h",
        )
        if all(ts in available for ts in required):
            valid.append(origin)
        else:
            excluded.append(
                {"target_start": target_start.isoformat(), "reason": "INCOMPLETE_168_PLUS_24"}
            )
    return pd.DatetimeIndex(valid), excluded
