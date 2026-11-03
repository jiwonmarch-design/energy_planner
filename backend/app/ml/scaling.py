"""Train-only scaling retained for read-only legacy GRU run compatibility.

New XGBoost training uses raw engineered values and does not call this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from .contracts import EligibilityError, FEATURE_NAMES, HORIZON, LOOKBACK, SequenceBatch


@dataclass
class ScalerBundle:
    input_scaler: StandardScaler
    target_scaler: StandardScaler
    feature_names: tuple[str, ...] = FEATURE_NAMES
    warnings: tuple[str, ...] = ()

    @classmethod
    def fit(cls, train_features: pd.DataFrame, train_targets: pd.Series) -> "ScalerBundle":
        """Fit on unique Train timestamps, never on duplicated sequence rows."""
        if tuple(train_features.columns) != FEATURE_NAMES:
            raise ValueError("feature order mismatch")
        kwh = train_features[["kwh"]].to_numpy(dtype=float)
        targets = train_targets.to_numpy(dtype=float).reshape(-1, 1)
        if not np.isfinite(kwh).all() or not np.isfinite(targets).all():
            raise ValueError("scaler fit data contains NaN or Inf")
        input_scaler = StandardScaler().fit(kwh)
        target_scaler = StandardScaler().fit(targets)
        if float(input_scaler.var_[0]) == 0.0 or float(target_scaler.var_[0]) == 0.0:
            raise EligibilityError("FAIL_TRAIN_ZERO_VARIANCE")
        warnings: list[str] = []
        return cls(input_scaler, target_scaler, warnings=tuple(warnings))

    def transform_x(self, x: np.ndarray) -> np.ndarray:
        if x.ndim != 3 or x.shape[1:] != (LOOKBACK, len(FEATURE_NAMES)):
            raise ValueError(f"expected X shape [B,{LOOKBACK},{len(FEATURE_NAMES)}]")
        result = np.asarray(x, dtype=np.float32).copy()
        flat = result[:, :, 0].reshape(-1, 1)
        result[:, :, 0] = self.input_scaler.transform(flat).reshape(result.shape[:2])
        if not np.isfinite(result).all():
            raise ValueError("scaled inputs contain NaN or Inf")
        return result

    def transform_y(self, y: np.ndarray) -> np.ndarray:
        if y.ndim != 2 or y.shape[1] != HORIZON:
            raise ValueError(f"expected y shape [B,{HORIZON}]")
        result = self.target_scaler.transform(y.reshape(-1, 1)).reshape(y.shape).astype(np.float32)
        if not np.isfinite(result).all():
            raise ValueError("scaled targets contain NaN or Inf")
        return result

    def inverse_y(self, y: np.ndarray) -> np.ndarray:
        array = np.asarray(y, dtype=float)
        if array.ndim != 2 or array.shape[1] != HORIZON:
            raise ValueError(f"expected predictions shape [B,{HORIZON}]")
        result = self.target_scaler.inverse_transform(array.reshape(-1, 1)).reshape(array.shape)
        if not np.isfinite(result).all():
            raise ValueError("inverse-transformed predictions contain NaN or Inf")
        return result

    def transform_batch(self, batch: SequenceBatch) -> SequenceBatch:
        return SequenceBatch(
            x=self.transform_x(batch.x),
            y=self.transform_y(batch.y),
            origins=batch.origins,
            target_starts=batch.target_starts,
        )
