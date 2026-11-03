"""Read-only GRU definition for immutable legacy runs.

New training must not import this module.
"""

from __future__ import annotations

import torch
from torch import nn


class GRUForecaster(nn.Module):
    def __init__(self, config) -> None:
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
        encoded, _ = self.gru(x)
        return self.output(encoded[:, -1, :])
