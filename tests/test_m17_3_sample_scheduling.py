from pathlib import Path
import wave

import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.generators.percussion import PercussionEvent
from reawarp.score.planner import score_from_planner_events
from reawarp.synthesis.score_samples import prepare_score_sample_renderers


def _write_sample(path: Path, *, seconds: float = 0.30, sample_rate: int = 22_050, frequency: float = 173.0):
    count = int(round(seconds * sample_rate))
    time = np.arange(count, dtype=np.float64) / sample_rate
    audio = 0.32 * np.sin(2.0 * np.pi * frequency * time)
    audio *= np.exp(-time * 1.5)
    # A clear broadband onset makes the sample's transient window observable.
    onset = min(96, count)
    audio[:onset] += np.linspace(0.95, 0.05, onset)
    encoded = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(encoded)


def _hit(role: str, step: int, kind: str = "test_hit") -> PercussionEvent:
    return PercussionEvent(role, step, 0.0, 0.82, 0.0, kind, "m17.3-test")


def _score(role_events, *, metadata=None):
    return score_from_planner_events(
        percussion=role_events,
        bpm=120.0,
        seed_streams={
            "kick_pattern": 11,
            "snare_pattern": 12,
            "hat_pattern": 13,
            "break_pattern": 14,
        },
        metadata=metadata,
    )


def _sample_entry(path: Path, asset_id: str, metadata: dict | None = None, features: dict | None = None):
    return {
        "path": str(path),
        "asset_id": asset_id,
        "label": asset_id,
        "metadata": metadata or {"provider": "test", "asset_id": asset_id},
        "features": features or {},
    }


def test_sample_only_hits_become_first_class_score_triggers_and_keep_iro_metadata(tmp_path: Path):
    sample = tmp_path / "iro-kick.wav"
    _write_sample(sample, seconds=0.20)
    iro_metadata = {
        "provider": "IRO",
        "pack": "experimental-drum-kit-211",
        "family": "sub_impact",
        "articulation": "low",
        "relative_path": "mutated_kit/kick_01.wav",
        "source_asset_sha256": "a" * 64,
        "source_feature_index": 17,
    }
    config = GenerationConfig(
        bpm=120.0,
        duration=5.0,
        sample_rate=22_050,
        seed="m17.3-sample-only",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        percussion_source_mode="sample",
        percussion_synthesis="samples",
        sample_banks={"kick": (_sample_entry(sample, "iro-kick-01", iro_metadata),)},
    )
    score = _score({"kick": [_hit("kick", 4)]})

    prepared = prepare_score_sample_renderers(score, config)
    assert prepared.score.metadata["sample_schedule"]["sources"]["kick"]["variants"][0]["metadata"] == iro_metadata
    assert prepared.sample_manifest["kick"]["variants"][0]["features"] == {}
    result = ReawarpEngine().render_score(score, config=config)
    trigger = next(item for item in result.schedule if item.event.kind == "trigger")
    hit = next(item for item in result.schedule if item.event.kind == "hit")

    assert trigger.event.voice_id == "kick"
    assert trigger.start_frame == 11_025
    assert trigger.duration_frames == int(0.20 * config.sample_rate)
    assert trigger.event.parameters["sample_asset_id"] == "iro-kick-01"
    assert trigger.event.parameters["sample_metadata"] == iro_metadata
    assert hit.event.parameters["synth_gain"] == 0.0
    assert hit.event.parameters["sample_gain"] == 1.0
    assert result.frame_count == config.frame_count
    assert np.isfinite(result.stems["kick"]).all()
    assert np.max(np.abs(result.stems["kick"])) > 0.05
    assert result.schedule
    schedule_meta = result.schedule[0].event.parameters
    assert schedule_meta is not None


def test_score_section_and_cycle_metadata_drive_deterministic_variant_switches(tmp_path: Path):
    anchor = tmp_path / "anchor.wav"
    alternative = tmp_path / "alternative.wav"
    _write_sample(anchor, frequency=110.0)
    _write_sample(alternative, frequency=440.0)
    bank = (
        _sample_entry(anchor, "anchor", features={"spectral_centroid_hz": 450.0}),
        _sample_entry(alternative, "alternative", features={"spectral_centroid_hz": 9_000.0}),
    )
    metadata = {
        "composition_plan": {
            "sections": [
                {"index": 0, "name": "Anchor Return", "start_bar": 0, "end_bar": 1},
                {"index": 1, "name": "False Return", "start_bar": 1, "end_bar": 2},
            ]
        },
        "phrase_directives": [
            {"start_bar": 0, "end_bar": 1, "function": "return"},
            {"start_bar": 1, "end_bar": 2, "function": "false_return"},
        ],
    }
    config = GenerationConfig(
        bpm=120.0,
        duration=6.0,
        sample_rate=22_050,
        seed="m17.3-section-selection",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        percussion_source_mode="sample",
        drum_sample_automation="automatic",
        sample_banks={"kick": bank},
    )
    score = _score({"kick": [_hit("kick", 0), _hit("kick", 16)]}, metadata=metadata)

    first = ReawarpEngine().render_score(score, config=config)
    second = ReawarpEngine().render_score(score, config=config)
    triggers = [item for item in first.schedule if item.event.kind == "trigger"]
    assert len(triggers) == 2
    assert [item.event.parameters["sample_variant_index"] for item in triggers] == [0, 1]
    assert [item.event.source_id for item in triggers] == ["anchor", "alternative"]
    assert [item.event.source_id for item in triggers] == [
        item.event.source_id for item in second.schedule if item.event.kind == "trigger"
    ]
    np.testing.assert_array_equal(first.stems["kick"], second.stems["kick"])
    prepared = prepare_score_sample_renderers(score, config)
    schedule_metadata = prepared.score.metadata["sample_schedule"]
    assert schedule_metadata["switch_summary"]["kick"]["variant_usage"] == {"0": 1, "1": 1}
    assert schedule_metadata["sources"]["kick"]["variants"][1]["asset_id"] == "alternative"
    assert triggers[0].event.parameters["sample_section_name"] == "Anchor Return"


