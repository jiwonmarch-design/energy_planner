"""Deterministic synthetic hourly fixtures used only by Phase 7 tests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def hourly_frame(days: int, *, start: str = "2025-01-01T00:00:00Z", constant: float | None = None) -> pd.DataFrame:
    hours = days * 24
    index = pd.date_range(start, periods=hours, freq="h")
    if constant is None:
        position = np.arange(hours)
        values = (
            20.0
            + 5.0 * np.sin(2 * np.pi * position / 24)
            + 2.0 * np.sin(2 * np.pi * position / 168)
            + (index.weekday < 5).astype(float) * 3.0
        )
    else:
        values = np.full(hours, constant, dtype=float)
    return pd.DataFrame({"timestamp": index.astype(str), "kwh": values.astype(float)})
