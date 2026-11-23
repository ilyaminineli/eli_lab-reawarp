"""Slow harmonic atmosphere and stereo ambience generation."""

from __future__ import annotations

import numpy as np


def render_ambience(
        frame_count: int,
        sample_rate: int,
        rng: np.random.Generator,
        *,
        root_frequency: float = 110.0,
        amount: float = 0.16,
) -> np.ndarray:
    """Render a deterministic harmonic/noise bed with slow stereo motion.

    This is a continuous musical layer, not a random noise generator or a
    convolution reverb. It uses softly detuned partials, filtered noise,
    gradual fades, and a few low-level early reflections.
    """
    if frame_count < 0 or sample_rate <= 0:
        raise ValueError("frame_count must be non-negative and sample_rate positive")
    if root_frequency <= 0:
        raise ValueError("root_frequency must be positive")
    if not 0.0 <= amount <= 1.0:
        raise ValueError("amount must be between zero and one")
    if frame_count == 0:
        return np.zeros((0, 2), dtype=np.float32)

    time = np.arange(frame_count, dtype=np.float64) / float(sample_rate)
    duration = frame_count / float(sample_rate)
    phases = rng.uniform(0.0, 2.0 * np.pi, size=8)
    slow_a = np.sin(2.0 * np.pi * 0.031 * time + phases[0])
    slow_b = np.sin(2.0 * np.pi * 0.047 * time + phases[1])
    drift = 0.0018 * np.sin(2.0 * np.pi * 0.013 * time + phases[2])

    partials = (
        (0.5, 0.16),
        (1.0, 0.34),
        (1.5, 0.19),
        (2.0, 0.13),
        (3.0, 0.075),
        (4.01, 0.035),
    )
    tonal = np.zeros(frame_count, dtype=np.float64)
    for index, (ratio, amplitude) in enumerate(partials):
        frequency = float(root_frequency) * ratio
        if frequency >= sample_rate * 0.44:
            continue
        local_frequency = frequency * (1.0 + drift * (0.65 + index * 0.12))
        phase = 2.0 * np.pi * np.cumsum(local_frequency) / float(sample_rate)
        phase += phases[index + 2]
        tonal += amplitude * np.sin(phase + 0.025 * slow_a * (index + 1))

    # Spectrally soften a seeded noise source; no per-sample Python DSP loop.
    white = rng.standard_normal(frame_count)
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(frame_count, 1.0 / float(sample_rate))
    high_rolloff = 1.0 / np.sqrt(1.0 + (frequencies / 1_350.0) ** 6)
    low_rolloff = frequencies / np.sqrt(frequencies * frequencies + 38.0 * 38.0)
    coloured = np.fft.irfft(spectrum * high_rolloff * low_rolloff, n=frame_count)
    noise_rms = float(np.sqrt(np.mean(coloured * coloured))) if frame_count else 0.0
    if noise_rms > 1e-9:
        coloured = coloured / noise_rms
    else:
        coloured = np.zeros_like(coloured)
    bed = (tonal + coloured * 0.035) * (0.92 + 0.08 * slow_b)

    fade_seconds = min(1.25, max(0.08, duration * 0.22))
    fade_in = np.sin(
        0.5 * np.pi * np.clip(time / fade_seconds, 0.0, 1.0)
    ) ** 2
    fade_out = np.sin(
        0.5 * np.pi * np.clip((duration - time) / fade_seconds, 0.0, 1.0)
    ) ** 2
    bed *= np.minimum(fade_in, fade_out)

    left = bed * (0.78 + 0.07 * slow_a)
    right = bed * (0.78 - 0.07 * slow_a)
    early_left = int(round(sample_rate * 0.173))
    early_right = int(round(sample_rate * 0.257))
    late_left = int(round(sample_rate * 0.389))
    late_right = int(round(sample_rate * 0.463))
    if early_left < frame_count:
        left[early_left:] += bed[:-early_left] * 0.105
    if early_right < frame_count:
        right[early_right:] += bed[:-early_right] * 0.095
    if late_left < frame_count:
        left[late_left:] += bed[:-late_left] * 0.045
    if late_right < frame_count:
        right[late_right:] += bed[:-late_right] * 0.04

    stereo = np.column_stack((left, right))
    return (stereo * float(amount) * 0.62).astype(np.float32)
