"""Causal 168-hour inputs and 24-hour target generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .contracts import FEATURE_NAMES, HORIZON, LOOKBACK, SequenceBatch
from .split import frozen_evaluation_origins, interval_bounds


MIN_TRAIN_DENSE_SAMPLES = 1000
MIN_VALIDATION_DENSE_SAMPLES = 168
MIN_VALIDATION_EVALUATION_WINDOWS = 12
MIN_TEST_EVALUATION_WINDOWS = 12


@dataclass
class PreparedSequenceData:
    """The exact sequence batches shared by diagnosis and model training."""

    train_dense: SequenceBatch
    validation_dense: SequenceBatch
    validation_evaluation: SequenceBatch
    test_evaluation: SequenceBatch
    validation_excluded: list[dict[str, str]]
    test_excluded: list[dict[str, str]]
    availability: dict[str, Any]


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


def _dense_candidate_count(plan, split_name: str) -> int:
    start, end = interval_bounds(plan, split_name)
    last_target_start = end - pd.Timedelta(hours=HORIZON)
    if last_target_start < start:
        return 0
    return len(pd.date_range(start, last_target_start, freq="h"))


def minimum_sample_reason_codes(
    train_dense: SequenceBatch,
    validation_dense: SequenceBatch,
    validation_nonoverlap: SequenceBatch,
    test_nonoverlap: SequenceBatch,
) -> list[str]:
    reasons: list[str] = []
    if len(train_dense.x) < MIN_TRAIN_DENSE_SAMPLES:
        reasons.append("FAIL_MINIMUM_TRAIN_SAMPLES_1000")
    if len(validation_dense.x) < MIN_VALIDATION_DENSE_SAMPLES:
        reasons.append("FAIL_MINIMUM_VALIDATION_DENSE_SAMPLES_168")
    if len(validation_nonoverlap.x) < MIN_VALIDATION_EVALUATION_WINDOWS:
        reasons.append("FAIL_MINIMUM_VALIDATION_NONOVERLAP_12")
    if len(test_nonoverlap.x) < MIN_TEST_EVALUATION_WINDOWS:
        reasons.append("FAIL_MINIMUM_TEST_NONOVERLAP_12")
    return reasons


def prepare_sequence_data(
    features: pd.DataFrame,
    targets: pd.Series,
    plan,
) -> PreparedSequenceData:
    """Build and count only complete causal 168+24 hour samples.

    Missing timestamps and non-finite values are never imputed. A candidate is
    retained only when the complete input and target window is usable.
    """
    train_dense = make_sequences(features, targets, plan, "train")
    validation_dense = make_sequences(features, targets, plan, "validation")
    validation_origins, validation_excluded = frozen_evaluation_origins(
        plan, "validation", targets.index
    )
    test_origins, test_excluded = frozen_evaluation_origins(plan, "test", targets.index)
    validation_evaluation = make_sequences(
        features, targets, plan, "validation", origins=validation_origins
    )
    test_evaluation = make_sequences(
        features, targets, plan, "test", origins=test_origins
    )

    train_candidates = _dense_candidate_count(plan, "train")
    validation_candidates = _dense_candidate_count(plan, "validation")
    validation_evaluation_candidates = len(validation_origins) + len(validation_excluded)
    test_evaluation_candidates = len(test_origins) + len(test_excluded)
    reasons = minimum_sample_reason_codes(
        train_dense,
        validation_dense,
        validation_evaluation,
        test_evaluation,
    )
    availability = {
        "status": "FAIL" if reasons else "PASS",
        "reason_codes": reasons,
        "splits": {
            "train": {
                "sample_mode": "dense",
                "candidate_count": train_candidates,
                "valid_count": len(train_dense.x),
                "excluded_count": train_candidates - len(train_dense.x),
                "minimum_required": MIN_TRAIN_DENSE_SAMPLES,
            },
            "validation": {
                "sample_mode": "dense",
                "candidate_count": validation_candidates,
                "valid_count": len(validation_dense.x),
                "excluded_count": validation_candidates - len(validation_dense.x),
                "minimum_required": MIN_VALIDATION_DENSE_SAMPLES,
                "evaluation": {
                    "sample_mode": "nonoverlap_24h",
                    "candidate_count": validation_evaluation_candidates,
                    "valid_count": len(validation_evaluation.x),
                    "excluded_count": (
                        validation_evaluation_candidates - len(validation_evaluation.x)
                    ),
                    "minimum_required": MIN_VALIDATION_EVALUATION_WINDOWS,
                },
            },
            "test": {
                "sample_mode": "nonoverlap_24h",
                "candidate_count": test_evaluation_candidates,
                "valid_count": len(test_evaluation.x),
                "excluded_count": test_evaluation_candidates - len(test_evaluation.x),
                "minimum_required": MIN_TEST_EVALUATION_WINDOWS,
            },
        },
    }
    return PreparedSequenceData(
        train_dense=train_dense,
        validation_dense=validation_dense,
        validation_evaluation=validation_evaluation,
        test_evaluation=test_evaluation,
        validation_excluded=validation_excluded,
        test_excluded=test_excluded,
        availability=availability,
    )


def validate_minimum_samples(
    train_dense: SequenceBatch,
    validation_dense: SequenceBatch,
    validation_nonoverlap: SequenceBatch,
    test_nonoverlap: SequenceBatch,
) -> None:
    """Apply the Phase 6-5 provisional 1000/168/12/12 thresholds."""
    reasons = minimum_sample_reason_codes(
        train_dense,
        validation_dense,
        validation_nonoverlap,
        test_nonoverlap,
    )
    if reasons:
        raise ValueError(reasons[0])
