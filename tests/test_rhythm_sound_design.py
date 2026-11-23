"""Regression tests for Reawarp's rhythmic break grammar and new sound palette."""

from __future__ import annotations

import numpy as np

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.core.random_streams import RandomStreams
from reawarp.generators.percussion import build_percussion_events
from reawarp.synthesis.ambience import render_ambience
from reawarp.synthesis.instruments import render_fm_note
from reawarp.synthesis.profiles import MELODY_PROFILES


def _break_events(config: GenerationConfig):
    streams = RandomStreams(config.seed)
    return build_percussion_events(config, {
        "kick": streams.get("kick_pattern"),
        "snare": streams.get("snare_pattern"),
        "hat": streams.get("hat_pattern"),
        "break": streams.get("break_pattern"),
    })["break"]


def test_break_density_sets_bounded_hits_per_bar_and_is_grid_locked():
    expected_counts = {0.0: 4, 0.5: 6, 1.0: 8}
    for density, expected in expected_counts.items():
        config = GenerationConfig(
            bpm=120,
            duration=8.0,
            sample_rate=22_050,
            seed=741,
            break_density=density,
            break_variation=0.0,
            break_cycle_bars=4,
        )
        events = _break_events(config)
        grouped: dict[int, list] = {}
        for event in events:
            grouped.setdefault(event.step // 16, []).append(event)
            assert event.step % 1 == 0
            assert event.time == event.step * config.sixteenth_seconds
        assert len(grouped) == 4
        assert all(len(bar_events) == expected for bar_events in grouped.values())


def test_break_pattern_repeats_then_mutates_only_at_phrase_boundaries():
    config = GenerationConfig(
        bpm=120,
        duration=8.0,
        sample_rate=22_050,
        seed=913,
        break_density=0.5,
        break_variation=0.0,
        break_cycle_bars=2,
    )
    stable = _break_events(config)
    by_bar = {
        bar: [event.step % 16 for event in stable if event.step // 16 == bar]
        for bar in range(4)
    }
    assert by_bar[0] == by_bar[1] == by_bar[2] == by_bar[3]

    varied = _break_events(GenerationConfig(
        bpm=120,
        duration=8.0,
        sample_rate=22_050,
        seed=913,
        break_density=0.5,
        break_variation=1.0,
        break_cycle_bars=2,
    ))
    varied_by_bar = {
        bar: [event.step % 16 for event in varied if event.step // 16 == bar]
        for bar in range(4)
    }
    assert varied_by_bar[0] == varied_by_bar[2]
    assert varied_by_bar[1] != varied_by_bar[0]
    assert varied_by_bar[3] != varied_by_bar[2]
    for bar in range(4):
        assert {0, 4, 8, 12}.issubset(set(varied_by_bar[bar]))
        assert len(varied_by_bar[bar]) <= 8


def test_break_generation_is_deterministic_for_same_seed_and_settings():
    config = GenerationConfig(
        bpm=131,
        duration=8.0,
        sample_rate=22_050,
        seed="phrase-test",
        break_style="auto",
        break_density=0.62,
        break_variation=0.75,
        break_cycle_bars=2,
    )
    first = [event.to_dict() for event in _break_events(config)]
    second = [event.to_dict() for event in _break_events(config)]
    assert first == second


def test_profiled_melody_voices_are_finite_reproducible_and_distinct():
    renders = {}
    for name, profile in MELODY_PROFILES.items():
        first = render_fm_note(
            220.0, 22_050, np.random.default_rng(99),
            duration=0.25, velocity=0.7, profile=name,
        )
        second = render_fm_note(
            220.0, 22_050, np.random.default_rng(99),
            duration=0.25, velocity=0.7, profile=name,
        )
        assert np.array_equal(first, second)
        assert len(first) >= int(22_050 * (0.25 + profile.release)) - 1
        assert np.all(np.isfinite(first))
        assert float(np.max(np.abs(first))) > 0.01
        renders[name] = first
    assert not np.array_equal(renders["soft_keys"][:4_000], renders["glass_bell"][:4_000])


def test_ambience_is_stereo_smooth_and_seed_reproducible():
    sample_rate = 22_050
    first = render_ambience(
        sample_rate * 4, sample_rate, np.random.default_rng(55),
        root_frequency=130.81, amount=0.16,
    )
    second = render_ambience(
        sample_rate * 4, sample_rate, np.random.default_rng(55),
        root_frequency=130.81, amount=0.16,
    )
    assert first.shape == (sample_rate * 4, 2)
    assert np.array_equal(first, second)
    assert np.all(np.isfinite(first))
    assert float(np.max(np.abs(first))) < 0.5
    assert not np.array_equal(first[:, 0], first[:, 1])


def test_default_project_has_audible_ambience_and_break_provenance():
    project = ReawarpEngine().generate(GenerationConfig(
        duration=5.0, sample_rate=22_050, seed=211
    ))
    assert "ambience" in project.stems
    assert np.max(np.abs(project.stems["ambience"])) > 0.001
    assert project.metadata["break_rhythm"]["grid"].startswith("16-step")
    assert project.metadata["synthesis_profiles"]["melody"] in MELODY_PROFILES



def test_auto_timbres_remain_coherent_within_each_lane():
    project = ReawarpEngine().generate(GenerationConfig(
        duration=5.0, sample_rate=22_050, seed=518
    ))
    for lane in ("kick", "snare", "hat"):
        selected = {
            event["sound_profile"]
            for event in project.events
            if event.get("lane") == lane
        }
        assert len(selected) == 1
    for voice in ("kick", "snare", "hat"):
        selected = {
            event["sound_profile"]
            for event in project.events
            if event.get("lane") == "break" and event.get("kind") == voice
        }
        assert len(selected) <= 1
