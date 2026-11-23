"""Deterministic formal section planning for long-form IDM generation."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class SectionPlan:
    index: int
    name: str
    start_bar: int
    end_bar: int
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

    @property
    def phrase_bars(self) -> int:
        return self.end_bar - self.start_bar

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


# Name, relative duration, target energy, motif treatment.
STRUCTURES: dict[str, tuple[tuple[str, float, float, str], ...]] = {
    "evolving": (
        ("INTRO", .13, .20, "fragment"),
        ("FOUNDATION", .24, .43, "present"),
        ("EXPANSION", .25, .69, "develop"),
        ("MUTATION", .18, .82, "fragment"),
        ("REASSEMBLY", .14, .56, "return"),
        ("OUTRO", .06, .12, "dissolve"),
    ),
    "additive": (
        ("INTRO", .16, .18, "fragment"),
        ("FOUNDATION", .22, .38, "present"),
        ("EXPANSION", .30, .62, "develop"),
        ("PEAK", .22, .84, "develop"),
        ("OUTRO", .10, .14, "dissolve"),
    ),
    "subtractive": (
        ("FULL", .22, .78, "present"),
        ("UNRAVEL", .28, .58, "fragment"),
        ("EXPOSE", .22, .34, "fragment"),
        ("RESIDUAL", .18, .18, "dissolve"),
        ("OUTRO", .10, .08, "dissolve"),
    ),
    "episodic": (
        ("SCENE_A", .22, .44, "present"),
        ("SUSPENSION", .14, .16, "fragment"),
        ("SCENE_B", .26, .72, "develop"),
        ("CONTRAST", .18, .35, "fragment"),
        ("REASSEMBLY", .20, .57, "return"),
    ),
    "drift": (
        ("ORIGIN", .20, .30, "present"),
        ("DRIFT_A", .20, .50, "develop"),
        ("DRIFT_B", .20, .66, "develop"),
        ("DRIFT_C", .20, .42, "fragment"),
        ("RETURN", .20, .52, "return"),
    ),
}


def _seed_value(seed: int | str) -> int:
    digest = hashlib.blake2b(str(seed).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def build_composition_plan(
    *,
    duration_seconds: float,
    bpm: float,
    seed: int | str,
    structure: str = "evolving",
    energy: float = .62,
    variation: float = .45,
) -> CompositionPlan:
    """Allocate deterministic, bar-aligned sections over an exact render duration."""
    if duration_seconds <= 0 or bpm <= 0:
        raise ValueError("duration_seconds and bpm must be positive")
    if structure not in STRUCTURES:
        raise ValueError(f"unknown structure: {structure}")
    if not 0 <= energy <= 1 or not 0 <= variation <= 1:
        raise ValueError("energy and variation must be between zero and one")

    rng = np.random.default_rng(np.random.SeedSequence([_seed_value(seed), 0x52454157]))
    template = STRUCTURES[structure]
    weights = np.asarray([item[1] for item in template], dtype=np.float64)
    if variation:
        noise = rng.normal(0.0, .18 * variation, len(weights))
        noise -= noise.mean()
        weights *= np.exp(np.clip(noise, -.30, .30))
    weights = np.maximum(weights, .07)
    weights /= weights.sum()

    bar_seconds = 240.0 / float(bpm)
    total_bars = max(len(template), int(round(duration_seconds / bar_seconds)))
    target_bars = weights * total_bars
    bars = np.maximum(1, np.floor(target_bars).astype(int))
    while int(bars.sum()) > total_bars:
        candidates = np.flatnonzero(bars > 1)
        if candidates.size == 0:
            break
        index = int(candidates[np.argmin(target_bars[candidates] - bars[candidates])])
        bars[index] -= 1
    while int(bars.sum()) < total_bars:
        bars[int(np.argmax(target_bars - bars))] += 1

    edges = np.concatenate(([0], np.cumsum(bars)))
    sections: list[SectionPlan] = []
    for index, ((name, _weight, target, motif), first_bar, last_bar) in enumerate(
        zip(template, edges[:-1], edges[1:], strict=True)
    ):
        section_energy = float(np.clip(
            .68 * target + .32 * energy + rng.normal(0.0, .025 * variation), 0, 1
        ))
        density = float(np.clip(.08 + .68 * section_energy, .04, .78))
        brightness = float(np.clip(.16 + .69 * section_energy, .08, .92))
        instability = float(np.clip(
            .08 + .56 * section_energy + rng.uniform(-.08, .08) * variation, 0, .78
        ))
        space = float(np.clip(
            1.0 - .76 * density + rng.uniform(-.06, .06) * variation, .12, 1
        ))

        upper = name.upper()
        is_outro = "OUTRO" in upper or "RESIDUAL" in upper
        is_sparse = "SUSPENSION" in upper or "EXPOSE" in upper
        is_intro = upper == "INTRO"
        kick = not (is_outro or is_sparse or is_intro)
        melody = not is_outro and motif != "dissolve"
        texture = not is_outro
        if is_sparse:
            melody = motif == "present"
        register = int(rng.choice((-12, -7, 0, 5, 12))) if variation and motif in {"develop", "fragment"} else 0
        support = float(np.clip(.98 - .43 * density, .52, .96))
        if section_energy > .78 and density > .62 and rng.random() < .65:
            texture = False

        start_seconds = first_bar * bar_seconds
        end_seconds = min(duration_seconds, last_bar * bar_seconds)
        if index == len(template) - 1:
            end_seconds = duration_seconds
        sections.append(SectionPlan(
            index=index,
            name=name,
            start_bar=int(first_bar),
            end_bar=int(last_bar),
            start_seconds=float(start_seconds),
            end_seconds=float(end_seconds),
            energy=section_energy,
            density=density,
            brightness=brightness,
            instability=instability,
            space=space,
            kick=kick,
            melody=melody,
            texture=texture,
            ambience=True,
            motif_mode=motif,
            motif_register_semitones=register,
            percussion_density_scale=support,
        ))

    return CompositionPlan(
        duration_seconds=float(duration_seconds),
        bpm=float(bpm),
        seed=seed,
        structure=structure,
        sections=tuple(sections),
    )


def section_for_time(plan: CompositionPlan, time_seconds: float) -> SectionPlan:
    """Return the containing section, clamping to the first or last section."""
    if not plan.sections:
        raise ValueError("composition plan has no sections")
    value = float(time_seconds)
    for section in plan.sections:
        if section.start_seconds <= value < section.end_seconds:
            return section
    return plan.sections[0] if value < 0 else plan.sections[-1]
