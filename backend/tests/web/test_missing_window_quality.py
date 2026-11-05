from __future__ import annotations

import tempfile
import unittest

import pandas as pd

from backend.app.web.service import TrainingJobManager, analyze_csv
from backend.tests.ml.synthetic import hourly_frame


def analyze(frame: pd.DataFrame) -> dict:
    return analyze_csv(
        frame.to_csv(index=False),
        building_timezone="UTC",
        source_timezone_mode="explicit_offset",
    )


def without_rows(frame: pd.DataFrame, indexes: list[int] | range) -> pd.DataFrame:
    return frame.drop(index=list(indexes)).reset_index(drop=True)


class MissingWindowQualityCases(unittest.TestCase):
    def test_exactly_24_missing_hours_does_not_trigger_over_24_warning(self):
        result = analyze(without_rows(hourly_frame(180), range(1000, 1024)))

        self.assertEqual(result["quality"]["max_consecutive_missing_hours"], 24)
        self.assertEqual(result["quality"]["status"], "PASS")
        self.assertNotIn(
            "WARNING_MAX_GAP_OVER_24_HOURS", result["quality"]["reason_codes"]
        )
        self.assertEqual(result["training_status"], "PASS")
        self.assertTrue(result["training_eligible"])

    def test_over_24_missing_hours_warns_but_allows_sufficient_splits(self):
        frame = without_rows(hourly_frame(180), range(1000, 1025))
        result = analyze(frame)

        self.assertEqual(result["quality"]["max_consecutive_missing_hours"], 25)
        self.assertEqual(result["quality"]["status"], "WARNING")
        self.assertIn(
            "WARNING_MAX_GAP_OVER_24_HOURS", result["quality"]["reason_codes"]
        )
        self.assertEqual(result["sample_availability"]["status"], "PASS")
        self.assertEqual(result["training_status"], "PASS")
        self.assertTrue(result["training_eligible"])
        with tempfile.TemporaryDirectory() as temporary:
            manager = TrainingJobManager(temporary, pipeline=lambda *args, **kwargs: None)
            job = manager.submit(
                csv_text=frame.to_csv(index=False),
                building_timezone="UTC",
                source_timezone_mode="explicit_offset",
                start_background=False,
            )
            self.assertEqual(job.status, "QUEUED")

    def test_validation_zero_valid_samples_blocks_training(self):
        # A missing hour every 192 hours intersects every Validation 168+24
        # candidate while leaving Train and Test with sufficient samples.
        result = analyze(without_rows(hourly_frame(180), [2903, 3095, 3287, 3479]))
        validation = result["sample_availability"]["splits"]["validation"]

        self.assertEqual(validation["valid_count"], 0)
        self.assertEqual(validation["evaluation"]["valid_count"], 0)
        self.assertIn(
            "FAIL_MINIMUM_VALIDATION_DENSE_SAMPLES_168",
            result["training_blockers"],
        )
        self.assertIn(
            "FAIL_MINIMUM_VALIDATION_NONOVERLAP_12",
            result["training_blockers"],
        )
        self.assertEqual(result["training_status"], "FAIL")
        self.assertFalse(result["training_eligible"])

    def test_test_zero_valid_samples_blocks_training(self):
        # The same coverage pattern is applied only to the Test interval.
        result = analyze(without_rows(hourly_frame(180), [3623, 3815, 4007, 4199]))
        test = result["sample_availability"]["splits"]["test"]

        self.assertEqual(test["valid_count"], 0)
        self.assertIn("FAIL_MINIMUM_TEST_NONOVERLAP_12", result["training_blockers"])
        self.assertEqual(result["training_status"], "FAIL")
        self.assertFalse(result["training_eligible"])

    def test_complete_data_reports_all_split_counts_without_exclusions(self):
        result = analyze(hourly_frame(180))
        samples = result["sample_availability"]["splits"]

        self.assertEqual(result["quality"]["complete_168_plus_24_pairs"], 4129)
        self.assertEqual(
            (samples["train"]["valid_count"], samples["train"]["excluded_count"]),
            # The first 168 Train targets have no pre-dataset lookback context.
            (2689, 168),
        )
        self.assertEqual(
            (
                samples["validation"]["valid_count"],
                samples["validation"]["excluded_count"],
            ),
            (697, 0),
        )
        self.assertEqual(
            (samples["test"]["valid_count"], samples["test"]["excluded_count"]),
            (30, 0),
        )
        self.assertEqual(result["training_status"], "PASS")
        self.assertTrue(result["training_eligible"])

    def test_frontend_contains_every_returned_quality_and_training_reason_code(self):
        result = analyze(without_rows(hourly_frame(180), range(1000, 1025)))
        frontend = (
            __import__("pathlib").Path(__file__).parents[3] / "frontend" / "app.js"
        ).read_text(encoding="utf-8")

        returned_codes = result["quality"]["reason_codes"] + result["training_blockers"]
        for code in returned_codes:
            with self.subTest(code=code):
                self.assertIn(f"{code}:", frontend)
        self.assertNotIn("FAIL_MAX_GAP_OVER_24_HOURS:", frontend)


if __name__ == "__main__":
    unittest.main()
