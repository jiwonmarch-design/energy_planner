"""CSV contract validation and non-mutating quality diagnosis."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import (
    DataContractError,
    DistributionShiftReport,
    EligibilityError,
    QualityReport,
    QualityStatus,
    SourceTimezoneMode,
)


def load_csv_frame(path: str | Path) -> pd.DataFrame:
    """Read a UTF-8/UTF-8-BOM CSV without modifying its contents."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataContractError("CSV must be encoded as UTF-8 or UTF-8 BOM") from exc
    except Exception as exc:
        raise DataContractError(f"CSV could not be read: {path}") from exc


def _timezone(name: str) -> ZoneInfo:
    if not name or ("/" not in name and name != "UTC"):
        raise DataContractError("building_timezone must be a full IANA timezone name")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise DataContractError(f"unknown IANA timezone: {name}") from exc


def validate_and_normalize_frame(
    frame: pd.DataFrame,
    building_timezone: str,
    *,
    source_timezone_mode: SourceTimezoneMode | str = SourceTimezoneMode.IANA_CIVIL_TIME,
) -> pd.DataFrame:
    """Validate the input contract and return timestamp-indexed UTC data.

    The returned frame is a new object. Missing hours are not inserted and kWh
    values are never imputed or changed.
    """
    zone = _timezone(building_timezone)
    try:
        mode = SourceTimezoneMode(source_timezone_mode)
    except ValueError as exc:
        raise DataContractError(f"unsupported source_timezone_mode: {source_timezone_mode}") from exc
    if mode == SourceTimezoneMode.BDG2_FIXED_STANDARD_LOCAL_GRID and not (
        building_timezone == "UTC" or building_timezone.startswith("Etc/GMT")
    ):
        raise DataContractError(
            "BDG2 fixed-grid mode requires UTC or an Etc/GMT fixed-offset feature timezone"
        )
    if not isinstance(frame, pd.DataFrame):
        raise DataContractError("input must be a pandas DataFrame")
    missing = {"timestamp", "kwh"} - set(frame.columns)
    if missing:
        raise DataContractError(f"missing required columns: {sorted(missing)}")
    if frame.empty:
        raise DataContractError("CSV has no observations")

    raw = frame.loc[:, ["timestamp", "kwh"]].copy()
    if raw["timestamp"].isna().any() or raw["kwh"].isna().any():
        raise DataContractError("timestamp and kwh cannot be blank")
    numeric = pd.to_numeric(raw["kwh"], errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise DataContractError("kwh must contain finite numeric values")
    if (numeric < 0).any():
        raise DataContractError("kwh cannot be negative")

    parsed: list[pd.Timestamp] = []
    awareness: set[bool] = set()
    for value in raw["timestamp"]:
        try:
            ts = pd.Timestamp(value)
        except Exception as exc:
            raise DataContractError(f"invalid timestamp: {value!r}") from exc
        if pd.isna(ts):
            raise DataContractError("timestamp cannot be NaT")
        aware = ts.tzinfo is not None
        if mode == SourceTimezoneMode.EXPLICIT_OFFSET and not aware:
            raise DataContractError("explicit_offset mode requires an offset in every timestamp")
        if mode == SourceTimezoneMode.BDG2_FIXED_STANDARD_LOCAL_GRID and aware:
            raise DataContractError("BDG2 fixed-grid mode requires offset-naive source labels")
        awareness.add(aware)
        if len(awareness) > 1:
            raise DataContractError("offset-aware and offset-naive timestamps cannot be mixed")
        if ts.minute != 0 or ts.second != 0 or ts.microsecond != 0:
            raise DataContractError("timestamps must be aligned to exact hours")
        try:
            if aware:
                utc = ts.tz_convert("UTC")
            else:
                # Ambiguous/nonexistent local DST times must be explicit.
                localized = ts.tz_localize(zone, ambiguous="raise", nonexistent="raise")
                utc = localized.tz_convert("UTC")
        except Exception as exc:
            raise DataContractError(
                f"timestamp cannot be resolved in {building_timezone}: {value!r}"
            ) from exc
        parsed.append(utc)

    index = pd.DatetimeIndex(parsed, name="timestamp")
    if index.has_duplicates:
        raise DataContractError("duplicate physical timestamps are not allowed")
    if not index.is_monotonic_increasing:
        raise DataContractError("timestamps must be strictly increasing")
    if len(index) > 1:
        hour_ns = 3_600_000_000_000
        # Pandas 3 can preserve microsecond timestamp storage; normalize the
        # index unit before integer cadence arithmetic.
        delta_ns = np.diff(index.as_unit("ns").asi8)
        if np.any(delta_ns < hour_ns) or np.any(np.mod(delta_ns, hour_ns) != 0):
            raise DataContractError("input cadence violates the one-hour contract")
        if not np.any(delta_ns == hour_ns):
            raise DataContractError("input cadence is not hourly")

    return pd.DataFrame({"kwh": numeric.to_numpy(dtype=float)}, index=index)


def _max_missing_run(present: np.ndarray) -> int:
    maximum = current = 0
    for is_present in present:
        if is_present:
            current = 0
        else:
            current += 1
            maximum = max(maximum, current)
    return maximum


def _constant_run_metrics(values: np.ndarray) -> tuple[int, float, int, float]:
    """Return exact dominant-value and consecutive-run diagnostics.

    Values are not rounded or altered. The exact comparison intentionally
    exposes sentinel-like plateaus such as Maggie's repeated 0.0002 readings.
    """
    unique, counts = np.unique(values, return_counts=True)
    dominant_index = int(np.argmax(counts))
    dominant_value = float(unique[dominant_index])
    dominant_count = int(counts[dominant_index])
    longest = current = 1
    for previous, current_value in zip(values[:-1], values[1:]):
        if current_value == previous:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest, dominant_value, dominant_count, dominant_count / len(values)


def diagnose_quality(data: pd.DataFrame) -> QualityReport:
    """Calculate quality metrics on a validated UTC-indexed frame."""
    if data.empty or not isinstance(data.index, pd.DatetimeIndex):
        raise DataContractError("quality diagnosis requires validated timestamp-indexed data")
    expected_index = pd.date_range(data.index[0], data.index[-1], freq="h", tz="UTC")
    present = expected_index.isin(data.index)
    values = data["kwh"].to_numpy(dtype=float)
    longest_constant, dominant_value, dominant_count, dominant_rate = _constant_run_metrics(
        values
    )
    elapsed_days = len(expected_index) / 24.0
    missing_hours = int((~present).sum())
    missing_rate = missing_hours / len(expected_index)
    max_gap = _max_missing_run(present)

    aligned = data["kwh"].reindex(expected_index)
    valid = aligned.notna().to_numpy()
    complete_168 = 0
    complete_pairs = 0
    if len(valid) >= 168:
        complete_168 = sum(bool(valid[i : i + 168].all()) for i in range(len(valid) - 167))
    if len(valid) >= 192:
        complete_pairs = sum(bool(valid[i : i + 192].all()) for i in range(len(valid) - 191))

    # Robust IQR flag is diagnostic only; values are not modified or excluded.
    q1, q3 = np.quantile(values, [0.25, 0.75])
    iqr = q3 - q1
    upper = q3 + 3.0 * iqr
    outliers = int((values > upper).sum()) if iqr > 0 else 0

    reasons: list[str] = []
    if elapsed_days < 90:
        status = QualityStatus.FAIL
        reasons.append("FAIL_LESS_THAN_90_DAYS")
    elif elapsed_days < 180:
        status = QualityStatus.WARNING
        reasons.append("WARNING_90_TO_179_DAYS_APPROVAL_REQUIRED")
    else:
        status = QualityStatus.PASS
    if missing_rate > 0.05:
        status = QualityStatus.FAIL
        reasons.append("FAIL_MISSING_RATE_OVER_5_PERCENT")
    if max_gap > 24:
        if status == QualityStatus.PASS:
            status = QualityStatus.WARNING
        reasons.append("WARNING_MAX_GAP_OVER_24_HOURS")
    state_transition = bool(
        longest_constant >= 168
        and dominant_rate >= 0.5
        and np.any(values != dominant_value)
    )
    if longest_constant >= 168:
        if status == QualityStatus.PASS:
            status = QualityStatus.WARNING
        reasons.append("WARNING_LONG_CONSTANT_RUN_168H")
    if dominant_rate >= 0.5:
        if status == QualityStatus.PASS:
            status = QualityStatus.WARNING
        reasons.append("WARNING_DOMINANT_VALUE_OVER_50_PERCENT")
    if state_transition:
        if status == QualityStatus.PASS:
            status = QualityStatus.WARNING
        reasons.append("WARNING_SUSPECTED_METER_STATE_TRANSITION")
    if not reasons and status == QualityStatus.PASS:
        reasons.append("PASS_QUALITY_THRESHOLDS")

    return QualityReport(
        status=status,
        reason_codes=reasons,
        start_utc=data.index[0].isoformat(),
        end_utc=data.index[-1].isoformat(),
        elapsed_days=elapsed_days,
        expected_hours=len(expected_index),
        observed_hours=len(data),
        missing_hours=missing_hours,
        missing_rate=missing_rate,
        max_consecutive_missing_hours=max_gap,
        zero_count=int((values == 0).sum()),
        zero_rate=float((values == 0).mean()),
        suspicious_outlier_count=outliers,
        complete_168_windows=complete_168,
        complete_168_plus_24_pairs=complete_pairs,
        latest_168_complete=bool(len(valid) >= 168 and valid[-168:].all()),
        longest_constant_run_hours=longest_constant,
        dominant_value=dominant_value,
        dominant_value_count=dominant_count,
        dominant_value_rate=float(dominant_rate),
        suspected_state_transition=state_transition,
    )


def diagnose_split_distribution(data: pd.DataFrame, plan) -> DistributionShiftReport:
    """Diagnose, but never repair, distribution changes across temporal splits."""
    intervals: dict[str, pd.Series] = {}
    for name in ("train", "validation", "test"):
        start = pd.Timestamp(getattr(plan, f"{name}_start"))
        end = pd.Timestamp(getattr(plan, f"{name}_end"))
        intervals[name] = data.loc[(data.index >= start) & (data.index < end), "kwh"]
        if intervals[name].empty:
            raise EligibilityError(f"{name} distribution interval is empty")
    train = intervals["train"].to_numpy(dtype=float)
    validation = intervals["validation"].to_numpy(dtype=float)
    test = intervals["test"].to_numpy(dtype=float)
    train_std = float(np.std(train))
    train_zero_variance = bool(np.all(train == train[0]))

    def shift(values: np.ndarray) -> float | None:
        if train_zero_variance:
            return None
        return float(abs(np.mean(values) - np.mean(train)) / train_std)

    validation_shift = shift(validation)
    test_shift = shift(test)
    warnings: list[str] = []
    if train_zero_variance:
        warnings.append("FAIL_TRAIN_ZERO_VARIANCE")
    if validation_shift is not None and validation_shift >= 1.0:
        warnings.append("WARNING_VALIDATION_MEAN_SHIFT_OVER_1_TRAIN_STD")
    if test_shift is not None and test_shift >= 1.0:
        warnings.append("WARNING_TEST_MEAN_SHIFT_OVER_1_TRAIN_STD")
    if train_zero_variance and (
        np.any(validation != train[0]) or np.any(test != train[0])
    ):
        warnings.append("WARNING_POST_TRAIN_STATE_TRANSITION")
    return DistributionShiftReport(
        train_count=len(train),
        validation_count=len(validation),
        test_count=len(test),
        train_mean=float(np.mean(train)),
        validation_mean=float(np.mean(validation)),
        test_mean=float(np.mean(test)),
        train_std=train_std,
        validation_std=float(np.std(validation)),
        test_std=float(np.std(test)),
        validation_standardized_mean_shift=validation_shift,
        test_standardized_mean_shift=test_shift,
        train_zero_variance=train_zero_variance,
        warning_codes=warnings,
    )


def enforce_train_variance(report: DistributionShiftReport) -> None:
    """Block model fitting when Train cannot define a meaningful kWh scale."""
    if report.train_zero_variance:
        raise EligibilityError("FAIL_TRAIN_ZERO_VARIANCE")
