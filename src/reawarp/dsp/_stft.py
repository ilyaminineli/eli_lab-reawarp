"""Small NumPy-only STFT helpers shared by offline M24 spectral modules."""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def audio_channels(audio: Any, name: str = "audio") -> tuple[np.ndarray, bool]:
    value = np.asarray(audio)
    if value.dtype.kind not in {"f", "i", "u"}:
        raise ValueError(f"{name} must be a real numeric audio array")
    if value.ndim == 1:
        was_vector = True
        value = value[:, None]
    elif value.ndim == 2 and value.shape[1] in {1, 2}:
        was_vector = False
    else:
        raise ValueError(f"{name} must be mono or stereo (frames, channels)")
    value = np.asarray(value, dtype=np.float32)
    if not np.isfinite(value).all():
        raise ValueError(f"{name} must contain only finite samples")
    return np.ascontiguousarray(value), was_vector


def finite_range(value: Any, name: str, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < low or result > high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return result


def validate_stft(frame_size: int, hop_size: int) -> tuple[int, int]:
    if isinstance(frame_size, bool) or not isinstance(frame_size, int):
        raise ValueError("frame_size must be an integer power of two")
    if frame_size < 256 or frame_size > 8192 or frame_size & (frame_size - 1):
        raise ValueError("frame_size must be a power of two between 256 and 8192")
    if isinstance(hop_size, bool) or not isinstance(hop_size, int):
        raise ValueError("hop_size must be an integer")
    if hop_size < 1 or hop_size > frame_size // 2 or frame_size % hop_size:
        raise ValueError("hop_size must divide frame_size and be <= frame_size/2")
    return frame_size, hop_size


def stft(audio: np.ndarray, frame_size: int, hop_size: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Centered periodic-Hann STFT with deterministic zero padding and WOLA metadata."""
    source, was_vector = audio_channels(audio)
    validate_stft(frame_size, hop_size)
    frame_count = 0 if len(source) == 0 else 1 + int(math.ceil((len(source) - 1) / hop_size))
    window = np.hanning(frame_size + 1)[:-1].astype(np.float64)
    if frame_count == 0:
        return np.zeros((0, frame_size // 2 + 1, source.shape[1]), dtype=np.complex128), {
            "window": window, "pad_left": frame_size // 2, "input_frames": 0,
            "frame_size": frame_size, "hop_size": hop_size, "was_vector": was_vector,
        }
    pad = frame_size // 2
    padded = np.pad(source.astype(np.float64), ((pad, pad + hop_size), (0, 0)))
    frames = np.empty((frame_count, frame_size, source.shape[1]), dtype=np.float64)
    for index in range(frame_count):
        start = index * hop_size
        frames[index] = padded[start:start + frame_size] * window[:, None]
    spectra = np.fft.rfft(frames, axis=1)
    return spectra, {
        "window": window, "pad_left": pad, "input_frames": len(source),
        "frame_size": frame_size, "hop_size": hop_size, "was_vector": was_vector,
    }


def istft(spectra: np.ndarray, metadata: dict[str, Any], output_frames: int | None = None) -> np.ndarray:
    """Weighted overlap-add inverse, cropped to the requested aligned file length."""
    frame_size = int(metadata["frame_size"])
    hop_size = int(metadata["hop_size"])
    window = np.asarray(metadata["window"], dtype=np.float64)
    pad = int(metadata["pad_left"])
    channels = int(spectra.shape[2]) if spectra.ndim == 3 else 1
    frames = np.fft.irfft(spectra, n=frame_size, axis=1)
    total = max(0, (len(frames) - 1) * hop_size + frame_size)
    accumulated = np.zeros((total, channels), dtype=np.float64)
    weights = np.zeros(total, dtype=np.float64)
    window_sq = window * window
    for index, frame in enumerate(frames):
        start = index * hop_size
        accumulated[start:start + frame_size] += frame * window[:, None]
        weights[start:start + frame_size] += window_sq
    valid = weights > 1e-12
    accumulated[valid] /= weights[valid, None]
    accumulated[~valid] = 0.0
    length = int(metadata["input_frames"] if output_frames is None else output_frames)
    result = accumulated[pad:pad + length]
    if len(result) < length:
        result = np.pad(result, ((0, length - len(result)), (0, 0)))
    if not np.isfinite(result).all():
        raise FloatingPointError("STFT synthesis produced non-finite output")
    result = np.ascontiguousarray(result, dtype=np.float32)
    if metadata.get("was_vector") and result.shape[1] == 1:
        return result[:, 0]
    return result


def restore_shape(audio: np.ndarray, was_vector: bool) -> np.ndarray:
    result = np.asarray(audio, dtype=np.float32)
    if was_vector and result.ndim == 2 and result.shape[1] == 1:
        result = result[:, 0]
    return np.ascontiguousarray(result)


def signal_diagnostics(audio: np.ndarray) -> dict[str, Any]:
    value = np.asarray(audio, dtype=np.float64)
    peak = float(np.max(np.abs(value))) if value.size else 0.0
    rms = float(np.sqrt(np.mean(value * value))) if value.size else 0.0
    return {
        "finite_output": bool(np.isfinite(value).all()),
        "peak": peak,
        "rms": rms,
        "headroom_db": float(20.0 * math.log10(1.0 / peak)) if peak > 0.0 else None,
        "over_unity": peak > 1.0,
        "denormal_sample_count": int(np.count_nonzero((np.abs(value) > 0.0) & (np.abs(value) < np.finfo(np.float32).tiny))),
        "output_bytes": int(np.asarray(audio).nbytes),
    }
