"""Run the public portfolio samples through quality, training, and prediction."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.ml.contracts import to_jsonable  # noqa: E402
from backend.app.web.service import TrainingJobManager, analyze_csv  # noqa: E402


SAMPLES = (
    ("synthetic", PROJECT_ROOT / "frontend" / "samples" / "synthetic-power-202604-202610.csv"),
    ("samdasoo", PROJECT_ROOT / "frontend" / "samples" / "jeju-samdasoo-factory-2025.csv"),
)


def validate_sample(name: str, path: Path) -> dict:
    csv_text = path.read_text(encoding="utf-8-sig")
    print(f"[{name}] quality diagnosis started", flush=True)
    quality_started = time.perf_counter()
    analysis = analyze_csv(csv_text, building_timezone="Asia/Seoul")
    quality_seconds = time.perf_counter() - quality_started
    if not analysis["training_eligible"]:
        raise RuntimeError(f"{name} is not training eligible: {analysis['training_blockers']}")

    with tempfile.TemporaryDirectory(prefix=f"energy-planner-{name}-") as temporary:
        manager = TrainingJobManager(temporary)
        job = manager.submit(
            building_id=f"sample-{name}",
            csv_text=csv_text,
            building_timezone="Asia/Seoul",
            start_background=False,
        )
        print(f"[{name}] model training started", flush=True)
        training_started = time.perf_counter()
        manager._run(job.job_id, warning_approved=False)
        training_seconds = time.perf_counter() - training_started
        if job.status != "COMPLETED":
            raise RuntimeError(f"{name} training failed: {job.error}")

        print(f"[{name}] 24-hour prediction started", flush=True)
        prediction_started = time.perf_counter()
        prediction = manager.predict(job.job_id, csv_text)
        prediction_seconds = time.perf_counter() - prediction_started
        selected_validation = (job.validation_metrics or {}).get(job.selected_model, {})
        selected_test = (job.test_metrics or {}).get(job.selected_model, {})
        return to_jsonable(
            {
                "sample": name,
                "file": path.name,
                "quality_status": analysis["quality"]["status"],
                "training_status": analysis["training_status"],
                "quality_seconds": quality_seconds,
                "training_seconds": training_seconds,
                "model_training_seconds": job.model_training_seconds,
                "selected_model": job.selected_model,
                "selected_validation_metrics": selected_validation,
                "selected_test_metrics": selected_test,
                "prediction_seconds": prediction_seconds,
                "prediction_points": len(prediction["predictions_kwh"]),
                "forecast_start": prediction["timestamps"][0],
                "forecast_end": prediction["timestamps"][-1],
            }
        )


def main() -> None:
    results = [validate_sample(name, path) for name, path in SAMPLES]
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
