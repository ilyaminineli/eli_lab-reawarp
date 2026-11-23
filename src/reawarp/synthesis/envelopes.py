"""Small vectorized envelope helpers."""

from __future__ import annotations

import numpy as np


def exponential_decay(
        length: int,
        sample_rate: int,
        decay_seconds: float,
        attack_seconds: float = 0.001,
) -> np.ndarray:
    if length <= 0:
        return np.empty(0, dtype=np.float32)
    time = np.arange(length, dtype=np.float64) / float(sample_rate)
    attack = 1.0 - np.exp(-time / max(attack_seconds, 1e-5))
    decay = np.exp(-time / max(decay_seconds, 1e-4))
    return (attack * decay).astype(np.float32)


def one_shot(length: int, sample_rate: int, attack: float, decay: float) -> np.ndarray:
    return exponential_decay(length, sample_rate, decay, attack)
