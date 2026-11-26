"""Distinct cross-synthesis and frequency-transformation reference algorithms."""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from reawarp.dsp._stft import (
    audio_channels,
    finite_range,
    istft,
    restore_shape,
    signal_diagnostics,
    stft,
)


class CrossSynthesisResult:
    __slots__ = ("audio", "diagnostics")

    def __init__(self, audio: np.ndarray, diagnostics: dict[str, Any]):
        self.audio = audio
        self.diagnostics = diagnostics


def _paired_audio(
    carrier: np.ndarray, modulator: np.ndarray
) -> tuple[np.ndarray, np.ndarray, bool]:
    c, c_vector = audio_channels(carrier, "carrier")
    m, _m_vector = audio_channels(modulator, "modulator")
    if len(c) != len(m):
        raise ValueError(
            "carrier and modulator must have the same frame count; align them explicitly"
        )
    if c.shape[1] == m.shape[1]:
        return c, m, c_vector
    if c.shape[1] == 2 and m.shape[1] == 1:
        return c, np.repeat(m, 2, axis=1), c_vector
    if c.shape[1] == 1 and m.shape[1] == 2:
        return np.repeat(c, 2, axis=1), m, False
    raise ValueError("carrier and modulator channel layouts are incompatible")


def ring_modulate(
    carrier: np.ndarray,
    modulator: np.ndarray,
    sample_rate: int,
    *,
    wet: float = 1.0,
    bypass: bool = False,
) -> CrossSynthesisResult:
    """Multiply a carrier by a modulator: genuine sum/difference sideband generation."""
    c, m, was_vector = _paired_audio(carrier, modulator)
    if (
        isinstance(sample_rate, bool)
        or int(sample_rate) != sample_rate
        or int(sample_rate) < 1000
    ):
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    amount = finite_range(wet, "wet", 0.0, 1.0)
    started = time.perf_counter()
    if bypass or amount == 0.0:
        output = restore_shape(c.copy(), was_vector)
        return CrossSynthesisResult(
            output,
            {
                "module": "m24.3.ring_modulation",
                "algorithm": "bypass",
                "bypass": True,
                "sample_rate": int(sample_rate),
                "input_frames": len(c),
                "output_frames": len(c),
                "latency_frames": 0,
                "processing_seconds": time.perf_counter() - started,
                **signal_diagnostics(output),
            },
        )
    product = c.astype(np.float64) * m.astype(np.float64)
    output = c.astype(np.float64) * (1.0 - amount) + product * amount
    output = restore_shape(output, was_vector)
    return CrossSynthesisResult(
        output,
        {
            "module": "m24.3.ring_modulation",
            "algorithm": "time_domain_sample_product",
            "bypass": False,
            "sample_rate": int(sample_rate),
            "input_frames": len(c),
            "output_frames": len(output),
            "latency_frames": 0,
            "processing_seconds": time.perf_counter() - started,
            "formula": "y[n] = (1-wet)*carrier[n] + wet*carrier[n]*modulator[n]",
            "wet": amount,
            **signal_diagnostics(output),
        },
    )


