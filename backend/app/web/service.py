"""Framework-free application service for quality, training jobs and inference."""

from __future__ import annotations

import io
import hashlib
import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields as dataclass_fields
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
from backend.app.web.ai_analysis import analyze_prediction
from backend.app.web.analysis_report import build_analysis_report


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
BUILDING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def same_weekday_baseline(
    local_data: pd.DataFrame,
    forecast_timestamps: list[str],
    *,
    max_weeks: int = 8,
    minimum_samples: int = 2,
) -> dict[str, Any]:
    """Return actual historical means for matching local weekday and hour."""
    values: list[float | None] = []
    sample_counts: list[int] = []
    statistics_by_hour: list[dict[str, Any]] = []
    for raw_timestamp in forecast_timestamps:
        forecast_time = pd.Timestamp(raw_timestamp)
        if forecast_time.tzinfo is None:
            raise ValueError("예측 시각에는 시간대 정보가 필요합니다.")
        forecast_time = forecast_time.tz_convert(local_data.index.tz)
        mask = (
            (local_data.index < forecast_time)
            & (local_data.index.weekday == forecast_time.weekday())
            & (local_data.index.hour == forecast_time.hour)
            & (local_data.index.minute == forecast_time.minute)
        )
        samples = local_data.loc[mask, "kwh"].tail(max_weeks)
        sample_count = int(len(samples))
        available_sample = sample_count >= minimum_samples
        mean = float(samples.mean()) if available_sample else None
        sample_counts.append(sample_count)
        values.append(mean)
        statistics_by_hour.append(
            {
                "timestamp": forecast_time.isoformat(),
                "sample_count": sample_count,
                "mean_kwh": mean,
                "variance_kwh2": float(samples.var(ddof=0)) if available_sample else None,
                "standard_deviation_kwh": float(samples.std(ddof=0)) if available_sample else None,
                "minimum_kwh": float(samples.min()) if available_sample else None,
                "maximum_kwh": float(samples.max()) if available_sample else None,
                "range_kwh": float(samples.max() - samples.min()) if available_sample else None,
            }
        )
    available = len(values) == 24 and all(value is not None for value in values)
    complete_values = [float(value) for value in values if value is not None]
    return {
        "status": "available" if available else "insufficient",
        "method": f"최근 최대 {max_weeks}주 동일 요일·시간 실측 평균",
        "values_kwh": complete_values if available else [],
        "sample_counts": sample_counts,
        "statistics_by_hour": statistics_by_hour,
        "minimum_samples_per_hour": minimum_samples,
        "total_kwh": float(sum(complete_values)) if available else None,
    }


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


def infer_source_timezone_mode(frame: pd.DataFrame) -> SourceTimezoneMode:
    """Use explicit offsets when every timestamp has one; otherwise use building time."""
    if "timestamp" not in frame.columns:
        return SourceTimezoneMode.IANA_CIVIL_TIME
    labels = frame["timestamp"].astype(str).str.strip()
    offset_pattern = r"(?:Z|[+-]\d{2}:?\d{2})$"
    aware = labels.str.contains(offset_pattern, regex=True, case=False, na=False)
    if aware.any() and not aware.all():
        raise DataContractError(
            "offset-aware and offset-naive timestamps cannot be mixed"
        )
    return (
        SourceTimezoneMode.EXPLICIT_OFFSET
        if aware.all()
        else SourceTimezoneMode.IANA_CIVIL_TIME
    )


def generated_building_id(csv_text: str, building_timezone: str) -> str:
    digest = hashlib.sha256()
    digest.update(building_timezone.encode("utf-8"))
    digest.update(b"\0")
    digest.update(csv_text.encode("utf-8"))
    return f"building-{digest.hexdigest()[:16]}"


