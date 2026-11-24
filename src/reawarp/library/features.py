"""Dependency-light audio descriptors for the searchable Reawarp library."""

from __future__ import annotations

import math
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from reawarp.samples.io import read_sample
from reawarp.transforms.analysis import detect_transients

ANALYSIS_SAMPLE_RATE = 22_050
SUPPORTED_AUDIO_SUFFIXES = {".wav", ".flac", ".aif", ".aiff", ".ogg"}


@dataclass(frozen=True, slots=True)
class AudioFeatures:
    """Compact timbral and rhythmic description of an audio asset."""

    analysis_sample_rate: int
    frames: int
    duration_seconds: float
    peak: float
    rms: float
    rms_dbfs: float
    crest_factor_db: float
    zero_crossing_rate: float
    spectral_centroid_hz: float
    spectral_rolloff85_hz: float
    spectral_flatness: float
    onset_count: int
    onset_density_per_second: float
    onset_interval_cv: float
    tempo_bpm: float | None
    rhythm_histogram: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def source_audio_info(path: str | Path) -> tuple[int, int]:
    """Return original sample rate and channel count without decoding the file."""
    source = Path(path)
    try:
        import soundfile as sf
    except ImportError:
        if source.suffix.lower() != ".wav":
            raise ValueError(
                "non-WAV library indexing requires the optional soundfile package"
            )
        with wave.open(str(source), "rb") as wav:
            return int(wav.getframerate()), int(wav.getnchannels())
    info = sf.info(str(source))
    return int(info.samplerate), int(info.channels)


def _spectral_descriptors(audio: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    frame_length = 2_048
    hop_length = 1_024
    if audio.size <= frame_length:
        starts = [0]
    else:
        starts_array = np.arange(0, audio.size - frame_length + 1, hop_length)
        if starts_array.size > 512:
            selected = np.linspace(0, starts_array.size - 1, 512).round().astype(int)
            starts_array = starts_array[np.unique(selected)]
        starts = starts_array.tolist()

    window = np.hanning(frame_length).astype(np.float64)
    frames = np.zeros((len(starts), frame_length), dtype=np.float64)
    for index, start in enumerate(starts):
        chunk = audio[start:start + frame_length]
        frames[index, :len(chunk)] = chunk
    power = np.abs(np.fft.rfft(frames * window[None, :], axis=1)) ** 2
    frequencies = np.fft.rfftfreq(frame_length, 1.0 / float(sample_rate))
    totals = np.sum(power, axis=1) + 1e-15

    centroid = np.sum(power * frequencies[None, :], axis=1) / totals
    cumulative = np.cumsum(power, axis=1)
    rolloff_indices = np.argmax(cumulative >= (totals[:, None] * 0.85), axis=1)
    rolloff = frequencies[rolloff_indices]

    positive_power = np.maximum(power[:, 1:], 1e-15)
    flatness = np.exp(np.mean(np.log(positive_power), axis=1)) / (
            np.mean(positive_power, axis=1) + 1e-15
    )
    return (
        float(np.mean(centroid)),
        float(np.mean(rolloff)),
        float(np.clip(np.mean(flatness), 0.0, 1.0)),
    )


def _rhythm_descriptors(
        onsets: list[int],
        sample_rate: int,
        duration_seconds: float,
) -> tuple[float, float, float | None, tuple[float, ...]]:
    if len(onsets) >= 2:
        intervals = np.diff(np.asarray(onsets, dtype=np.float64)) / float(sample_rate)
        median_interval = float(np.median(intervals))
        interval_cv = float(np.std(intervals) / (np.mean(intervals) + 1e-12))
        tempo = 60.0 / max(median_interval, 1e-9)
        while tempo < 60.0:
            tempo *= 2.0
        while tempo > 180.0:
            tempo /= 2.0
        tempo_bpm: float | None = float(tempo) if 60.0 <= tempo <= 180.0 else None
    else:
        interval_cv = 0.0
        tempo_bpm = None

    histogram = np.zeros(16, dtype=np.float64)
    if onsets:
        if tempo_bpm is not None:
            cycle_seconds = 240.0 / tempo_bpm
        else:
            cycle_seconds = max(duration_seconds, 1e-9)
        onset_seconds = np.asarray(onsets, dtype=np.float64) / float(sample_rate)
        phase = np.mod(onset_seconds, cycle_seconds) / cycle_seconds
        bins = np.minimum(15, np.floor(phase * 16.0).astype(int))
        np.add.at(histogram, bins, 1.0)
        histogram /= max(1.0, float(np.sum(histogram)))

    density = float(len(onsets) / max(duration_seconds, 1e-9))
    return density, interval_cv, tempo_bpm, tuple(float(value) for value in histogram)


def analyze_audio_file(path: str | Path) -> tuple[dict[str, int], AudioFeatures]:
    """Load and analyse one file using NumPy and the existing sample reader."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    source_rate, channels = source_audio_info(source)
    audio = read_sample(source, ANALYSIS_SAMPLE_RATE)
    if audio.size == 0:
        raise ValueError(f"audio asset is empty: {source}")
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    frames = int(audio.size)
    duration = frames / float(ANALYSIS_SAMPLE_RATE)
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    rms_dbfs = float(20.0 * math.log10(max(rms, 1e-12)))
    crest_db = float(20.0 * math.log10(max(peak, 1e-12) / max(rms, 1e-12)))
    zero_crossing = float(np.mean(np.not_equal(audio[1:] < 0.0, audio[:-1] < 0.0))) if frames > 1 else 0.0
    centroid, rolloff, flatness = _spectral_descriptors(audio, ANALYSIS_SAMPLE_RATE)
    onsets = detect_transients(
        audio, ANALYSIS_SAMPLE_RATE, threshold=0.20, min_interval_ms=40.0
    )
    density, interval_cv, tempo, histogram = _rhythm_descriptors(
        onsets, ANALYSIS_SAMPLE_RATE, duration
    )
    info = {
        "source_sample_rate": int(source_rate),
        "channels": int(channels),
        "analysis_sample_rate": ANALYSIS_SAMPLE_RATE,
        "frames": frames,
    }
    features = AudioFeatures(
        analysis_sample_rate=ANALYSIS_SAMPLE_RATE,
        frames=frames,
        duration_seconds=float(duration),
        peak=peak,
        rms=rms,
        rms_dbfs=rms_dbfs,
        crest_factor_db=crest_db,
        zero_crossing_rate=zero_crossing,
        spectral_centroid_hz=centroid,
        spectral_rolloff85_hz=rolloff,
        spectral_flatness=flatness,
        onset_count=len(onsets),
        onset_density_per_second=density,
        onset_interval_cv=interval_cv,
        tempo_bpm=tempo,
        rhythm_histogram=histogram,
    )
    return info, features
