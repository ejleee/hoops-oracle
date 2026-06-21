"""
Win probability MLP definition.

Input features (8 total — must stay in sync with data/features.py):
  score_differential, seconds_remaining, quarter, home_possession,
  home_fouls, away_fouls, home_win_rate, away_win_rate

Output: single sigmoid unit → P(home team wins)
"""

import torch
import torch.nn as nn

INPUT_SIZE = 8


class WinProbabilityModel(nn.Module):
    def __init__(self, hidden_sizes: list[int] | None = None) -> None:
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [64, 32, 16]

        layer_sizes = [INPUT_SIZE] + hidden_sizes

        layers: list[nn.Module] = []
        for in_size, out_size in zip(layer_sizes[:-1], layer_sizes[1:]):
            layers.append(nn.Linear(in_size, out_size))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(p=0.2))

        # Final sigmoid for binary probability output
        layers.append(nn.Linear(hidden_sizes[-1], 1))
        layers.append(nn.Sigmoid())

        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch_size, INPUT_SIZE) → output: (batch_size, 1)
        return self.network(x)
