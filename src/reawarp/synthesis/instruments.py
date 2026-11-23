"""Procedural percussion and FM synthesis instruments."""

from __future__ import annotations

import numpy as np

from reawarp.synthesis.envelopes import exponential_decay
from reawarp.synthesis.profiles import (
    HAT_PROFILES,
    KICK_PROFILES,
    SNARE_PROFILES,
    select_profile_name,
)


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
        profile: str = "909_punch",
) -> np.ndarray:
    """Render a kick using one of thirteen independently tunable profiles.

    Explicit legacy parameters remain available and override the selected
    profile, preserving the original renderer's call signature.
    """
    if profile == "auto":
        profile = select_profile_name(profile, KICK_PROFILES, rng)
    if profile not in KICK_PROFILES:
        raise ValueError(f"unknown kick profile: {profile}")
    shape = KICK_PROFILES[profile]
    start = shape.start_frequency if start_frequency == 155.0 else start_frequency
    end = shape.end_frequency if end_frequency == 43.0 else end_frequency
    pitch_tau = shape.pitch_decay if pitch_decay == 0.035 else pitch_decay
    amp_tau = shape.amp_decay if amp_decay == 0.23 else amp_decay
    drive = shape.distortion if distortion == 1.7 else distortion
    length = max(32, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    tau = max(float(pitch_tau), 1e-4)
    phase = 2.0 * np.pi * (
            end * time + (start - end) * tau * (1.0 - np.exp(-time / tau))
    )
    envelope = exponential_decay(length, sample_rate, amp_tau, 0.0015).astype(np.float64)
    body = np.sin(phase) * envelope
    sub = shape.sub_gain * np.sin(2.0 * np.pi * (end * 0.52) * time) * np.exp(
        -time / shape.sub_decay
    )
    click_noise = rng.standard_normal(length)
    click = click_noise * np.exp(-time / shape.click_decay) * shape.click_gain
    signal = np.tanh((body + sub + click) * drive) / max(1.0, drive * 0.78)
    return (signal * float(np.clip(velocity, 0.0, 1.0))).astype(np.float32)


def render_snare(
        sample_rate: int,
        rng: np.random.Generator,
        velocity: float = 1.0,
        duration: float = 0.30,
        profile: str = "909_crack",
) -> np.ndarray:
    """Render a snare from one of six noise/body/envelope profiles."""
    if profile == "auto":
        profile = select_profile_name(profile, SNARE_PROFILES, rng)
    if profile not in SNARE_PROFILES:
        raise ValueError(f"unknown snare profile: {profile}")
    shape = SNARE_PROFILES[profile]
    length = max(32, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    noise = rng.standard_normal(length)
    high = np.empty_like(noise)
    high[0] = noise[0]
    high[1:] = noise[1:] - shape.noise_highpass * noise[:-1]
    noise_env = np.exp(-time / shape.noise_decay) * (1.0 - np.exp(-time / 0.001))
    body_env = np.exp(-time / shape.body_decay) * (1.0 - np.exp(-time / 0.002))
    body_frequency = shape.body_frequency - shape.body_sweep * np.exp(-time / 0.012)
    body = np.sin(2.0 * np.pi * body_frequency * time)
    signal = shape.noise_gain * high * noise_env + shape.body_gain * body * body_env
    signal = np.tanh(signal * shape.drive) / shape.drive
    return (signal * float(np.clip(velocity, 0.0, 1.0)) * 0.72).astype(np.float32)


def render_hat(
        sample_rate: int,
        rng: np.random.Generator,
        velocity: float = 0.5,
        duration: float = 0.115,
        profile: str = "closed",
) -> np.ndarray:
    """Render a hi-hat from one of six noise/metallic spectral profiles."""
    if profile == "auto":
        profile = select_profile_name(profile, HAT_PROFILES, rng)
    if profile not in HAT_PROFILES:
        raise ValueError(f"unknown hi-hat profile: {profile}")
    shape = HAT_PROFILES[profile]
    length = max(24, int(round(sample_rate * duration)))
    time = np.arange(length, dtype=np.float64) / sample_rate
    noise = rng.standard_normal(length)
    high = np.empty_like(noise)
    high[0] = noise[0]
    high[1:] = noise[1:] - shape.highpass * noise[:-1]
    metallic = np.zeros(length, dtype=np.float64)
    for frequency, amplitude in shape.partials:
        metallic += amplitude * np.sin(
            2.0 * np.pi * frequency * time + rng.uniform(0.0, 2.0 * np.pi)
        )
    envelope = np.exp(-time / shape.decay) * (1.0 - np.exp(-time / 0.0007))
    signal = (shape.noise_gain * high + shape.metallic_gain * metallic) * envelope
    signal = np.tanh(signal * shape.drive) / shape.drive
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
    phase = 2.0 * np.pi * frequency * time + index_curve * np.sin(
        2.0 * np.pi * mod_frequency * time
    )
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
