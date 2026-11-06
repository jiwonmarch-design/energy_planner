"""Deterministic single-channel PatchTST training and inference."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Callable

import numpy as np

from .contracts import FEATURE_NAMES, HORIZON, LOOKBACK, PatchTSTConfig, SequenceBatch


@dataclass(frozen=True)
class PatchTSTScaler:
    mean: float
    scale: float

    @classmethod
    def fit(cls, train: SequenceBatch) -> "PatchTSTScaler":
        values = _kwh_channel(train.x)
        mean = float(np.mean(values))
        scale = float(np.std(values))
        if not np.isfinite(mean) or not np.isfinite(scale) or scale <= 0:
            raise ValueError("PatchTST training kWh channel must have finite non-zero variance")
        return cls(mean=mean, scale=scale)

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (np.asarray(values, dtype=np.float32) - self.mean) / self.scale

    def inverse(self, values: np.ndarray) -> np.ndarray:
        return np.asarray(values, dtype=np.float32) * self.scale + self.mean

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class PatchTSTTrainingOutcome:
    model: Any
    scaler: PatchTSTScaler
    best_epoch: int
    stopped_epoch: int
    best_validation_loss: float
    history: list[dict[str, float | int]]


def _torch_modules():
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise RuntimeError(
            "torch is required for PatchTST training; install backend/requirements.txt"
        ) from exc
    return torch, nn


def _kwh_channel(x: np.ndarray) -> np.ndarray:
    array = np.asarray(x, dtype=np.float32)
    expected = (LOOKBACK, len(FEATURE_NAMES))
    if array.ndim != 3 or array.shape[1:] != expected:
        raise ValueError(f"expected X shape [B,{expected[0]},{expected[1]}]")
    result = array[:, :, 0]
    if not np.isfinite(result).all():
        raise ValueError("PatchTST kWh inputs contain NaN or Inf")
    return result


def create_patchtst_model(config: PatchTSTConfig):
    torch, nn = _torch_modules()
    patch_count = (config.lookback - config.patch_length) // config.stride + 1
    if patch_count <= 0 or (config.lookback - config.patch_length) % config.stride:
        raise ValueError("PatchTST patches must cover the 168-hour input exactly")
    if config.d_model % config.n_heads:
        raise ValueError("PatchTST d_model must be divisible by n_heads")

    class SingleChannelPatchTST(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            if config.use_revin and config.revin_affine:
                self.revin_weight = nn.Parameter(torch.ones(1))
                self.revin_bias = nn.Parameter(torch.zeros(1))
            self.patch_projection = nn.Linear(config.patch_length, config.d_model)
            self.position = nn.Parameter(torch.zeros(1, patch_count, config.d_model))
            layer = nn.TransformerEncoderLayer(
                d_model=config.d_model,
                nhead=config.n_heads,
                dim_feedforward=config.dim_feedforward,
                dropout=config.dropout,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(
                layer,
                num_layers=config.encoder_layers,
                enable_nested_tensor=False,
            )
            self.head = nn.Sequential(
                nn.LayerNorm(patch_count * config.d_model),
                nn.Linear(patch_count * config.d_model, config.horizon),
            )

        def forward(self, values):
            if values.ndim != 2 or values.shape[1] != config.lookback:
                raise ValueError(f"expected PatchTST input shape [B,{config.lookback}]")
            if config.use_revin:
                center = values.mean(dim=1, keepdim=True).detach()
                scale = torch.sqrt(
                    values.var(dim=1, keepdim=True, unbiased=False) + config.revin_epsilon
                ).detach()
                model_values = (values - center) / scale
                if config.revin_affine:
                    model_values = model_values * self.revin_weight + self.revin_bias
            else:
                model_values = values
                center = None
                scale = None
            patches = model_values.unfold(1, config.patch_length, config.stride)
            encoded = self.patch_projection(patches) + self.position
            encoded = self.encoder(encoded)
            result = self.head(encoded.reshape(len(values), -1))
            if config.use_revin:
                if config.revin_affine:
                    safe_weight = torch.where(
                        self.revin_weight.abs() < config.revin_epsilon,
                        torch.full_like(self.revin_weight, config.revin_epsilon),
                        self.revin_weight,
                    )
                    result = (result - self.revin_bias) / safe_weight
                result = result * scale + center
            return result

    return SingleChannelPatchTST()


def load_patchtst_model(config: PatchTSTConfig, state_dict: dict[str, Any]):
    model = create_patchtst_model(config)
    model.load_state_dict(state_dict, strict=True)
    model.eval()
    return model


def train_patchtst(
    train: SequenceBatch,
    validation: SequenceBatch,
    config: PatchTSTConfig = PatchTSTConfig(),
    progress_callback: Callable[[int, int], None] | None = None,
) -> PatchTSTTrainingOutcome:
    """Train a single-channel 168-to-24 PatchTST candidate on CPU."""
    if len(train.x) == 0 or len(validation.x) == 0:
        raise ValueError("training and validation samples are required")
    torch, nn = _torch_modules()
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(config.num_threads)
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    try:
        scaler = PatchTSTScaler.fit(train)
        train_x = torch.from_numpy(scaler.transform(_kwh_channel(train.x)))
        validation_x = torch.from_numpy(scaler.transform(_kwh_channel(validation.x)))
        train_y_array = np.asarray(train.y, dtype=np.float32)
        validation_y_array = np.asarray(validation.y, dtype=np.float32)
        if train_y_array.shape != (len(train_x), HORIZON) or validation_y_array.shape != (
            len(validation_x),
            HORIZON,
        ):
            raise ValueError("expected PatchTST y shape [B,24]")
        train_y = torch.from_numpy(scaler.transform(train_y_array))
        validation_y = torch.from_numpy(scaler.transform(validation_y_array))

        model = create_patchtst_model(config)
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        loss_function = nn.MSELoss()
        generator = torch.Generator().manual_seed(config.seed)
        best_state = deepcopy(model.state_dict())
        best_epoch = 0
        best_loss = float("inf")
        stale_epochs = 0
        history: list[dict[str, float | int]] = []

        for epoch in range(config.epochs):
            model.train()
            permutation = torch.randperm(len(train_x), generator=generator)
            total_loss = 0.0
            for start in range(0, len(train_x), config.batch_size):
                batch_index = permutation[start : start + config.batch_size]
                optimizer.zero_grad(set_to_none=True)
                predictions = model(train_x[batch_index])
                loss = loss_function(predictions, train_y[batch_index])
                loss.backward()
                if config.gradient_clip_norm is not None:
                    nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip_norm)
                optimizer.step()
                total_loss += float(loss.detach()) * len(batch_index)

            model.eval()
            with torch.inference_mode():
                validation_prediction = scaler.inverse(model(validation_x).cpu().numpy())
            validation_mae = float(np.mean(np.abs(validation_prediction - validation_y_array)))
            if not np.isfinite(validation_mae):
                raise RuntimeError("PatchTST training did not produce finite validation metrics")
            history.append(
                {
                    "epoch": epoch + 1,
                    "train_mse": total_loss / len(train_x),
                    "validation_mae": validation_mae,
                }
            )
            if validation_mae < best_loss - 1e-12:
                best_loss = validation_mae
                best_epoch = epoch
                best_state = deepcopy(model.state_dict())
                stale_epochs = 0
            else:
                stale_epochs += 1
            if progress_callback is not None:
                progress_callback(epoch + 1, config.epochs)
            if stale_epochs >= config.patience:
                break

        model.load_state_dict(best_state, strict=True)
        model.eval()
        return PatchTSTTrainingOutcome(
            model=model,
            scaler=scaler,
            best_epoch=best_epoch,
            stopped_epoch=len(history) - 1,
            best_validation_loss=best_loss,
            history=history,
        )
    finally:
        torch.set_num_threads(previous_threads)


def predict_patchtst(
    model,
    scaler: PatchTSTScaler,
    x: np.ndarray,
) -> np.ndarray:
    torch, _ = _torch_modules()
    inputs = torch.from_numpy(scaler.transform(_kwh_channel(x)))
    model.eval()
    with torch.inference_mode():
        result = scaler.inverse(model(inputs).cpu().numpy()).astype(float)
    if result.shape != (len(x), HORIZON) or not np.isfinite(result).all():
        raise RuntimeError("invalid PatchTST output")
    return result
