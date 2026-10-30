"""Deterministic CPU training with early stopping."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .contracts import SequenceBatch, TrainingConfig
from .model import GRUForecaster, set_deterministic_seed


@dataclass
class TrainingOutcome:
    state_dict: dict[str, torch.Tensor]
    best_epoch: int
    stopped_epoch: int
    best_validation_loss: float
    history: list[dict[str, float | int]]


@dataclass
class PipelineOutcome:
    run_dir: Path
    quality_status: str
    selected_model: str
    train_samples: int
    validation_dense_samples: int
    validation_evaluation_windows: int
    test_evaluation_windows: int
    input_shape: tuple[int, int, int]
    output_shape: tuple[int, int]
    best_epoch: int
    stopped_epoch: int
    validation_metrics: dict[str, Any]
    test_metrics: dict[str, Any]
    data_preparation_seconds: float
    training_seconds: float
    artifact_save_seconds: float
    total_seconds: float


def _loader(batch: SequenceBatch, batch_size: int, shuffle: bool, seed: int) -> DataLoader:
    dataset = TensorDataset(torch.from_numpy(batch.x), torch.from_numpy(batch.y))
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        generator=generator,
        num_workers=0,
    )


def _mean_loss(model: nn.Module, loader: DataLoader, loss_fn: nn.Module) -> float:
    total = 0.0
    count = 0
    model.eval()
    with torch.inference_mode():
        for x, y in loader:
            loss = loss_fn(model(x), y)
            if not torch.isfinite(loss):
                raise RuntimeError("non-finite validation loss")
            total += float(loss) * len(x)
            count += len(x)
    if count == 0:
        raise ValueError("validation set is empty")
    return total / count


def train_gru(
    train: SequenceBatch,
    validation: SequenceBatch,
    config: TrainingConfig = TrainingConfig(),
) -> TrainingOutcome:
    if config.device != "cpu":
        raise ValueError("Phase 7 implementation supports CPU only")
    if len(train.x) == 0 or len(validation.x) == 0:
        raise ValueError("training and validation samples are required")
    set_deterministic_seed(config.seed)
    model = GRUForecaster(config)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    loss_fn = nn.L1Loss()
    train_loader = _loader(train, config.batch_size, True, config.seed)
    validation_loader = _loader(validation, config.batch_size, False, config.seed)
    best_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    stale = 0
    history: list[dict[str, float | int]] = []
    stopped_epoch = 0
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        total = 0.0
        count = 0
        for x, y in train_loader:
            optimizer.zero_grad(set_to_none=True)
            prediction = model(x)
            loss = loss_fn(prediction, y)
            if not torch.isfinite(loss):
                raise RuntimeError("non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip)
            optimizer.step()
            total += float(loss.detach()) * len(x)
            count += len(x)
        validation_loss = _mean_loss(model, validation_loader, loss_fn)
        train_loss = total / count
        history.append({"epoch": epoch, "train_loss": train_loss, "validation_loss": validation_loss})
        if best_loss - validation_loss >= config.min_delta:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = deepcopy({key: value.detach().cpu() for key, value in model.state_dict().items()})
            stale = 0
        else:
            stale += 1
        stopped_epoch = epoch
        if stale >= config.patience:
            break
    if best_state is None or not np.isfinite(best_loss):
        raise RuntimeError("training did not produce a finite checkpoint")
    return TrainingOutcome(best_state, best_epoch, stopped_epoch, best_loss, history)


def predict_gru(
    state_dict: dict[str, torch.Tensor],
    x: np.ndarray,
    config: TrainingConfig = TrainingConfig(),
) -> np.ndarray:
    model = GRUForecaster(config)
    model.load_state_dict(state_dict, strict=True)
    model.eval()
    with torch.inference_mode():
        result = model(torch.from_numpy(np.asarray(x, dtype=np.float32))).cpu().numpy()
    if result.shape != (len(x), config.output_size) or not np.isfinite(result).all():
        raise RuntimeError("invalid GRU output")
    return result


def run_training_pipeline(
    frame,
    *,
    building_id: str,
    building_timezone: str,
    artifact_root: str | Path,
    run_id: str,
    warning_approved: bool = False,
    config: TrainingConfig = TrainingConfig(),
    source_timezone_mode="iana_civil_time",
    source_timezone_metadata: str | None = None,
) -> PipelineOutcome:
    """Run the approved standalone pipeline without promotion or retraining.

    The caller must explicitly approve 90-179 day limited experiments. The
    returned run always remains a candidate; this function never writes an
    active-model pointer.
    """
    from .artifacts import save_run_artifacts
    from .baselines import LAST_168H, LAST_24H, baseline_predictions
    from .contracts import to_jsonable
    from .evaluate import evaluate_predictions, select_on_validation
    from .features import build_features
    from .quality import (
        diagnose_quality,
        diagnose_split_distribution,
        enforce_train_variance,
        validate_and_normalize_frame,
    )
    from .scaling import ScalerBundle
    from .sequences import make_sequences, validate_minimum_samples
    from .split import frozen_evaluation_origins, make_split_plan

    total_started = perf_counter()
    data = validate_and_normalize_frame(
        frame, building_timezone, source_timezone_mode=source_timezone_mode
    )
    quality = diagnose_quality(data)
    plan = make_split_plan(
        data.index, quality.status, warning_approved=warning_approved
    )
    distribution_report = diagnose_split_distribution(data, plan)
    enforce_train_variance(distribution_report)
    features = build_features(data, building_timezone)
    train_dense = make_sequences(features, data.kwh, plan, "train")
    validation_dense = make_sequences(features, data.kwh, plan, "validation")
    validation_origins, validation_excluded = frozen_evaluation_origins(
        plan, "validation", data.index
    )
    test_origins, test_excluded = frozen_evaluation_origins(plan, "test", data.index)
    validation_eval = make_sequences(
        features, data.kwh, plan, "validation", origins=validation_origins
    )
    test_eval = make_sequences(features, data.kwh, plan, "test", origins=test_origins)
    validate_minimum_samples(train_dense, validation_dense, validation_eval, test_eval)

    train_end = pd.Timestamp(plan.train_end)
    train_features = features.loc[
        (features.index >= pd.Timestamp(plan.train_start)) & (features.index < train_end)
    ]
    train_targets = data.kwh.loc[
        (data.index >= pd.Timestamp(plan.train_start)) & (data.index < train_end)
    ]
    scalers = ScalerBundle.fit(train_features, train_targets)
    train_scaled = scalers.transform_batch(train_dense)
    validation_dense_scaled = scalers.transform_batch(validation_dense)
    data_preparation_seconds = perf_counter() - total_started
    training_started = perf_counter()
    outcome = train_gru(train_scaled, validation_dense_scaled, config)
    training_seconds = perf_counter() - training_started

    validation_x = scalers.transform_x(validation_eval.x)
    validation_gru = scalers.inverse_y(predict_gru(outcome.state_dict, validation_x, config))
    validation_predictions = {
        "gru": validation_gru,
        LAST_24H: baseline_predictions(data.kwh, validation_eval.origins, LAST_24H),
        LAST_168H: baseline_predictions(data.kwh, validation_eval.origins, LAST_168H),
    }
    validation_metrics_objects = {
        name: evaluate_predictions(validation_eval.y, values)
        for name, values in validation_predictions.items()
    }
    selection = select_on_validation(
        validation_metrics_objects["gru"],
        validation_metrics_objects[LAST_24H],
        validation_metrics_objects[LAST_168H],
    )

    # Freeze the candidate before any Test prediction is created. All three Test
    # metrics may be reported, but are never passed back into selection.
    test_predictions = {
        "gru": scalers.inverse_y(
            predict_gru(outcome.state_dict, scalers.transform_x(test_eval.x), config)
        ),
        LAST_24H: baseline_predictions(data.kwh, test_eval.origins, LAST_24H),
        LAST_168H: baseline_predictions(data.kwh, test_eval.origins, LAST_168H),
    }
    validation_metrics = {
        name: to_jsonable(metric) for name, metric in validation_metrics_objects.items()
    }
    test_metrics = {
        name: to_jsonable(evaluate_predictions(test_eval.y, values))
        for name, values in test_predictions.items()
    }

    digest = sha256()
    for timestamp, value in data.kwh.items():
        digest.update(timestamp.isoformat().encode("utf-8"))
        digest.update(np.float64(value).tobytes())
    schedule = {
        "validation_origins": [value.isoformat() for value in validation_eval.origins],
        "test_origins": [value.isoformat() for value in test_eval.origins],
        "validation_excluded": validation_excluded,
        "test_excluded": test_excluded,
        "interval_hours": 24,
        "frozen_before_training": True,
    }
    canonical_input = data.rename_axis("timestamp").reset_index()
    canonical_input["timestamp"] = canonical_input["timestamp"].map(lambda value: value.isoformat())
    derived_input_csv = canonical_input.to_csv(index=False).encode("utf-8")
    artifact_started = perf_counter()
    run_dir = save_run_artifacts(
        artifact_root,
        building_id=building_id,
        run_id=run_id,
        model_kind=selection.selected_model,
        building_timezone=building_timezone,
        training_config=config,
        split_manifest=to_jsonable(plan),
        evaluation_schedule=schedule,
        quality_report=quality,
        distribution_report=distribution_report,
        validation_metrics=validation_metrics,
        test_metrics=test_metrics,
        selection=selection,
        data_hash=digest.hexdigest(),
        # Preserve the evaluated GRU candidate even when a baseline wins. The
        # manifest's model_kind remains the fixed Validation-selected predictor.
        state_dict=outcome.state_dict,
        scalers=scalers,
        training_history=outcome.history,
        derived_input_csv=derived_input_csv,
        source_timezone_mode=source_timezone_mode,
        source_timezone_metadata=source_timezone_metadata,
    )
    artifact_save_seconds = perf_counter() - artifact_started
    total_seconds = perf_counter() - total_started
    return PipelineOutcome(
        run_dir=run_dir,
        quality_status=quality.status.value,
        selected_model=selection.selected_model,
        train_samples=len(train_dense.x),
        validation_dense_samples=len(validation_dense.x),
        validation_evaluation_windows=len(validation_eval.x),
        test_evaluation_windows=len(test_eval.x),
        input_shape=tuple(train_dense.x.shape),
        output_shape=tuple(train_dense.y.shape),
        best_epoch=outcome.best_epoch,
        stopped_epoch=outcome.stopped_epoch,
        validation_metrics=validation_metrics,
        test_metrics=test_metrics,
        data_preparation_seconds=data_preparation_seconds,
        training_seconds=training_seconds,
        artifact_save_seconds=artifact_save_seconds,
        total_seconds=total_seconds,
    )


def run_training_pipeline_from_csv(
    csv_path: str | Path,
    **pipeline_options,
) -> PipelineOutcome:
    """CSV entry point for the standalone pipeline."""
    from .quality import load_csv_frame

    return run_training_pipeline(load_csv_frame(csv_path), **pipeline_options)
