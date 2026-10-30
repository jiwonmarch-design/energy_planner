"""Causal Last-24h and Last-168h baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import HORIZON


LAST_24H = "last_24h"
LAST_168H = "last_168h"


def baseline_predictions(
    targets: pd.Series,
    origins: pd.DatetimeIndex,
    model_name: str,
) -> np.ndarray:
    rows: list[np.ndarray] = []
    available = set(targets.index)
    for origin in origins:
        if model_name == LAST_24H:
            source = pd.date_range(origin - pd.Timedelta(hours=23), origin, freq="h")
        elif model_name == LAST_168H:
            target_start = origin + pd.Timedelta(hours=1)
            source = pd.date_range(target_start - pd.Timedelta(hours=168), periods=HORIZON, freq="h")
        else:
            raise ValueError(f"unknown baseline: {model_name}")
        if not all(ts in available for ts in source):
            raise ValueError(f"{model_name} source context is incomplete")
        rows.append(targets.loc[source].to_numpy(dtype=float))
    return np.stack(rows) if rows else np.empty((0, HORIZON), dtype=float)
