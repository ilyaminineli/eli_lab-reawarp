import numpy as np

from reawarp import GenerationConfig, ReawarpEngine


def test_small_render_is_repeatable_finite_and_stem_aligned():
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m14-small-fixture",
        complexity=0.35,
        include_texture=False,
    )
    engine = ReawarpEngine()

    first = engine.generate(config)
    second = engine.generate(config)

    assert first.stems.keys() == second.stems.keys()
    assert first.frame_count == config.frame_count
    assert first.duration == 5.0
    assert first.events == second.events
    for name, audio in first.stems.items():
        assert audio.shape == (config.frame_count, 2)
        assert np.isfinite(audio).all()
        np.testing.assert_array_equal(audio, second.stems[name])


def test_stem_regeneration_keeps_unrelated_stems_bit_identical():
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m14-stem-isolation",
        complexity=0.35,
        include_texture=False,
    )
    engine = ReawarpEngine()
    base = engine.generate(config)
    varied = engine.generate_variant(config, "kick", 1, base_project=base)

    assert set(varied.stems) == set(base.stems)
    for name in base.stems:
        if name != "kick":
            np.testing.assert_array_equal(varied.stems[name], base.stems[name])
