"""XGBoost model construction and fixed sequence-to-table adaptation."""

from __future__ import annotations

import numpy as np

from .contracts import FEATURE_NAMES, LOOKBACK, TrainingConfig


def flatten_features(x: np.ndarray) -> np.ndarray:
    """Flatten causal [sample, 168, 6] windows without changing their order."""
    array = np.asarray(x, dtype=np.float32)
    expected = (LOOKBACK, len(FEATURE_NAMES))
    if array.ndim != 3 or array.shape[1:] != expected:
        raise ValueError(f"expected X shape [B,{expected[0]},{expected[1]}]")
    result = array.reshape(len(array), LOOKBACK * len(FEATURE_NAMES))
    if not np.isfinite(result).all():
        raise ValueError("XGBoost inputs contain NaN or Inf")
    return result


def create_xgboost_regressor(config: TrainingConfig):
    """Build the deterministic CPU regressor used for each forecast horizon."""
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise RuntimeError(
            "xgboost is required for model training; install backend/requirements.txt"
        ) from exc
    return XGBRegressor(
        objective="reg:squarederror",
        eval_metric="mae",
        n_estimators=config.n_estimators,
        learning_rate=config.learning_rate,
        max_depth=config.max_depth,
        min_child_weight=config.min_child_weight,
        subsample=config.subsample,
        colsample_bytree=config.colsample_bytree,
        reg_alpha=config.reg_alpha,
        reg_lambda=config.reg_lambda,
        early_stopping_rounds=config.early_stopping_rounds,
        random_state=config.seed,
        n_jobs=config.n_jobs,
        tree_method=config.tree_method,
        verbosity=0,
    )
