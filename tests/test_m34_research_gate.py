from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from reawarp.library.features import analyze_audio_file

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "m34"
    / "audio_conditioning_order_pair.json"
)


def _pulse_segment(
    sample_rate: int,
    frame_count: int,
    *,
    frequency_hz: float,
    pulse_count: int,
    pulse_duration_seconds: float,
    amplitude: float,
) -> np.ndarray:
    result = np.zeros(frame_count, dtype=np.float32)
    pulse_frames = int(round(sample_rate * pulse_duration_seconds))
    for index in range(pulse_count):
        start = int((index + 0.25) * frame_count / pulse_count)
        end = min(frame_count, start + pulse_frames)
        length = end - start
        if length <= 0:
            continue
        envelope = np.sin(np.linspace(0.0, np.pi, length, dtype=np.float64)) ** 2
        phase = 2.0 * np.pi * frequency_hz * np.arange(length, dtype=np.float64) / sample_rate
        result[start:end] += (amplitude * envelope * np.sin(phase)).astype(np.float32)
    return np.clip(result, -0.95, 0.95)


def _guarded(segment: np.ndarray, guard_frames: int) -> np.ndarray:
    guard = np.zeros(guard_frames, dtype=np.float32)
    return np.concatenate((guard, segment, guard))


def _write_pcm16(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    pcm = np.rint(np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def _spectral_centroid(audio: np.ndarray, sample_rate: int) -> float:
    window = np.hanning(len(audio))
    power = np.abs(np.fft.rfft(audio.astype(np.float64) * window)) ** 2
    frequencies = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    return float(np.sum(power * frequencies) / max(float(np.sum(power)), 1e-15))


def test_m34_baseline_global_summaries_collapse_opposite_audio_orders(tmp_path):
    spec = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sample_rate = int(spec["sample_rate"])
    frame_count = int(spec["segment_frames"])
    guard_frames = 2048

    segments: dict[str, np.ndarray] = {}
    for name, item in spec["segments"].items():
        segments[name] = _pulse_segment(
            sample_rate,
            frame_count,
            frequency_hz=float(item["frequency_hz"]),
            pulse_count=int(item["pulse_count"]),
            pulse_duration_seconds=float(item["pulse_duration_seconds"]),
            amplitude=float(item["amplitude"]),
        )

    dark = segments["sparse_dark"]
    bright = segments["dense_bright"]
    assert _spectral_centroid(bright, sample_rate) > (
        _spectral_centroid(dark, sample_rate) * 10.0
    )

    guarded = {name: _guarded(value, guard_frames) for name, value in segments.items()}
    sequence_a = np.concatenate((guarded["sparse_dark"], guarded["dense_bright"]))
    sequence_b = np.concatenate((guarded["dense_bright"], guarded["sparse_dark"]))
    assert not np.array_equal(sequence_a, sequence_b)

    path_a = tmp_path / "sparse-dark_then_dense-bright.wav"
    path_b = tmp_path / "dense-bright_then_sparse-dark.wav"
    _write_pcm16(path_a, sequence_a, sample_rate)
    _write_pcm16(path_b, sequence_b, sample_rate)

    _, features_a = analyze_audio_file(path_a)
    _, features_b = analyze_audio_file(path_b)
    for name in spec["current_global_metrics_expected_to_match"]:
        value_a = float(getattr(features_a, name))
        value_b = float(getattr(features_b, name))
        assert value_a == pytest.approx(value_b, rel=1e-5, abs=1e-6), (
            f"global {name} unexpectedly describes temporal order"
        )

    # AudioFeatures is a whole-file summary: no feature frame or time-indexed
    # control curve is available to distinguish the two musical trajectories.
    assert not hasattr(features_a, "frame_features")
    assert not hasattr(features_a, "feature_curve")
    assert features_a.duration_seconds == pytest.approx(features_b.duration_seconds)


def test_m34_gate_fixture_is_reproducible_and_declares_a_single_order_pair():
    spec = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert spec["fixture_id"] == "m34-audio-conditioning-order-pair-v1"
    assert spec["sequences"]["A"] == ["sparse_dark", "dense_bright"]
    assert spec["sequences"]["B"] == ["dense_bright", "sparse_dark"]
    assert spec["temporal_order_expected_to_differ"] is True
