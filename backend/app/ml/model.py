"""PyTorch GRU forecasting model."""

from __future__ import annotations

import random

import numpy as np
import torch
from torch import nn

from .contracts import TrainingConfig


def set_deterministic_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


class GRUForecaster(nn.Module):
    def __init__(self, config: TrainingConfig):
        super().__init__()
        self.config = config
        self.gru = nn.GRU(
            input_size=config.input_size,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.output = nn.Linear(config.hidden_size, config.output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1] != self.config.lookback or x.shape[2] != self.config.input_size:
            raise ValueError(
                f"expected [B,{self.config.lookback},{self.config.input_size}], got {tuple(x.shape)}"
            )
        encoded, _ = self.gru(x)
        return self.output(encoded[:, -1, :])
