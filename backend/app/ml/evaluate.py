"""Forecast metrics and validation-only deterministic model selection."""

from __future__ import annotations

import numpy as np

from .baselines import LAST_168H, LAST_24H
from .contracts import (
    ENSEMBLE_50_50,
    PATCHTST,
    XGBOOST,
    EvaluationMetrics,
    SelectionDecision,
)


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
    xgboost: EvaluationMetrics,
    last_24h: EvaluationMetrics,
    last_168h: EvaluationMetrics,
    patchtst: EvaluationMetrics | None = None,
    ensemble_50_50: EvaluationMetrics | None = None,
) -> SelectionDecision:
    # Deterministic tie rule: prefer Last-24h because it needs less history.
    tolerance = 1e-12
    if last_24h.mae <= last_168h.mae + tolerance:
        baseline_name, baseline = LAST_24H, last_24h
    else:
        baseline_name, baseline = LAST_168H, last_168h
    candidates = {
        XGBOOST: xgboost,
        **({PATCHTST: patchtst} if patchtst is not None else {}),
        **({ENSEMBLE_50_50: ensemble_50_50} if ensemble_50_50 is not None else {}),
    }
    labels = {
        XGBOOST: "XGBOOST",
        PATCHTST: "PATCHTST",
        ENSEMBLE_50_50: "ENSEMBLE_50_50",
    }
    all_reasons: list[str] = []
    candidate_reasons: dict[str, list[str]] = {}
    improvements: dict[str, float | None] = {}
    eligible_candidates: list[str] = []

    for name, metrics in candidates.items():
        label = labels[name]
        reasons: list[str] = []
        if baseline.mae <= 0:
            improvement = None
            mae_ok = False
            reasons.append(f"{label}_5_PERCENT_MAE_IMPROVEMENT_UNDEFINED_AT_ZERO_BASELINE")
        else:
            improvement = (baseline.mae - metrics.mae) / baseline.mae
            mae_ok = improvement >= 0.05 - tolerance
            if not mae_ok:
                reasons.append(f"{label}_MAE_IMPROVEMENT_BELOW_5_PERCENT")
        rmse_ok = metrics.rmse <= baseline.rmse * 1.05 + tolerance
        if not rmse_ok:
            reasons.append(f"{label}_RMSE_DEGRADED_OVER_5_PERCENT")
        if metrics.wape is None or baseline.wape is None:
            wape_ok = False
            reasons.append("WAPE_UNDEFINED_BASELINE_SELECTED")
        else:
            wape_ok = metrics.wape <= baseline.wape * 1.05 + tolerance
            if not wape_ok:
                reasons.append(f"{label}_WAPE_DEGRADED_OVER_5_PERCENT")
        valid_ok = metrics.nonfinite_count == 0 and metrics.negative_count == 0
        if metrics.nonfinite_count:
            reasons.append(f"{label}_NONFINITE_PREDICTION")
        if metrics.negative_count:
            reasons.append(f"{label}_NEGATIVE_PREDICTION")
        eligible = mae_ok and rmse_ok and wape_ok and valid_ok
        if eligible:
            reasons.append(f"{label}_VALIDATION_PROMOTION_RULES_MET")
            eligible_candidates.append(name)
        improvements[name] = improvement
        candidate_reasons[name] = reasons
        all_reasons.extend(reason for reason in reasons if reason not in all_reasons)

    # Stable tie order preserves the previous XGBoost-first behavior, then
    # PatchTST, then the 50:50 ensemble.
    selected_model = baseline_name
    if eligible_candidates:
        selected_model = min(
            eligible_candidates,
            key=lambda name: (candidates[name].mae, list(candidates).index(name)),
        )
    else:
        all_reasons.append("BEST_BASELINE_SELECTED")
    return SelectionDecision(
        selected_model=selected_model,
        best_baseline=baseline_name,
        xgboost_eligible=XGBOOST in eligible_candidates,
        reason_codes=all_reasons,
        xgboost_mae_improvement=improvements[XGBOOST],
        eligible_candidates=eligible_candidates,
        candidate_reason_codes=candidate_reasons,
        candidate_mae_improvements=improvements,
    )
