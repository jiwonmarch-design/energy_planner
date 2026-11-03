"""Framework-free application service for quality, training jobs and inference."""

from __future__ import annotations

import io
import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from backend.app.ml.contracts import (
    DataContractError,
    EligibilityError,
    SourceTimezoneMode,
    to_jsonable,
)
from backend.app.ml.inference import predict_from_run
from backend.app.ml.quality import (
    diagnose_quality,
    diagnose_split_distribution,
    validate_and_normalize_frame,
)
from backend.app.ml.split import make_split_plan
from backend.app.ml.train import run_training_pipeline


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
BUILDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def parse_csv_text(csv_text: str) -> pd.DataFrame:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise DataContractError("CSV 내용이 비어 있습니다.")
    encoded = csv_text.encode("utf-8")
    if len(encoded) > MAX_UPLOAD_BYTES:
        raise DataContractError("CSV는 25MB 이하여야 합니다.")
    try:
        return pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:
        raise DataContractError("CSV를 읽을 수 없습니다. UTF-8과 헤더를 확인하세요.") from exc


def analyze_csv(
    csv_text: str,
    *,
    building_timezone: str,
    source_timezone_mode: SourceTimezoneMode | str,
    warning_approved: bool = False,
) -> dict[str, Any]:
    frame = parse_csv_text(csv_text)
    data = validate_and_normalize_frame(
        frame,
        building_timezone,
        source_timezone_mode=source_timezone_mode,
    )
    quality = diagnose_quality(data)
    payload: dict[str, Any] = {
        "contract_status": "PASS",
        "quality": to_jsonable(quality),
        "training_eligible": False,
        "training_blockers": [],
        "prediction_eligible": quality.latest_168_complete,
        "source_timezone_mode": SourceTimezoneMode(source_timezone_mode).value,
        "building_timezone": building_timezone,
    }
    try:
        plan = make_split_plan(
            data.index, quality.status, warning_approved=warning_approved
        )
    except EligibilityError as exc:
        payload["training_blockers"].append(str(exc))
        return payload
    distribution = diagnose_split_distribution(data, plan)
    payload["split"] = to_jsonable(plan)
    payload["distribution"] = to_jsonable(distribution)
    if distribution.train_zero_variance:
        payload["training_blockers"].append("FAIL_TRAIN_ZERO_VARIANCE")
    payload["training_eligible"] = not payload["training_blockers"]
    return payload


@dataclass
class TrainingJob:
    job_id: str
    building_id: str
    status: str = "QUEUED"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at_utc: str | None = None
    completed_at_utc: str | None = None
    run_dir: str | None = None
    selected_model: str | None = None
    validation_metrics: dict[str, Any] | None = None
    test_metrics: dict[str, Any] | None = None
    error: str | None = None
    progress_message: str = "학습 대기 중"
    csv_text: str = field(default="", repr=False)
    building_timezone: str = field(default="", repr=False)
    source_timezone_mode: str = field(default="", repr=False)

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("csv_text", "building_timezone", "source_timezone_mode"):
            value.pop(key, None)
        return value


class TrainingJobManager:
    """In-memory local prototype registry; it never auto-promotes a model."""

    def __init__(
        self,
        artifact_root: str | Path,
        *,
        pipeline: Callable[..., Any] = run_training_pipeline,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.pipeline = pipeline
        self._jobs: dict[str, TrainingJob] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        building_id: str,
        csv_text: str,
        building_timezone: str,
        source_timezone_mode: str,
        warning_approved: bool = False,
        start_background: bool = True,
    ) -> TrainingJob:
        if not BUILDING_ID.fullmatch(building_id or ""):
            raise DataContractError("building_id는 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다.")
        analysis = analyze_csv(
            csv_text,
            building_timezone=building_timezone,
            source_timezone_mode=source_timezone_mode,
            warning_approved=warning_approved,
        )
        if not analysis["training_eligible"]:
            raise EligibilityError(
                ", ".join(analysis["training_blockers"]) or "데이터가 학습 조건을 충족하지 않습니다."
            )
        if analysis["quality"]["status"] == "WARNING" and not warning_approved:
            raise EligibilityError("WARNING 데이터는 명시적 제한 실험 승인이 필요합니다.")
        job_id = uuid.uuid4().hex
        job = TrainingJob(
            job_id=job_id,
            building_id=building_id,
            csv_text=csv_text,
            building_timezone=building_timezone,
            source_timezone_mode=source_timezone_mode,
        )
        with self._lock:
            if any(
                existing.building_id == building_id
                and existing.status in {"QUEUED", "RUNNING"}
                for existing in self._jobs.values()
            ):
                raise EligibilityError("같은 건물의 학습 작업이 이미 진행 중입니다.")
            self._jobs[job_id] = job
        if start_background:
            threading.Thread(
                target=self._run,
                args=(job_id, warning_approved),
                daemon=True,
                name=f"energy-planner-{job_id[:8]}",
            ).start()
        return job

    def _run(self, job_id: str, warning_approved: bool) -> None:
        job = self._jobs[job_id]
        job.status = "RUNNING"
        job.started_at_utc = datetime.now(UTC).isoformat()
        job.progress_message = "GRU와 기준 모델을 평가하고 있습니다."
        try:
            run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{job_id[:8]}"
            outcome = self.pipeline(
                parse_csv_text(job.csv_text),
                building_id=job.building_id,
                building_timezone=job.building_timezone,
                artifact_root=self.artifact_root,
                run_id=run_id,
                warning_approved=warning_approved,
                source_timezone_mode=job.source_timezone_mode,
                source_timezone_metadata=job.building_timezone,
            )
            job.run_dir = str(outcome.run_dir)
            job.selected_model = outcome.selected_model
            job.validation_metrics = getattr(outcome, "validation_metrics", None)
            job.test_metrics = getattr(outcome, "test_metrics", None)
            if job.validation_metrics is None:
                metrics_path = Path(job.run_dir) / "validation_metrics.json"
                if metrics_path.exists():
                    job.validation_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            if job.test_metrics is None:
                metrics_path = Path(job.run_dir) / "test_metrics.json"
                if metrics_path.exists():
                    job.test_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            job.status = "COMPLETED"
            job.progress_message = "후보 모델 평가와 저장을 완료했습니다. 자동 승격은 하지 않았습니다."
        except Exception as exc:  # surfaced to the local user, not silently retried
            job.status = "FAILED"
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress_message = "학습이 중단되었습니다. 원인을 확인하세요."
        finally:
            job.completed_at_utc = datetime.now(UTC).isoformat()

    def get(self, job_id: str) -> TrainingJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError("학습 작업을 찾을 수 없습니다.") from exc

    def predict(self, job_id: str, csv_text: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job.status != "COMPLETED" or not job.run_dir:
            raise EligibilityError("완료된 학습 작업만 예측에 사용할 수 있습니다.")
        data = validate_and_normalize_frame(
            parse_csv_text(csv_text),
            job.building_timezone,
            source_timezone_mode=job.source_timezone_mode,
        )
        result = predict_from_run(
            job.run_dir,
            building_id=job.building_id,
            normalized_data=data,
        )
        values = result.predictions_kwh
        peak_index = max(range(len(values)), key=values.__getitem__)
        return {
            **asdict(result),
            "history_timestamps": [value.isoformat() for value in data.index[-12:]],
            "history_kwh": data.kwh.iloc[-12:].astype(float).tolist(),
            "total_kwh": float(sum(values)),
            "peak_kwh": float(values[peak_index]),
            "peak_timestamp": result.timestamps[peak_index],
        }
