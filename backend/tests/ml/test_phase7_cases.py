"""The 15 approved Phase 7 automatic validation cases."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch

from backend.app.ml.artifacts import load_gru_artifacts, save_run_artifacts
from backend.app.ml.baselines import LAST_168H, LAST_24H, baseline_predictions
from backend.app.ml.contracts import (
    ArtifactError,
    EligibilityError,
    QualityStatus,
    SequenceBatch,
    TrainingConfig,
)
from backend.app.ml.evaluate import evaluate_predictions, select_on_validation
from backend.app.ml.features import build_features
from backend.app.ml.inference import predict_from_run
from backend.app.ml.model import GRUForecaster
from backend.app.ml.quality import diagnose_quality, load_csv_frame, validate_and_normalize_frame
from backend.app.ml.scaling import ScalerBundle
from backend.app.ml.sequences import make_sequences, validate_minimum_samples
from backend.app.ml.split import frozen_evaluation_origins, make_split_plan
from backend.app.ml.train import predict_gru, train_gru
from backend.tests.ml.synthetic import hourly_frame


def prepared(days: int, *, warning_approved: bool = True):
    data = validate_and_normalize_frame(hourly_frame(days), "Asia/Seoul")
    quality = diagnose_quality(data)
    plan = make_split_plan(data.index, quality.status, warning_approved=warning_approved)
    features = build_features(data, "Asia/Seoul")
    return data, quality, plan, features


def batches(days: int = 90):
    data, quality, plan, features = prepared(days)
    train = make_sequences(features, data.kwh, plan, "train")
    validation_dense = make_sequences(features, data.kwh, plan, "validation")
    validation_origins, _ = frozen_evaluation_origins(plan, "validation", data.index)
    test_origins, _ = frozen_evaluation_origins(plan, "test", data.index)
    validation_eval = make_sequences(
        features, data.kwh, plan, "validation", origins=validation_origins
    )
    test_eval = make_sequences(features, data.kwh, plan, "test", origins=test_origins)
    return data, quality, plan, features, train, validation_dense, validation_eval, test_eval


class Phase7ApprovedCases(unittest.TestCase):
    def test_case_01_complete_89_days_fails(self):
        data = validate_and_normalize_frame(hourly_frame(89), "Asia/Seoul")
        quality = diagnose_quality(data)
        self.assertEqual(quality.status, QualityStatus.FAIL)
        with self.assertRaises(EligibilityError):
            make_split_plan(data.index, quality.status)

    def test_case_02_complete_90_days_is_warning_and_60_15_15(self):
        source = hourly_frame(90)
        with tempfile.TemporaryDirectory() as temporary:
            csv_path = Path(temporary) / "building.csv"
            source.to_csv(csv_path, index=False, encoding="utf-8-sig")
            loaded = load_csv_frame(csv_path)
        data = validate_and_normalize_frame(loaded, "Asia/Seoul")
        quality = diagnose_quality(data)
        self.assertEqual(quality.status, QualityStatus.WARNING)
        with self.assertRaises(EligibilityError):
            make_split_plan(data.index, quality.status, warning_approved=False)
        plan = make_split_plan(data.index, quality.status, warning_approved=True)
        self.assertEqual((plan.validation_days, plan.test_days), (15, 15))
        self.assertEqual(
            pd.Timestamp(plan.train_end) - pd.Timestamp(plan.train_start), pd.Timedelta(days=60)
        )

    def test_case_03_complete_180_days_is_120_30_30(self):
        data, quality, plan, _ = prepared(180)
        self.assertEqual(quality.status, QualityStatus.PASS)
        self.assertEqual((plan.validation_days, plan.test_days), (30, 30))
        self.assertEqual(
            pd.Timestamp(plan.train_end) - pd.Timestamp(plan.train_start), pd.Timedelta(days=120)
        )
        validation, excluded = frozen_evaluation_origins(plan, "validation", data.index)
        test, _ = frozen_evaluation_origins(plan, "test", data.index)
        self.assertEqual((len(validation), len(test), len(excluded)), (30, 30, 0))

    def test_case_04_missing_data_below_minimum_samples_fails(self):
        raw = hourly_frame(90)
        # Sparse one-hour holes preserve hourly cadence and keep the overall gap
        # below the quality threshold, but invalidate many causal windows.
        raw = raw.drop(index=list(range(200, 1400, 12))).reset_index(drop=True)
        data = validate_and_normalize_frame(raw, "Asia/Seoul")
        quality = diagnose_quality(data)
        self.assertEqual(quality.status, QualityStatus.WARNING)
        plan = make_split_plan(data.index, quality.status, warning_approved=True)
        features = build_features(data, "Asia/Seoul")
        train = make_sequences(features, data.kwh, plan, "train")
        validation_dense = make_sequences(features, data.kwh, plan, "validation")
        vo, _ = frozen_evaluation_origins(plan, "validation", data.index)
        to, _ = frozen_evaluation_origins(plan, "test", data.index)
        validation_eval = make_sequences(features, data.kwh, plan, "validation", origins=vo)
        test_eval = make_sequences(features, data.kwh, plan, "test", origins=to)
        with self.assertRaisesRegex(ValueError, "FAIL_MINIMUM"):
            validate_minimum_samples(train, validation_dense, validation_eval, test_eval)

    def test_case_05_targets_never_cross_split_boundaries(self):
        data, _, plan, features, train, validation, _, _ = batches()
        for name, batch in (("train", train), ("validation", validation)):
            start = pd.Timestamp(getattr(plan, f"{name}_start"))
            end = pd.Timestamp(getattr(plan, f"{name}_end"))
            self.assertTrue((batch.target_starts >= start).all())
            self.assertTrue((batch.target_starts + pd.Timedelta(hours=24) <= end).all())
            self.assertTrue((batch.origins < batch.target_starts).all())

    def test_case_06_future_values_do_not_change_past_features(self):
        data, _, _, _ = prepared(90)
        cutoff = data.index[500]
        changed = data.copy()
        changed.loc[changed.index > cutoff, "kwh"] += 9999
        before = build_features(data, "Asia/Seoul").loc[:cutoff]
        after = build_features(changed, "Asia/Seoul").loc[:cutoff]
        pd.testing.assert_frame_equal(before, after)

    def test_case_07_validation_test_values_do_not_change_train_scalers(self):
        data, _, plan, features = prepared(90)
        train_end = pd.Timestamp(plan.train_end)
        train_features = features.loc[features.index < train_end]
        train_targets = data.kwh.loc[data.index < train_end]
        first = ScalerBundle.fit(train_features, train_targets)
        altered_features = features.copy()
        altered_targets = data.kwh.copy()
        altered_features.loc[altered_features.index >= train_end, "kwh"] += 100000
        altered_targets.loc[altered_targets.index >= train_end] += 100000
        second = ScalerBundle.fit(
            altered_features.loc[altered_features.index < train_end],
            altered_targets.loc[altered_targets.index < train_end],
        )
        np.testing.assert_array_equal(first.input_scaler.mean_, second.input_scaler.mean_)
        np.testing.assert_array_equal(first.target_scaler.var_, second.target_scaler.var_)

    def test_case_08_gru_shapes_for_batch_one_and_many(self):
        config = dataclasses.replace(TrainingConfig(), hidden_size=8, num_layers=1, dropout=0)
        model = GRUForecaster(config)
        self.assertEqual(tuple(model(torch.zeros(1, 168, 6)).shape), (1, 24))
        self.assertEqual(tuple(model(torch.zeros(7, 168, 6)).shape), (7, 24))

    def test_case_09_artifacts_are_building_isolated_and_reloadable(self):
        data, quality, plan, features = prepared(90)
        train_end = pd.Timestamp(plan.train_end)
        scalers = ScalerBundle.fit(
            features.loc[features.index < train_end], data.kwh.loc[data.index < train_end]
        )
        config = dataclasses.replace(TrainingConfig(), hidden_size=8, num_layers=1, dropout=0)
        state = GRUForecaster(config).state_dict()
        with tempfile.TemporaryDirectory() as temporary:
            run = save_run_artifacts(
                temporary,
                building_id="building-a",
                run_id="run-001",
                model_kind="gru",
                building_timezone="Asia/Seoul",
                training_config=config,
                split_manifest=dataclasses.asdict(plan),
                evaluation_schedule={},
                quality_report=quality,
                validation_metrics={},
                test_metrics={},
                selection={},
                data_hash="synthetic",
                state_dict=state,
                scalers=scalers,
                training_history=[],
            )
            _, loaded_config, loaded_state, _ = load_gru_artifacts(
                run, expected_building_id="building-a"
            )
            self.assertEqual(loaded_config.hidden_size, 8)
            self.assertEqual(set(loaded_state), set(state))
            with self.assertRaises(ArtifactError):
                load_gru_artifacts(run, expected_building_id="building-b")
            with patch("backend.app.ml.train.train_gru", side_effect=AssertionError("retrained")):
                result = predict_from_run(run, building_id="building-a", normalized_data=data)
            self.assertFalse(result.retrained)
            self.assertEqual(result.output_shape, (1, 24))

    def test_case_10_same_seed_reproduces_checkpoint_and_predictions(self):
        _, _, _, _, train, validation, _, _ = batches()
        train = SequenceBatch(train.x[:128], train.y[:128], train.origins[:128], train.target_starts[:128])
        validation = SequenceBatch(
            validation.x[:64], validation.y[:64], validation.origins[:64], validation.target_starts[:64]
        )
        scaler = ScalerBundle.fit(
            pd.DataFrame({"kwh": train.x[:, :, 0].reshape(-1)}).assign(
                hour_sin=0.0, hour_cos=0.0, weekday_sin=0.0, weekday_cos=0.0, is_weekend=0.0
            ),
            pd.Series(train.y.reshape(-1)),
        )
        train_scaled = scaler.transform_batch(train)
        validation_scaled = scaler.transform_batch(validation)
        config = dataclasses.replace(
            TrainingConfig(), hidden_size=8, num_layers=1, dropout=0, max_epochs=2, patience=2
        )
        first = train_gru(train_scaled, validation_scaled, config)
        second = train_gru(train_scaled, validation_scaled, config)
        self.assertEqual(first.best_epoch, second.best_epoch)
        for key in first.state_dict:
            self.assertTrue(torch.equal(first.state_dict[key], second.state_dict[key]))
        np.testing.assert_array_equal(
            predict_gru(first.state_dict, validation_scaled.x[:2], config),
            predict_gru(second.state_dict, validation_scaled.x[:2], config),
        )

    def test_case_11_missing_latest_hour_rejects_inference(self):
        data, quality, plan, _ = prepared(90)
        with tempfile.TemporaryDirectory() as temporary:
            run = save_run_artifacts(
                temporary,
                building_id="a",
                run_id="baseline",
                model_kind=LAST_24H,
                building_timezone="Asia/Seoul",
                training_config=TrainingConfig(),
                split_manifest=dataclasses.asdict(plan),
                evaluation_schedule={}, quality_report=quality,
                validation_metrics={}, test_metrics={}, selection={}, data_hash="synthetic",
            )
            incomplete = data.drop(data.index[-50])
            with self.assertRaisesRegex(ValueError, "incomplete"):
                predict_from_run(run, building_id="a", normalized_data=incomplete)

    def test_case_12_test_metrics_cannot_reselect_validation_candidate(self):
        actual = np.ones((12, 24)) * 10
        l24 = evaluate_predictions(actual, actual + 2)
        l168 = evaluate_predictions(actual, actual + 3)
        gru = evaluate_predictions(actual, actual + 1)
        decision = select_on_validation(gru, l24, l168)
        self.assertEqual(decision.selected_model, "gru")
        # Deliberately terrible GRU Test performance is report-only and is not an
        # input accepted by the selection API.
        _test_metrics = evaluate_predictions(actual, actual + 100)
        self.assertEqual(decision.selected_model, "gru")
        # Exact baseline ties deterministically prefer Last-24h. With all-zero
        # actuals WAPE is undefined, so GRU cannot be promoted by omission of
        # that safeguard.
        zeros = np.zeros((12, 24))
        tied_baseline = evaluate_predictions(zeros, np.ones_like(zeros))
        undefined_gru = evaluate_predictions(zeros, np.zeros_like(zeros))
        undefined = select_on_validation(undefined_gru, tied_baseline, tied_baseline)
        self.assertEqual(undefined.best_baseline, LAST_24H)
        self.assertEqual(undefined.selected_model, LAST_24H)
        self.assertIn("WAPE_UNDEFINED_BASELINE_SELECTED", undefined.reason_codes)

    def test_case_13_constant_train_values_are_blocked_before_training(self):
        index = pd.date_range("2025-01-01", periods=200, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                "kwh": 7.0,
                "hour_sin": 0.0,
                "hour_cos": 1.0,
                "weekday_sin": 0.0,
                "weekday_cos": 1.0,
                "is_weekend": 0.0,
            }, index=index,
        )
        with self.assertRaisesRegex(EligibilityError, "FAIL_TRAIN_ZERO_VARIANCE"):
            ScalerBundle.fit(frame, frame.kwh)

    def test_case_14_negative_gru_prediction_is_not_promoted_or_clipped(self):
        actual = np.ones((12, 24))
        gru = evaluate_predictions(actual, np.full_like(actual, -0.01))
        baseline = evaluate_predictions(actual, np.full_like(actual, 2.0))
        decision = select_on_validation(gru, baseline, baseline)
        self.assertFalse(decision.gru_eligible)
        self.assertIn("GRU_NEGATIVE_PREDICTION", decision.reason_codes)
        self.assertEqual(gru.prediction_min, -0.01)

    def test_case_15_legacy_model_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy = Path(temporary) / "legacy_model.pth"
            torch.save({"weight": torch.tensor([1.0])}, legacy)
            with self.assertRaises(ArtifactError):
                predict_from_run(legacy, building_id="a", normalized_data=pd.DataFrame())


if __name__ == "__main__":
    unittest.main()
