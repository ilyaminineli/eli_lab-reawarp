"""Dependency-free 16-bit and 24-bit PCM WAV output."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(
    path: str | Path, audio: np.ndarray, sample_rate: int, bit_depth: int = 24
) -> Path:
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


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Read a PCM WAV as channel-last float32 audio without downmixing."""
    source = Path(path)
    with wave.open(str(source), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        compression = wav_file.getcomptype()
        raw = wav_file.readframes(frame_count)

    if compression != "NONE":
        raise ValueError(f"unsupported WAV compression in {source}: {compression}")
    if channels not in (1, 2):
        raise ValueError(f"WAV must contain one or two channels: {source}")
    if sample_rate <= 0:
        raise ValueError(f"WAV sample rate must be positive: {source}")

    if sample_width == 1:
        values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8)
        if packed.size % 3:
            raise ValueError(f"malformed 24-bit PCM data in {source}")
        packed = packed.reshape(-1, 3).astype(np.int32)
        integers = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        integers = np.where(integers & 0x800000, integers - 0x1000000, integers)
        values = integers.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported PCM bit depth ({sample_width * 8}) in {source}")

    expected_values = frame_count * channels
    if values.size != expected_values:
        raise ValueError(f"malformed PCM frame data in {source}")
    return (
        values.reshape(frame_count, channels).astype(np.float32, copy=False),
        sample_rate,
    )
