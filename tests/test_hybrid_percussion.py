import wave
from pathlib import Path

import numpy as np

from reawarp import GenerationConfig, ReawarpEngine


def _write_test_sample(path: Path, sample_rate: int = 22_050) -> None:
    duration = 0.16
    count = int(sample_rate * duration)
    time = np.arange(count, dtype=np.float64) / sample_rate
    envelope = np.exp(-time * 20.0)
    signal = np.sin(2.0 * np.pi * 82.0 * time) * envelope
    signal[:24] += np.linspace(0.8, 0.0, 24)
    pcm = np.clip(signal, -1.0, 1.0)
    encoded = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(encoded)


def _config(sample_path: Path, **overrides):
    values = {
        "duration": 8.0,
        "bpm": 120.0,
        "sample_rate": 22_050,
        "seed": "hybrid-score-test",
        "pattern_follow_structure": True,
        "include_melody": False,
        "include_texture": False,
        "include_ambience": False,
        "sample_paths": {"kick": str(sample_path)},
        "sample_metadata": {
            "kick": {
                "provider": "test_fixture",
                "source_name": sample_path.name,
            }
        },
    }
    values.update(overrides)
    return GenerationConfig(**values)


def test_hybrid_transient_body_uses_one_shared_kick_event_stream(tmp_path: Path):
    sample = tmp_path / "sample_kick.wav"
    _write_test_sample(sample)
    config = _config(
        sample,
        percussion_source_mode="hybrid",
        percussion_hybrid_architecture="transient_body",
        percussion_sample_mix=0.4,
        hybrid_transient_ms=26.0,
    )
    project = ReawarpEngine().generate(config)

    assert "kick" in project.stems
    assert "sample_kick" not in project.stems
    assert np.isfinite(project.stems["kick"]).all()
    assert np.max(np.abs(project.stems["kick"])) > 0.0
    kick_events = [item for item in project.events if item.get("lane") == "kick"]
    assert kick_events
    assert all(item["source_mix"]["synth_gain"] == 1.0 for item in kick_events)
    assert all(item["source_mix"]["sample_gain"] == 0.4 for item in kick_events)
    assert project.metadata["sample_sources"]["kick"]["trigger_mode"] == "shared_drum_score"
    assert project.metadata["drum_source_mode"] == "hybrid"


def test_sample_only_mode_does_not_render_a_parallel_synth_layer(tmp_path: Path):
    sample = tmp_path / "sample_kick.wav"
    _write_test_sample(sample)
    config = _config(sample, percussion_source_mode="sample")
    project = ReawarpEngine().generate(config)
    events = [item for item in project.events if item.get("lane") == "kick"]
    assert events
    assert all(item["source_mix"]["synth_gain"] == 0.0 for item in events)
    assert all(item["source_mix"]["sample_gain"] == 1.0 for item in events)
    assert "sample_kick" not in project.stems


def test_layered_hybrid_uses_complementary_gains(tmp_path: Path):
    sample = tmp_path / "sample_kick.wav"
    _write_test_sample(sample)
    config = _config(
        sample,
        percussion_source_mode="hybrid",
        percussion_hybrid_architecture="layered",
        percussion_sample_mix=0.35,
    )
    project = ReawarpEngine().generate(config)
    events = [item for item in project.events if item.get("lane") == "kick"]
    assert events
    for event in events:
        assert event["source_mix"]["synth_gain"] == 0.65
        assert event["source_mix"]["sample_gain"] == 0.35
