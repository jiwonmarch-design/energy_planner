"""One-shot Phase 7-2 experiment for Hog_office_Leon only."""

from __future__ import annotations

import ctypes
import dataclasses
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.ml.artifacts import load_gru_artifacts
from backend.app.ml.contracts import QualityStatus, TrainingConfig, to_jsonable
from backend.app.ml.features import build_features
from backend.app.ml.inference import predict_from_run
from backend.app.ml.quality import diagnose_quality, validate_and_normalize_frame
from backend.app.ml.scaling import ScalerBundle
from backend.app.ml.sequences import make_sequences, validate_minimum_samples
from backend.app.ml.split import frozen_evaluation_origins, make_split_plan
from backend.app.ml.train import predict_gru, run_training_pipeline


BUILDING_ID = "Hog_office_Leon"
RUN_ID = "20261030T024644Z_phase7-2_a6-v1"
BUILDING_TIMEZONE_SOURCE = "US/Central"
BUILDING_TIMEZONE_PIPELINE = "Etc/GMT+6"
DATASET_ROOT = Path(
    "C:/Users/aicam/Desktop/energy-planner-datasets/building-data-genome-project-2"
)
PROJECT_ROOT = Path("C:/Users/aicam/Desktop/energy-planner-mini")
SOURCE_CSV = DATASET_ROOT / "data/meters/cleaned/electricity_cleaned.csv"
METADATA_CSV = DATASET_ROOT / "data/metadata/metadata.csv"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/phase7_2_office"
REPORT_ROOT = PROJECT_ROOT / "analysis/phase7_2_office" / BUILDING_ID / RUN_ID


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
    rows = ["| 모델 | MAE | RMSE | WAPE | 음수 | 비유한 |", "|---|---:|---:|---:|---:|---:|"]
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
    samples = result["precheck"]["samples"]
    timing = result["resources"]
    selection = result["selection"]
    return f"""# Energy Planner — Phase 7-2 Hog_office_Leon 최초 학습 보고서

## 1. 최종 판정

- 사전 점검: **PASS**
- 실제 GRU 학습: **성공, 1회 실행**
- Validation 선택 모델: **{selection['selected_model']}**
- Test 결과에 따른 재선택: **없음**
- 저장 run 재사용 24시간 추론: **PASS**
- 운영 자동 승격: **수행하지 않음**

## 2. 입력과 단위

- 건물 ID: `{BUILDING_ID}`
- 사이트·용도: `Hog / Office / Office`
- 면적: 1,938.3 m²
- 메타데이터 시간대: `{BUILDING_TIMEZONE_SOURCE}`
- 전력 단위: BDG2 공식 노트북의 electricity `meter_reading` 정의에 따른 시간별 kWh
- 원본: cleaned electricity CSV의 Leon 열을 읽기 전용으로 사용
- 파생 입력: UTC timestamp와 `kwh` 두 열로 run 내부에 저장

BDG2 원본은 DST 중복·누락 없이 2년간 매일 24개 시각을 제공한다. 원본 로컬 시각의 시간·요일 의미를 보존하기 위해 `{BUILDING_TIMEZONE_PIPELINE}` 고정 표준시로 UTC 변환했다. 실제 서비스 CSV의 `America/Chicago` DST 처리와는 별도 호환성 규칙이 필요하다.

## 3. 사용 기간과 품질

- 원본 로컬 표준시: `{result['precheck']['local_start']}` ~ `{result['precheck']['local_end']}`
- UTC: `{q['start_utc']}` ~ `{q['end_utc']}`
- 예상/관측/유효 시간: {q['expected_hours']} / {q['observed_hours']} / {result['precheck']['valid_hours']}
- 결측률: {q['missing_rate']:.6%}
- 최대 연속 결측: {q['max_consecutive_missing_hours']}시간
- 0값/음수값: {q['zero_count']} / {result['precheck']['negative_count']}
- IQR 이상치 의심값: {q['suspicious_outlier_count']}
- 값 범위·평균: {result['precheck']['minimum_kwh']:.3f} ~ {result['precheck']['maximum_kwh']:.3f} kWh, 평균 {result['precheck']['mean_kwh']:.3f} kWh

## 4. 분할과 표본

| 구분 | UTC 기간 | 유효 조합 수 |
|---|---|---:|
| Train | {result['precheck']['split']['train_start']} ~ {result['precheck']['split']['train_end']} | {samples['train_dense']} |
| Validation dense | {result['precheck']['split']['validation_start']} ~ {result['precheck']['split']['validation_end']} | {samples['validation_dense']} |
| Validation 비중복 | 동일 구간, 24시간 간격 | {samples['validation_nonoverlap']} |
| Test 비중복 | {result['precheck']['split']['test_start']} ~ {result['precheck']['split']['test_end']} | {samples['test_nonoverlap']} |

잠정 1,000/168/12/12 기준을 모두 충족했다. 입력·출력 shape는 `[B,168,6] → [B,24]`다.

## 5. Validation 비교

{metric_table(result['validation_metrics'])}

선택 이유: `{', '.join(selection['reason_codes'])}`. GRU의 최우수 baseline 대비 MAE 개선률은 `{selection['gru_mae_improvement']}`다.

## 6. 독립 Test 비교

후보를 Validation에서 먼저 고정한 후 세 모델의 Test 지표를 보고용으로 계산했다. 아래 결과는 후보 재선택에 사용하지 않았다.

{metric_table(result['test_metrics'])}

## 7. 학습과 자원

- 데이터 원본 추출·사전 점검: {timing['source_precheck_seconds']:.3f}초
- 파이프라인 데이터 준비: {timing['pipeline_data_preparation_seconds']:.3f}초
- GRU 학습: {timing['gru_training_seconds']:.3f}초
- 산출물 저장: {timing['artifact_save_seconds']:.3f}초
- 전체 실험: {timing['total_experiment_seconds']:.3f}초
- 최대 working set: {timing['peak_working_set_bytes']:,} bytes ({timing['peak_working_set_mib']:.1f} MiB)
- 최적/종료 epoch: {result['training']['best_epoch']} / {result['training']['stopped_epoch']}
- Early stopping: {result['training']['early_stopping']}

## 8. 저장 및 재사용 추론

- run ID: `{RUN_ID}`
- 선택 예측기: `{selection['selected_model']}`
- run 상태: `candidate`
- 자동 승격: false
- GRU 후보 가중치 재로딩: {result['reuse']['gru_candidate_load_success']}
- 선택 예측기 24시간 추론 시간: {result['reuse']['selected_inference_seconds']:.6f}초
- 입력/출력: `{result['reuse']['input_shape']}` / `{result['reuse']['output_shape']}`
- 추론 중 재학습: {result['reuse']['retrained']}

## 9. 경고와 다음 실험 전 개선점

1. DST를 표현하지 않는 BDG2 로컬 시각 격자를 고정 표준시로 변환했다. 실제 사용자 CSV의 IANA DST 처리와 동일하지 않다.
2. 최신 180일 한 구간·한 건물 결과이므로 일반화 성능을 입증하지 않는다.
3. IQR 이상치 검사는 진단 전용이며 값을 제거하거나 보정하지 않았다.
4. Maggie 실험 전 고정 표준시 변환 정책을 명세에 추가하고, 실행기에서 source timezone mode를 manifest 필수 항목으로 승격해야 한다.
5. 이 run은 candidate일 뿐이며 `active_model.json`은 생성하거나 변경하지 않았다.

PM 승인 전 Maggie 또는 다른 건물 학습으로 진행하지 않는다.
"""


