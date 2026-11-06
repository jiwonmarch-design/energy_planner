"""Immutable, building-isolated artifact persistence."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import joblib
import numpy as np
import sklearn

from .contracts import (
    ENSEMBLE_50_50,
    PATCHTST,
    XGBOOST,
    ArtifactError,
    FEATURE_NAMES,
    PatchTSTConfig,
    SourceTimezoneMode,
    TrainingConfig,
    to_jsonable,
)
from .patchtst import PatchTSTScaler
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
    patchtst_config: PatchTSTConfig | None = None,
    xgboost_models: list[Any] | None = None,
    training_history: list[dict[str, Any]] | None = None,
    patchtst_model: Any | None = None,
    patchtst_scaler: PatchTSTScaler | None = None,
    patchtst_history: list[dict[str, Any]] | None = None,
    derived_input_csv: bytes | None = None,
    distribution_report: Any | None = None,
    source_timezone_mode: SourceTimezoneMode | str = SourceTimezoneMode.IANA_CIVIL_TIME,
    source_timezone_metadata: str | None = None,
) -> Path:
    """Create one immutable run directory; existing runs are never overwritten."""
    building_id = _safe_component(building_id, "building_id")
    run_id = _safe_component(run_id, "run_id")
    if model_kind not in {XGBOOST, PATCHTST, ENSEMBLE_50_50, "last_24h", "last_168h"}:
        raise ArtifactError(f"unsupported model kind: {model_kind}")
    if model_kind in {XGBOOST, ENSEMBLE_50_50} and not xgboost_models:
        raise ArtifactError("XGBoost artifacts require trained models")
    if model_kind in {PATCHTST, ENSEMBLE_50_50} and patchtst_model is None:
        raise ArtifactError("PatchTST artifacts require a trained model")
    if patchtst_model is not None and (patchtst_config is None or patchtst_scaler is None):
        raise ArtifactError("PatchTST artifacts require config and scaler")
    if xgboost_models is not None and len(xgboost_models) != 24:
        raise ArtifactError("XGBoost artifacts require 24 horizon models")
    run_dir = Path(artifact_root) / building_id / run_id
    if run_dir.exists():
        raise ArtifactError(f"run already exists and cannot be overwritten: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        _write_json(run_dir / "training_config.json", asdict(training_config))
        if patchtst_config is not None:
            _write_json(run_dir / "patchtst_config.json", asdict(patchtst_config))
        if patchtst_scaler is not None:
            _write_json(run_dir / "patchtst_scaler.json", patchtst_scaler.to_dict())
        _write_json(
            run_dir / "feature_spec.json",
            {
                "version": "xgboost-flat-a6-v1",
                "feature_names": FEATURE_NAMES,
                "lookback": 168,
                "horizon": 24,
                "table_columns": 168 * len(FEATURE_NAMES),
            },
        )
        _write_json(run_dir / "split_manifest.json", split_manifest)
        _write_json(run_dir / "evaluation_schedule.json", evaluation_schedule)
        _write_json(run_dir / "quality_report.json", quality_report)
        if distribution_report is not None:
            _write_json(run_dir / "distribution_report.json", distribution_report)
        _write_json(run_dir / "validation_metrics.json", validation_metrics)
        _write_json(run_dir / "test_metrics.json", test_metrics)
        if training_history is not None:
            fields = list(training_history[0]) if training_history else [
                "horizon",
                "best_iteration",
                "stopped_iteration",
                "best_validation_mae",
            ]
            with (run_dir / "training_history.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(training_history)
        if derived_input_csv is not None:
            (run_dir / "derived_input_utc.csv").write_bytes(derived_input_csv)
        if xgboost_models is not None:
            joblib.dump(xgboost_models, run_dir / "xgboost_models.joblib")
        if patchtst_model is not None:
            import torch

            state_dict = {
                name: value.detach().cpu() for name, value in patchtst_model.state_dict().items()
            }
            torch.save(state_dict, run_dir / "patchtst_state_dict.pth")
        if patchtst_history is not None:
            fields = list(patchtst_history[0]) if patchtst_history else [
                "epoch",
                "train_mse",
                "validation_mae",
            ]
            with (run_dir / "patchtst_history.csv").open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(patchtst_history)

        files = sorted(path for path in run_dir.iterdir() if path.name != "manifest.json")
        hashes = {path.name: _sha256(path) for path in files}
        manifest = {
            "schema_version": "hybrid-xgboost-patchtst-v1"
            if patchtst_model is not None
            else "xgboost-v1",
            "building_id": building_id,
            "run_id": run_id,
            "model_kind": model_kind,
            "building_timezone": building_timezone,
            "feature_timezone": building_timezone,
            "source_timezone_mode": SourceTimezoneMode(source_timezone_mode).value,
            "source_timezone_metadata": source_timezone_metadata or building_timezone,
            "dst_applied": SourceTimezoneMode(source_timezone_mode)
            == SourceTimezoneMode.IANA_CIVIL_TIME,
            "feature_names": FEATURE_NAMES,
            "input_shape": [None, 168, 6],
            "model_input_shape": [None, 1008],
            "output_shape": [None, 24],
            "data_sha256": data_hash,
            "selection": to_jsonable(selection),
            "xgboost_candidate_saved": xgboost_models is not None,
            "patchtst_candidate_saved": patchtst_model is not None,
            "ensemble_50_50_available": xgboost_models is not None and patchtst_model is not None,
            "status": "candidate",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "environment": {
                "python": platform.python_version(),
                "xgboost": _package_version("xgboost"),
                "torch": _package_version("torch"),
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
    feature_timezone = manifest.get("feature_timezone", manifest.get("building_timezone"))
    if not isinstance(feature_timezone, str) or not feature_timezone:
        raise ArtifactError("artifact feature timezone is missing")
    if (
        "feature_timezone" in manifest
        and manifest.get("building_timezone") is not None
        and manifest["feature_timezone"] != manifest["building_timezone"]
    ):
        raise ArtifactError("artifact feature timezone aliases disagree")
    # Backward compatibility is in-memory only; never rewrite an immutable run.
    manifest["feature_timezone"] = feature_timezone
    manifest.setdefault("building_timezone", feature_timezone)
    return manifest


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def load_xgboost_artifacts(
    run_dir: str | Path,
    *,
    expected_building_id: str,
) -> tuple[dict[str, Any], TrainingConfig, list[Any]]:
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir, expected_building_id=expected_building_id)
    if manifest["model_kind"] != "xgboost" and not manifest.get(
        "xgboost_candidate_saved", False
    ):
        raise ArtifactError("requested run does not contain an XGBoost candidate")
    config = TrainingConfig(
        **json.loads((run_dir / "training_config.json").read_text(encoding="utf-8"))
    )
    try:
        models = joblib.load(run_dir / "xgboost_models.joblib")
    except Exception as exc:
        raise ArtifactError("trusted local XGBoost artifacts could not be loaded") from exc
    if not isinstance(models, list) or len(models) != 24:
        raise ArtifactError("XGBoost horizon model bundle is invalid")
    return manifest, config, models


def load_patchtst_artifacts(
    run_dir: str | Path,
    *,
    expected_building_id: str,
) -> tuple[dict[str, Any], PatchTSTConfig, dict[str, Any], PatchTSTScaler]:
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir, expected_building_id=expected_building_id)
    if manifest["model_kind"] not in {PATCHTST, ENSEMBLE_50_50} and not manifest.get(
        "patchtst_candidate_saved", False
    ):
        raise ArtifactError("requested run does not contain a PatchTST candidate")
    try:
        config_payload = json.loads(
            (run_dir / "patchtst_config.json").read_text(encoding="utf-8")
        )
        # Runs created before the RevIN/overlapping-patch enhancement do not
        # contain these fields. Keep their exact original model graph in memory;
        # immutable artifact files are never rewritten.
        config_payload.setdefault("use_revin", False)
        config_payload.setdefault("revin_affine", False)
        config_payload.setdefault("revin_epsilon", 0.00001)
        config_payload.setdefault("gradient_clip_norm", None)
        config = PatchTSTConfig(**config_payload)
        scaler = PatchTSTScaler(
            **json.loads((run_dir / "patchtst_scaler.json").read_text(encoding="utf-8"))
        )
        import torch

        state_dict = torch.load(
            run_dir / "patchtst_state_dict.pth",
            map_location="cpu",
            weights_only=True,
        )
    except Exception as exc:
        raise ArtifactError("trusted local PatchTST artifacts could not be loaded") from exc
    if not isinstance(state_dict, dict):
        raise ArtifactError("PatchTST state dictionary is invalid")
    return manifest, config, state_dict, scaler


def load_gru_artifacts(
    run_dir: str | Path,
    *,
    expected_building_id: str,
) -> tuple[dict[str, Any], Any, dict[str, Any], ScalerBundle]:
    """Load a legacy immutable GRU run; new runs never call this function."""
    import torch
    run_dir = Path(run_dir)
    manifest = load_manifest(run_dir, expected_building_id=expected_building_id)
    if manifest["model_kind"] != "gru" and not manifest.get("gru_candidate_saved", False):
        raise ArtifactError("requested run does not contain a GRU candidate")
    config = SimpleNamespace(
        **json.loads((run_dir / "training_config.json").read_text(encoding="utf-8"))
    )
    try:
        state_dict = torch.load(run_dir / "model_state_dict.pth", map_location="cpu", weights_only=True)
        input_scaler = joblib.load(run_dir / "input_scaler.pkl")
        target_scaler = joblib.load(run_dir / "target_scaler.pkl")
    except Exception as exc:
        raise ArtifactError("trusted local run artifacts could not be loaded") from exc
    return manifest, config, state_dict, ScalerBundle(input_scaler, target_scaler)
