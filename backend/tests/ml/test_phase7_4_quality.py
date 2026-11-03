"""Phase 7-4 quality hardening and timezone-mode regression tests."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend.app.ml.artifacts import load_manifest, save_run_artifacts
from backend.app.ml.contracts import (
    DataContractError,
    EligibilityError,
    SourceTimezoneMode,
    TrainingConfig,
)
from backend.app.ml.features import build_features
from backend.app.ml.quality import (
    diagnose_quality,
    diagnose_split_distribution,
    enforce_train_variance,
    validate_and_normalize_frame,
)
from backend.app.ml.scaling import ScalerBundle
from backend.app.ml.split import make_split_plan
from backend.app.ml.train import run_training_pipeline
from backend.tests.ml.synthetic import hourly_frame


class _ConstantRegressor:
    def predict(self, x):
        return np.ones(len(x), dtype=float)


class Phase74QualityCases(unittest.TestCase):
    def test_long_constant_plateau_and_state_transition_warn(self):
        frame = hourly_frame(180)
        frame.loc[: 120 * 24 - 1, "kwh"] = 0.0002
        data = validate_and_normalize_frame(frame, "UTC")
        report = diagnose_quality(data)
        self.assertEqual(report.longest_constant_run_hours, 120 * 24)
        self.assertGreater(report.dominant_value_rate, 0.5)
        self.assertTrue(report.suspected_state_transition)
        self.assertIn("WARNING_LONG_CONSTANT_RUN_168H", report.reason_codes)
        self.assertIn("WARNING_SUSPECTED_METER_STATE_TRANSITION", report.reason_codes)

    def test_split_distribution_reports_shift(self):
        frame = hourly_frame(180)
        frame.loc[120 * 24 :, "kwh"] += 100.0
        data = validate_and_normalize_frame(frame, "UTC")
        plan = make_split_plan(data.index, diagnose_quality(data).status)
        report = diagnose_split_distribution(data, plan)
        self.assertFalse(report.train_zero_variance)
        self.assertIn("WARNING_VALIDATION_MEAN_SHIFT_OVER_1_TRAIN_STD", report.warning_codes)
        self.assertIn("WARNING_TEST_MEAN_SHIFT_OVER_1_TRAIN_STD", report.warning_codes)

    def test_train_zero_variance_is_hard_failure(self):
        frame = hourly_frame(180, constant=0.0002)
        data = validate_and_normalize_frame(frame, "UTC")
        plan = make_split_plan(data.index, diagnose_quality(data).status)
        report = diagnose_split_distribution(data, plan)
        self.assertTrue(report.train_zero_variance)
        with self.assertRaisesRegex(EligibilityError, "FAIL_TRAIN_ZERO_VARIANCE"):
            enforce_train_variance(report)

    def test_pipeline_blocks_before_train_or_artifact_write(self):
        frame = hourly_frame(180, constant=0.0002)
        with tempfile.TemporaryDirectory() as temporary:
            with patch("backend.app.ml.train.train_xgboost", side_effect=AssertionError("trained")):
                with self.assertRaisesRegex(EligibilityError, "FAIL_TRAIN_ZERO_VARIANCE"):
                    run_training_pipeline(
                        frame,
                        building_id="constant-building",
                        building_timezone="UTC",
                        artifact_root=temporary,
                        run_id="blocked-run",
                    )
            self.assertEqual(list(Path(temporary).rglob("*")), [])

    def test_explicit_offset_mode_rejects_naive_labels(self):
        frame = pd.DataFrame(
            {"timestamp": ["2025-01-01T00:00:00", "2025-01-01T01:00:00"], "kwh": [1, 2]}
        )
        with self.assertRaisesRegex(DataContractError, "requires an offset"):
            validate_and_normalize_frame(
                frame,
                "Asia/Seoul",
                source_timezone_mode=SourceTimezoneMode.EXPLICIT_OFFSET,
            )

    def test_explicit_offset_mode_accepts_offset_labels(self):
        frame = pd.DataFrame(
            {"timestamp": ["2025-01-01T00:00:00+09:00", "2025-01-01T01:00:00+09:00"], "kwh": [1, 2]}
        )
        data = validate_and_normalize_frame(
            frame,
            "Asia/Seoul",
            source_timezone_mode=SourceTimezoneMode.EXPLICIT_OFFSET,
        )
        self.assertEqual(data.index[0], pd.Timestamp("2024-12-31T15:00:00Z"))

    def test_bdg2_mode_requires_fixed_offset_feature_timezone(self):
        frame = pd.DataFrame(
            {"timestamp": ["2025-01-01T00:00:00", "2025-01-01T01:00:00"], "kwh": [1, 2]}
        )
        with self.assertRaisesRegex(DataContractError, "fixed-offset"):
            validate_and_normalize_frame(
                frame,
                "America/Chicago",
                source_timezone_mode=SourceTimezoneMode.BDG2_FIXED_STANDARD_LOCAL_GRID,
            )
        data = validate_and_normalize_frame(
            frame,
            "Etc/GMT+6",
            source_timezone_mode=SourceTimezoneMode.BDG2_FIXED_STANDARD_LOCAL_GRID,
        )
        self.assertEqual(data.index[0], pd.Timestamp("2025-01-01T06:00:00Z"))

    def test_manifest_persists_timezone_provenance(self):
        data = validate_and_normalize_frame(hourly_frame(180), "UTC")
        plan = make_split_plan(data.index, diagnose_quality(data).status)
        features = pd.DataFrame(
            {
                "kwh": data.kwh,
                "hour_sin": 0.0,
                "hour_cos": 1.0,
                "weekday_sin": 0.0,
                "weekday_cos": 1.0,
                "is_weekend": 0.0,
            },
            index=data.index,
        )
        train_end = pd.Timestamp(plan.train_end)
        scalers = ScalerBundle.fit(features.loc[: train_end - pd.Timedelta(hours=1)], data.kwh.loc[: train_end - pd.Timedelta(hours=1)])
        config = dataclasses.replace(TrainingConfig(), n_estimators=2)
        with tempfile.TemporaryDirectory() as temporary:
            run = save_run_artifacts(
                temporary,
                building_id="bdg2-building",
                run_id="timezone-run",
                model_kind="xgboost",
                building_timezone="Etc/GMT+6",
                training_config=config,
                split_manifest=dataclasses.asdict(plan),
                evaluation_schedule={},
                quality_report={},
                validation_metrics={},
                test_metrics={},
                selection={},
                data_hash="synthetic",
                xgboost_models=[_ConstantRegressor() for _ in range(24)],
                source_timezone_mode=SourceTimezoneMode.BDG2_FIXED_STANDARD_LOCAL_GRID,
                source_timezone_metadata="US/Central",
            )
            manifest = load_manifest(run, expected_building_id="bdg2-building")
            self.assertEqual(manifest["schema_version"], "xgboost-v1")
            self.assertEqual(manifest["source_timezone_mode"], "bdg2_naive_local_grid_fixed_standard")
            self.assertEqual(manifest["source_timezone_metadata"], "US/Central")
            self.assertEqual(manifest["feature_timezone"], "Etc/GMT+6")
            self.assertEqual(manifest["building_timezone"], "Etc/GMT+6")
            self.assertFalse(manifest["dst_applied"])

            # Simulate an immutable pre-feature_timezone manifest. Loading must
            # supply the compatibility value without changing the file or the
            # feature calculation.
            manifest_path = run / "manifest.json"
            legacy_on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
            legacy_on_disk.pop("feature_timezone")
            legacy_on_disk["schema_version"] = "phase7.4-v1"
            manifest_path.write_text(
                json.dumps(legacy_on_disk, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            before_load = manifest_path.read_bytes()
            legacy_loaded = load_manifest(run, expected_building_id="bdg2-building")
            self.assertEqual(legacy_loaded["feature_timezone"], "Etc/GMT+6")
            self.assertEqual(manifest_path.read_bytes(), before_load)
            pd.testing.assert_frame_equal(
                build_features(data, manifest["feature_timezone"]),
                build_features(data, legacy_loaded["feature_timezone"]),
            )


if __name__ == "__main__":
    unittest.main()
