"""Deterministic break-sample transformations implemented with NumPy."""

from __future__ import annotations

import math

import numpy as np


def _audio_2d(audio: np.ndarray) -> tuple[np.ndarray, bool]:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        return samples[:, None], True
    if samples.ndim == 2 and samples.shape[1] in (1, 2):
        return samples, False
    raise ValueError("audio must have shape (frames,), (frames, 1), or (frames, 2)")


def _restore(samples: np.ndarray, was_mono: bool) -> np.ndarray:
    result = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return result[:, 0] if was_mono else result


def reverse_audio(audio: np.ndarray) -> np.ndarray:
    """Reverse frames without changing channel order or sample count."""
    samples, mono = _audio_2d(audio)
    return _restore(samples[::-1].copy(), mono)


def rearrange_slices(
    audio: np.ndarray,
    boundaries: list[int] | tuple[int, ...],
    *,
    order: list[int] | tuple[int, ...] | None = None,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Rearrange transient slices while preserving the exact total frame count."""
    from reawarp.transforms.analysis import slice_audio

    samples, mono = _audio_2d(audio)
    chunks = slice_audio(samples, list(boundaries))
    if len(chunks) < 2:
        return _restore(samples.copy(), mono)
    if order is None:
        if rng is None:
            raise ValueError("provide either an explicit order or a random generator")
        indices = np.arange(len(chunks))
        rng.shuffle(indices)
        order = indices.tolist()
    if sorted(int(x) for x in order) != list(range(len(chunks))):
        raise ValueError("order must be a permutation of all slice indices")
    joined = np.concatenate([chunks[int(index)] for index in order], axis=0)
    return _restore(joined, mono)


def stutter(
    audio: np.ndarray,
    *,
    repeats: int = 4,
    start: int = 0,
    end: int | None = None,
) -> np.ndarray:
    """Repeat a selected segment inside its original time slot."""
    samples, mono = _audio_2d(audio)
    length = len(samples)
    if repeats < 2:
        raise ValueError("repeats must be at least two")
    start = int(start)
    end = length if end is None else int(end)
    if start < 0 or end > length or end <= start:
        raise ValueError("stutter segment must be a non-empty range inside the audio")
    segment = samples[start:end]
    grain_length = max(1, int(math.ceil(len(segment) / repeats)))
    grain = segment[:grain_length]
    repeated = np.tile(grain, (int(math.ceil(len(segment) / len(grain))), 1))[: len(segment)]
    result = samples.copy()
    result[start:end] = repeated
    return _restore(result, mono)


def dropout(
    audio: np.ndarray,
    *,
    probability: float = 0.18,
    block_ms: float = 45.0,
    sample_rate: int = 48_000,
    rng: np.random.Generator,
) -> np.ndarray:
    """Mute randomly selected short blocks, retaining the source duration."""
    samples, mono = _audio_2d(audio)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between zero and one")
    if sample_rate <= 0 or block_ms <= 0:
        raise ValueError("sample_rate and block_ms must be positive")
    block = max(1, int(round(sample_rate * block_ms / 1000.0)))
    result = samples.copy()
    for start in range(0, len(result), block):
        if rng.random() < probability:
            result[start : start + block] = 0.0
    return _restore(result, mono)


def gate_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    rate_hz: float = 8.0,
    duty: float = 0.62,
    fade_ms: float = 2.0,
) -> np.ndarray:
    """Apply a periodic, softly edged amplitude gate."""
    samples, mono = _audio_2d(audio)
    if sample_rate <= 0 or rate_hz <= 0:
        raise ValueError("sample_rate and rate_hz must be positive")
    if not 0.0 < duty <= 1.0:
        raise ValueError("duty must be in (0, 1]")
    if fade_ms < 0:
        raise ValueError("fade_ms cannot be negative")
    if duty >= 1.0:
        return _restore(samples.copy(), mono)
    period = sample_rate / rate_hz
    phase = np.mod(np.arange(len(samples), dtype=np.float64), period) / period
    mask = (phase < duty).astype(np.float64)
    fade = min(float(fade_ms) / 1000.0 * rate_hz, duty * 0.45, (1.0 - duty) * 0.45)
    if fade > 0:
        fade_in = np.clip(phase / fade, 0.0, 1.0)
        fade_out = np.clip((duty - phase) / fade, 0.0, 1.0)
        mask *= np.minimum(fade_in, fade_out)
    return _restore(samples * mask[:, None], mono)


def _phase_vocoder(samples: np.ndarray, factor: float) -> np.ndarray:
    """Stretch a frame-major signal with an STFT phase vocoder."""
    frame_count = len(samples)
    if frame_count < 64:
        target = max(1, int(round(frame_count * factor)))
        old = np.linspace(0.0, 1.0, frame_count)
        new = np.linspace(0.0, 1.0, target)
        return np.column_stack([
            np.interp(new, old, samples[:, channel]) for channel in range(samples.shape[1])
        ]).astype(np.float32)

    power = min(11, int(math.floor(math.log2(min(frame_count, 2048)))))
    fft_size = max(64, 2 ** power)
    hop = max(16, fft_size // 4)
    pad = fft_size // 2
    mode = "reflect" if frame_count > 1 else "edge"
    padded = np.pad(samples, ((pad, pad), (0, 0)), mode=mode)
    n_frames = max(2, int(math.ceil((len(padded) - fft_size) / hop)) + 1)
    required = (n_frames - 1) * hop + fft_size
    if required > len(padded):
        padded = np.pad(padded, ((0, required - len(padded)), (0, 0)))
    window = np.hanning(fft_size + 1)[:-1].astype(np.float64)
    frames = np.stack([
        padded[index * hop : index * hop + fft_size] for index in range(n_frames)
    ])
    spectrum = np.fft.rfft(frames * window[None, :, None], axis=1)
    time_steps = np.arange(0.0, n_frames - 1.0, 1.0 / factor)
    if len(time_steps) == 0:
        time_steps = np.asarray([0.0])
    bins = np.arange(spectrum.shape[1], dtype=np.float64)
    phase_advance = 2.0 * np.pi * hop * bins / fft_size
    phase_acc = np.angle(spectrum[0]).copy()
    output_frames = np.empty(
        (len(time_steps), spectrum.shape[1], samples.shape[1]), dtype=np.complex128
    )
    for out_index, step in enumerate(time_steps):
        index = min(int(step), n_frames - 2)
        fraction = float(step - index)
        first = spectrum[index]
        second = spectrum[index + 1]
        magnitude = (1.0 - fraction) * np.abs(first) + fraction * np.abs(second)
        delta = np.angle(second) - np.angle(first) - phase_advance[:, None]
        delta -= 2.0 * np.pi * np.round(delta / (2.0 * np.pi))
        if out_index:
            phase_acc += phase_advance[:, None] + delta
        output_frames[out_index] = magnitude * np.exp(1j * phase_acc)

    output_length = max(1, int(round(frame_count * factor)))
    raw_length = (len(output_frames) - 1) * hop + fft_size
    output = np.zeros((raw_length, samples.shape[1]), dtype=np.float64)
    normalizer = np.zeros(raw_length, dtype=np.float64)
    for index, spectrum_frame in enumerate(output_frames):
        frame = np.fft.irfft(spectrum_frame, n=fft_size, axis=0).real
        start = index * hop
        output[start : start + fft_size] += frame * window[:, None]
        normalizer[start : start + fft_size] += window * window
    valid = normalizer > 1e-8
    output[valid] /= normalizer[valid, None]
    trimmed = output[pad : pad + output_length]
    if len(trimmed) < output_length:
        trimmed = np.pad(trimmed, ((0, output_length - len(trimmed)), (0, 0)))
    return trimmed.astype(np.float32)


def time_stretch(audio: np.ndarray, factor: float = 1.0) -> np.ndarray:
    """Change duration while approximately preserving pitch. Factor is the output/input length ratio."""
    samples, mono = _audio_2d(audio)
    if not 0.25 <= factor <= 4.0:
        raise ValueError("time-stretch factor must be between 0.25 and 4.0")
    if len(samples) == 0 or abs(factor - 1.0) < 1e-9:
        return _restore(samples.copy(), mono)
    return _restore(_phase_vocoder(samples, float(factor)), mono)


def pitch_shift(audio: np.ndarray, semitones: float) -> np.ndarray:
    """Shift pitch by semitones and preserve the original frame count."""
    samples, mono = _audio_2d(audio)
    if not -24.0 <= semitones <= 24.0:
        raise ValueError("pitch shift must be between -24 and 24 semitones")
    if len(samples) == 0 or abs(semitones) < 1e-9:
        return _restore(samples.copy(), mono)
    ratio = 2.0 ** (float(semitones) / 12.0)
    intermediate_length = max(1, int(round(len(samples) / ratio)))
    source_positions = np.arange(intermediate_length, dtype=np.float64) * ratio
    source_positions = np.clip(source_positions, 0.0, max(0, len(samples) - 1))
    original_positions = np.arange(len(samples), dtype=np.float64)
    resampled = np.column_stack([
        np.interp(source_positions, original_positions, samples[:, channel])
        for channel in range(samples.shape[1])
    ]).astype(np.float32)
    shifted = _phase_vocoder(resampled, len(samples) / intermediate_length)
    if len(shifted) > len(samples):
        shifted = shifted[: len(samples)]
    elif len(shifted) < len(samples):
        shifted = np.pad(shifted, ((0, len(samples) - len(shifted)), (0, 0)))
    return _restore(shifted, mono)


def granular_resynthesis(
    audio: np.ndarray,
    sample_rate: int,
    *,
    grain_size_ms: float = 80.0,
    density: float = 1.5,
    jitter: float = 0.35,
    rng: np.random.Generator,
) -> np.ndarray:
    """Resynthesize a same-length buffer from overlapping, jittered source grains."""
    samples, mono = _audio_2d(audio)
    if sample_rate <= 0 or grain_size_ms <= 0:
        raise ValueError("sample_rate and grain_size_ms must be positive")
    if not 0.25 <= density <= 4.0 or not 0.0 <= jitter <= 1.0:
        raise ValueError("density must be 0.25–4.0 and jitter 0–1")
    length = len(samples)
    if length == 0:
        return _restore(samples.copy(), mono)
    grain = min(length, max(8, int(round(sample_rate * grain_size_ms / 1000.0))))
    output_hop = max(1, int(round(grain / density)))
    window = np.hanning(grain + 1)[:-1].astype(np.float64)
    output = np.zeros_like(samples, dtype=np.float64)
    weight = np.zeros(length, dtype=np.float64)
    max_jitter = int(round(grain * jitter))
    for out_start in range(0, length, output_hop):
        source_start = out_start + (
            int(rng.integers(-max_jitter, max_jitter + 1)) if max_jitter else 0
        )
        indices = (source_start + np.arange(grain)) % length
        count = min(grain, length - out_start)
        local_window = window[:count]
        output[out_start : out_start + count] += samples[indices[:count]] * local_window[:, None]
        weight[out_start : out_start + count] += local_window
    valid = weight > 1e-7
    output[valid] /= weight[valid, None]
    return _restore(output, mono)


def spectral_freeze(
    audio: np.ndarray,
    sample_rate: int,
    *,
    position: float = 0.25,
    mix: float = 1.0,
    window_ms: float = 120.0,
) -> np.ndarray:
    """Hold one selected spectral frame across the source duration."""
    samples, mono = _audio_2d(audio)
    if sample_rate <= 0 or window_ms <= 0:
        raise ValueError("sample_rate and window_ms must be positive")
    if not 0.0 <= position <= 1.0 or not 0.0 <= mix <= 1.0:
        raise ValueError("position and mix must be between zero and one")
    length = len(samples)
    if length == 0 or mix == 0:
        return _restore(samples.copy(), mono)
    size = min(length, max(32, int(round(sample_rate * window_ms / 1000.0))))
    center = int(round((length - 1) * position))
    start = max(0, min(length - size, center - size // 2))
    frame = samples[start : start + size].copy()
    if len(frame) < size:
        frame = np.pad(frame, ((0, size - len(frame)), (0, 0)))
    window = np.hanning(size + 1)[:-1]
    spectrum = np.fft.rfft(frame * window[:, None], axis=0)
    frozen = np.fft.irfft(spectrum, n=size, axis=0).real.astype(np.float32)
    hop = max(1, size // 2)
    held = np.zeros_like(samples, dtype=np.float64)
    weights = np.zeros(length, dtype=np.float64)
    for out_start in range(0, length, hop):
        count = min(size, length - out_start)
        held[out_start : out_start + count] += frozen[:count] * window[:count, None]
        weights[out_start : out_start + count] += window[:count] ** 2
    valid = weights > 1e-8
    held[valid] /= weights[valid, None]
    result = samples * (1.0 - mix) + held * mix
    return _restore(result, mono)
