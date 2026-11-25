"""Frequency-region spectral delay with bounded, offline spectral feedback."""
from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from reawarp.dsp._stft import audio_channels, finite_range, istft, restore_shape, signal_diagnostics, stft



class SpectralDelayResult:
    __slots__ = ("audio", "diagnostics")
    def __init__(self, audio: np.ndarray, diagnostics: dict[str, Any]):
        self.audio = audio
        self.diagnostics = diagnostics


def _normalise_bands(bands: Sequence[Mapping[str, Any]] | None, sample_rate: int, feedback: float) -> list[dict[str, float]]:
    nyquist = sample_rate / 2.0
    source = bands if bands is not None else [{"low_hz": 0.0, "high_hz": nyquist, "delay_ms": 180.0}]
    if not source:
        raise ValueError("frequency_bands cannot be empty")
    result: list[dict[str, float]] = []
    for index, band in enumerate(source):
        if not isinstance(band, Mapping):
            raise ValueError(f"frequency_bands[{index}] must be an object")
        low = finite_range(band.get("low_hz"), f"frequency_bands[{index}].low_hz", 0.0, nyquist)
        high = finite_range(band.get("high_hz"), f"frequency_bands[{index}].high_hz", 0.0, nyquist)
        delay = finite_range(band.get("delay_ms"), f"frequency_bands[{index}].delay_ms", 0.0, 2000.0)
        fb = finite_range(band.get("feedback", feedback), f"frequency_bands[{index}].feedback", 0.0, 0.85)
        gain = finite_range(band.get("gain", 1.0), f"frequency_bands[{index}].gain", 0.0, 1.5)
        if high <= low:
            raise ValueError(f"frequency_bands[{index}] high_hz must exceed low_hz")
        result.append({"low_hz": low, "high_hz": high, "delay_ms": delay, "feedback": fb, "gain": gain})
    ordered = sorted(result, key=lambda item: item["low_hz"])
    for left, right in zip(ordered, ordered[1:]):
        if right["low_hz"] < left["high_hz"]:
            raise ValueError("frequency_bands must not overlap")
    return result


