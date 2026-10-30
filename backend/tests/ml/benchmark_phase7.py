"""Run a full default-config Phase 7 synthetic CPU benchmark."""

from __future__ import annotations

import ctypes
import json
import tempfile
import time
from dataclasses import asdict

from backend.app.ml.contracts import TrainingConfig, to_jsonable
from backend.app.ml.inference import predict_from_run
from backend.app.ml.quality import validate_and_normalize_frame
from backend.app.ml.train import run_training_pipeline
from backend.tests.ml.synthetic import hourly_frame


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
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        raise OSError("GetProcessMemoryInfo failed")
    return counters.WorkingSetSize, counters.PeakWorkingSetSize


def main() -> None:
    frame = hourly_frame(90)
    start_working, _ = memory_bytes()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as temporary:
        outcome = run_training_pipeline(
            frame,
            building_id="synthetic-90d",
            building_timezone="Asia/Seoul",
            artifact_root=temporary,
            run_id="phase7-default",
            warning_approved=True,
            config=TrainingConfig(),
        )
        elapsed = time.perf_counter() - started
        normalized = validate_and_normalize_frame(frame, "Asia/Seoul")
        inference_started = time.perf_counter()
        inference = predict_from_run(
            outcome.run_dir,
            building_id="synthetic-90d",
            normalized_data=normalized,
        )
        inference_elapsed = time.perf_counter() - inference_started
        current_working, peak_working = memory_bytes()
        result = {
            "config": asdict(TrainingConfig()),
            "pipeline": to_jsonable(outcome),
            "elapsed_seconds": elapsed,
            "inference_seconds": inference_elapsed,
            "working_set_start_bytes": start_working,
            "working_set_end_bytes": current_working,
            "peak_working_set_bytes": peak_working,
            "working_set_increase_bytes": current_working - start_working,
            "inference": to_jsonable(inference),
            "artifact_reload_success": True,
        }
        result["pipeline"]["run_dir"] = "<temporary>/synthetic-90d/phase7-default"
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
