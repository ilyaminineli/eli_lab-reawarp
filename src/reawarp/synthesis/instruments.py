"""Procedural percussion and FM synthesis instruments."""

from __future__ import annotations

import numpy as np

from reawarp.synthesis.envelopes import exponential_decay
from reawarp.synthesis.profiles import (
    EXTENDED_MELODY_PROFILES,
    HAT_PROFILES,
    KICK_PROFILES,
    MELODY_PROFILES,
    PERCUSSION_VOICES,
    SNARE_PROFILES,
    SUBTRACTIVE_VOICES,
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


def _spectral_lowpass(
        signal: np.ndarray,
        sample_rate: int,
        cutoff_hz: float,
) -> np.ndarray:
    """Apply a smooth offline low-pass without requiring a native DSP package."""
    spectrum = np.fft.rfft(signal)
    frequencies = np.fft.rfftfreq(len(signal), 1.0 / float(sample_rate))
    ratio = frequencies / max(100.0, float(cutoff_hz))
    response = 1.0 / np.sqrt(1.0 + ratio ** 8)
    return np.fft.irfft(spectrum * response, n=len(signal))


def _envelope_time(
        override: float | None,
        fallback: float,
        minimum: float,
        name: str,
) -> float:
    """Resolve a finite, positive envelope time while retaining profile defaults."""
    value = float(fallback if override is None else override)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return max(float(minimum), value)


def _carrier_phase(
        frequency: float,
        time: np.ndarray,
        sample_rate: int,
        vibrato_depth_semitones: float = 0.0,
        vibrato_rate_hz: float = 0.0,
) -> np.ndarray:
    """Integrate a bounded sinusoidal pitch trajectory into continuous oscillator phase."""
    depth = float(vibrato_depth_semitones)
    rate = float(vibrato_rate_hz)
    if not np.isfinite(depth) or not 0.0 <= depth <= 2.0:
        raise ValueError("vibrato_depth_semitones must be finite and between 0 and 2")
    if not np.isfinite(rate) or not 0.0 <= rate <= 40.0:
        raise ValueError("vibrato_rate_hz must be finite and between 0 and 40")
    if depth <= 0.0 or rate <= 0.0 or len(time) < 2:
        return 2.0 * np.pi * float(frequency) * time
    bend = depth * np.sin(2.0 * np.pi * rate * time)
    ratios = np.power(2.0, bend / 12.0)
    cycles = np.empty(len(time), dtype=np.float64)
    cycles[0] = 0.0
    cycles[1:] = np.cumsum(0.5 * (ratios[:-1] + ratios[1:])) / float(sample_rate)
    return 2.0 * np.pi * float(frequency) * cycles


def render_fm_note(
        frequency: float,
        sample_rate: int,
        rng: np.random.Generator,
        duration: float = 0.34,
        velocity: float = 0.65,
        modulation_ratio: float | None = None,
        modulation_index: float | None = None,
        profile: str = "soft_keys",
        brightness: float = 0.5,
        instability: float = 0.0,
        attack_seconds: float | None = None,
        decay_seconds: float | None = None,
        release_seconds: float | None = None,
        vibrato_depth_semitones: float = 0.0,
        vibrato_rate_hz: float = 0.0,
) -> np.ndarray:
    """Render a softly evolving additive/FM note with a defined release tail.

    The profile controls its partial spectrum, envelope, detuning, FM depth,
    filtering, and saturation. FM remains a colour source rather than the
    entire timbral identity, avoiding the brittle two-oscillator sound.
    """
    if sample_rate <= 0 or duration <= 0 or frequency <= 0:
        raise ValueError("frequency, sample_rate, and duration must be positive")
    if not 0.0 <= brightness <= 1.0:
        raise ValueError("brightness must be between zero and one")
    if not 0.0 <= instability <= 1.0:
        raise ValueError("instability must be between zero and one")
    if profile not in MELODY_PROFILES:
        raise ValueError(
            f"unknown melody profile: {profile}; choose from {', '.join(MELODY_PROFILES)}"
        )
    shape = MELODY_PROFILES[profile]
    attack = _envelope_time(attack_seconds, shape.attack, 0.001, "attack_seconds")
    decay = _envelope_time(decay_seconds, shape.decay, 0.01, "decay_seconds")
    release = _envelope_time(release_seconds, shape.release, 0.02, "release_seconds")
    length = max(48, int(round(sample_rate * (duration + release))))
    time = np.arange(length, dtype=np.float64) / float(sample_rate)
    carrier_phase = _carrier_phase(
        frequency, time, sample_rate, vibrato_depth_semitones, vibrato_rate_hz
    )

    ratio = float(modulation_ratio if modulation_ratio is not None else shape.fm_ratio)
    index = float(modulation_index if modulation_index is not None else shape.fm_index)
    mod_phase = float(rng.uniform(0.0, 2.0 * np.pi))
    modulator = np.sin(carrier_phase * ratio + mod_phase)
    bounded_drift = 1.0 + 0.16 * float(instability) * np.sin(
        2.0 * np.pi * 0.19 * time + mod_phase * 0.37
    )
    index_curve = index * bounded_drift * np.exp(-time / max(0.04, duration * 0.55))

    signal = np.zeros(length, dtype=np.float64)
    for partial_ratio, amplitude in shape.partials:
        partial_frequency = float(frequency) * float(partial_ratio)
        if partial_frequency >= sample_rate * 0.46:
            continue
        phase_offset = float(rng.uniform(0.0, 2.0 * np.pi))
        partial_index = index_curve * min(1.0, float(partial_ratio) ** 0.25)
        phase = (
                carrier_phase * float(partial_ratio)
                + partial_index * modulator
                + phase_offset
        )
        signal += float(amplitude) * np.sin(phase)

    # A quiet detuned fundamental thickens the voice without chorus smear.
    detune_cents = float(shape.detune_cents) + 8.0 * float(instability)
    detune_ratio = 2.0 ** (detune_cents / 1_200.0)
    signal += 0.14 * np.sin(
        carrier_phase * detune_ratio
        + float(rng.uniform(0.0, 2.0 * np.pi))
    )
    transient = rng.standard_normal(length) * np.exp(-time / 0.006) * 0.012
    signal += transient

    sustain = float(np.clip(shape.sustain, 0.0, 1.0))
    attack_curve = 1.0 - np.exp(-time / attack)
    decay_curve = sustain + (1.0 - sustain) * np.exp(-time / decay)
    envelope = attack_curve * decay_curve
    release_mask = time >= float(duration)
    envelope[release_mask] *= np.exp(
        -(time[release_mask] - float(duration)) / release
    )

    signal *= envelope
    brightness_scale = 0.55 + 0.90 * float(brightness)
    cutoff = min(sample_rate * 0.45, shape.lowpass_hz * brightness_scale)
    signal = _spectral_lowpass(signal, sample_rate, cutoff)
    drive = max(1.0, float(shape.drive))
    signal = np.tanh(signal * drive) / np.tanh(drive)
    signal *= float(np.clip(velocity, 0.0, 1.0)) * 0.42
    return signal.astype(np.float32)


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



def render_extended_note(
        frequency: float,
        sample_rate: int,
        rng: np.random.Generator,
        duration: float = 0.34,
        velocity: float = 0.65,
        palette: str = "hybrid",
        brightness: float = 0.5,
        instability: float = 0.0,
        attack_seconds: float | None = None,
        decay_seconds: float | None = None,
        release_seconds: float | None = None,
        vibrato_depth_semitones: float = 0.0,
        vibrato_rate_hz: float = 0.0,
        wavetable_position: float | None = None,
        partial_balance: float | None = None,
        grain_size_ms: float | None = None,
        grain_position: float | None = None,
        grain_density_hz: float | None = None,
) -> np.ndarray:
    """Render extended tonal families with NumPy-only reference algorithms.

    Families include additive/inharmonic partial banks, a wavetable-like
    oscillator scan, pulsar windows, and modal resonators. Granular and physical
    palettes use a restrained deterministic microsound/modal approximation;
    optional specialist backends can be added without changing event data.
    """
    if frequency <= 0 or sample_rate <= 0 or duration <= 0:
        raise ValueError("frequency, sample_rate, and duration must be positive")
    if not 0 <= brightness <= 1 or not 0 <= instability <= 1:
        raise ValueError("brightness and instability must be between zero and one")
    if palette not in {
        "hybrid", "fm", "additive", "modal", "inharmonic",
        "wavetable", "granular", "physical",
    }:
        raise ValueError(f"unknown synthesis palette: {palette}")
    for name, value, low, high in (
        ("wavetable_position", wavetable_position, 0.0, 1.0),
        ("partial_balance", partial_balance, 0.0, 1.0),
        ("grain_position", grain_position, 0.0, 1.0),
        ("grain_density_hz", grain_density_hz, 0.0, 200.0),
        ("grain_size_ms", grain_size_ms, 1.0, 500.0),
    ):
        if value is not None and (
            not np.isfinite(float(value)) or not low <= float(value) <= high
        ):
            raise ValueError(f"{name} must be finite and between {low:g} and {high:g}")

    if palette in {"hybrid", "fm"}:
        profile = "soft_keys" if palette == "hybrid" else "metallic_fm"
        return render_fm_note(
            frequency, sample_rate, rng, duration, velocity,
            profile=profile, brightness=brightness, instability=instability,
            attack_seconds=attack_seconds, decay_seconds=decay_seconds,
            release_seconds=release_seconds,
            vibrato_depth_semitones=vibrato_depth_semitones,
            vibrato_rate_hz=vibrato_rate_hz,
        )

    attack_time = _envelope_time(attack_seconds, 0.006, 0.001, "attack_seconds")
    release_time = _envelope_time(release_seconds, 0.28, 0.02, "release_seconds")
    length = max(64, int(round(sample_rate * (duration + release_time))))
    t = np.arange(length, dtype=np.float64) / float(sample_rate)
    note_end = float(duration)
    release = np.exp(-np.maximum(0.0, t - note_end) / release_time)
    attack = 1.0 - np.exp(-t / attack_time)
    body_env = np.where(t < note_end, attack, attack * release)
    if decay_seconds is not None:
        decay_time = _envelope_time(decay_seconds, 0.2, 0.01, "decay_seconds")
        decay_curve = 0.72 + 0.28 * np.exp(-t / decay_time)
        held_decay = 0.72 + 0.28 * np.exp(-note_end / decay_time)
        body_env *= np.where(t < note_end, decay_curve, held_decay)
    carrier_phase = _carrier_phase(
        frequency, t, sample_rate, vibrato_depth_semitones, vibrato_rate_hz
    )
    rng_phase = rng.uniform(0.0, 2.0 * np.pi, 12)
    signal = np.zeros(length, dtype=np.float64)

    def partial_level(ratio: float) -> float:
        if partial_balance is None:
            return 1.0
        balance = float(partial_balance)
        # Neutral at 0.5; endpoints tilt energy between the fundamental and overtones.
        return (
            1.0 + 0.8 * (0.5 - balance)
            if float(ratio) <= 1.000001
            else 1.0 + 1.2 * (balance - 0.5)
        )

    # Data-driven inharmonic/modal-style voices provide reproducible partial recipes.
    # For these palettes, the recipe is used to distribute partial ratios/decays.
    if palette in {"additive", "inharmonic"}:
        extended_profile = EXTENDED_MELODY_PROFILES.get(
            "inharmonic_mallet" if palette == "inharmonic" else "soft_spectral_pad"
        )
        ratios = (
            (1.0, .60), (2.0, .24), (3.0, .12), (4.0, .07), (5.0, .035),
            (6.0, .02), (7.0, .012), (8.0, .008),
        ) if palette == "additive" else (
            (1.0, .58), (2.76, .24), (5.41, .13), (8.93, .07),
            (13.1, .035), (17.8, .018),
        )
        if extended_profile is not None:
            ratios = extended_profile.partials
        for index, (ratio, amp) in enumerate(ratios):
            detune = 1.0 + instability * (0.0007 * np.sin(2*np.pi*(.11+index*.017)*t))
            signal += amp * partial_level(float(ratio)) * np.sin(
                carrier_phase * float(ratio) * detune + rng_phase[index]
            )
    elif palette == "modal" or palette == "physical":
        # Modal bank: inharmonic frequencies with individual decay constants.
        mode_profile = EXTENDED_MELODY_PROFILES.get(
            "inharmonic_mallet" if palette == "physical" else "metallic_fm"
        )
        ratios = mode_profile.partials if mode_profile is not None else (
            (1.0, .62), (2.32, .28), (4.18, .19), (6.71, .12), (9.4, .075), (13.2, .04)
        )
        modes = tuple(
            (ratio, amplitude, max(.10, .65 - index * .075))
            for index, (ratio, amplitude) in enumerate(ratios)
        )
        excitation = np.exp(-t / (0.004 + (1.0-brightness)*0.012))
        for index, (ratio, amp, decay) in enumerate(modes):
            mode = np.sin(carrier_phase * float(ratio) + rng_phase[index])
            signal += (
                amp * partial_level(float(ratio)) * mode
                * np.exp(-t / (decay * (0.35 + duration))) * excitation
            )
    elif palette == "granular":
        # Micro-grain cloud around a tuned carrier; fixed windows avoid clicks.
        grain_count = (
            max(8, int(duration * (18 + 70 * brightness)))
            if grain_density_hz is None
            else max(0, int(round(duration * float(grain_density_hz))))
        )
        centres = (
            np.linspace(0.015, max(0.02, duration), grain_count)
            if grain_count else np.empty(0, dtype=np.float64)
        )
        grain_duration = (
            (0.012 + 0.055 * (1.0 - brightness))
            if grain_size_ms is None else float(grain_size_ms) / 1000.0
        )
        grain_phase_offset = (
            0.0 if grain_position is None
            else (float(grain_position) - 0.5) * 2.0 * np.pi
        )
        for index, centre in enumerate(centres):
            rate = 1.0 + rng.uniform(-0.12, 0.12) * (0.25 + instability)
            start = max(0, int((centre - grain_duration * .5) * sample_rate))
            end = min(length, int((centre + grain_duration * .5) * sample_rate))
            if end <= start:
                continue
            local_t = np.arange(end-start, dtype=np.float64) / sample_rate
            window = np.hanning(max(3, end-start))
            local_phase = carrier_phase[start:end] - carrier_phase[start]
            grain = np.sin(
                local_phase * rate
                + rng_phase[index % len(rng_phase)]
                + grain_phase_offset
            )
            signal[start:end] += grain * window * (0.55 / max(1, grain_count)**0.35)
    else:
        # Wavetable/pulsar hybrid: smoothly scan harmonic tables by varying
        # partial amplitudes over a slow cycle; pulses expose microscopic slices.
        table_position = 0.5 if wavetable_position is None else float(wavetable_position)
        phase = (
            carrier_phase / (2.0 * np.pi) + table_position - 0.5
        ) % 1.0
        pulse_width = 0.18 + 0.72 * brightness
        pulse = np.clip((pulse_width - phase) * 28.0, 0.0, 1.0)
        scan = 0.5 + 0.5 * np.sin(
            2 * np.pi * (0.17 + instability * 0.31) * t
            + 2 * np.pi * (table_position - 0.5)
        )
        for index, ratio in enumerate((1.0, 2.0, 3.01, 4.2, 5.7, 7.4)):
            amp = (
                0.55 / (index + 1)
            ) * (0.2 + 0.8 * scan ** (1 + index * 0.35))
            signal += (
                amp * partial_level(float(ratio))
                * np.sin(carrier_phase * ratio + rng_phase[index]) * pulse
            )

    signal *= body_env
    # Gentle spectral darkening, implemented without an external DSP backend.
    cutoff = min(sample_rate * .44, frequency * (7.0 + 34.0 * brightness))
    spectrum = np.fft.rfft(signal)
    hz = np.fft.rfftfreq(length, 1.0 / sample_rate)
    spectrum *= 1.0 / np.sqrt(1.0 + (hz / max(120.0, cutoff)) ** 8)
    signal = np.fft.irfft(spectrum, n=length)
    drive = 1.0 + 1.6 * instability
    signal = np.tanh(signal * drive) / max(1.0, np.tanh(drive) * 1.5)
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak > 1e-9:
        signal *= min(1.0, 0.82 / peak)
    return (signal * float(np.clip(velocity, 0.0, 1.0))).astype(np.float32)


def _one_pole_lowpass(
        signal: np.ndarray,
        sample_rate: int,
        cutoff_hz: float | np.ndarray,
) -> np.ndarray:
    """One-pole low-pass with scalar or per-sample cutoff automation."""
    cutoff = np.clip(np.asarray(cutoff_hz, dtype=np.float64), 20.0, sample_rate * 0.45)
    if cutoff.ndim == 0:
        coefficient = np.full(len(signal), 1.0 - np.exp(-2.0 * np.pi * float(cutoff) / sample_rate))
    else:
        if cutoff.shape != signal.shape:
            cutoff = np.broadcast_to(cutoff, signal.shape)
        coefficient = 1.0 - np.exp(-2.0 * np.pi * cutoff / sample_rate)
    output = np.empty_like(signal, dtype=np.float64)
    state = 0.0
    for index, sample in enumerate(signal):
        state += float(coefficient[index]) * (float(sample) - state)
        output[index] = state
    return output


def render_subtractive_note(
        frequency: float,
        sample_rate: int,
        rng: np.random.Generator,
        duration: float = 0.22,
        velocity: float = 0.55,
        profile: str = "dry_pluck",
        brightness: float = 0.42,
        instability: float = 0.0,
        attack_seconds: float | None = None,
        decay_seconds: float | None = None,
        release_seconds: float | None = None,
        vibrato_depth_semitones: float = 0.0,
        vibrato_rate_hz: float = 0.0,
) -> np.ndarray:
    """Render a genuinely subtractive voice: harmonic source, moving filter, ADSR.

    Unlike the FM renderer, this uses a pulse/saw-like harmonic source filtered by
    a time-varying one-pole ladder approximation. No FM operator is involved.
    """
    if frequency <= 0 or sample_rate <= 0 or duration <= 0:
        raise ValueError("frequency, sample_rate, and duration must be positive")
    if profile not in SUBTRACTIVE_VOICES:
        raise ValueError(f"unknown subtractive profile: {profile}")
    if not 0.0 <= brightness <= 1.0 or not 0.0 <= instability <= 1.0:
        raise ValueError("brightness and instability must be between zero and one")
    shape = SUBTRACTIVE_VOICES[profile]
    attack_time = _envelope_time(attack_seconds, shape.attack, 0.0001, "attack_seconds")
    decay_time = _envelope_time(decay_seconds, shape.decay, 0.0001, "decay_seconds")
    release_time = _envelope_time(release_seconds, shape.release, 0.0001, "release_seconds")
    length = max(64, int(round(sample_rate * (duration + release_time + 0.04))))
    t = np.arange(length, dtype=np.float64) / float(sample_rate)
    phase_drift = np.sin(2*np.pi*0.13*t) * shape.drift_cents * instability
    source = np.zeros(length, dtype=np.float64)
    carrier_phase = _carrier_phase(
        frequency, t, sample_rate, vibrato_depth_semitones, vibrato_rate_hz
    )
    phase = carrier_phase * np.power(2.0, phase_drift / 1200.0)
    for harmonic, amplitude in enumerate(shape.harmonics, start=1):
        source += amplitude * np.sin(harmonic * phase)
    if len(shape.harmonics) > 4:
        source += 0.12 * np.sign(np.sin(phase))
    attack = np.clip(t / max(attack_time, 1e-4), 0.0, 1.0)
    decay = shape.sustain + (1.0-shape.sustain)*np.exp(
        -np.maximum(0.0, t-attack_time)/max(decay_time, 1e-4)
    )
    envelope = attack * decay
    release_start = duration
    release = np.exp(-np.maximum(0.0, t-release_start)/max(release_time, 1e-4))
    envelope *= np.where(t >= release_start, release, 1.0)
    filter_env = np.exp(-t/max(shape.decay*1.8, 1e-3))
    cutoff = frequency * (
        1.6 + 18.0*brightness + shape.filter_env_amount*28.0*filter_env
    )
    filtered = _one_pole_lowpass(source, sample_rate, cutoff)
    # Small resonant emphasis via a high-passed portion; deliberately restrained.
    high = source - filtered
    signal = filtered + shape.resonance * high
    signal *= envelope
    signal = np.tanh(signal * 1.1)
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak > 1e-9:
        signal *= 0.78 / peak
    return (signal * float(np.clip(velocity, 0.0, 1.0))).astype(np.float32)


def render_synthetic_percussion(
        voice: str,
        sample_rate: int,
        rng: np.random.Generator,
        duration: float = 0.22,
        velocity: float = 0.7,
        pitch_hz: float | None = None,
) -> np.ndarray:
    """Render a sparse transient/body/tail percussion object without FM."""
    if voice not in PERCUSSION_VOICES:
        raise ValueError(f"unknown percussion voice: {voice}")
    if sample_rate <= 0 or duration <= 0:
        raise ValueError("sample_rate and duration must be positive")
    shape = PERCUSSION_VOICES[voice]
    length = max(32, int(round(sample_rate * duration)))
    t = np.arange(length, dtype=np.float64)/sample_rate
    signal = np.zeros(length, dtype=np.float64)
    if shape.body_hz > 0.0:
        base = float(pitch_hz or shape.body_hz)
        ratio = 1.0 + shape.inharmonicity
        body = np.sin(2*np.pi*base*t) * 0.72
        if shape.inharmonicity:
            body += 0.22*np.sin(2*np.pi*base*ratio*2.17*t)
        signal += body*np.exp(-t/max(shape.body_decay, 1e-4))
    if shape.transient_gain:
        transient_noise = rng.standard_normal(length)
        transient = transient_noise*np.exp(-t/max(shape.transient_decay, 1e-4))
        signal += shape.transient_gain*transient
    if shape.noise_gain:
        noise = rng.standard_normal(length)
        # Tilt the noise toward the top end without generating an unbounded hiss.
        high = np.empty_like(noise)
        high[0] = noise[0]
        high[1:] = noise[1:] - 0.92*noise[:-1]
        signal += shape.noise_gain*high*np.exp(-t/max(shape.body_decay, 1e-4))
    if shape.tail_gain:
        tail = np.zeros(length, dtype=np.float64)
        ratios = (1.0, 2.31, 3.87, 6.14)
        for index, ratio in enumerate(ratios):
            tail += np.sin(2*np.pi*float(pitch_hz or shape.body_hz)*ratio*t + index*.7)/(index+1)
        signal += shape.tail_gain*tail*np.exp(-t/max(shape.tail_decay, 1e-4))
    # A short onset ramp and restrained output level make dry hits sit naturally.
    attack = 1.0-np.exp(-t/0.0008)
    signal *= attack
    signal = np.tanh(signal*0.8)
    peak=float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak>1e-9:
        signal *= 0.72/peak
    return (signal*float(np.clip(velocity,0.0,1.0))).astype(np.float32)


