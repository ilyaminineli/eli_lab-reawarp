import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.core.random_streams import RandomStreams
from reawarp.export.wav import write_wav


def small_config(**overrides):
    values = dict(bpm=137, duration=5.0, sample_rate=22_050, seed=211, complexity=0.62)
    values.update(overrides)
    return GenerationConfig(**values)


def test_render_has_expected_stems_and_exact_frame_count():
    project = ReawarpEngine().generate(small_config())
    assert project.frame_count == 5 * 22_050
    assert set((
        "kick", "snare", "hats", "synthetic_break", "melody", "noise_texture", "ambience"
    )).issubset(project.stems)
    assert all(stem.shape == (project.frame_count, 2) for stem in project.stems.values())
    assert all(stem.dtype == np.float32 for stem in project.stems.values())


def test_render_is_deterministic():
    engine = ReawarpEngine()
    first = engine.generate(small_config())
    second = engine.generate(small_config())
    assert first.stems.keys() == second.stems.keys()
    for key in first.stems:
        assert np.array_equal(first.stems[key], second.stems[key]), key
    assert first.events == second.events


def test_independent_random_streams_do_not_depend_on_call_order():
    a = RandomStreams(211)
    expected = a.get("kick").random(32)
    b = RandomStreams(211)
    b.get("snare").random(1000)
    actual = b.get("kick").random(32)
    assert np.array_equal(expected, actual)


def test_repeated_event_times_are_inside_requested_duration():
    project = ReawarpEngine().generate(small_config())
    for event in project.events:
        if "time" in event:
            assert 0.0 <= event["time"] < 5.0


def test_config_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        GenerationConfig(duration=2.0)
    with pytest.raises(ValueError):
        GenerationConfig(bpm=300)
    with pytest.raises(ValueError):
        GenerationConfig(complexity=1.5)


def test_master_is_finite_and_bounded():
    master = ReawarpEngine().generate(small_config()).render_master()
    assert np.all(np.isfinite(master))
    assert np.max(np.abs(master)) <= 1.0


def test_regenerating_one_stem_preserves_other_stems():
    engine = ReawarpEngine()
    config = small_config()
    original = engine.generate(config)
    variant = engine.generate_variant(config, "kick", variation=2)
    assert not np.array_equal(original.stems["kick"], variant.stems["kick"])
    for name in original.stems:
        if name != "kick":
            assert np.array_equal(original.stems[name], variant.stems[name]), name
    assert variant.metadata["variation"] == {"stem": "kick", "index": 2}


def test_unknown_stem_variant_is_rejected():
    with pytest.raises(ValueError):
        ReawarpEngine().generate_variant(small_config(), "master", variation=1)


def test_regenerating_procedural_lane_keeps_imported_sample_overlays_identical(tmp_path):
    sample = np.sin(np.linspace(0.0, 16.0 * np.pi, 1024)).astype(np.float32) * 0.4
    kick_path = write_wav(tmp_path / "kick.wav", sample, 22_050, 16)
    break_path = write_wav(tmp_path / "break.wav", sample, 22_050, 16)
    config = small_config(sample_paths={
        "kick": str(kick_path),
        "break": str(break_path),
    })
    engine = ReawarpEngine()
    original = engine.generate(config)

    kick_variant = engine.generate_variant(config, "kick", variation=3)
    assert not np.array_equal(original.stems["kick"], kick_variant.stems["kick"])
    for name in original.stems:
        if name != "kick":
            assert np.array_equal(original.stems[name], kick_variant.stems[name]), name

    break_variant = engine.generate_variant(config, "synthetic_break", variation=2)
    assert not np.array_equal(
        original.stems["synthetic_break"], break_variant.stems["synthetic_break"]
    )
    for name in original.stems:
        if name != "synthetic_break":
            assert np.array_equal(original.stems[name], break_variant.stems[name]), name


def test_ambience_regeneration_changes_only_its_own_stem():
    engine = ReawarpEngine()
    config = small_config()
    original = engine.generate(config)
    variant = engine.generate_variant(config, "ambience", variation=2)
    assert not np.array_equal(original.stems["ambience"], variant.stems["ambience"])
    for name in original.stems:
        if name != "ambience":
            assert np.array_equal(original.stems[name], variant.stems[name]), name


def test_ambience_can_be_disabled_without_changing_other_stems():
    project = ReawarpEngine().generate(small_config(include_ambience=False))
    assert "ambience" not in project.stems
    assert "melody" in project.stems
    assert "noise_texture" in project.stems


def test_melody_regeneration_does_not_change_ambience_or_other_stems():
    engine = ReawarpEngine()
    config = small_config()
    original = engine.generate(config)
    variant = engine.generate_variant(config, "melody", variation=4)
    assert not np.array_equal(original.stems["melody"], variant.stems["melody"])
    for name in original.stems:
        if name != "melody":
            assert np.array_equal(original.stems[name], variant.stems[name]), name


def test_sample_layer_regeneration_is_independent_and_mergeable(tmp_path):
    sample = np.sin(np.linspace(0.0, 12.0 * np.pi, 2048)).astype(np.float32) * 0.35
    sample_path = write_wav(tmp_path / "kick.wav", sample, 22_050, 16)
    config = small_config(sample_paths={"kick": str(sample_path)})
    engine = ReawarpEngine()
    original = engine.generate(config)
    candidate = engine.generate_variant(config, "sample_kick", variation=2)
    merged = engine.generate_variant(
        config, "sample_kick", variation=2, base_project=original
    )
    assert not np.array_equal(original.stems["sample_kick"], candidate.stems["sample_kick"])
    for name in original.stems:
        if name != "sample_kick":
            assert np.array_equal(original.stems[name], merged.stems[name]), name
    assert np.array_equal(candidate.stems["sample_kick"], merged.stems["sample_kick"])
    assert merged.metadata["variation"] == {"stem": "sample_kick", "index": 2}
    assert merged.metadata["event_count"] == len(merged.events)
    assert merged.metadata["sample_sources"]["kick"]["trigger_count"] == sum(
        event.get("lane") == "sample_kick" for event in merged.events
    )


def test_engine_stores_seeded_composition_plan_and_respects_duration():
    config = small_config(duration=12.0, structure="episodic",
                          composition_energy=0.7, composition_variation=0.8)
    project = ReawarpEngine().generate(config)
    plan = project.metadata["composition_plan"]
    assert plan["structure"] == "episodic"
    assert plan["duration_seconds"] == pytest.approx(12.0)
    assert plan["sections"][0]["start_seconds"] == 0.0
    assert plan["sections"][-1]["end_seconds"] == pytest.approx(12.0)
    assert project.frame_count == 12 * 22_050



def test_engine_renders_three_minute_composition_with_new_form_and_palette():
    project = ReawarpEngine().generate(small_config(
        duration=180.0, structure="autechre_like", composition_flow="mutate",
        synth_palette="inharmonic",
    ))
    assert project.frame_count == 180 * 22_050
    plan = project.metadata["composition_plan"]
    assert plan["duration_seconds"] == pytest.approx(180.0)
    assert plan["flow"] == "mutate"
    assert plan["sections"][-1]["end_seconds"] == pytest.approx(180.0)
    assert project.metadata["synth_palette"] == "inharmonic"
    assert np.all(np.isfinite(project.stems["melody"]))
