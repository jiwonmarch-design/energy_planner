"""Deterministic CPU XGBoost training and the end-to-end ML pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import numpy as np
import pandas as pd

from .contracts import HORIZON, SequenceBatch, TrainingConfig
from .model import create_xgboost_regressor, flatten_features


@dataclass
class TrainingOutcome:
    models: list[Any]
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


def train_xgboost(
    train: SequenceBatch,
    validation: SequenceBatch,
    config: TrainingConfig = TrainingConfig(),
    progress_callback: Callable[[int, int], None] | None = None,
) -> TrainingOutcome:
    """Train one deterministic regressor for each of the 24 forecast hours."""
    if len(train.x) == 0 or len(validation.x) == 0:
        raise ValueError("training and validation samples are required")
    train_x = flatten_features(train.x)
    validation_x = flatten_features(validation.x)
    train_y = np.asarray(train.y, dtype=np.float32)
    validation_y = np.asarray(validation.y, dtype=np.float32)
    if train_y.shape != (len(train_x), HORIZON) or validation_y.shape != (
        len(validation_x),
        HORIZON,
    ):
        raise ValueError("expected y shape [B,24]")

    models: list[Any] = []
    history: list[dict[str, float | int]] = []
    best_iterations: list[int] = []
    stopped_iterations: list[int] = []
    best_losses: list[float] = []
    for horizon in range(HORIZON):
        model = create_xgboost_regressor(config)
        model.fit(
            train_x,
            train_y[:, horizon],
            eval_set=[(validation_x, validation_y[:, horizon])],
            verbose=False,
        )
        results = model.evals_result().get("validation_0", {}).get("mae", [])
        if not results or not np.isfinite(results).all():
            raise RuntimeError("training did not produce finite validation metrics")
        best_iteration = int(getattr(model, "best_iteration", int(np.argmin(results))))
        best_loss = float(results[best_iteration])
        stopped_iteration = len(results) - 1
        models.append(model)
        best_iterations.append(best_iteration)
        stopped_iterations.append(stopped_iteration)
        best_losses.append(best_loss)
        history.append(
            {
                "horizon": horizon + 1,
                "best_iteration": best_iteration,
                "stopped_iteration": stopped_iteration,
                "best_validation_mae": best_loss,
            }
        )
        if progress_callback is not None:
            progress_callback(horizon + 1, HORIZON)
    return TrainingOutcome(
        models=models,
        best_epoch=max(best_iterations),
        stopped_epoch=max(stopped_iterations),
        best_validation_loss=float(np.mean(best_losses)),
        history=history,
    )


def predict_xgboost(models: list[Any], x: np.ndarray) -> np.ndarray:
    if len(models) != HORIZON:
        raise RuntimeError(f"expected {HORIZON} XGBoost horizon models")
    table = flatten_features(x)
    result = np.column_stack([model.predict(table) for model in models]).astype(float)
    if result.shape != (len(x), HORIZON) or not np.isfinite(result).all():
        raise RuntimeError("invalid XGBoost output")
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
    progress_callback: Callable[[int, str], None] | None = None,
) -> PipelineOutcome:
    """Train and evaluate an XGBoost candidate without promotion or retraining."""
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
    from .sequences import make_sequences, validate_minimum_samples
    from .split import frozen_evaluation_origins, make_split_plan

    def report_progress(percent: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, message)

    total_started = perf_counter()
    report_progress(10, "입력 데이터와 시간대를 검증하고 있습니다.")
    data = validate_and_normalize_frame(
        frame, building_timezone, source_timezone_mode=source_timezone_mode
    )
    quality = diagnose_quality(data)
    plan = make_split_plan(data.index, quality.status, warning_approved=warning_approved)
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
    data_preparation_seconds = perf_counter() - total_started
    report_progress(25, "학습·Validation·Test 데이터를 준비했습니다.")

    training_started = perf_counter()
    outcome = train_xgboost(
        train_dense,
        validation_dense,
        config,
        progress_callback=lambda completed, total: report_progress(
            25 + round(completed / total * 50),
            f"24개 예측 시점별 XGBoost 모델을 학습하고 있습니다. ({completed}/{total})",
        ),
    )
    training_seconds = perf_counter() - training_started

    report_progress(80, "Validation 성능으로 후보 모델을 비교하고 있습니다.")
    validation_predictions = {
        "xgboost": predict_xgboost(outcome.models, validation_eval.x),
        LAST_24H: baseline_predictions(data.kwh, validation_eval.origins, LAST_24H),
        LAST_168H: baseline_predictions(data.kwh, validation_eval.origins, LAST_168H),
    }
    validation_metrics_objects = {
        name: evaluate_predictions(validation_eval.y, values)
        for name, values in validation_predictions.items()
    }
    selection = select_on_validation(
        validation_metrics_objects["xgboost"],
        validation_metrics_objects[LAST_24H],
        validation_metrics_objects[LAST_168H],
    )

    report_progress(88, "선택 모델의 Test 성능을 최종 평가하고 있습니다.")
    test_predictions = {
        "xgboost": predict_xgboost(outcome.models, test_eval.x),
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
    canonical_input["timestamp"] = canonical_input["timestamp"].map(
        lambda value: value.isoformat()
    )
    report_progress(95, "모델과 평가 산출물을 저장하고 있습니다.")
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
        xgboost_models=outcome.models,
        training_history=outcome.history,
        derived_input_csv=canonical_input.to_csv(index=False).encode("utf-8"),
        source_timezone_mode=source_timezone_mode,
        source_timezone_metadata=source_timezone_metadata,
    )
    artifact_save_seconds = perf_counter() - artifact_started
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
        total_seconds=perf_counter() - total_started,
    )


def run_training_pipeline_from_csv(csv_path: str | Path, **pipeline_options) -> PipelineOutcome:
    from .quality import load_csv_frame

    return run_training_pipeline(load_csv_frame(csv_path), **pipeline_options)
