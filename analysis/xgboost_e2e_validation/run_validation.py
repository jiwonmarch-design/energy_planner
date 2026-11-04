"""One-shot 180-day synthetic CSV validation for the production XGBoost pipeline."""

from __future__ import annotations

import json
import math
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.app.ml.artifacts import load_manifest, load_xgboost_artifacts
from backend.app.ml.contracts import LOOKBACK, TrainingConfig, to_jsonable
from backend.app.ml.features import build_features
from backend.app.ml.inference import predict_from_run
from backend.app.ml.quality import load_csv_frame, validate_and_normalize_frame
from backend.app.ml.train import predict_xgboost, run_training_pipeline_from_csv
from backend.tests.ml.benchmark_phase7 import memory_bytes
from backend.tests.ml.synthetic import hourly_frame


ROOT = Path(__file__).resolve().parent
RESULT_PATH = ROOT / "results.json"


def main() -> None:
    frame = hourly_frame(180)
    config = TrainingConfig()
    started = time.perf_counter()
    start_working, _ = memory_bytes()

    with tempfile.TemporaryDirectory(prefix="energy-planner-xgb-") as temporary:
        temporary_path = Path(temporary)
        csv_path = temporary_path / "synthetic_180_days.csv"
        frame.to_csv(csv_path, index=False)

        outcome = run_training_pipeline_from_csv(
            csv_path,
            building_id="synthetic-xgboost-180d",
            building_timezone="Asia/Seoul",
            artifact_root=temporary_path / "artifacts",
            run_id="xgboost-e2e-validation",
            config=config,
        )
        manifest = load_manifest(
            outcome.run_dir, expected_building_id="synthetic-xgboost-180d"
        )
        evaluation_schedule = json.loads(
            (outcome.run_dir / "evaluation_schedule.json").read_text(encoding="utf-8")
        )
        _, loaded_config, models = load_xgboost_artifacts(
            outcome.run_dir, expected_building_id="synthetic-xgboost-180d"
        )

        normalized = validate_and_normalize_frame(load_csv_frame(csv_path), "Asia/Seoul")
        latest = normalized.iloc[-LOOKBACK:]
        x = build_features(latest, "Asia/Seoul").to_numpy(dtype=np.float32)[None, :, :]
        candidate_started = time.perf_counter()
        candidate_prediction = predict_xgboost(models, x)
        candidate_inference_seconds = time.perf_counter() - candidate_started

        selected_started = time.perf_counter()
        selected_prediction = predict_from_run(
            outcome.run_dir,
            building_id="synthetic-xgboost-180d",
            normalized_data=normalized,
        )
        selected_inference_seconds = time.perf_counter() - selected_started
        current_working, peak_working = memory_bytes()

        checks = {
            "pipeline_completed": outcome.output_shape[1] == 24,
            "xgboost_candidate_saved": bool(manifest["xgboost_candidate_saved"]),
            "xgboost_models_reloaded": len(models) == 24,
            "config_reloaded": asdict(loaded_config) == asdict(config),
            "candidate_output_shape": candidate_prediction.shape == (1, 24),
            "candidate_output_finite": bool(np.isfinite(candidate_prediction).all()),
            "selected_output_shape": selected_prediction.output_shape == (1, 24),
            "selected_output_finite": all(
                math.isfinite(value) for value in selected_prediction.predictions_kwh
            ),
            "selected_inference_did_not_retrain": not selected_prediction.retrained,
            "validation_has_three_models": set(outcome.validation_metrics)
            == {"xgboost", "last_24h", "last_168h"},
            "test_has_three_models": set(outcome.test_metrics)
            == {"xgboost", "last_24h", "last_168h"},
            "evaluation_schedule_frozen": bool(
                evaluation_schedule["frozen_before_training"]
            ),
        }
        if not all(checks.values()):
            raise RuntimeError(f"XGBoost validation failed: {checks}")

        result = {
            "status": "PASS",
            "environment": {
                "xgboost": manifest["environment"]["xgboost"],
                "config": asdict(config),
                "source": "generated 180-day hourly CSV",
            },
            "pipeline": {
                **to_jsonable(outcome),
                "run_dir": "<temporary>/artifacts/synthetic-xgboost-180d/xgboost-e2e-validation",
            },
            "candidate_prediction": {
                "shape": list(candidate_prediction.shape),
                "minimum_kwh": float(candidate_prediction.min()),
                "maximum_kwh": float(candidate_prediction.max()),
                "mean_kwh": float(candidate_prediction.mean()),
                "inference_seconds": candidate_inference_seconds,
            },
            "selected_prediction": {
                **to_jsonable(selected_prediction),
                "predictions_kwh": {
                    "count": len(selected_prediction.predictions_kwh),
                    "minimum": min(selected_prediction.predictions_kwh),
                    "maximum": max(selected_prediction.predictions_kwh),
                    "mean": sum(selected_prediction.predictions_kwh)
                    / len(selected_prediction.predictions_kwh),
                },
                "inference_seconds": selected_inference_seconds,
            },
            "resources": {
                "total_seconds": time.perf_counter() - started,
                "working_set_start_bytes": start_working,
                "working_set_end_bytes": current_working,
                "peak_working_set_bytes": peak_working,
            },
            "checks": checks,
        }
        RESULT_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
