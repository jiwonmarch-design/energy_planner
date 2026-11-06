from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.app.ml.artifacts import load_patchtst_artifacts, save_run_artifacts
from backend.app.ml.contracts import (
    ENSEMBLE_50_50,
    PATCHTST,
    XGBOOST,
    PatchTSTConfig,
    TrainingConfig,
)
from backend.app.ml.evaluate import evaluate_predictions, select_on_validation
from backend.app.ml.inference import predict_from_run
from backend.app.ml.patchtst import PatchTSTScaler, create_patchtst_model
from backend.app.ml.quality import diagnose_quality, validate_and_normalize_frame
from backend.app.ml.split import make_split_plan
from backend.app.ml.train import run_training_pipeline
from backend.app.web.service import TrainingJobManager
from backend.tests.ml.synthetic import hourly_frame


CANDIDATES = {XGBOOST, PATCHTST, ENSEMBLE_50_50, "last_24h", "last_168h"}


class ConstantRegressor:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, x):
        return np.full(len(x), self.value, dtype=float)


def fast_xgboost_config() -> TrainingConfig:
    return dataclasses.replace(
        TrainingConfig(),
        n_estimators=2,
        early_stopping_rounds=1,
        max_depth=2,
    )


def fast_patchtst_config() -> PatchTSTConfig:
    return dataclasses.replace(
        PatchTSTConfig(),
        d_model=8,
        n_heads=2,
        encoder_layers=1,
        dim_feedforward=16,
        dropout=0.0,
        epochs=2,
        batch_size=128,
        patience=2,
    )


