"""Forecast metrics and validation-only deterministic model selection."""

from __future__ import annotations

import numpy as np

from .baselines import LAST_168H, LAST_24H
from .contracts import EvaluationMetrics, SelectionDecision


def evaluate_predictions(actual: np.ndarray, predicted: np.ndarray) -> EvaluationMetrics:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or actual.ndim != 2 or actual.shape[1] != 24:
        raise ValueError("actual and predicted must have matching [N,24] shapes")
    finite = np.isfinite(predicted)
    nonfinite_count = int((~finite).sum())
    safe = np.where(finite, predicted, 0.0)
    error = safe - actual
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(np.square(error))))
    denominator = float(np.abs(actual).sum())
    wape = None if denominator == 0 else float(np.abs(error).sum() / denominator)
    nonzero = actual != 0
    mape = float(np.mean(np.abs(error[nonzero] / actual[nonzero]))) if nonzero.any() else None
    actual_peaks = np.argmax(actual, axis=1)  # first occurrence resolves ties
    predicted_peaks = np.argmax(safe, axis=1)
    actual_peak_values = actual[np.arange(len(actual)), actual_peaks]
    predicted_peak_values = safe[np.arange(len(actual)), predicted_peaks]
    return EvaluationMetrics(
        mae=mae,
        rmse=rmse,
        wape=wape,
        mape=mape,
        mape_excluded_count=int((~nonzero).sum()),
        peak_mae=float(np.mean(np.abs(predicted_peak_values - actual_peak_values))),
        peak_time_error_hours=float(np.mean(np.abs(predicted_peaks - actual_peaks))),
        prediction_min=float(np.min(safe)),
        prediction_max=float(np.max(safe)),
        prediction_mean=float(np.mean(safe)),
        negative_count=int((safe < 0).sum()),
        nonfinite_count=nonfinite_count,
    )


def select_on_validation(
    gru: EvaluationMetrics,
    last_24h: EvaluationMetrics,
    last_168h: EvaluationMetrics,
) -> SelectionDecision:
    # Deterministic tie rule: prefer Last-24h because it needs less history.
    tolerance = 1e-12
    if last_24h.mae <= last_168h.mae + tolerance:
        baseline_name, baseline = LAST_24H, last_24h
    else:
        baseline_name, baseline = LAST_168H, last_168h
    reasons: list[str] = []
    if baseline.mae <= 0:
        improvement = None
        mae_ok = False
        reasons.append("GRU_5_PERCENT_MAE_IMPROVEMENT_UNDEFINED_AT_ZERO_BASELINE")
    else:
        improvement = (baseline.mae - gru.mae) / baseline.mae
        mae_ok = improvement >= 0.05 - tolerance
        if not mae_ok:
            reasons.append("GRU_MAE_IMPROVEMENT_BELOW_5_PERCENT")
    rmse_ok = gru.rmse <= baseline.rmse * 1.05 + tolerance
    if not rmse_ok:
        reasons.append("GRU_RMSE_DEGRADED_OVER_5_PERCENT")
    if gru.wape is None or baseline.wape is None:
        wape_ok = False
        reasons.append("WAPE_UNDEFINED_BASELINE_SELECTED")
    else:
        wape_ok = gru.wape <= baseline.wape * 1.05 + tolerance
        if not wape_ok:
            reasons.append("GRU_WAPE_DEGRADED_OVER_5_PERCENT")
    valid_ok = gru.nonfinite_count == 0 and gru.negative_count == 0
    if gru.nonfinite_count:
        reasons.append("GRU_NONFINITE_PREDICTION")
    if gru.negative_count:
        reasons.append("GRU_NEGATIVE_PREDICTION")
    eligible = mae_ok and rmse_ok and wape_ok and valid_ok
    if eligible:
        reasons.append("GRU_VALIDATION_PROMOTION_RULES_MET")
    else:
        reasons.append("BEST_BASELINE_SELECTED")
    return SelectionDecision(
        selected_model="gru" if eligible else baseline_name,
        best_baseline=baseline_name,
        gru_eligible=eligible,
        reason_codes=reasons,
        gru_mae_improvement=improvement,
    )