def test_transient_body_hybrid_uses_short_sample_trigger_and_synth_body(tmp_path: Path):
    sample = tmp_path / "hybrid-kick.wav"
    _write_sample(sample, seconds=0.40)
    config = GenerationConfig(
        bpm=120.0,
        duration=5.0,
        sample_rate=22_050,
        seed="m17.3-transient-body",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        percussion_source_mode="hybrid",
        percussion_synthesis="extended",
        percussion_hybrid_architecture="transient_body",
        percussion_sample_mix=0.40,
        hybrid_transient_ms=20.0,
        sample_banks={"kick": (_sample_entry(sample, "hybrid-kick"),)},
    )
    result = ReawarpEngine().render_score(_score({"kick": [_hit("kick", 0)]}), config=config)
    hit = next(item for item in result.schedule if item.event.kind == "hit")
    trigger = next(item for item in result.schedule if item.event.kind == "trigger")

    assert hit.event.parameters["synth_gain"] == 1.0
    assert trigger.event.parameters["sample_gain"] == pytest.approx(0.40)
    assert trigger.duration_frames == int(round(config.sample_rate * 0.020))
    assert hit.duration_frames > trigger.duration_frames * 10
    assert np.max(np.abs(result.stems["kick"])) > 0.05
    assert np.isfinite(result.stems["kick"]).all()


def test_break_slices_trim_to_next_score_trigger_and_fade_on_absolute_frames(tmp_path: Path):
    break_sample = tmp_path / "imported-break.wav"
    _write_sample(break_sample, seconds=1.0, frequency=97.0)
    break_metadata = {
        "provider": "IRO",
        "pack": "sound-fx-211",
        "family": "break_loop",
        "articulation": "loop",
        "relative_path": "loops/break.wav",
    }
    config = GenerationConfig(
        bpm=120.0,
        duration=5.0,
        sample_rate=22_050,
        seed="m17.3-break-slices",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        sample_paths={"break": str(break_sample)},
        sample_metadata={"break": break_metadata},
        break_slice_count=4,
    )
    score = _score({
        "break": [_hit("break", 0, "kick"), _hit("break", 4, "snare")],
    })

    result = ReawarpEngine().render_score(score, config=config)
    slices = sorted(
        (item for item in result.schedule if item.event.voice_id == "sample_break"),
        key=lambda item: item.start_frame,
    )
    assert len(slices) == 2
    assert slices[0].start_frame == 0
    assert slices[1].start_frame == 11_025
    assert slices[0].end_frame == slices[1].start_frame
    assert slices[0].duration_frames == 11_025
    assert slices[0].event.parameters["sample_metadata"] == break_metadata
    assert slices[0].event.parameters["break_source_frame_end"] > slices[0].event.parameters["break_source_frame_start"]
    assert result.stems["sample_break"].shape == (config.frame_count, 2)
    assert np.isfinite(result.stems["sample_break"]).all()
    assert np.max(np.abs(result.stems["sample_break"])) > 0.01
    # The two-millisecond edge fade is applied to the slice buffer, not after
    # the whole stem is assembled.
    assert np.max(np.abs(result.stems["sample_break"][0])) < 1e-6



def test_feature_guided_hybrid_keeps_sample_driven_voice_and_pitch_adaptation(tmp_path: Path):
    sample = tmp_path / "feature-guided.wav"
    _write_sample(sample, seconds=0.40, frequency=380.0)
    features = {
        "spectral_centroid_hz": 8_000.0,
        "spectral_flatness": 0.48,
        "onset_density_per_second": 9.0,
        "crest_factor_db": 12.0,
    }
    config = GenerationConfig(
        bpm=120.0,
        duration=5.0,
        sample_rate=22_050,
        seed="m17.3-feature-guided",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        percussion_source_mode="hybrid",
        percussion_hybrid_architecture="feature_guided",
        sample_banks={"kick": (_sample_entry(sample, "guided-kick", features=features),)},
    )
    result = ReawarpEngine().render_score(_score({"kick": [_hit("kick", 0)]}), config=config)
    hit = next(item for item in result.schedule if item.event.kind == "hit")
    trigger = next(item for item in result.schedule if item.event.kind == "trigger")

    assert hit.event.parameters["synthesis_voice"] == "dry_thump"
    assert hit.event.parameters["synthesis_pitch_ratio"] > 1.0
    assert hit.event.parameters["synthesis_guidance"]["spectral_centroid_hz"] == 8_000.0
    expected_transient_ms = 28.0 * (0.72 + 12.0 / 35.0)
    assert trigger.duration_frames == int(round(config.sample_rate * expected_transient_ms / 1000.0))
    assert np.isfinite(result.stems["kick"]).all()
    assert np.max(np.abs(result.stems["kick"])) > 0.05
