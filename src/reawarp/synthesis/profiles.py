"""Named synthesis profiles for Reawarp's percussion instruments.

Profiles are data, not separate renderer implementations. Each profile exposes
its envelope and oscillator/noise characteristics for reproducible sound design.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KickProfile:
    start_frequency: float
    end_frequency: float
    pitch_decay: float
    amp_decay: float
    distortion: float
    sub_gain: float
    sub_decay: float
    click_gain: float
    click_decay: float


@dataclass(frozen=True, slots=True)
class SnareProfile:
    noise_gain: float
    body_gain: float
    noise_decay: float
    body_decay: float
    body_frequency: float
    body_sweep: float
    noise_highpass: float
    drive: float


@dataclass(frozen=True, slots=True)
class HatProfile:
    noise_gain: float
    metallic_gain: float
    decay: float
    highpass: float
    partials: tuple[tuple[float, float], ...]
    drive: float


@dataclass(frozen=True, slots=True)
class MelodyProfile:
    """A soft additive/FM voice definition; values are stable preset data."""

    partials: tuple[tuple[float, float], ...]
    attack: float
    decay: float
    sustain: float
    release: float
    fm_ratio: float
    fm_index: float
    detune_cents: float
    lowpass_hz: float
    drive: float


KICK_PROFILES: dict[str, KickProfile] = {
    "deep_sub": KickProfile(112, 36, 0.055, 0.34, 1.35, 0.42, 0.48, 0.045, 0.005),
    "909_punch": KickProfile(155, 43, 0.035, 0.23, 1.70, 0.24, 0.31, 0.10, 0.0038),
    "hard_click": KickProfile(188, 48, 0.022, 0.19, 2.15, 0.16, 0.24, 0.22, 0.0022),
    "soft_round": KickProfile(128, 48, 0.070, 0.30, 1.10, 0.30, 0.40, 0.025, 0.007),
    "rubber": KickProfile(205, 55, 0.095, 0.24, 2.0, 0.12, 0.30, 0.035, 0.004),
    "fm_bass": KickProfile(92, 31, 0.14, 0.42, 2.6, 0.34, 0.55, 0.035, 0.006),
    "laser": KickProfile(310, 42, 0.018, 0.20, 2.8, 0.10, 0.22, 0.08, 0.002),
    "wooden": KickProfile(175, 62, 0.025, 0.13, 1.25, 0.12, 0.17, 0.14, 0.003),
    "industrial": KickProfile(145, 39, 0.048, 0.37, 3.2, 0.27, 0.42, 0.16, 0.008),
    "distorted": KickProfile(165, 46, 0.030, 0.28, 5.0, 0.20, 0.34, 0.13, 0.004),
    "short_pluck": KickProfile(220, 58, 0.016, 0.095, 1.8, 0.09, 0.12, 0.09, 0.0018),
    "long_tail": KickProfile(118, 34, 0.085, 0.52, 1.5, 0.38, 0.62, 0.055, 0.005),
    "broken_digital": KickProfile(265, 52, 0.012, 0.16, 4.0, 0.08, 0.20, 0.19, 0.0015),
}

SNARE_PROFILES: dict[str, SnareProfile] = {
    "acoustic": SnareProfile(0.70, 0.34, 0.125, 0.075, 185, 30, 0.92, 1.25),
    "909_crack": SnareProfile(0.78, 0.31, 0.105, 0.065, 178, 38, 0.94, 1.35),
    "noise_burst": SnareProfile(1.00, 0.08, 0.075, 0.035, 240, 12, 0.965, 1.15),
    "tonal": SnareProfile(0.42, 0.70, 0.085, 0.115, 205, 62, 0.90, 1.45),
    "industrial": SnareProfile(0.88, 0.48, 0.18, 0.095, 132, 48, 0.985, 2.2),
    "soft_brush": SnareProfile(0.55, 0.18, 0.21, 0.12, 260, 18, 0.84, 1.05),
}

HAT_PROFILES: dict[str, HatProfile] = {
    "closed": HatProfile(
        0.62,
        0.38,
        0.022,
        0.975,
        ((463, 0.25), (701, 0.19), (1139, 0.16), (1777, 0.12)),
        1.1,
    ),
    "open": HatProfile(
        0.58,
        0.42,
        0.115,
        0.965,
        ((463, 0.22), (701, 0.18), (1139, 0.16), (1777, 0.13), (2633, 0.10)),
        1.15,
    ),
    "metallic": HatProfile(
        0.28,
        0.72,
        0.055,
        0.982,
        ((401, 0.28), (617, 0.24), (997, 0.21), (1601, 0.18), (2477, 0.14)),
        1.45,
    ),
    "digital": HatProfile(
        0.72,
        0.28,
        0.035,
        0.995,
        ((523, 0.18), (1047, 0.16), (2093, 0.14), (3136, 0.12)),
        2.2,
    ),
    "noisy": HatProfile(0.92, 0.08, 0.045, 0.91, ((881, 0.08), (1760, 0.06)), 1.05),
    "dark": HatProfile(
        0.68,
        0.32,
        0.075,
        0.90,
        ((330, 0.24), (494, 0.18), (740, 0.14), (1110, 0.10)),
        1.25,
    ),
}

MELODY_PROFILES: dict[str, MelodyProfile] = {
    "soft_keys": MelodyProfile(
        ((1.0, 0.72), (2.0, 0.22), (3.0, 0.075), (4.0, 0.025)),
        0.012,
        0.16,
        0.42,
        0.13,
        1.50,
        0.42,
        1.8,
        6_500.0,
        1.04,
    ),
    "glass_bell": MelodyProfile(
        ((1.0, 0.62), (2.01, 0.25), (3.98, 0.12), (6.01, 0.045)),
        0.003,
        0.46,
        0.20,
        0.26,
        2.35,
        0.78,
        0.7,
        10_500.0,
        1.00,
    ),
    "soft_pluck": MelodyProfile(
        ((1.0, 0.78), (2.0, 0.18), (3.0, 0.045)),
        0.004,
        0.12,
        0.18,
        0.09,
        1.08,
        0.26,
        2.6,
        5_500.0,
        1.06,
    ),
    "reed_pad": MelodyProfile(
        ((1.0, 0.72), (2.0, 0.34), (3.0, 0.16), (4.0, 0.055), (5.0, 0.018)),
        0.045,
        0.28,
        0.68,
        0.30,
        0.52,
        0.34,
        3.2,
        4_800.0,
        1.02,
    ),
    "wood_mallet": MelodyProfile(
        ((1.0, 0.72), (2.7, 0.18), (4.2, 0.075), (6.8, 0.025)),
        0.003,
        0.24,
        0.16,
        0.18,
        1.92,
        0.58,
        0.5,
        8_200.0,
        1.00,
    ),
    "inharmonic_mallet": MelodyProfile(
        ((1.0, 0.62), (2.76, 0.27), (5.41, 0.14), (8.93, 0.07)),
        0.002,
        0.38,
        0.12,
        0.42,
        2.71,
        0.92,
        0.4,
        11_500.0,
        1.35,
    ),
    "metallic_fm": MelodyProfile(
        ((1.0, 0.58), (1.414, 0.23), (2.718, 0.12), (4.07, 0.06)),
        0.001,
        0.22,
        0.16,
        0.34,
        2.73,
        1.25,
        1.1,
        12_000.0,
        1.8,
    ),
    "dark_formant": MelodyProfile(
        ((1.0, 0.66), (1.48, 0.21), (2.25, 0.12), (3.4, 0.05)),
        0.018,
        0.20,
        0.52,
        0.22,
        0.71,
        0.48,
        4.2,
        3_200.0,
        1.25,
    ),
    "soft_spectral_pad": MelodyProfile(
        ((1.0, 0.58), (1.997, 0.22), (3.01, 0.12), (4.98, 0.06), (6.03, 0.03)),
        0.12,
        0.35,
        0.76,
        0.65,
        0.50,
        0.28,
        6.0,
        5_200.0,
        1.02,
    ),
}

# Automatic mode favours controlled, mix-friendly voices. More aggressive
# profiles remain available explicitly rather than appearing unpredictably.

# Extended sound-object palette. Renderer selection is explicit and deterministic.
SYNTH_PALETTES = (
    "subtractive",
    "hybrid",
    "fm",
    "additive",
    "modal",
    "inharmonic",
    "wavetable",
    "granular",
    "physical",
)

# Each voice is a compact, serialisable recipe: its oscillator family, spectral
# character and temporal envelope. These remain data-driven profiles.
EXTENDED_MELODY_PROFILES: dict[str, MelodyProfile] = {
    "inharmonic_mallet": MelodyProfile(
        ((1.0, 0.62), (2.76, 0.27), (5.41, 0.14), (8.93, 0.07)),
        0.002,
        0.38,
        0.12,
        0.42,
        2.71,
        0.92,
        0.4,
        11_500.0,
        1.35,
    ),
    "metallic_fm": MelodyProfile(
        ((1.0, 0.58), (1.414, 0.23), (2.718, 0.12), (4.07, 0.06)),
        0.001,
        0.22,
        0.16,
        0.34,
        2.73,
        1.25,
        1.1,
        12_000.0,
        1.8,
    ),
    "dark_formant": MelodyProfile(
        ((1.0, 0.66), (1.48, 0.21), (2.25, 0.12), (3.4, 0.05)),
        0.018,
        0.20,
        0.52,
        0.22,
        0.71,
        0.48,
        4.2,
        3_200.0,
        1.25,
    ),
    "soft_spectral_pad": MelodyProfile(
        ((1.0, 0.58), (1.997, 0.22), (3.01, 0.12), (4.98, 0.06), (6.03, 0.03)),
        0.12,
        0.35,
        0.76,
        0.65,
        0.50,
        0.28,
        6.0,
        5_200.0,
        1.02,
    ),
}


# M9 role-driven minimal voices. Profiles describe sound-object behaviour rather
# than genre labels: short transients, sparse partials, restrained decay and
# explicit identity. These are separate from the legacy FM profile catalogue.
@dataclass(frozen=True, slots=True)
class PercussionVoiceProfile:
    body_hz: float
    body_decay: float
    transient_gain: float
    transient_decay: float
    noise_gain: float
    tail_gain: float
    tail_decay: float
    inharmonicity: float = 0.0


@dataclass(frozen=True, slots=True)
class SubtractiveVoiceProfile:
    harmonics: tuple[float, ...]
    cutoff_ratio: float
    resonance: float
    attack: float
    decay: float
    sustain: float
    release: float
    filter_env_amount: float
    drift_cents: float = 0.0


SUBTRACTIVE_VOICES: dict[str, SubtractiveVoiceProfile] = {
    "soft_reed": SubtractiveVoiceProfile(
        (1.0, 0.24, 0.09, 0.035), 5.0, 0.12, 0.018, 0.28, 0.42, 0.24, 0.18, 0.7
    ),
    "dry_pluck": SubtractiveVoiceProfile(
        (1.0, 0.38, 0.12, 0.035, 0.01), 8.0, 0.08, 0.002, 0.14, 0.10, 0.08, 0.38, 0.15
    ),
    "dark_pulse": SubtractiveVoiceProfile(
        (1.0, 0.28, 0.19, 0.08, 0.03), 3.2, 0.22, 0.006, 0.22, 0.24, 0.16, 0.22, 0.25
    ),
    "thin_bass": SubtractiveVoiceProfile(
        (1.0, 0.18, 0.045), 2.6, 0.06, 0.004, 0.20, 0.28, 0.12, 0.16, 0.1
    ),
}

PERCUSSION_VOICES: dict[str, PercussionVoiceProfile] = {
    "dry_thump": PercussionVoiceProfile(
        68.0, 0.105, 0.55, 0.003, 0.025, 0.0, 0.02, 0.0
    ),
    "soft_kick": PercussionVoiceProfile(
        55.0, 0.155, 0.28, 0.004, 0.015, 0.0, 0.02, 0.0
    ),
    "wood_tap": PercussionVoiceProfile(
        185.0, 0.055, 0.72, 0.0018, 0.025, 0.03, 0.035, 0.12
    ),
    "paper_snare": PercussionVoiceProfile(
        175.0, 0.065, 0.32, 0.002, 0.22, 0.08, 0.055, 0.08
    ),
    "metal_tick": PercussionVoiceProfile(
        620.0, 0.085, 0.52, 0.0012, 0.045, 0.18, 0.16, 0.62
    ),
    "glass_ping": PercussionVoiceProfile(
        880.0, 0.24, 0.35, 0.001, 0.0, 0.42, 0.32, 0.74
    ),
    "muted_rim": PercussionVoiceProfile(
        930.0, 0.028, 0.58, 0.0008, 0.01, 0.0, 0.015, 0.3
    ),
    "noise_hat": PercussionVoiceProfile(0.0, 0.035, 0.0, 0.0008, 0.20, 0.0, 0.04, 0.0),
}

AUTO_KICK_PROFILES = (
    "deep_sub",
    "909_punch",
    "soft_round",
    "rubber",
    "wooden",
    "long_tail",
)
AUTO_SNARE_PROFILES = ("acoustic", "909_crack", "tonal", "soft_brush")
AUTO_HAT_PROFILES = ("closed", "open", "dark")
AUTO_MELODY_PROFILES = ("dry_pluck", "soft_reed", "thin_bass")


def select_profile_name(
    profile: str,
    catalog: dict,
    rng,
    *,
    auto_choices: tuple[str, ...] | None = None,
) -> str:
    """Resolve a named profile or select one deterministically for automatic mode."""
    if profile == "auto":
        choices = auto_choices or tuple(catalog)
        return str(rng.choice(choices))
    if profile not in catalog:
        raise ValueError(
            f"unknown profile {profile!r}; choose one of: {', '.join(catalog)}"
        )
    return profile
