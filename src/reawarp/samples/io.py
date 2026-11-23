"""Small WAV sample reader with optional SoundFile support."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def _read_pcm_wave(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        compression = wav.getcomptype()
        raw = wav.readframes(frame_count)
    if compression != "NONE":
        raise ValueError(f"unsupported WAV compression in {path}: {compression}")
    if channels < 1:
        raise ValueError(f"WAV has no channels: {path}")

    if sample_width == 1:
        values = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        values = (values - 128.0) / 128.0
    elif sample_width == 2:
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8)
        if packed.size % 3:
            raise ValueError(f"malformed 24-bit PCM data in {path}")
        packed = packed.reshape(-1, 3).astype(np.int32)
        integers = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        integers = np.where(integers & 0x800000, integers - 0x1000000, integers)
        values = integers.astype(np.float32) / 8388608.0
    elif sample_width == 4:
        values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported PCM bit depth ({sample_width * 8}) in {path}")

    if values.size % channels:
        raise ValueError(f"malformed channel data in {path}")
    audio = values.reshape(-1, channels).mean(axis=1)
    return np.asarray(audio, dtype=np.float32), sample_rate


def read_sample(path: str | Path, target_sample_rate: int) -> np.ndarray:
    """Read an audio file as mono float32 and linearly resample to target rate."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"sample not found: {source}")

    try:
        import soundfile as sf

        audio, source_rate = sf.read(str(source), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
    except ImportError:
        if source.suffix.lower() != ".wav":
            raise ValueError("non-WAV sample import requires the optional soundfile package")
        audio, source_rate = _read_pcm_wave(source)

    if audio.size == 0:
        raise ValueError(f"sample is empty: {source}")
    if not np.all(np.isfinite(audio)):
        audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    audio = np.clip(audio, -1.0, 1.0).astype(np.float32, copy=False)

    if source_rate != target_sample_rate:
        new_length = max(1, int(round(len(audio) * target_sample_rate / source_rate)))
        old_positions = np.arange(len(audio), dtype=np.float64)
        new_positions = np.linspace(0.0, max(0.0, len(audio) - 1.0), new_length)
        audio = np.interp(new_positions, old_positions, audio).astype(np.float32)
    return audio
