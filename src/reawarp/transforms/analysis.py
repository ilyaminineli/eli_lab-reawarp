"""Transient and slice analysis for imported break material."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class AudioSlice:
    """A half-open slice range measured in audio frames."""

    start: int
    end: int

    @property
    def frame_count(self) -> int:
        return self.end - self.start


def _mono(audio: np.ndarray) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        return samples
    if samples.ndim == 2 and samples.shape[1] in (1, 2):
        return samples.mean(axis=1, dtype=np.float32)
    raise ValueError("audio must have shape (frames,), (frames, 1), or (frames, 2)")


def detect_transients(
        audio: np.ndarray,
        sample_rate: int,
        *,
        threshold: float = 0.22,
        min_interval_ms: float = 70.0,
        window_ms: float = 12.0,
        hop_ms: float = 3.0,
) -> list[int]:
    """Return onset frame indices using positive short-time energy flux.

    The detector is dependency-free. Threshold is relative to the strongest
    positive energy rise; returned indices are sample-frame positions.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    if min_interval_ms < 0 or window_ms <= 0 or hop_ms <= 0:
        raise ValueError("timing parameters must be positive (min_interval may be zero)")
    signal = np.nan_to_num(_mono(audio), nan=0.0, posinf=0.0, neginf=0.0)
    if signal.size < 2 or float(np.max(np.abs(signal))) < 1e-8:
        return []

    window = max(8, int(round(sample_rate * window_ms / 1000.0)))
    hop = max(1, int(round(sample_rate * hop_ms / 1000.0)))
    frame_count = max(1, int(np.ceil(max(0, signal.size - window) / hop)) + 1)
    padded = np.pad(signal, (0, max(0, (frame_count - 1) * hop + window - signal.size)))
    rms = np.empty(frame_count, dtype=np.float64)
    for index in range(frame_count):
        frame = padded[index * hop: index * hop + window].astype(np.float64)
        rms[index] = np.sqrt(np.mean(frame * frame) + 1e-15)

    flux = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    peak = float(np.max(flux))
    if peak <= 1e-10:
        return []
    cutoff = peak * threshold
    candidates: list[tuple[int, float]] = []
    for index in range(1, len(flux)):
        previous = flux[index - 1]
        current = flux[index]
        following = flux[index + 1] if index + 1 < len(flux) else 0.0
        if current >= cutoff and current >= previous and current > following:
            candidates.append((min(signal.size - 1, index * hop), float(current)))

    min_gap = int(round(sample_rate * min_interval_ms / 1000.0))
    selected: list[tuple[int, float]] = []
    for candidate in candidates:
        if not selected or candidate[0] - selected[-1][0] >= min_gap:
            selected.append(candidate)
        elif candidate[1] > selected[-1][1]:
            selected[-1] = candidate
    return [position for position, _ in selected]


def slice_audio(audio: np.ndarray, boundaries: list[int] | tuple[int, ...]) -> list[np.ndarray]:
    """Split audio at frame boundaries; zero and the final frame are implicit."""
    samples = np.asarray(audio)
    if samples.ndim not in (1, 2):
        raise ValueError("audio must be mono or frame-major multichannel audio")
    if samples.shape[0] == 0:
        return []
    points = sorted({0, samples.shape[0], *(int(x) for x in boundaries)})
    if any(point < 0 or point > samples.shape[0] for point in points):
        raise ValueError("slice boundaries must be within the audio")
    return [samples[a:b].copy() for a, b in zip(points[:-1], points[1:]) if b > a]


def auto_slice(
        audio: np.ndarray,
        sample_rate: int,
        *,
        threshold: float = 0.22,
        min_interval_ms: float = 70.0,
        max_slices: int | None = None,
) -> list[AudioSlice]:
    """Detect transients and return ordered, non-overlapping slice ranges."""
    samples = np.asarray(audio)
    if samples.ndim not in (1, 2):
        raise ValueError("audio must be mono or frame-major multichannel audio")
    length = samples.shape[0]
    if length == 0:
        return []
    transients = detect_transients(
        samples, sample_rate, threshold=threshold, min_interval_ms=min_interval_ms
    )
    points = sorted({0, *[x for x in transients if 0 < x < length], length})
    if max_slices is not None:
        if max_slices < 1:
            raise ValueError("max_slices must be at least one")
        if len(points) - 1 > max_slices:
            interior = np.asarray(points[1:-1], dtype=np.int64)
            keep = max(0, max_slices - 1)
            if keep:
                indices = np.linspace(0, len(interior) - 1, keep).round().astype(int)
                points = [0, *interior[np.unique(indices)].tolist(), length]
            else:
                points = [0, length]
    return [AudioSlice(a, b) for a, b in zip(points[:-1], points[1:]) if b > a]