class PatchTSTPipelineCases(unittest.TestCase):
    def test_revin_model_preserves_input_level_shift(self):
        config = dataclasses.replace(
            fast_patchtst_config(),
            use_revin=True,
            revin_affine=True,
        )
        model = create_patchtst_model(config)
        model.eval()
        base = np.linspace(1.0, 5.0, 168, dtype=np.float32)[None, :]
        shifted = base + 17.0

        import torch

        with torch.inference_mode():
            base_prediction = model(torch.from_numpy(base)).numpy()
            shifted_prediction = model(torch.from_numpy(shifted)).numpy()
        np.testing.assert_allclose(
            shifted_prediction - base_prediction,
            17.0,
            atol=2e-5,
        )

    def test_new_patchtst_defaults_use_revin_and_overlapping_patches(self):
        config = PatchTSTConfig()
        self.assertTrue(config.use_revin)
        self.assertTrue(config.revin_affine)
        self.assertLess(config.stride, config.patch_length)
        self.assertEqual((config.lookback - config.patch_length) % config.stride, 0)

    def test_selection_chooses_lowest_mae_eligible_candidate_and_keeps_tie_order(self):
        actual = np.full((12, 24), 10.0)
        baseline = evaluate_predictions(actual, actual + 2.0)
        xgboost = evaluate_predictions(actual, actual + 1.0)
        patchtst = evaluate_predictions(actual, actual + 0.5)
        ensemble = evaluate_predictions(actual, actual + 0.75)

        selected = select_on_validation(
            xgboost, baseline, baseline, patchtst, ensemble
        )
        self.assertEqual(selected.selected_model, PATCHTST)
        self.assertEqual(
            selected.eligible_candidates,
            [XGBOOST, PATCHTST, ENSEMBLE_50_50],
        )

        tie = select_on_validation(xgboost, baseline, baseline, xgboost, xgboost)
        self.assertEqual(tie.selected_model, XGBOOST)

    def test_patchtst_and_ensemble_artifacts_reload_for_inference(self):
        frame = hourly_frame(90)
        data = validate_and_normalize_frame(
            frame,
            "Asia/Seoul",
            source_timezone_mode="explicit_offset",
        )
        quality = diagnose_quality(data)
        plan = make_split_plan(data.index, quality.status, warning_approved=True)
        patch_config = fast_patchtst_config()
        model = create_patchtst_model(patch_config)
        for parameter in model.parameters():
            parameter.data.zero_()
        scaler = PatchTSTScaler(mean=20.0, scale=5.0)
        xgboost_models = [ConstantRegressor(10.0) for _ in range(24)]
        patch_expected = float(data["kwh"].iloc[-168:].mean())

        with tempfile.TemporaryDirectory() as temporary:
            for model_kind, expected in (
                (PATCHTST, patch_expected),
                (ENSEMBLE_50_50, (10.0 + patch_expected) / 2.0),
            ):
                run = save_run_artifacts(
                    temporary,
                    building_id="building-a",
                    run_id=f"run-{model_kind}",
                    model_kind=model_kind,
                    building_timezone="Asia/Seoul",
                    training_config=fast_xgboost_config(),
                    patchtst_config=patch_config,
                    split_manifest=dataclasses.asdict(plan),
                    evaluation_schedule={"frozen_before_training": True},
                    quality_report=quality,
                    validation_metrics={},
                    test_metrics={},
                    selection={"selected_model": model_kind},
                    data_hash="synthetic",
                    xgboost_models=xgboost_models,
                    patchtst_model=model,
                    patchtst_scaler=scaler,
                    patchtst_history=[],
                )
                result = predict_from_run(
                    run,
                    building_id="building-a",
                    normalized_data=data,
                )
                self.assertEqual(result.model_kind, model_kind)
                self.assertEqual(result.output_shape, (1, 24))
                np.testing.assert_allclose(result.predictions_kwh, expected, atol=1e-6)
                self.assertFalse(result.retrained)

    def test_pre_revin_patchtst_config_remains_loadable(self):
        frame = hourly_frame(90)
        data = validate_and_normalize_frame(
            frame,
            "Asia/Seoul",
            source_timezone_mode="explicit_offset",
        )
        quality = diagnose_quality(data)
        plan = make_split_plan(data.index, quality.status, warning_approved=True)
        legacy_config = dataclasses.replace(
            fast_patchtst_config(),
            stride=24,
            use_revin=False,
            revin_affine=False,
            gradient_clip_norm=None,
        )
        model = create_patchtst_model(legacy_config)
        scaler = PatchTSTScaler(mean=20.0, scale=5.0)

        with tempfile.TemporaryDirectory() as temporary:
            run = save_run_artifacts(
                temporary,
                building_id="legacy-building",
                run_id="legacy-run",
                model_kind=PATCHTST,
                building_timezone="Asia/Seoul",
                training_config=fast_xgboost_config(),
                patchtst_config=legacy_config,
                split_manifest=dataclasses.asdict(plan),
                evaluation_schedule={"frozen_before_training": True},
                quality_report=quality,
                validation_metrics={},
                test_metrics={},
                selection={"selected_model": PATCHTST},
                data_hash="synthetic",
                patchtst_model=model,
                patchtst_scaler=scaler,
                patchtst_history=[],
            )
            config_path = run / "patchtst_config.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            for name in (
                "use_revin",
                "revin_affine",
                "revin_epsilon",
                "gradient_clip_norm",
            ):
                payload.pop(name)
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            manifest_path = run / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            import hashlib

            manifest["file_sha256"]["patchtst_config.json"] = hashlib.sha256(
                config_path.read_bytes()
            ).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            _, loaded_config, state_dict, _ = load_patchtst_artifacts(
                run,
                expected_building_id="legacy-building",
            )
            self.assertFalse(loaded_config.use_revin)
            self.assertFalse(loaded_config.revin_affine)
            self.assertIsNone(loaded_config.gradient_clip_norm)
            loaded = create_patchtst_model(loaded_config)
            loaded.load_state_dict(state_dict, strict=True)

    def test_training_job_runs_two_models_five_candidates_and_reload_prediction(self):
        csv_text = hourly_frame(90).to_csv(index=False)

        def fast_pipeline(frame, **kwargs):
            return run_training_pipeline(
                frame,
                config=fast_xgboost_config(),
                patchtst_config=fast_patchtst_config(),
                **kwargs,
            )

        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=fast_pipeline)
            job = manager.submit(
                building_id="synthetic-building",
                csv_text=csv_text,
                building_timezone="Asia/Seoul",
                source_timezone_mode="explicit_offset",
                warning_approved=True,
                start_background=False,
            )
            manager._run(job.job_id, warning_approved=True)
            completed = manager.get(job.job_id)
            self.assertEqual(completed.status, "COMPLETED", completed.error)
            self.assertEqual(set(completed.validation_metrics or {}), CANDIDATES)
            self.assertEqual(set(completed.test_metrics or {}), CANDIDATES)
            self.assertIn(completed.selected_model, CANDIDATES)
            self.assertEqual(set(completed.model_training_seconds or {}), {XGBOOST, PATCHTST})

            schedule = json.loads(
                (Path(completed.run_dir) / "evaluation_schedule.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(schedule["frozen_before_training"])
            self.assertEqual(len(schedule["validation_origins"]), 15)
            self.assertEqual(len(schedule["test_origins"]), 15)

            first = manager.predict(job.job_id, "")
            recovered = TrainingJobManager(temporary, pipeline=fast_pipeline)
            second = recovered.predict(job.job_id, "")
            self.assertEqual(first["model_kind"], completed.selected_model)
            self.assertEqual(second["model_kind"], completed.selected_model)
            np.testing.assert_allclose(
                first["predictions_kwh"], second["predictions_kwh"], atol=1e-6
            )
            self.assertEqual(len(second["predictions_kwh"]), 24)


if __name__ == "__main__":
    unittest.main()
