"""Immutable, building-isolated artifact persistence."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
import torch

from .contracts import (
    ArtifactError,
    FEATURE_NAMES,
    SourceTimezoneMode,
    TrainingConfig,
    to_jsonable,
)
from .scaling import ScalerBundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or any(char in value for char in "\\/:*?\"<>|"):
        raise ArtifactError(f"unsafe {label}: {value!r}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")


def save_run_artifacts(
    artifact_root: str | Path,
    *,
    building_id: str,
    run_id: str,
    model_kind: str,
    building_timezone: str,
    training_config: TrainingConfig,
    split_manifest: dict[str, Any],
    evaluation_schedule: dict[str, Any],
    quality_report: Any,
    validation_metrics: dict[str, Any],
    test_metrics: dict[str, Any],
    selection: Any,
    data_hash: str,
    state_dict: dict[str, torch.Tensor] | None = None,
    scalers: ScalerBundle | None = None,
    training_history: list[dict[str, Any]] | None = None,
    derived_input_csv: bytes | None = None,
    distribution_report: Any | None = None,
    source_timezone_mode: SourceTimezoneMode | str = SourceTimezoneMode.IANA_CIVIL_TIME,
    source_timezone_metadata: str | None = None,
) -> Path:
    """Create one immutable run directory; existing runs are never overwritten."""
    building_id = _safe_component(building_id, "building_id")
    run_id = _safe_component(run_id, "run_id")
    if model_kind not in {"gru", "last_24h", "last_168h"}:
        raise ArtifactError(f"unsupported model kind: {model_kind}")
    if (state_dict is None) != (scalers is None):
        raise ArtifactError("state_dict and scalers must be supplied together")
    if model_kind == "gru" and (state_dict is None or scalers is None):
        raise ArtifactError("GRU artifacts require state_dict and scalers")
    run_dir = Path(artifact_root) / building_id / run_id
    if run_dir.exists():
        raise ArtifactError(f"run already exists and cannot be overwritten: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        _write_json(run_dir / "training_config.json", asdict(training_config))
        _write_json(
            run_dir / "feature_spec.json",
            {"version": "a6-v1", "feature_names": FEATURE_NAMES, "lookback": 168, "horizon": 24},
        )
        _write_json(run_dir / "split_manifest.json", split_manifest)
        _write_json(run_dir / "evaluation_schedule.json", evaluation_schedule)
        _write_json(run_dir / "quality_report.json", quality_report)
        if distribution_report is not None:
            _write_json(run_dir / "distribution_report.json", distribution_report)
        _write_json(run_dir / "validation_metrics.json", validation_metrics)
        _write_json(run_dir / "test_metrics.json", test_metrics)
        if training_history is not None:
            fields = list(training_history[0]) if training_history else ["epoch", "train_loss", "validation_loss"]
            with (run_dir / "training_history.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(training_history)
        if derived_input_csv is not None:
            (run_dir / "derived_input_utc.csv").write_bytes(derived_input_csv)
        if state_dict is not None and scalers is not None:
            torch.save(state_dict, run_dir / "model_state_dict.pth")
            joblib.dump(scalers.input_scaler, run_dir / "input_scaler.pkl")
            joblib.dump(scalers.target_scaler, run_dir / "target_scaler.pkl")

        files = sorted(path for path in run_dir.iterdir() if path.name != "manifest.json")
        hashes = {path.name: _sha256(path) for path in files}
        manifest = {
            "schema_version": "phase7.4-v1",
            "building_id": building_id,
            "run_id": run_id,
            "model_kind": model_kind,
            "building_timezone": building_timezone,
            "source_timezone_mode": SourceTimezoneMode(source_timezone_mode).value,
            "source_timezone_metadata": source_timezone_metadata or building_timezone,
            "dst_applied": SourceTimezoneMode(source_timezone_mode)
            == SourceTimezoneMode.IANA_CIVIL_TIME,
            "feature_names": FEATURE_NAMES,
            "input_shape": [None, 168, 6],
            "output_shape": [None, 24],
            "data_sha256": data_hash,
            "selection": to_jsonable(selection),
            "gru_candidate_saved": state_dict is not None,
            "status": "candidate",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "environment": {
                "python": platform.python_version(),
                "torch": torch.__version__,
                "numpy": np.__version__,
                "sklearn": sklearn.__version__,
                "device": "cpu",
            },
            "file_sha256": hashes,
            "auto_promoted": False,
        }
        _write_json(run_dir / "manifest.json", manifest)
        return run_dir
    except Exception:
        # Keep the failed staging directory for diagnosis; never pretend success.
        raise


def load_manifest(run_dir: str | Path, *, expected_building_id: str | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ArtifactError("manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if expected_building_id is not None and manifest.get("building_id") != expected_building_id:
        raise ArtifactError("artifact building identity mismatch")
    if tuple(manifest.get("feature_names", ())) != FEATURE_NAMES:
        raise ArtifactError("artifact feature contract mismatch")
    timezone_mode = manifest.get(
        "source_timezone_mode", SourceTimezoneMode.IANA_CIVIL_TIME.value
    )
    try:
        SourceTimezoneMode(timezone_mode)
    except ValueError as exc:
        raise ArtifactError("artifact source timezone mode is invalid") from exc
    for name, expected_hash in manifest.get("file_sha256", {}).items():
        path = run_dir / name
        if not path.is_file() or _sha256(path) != expected_hash:
            raise ArtifactError(f"artifact hash mismatch: {name}")
    return manifest


def load_gru_artifacts(
    run_dir: str | Path,
    *,
    expected_building_id: str,
) -> tuple[dict[str, Any], TrainingConfig, dict[str, torch.Tensor], ScalerBundle]:
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir, expected_building_id=expected_building_id)
    if manifest["model_kind"] != "gru" and not manifest.get("gru_candidate_saved", False):
        raise ArtifactError("requested run does not contain a GRU candidate")
    config = TrainingConfig(**json.loads((run_dir / "training_config.json").read_text(encoding="utf-8")))
    try:
        state_dict = torch.load(run_dir / "model_state_dict.pth", map_location="cpu", weights_only=True)
        input_scaler = joblib.load(run_dir / "input_scaler.pkl")
        target_scaler = joblib.load(run_dir / "target_scaler.pkl")
    except Exception as exc:
        raise ArtifactError("trusted local run artifacts could not be loaded") from exc
    return manifest, config, state_dict, ScalerBundle(input_scaler, target_scaler)
