import wave
from pathlib import Path

import numpy as np

from reawarp import GenerationConfig, ReawarpEngine


def _write_sample(path: Path, frequency: float, transient: float = 0.8) -> None:
    sample_rate = 22_050
    duration = 0.20
    count = int(sample_rate * duration)
    time = np.arange(count, dtype=np.float64) / sample_rate
    envelope = np.exp(-time * (18.0 + frequency / 500.0))
    signal = np.sin(2.0 * np.pi * frequency * time) * envelope
    signal[:32] += np.linspace(transient, 0.0, 32)
    encoded = (np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(encoded)


def _features(centroid: float, flatness: float, onsets: float, crest: float) -> dict:
    return {
        "spectral_centroid_hz": centroid,
        "rms_dbfs": -20.0,
        "spectral_flatness": flatness,
        "onset_density_per_second": onsets,
        "crest_factor_db": crest,
    }


def test_feature_guided_bank_switches_by_phrase_and_returns_to_anchor(tmp_path: Path):
    paths = [
        tmp_path / "anchor_kick.wav",
        tmp_path / "bright_kick.wav",
        tmp_path / "granular_kick.wav",
    ]
    _write_sample(paths[0], 72.0)
    _write_sample(paths[1], 130.0, 1.0)
    _write_sample(paths[2], 205.0, 0.45)
    assets = (
        {"path": str(paths[0]), "asset_id": "anchor", "label": "anchor kick", "metadata": {"provider": "test", "role": "kick"}, "features": _features(650.0, 0.10, 3.0, 8.0)},
        {"path": str(paths[1]), "asset_id": "bright", "label": "bright kick", "metadata": {"provider": "test", "role": "kick"}, "features": _features(8800.0, 0.70, 11.0, 14.0)},
        {"path": str(paths[2]), "asset_id": "granular", "label": "granular kick", "metadata": {"provider": "test", "role": "kick"}, "features": _features(4200.0, 0.88, 8.0, 6.0)},
    )
    config = GenerationConfig(
        duration=90.0, bpm=120.0, sample_rate=22_050,
        seed="feature-guided-sample-bank", structure="sonata_mutation",
        pattern_follow_structure=True, drum_change_intensity=0.95,
        drum_part_cycle_bars=1, percussion_source_mode="hybrid",
        percussion_hybrid_architecture="feature_guided",
        percussion_sample_mix=0.42,
        sample_paths={"kick": str(paths[0])},
        sample_metadata={"kick": {"provider": "test", "role": "kick"}},
        sample_banks={"kick": assets}, drum_sample_automation="automatic",
        include_melody=False, include_texture=False, include_ambience=False,
    )
    first = ReawarpEngine().generate(config)
    second = ReawarpEngine().generate(config)

    source = first.metadata["sample_sources"]["kick"]
    assert source["bank_count"] == 3
    assert source["switch_points"]
    assert source["final_variant_count"] >= 2
    assert first.events == second.events
    assert first.metadata["sample_switch_summary"] == second.metadata["sample_switch_summary"]

    kick_events = [event for event in first.events if event.get("lane") == "kick"]
    assert kick_events
    assert all(event.get("sample_source") for event in kick_events)
    assert all(event["source_mix"]["architecture"] == "feature_guided" for event in kick_events)
    assert all(event["synthesis_guidance"]["spectral_centroid_hz"] > 0 for event in kick_events)
    assert all(abs(event["source_mix"]["synth_gain"] - 0.58) < 1e-9 for event in kick_events)
    assert all(abs(event["source_mix"]["sample_gain"] - 0.42) < 1e-9 for event in kick_events)

    reprise = [event for event in kick_events if event.get("section_name") == "REPRISE_TRANSFORMED"]
    assert reprise
    assert all(event["sample_source"]["asset_id"] == "anchor" for event in reprise)


def test_fixed_sample_automation_never_switches_variants(tmp_path: Path):
    anchor = tmp_path / "anchor.wav"
    other = tmp_path / "other.wav"
    _write_sample(anchor, 80.0)
    _write_sample(other, 180.0)
    entries = (
        {"path": str(anchor), "asset_id": "anchor", "metadata": {}, "features": {}},
        {"path": str(other), "asset_id": "other", "metadata": {}, "features": {}},
    )
    config = GenerationConfig(
        duration=12.0, bpm=120.0, sample_rate=22_050, seed=712,
        sample_paths={"kick": str(anchor)}, sample_banks={"kick": entries},
        drum_sample_automation="fixed", percussion_source_mode="sample",
        include_melody=False, include_texture=False, include_ambience=False,
    )
    project = ReawarpEngine().generate(config)
    events = [event for event in project.events if event.get("lane") == "kick"]
    assert events
    assert {event["sample_source"]["asset_id"] for event in events} == {"anchor"}
    assert project.metadata["sample_sources"]["kick"]["switch_points"] == []
