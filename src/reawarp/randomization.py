"""Seeded, reproducible randomisation of Reawarp generator configurations."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from reawarp import GenerationConfig
from reawarp.composition.director import STRUCTURES
from reawarp.composition.patterns import PATTERN_FAMILIES, PATTERN_RELATIONSHIPS
from reawarp.mathematics.theory import SCALE_STEPS
from reawarp.synthesis.profiles import (
    HAT_PROFILES, KICK_PROFILES, MELODY_PROFILES, SNARE_PROFILES, SYNTH_PALETTES,
)
from reawarp.transforms.pipeline import BREAK_TRANSFORMS


def random_generation_config(
    base: GenerationConfig,
    *,
    seed: int | str | None = None,
) -> GenerationConfig:
    """Randomise every generative setting while preserving BPM, duration and assets.

    The seed drives a local NumPy generator, so a given seed produces the same
    complete configuration. Sample paths, metadata, sample banks and sample
    rate are preserved: randomisation changes how available material is used,
    not which external files exist or the project's technical clock.
    """
    if not isinstance(base, GenerationConfig):
        raise TypeError("base must be a GenerationConfig")
    actual_seed = base.seed if seed is None else seed
    rng = np.random.default_rng(
        int(actual_seed) if str(actual_seed).lstrip("-+").isdigit()
        else int.from_bytes(str(actual_seed).encode("utf-8")[:8].ljust(8, b"\0"), "little")
    )

    def unit(low: float = 0.05, high: float = 0.95) -> float:
        return float(rng.uniform(low, high))

    def choose(values):
        values = tuple(values)
        return values[int(rng.integers(0, len(values)))]

    transform_count = int(rng.integers(2, len(BREAK_TRANSFORMS) + 1))
    transforms = tuple(
        str(item) for item in rng.choice(
            np.asarray(BREAK_TRANSFORMS, dtype=object),
            size=transform_count,
            replace=False,
        ).tolist()
    )
    return replace(
        base,
        seed=actual_seed,
        structure=choose(STRUCTURES),
        composition_flow=choose(("preset", "mix", "mutate")),
        pattern_family=choose(PATTERN_FAMILIES),
        pattern_relationship=choose(PATTERN_RELATIONSHIPS),
        pattern_follow_structure=bool(rng.integers(0, 2)),
        drum_change_intensity=unit(0.15, 1.0),
        drum_part_cycle_bars=choose((1, 2, 4)),
        composition_energy=unit(0.15, 0.95),
        composition_variation=unit(0.15, 0.95),
        arrangement_density=unit(0.15, 0.95),
        rhythmic_syncopation=unit(0.15, 0.95),
        arrangement_instability=unit(0.10, 0.95),
        melodic_activity=unit(0.10, 0.95),
        melody_register_semitones=int(rng.integers(-18, 19)),
        tonal_brightness=unit(0.08, 0.95),
        spatial_intent=unit(0.08, 0.95),
        complexity=unit(0.15, 0.98),
        include_melody=bool(rng.integers(0, 2)),
        include_texture=bool(rng.integers(0, 2)),
        include_ambience=bool(rng.integers(0, 2)),
        ambience_level=unit(0.02, 0.50),
        drum_sample_automation=choose(("fixed", "section", "cycle", "automatic")),
        kick_profile=choose(("auto", *KICK_PROFILES)),
        snare_profile=choose(("auto", *SNARE_PROFILES)),
        hat_profile=choose(("auto", *HAT_PROFILES)),
        melody_profile=choose(("auto", *MELODY_PROFILES)),
        synth_palette=choose(SYNTH_PALETTES),
        percussion_synthesis=choose(("minimal", "extended", "samples")),
        percussion_source_mode=choose(("automatic", "synth", "sample", "hybrid")),
        percussion_hybrid_architecture=choose(("transient_body", "layered", "feature_guided")),
        percussion_sample_mix=unit(0.1, 0.9),
        hybrid_transient_ms=float(rng.uniform(5.0, 120.0)),
        melody_scale=choose(SCALE_STEPS),
        melody_root=int(rng.integers(0, 12)),
        break_style=choose(("auto", "broken_funk", "half_time", "straight", "sparse")),
        break_density=unit(0.08, 0.95),
        break_variation=unit(0.05, 0.95),
        break_cycle_bars=choose((1, 2, 4)),
        break_transforms=transforms,
        break_slice_count=int(rng.integers(4, 65)),
        break_stutter_repeats=int(rng.integers(2, 13)),
        break_dropout_probability=float(rng.uniform(0.0, 0.55)),
        break_pitch_semitones=float(rng.uniform(-12.0, 12.0)),
        break_time_stretch=float(rng.uniform(0.65, 1.6)),
        break_gate_rate_hz=float(rng.uniform(1.0, 24.0)),
        break_gate_duty=float(rng.uniform(0.12, 0.92)),
        break_grain_size_ms=float(rng.uniform(15.0, 300.0)),
        break_grain_density=float(rng.uniform(0.35, 3.75)),
        break_spectral_freeze_position=unit(0.0, 1.0),
    )