def spectral_delay(
    audio: np.ndarray,
    sample_rate: int,
    *,
    frequency_bands: Sequence[Mapping[str, Any]] | None = None,
    frame_size: int = 1024,
    hop_size: int = 256,
    feedback: float = 0.35,
    wet: float = 1.0,
    transient_preserve: float = 0.25,
    max_tail_seconds: float = 12.0,
    bypass: bool = False,
) -> SpectralDelayResult:
    """Apply region-specific frame delays to STFT bins.

    The recurrence is Y[k,t] = X[k,t] + a[k] * Y[k,t-D[k]]. Each band has
    an integer hop-domain delay, an explicit gain and a feedback coefficient
    capped at 0.85. The feedback tap reads the already-processed spectrum,
    giving decaying repeats without an unbounded recursive graph.
    """
    source, was_vector = audio_channels(audio, "input audio")
    if isinstance(sample_rate, bool) or int(sample_rate) != sample_rate or int(sample_rate) < 1000:
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    rate = int(sample_rate)
    amount = finite_range(wet, "wet", 0.0, 1.0)
    fb_default = finite_range(feedback, "feedback", 0.0, 0.85)
    transient_amount = finite_range(transient_preserve, "transient_preserve", 0.0, 1.0)
    tail_limit = finite_range(max_tail_seconds, "max_tail_seconds", 0.0, 30.0)
    started = time.perf_counter()
    if bypass or amount == 0.0 or len(source) == 0:
        dry = restore_shape(source.copy(), was_vector)
        return SpectralDelayResult(dry, {
            "module": "m24.2.spectral_delay", "algorithm": "bypass", "bypass": True,
            "sample_rate": rate, "input_frames": len(source), "output_frames": len(source),
            "tail_frames": 0, "tail_seconds": 0.0, "latency_frames": 0,
            "processing_seconds": time.perf_counter() - started, "wet": amount,
            **signal_diagnostics(dry),
        })
    bands = _normalise_bands(frequency_bands, rate, fb_default)
    spectra, meta = stft(source, frame_size, hop_size)
    bins = spectra.shape[1]
    freqs = np.fft.rfftfreq(frame_size, 1.0 / rate)
    delay_frames = np.zeros(bins, dtype=np.int64)
    bin_feedback = np.zeros(bins, dtype=np.float64)
    bin_gain = np.zeros(bins, dtype=np.float64)
    for band in bands:
        mask = (freqs >= band["low_hz"]) & (freqs < band["high_hz"])
        if band["high_hz"] >= rate / 2.0:
            mask |= np.isclose(freqs, rate / 2.0)
        frames = int(round(band["delay_ms"] * rate / (1000.0 * hop_size)))
        if band["delay_ms"] > 0.0:
            frames = max(1, frames)
        delay_frames[mask] = frames
        bin_feedback[mask] = band["feedback"]
        bin_gain[mask] = band["gain"]
    positive_delays = delay_frames[delay_frames > 0]
    max_delay = int(np.max(positive_delays)) if positive_delays.size else 0
    active_feedback = bin_feedback[delay_frames > 0]
    max_fb = float(np.max(active_feedback)) if active_feedback.size else 0.0
    if max_delay and max_fb > 0.0:
        repeats = min(128, max(1, int(math.ceil(math.log(1e-4) / math.log(max_fb)))))
        requested_tail = max_delay * repeats * hop_size
    else:
        repeats, requested_tail = 0, 0
    tail_frames = min(requested_tail, int(math.floor(tail_limit * rate / hop_size)) * hop_size)
    tail_stft_frames = int(math.ceil(tail_frames / hop_size))
    truncated = tail_frames < requested_tail
    output_count = spectra.shape[0] + tail_stft_frames
    rendered = np.zeros((output_count, bins, source.shape[1]), dtype=np.complex128)
    rendered[:len(spectra)] = spectra

    # Positive spectral flux estimates abrupt attacks; it only attenuates the
    # repeat contribution on attack frames, never the direct source spectrum.
    magnitudes = np.abs(spectra)
    flux = np.zeros(len(spectra), dtype=np.float64)
    for frame in range(1, len(spectra)):
        increase = np.maximum(magnitudes[frame] - magnitudes[frame - 1], 0.0)
        flux[frame] = float(np.sum(increase) / (np.sum(magnitudes[frame]) + 1e-12))
    transient = np.clip(flux / 0.65, 0.0, 1.0)
    max_delay = int(np.max(delay_frames)) if delay_frames.size else 0
    for frame in range(output_count):
        direct = spectra[frame] if frame < len(spectra) else 0.0
        if max_fb == 0.0 or frame == 0:
            rendered[frame] = direct
            continue
        previous = np.zeros((bins, source.shape[1]), dtype=np.complex128)
        active = delay_frames > 0
        if np.any(active):
            indices = frame - delay_frames[active]
            valid = indices >= 0
            if np.any(valid):
                selected_bins = np.flatnonzero(active)[valid]
                previous[selected_bins] = rendered[indices[valid], selected_bins]
        attenuation = 1.0
        if frame < len(spectra) and transient_amount > 0.0:
            attenuation -= transient_amount * transient[frame]
        rendered[frame] = direct + previous * (bin_feedback * bin_gain * attenuation)[:, None]

    output_length = len(source) + tail_frames
    processed = istft(rendered, meta, output_length)
    dry = np.zeros((output_length, source.shape[1]), dtype=np.float32)
    dry[:len(source)] = source
    if amount < 1.0:
        processed = dry + (processed - dry) * np.float32(amount)
    output = restore_shape(processed, was_vector)
    diagnostics = {
        "module": "m24.2.spectral_delay", "algorithm": "centered_stft_bin_delay_feedback",
        "bypass": False, "sample_rate": rate, "frame_size": frame_size, "hop_size": hop_size,
        "input_frames": len(source), "output_frames": len(output),
        "tail_frames": tail_frames, "tail_seconds": tail_frames / rate,
        "latency_frames": 0, "offline_alignment": "centered_stft_reconstructed_to_source_origin",
        "feedback_ceiling": 0.85, "maximum_feedback": max_fb,
        "maximum_delay_hops": max_delay, "feedback_repeats_estimate": repeats,
        "tail_truncated": truncated, "frequency_bands": bands,
        "transient_preserve": transient_amount, "wet": amount,
        "processing_seconds": time.perf_counter() - started,
        "estimated_working_bytes": int(spectra.nbytes * 2 + rendered.nbytes + processed.nbytes),
        **signal_diagnostics(output),
    }
    return SpectralDelayResult(output, diagnostics)
