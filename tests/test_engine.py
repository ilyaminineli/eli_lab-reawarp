import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.core.random_streams import RandomStreams


def small_config(**overrides):
    values = dict(bpm=137, duration=5.0, sample_rate=22_050, seed=211, complexity=0.62)
    values.update(overrides)
    return GenerationConfig(**values)


def test_render_has_expected_stems_and_exact_frame_count():
    project = ReawarpEngine().generate(small_config())
    assert project.frame_count == 5 * 22_050
    assert set(("kick", "snare", "hats", "synthetic_break", "melody", "noise_texture")).issubset(project.stems)
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
