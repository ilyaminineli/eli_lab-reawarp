"""Oversampled, FIR-reconstructed nonlinear waveshaping reference processors."""
from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from reawarp.dsp._stft import audio_channels, finite_range, restore_shape, signal_diagnostics


class NonlinearResult:
    __slots__ = ("audio", "diagnostics")
    def __init__(self, audio: np.ndarray, diagnostics: dict[str, Any]):
        self.audio = audio
        self.diagnostics = diagnostics


def _fir_lowpass(factor: int, taps_per_phase: int) -> np.ndarray:
    """Kaiser-windowed sinc at the post-decimation Nyquist frequency."""
    length = 2 * taps_per_phase * factor + 1
    centre = length // 2
    indices = np.arange(length, dtype=np.float64) - centre
    cutoff = 0.5 / factor
    kernel = 2.0 * cutoff * np.sinc(2.0 * cutoff * indices)
    kernel *= np.kaiser(length, 8.6)
    kernel /= np.sum(kernel)
    return kernel


def _filter_aligned(audio: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    delay = len(kernel) // 2
    channels = audio.shape[1]
    output = np.empty_like(audio, dtype=np.float64)
    for channel in range(channels):
        filtered = np.convolve(audio[:, channel], kernel, mode="full")
        output[:, channel] = filtered[delay:delay + len(audio)]
    return output


def _shape(signal: np.ndarray, shape: str, drive: float, clip_level: float) -> np.ndarray:
    driven = signal * drive
    if shape == "tanh":
        return np.tanh(driven)
    if shape == "atan":
        return (2.0 / math.pi) * np.arctan(driven)
    if shape == "hard_clip":
        return np.clip(driven, -clip_level, clip_level)
    if shape == "sine_fold":
        return np.sin(driven)
    if shape == "softsign":
        return driven / (1.0 + np.abs(driven))
    raise ValueError("shape must be one of: tanh, atan, hard_clip, sine_fold, softsign")


def oversampled_waveshaper(
    audio: np.ndarray,
    sample_rate: int,
    *,
    shape: str = "tanh",
    drive: float = 2.0,
    oversample: int = 4,
    clip_level: float = 1.0,
    output_gain: float = 1.0,
    wet: float = 1.0,
    taps_per_phase: int = 16,
    bypass: bool = False,
) -> NonlinearResult:
    """Apply an explicit waveshaper at 1x/2x/4x/8x, then anti-alias and decimate.

    Interpolation inserts zeros and uses an FIR with DC gain equal to the
    oversampling factor. The same unity-DC low-pass kernel is used before
    decimation. Both symmetric FIR group delays are trimmed in this offline
    renderer; output file alignment therefore remains zero-latency.
    """
    source, was_vector = audio_channels(audio, "input audio")
    if isinstance(sample_rate, bool) or int(sample_rate) != sample_rate or int(sample_rate) < 1000:
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    rate = int(sample_rate)
    if isinstance(oversample, bool) or oversample not in {1, 2, 4, 8}:
        raise ValueError("oversample must be one of 1, 2, 4, or 8")
    if shape not in {"tanh", "atan", "hard_clip", "sine_fold", "softsign"}:
        raise ValueError("unsupported nonlinear shape")
    amount = finite_range(wet, "wet", 0.0, 1.0)
    gain = finite_range(drive, "drive", 0.01, 32.0)
    threshold = finite_range(clip_level, "clip_level", 0.01, 4.0)
    out_gain = finite_range(output_gain, "output_gain", 0.0, 4.0)
    if isinstance(taps_per_phase, bool) or not isinstance(taps_per_phase, int) or not 8 <= taps_per_phase <= 64:
        raise ValueError("taps_per_phase must be an integer between 8 and 64")
    started = time.perf_counter()
    if bypass or amount == 0.0 or len(source) == 0:
        output = restore_shape(source.copy(), was_vector)
        return NonlinearResult(output, {
            "module": "m24.4.oversampled_nonlinear", "algorithm": "bypass", "bypass": True,
            "sample_rate": rate, "input_frames": len(source), "output_frames": len(source),
            "tail_frames": 0, "latency_frames": 0, "oversample": oversample,
            "processing_seconds": time.perf_counter() - started,
            **signal_diagnostics(output),
        })

    if oversample == 1:
        high_rate = source.astype(np.float64)
        kernel = np.asarray([1.0], dtype=np.float64)
        shaped = _shape(high_rate, shape, gain, threshold)
        aligned = shaped
        filter_length = 1
    else:
        kernel = _fir_lowpass(oversample, taps_per_phase)
        upsampled = np.zeros((len(source) * oversample, source.shape[1]), dtype=np.float64)
        upsampled[::oversample] = source
        high_rate = _filter_aligned(upsampled, kernel * oversample)
        shaped = _shape(high_rate, shape, gain, threshold)
        filtered = _filter_aligned(shaped, kernel)
        aligned = filtered[::oversample]
        filter_length = len(kernel)
    processed = aligned * out_gain
    output = source.astype(np.float64) * (1.0 - amount) + processed * amount
    output = restore_shape(output, was_vector)
    diagnostics = {
        "module": "m24.4.oversampled_nonlinear", "algorithm": "kaiser_sinc_oversample_shape_decimate",
        "bypass": False, "sample_rate": rate, "shape": shape, "drive": gain,
        "oversample": oversample, "internal_sample_rate": rate * oversample,
        "clip_level": threshold if shape == "hard_clip" else None,
        "output_gain": out_gain, "wet": amount,
        "anti_alias_filter": "kaiser_windowed_sinc" if oversample > 1 else "disabled_native_rate",
        "anti_alias_cutoff_hz": rate / 2.0 if oversample > 1 else None,
        "anti_alias_filter_taps": filter_length,
        "kaiser_beta": 8.6 if oversample > 1 else None,
        "fir_group_delay_high_rate_samples_per_stage": (filter_length - 1) // 2 if oversample > 1 else 0,
        "delay_compensated": True, "latency_frames": 0, "tail_frames": 0,
        "input_frames": len(source), "output_frames": len(output),
        "estimated_working_bytes": int(source.nbytes * (oversample + 5) + high_rate.nbytes + shaped.nbytes),
        "processing_seconds": time.perf_counter() - started,
        **signal_diagnostics(output),
    }
    return NonlinearResult(output, diagnostics)
