"""Reuse-only inference. This module never trains or refits a scaler."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .artifacts import load_gru_artifacts, load_manifest
from .baselines import LAST_168H, LAST_24H, baseline_predictions
from .contracts import ArtifactError, HORIZON, LOOKBACK
from .features import build_features
from .model import GRUForecaster


@dataclass
class InferenceResult:
    building_id: str
    run_id: str
    model_kind: str
    forecast_origin: str
    timestamps: list[str]
    predictions_kwh: list[float]
    input_shape: tuple[int, int, int]
    output_shape: tuple[int, int]
    retrained: bool = False


def predict_from_run(
    run_dir: str | Path,
    *,
    building_id: str,
    normalized_data: pd.DataFrame,
) -> InferenceResult:
    manifest = load_manifest(run_dir, expected_building_id=building_id)
    if len(normalized_data) < LOOKBACK:
        raise ValueError("latest 168 hours are not available")
    latest = pd.date_range(normalized_data.index[-1] - pd.Timedelta(hours=LOOKBACK - 1), periods=LOOKBACK, freq="h")
    if not latest.isin(normalized_data.index).all():
        raise ValueError("latest 168 hours are incomplete")
    origin = normalized_data.index[-1]
    model_kind = manifest["model_kind"]
    if model_kind == "gru":
        _, config, state_dict, scalers = load_gru_artifacts(
            run_dir, expected_building_id=building_id
        )
        features = build_features(normalized_data.loc[latest], manifest["building_timezone"])
        x = features.to_numpy(dtype=np.float32)[None, :, :]
        scaled = scalers.transform_x(x)
        model = GRUForecaster(config)
        model.load_state_dict(state_dict, strict=True)
        model.eval()
        import torch

        with torch.inference_mode():
            scaled_prediction = model(torch.from_numpy(scaled)).cpu().numpy()
        prediction = scalers.inverse_y(scaled_prediction)
    elif model_kind in {LAST_24H, LAST_168H}:
        prediction = baseline_predictions(normalized_data["kwh"], pd.DatetimeIndex([origin]), model_kind)
        x = np.empty((1, LOOKBACK, 6), dtype=np.float32)
    else:
        raise ArtifactError(f"unsupported model kind in manifest: {model_kind}")
    if prediction.shape != (1, HORIZON) or not np.isfinite(prediction).all():
        raise RuntimeError("inference output is invalid")
    if (prediction < 0).any():
        raise RuntimeError("negative forecasts are not permitted; no clipping was applied")
    timestamps = pd.date_range(origin + pd.Timedelta(hours=1), periods=HORIZON, freq="h")
    return InferenceResult(
        building_id=building_id,
        run_id=manifest["run_id"],
        model_kind=model_kind,
        forecast_origin=origin.isoformat(),
        timestamps=[value.isoformat() for value in timestamps],
        predictions_kwh=prediction[0].astype(float).tolist(),
        input_shape=tuple(x.shape),
        output_shape=tuple(prediction.shape),
        retrained=False,
    )
