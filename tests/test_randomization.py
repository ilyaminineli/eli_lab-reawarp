from __future__ import annotations

from dataclasses import asdict

import pytest

from reawarp import GenerationConfig
from reawarp.randomization import random_generation_config


def test_random_generation_config_preserves_bpm_duration_and_assets() -> None:
    base = GenerationConfig(
        bpm=123.5,
        duration=47.25,
        sample_rate=44_100,
        seed=10,
        sample_paths={"kick": "samples/kick.wav"},
        sample_metadata={"kick": {"role": "kick"}},
        sample_banks={
            "kick": ({"path": "samples/kick.wav", "metadata": {}, "features": {}},)
        },
    )
    changed = random_generation_config(base, seed=20261126)

    assert changed.bpm == base.bpm
    assert changed.duration == base.duration
    assert changed.sample_rate == base.sample_rate
    assert changed.sample_paths == base.sample_paths
    assert changed.sample_metadata == base.sample_metadata
    assert changed.sample_banks == base.sample_banks
    assert changed.seed == 20261126


def test_random_generation_config_is_deterministic_for_same_seed() -> None:
    base = GenerationConfig(bpm=137.0, duration=32.0, seed=4)
    first = random_generation_config(base, seed=20261126)
    second = random_generation_config(base, seed=20261126)

    assert asdict(first) == asdict(second)


def test_random_generation_config_changes_non_invariant_settings() -> None:
    base = GenerationConfig(bpm=137.0, duration=32.0, seed=4)
    changed = random_generation_config(base, seed=20261126)

    assert changed.bpm == 137.0
    assert changed.duration == 32.0
    assert changed.seed == 20261126
    assert changed != base


def test_random_generation_config_outputs_validated_bounds() -> None:
    base = GenerationConfig()
    for seed in range(40):
        config = random_generation_config(base, seed=seed)
        # Constructing GenerationConfig performs the complete field validation.
        assert 0.0 <= config.break_spectral_freeze_position <= 1.0
        assert 5.0 <= config.hybrid_transient_ms <= 200.0
        assert 0.25 <= config.break_grain_density <= 4.0
        assert 0.25 <= config.break_time_stretch <= 4.0
        assert 2 <= config.break_slice_count <= 128
        assert len(config.break_transforms) >= 2
