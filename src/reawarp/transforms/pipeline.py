"""High-level deterministic break transformation pipeline."""

from __future__ import annotations

import numpy as np

from reawarp.transforms.analysis import auto_slice
from reawarp.transforms.effects import (
    dropout,
    gate_audio,
    granular_resynthesis,
    pitch_shift,
    rearrange_slices,
    reverse_audio,
    spectral_freeze,
    stutter,
    time_stretch,
)


BREAK_TRANSFORMS = (
    "slice_rearrange",
    "stutter",
    "dropout",
    "reverse",
    "gate",
    "pitch_shift",
    "time_stretch",
    "granular",
    "spectral_freeze",
)


def apply_break_transforms(
    audio: np.ndarray,
    sample_rate: int,
    transforms: tuple[str, ...] | list[str],
    rng: np.random.Generator,
    *,
    slice_count: int = 16,
    stutter_repeats: int = 4,
    dropout_probability: float = 0.18,
    pitch_semitones: float = 0.0,
    stretch_factor: float = 1.0,
    gate_rate_hz: float = 8.0,
    gate_duty: float = 0.62,
    grain_size_ms: float = 80.0,
    grain_density: float = 1.5,
    freeze_position: float = 0.25,
) -> np.ndarray:
    """Apply named operations in order; the input buffer is never modified."""
    unknown = set(transforms) - set(BREAK_TRANSFORMS)
    if unknown:
        raise ValueError(f"unknown break transforms: {', '.join(sorted(unknown))}")
    if slice_count < 2:
        raise ValueError("slice_count must be at least two")
    result = np.asarray(audio, dtype=np.float32).copy()
    for operation in transforms:
        if operation == "slice_rearrange":
            slices = auto_slice(result, sample_rate, max_slices=slice_count)
            boundaries = [item.start for item in slices[1:]]
            if len(slices) < 2:
                boundaries = np.linspace(0, len(result), min(slice_count, len(result)) + 1)[1:-1]
                boundaries = [int(x) for x in boundaries]
            result = rearrange_slices(result, boundaries, rng=rng)
        elif operation == "stutter":
            if len(result):
                segment_end = max(1, int(round(len(result) * 0.25)))
                result = stutter(result, repeats=stutter_repeats, start=0, end=segment_end)
        elif operation == "dropout":
            result = dropout(
                result, probability=dropout_probability, sample_rate=sample_rate, rng=rng
            )
        elif operation == "reverse":
            result = reverse_audio(result)
        elif operation == "gate":
            result = gate_audio(result, sample_rate, rate_hz=gate_rate_hz, duty=gate_duty)
        elif operation == "pitch_shift":
            result = pitch_shift(result, pitch_semitones)
        elif operation == "time_stretch":
            result = time_stretch(result, stretch_factor)
        elif operation == "granular":
            result = granular_resynthesis(
                result,
                sample_rate,
                grain_size_ms=grain_size_ms,
                density=grain_density,
                rng=rng,
            )
        elif operation == "spectral_freeze":
            result = spectral_freeze(
                result, sample_rate, position=freeze_position, mix=1.0
            )
    return np.asarray(result, dtype=np.float32)
