"""Causal 168-hour inputs and 24-hour target generation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import FEATURE_NAMES, HORIZON, LOOKBACK, SequenceBatch
from .split import interval_bounds


def make_sequences(
    features: pd.DataFrame,
    targets: pd.Series,
    plan,
    split_name: str,
    *,
    origins: pd.DatetimeIndex | None = None,
) -> SequenceBatch:
    """Create samples whose targets are fully contained in the named split.

    Validation and test inputs may use prior observed context. No target value is
    included in an input window.
    """
    if tuple(features.columns) != FEATURE_NAMES:
        raise ValueError("feature names or order do not match the six-feature contract")
    start, end = interval_bounds(plan, split_name)
    if origins is None:
        candidate_target_starts = pd.date_range(start, end - pd.Timedelta(hours=24), freq="h")
        origins = candidate_target_starts - pd.Timedelta(hours=1)
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    kept_origins: list[pd.Timestamp] = []
    target_starts: list[pd.Timestamp] = []
    feature_index = set(features.index)
    target_index = set(targets.index)
    for origin in origins:
        target_start = origin + pd.Timedelta(hours=1)
        target_end_exclusive = target_start + pd.Timedelta(hours=HORIZON)
        if target_start < start or target_end_exclusive > end:
            continue
        input_index = pd.date_range(origin - pd.Timedelta(hours=LOOKBACK - 1), origin, freq="h")
        output_index = pd.date_range(target_start, periods=HORIZON, freq="h")
        if not all(ts in feature_index for ts in input_index):
            continue
        if not all(ts in target_index for ts in output_index):
            continue
        x = features.loc[input_index, FEATURE_NAMES].to_numpy(dtype=np.float32)
        y = targets.loc[output_index].to_numpy(dtype=np.float32)
        if np.isfinite(x).all() and np.isfinite(y).all():
            xs.append(x)
            ys.append(y)
            kept_origins.append(origin)
            target_starts.append(target_start)
    x_array = np.stack(xs) if xs else np.empty((0, LOOKBACK, len(FEATURE_NAMES)), dtype=np.float32)
    y_array = np.stack(ys) if ys else np.empty((0, HORIZON), dtype=np.float32)
    return SequenceBatch(
        x=x_array,
        y=y_array,
        origins=pd.DatetimeIndex(kept_origins),
        target_starts=pd.DatetimeIndex(target_starts),
    )


def validate_minimum_samples(
    train_dense: SequenceBatch,
    validation_dense: SequenceBatch,
    validation_nonoverlap: SequenceBatch,
    test_nonoverlap: SequenceBatch,
) -> None:
    """Apply the Phase 6-5 provisional 1000/168/12/12 thresholds."""
    if len(train_dense.x) < 1000:
        raise ValueError("FAIL_MINIMUM_TRAIN_SAMPLES_1000")
    if len(validation_dense.x) < 168:
        raise ValueError("FAIL_MINIMUM_VALIDATION_DENSE_SAMPLES_168")
    if len(validation_nonoverlap.x) < 12:
        raise ValueError("FAIL_MINIMUM_VALIDATION_NONOVERLAP_12")
    if len(test_nonoverlap.x) < 12:
        raise ValueError("FAIL_MINIMUM_TEST_NONOVERLAP_12")
