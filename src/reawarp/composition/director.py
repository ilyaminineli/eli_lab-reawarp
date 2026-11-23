"""Deterministic section and phrase planning for composition-level generation."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class SectionPlan:
    index: int
    name: str
    start_seconds: float
    end_seconds: float
    energy: float
    density: float
    brightness: float
    instability: float
    space: float
    kick: bool
    melody: bool
    texture: bool
    ambience: bool
    motif_mode: str
    motif_register_semitones: int
    percussion_density_scale: float
    phrase_bars: int

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompositionPlan:
    duration_seconds: float
    bpm: float
    seed: int | str
    structure: str
    sections: tuple[SectionPlan, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "bpm": self.bpm,
            "seed": self.seed,
            "structure": self.structure,
            "sections": [section.to_dict() for section in self.sections],
        }


# name, relative duration weight, target energy, motif treatment
STRUCTURES: dict[str, tuple[tuple[str, float, float, str], ...]] = {
    "evolving": (
        ("INTRO", 0.13, 0.20, "fragment"),
        ("FOUNDATION", 0.24, 0.43, "present"),
        ("EXPANSION", 0.25, 0.69, "develop"),
        ("MUTATION", 0.18, 0.82, "fragment"),
        ("REASSEMBLY", 0.14, 0.56, "return"),
        ("OUTRO", 0.06, 0.12, "dissolve"),
    ),
    "additive": (
        ("INTRO", 0.16, 0.18, "fragment"),
        ("FOUNDATION", 0.22, 0.38, "present"),
        ("EXPANSION", 0.30, 0.62, "develop"),
        ("PEAK", 0.22, 0.84, "develop"),
        ("OUTRO", 0.10, 0.14, "dissolve"),
    ),
    "subtractive": (
        ("FULL", 0.22, 0.78, "present"),
        ("UNRAVEL", 0.28, 0.58, "fragment"),
        ("EXPOSE", 0.22, 0.34, "fragment"),
        ("RESIDUAL", 0.18, 0.18, "dissolve"),
        ("OUTRO", 0.10, 0.08, "dissolve"),
    ),
    "episodic": (
        ("SCENE_A", 0.22, 0.44, "present"),
        ("SUSPENSION", 0.14, 0.16, "fragment"),
        ("SCENE_B", 0.26, 0.72, "develop"),
        ("CONTRAST", 0.18, 0.35, "fragment"),
        ("REASSEMBLY", 0.20, 0.57, "return"),
    ),
    "drift": (
        ("ORIGIN", 0.20, 0.30, "present"),
        ("DRIFT_A", 0.20, 0.50, "develop"),
        ("DRIFT_B", 0.20, 0.66, "develop"),
        ("DRIFT_C", 0.20, 0.42, "fragment"),
        ("RETURN", 0.20, 0.52, "return"),
    ),
}


def _normalised_weights(template, rng: np.random.Generator, variation: float) -> np.ndarray:
    weights = np.asarray([item[1] for item in template], dtype=np.float64)
    if variation > 0.0 and len(weights) > 2:
        noise = rng.normal(0.0, 0.18 * variation, size=len(weights))
        noise -= np.mean(noise)
        weights *= np.exp(np.clip(noise, -0.35, 0.35))
    weights = np.maximum(weights, 0.07)
    return weights / np.sum(weights)


def build_composition_plan(
    *,
    duration_seconds: float,
    bpm: float,
    seed: int | str,
    structure: str = "evolving",
    energy: float = 0.62,
    variation: float = 0.45,
) -> CompositionPlan:
    """Create a seeded formal plan covering the exact requested duration."""
    if duration_seconds <= 0.0 or bpm <= 0.0:
        raise ValueError("duration_seconds and bpm must be positive")
    if structure not in STRUCTURES:
        raise ValueError(f"unknown structure: {structure}")
    if not 0.0 <= energy <= 1.0 or not 0.0 <= variation <= 1.0:
        raise ValueError("energy and variation must be between zero and one")

    seed_word = int.from_bytes(
        hashlib.blake2b(str(seed).encode("utf-8"), digest_size=4).digest(),
        "little",
    )
    rng = np.random.default_rng(np.random.SeedSequence([seed_word, 0x52454157]))
    template = STRUCTURES[structure]
    weights = _normalised_weights(template, rng, variation)
    bar_seconds = 240.0 / float(bpm)
    boundaries = np.concatenate(([0.0], np.cumsum(weights) * duration_seconds))
    boundaries[-1] = float(duration_seconds)
    sections: list[SectionPlan] = []

    for index, ((name, _weight, target_energy, motif_mode), start, end) in enumerate(
        zip(template, boundaries[:-1], boundaries[1:], strict=True)
    ):
        section_energy = float(np.clip(
            0.68 * target_energy + 0.32 * energy
            + rng.normal(0.0, 0.035 * variation),
            0.0, 1.0,
        ))
        density = float(np.clip(
            0.08 + 0.68 * section_energy
            + rng.normal(0.0, 0.035 * variation),
            0.04, 0.78,
        ))
        brightness = float(np.clip(
            0.16 + 0.69 * section_energy
            + rng.normal(0.0, 0.08 * variation),
            0.08, 0.92,
        ))
        instability = float(np.clip(
            0.08 + 0.56 * section_energy
            + rng.uniform(-0.12, 0.12) * variation,
            0.0, 0.78,
        ))
        space = float(np.clip(
            1.0 - 0.76 * density + rng.uniform(-0.08, 0.08) * variation,
            0.12, 1.0,
        ))

        upper_name = name.upper()
        is_outro = "OUTRO" in upper_name or "RESIDUAL" in upper_name
        is_suspension = "SUSPENSION" in upper_name or "EXPOSE" in upper_name
        is_intro = upper_name == "INTRO"
        kick = not (is_outro or is_suspension or is_intro)
        melody = not is_outro and motif_mode != "dissolve"
        texture = not is_outro
        ambience = True
        if is_suspension:
            kick = False
            melody = motif_mode == "present"

        phrase_bars = max(1, int(round(float(end - start) / bar_seconds)))
        register_shift = 0
        if variation > 0.05 and motif_mode in ("develop", "fragment"):
            register_shift = int(rng.choice((-12, -7, 0, 5, 12)))

        # Retain anchors but allocate less probability to supporting ornaments
        # as the section becomes denser.
        support_scale = float(np.clip(0.98 - 0.43 * density, 0.52, 0.96))
        if section_energy > 0.78 and density > 0.62:
            texture = bool(rng.random() < 0.35)

        sections.append(SectionPlan(
            index=index,
            name=name,
            start_seconds=float(start),
            end_seconds=float(end),
            energy=section_energy,
            density=density,
            brightness=brightness,
            instability=instability,
            space=space,
            kick=kick,
            melody=melody,
            texture=texture,
            ambience=ambience,
            motif_mode=motif_mode,
            motif_register_semitones=register_shift,
            percussion_density_scale=support_scale,
            phrase_bars=phrase_bars,
        ))

    return CompositionPlan(
        duration_seconds=float(duration_seconds),
        bpm=float(bpm),
        seed=seed,
        structure=structure,
        sections=tuple(sections),
    )


def section_for_time(plan: CompositionPlan, time_seconds: float) -> SectionPlan:
    """Return the containing section, clamping at the start and end."""
    if not plan.sections:
        raise ValueError("composition plan has no sections")
    value = float(time_seconds)
    for section in plan.sections:
        if section.start_seconds <= value < section.end_seconds:
            return section
    return plan.sections[0] if value < 0.0 else plan.sections[-1]