def frequency_shift(
    audio: np.ndarray,
    sample_rate: int,
    shift_hz: float,
    *,
    wet: float = 1.0,
    edge_padding_ms: float = 20.0,
    bypass: bool = False,
) -> CrossSynthesisResult:
    """Translate every analytic-signal partial by a fixed Hz offset (not pitch shift)."""
    source, was_vector = audio_channels(audio, "input audio")
    if (
        isinstance(sample_rate, bool)
        or int(sample_rate) != sample_rate
        or int(sample_rate) < 1000
    ):
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    rate = int(sample_rate)
    shift = finite_range(shift_hz, "shift_hz", -0.45 * rate, 0.45 * rate)
    amount = finite_range(wet, "wet", 0.0, 1.0)
    pad_ms = finite_range(edge_padding_ms, "edge_padding_ms", 0.0, 250.0)
    started = time.perf_counter()
    if bypass or amount == 0.0 or len(source) == 0 or shift == 0.0:
        output = restore_shape(source.copy(), was_vector)
        return CrossSynthesisResult(
            output,
            {
                "module": "m24.3.frequency_shift",
                "algorithm": "bypass",
                "bypass": True,
                "sample_rate": rate,
                "shift_hz": shift,
                "input_frames": len(source),
                "output_frames": len(source),
                "latency_frames": 0,
                "processing_seconds": time.perf_counter() - started,
                **signal_diagnostics(output),
            },
        )
    pad = int(round(rate * pad_ms / 1000.0))
    if len(source) > 1 and pad:
        padded = np.pad(source.astype(np.float64), ((pad, pad), (0, 0)), mode="reflect")
    else:
        padded = np.pad(source.astype(np.float64), ((pad, pad), (0, 0)))
    count = len(padded)
    spectrum = np.fft.fft(padded, axis=0)
    analytic_mask = np.zeros(count, dtype=np.float64)
    analytic_mask[0] = 1.0
    if count % 2 == 0:
        analytic_mask[1 : count // 2] = 2.0
        analytic_mask[count // 2] = 1.0
    else:
        analytic_mask[1 : (count + 1) // 2] = 2.0
    analytic = np.fft.ifft(spectrum * analytic_mask[:, None], axis=0)
    time_axis = np.arange(count, dtype=np.float64) / rate
    translated = np.real(analytic * np.exp(1j * math.tau * shift * time_axis)[:, None])
    translated = translated[pad : pad + len(source)]
    output = source.astype(np.float64) * (1.0 - amount) + translated * amount
    output = restore_shape(output, was_vector)
    return CrossSynthesisResult(
        output,
        {
            "module": "m24.3.frequency_shift",
            "algorithm": "fft_analytic_signal_translation",
            "bypass": False,
            "sample_rate": rate,
            "shift_hz": shift,
            "input_frames": len(source),
            "output_frames": len(output),
            "latency_frames": 0,
            "edge_padding_frames": pad,
            "frequency_shift_is_not_pitch_shift": True,
            "wet": amount,
            "processing_seconds": time.perf_counter() - started,
            **signal_diagnostics(output),
        },
    )


def _smooth_frequency(magnitude: np.ndarray, width: int) -> np.ndarray:
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width < 3
        or width > 255
    ):
        raise ValueError("envelope_bins must be an odd integer between 3 and 255")
    if width % 2 == 0:
        raise ValueError("envelope_bins must be odd")
    kernel = np.ones(width, dtype=np.float64) / width
    pad = width // 2
    result = np.empty_like(magnitude, dtype=np.float64)
    for frame in range(magnitude.shape[0]):
        for channel in range(magnitude.shape[2]):
            values = np.pad(magnitude[frame, :, channel], (pad, pad), mode="edge")
            result[frame, :, channel] = np.convolve(values, kernel, mode="valid")
    return result


def spectral_envelope_transfer(
    carrier: np.ndarray,
    modulator: np.ndarray,
    sample_rate: int,
    *,
    frame_size: int = 1024,
    hop_size: int = 256,
    envelope_bins: int = 31,
    amount: float = 1.0,
    max_ratio: float = 8.0,
    wet: float = 1.0,
    bypass: bool = False,
) -> CrossSynthesisResult:
    """Apply modulator's smoothed spectral envelope to carrier detail and phase."""
    c, m, was_vector = _paired_audio(carrier, modulator)
    if (
        isinstance(sample_rate, bool)
        or int(sample_rate) != sample_rate
        or int(sample_rate) < 1000
    ):
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    rate = int(sample_rate)
    amt = finite_range(amount, "amount", 0.0, 1.0)
    ratio_limit = finite_range(max_ratio, "max_ratio", 1.0, 32.0)
    wet_amount = finite_range(wet, "wet", 0.0, 1.0)
    started = time.perf_counter()
    if bypass or wet_amount == 0.0 or amt == 0.0:
        output = restore_shape(c.copy(), was_vector)
        return CrossSynthesisResult(
            output,
            {
                "module": "m24.3.spectral_envelope_transfer",
                "algorithm": "bypass",
                "bypass": True,
                "sample_rate": rate,
                "input_frames": len(c),
                "output_frames": len(c),
                "latency_frames": 0,
                "processing_seconds": time.perf_counter() - started,
                **signal_diagnostics(output),
            },
        )
    carrier_spec, metadata = stft(c, frame_size, hop_size)
    modulator_spec, _ = stft(m, frame_size, hop_size)
    carrier_mag = np.abs(carrier_spec)
    modulator_mag = np.abs(modulator_spec)
    carrier_env = _smooth_frequency(carrier_mag, envelope_bins)
    modulator_env = _smooth_frequency(modulator_mag, envelope_bins)
    ratio = (modulator_env + 1e-8) / (carrier_env + 1e-8)
    ratio = np.clip(ratio, 1.0 / ratio_limit, ratio_limit)
    scale = np.power(ratio, amt)
    transformed = carrier_spec * scale
    rendered = istft(transformed, metadata, len(c))
    output = c * np.float32(1.0 - wet_amount) + rendered * np.float32(wet_amount)
    output = restore_shape(output, was_vector)
    return CrossSynthesisResult(
        output,
        {
            "module": "m24.3.spectral_envelope_transfer",
            "algorithm": "stft_smoothed_magnitude_ratio",
            "bypass": False,
            "sample_rate": rate,
            "frame_size": frame_size,
            "hop_size": hop_size,
            "envelope_bins": envelope_bins,
            "carrier_phase_retained": True,
            "modulator_contributes": "smoothed_spectral_envelope",
            "ratio_limit": ratio_limit,
            "amount": amt,
            "wet": wet_amount,
            "input_frames": len(c),
            "output_frames": len(output),
            "latency_frames": 0,
            "processing_seconds": time.perf_counter() - started,
            "estimated_working_bytes": int(
                carrier_spec.nbytes * 2 + modulator_spec.nbytes + transformed.nbytes
            ),
            **signal_diagnostics(output),
        },
    )


def _triangular_bands(sample_rate: int, frame_size: int, bands: int) -> np.ndarray:
    if isinstance(bands, bool) or not isinstance(bands, int) or bands < 4 or bands > 64:
        raise ValueError("bands must be an integer between 4 and 64")
    frequencies = np.fft.rfftfreq(frame_size, 1.0 / sample_rate)
    minimum = max(20.0, sample_rate / frame_size)
    centres = np.geomspace(minimum, sample_rate / 2.0, bands)
    log_frequency = np.log(np.maximum(frequencies, minimum))
    log_centres = np.log(centres)
    weights = np.zeros((bands, len(frequencies)), dtype=np.float64)
    for index, centre in enumerate(log_centres):
        left = log_centres[index] - (
            log_centres[index] - log_centres[index - 1]
            if index
            else (log_centres[1] - log_centres[0])
        )
        right = log_centres[index] + (
            log_centres[index + 1] - log_centres[index]
            if index < bands - 1
            else (log_centres[-1] - log_centres[-2])
        )
        weights[index] = np.maximum(
            0.0,
            1.0
            - np.where(
                log_frequency < centre,
                (centre - log_frequency) / max(centre - left, 1e-12),
                (log_frequency - centre) / max(right - centre, 1e-12),
            ),
        )
    weights[0, frequencies <= minimum] = 1.0
    normalizer = np.sum(weights, axis=0)
    weights[:, normalizer <= 1e-12] = 0.0
    weights[0, normalizer <= 1e-12] = 1.0
    normalizer = np.sum(weights, axis=0)
    return weights / normalizer[None, :]


def _envelope_follow(
    values: np.ndarray,
    sample_rate: int,
    hop_size: int,
    attack_ms: float,
    release_ms: float,
) -> np.ndarray:
    attack = (
        math.exp(-hop_size / max(sample_rate * attack_ms / 1000.0, 1.0))
        if attack_ms > 0.0
        else 0.0
    )
    release = (
        math.exp(-hop_size / max(sample_rate * release_ms / 1000.0, 1.0))
        if release_ms > 0.0
        else 0.0
    )
    result = np.zeros_like(values, dtype=np.float64)
    state = np.zeros(values.shape[1:], dtype=np.float64)
    for frame in range(len(values)):
        coefficient = np.where(values[frame] > state, attack, release)
        state = coefficient * state + (1.0 - coefficient) * values[frame]
        result[frame] = state
    return result


def vocoder(
    carrier: np.ndarray,
    modulator: np.ndarray,
    sample_rate: int,
    *,
    bands: int = 24,
    frame_size: int = 1024,
    hop_size: int = 256,
    attack_ms: float = 5.0,
    release_ms: float = 70.0,
    amount: float = 1.0,
    max_band_gain: float = 12.0,
    wet: float = 1.0,
    bypass: bool = False,
) -> CrossSynthesisResult:
    """Vocoder: modulator band envelopes articulate carrier spectral detail."""
    c, m, was_vector = _paired_audio(carrier, modulator)
    if (
        isinstance(sample_rate, bool)
        or int(sample_rate) != sample_rate
        or int(sample_rate) < 1000
    ):
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    rate = int(sample_rate)
    attack = finite_range(attack_ms, "attack_ms", 0.0, 250.0)
    release = finite_range(release_ms, "release_ms", 0.0, 1000.0)
    amt = finite_range(amount, "amount", 0.0, 1.0)
    gain_limit = finite_range(max_band_gain, "max_band_gain", 1.0, 32.0)
    wet_amount = finite_range(wet, "wet", 0.0, 1.0)
    started = time.perf_counter()
    if bypass or wet_amount == 0.0 or amt == 0.0:
        output = restore_shape(c.copy(), was_vector)
        return CrossSynthesisResult(
            output,
            {
                "module": "m24.3.vocoder",
                "algorithm": "bypass",
                "bypass": True,
                "sample_rate": rate,
                "input_frames": len(c),
                "output_frames": len(c),
                "latency_frames": 0,
                "processing_seconds": time.perf_counter() - started,
                **signal_diagnostics(output),
            },
        )
    carrier_spec, metadata = stft(c, frame_size, hop_size)
    modulator_spec, _ = stft(m, frame_size, hop_size)
    weights = _triangular_bands(rate, frame_size, bands)
    carrier_mag = np.abs(carrier_spec)
    modulator_mag = np.abs(modulator_spec)
    # Weighted RMS band levels retain the modulator's evolving articulation.
    denom = np.sum(weights, axis=1)[None, :, None]
    carrier_level = np.sqrt(
        np.einsum("bk,fkc->fbc", weights, carrier_mag**2) / np.maximum(denom, 1e-12)
    )
    modulator_level = np.sqrt(
        np.einsum("bk,fkc->fbc", weights, modulator_mag**2) / np.maximum(denom, 1e-12)
    )
    followed = _envelope_follow(modulator_level, rate, hop_size, attack, release)
    ratio = followed / np.maximum(carrier_level, 1e-8)
    ratio = np.clip(ratio, 0.0, gain_limit)
    ratio = np.power(ratio, amt)
    bin_scale = np.einsum("bk,fbc->fkc", weights, ratio)
    transformed = carrier_spec * bin_scale
    rendered = istft(transformed, metadata, len(c))
    output = c * np.float32(1.0 - wet_amount) + rendered * np.float32(wet_amount)
    output = restore_shape(output, was_vector)
    return CrossSynthesisResult(
        output,
        {
            "module": "m24.3.vocoder",
            "algorithm": "log_triangular_band_envelope_vocoder",
            "bypass": False,
            "sample_rate": rate,
            "bands": bands,
            "frame_size": frame_size,
            "hop_size": hop_size,
            "attack_ms": attack,
            "release_ms": release,
            "carrier_phase_retained": True,
            "modulator_contributes": "smoothed_band_amplitude_envelopes",
            "max_band_gain": gain_limit,
            "amount": amt,
            "wet": wet_amount,
            "input_frames": len(c),
            "output_frames": len(output),
            "latency_frames": 0,
            "processing_seconds": time.perf_counter() - started,
            "estimated_working_bytes": int(
                carrier_spec.nbytes * 2 + modulator_spec.nbytes + transformed.nbytes
            ),
            **signal_diagnostics(output),
        },
    )