def main() -> None:
    if BUILDING_ID != "Hog_office_Leon":
        raise RuntimeError("Phase 7-2 runner is locked to Hog_office_Leon")
    expected_run = ARTIFACT_ROOT / BUILDING_ID / RUN_ID
    if expected_run.exists() or REPORT_ROOT.exists():
        raise FileExistsError("immutable experiment run already exists")

    experiment_started = time.perf_counter()
    working_start, _ = memory_bytes()
    metadata = pd.read_csv(METADATA_CSV)
    row = metadata.loc[metadata.building_id == BUILDING_ID]
    if len(row) != 1:
        raise RuntimeError("Leon metadata identity is not unique")
    meta = row.iloc[0]
    if meta.site_id != "Hog" or meta.primaryspaceusage != "Office" or meta.electricity != "Yes":
        raise RuntimeError("Leon metadata does not match approved scope")
    if meta.timezone != BUILDING_TIMEZONE_SOURCE:
        raise RuntimeError("unexpected source timezone")

    source = pd.read_csv(SOURCE_CSV, usecols=["timestamp", BUILDING_ID])
    source["timestamp"] = pd.to_datetime(source["timestamp"], format="%Y-%m-%d %H:%M:%S")
    end = source.timestamp.max()
    start = end - pd.Timedelta(hours=180 * 24 - 1)
    window = source.loc[
        (source.timestamp >= start) & (source.timestamp <= end), ["timestamp", BUILDING_ID]
    ].rename(columns={BUILDING_ID: "kwh"}).copy()
    contract = window.copy()
    contract["timestamp"] = contract.timestamp.dt.strftime("%Y-%m-%dT%H:%M:%S")
    data = validate_and_normalize_frame(contract, BUILDING_TIMEZONE_PIPELINE)
    quality = diagnose_quality(data)
    if quality.status != QualityStatus.PASS:
        raise RuntimeError(f"precheck quality failed: {quality.reason_codes}")
    plan = make_split_plan(data.index, quality.status)
    features = build_features(data, BUILDING_TIMEZONE_PIPELINE)
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

    # The single approved real-building training invocation.
    outcome = run_training_pipeline(
        contract,
        building_id=BUILDING_ID,
        building_timezone=BUILDING_TIMEZONE_PIPELINE,
        artifact_root=ARTIFACT_ROOT,
        run_id=RUN_ID,
        warning_approved=False,
        config=TrainingConfig(),
    )

    load_started = time.perf_counter()
    manifest, loaded_config, loaded_state, loaded_scalers = load_gru_artifacts(
        outcome.run_dir, expected_building_id=BUILDING_ID
    )
    gru_candidate_load_seconds = time.perf_counter() - load_started
    latest_features = build_features(data.iloc[-168:], BUILDING_TIMEZONE_PIPELINE)
    latest_x = latest_features.to_numpy(dtype=np.float32)[None, :, :]
    candidate_prediction = loaded_scalers.inverse_y(
        predict_gru(loaded_state, loaded_scalers.transform_x(latest_x), loaded_config)
    )
    inference_started = time.perf_counter()
    reuse = predict_from_run(
        outcome.run_dir, building_id=BUILDING_ID, normalized_data=data
    )
    selected_inference_seconds = time.perf_counter() - inference_started
    source_csv_hash = file_sha256(SOURCE_CSV)
    metadata_csv_hash = file_sha256(METADATA_CSV)
    _, peak_working = memory_bytes()
    total_experiment_seconds = time.perf_counter() - experiment_started

    selection = manifest["selection"]
    result = {
        "phase": "Phase 7-2",
        "status": "PASS",
        "building_id": BUILDING_ID,
        "run_id": RUN_ID,
        "training_invocations": 1,
        "source": {
            "cleaned_electricity_csv": str(SOURCE_CSV),
            "cleaned_electricity_sha256": source_csv_hash,
            "metadata_csv": str(METADATA_CSV),
            "metadata_sha256": metadata_csv_hash,
            "unit": "hourly interval kWh",
            "unit_evidence": "BDG2 notebooks/03_EDA-meter-reading.ipynb and Scientific Data 7, 368 (2020)",
            "source_timezone": BUILDING_TIMEZONE_SOURCE,
            "pipeline_timezone": BUILDING_TIMEZONE_PIPELINE,
            "timezone_mode": "fixed standard time; source grid has no DST duplicate/skip",
        },
        "precheck": {
            "local_start": start.isoformat(),
            "local_end": end.isoformat(),
            "valid_hours": int(window.kwh.notna().sum()),
            "negative_count": int((window.kwh < 0).sum()),
            "minimum_kwh": float(window.kwh.min()),
            "maximum_kwh": float(window.kwh.max()),
            "mean_kwh": float(window.kwh.mean()),
            "quality": to_jsonable(quality),
            "split": to_jsonable(plan),
            "samples": {
                "train_dense": len(train.x),
                "validation_dense": len(validation_dense.x),
                "validation_nonoverlap": len(validation_eval.x),
                "test_nonoverlap": len(test_eval.x),
                "minimum_policy": "PASS",
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
        "selection": selection,
        "test_metrics": outcome.test_metrics,
        "resources": {
            "source_precheck_seconds": source_precheck_seconds,
            "pipeline_data_preparation_seconds": outcome.data_preparation_seconds,
            "gru_training_seconds": outcome.training_seconds,
            "artifact_save_seconds": outcome.artifact_save_seconds,
            "pipeline_total_seconds": outcome.total_seconds,
            "total_experiment_seconds": total_experiment_seconds,
            "working_set_start_bytes": working_start,
            "peak_working_set_bytes": peak_working,
            "peak_working_set_mib": peak_working / 1024 / 1024,
        },
        "reuse": {
            "gru_candidate_load_success": True,
            "gru_candidate_load_seconds": gru_candidate_load_seconds,
            "gru_candidate_prediction_finite": bool(np.isfinite(candidate_prediction).all()),
            "gru_candidate_prediction_negative_count": int((candidate_prediction < 0).sum()),
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
        "active_model_changed": False,
        "test_used_for_reselection": False,
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=False)
    result_path = REPORT_ROOT / "phase7_2_leon_results.json"
    report_path = REPORT_ROOT / "phase7_2_leon_report.md"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(make_report(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