def analyze_csv(
    csv_text: str,
    *,
    building_timezone: str,
    source_timezone_mode: SourceTimezoneMode | str | None = None,
    warning_approved: bool = False,
) -> dict[str, Any]:
    frame = parse_csv_text(csv_text)
    resolved_timezone_mode = source_timezone_mode or infer_source_timezone_mode(frame)
    data = validate_and_normalize_frame(
        frame,
        building_timezone,
        source_timezone_mode=resolved_timezone_mode,
    )
    quality = diagnose_quality(data)
    payload: dict[str, Any] = {
        "contract_status": "PASS",
        "quality": to_jsonable(quality),
        "training_eligible": False,
        "training_blockers": [],
        "prediction_eligible": quality.latest_168_complete,
        "source_timezone_mode": SourceTimezoneMode(resolved_timezone_mode).value,
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
    progress_mode: str = "determinate"
    progress_percent: int = 0
    csv_text: str = field(default="", repr=False)
    building_timezone: str = field(default="", repr=False)
    source_timezone_mode: str = field(default="", repr=False)

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("csv_text", "building_timezone", "source_timezone_mode"):
            value.pop(key, None)
        return value


class TrainingJobManager:
    """Local job registry with metadata-only restart recovery and no auto-promotion."""

    def __init__(
        self,
        artifact_root: str | Path,
        *,
        pipeline: Callable[..., Any] = run_training_pipeline,
        ai_analyzer: Callable[[dict[str, Any]], dict[str, Any]] = analyze_prediction,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.pipeline = pipeline
        self.ai_analyzer = ai_analyzer
        self._jobs: dict[str, TrainingJob] = {}
        self._lock = threading.Lock()
        self._analysis_in_progress: set[str] = set()
        self._analysis_counts: dict[str, int] = {}
        self._job_state_root = self.artifact_root / "_jobs"
        self._load_persisted_jobs()

    def _job_state_path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("job_id 형식이 올바르지 않습니다.")
        return self._job_state_root / f"{job_id}.json"

    def _persist_job(self, job: TrainingJob) -> None:
        self._job_state_root.mkdir(parents=True, exist_ok=True)
        value = asdict(job)
        value.pop("csv_text", None)
        target = self._job_state_path(job.job_id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)

    def _load_persisted_jobs(self) -> None:
        if not self._job_state_root.is_dir():
            return
        allowed = {field.name for field in dataclass_fields(TrainingJob)} - {"csv_text"}
        for path in sorted(self._job_state_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                filtered = {key: value[key] for key in allowed if key in value}
                job = TrainingJob(**filtered, csv_text="")
                if job.status in {"QUEUED", "RUNNING"}:
                    job.status = "FAILED"
                    job.error = "ServerRestarted: 서버 재시작으로 진행 중 작업을 복구할 수 없습니다. 다시 학습해 주세요."
                    job.progress_message = "서버 재시작으로 학습이 중단되었습니다."
                    job.completed_at_utc = datetime.now(UTC).isoformat()
                    self._persist_job(job)
                elif job.status == "COMPLETED":
                    run_dir = Path(job.run_dir or "").resolve()
                    artifact_root = self.artifact_root.resolve()
                    if artifact_root not in run_dir.parents or not run_dir.is_dir():
                        job.status = "FAILED"
                        job.error = "ArtifactMissing: 저장된 모델 경로를 확인할 수 없습니다."
                        job.progress_message = "저장된 모델을 다시 연결할 수 없습니다."
                        self._persist_job(job)
                    else:
                        job.progress_mode = "determinate"
                        job.progress_percent = 100
                self._jobs[job.job_id] = job
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue

    def submit(
        self,
        *,
        building_id: str | None = None,
        csv_text: str,
        building_timezone: str,
        source_timezone_mode: str | None = None,
        warning_approved: bool = False,
        start_background: bool = True,
    ) -> TrainingJob:
        building_id = building_id or generated_building_id(csv_text, building_timezone)
        if not BUILDING_ID.fullmatch(building_id):
            raise DataContractError("building_id는 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다.")
        frame = parse_csv_text(csv_text)
        resolved_timezone_mode = source_timezone_mode or infer_source_timezone_mode(frame)
        analysis = analyze_csv(
            csv_text,
            building_timezone=building_timezone,
            source_timezone_mode=resolved_timezone_mode,
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
            source_timezone_mode=SourceTimezoneMode(resolved_timezone_mode).value,
        )
        with self._lock:
            if any(
                existing.building_id == building_id
                and existing.status in {"QUEUED", "RUNNING"}
                for existing in self._jobs.values()
            ):
                raise EligibilityError("같은 건물의 학습 작업이 이미 진행 중입니다.")
            self._jobs[job_id] = job
            self._persist_job(job)
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
        job.progress_mode = "determinate"
        job.progress_percent = 5
        job.progress_message = "학습 작업을 시작하고 있습니다."
        self._persist_job(job)

        def update_progress(percent: int, message: str) -> None:
            job.progress_percent = max(job.progress_percent, min(99, max(0, int(percent))))
            job.progress_message = message
            self._persist_job(job)

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
                progress_callback=update_progress,
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
            job.progress_percent = 100
            job.progress_message = "학습과 모델 선택을 완료했습니다."
        except Exception as exc:  # surfaced to the local user, not silently retried
            job.status = "FAILED"
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress_message = "학습이 중단되었습니다. 원인을 확인하세요."
        finally:
            job.completed_at_utc = datetime.now(UTC).isoformat()
            job.csv_text = ""
            self._persist_job(job)

    def get(self, job_id: str) -> TrainingJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError("학습 작업을 찾을 수 없습니다.") from exc

    def predict(self, job_id: str, csv_text: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job.status != "COMPLETED" or not job.run_dir:
            raise EligibilityError("완료된 학습 작업만 예측에 사용할 수 있습니다.")
        if isinstance(csv_text, str) and csv_text.strip():
            prediction_frame = parse_csv_text(csv_text)
            prediction_timezone_mode = job.source_timezone_mode
        else:
            derived_path = Path(job.run_dir) / "derived_input_utc.csv"
            if not derived_path.is_file():
                raise EligibilityError(
                    "저장된 예측 입력을 찾을 수 없습니다. 원본 CSV를 다시 선택해 주세요."
                )
            prediction_frame = pd.read_csv(derived_path)
            prediction_timezone_mode = SourceTimezoneMode.EXPLICIT_OFFSET.value
        data = validate_and_normalize_frame(
            prediction_frame,
            job.building_timezone,
            source_timezone_mode=prediction_timezone_mode,
        )
        result = predict_from_run(
            job.run_dir,
            building_id=job.building_id,
            normalized_data=data,
        )
        values = result.predictions_kwh
        peak_index = max(range(len(values)), key=values.__getitem__)
        local_data = data.copy()
        local_data.index = local_data.index.tz_convert(job.building_timezone)
        recent_actual = local_data.kwh.iloc[-24:]
        actual_peak_timestamp = recent_actual.idxmax()
        daily = local_data.kwh.groupby(local_data.index.date).sum().tail(7)
        monthly_periods = local_data.index.tz_localize(None).to_period("M")
        monthly = local_data.kwh.groupby(monthly_periods).sum().tail(6)
        period_labels = ("00–05시", "06–11시", "12–17시", "18–23시")
        period_totals = [0.0, 0.0, 0.0, 0.0]
        for timestamp, amount in local_data.kwh.iloc[-168:].items():
            period_totals[min(timestamp.hour // 6, 3)] += float(amount)
        period_total = sum(period_totals)
        forecast_timestamps = [str(value) for value in result.timestamps]
        weekday_baseline = same_weekday_baseline(local_data, forecast_timestamps)
        return {
            **asdict(result),
            "building_timezone": job.building_timezone,
            "history_timestamps": [value.isoformat() for value in data.index[-24:]],
            "history_kwh": data.kwh.iloc[-24:].astype(float).tolist(),
            "total_kwh": float(sum(values)),
            "average_kwh": float(sum(values) / len(values)),
            "peak_kwh": float(values[peak_index]),
            "peak_timestamp": result.timestamps[peak_index],
            "data_period": {
                "start": local_data.index[0].isoformat(),
                "end": local_data.index[-1].isoformat(),
                "rows": int(len(local_data)),
            },
            "same_weekday_baseline": weekday_baseline,
            "actual_summary": {
                "total_24h_kwh": float(recent_actual.sum()),
                "average_hourly_kwh": float(recent_actual.mean()),
                "peak_kwh": float(recent_actual.max()),
                "peak_timestamp": actual_peak_timestamp.isoformat(),
            },
            "recent_daily_usage": [
                {"date": str(date), "kwh": float(amount)} for date, amount in daily.items()
            ],
            "recent_monthly_usage": [
                {"month": str(month), "kwh": float(amount)}
                for month, amount in monthly.items()
            ],
            "period_composition": [
                {
                    "label": label,
                    "kwh": amount,
                    "share": amount / period_total if period_total else 0.0,
                }
                for label, amount in zip(period_labels, period_totals, strict=True)
            ],
        }

    def analysis_report(self, job_id: str, csv_text: str) -> dict[str, Any]:
        """Calculate a complete local report without calling an external API."""
        job = self.get(job_id)
        prediction = self.predict(job_id, csv_text)
        return build_analysis_report(prediction, job)

    def analyze_prediction(self, job_id: str, csv_text: str) -> dict[str, Any]:
        """Explain a fresh local forecast without changing model or prediction state."""
        with self._lock:
            if job_id in self._analysis_in_progress:
                raise EligibilityError("이 학습 기록의 AI 분석이 이미 진행 중입니다.")
            if self._analysis_counts.get(job_id, 0) >= 3:
                raise EligibilityError("한 학습 기록의 AI 분석은 로컬 실행당 최대 3회까지 가능합니다.")
            self._analysis_in_progress.add(job_id)
            self._analysis_counts[job_id] = self._analysis_counts.get(job_id, 0) + 1
        try:
            prediction = self.predict(job_id, csv_text)
            report = build_analysis_report(prediction, self.get(job_id))
            return self.ai_analyzer(report)
        finally:
            with self._lock:
                self._analysis_in_progress.discard(job_id)
