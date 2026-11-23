"""Procedural one-shot synthesis and simple FM voices."""

from __future__ import annotations

import numpy as np

from reawarp.synthesis.envelopes import exponential_decay


def render_kick(
    sample_rate: int,
    rng: np.random.Generator,
    velocity: float = 1.0,
    duration: float = 0.48,
    start_frequency: float = 155.0,
    end_frequency: float = 43.0,
    pitch_decay: float = 0.035,
    amp_decay: float = 0.23,
    distortion: float = 1.7,
) -> np.ndarray:
    length = max(32, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    tau = max(pitch_decay, 1e-4)
    phase = 2.0 * np.pi * (
        end_frequency * time
        + (start_frequency - end_frequency) * tau * (1.0 - np.exp(-time / tau))
    )
    envelope = exponential_decay(length, sample_rate, amp_decay, 0.0015).astype(np.float64)
    body = np.sin(phase) * envelope
    sub = 0.24 * np.sin(2.0 * np.pi * (end_frequency * 0.52) * time) * np.exp(-time / 0.31)
    click_noise = rng.standard_normal(length)
    click_env = np.exp(-time / 0.0038)
    click = click_noise * click_env * 0.10
    signal = body + sub + click
    signal = np.tanh(signal * distortion) / max(1.0, distortion * 0.78)
    return (signal * float(np.clip(velocity, 0.0, 1.0))).astype(np.float32)


def render_snare(
    sample_rate: int,
    rng: np.random.Generator,
    velocity: float = 1.0,
    duration: float = 0.30,
) -> np.ndarray:
    length = max(32, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    noise = rng.standard_normal(length)
    high = np.empty_like(noise)
    high[0] = noise[0]
    high[1:] = noise[1:] - 0.94 * noise[:-1]
    noise_env = np.exp(-time / 0.105) * (1.0 - np.exp(-time / 0.001))
    body_env = np.exp(-time / 0.065) * (1.0 - np.exp(-time / 0.002))
    body = np.sin(2.0 * np.pi * (178.0 - 38.0 * np.exp(-time / 0.012)) * time)
    signal = 0.72 * high * noise_env + 0.31 * body * body_env
    signal = np.tanh(signal * 1.35) / 1.35
    return (signal * float(np.clip(velocity, 0.0, 1.0)) * 0.72).astype(np.float32)


def render_hat(
    sample_rate: int,
    rng: np.random.Generator,
    velocity: float = 0.5,
    duration: float = 0.115,
) -> np.ndarray:
    length = max(24, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    noise = rng.standard_normal(length)
    high = np.empty_like(noise)
    high[0] = noise[0]
    high[1:] = noise[1:] - 0.975 * noise[:-1]
    metallic = np.zeros(length, dtype=np.float64)
    for frequency, amplitude in ((463, 0.25), (701, 0.19), (1139, 0.16), (1777, 0.12), (2633, 0.08)):
        metallic += amplitude * np.sin(2.0 * np.pi * frequency * time + rng.uniform(0, 2 * np.pi))
    envelope = np.exp(-time / 0.032) * (1.0 - np.exp(-time / 0.0007))
    signal = (0.58 * high + 0.42 * metallic) * envelope
    signal = np.tanh(signal * 1.1) / 1.1
    return (signal * float(np.clip(velocity, 0.0, 1.0)) * 0.35).astype(np.float32)


def render_fm_note(
    frequency: float,
    sample_rate: int,
    rng: np.random.Generator,
    duration: float = 0.34,
    velocity: float = 0.65,
    modulation_ratio: float | None = None,
    modulation_index: float = 2.4,
) -> np.ndarray:
    length = max(48, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    ratio = modulation_ratio if modulation_ratio is not None else float(
        rng.choice([1.4142, 1.5, 1.618, 2.0, 2.718])
    )
    mod_frequency = max(1.0, frequency * ratio)
    index_curve = modulation_index * np.exp(-time / max(duration * 0.45, 0.02))
    phase = 2.0 * np.pi * frequency * time + index_curve * np.sin(2.0 * np.pi * mod_frequency * time)
    envelope = exponential_decay(length, sample_rate, max(duration * 0.48, 0.055), 0.004)
    carrier = np.sin(phase)
    upper_partial = 0.22 * np.sin(2.0 * phase + 0.17)
    low_component = 0.12 * np.sin(2.0 * np.pi * (frequency * 0.503) * time)
    signal = (carrier + upper_partial + low_component) * envelope
    return (signal * float(np.clip(velocity, 0.0, 1.0)) * 0.43).astype(np.float32)


def render_noise_texture(
    frame_count: int,
    sample_rate: int,
    rng: np.random.Generator,
    amount: float = 0.11,
) -> np.ndarray:
    """Generate slowly evolving coloured noise with subtle resonant components."""
    white = rng.standard_normal(frame_count).astype(np.float64)
    brown = np.empty_like(white)
    state = 0.0
    for index, value in enumerate(white):
        state = 0.985 * state + 0.015 * value
        brown[index] = state
    brown /= max(1e-9, float(np.max(np.abs(brown))))
    time = np.arange(frame_count, dtype=np.float64) / sample_rate
    slow_mod = 0.55 + 0.45 * np.sin(
        2.0 * np.pi * 0.17 * time + 0.8 * np.sin(2.0 * np.pi * 0.037 * time)
    )
    airy = 0.18 * white
    signal = (0.72 * brown + airy) * slow_mod * float(amount)
    return signal.astype(np.float32)
