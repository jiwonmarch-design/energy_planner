"""Leakage-safe six-feature construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import FEATURE_NAMES, DataContractError


def build_features(data: pd.DataFrame, building_timezone: str) -> pd.DataFrame:
    """Create A-plan features without looking beyond each observation."""
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
        raise DataContractError("features require a timezone-aware UTC DatetimeIndex")
    local = data.index.tz_convert(building_timezone)
    hour = local.hour.to_numpy(dtype=float)
    weekday = local.weekday.to_numpy(dtype=float)
    result = pd.DataFrame(
        {
            "kwh": data["kwh"].to_numpy(dtype=float),
            "hour_sin": np.sin(2 * np.pi * hour / 24.0),
            "hour_cos": np.cos(2 * np.pi * hour / 24.0),
            "weekday_sin": np.sin(2 * np.pi * weekday / 7.0),
            "weekday_cos": np.cos(2 * np.pi * weekday / 7.0),
            "is_weekend": (weekday >= 5).astype(float),
        },
        index=data.index.copy(),
    )
    if tuple(result.columns) != FEATURE_NAMES:
        raise AssertionError("feature order does not match the model contract")
    if not np.isfinite(result.to_numpy()).all():
        raise DataContractError("features contain NaN or Inf")
    return result
