"""Shared contracts for the standalone ML pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


LOOKBACK = 168
HORIZON = 24
FEATURE_NAMES = (
    "kwh",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "is_weekend",
)


class PipelineError(RuntimeError):
    """Base exception for a deterministic pipeline failure."""


class DataContractError(PipelineError):
    """The uploaded data does not satisfy the CSV contract."""


class EligibilityError(PipelineError):
    """The data is valid CSV but not eligible for the requested operation."""


class ArtifactError(PipelineError):
    """An artifact is missing, corrupt, mismatched, or would be overwritten."""


class QualityStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class SourceTimezoneMode(StrEnum):
    """How timestamp labels in an input source must be interpreted."""

    IANA_CIVIL_TIME = "iana_civil_time"
    EXPLICIT_OFFSET = "explicit_offset"
    BDG2_FIXED_STANDARD_LOCAL_GRID = "bdg2_naive_local_grid_fixed_standard"


@dataclass(frozen=True)
class TrainingConfig:
    input_size: int = 6
    lookback: int = LOOKBACK
    output_size: int = HORIZON
    hidden_size: int = 64
    num_layers: int = 2
    dropout: float = 0.1
    batch_size: int = 64
    learning_rate: float = 0.001
    max_epochs: int = 50
    patience: int = 7
    min_delta: float = 0.0001
    gradient_clip: float = 1.0
    seed: int = 42
    device: str = "cpu"


@dataclass
class QualityReport:
    status: QualityStatus
    reason_codes: list[str]
    start_utc: str | None
    end_utc: str | None
    elapsed_days: float
    expected_hours: int
    observed_hours: int
    missing_hours: int
    missing_rate: float
    max_consecutive_missing_hours: int
    zero_count: int
    zero_rate: float
    suspicious_outlier_count: int
    complete_168_windows: int
    complete_168_plus_24_pairs: int
    latest_168_complete: bool
    longest_constant_run_hours: int = 0
    dominant_value: float | None = None
    dominant_value_count: int = 0
    dominant_value_rate: float = 0.0
    suspected_state_transition: bool = False


@dataclass
class DistributionShiftReport:
    train_count: int
    validation_count: int
    test_count: int
    train_mean: float
    validation_mean: float
    test_mean: float
    train_std: float
    validation_std: float
    test_std: float
    validation_standardized_mean_shift: float | None
    test_standardized_mean_shift: float | None
    train_zero_variance: bool
    warning_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SplitPlan:
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    validation_days: int
    test_days: int
    warning_limited_experiment: bool


@dataclass
class SequenceBatch:
    x: Any
    y: Any
    origins: Any
    target_starts: Any


@dataclass
class EvaluationMetrics:
    mae: float
    rmse: float
    wape: float | None
    mape: float | None
    mape_excluded_count: int
    peak_mae: float
    peak_time_error_hours: float
    prediction_min: float
    prediction_max: float
    prediction_mean: float
    negative_count: int
    nonfinite_count: int


@dataclass
class SelectionDecision:
    selected_model: str
    best_baseline: str
    gru_eligible: bool
    reason_codes: list[str] = field(default_factory=list)
    gru_mae_improvement: float | None = None


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses and enums into JSON-safe primitives."""
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value
