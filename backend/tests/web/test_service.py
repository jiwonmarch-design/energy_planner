from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.app.ml.artifacts import save_run_artifacts
from backend.app.ml.baselines import LAST_24H
from backend.app.ml.contracts import DataContractError, EligibilityError, TrainingConfig
from backend.app.ml.quality import diagnose_quality, validate_and_normalize_frame
from backend.app.ml.split import make_split_plan
from backend.app.web.service import (
    TrainingJobManager,
    analyze_csv,
    generated_building_id,
    infer_source_timezone_mode,
    parse_csv_text,
)
from backend.tests.ml.synthetic import hourly_frame


def csv_for(days: int, *, constant: float | None = None) -> str:
    return hourly_frame(days, constant=constant).to_csv(index=False)


class WebServiceCases(unittest.TestCase):
    def test_timezone_mode_is_inferred_from_timestamp_offsets(self):
        aware = parse_csv_text(csv_for(180))
        self.assertEqual(infer_source_timezone_mode(aware).value, "explicit_offset")
        naive = aware.copy()
        naive["timestamp"] = naive["timestamp"].str.replace("+00:00", "", regex=False)
        self.assertEqual(infer_source_timezone_mode(naive).value, "iana_civil_time")

    def test_server_generates_stable_building_id(self):
        csv_text = csv_for(180)
        first = generated_building_id(csv_text, "Asia/Seoul")
        second = generated_building_id(csv_text, "Asia/Seoul")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^building-[0-9a-f]{16}$")

    def test_submit_without_building_id_uses_generated_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *a, **k: None)
            job = manager.submit(
                csv_text=csv_for(180),
                building_timezone="Asia/Seoul",
                source_timezone_mode=None,
                start_background=False,
            )
            self.assertRegex(job.building_id, r"^building-[0-9a-f]{16}$")
            self.assertEqual(job.source_timezone_mode, "explicit_offset")

    def test_quality_api_payload_for_complete_180_days(self):
        result = analyze_csv(
            csv_for(180),
            building_timezone="Asia/Seoul",
            source_timezone_mode="explicit_offset",
        )
        self.assertEqual(result["contract_status"], "PASS")
        self.assertEqual(result["quality"]["status"], "PASS")
        self.assertTrue(result["training_eligible"])
        self.assertTrue(result["prediction_eligible"])

    def test_invalid_csv_reports_contract_error(self):
        with self.assertRaises(DataContractError):
            analyze_csv(
                "time,value\n2025-01-01,1",
                building_timezone="Asia/Seoul",
                source_timezone_mode="iana_civil_time",
            )

    def test_invalid_timestamp_and_negative_kwh_are_rejected(self):
        with self.assertRaisesRegex(DataContractError, "invalid timestamp"):
            analyze_csv(
                "timestamp,kwh\nnot-a-date,1",
                building_timezone="UTC",
                source_timezone_mode="iana_civil_time",
            )
        with self.assertRaisesRegex(DataContractError, "cannot be negative"):
            analyze_csv(
                "timestamp,kwh\n2025-01-01T00:00:00Z,-1",
                building_timezone="UTC",
                source_timezone_mode="explicit_offset",
            )

    def test_latest_168_hour_gap_disables_prediction(self):
        frame = hourly_frame(180).drop(index=len(hourly_frame(180)) - 50)
        result = analyze_csv(
            frame.to_csv(index=False),
            building_timezone="UTC",
            source_timezone_mode="explicit_offset",
        )
        self.assertFalse(result["prediction_eligible"])
        self.assertEqual(result["quality"]["missing_hours"], 1)

    def test_long_constant_run_is_warning_not_silently_changed(self):
        frame = hourly_frame(180)
        frame.loc[500:700, "kwh"] = 7.5
        result = analyze_csv(
            frame.to_csv(index=False),
            building_timezone="UTC",
            source_timezone_mode="explicit_offset",
            warning_approved=True,
        )
        self.assertEqual(result["quality"]["status"], "WARNING")
        self.assertIn("WARNING_LONG_CONSTANT_RUN_168H", result["quality"]["reason_codes"])
        self.assertTrue(result["training_eligible"])

    def test_constant_train_is_not_submitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *a, **k: None)
            with self.assertRaisesRegex(EligibilityError, "FAIL_TRAIN_ZERO_VARIANCE"):
                manager.submit(
                    building_id="constant-building",
                    csv_text=csv_for(180, constant=0.0002),
                    building_timezone="Asia/Seoul",
                    source_timezone_mode="explicit_offset",
                    start_background=False,
                )
            self.assertEqual(list(Path(temporary).rglob("*")), [])

    def test_job_lifecycle_uses_separate_pipeline_call(self):
        calls = []

        def fake_pipeline(*args, **kwargs):
            calls.append((args, kwargs))
            kwargs["progress_callback"](50, "테스트 학습 진행 중")
            run = Path(kwargs["artifact_root"]) / kwargs["building_id"] / kwargs["run_id"]
            return SimpleNamespace(run_dir=run, selected_model="last_24h")

        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=fake_pipeline)
            job = manager.submit(
                building_id="building-a",
                csv_text=csv_for(180),
                building_timezone="Asia/Seoul",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            self.assertEqual(job.status, "QUEUED")
            manager._run(job.job_id, warning_approved=False)
            completed = manager.get(job.job_id)
            self.assertEqual(completed.status, "COMPLETED")
            self.assertEqual(completed.progress_mode, "determinate")
            self.assertEqual(completed.progress_percent, 100)
            self.assertEqual(completed.selected_model, "last_24h")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1]["source_timezone_mode"], "explicit_offset")

    def test_job_failure_is_exposed_without_automatic_retry(self):
        calls = []

        def failing_pipeline(*args, **kwargs):
            calls.append((args, kwargs))
            raise RuntimeError("synthetic training failure")

        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=failing_pipeline)
            job = manager.submit(
                building_id="building-failure",
                csv_text=csv_for(180),
                building_timezone="Asia/Seoul",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            manager._run(job.job_id, warning_approved=False)
            failed = manager.get(job.job_id)
            self.assertEqual(failed.status, "FAILED")
            self.assertIn("synthetic training failure", failed.error)
            self.assertEqual(len(calls), 1)

    def test_duplicate_active_training_for_same_building_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *a, **k: None)
            manager.submit(
                building_id="building-duplicate",
                csv_text=csv_for(180),
                building_timezone="UTC",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            with self.assertRaisesRegex(EligibilityError, "이미 진행 중"):
                manager.submit(
                    building_id="building-duplicate",
                    csv_text=csv_for(180),
                    building_timezone="UTC",
                    source_timezone_mode="explicit_offset",
                    start_background=False,
                )

    def test_job_public_payload_does_not_expose_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *a, **k: None)
            job = manager.submit(
                building_id="building-a",
                csv_text=csv_for(180),
                building_timezone="Asia/Seoul",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            self.assertNotIn("csv_text", job.public())
            self.assertNotIn("building_timezone", job.public())

    def test_completed_job_metadata_survives_restart_without_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *a, **k: None)
            job = manager.submit(
                building_id="building-persisted",
                csv_text=csv_for(180),
                building_timezone="Asia/Seoul",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            run_dir = Path(temporary) / "building-persisted" / "run-a"
            run_dir.mkdir(parents=True)
            job.status = "COMPLETED"
            job.run_dir = str(run_dir)
            job.selected_model = "last_24h"
            job.csv_text = ""
            manager._persist_job(job)

            state_path = Path(temporary) / "_jobs" / f"{job.job_id}.json"
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn("csv_text", persisted)

            recovered = TrainingJobManager(temporary, pipeline=lambda *a, **k: None).get(job.job_id)
            self.assertEqual(recovered.status, "COMPLETED")
            self.assertEqual(recovered.run_dir, str(run_dir))
            self.assertEqual(recovered.building_timezone, "Asia/Seoul")

    def test_incomplete_job_is_marked_failed_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *a, **k: None)
            job = manager.submit(
                building_id="building-interrupted",
                csv_text=csv_for(180),
                building_timezone="UTC",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            recovered = TrainingJobManager(temporary, pipeline=lambda *a, **k: None).get(job.job_id)
            self.assertEqual(recovered.status, "FAILED")
            self.assertIn("서버 재시작", recovered.error)

    def test_warning_period_requires_and_accepts_explicit_approval(self):
        without = analyze_csv(
            csv_for(90),
            building_timezone="Asia/Seoul",
            source_timezone_mode="explicit_offset",
        )
        self.assertFalse(without["training_eligible"])
        with_approval = analyze_csv(
            csv_for(90),
            building_timezone="Asia/Seoul",
            source_timezone_mode="explicit_offset",
            warning_approved=True,
        )
        self.assertTrue(with_approval["training_eligible"])

    def test_upload_size_guard(self):
        with self.assertRaisesRegex(DataContractError, "25MB"):
            parse_csv_text("x" * (25 * 1024 * 1024 + 1))

    def test_completed_baseline_run_is_reused_for_24_hour_prediction(self):
        validation_metrics = {
            "xgboost": {"mae": 2.0},
            "last_24h": {"mae": 1.0},
            "last_168h": {"mae": 1.5},
        }

        def artifact_pipeline(frame, **kwargs):
            data = validate_and_normalize_frame(
                frame,
                kwargs["building_timezone"],
                source_timezone_mode=kwargs["source_timezone_mode"],
            )
            quality = diagnose_quality(data)
            plan = make_split_plan(data.index, quality.status)
            run = save_run_artifacts(
                kwargs["artifact_root"],
                building_id=kwargs["building_id"],
                run_id=kwargs["run_id"],
                model_kind=LAST_24H,
                building_timezone=kwargs["building_timezone"],
                training_config=TrainingConfig(),
                split_manifest=dataclasses.asdict(plan),
                evaluation_schedule={},
                quality_report=quality,
                validation_metrics=validation_metrics,
                test_metrics={"last_24h": {"mae": 1.1}},
                selection={"selected_model": LAST_24H},
                data_hash="synthetic-web-test",
                source_timezone_mode=kwargs["source_timezone_mode"],
                source_timezone_metadata=kwargs["source_timezone_metadata"],
                derived_input_csv=frame.to_csv(index=False).encode("utf-8"),
            )
            return SimpleNamespace(
                run_dir=run,
                selected_model=LAST_24H,
                validation_metrics=validation_metrics,
                test_metrics={"last_24h": {"mae": 1.1}},
            )

        csv_text = csv_for(180)
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=artifact_pipeline)
            job = manager.submit(
                building_id="building-a",
                csv_text=csv_text,
                building_timezone="Asia/Seoul",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            manager._run(job.job_id, warning_approved=False)
            result = manager.predict(job.job_id, csv_text)
            self.assertEqual(result["model_kind"], LAST_24H)
            self.assertEqual(result["building_timezone"], "Asia/Seoul")
            self.assertEqual(tuple(result["output_shape"]), (1, 24))
            self.assertEqual(len(result["predictions_kwh"]), 24)
            self.assertEqual(len(result["history_kwh"]), 24)
            self.assertEqual(result["same_weekday_baseline"]["status"], "available")
            self.assertEqual(len(result["same_weekday_baseline"]["values_kwh"]), 24)
            self.assertTrue(all(count >= 2 for count in result["same_weekday_baseline"]["sample_counts"]))
            self.assertEqual(result["data_period"]["rows"], 180 * 24)
            self.assertEqual(len(result["recent_daily_usage"]), 7)
            self.assertGreaterEqual(len(result["recent_monthly_usage"]), 1)
            self.assertEqual(len(result["period_composition"]), 4)
            self.assertAlmostEqual(
                sum(period["share"] for period in result["period_composition"]), 1.0
            )
            self.assertAlmostEqual(result["average_kwh"], result["total_kwh"] / 24)
            self.assertFalse(result["retrained"])
            self.assertEqual(manager.get(job.job_id).validation_metrics, validation_metrics)
            report = manager.analysis_report(job.job_id, csv_text)
            self.assertEqual(report["source"], "local_quantitative_analysis")
            self.assertEqual(len(report["chart"]["forecast_kwh"]), 24)
            self.assertEqual(len(report["chart"]["same_weekday_baseline_kwh"]), 24)
            self.assertLessEqual(len(report["recommendations"]), 3)
            self.assertNotIn("csv_text", json.dumps(report))
            recovered_manager = TrainingJobManager(temporary, pipeline=artifact_pipeline)
            recovered_result = recovered_manager.predict(job.job_id, "")
            self.assertEqual(recovered_result["model_kind"], LAST_24H)
            self.assertEqual(len(recovered_result["predictions_kwh"]), 24)


if __name__ == "__main__":
    unittest.main()
