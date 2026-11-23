"""Dependency-free 16-bit and 24-bit PCM WAV output."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int, bit_depth: int = 24) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = np.column_stack((samples, samples))
    if samples.ndim != 2 or samples.shape[1] not in (1, 2):
        raise ValueError("audio must have shape (frames,), (frames, 1), or (frames, 2)")
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    samples = np.clip(samples, -1.0, 1.0 - (1.0 / (1 << (bit_depth - 1))))

    if bit_depth == 16:
        pcm = np.round(samples * 32767.0).astype("<i2").tobytes()
        sample_width = 2
    elif bit_depth == 24:
        integers = np.round(samples * 8388607.0).astype(np.int32)
        packed = np.empty((integers.size, 3), dtype=np.uint8)
        flat = integers.reshape(-1)
        packed[:, 0] = flat & 0xFF
        packed[:, 1] = (flat >> 8) & 0xFF
        packed[:, 2] = (flat >> 16) & 0xFF
        pcm = packed.tobytes()
        sample_width = 3
    else:
        raise ValueError("bit_depth must be 16 or 24")

    with wave.open(str(destination), "wb") as wav:
        wav.setnchannels(samples.shape[1])
        wav.setsampwidth(sample_width)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm)
    return destination
