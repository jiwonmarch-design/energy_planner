"""One-shot Phase 7-6 experiment for Panther_office_Danica only."""

from __future__ import annotations

import ctypes
import dataclasses
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from backend.app.ml.contracts import QualityStatus, TrainingConfig, to_jsonable
from backend.app.ml.features import build_features
from backend.app.ml.inference import predict_from_run
from backend.app.ml.quality import (
    diagnose_quality,
    diagnose_split_distribution,
    validate_and_normalize_frame,
)
from backend.app.ml.sequences import make_sequences, validate_minimum_samples
from backend.app.ml.split import frozen_evaluation_origins, make_split_plan
from backend.app.ml.train import run_training_pipeline


BUILDING_ID = "Panther_office_Danica"
RUN_ID = "20261030T055947Z_phase7-6_a6-v1"
SOURCE_TIMEZONE = "US/Eastern"
PIPELINE_TIMEZONE = "Etc/GMT+5"
SOURCE_TIMEZONE_MODE = "bdg2_naive_local_grid_fixed_standard"
DATASET_ROOT = Path(
    "C:/Users/aicam/Desktop/energy-planner-datasets/building-data-genome-project-2"
)
PROJECT_ROOT = Path("C:/Users/aicam/Desktop/energy-planner-mini")
SOURCE_CSV = DATASET_ROOT / "data/meters/cleaned/electricity_cleaned.csv"
METADATA_CSV = DATASET_ROOT / "data/metadata/metadata.csv"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/phase7_6_office"
REPORT_ROOT = PROJECT_ROOT / "analysis/phase7_6_office" / BUILDING_ID / RUN_ID


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def memory_bytes() -> tuple[int, int]:
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        raise OSError("GetProcessMemoryInfo failed")
    return counters.WorkingSetSize, counters.PeakWorkingSetSize


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metric_table(metrics: dict[str, dict]) -> str:
    rows = [
        "| 모델 | MAE | RMSE | WAPE | 음수 | 비유한 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("gru", "last_24h", "last_168h"):
        value = metrics[name]
        wape = "계산 불가" if value["wape"] is None else f"{value['wape']:.6f}"
        rows.append(
            f"| {name} | {value['mae']:.6f} | {value['rmse']:.6f} | {wape} | "
            f"{value['negative_count']} | {value['nonfinite_count']} |"
        )
    return "\n".join(rows)


def make_report(result: dict) -> str:
    q = result["precheck"]["quality"]
    split = result["precheck"]["split"]
    samples = result["precheck"]["samples"]
    resources = result["resources"]
    return f"""# Energy Planner — Phase 7-6 Panther_office_Danica 최초 학습 보고서

## 최종 판정

- 사전 품질 게이트: **PASS**
- GRU 학습: **성공, 정확히 1회 실행**
- Validation 선택 모델: **{result['selection']['selected_model']}**
- Test에 의한 재선택: **없음**
- 저장 run 재사용 추론: **PASS**
- 운영 자동 승격: **수행하지 않음**

## 데이터와 시간대

- 건물: `{BUILDING_ID}` / Panther / Office
- 메타데이터 시간대: `{SOURCE_TIMEZONE}`
- 원본 로컬 기간: `{result['precheck']['local_start']}` ~ `{result['precheck']['local_end']}`
- UTC 기간: `{q['start_utc']}` ~ `{q['end_utc']}`
- source_timezone_mode: `{SOURCE_TIMEZONE_MODE}`
- 고정 표준시 피처 시간대: `{PIPELINE_TIMEZONE}` (UTC-05:00)
- 단위: BDG2 electricity meter_reading 정의에 따른 시간별 구간 kWh

BDG2 원본의 DST 미반영 로컬 격자를 보존하기 위해 실제 IANA DST 변환과 분리했다.

## 품질과 분할

- 예상/관측 시간: {q['expected_hours']} / {q['observed_hours']}
- 결측률·최대 연속 결측: {q['missing_rate']:.6%} / {q['max_consecutive_missing_hours']}시간
- 0값·최대 상수 구간: {q['zero_count']} / {q['longest_constant_run_hours']}시간
- IQR 이상치 의심값: {q['suspicious_outlier_count']}
- Train: `{split['train_start']}` ~ `{split['train_end']}`, {samples['train_dense']}조합
- Validation: `{split['validation_start']}` ~ `{split['validation_end']}`, dense {samples['validation_dense']} / 비중복 {samples['validation_nonoverlap']}
- Test: `{split['test_start']}` ~ `{split['test_end']}`, 비중복 {samples['test_nonoverlap']}
- 동결 평가 일정 제외 구간: Validation {samples['validation_excluded']} / Test {samples['test_excluded']}

## Validation 비교

{metric_table(result['validation_metrics'])}

선택 사유: `{', '.join(result['selection']['reason_codes'])}`

## 독립 Test 비교

후보는 Validation에서 고정했으며 Test 결과는 보고 및 진단에만 사용했다.

{metric_table(result['test_metrics'])}

## 실행 자원과 재사용

- 데이터 사전 점검: {resources['source_precheck_seconds']:.3f}초
- 파이프라인 데이터 준비: {resources['pipeline_data_preparation_seconds']:.3f}초
- GRU 학습: {resources['gru_training_seconds']:.3f}초
- 전체 실험: {resources['total_experiment_seconds']:.3f}초
- 최대 working set: {resources['peak_working_set_mib']:.1f} MiB
- 최적/종료 epoch: {result['training']['best_epoch']} / {result['training']['stopped_epoch']}
- Early stopping: {result['training']['early_stopping']}
- 저장 run 예측 시간: {result['reuse']['selected_inference_seconds']:.6f}초
- 출력 shape: `{result['reuse']['output_shape']}`
- 추론 중 재학습: {result['reuse']['retrained']}

## 제한과 경고

1. 최신 180일 단일 구간·단일 건물 실험이므로 일반화 성능을 입증하지 않는다.
2. IQR 이상치 의심값은 제거하거나 보정하지 않았다.
3. BDG2 고정 표준시 규칙은 일반 사용자 CSV의 IANA/DST 규칙과 다르다.
4. 이 run은 candidate이며 `active_model.json`은 생성하거나 변경하지 않았다.
"""


def main() -> None:
    if BUILDING_ID != "Panther_office_Danica":
        raise RuntimeError("runner is locked to Panther_office_Danica")
    run_dir = ARTIFACT_ROOT / BUILDING_ID / RUN_ID
    if run_dir.exists() or REPORT_ROOT.exists():
        raise FileExistsError("immutable experiment run already exists")

    experiment_started = time.perf_counter()
    working_start, _ = memory_bytes()
    metadata = pd.read_csv(METADATA_CSV)
    match = metadata.loc[metadata.building_id == BUILDING_ID]
    if len(match) != 1:
        raise RuntimeError("Danica metadata identity is not unique")
    meta = match.iloc[0]
    if (
        meta.site_id != "Panther"
        or meta.primaryspaceusage != "Office"
        or meta.electricity != "Yes"
        or meta.timezone != SOURCE_TIMEZONE
    ):
        raise RuntimeError("Danica metadata does not match approved scope")

    source = pd.read_csv(SOURCE_CSV, usecols=["timestamp", BUILDING_ID])
    source["timestamp"] = pd.to_datetime(source["timestamp"], format="%Y-%m-%d %H:%M:%S")
    end = source.timestamp.max()
    start = end - pd.Timedelta(hours=180 * 24 - 1)
    window = source.loc[
        source.timestamp.between(start, end), ["timestamp", BUILDING_ID]
    ].rename(columns={BUILDING_ID: "kwh"}).copy()
    contract = window.copy()
    contract["timestamp"] = contract.timestamp.dt.strftime("%Y-%m-%dT%H:%M:%S")
    data = validate_and_normalize_frame(
        contract,
        PIPELINE_TIMEZONE,
        source_timezone_mode=SOURCE_TIMEZONE_MODE,
    )
    quality = diagnose_quality(data)
    if quality.status != QualityStatus.PASS:
        raise RuntimeError(f"precheck quality failed: {quality.reason_codes}")
    plan = make_split_plan(data.index, quality.status)
    distribution = diagnose_split_distribution(data, plan)
    if distribution.train_zero_variance:
        raise RuntimeError("FAIL_TRAIN_ZERO_VARIANCE")
    features = build_features(data, PIPELINE_TIMEZONE)
    train = make_sequences(features, data.kwh, plan, "train")
    validation_dense = make_sequences(features, data.kwh, plan, "validation")
    validation_origins, validation_excluded = frozen_evaluation_origins(
        plan, "validation", data.index
    )
    test_origins, test_excluded = frozen_evaluation_origins(plan, "test", data.index)
    validation_eval = make_sequences(
        features, data.kwh, plan, "validation", origins=validation_origins
    )
    test_eval = make_sequences(features, data.kwh, plan, "test", origins=test_origins)
    validate_minimum_samples(train, validation_dense, validation_eval, test_eval)
    if validation_excluded or test_excluded:
        raise RuntimeError("frozen evaluation schedule contains exclusions")
    source_precheck_seconds = time.perf_counter() - experiment_started

    # The only approved real-building training invocation in this runner.
    outcome = run_training_pipeline(
        contract,
        building_id=BUILDING_ID,
        building_timezone=PIPELINE_TIMEZONE,
        artifact_root=ARTIFACT_ROOT,
        run_id=RUN_ID,
        warning_approved=False,
        config=TrainingConfig(),
        source_timezone_mode=SOURCE_TIMEZONE_MODE,
        source_timezone_metadata=(
            "BDG2 metadata timezone=US/Eastern; fixed standard offset UTC-05:00; "
            "source local grid has no DST duplicate/skip"
        ),
    )

    inference_started = time.perf_counter()
    reuse = predict_from_run(outcome.run_dir, building_id=BUILDING_ID, normalized_data=data)
    selected_inference_seconds = time.perf_counter() - inference_started
    _, peak_working = memory_bytes()
    total_seconds = time.perf_counter() - experiment_started
    active_models = list(PROJECT_ROOT.rglob("active_model.json"))

    result = {
        "phase": "Phase 7-6",
        "status": "PASS",
        "building_id": BUILDING_ID,
        "run_id": RUN_ID,
        "training_invocations": 1,
        "source": {
            "cleaned_electricity_csv": str(SOURCE_CSV),
            "cleaned_electricity_sha256": file_sha256(SOURCE_CSV),
            "metadata_csv": str(METADATA_CSV),
            "metadata_sha256": file_sha256(METADATA_CSV),
            "unit": "hourly interval kWh",
            "source_timezone": SOURCE_TIMEZONE,
            "pipeline_timezone": PIPELINE_TIMEZONE,
            "source_timezone_mode": SOURCE_TIMEZONE_MODE,
        },
        "precheck": {
            "local_start": start.isoformat(),
            "local_end": end.isoformat(),
            "quality": to_jsonable(quality),
            "split": to_jsonable(plan),
            "distribution": to_jsonable(distribution),
            "samples": {
                "train_dense": len(train.x),
                "validation_dense": len(validation_dense.x),
                "validation_nonoverlap": len(validation_eval.x),
                "test_nonoverlap": len(test_eval.x),
                "validation_excluded": len(validation_excluded),
                "test_excluded": len(test_excluded),
            },
        },
        "training": {
            "config": dataclasses.asdict(TrainingConfig()),
            "best_epoch": outcome.best_epoch,
            "stopped_epoch": outcome.stopped_epoch,
            "early_stopping": outcome.stopped_epoch < TrainingConfig().max_epochs,
            "input_shape": list(outcome.input_shape),
            "output_shape": list(outcome.output_shape),
        },
        "validation_metrics": outcome.validation_metrics,
        "selection": json.loads((outcome.run_dir / "manifest.json").read_text(encoding="utf-8"))[
            "selection"
        ],
        "test_metrics": outcome.test_metrics,
        "resources": {
            "source_precheck_seconds": source_precheck_seconds,
            "pipeline_data_preparation_seconds": outcome.data_preparation_seconds,
            "gru_training_seconds": outcome.training_seconds,
            "artifact_save_seconds": outcome.artifact_save_seconds,
            "pipeline_total_seconds": outcome.total_seconds,
            "total_experiment_seconds": total_seconds,
            "working_set_start_bytes": working_start,
            "peak_working_set_bytes": peak_working,
            "peak_working_set_mib": peak_working / 1024 / 1024,
        },
        "reuse": {
            "selected_inference_seconds": selected_inference_seconds,
            "selected_model": reuse.model_kind,
            "input_shape": list(reuse.input_shape),
            "output_shape": list(reuse.output_shape),
            "prediction_min_kwh": min(reuse.predictions_kwh),
            "prediction_max_kwh": max(reuse.predictions_kwh),
            "retrained": reuse.retrained,
        },
        "artifact_run_dir": str(outcome.run_dir),
        "report_dir": str(REPORT_ROOT),
        "active_model_files_found": [str(path) for path in active_models],
        "active_model_changed": False,
        "test_used_for_reselection": False,
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=False)
    (REPORT_ROOT / "phase7_6_danica_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORT_ROOT / "phase7_6_danica_report.md").write_text(
        make_report(result), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
