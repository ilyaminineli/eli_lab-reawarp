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
    "closed": HatProfile(0.62, 0.38, 0.022, 0.975, ((463, 0.25), (701, 0.19), (1139, 0.16), (1777, 0.12)), 1.1),
    "open": HatProfile(0.58, 0.42, 0.115, 0.965, ((463, 0.22), (701, 0.18), (1139, 0.16), (1777, 0.13), (2633, 0.10)), 1.15),
    "metallic": HatProfile(0.28, 0.72, 0.055, 0.982, ((401, 0.28), (617, 0.24), (997, 0.21), (1601, 0.18), (2477, 0.14)), 1.45),
    "digital": HatProfile(0.72, 0.28, 0.035, 0.995, ((523, 0.18), (1047, 0.16), (2093, 0.14), (3136, 0.12)), 2.2),
    "noisy": HatProfile(0.92, 0.08, 0.045, 0.91, ((881, 0.08), (1760, 0.06)), 1.05),
    "dark": HatProfile(0.68, 0.32, 0.075, 0.90, ((330, 0.24), (494, 0.18), (740, 0.14), (1110, 0.10)), 1.25),
}


def select_profile_name(profile: str, catalog: dict, rng) -> str:
    """Resolve a named profile or select one deterministically for automatic mode."""
    if profile == "auto":
        return str(rng.choice(tuple(catalog)))
    if profile not in catalog:
        raise ValueError(f"unknown profile {profile!r}; choose one of: {', '.join(catalog)}")
    return profile
