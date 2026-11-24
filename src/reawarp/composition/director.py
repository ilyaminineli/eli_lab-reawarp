"""Deterministic formal section planning for long-form IDM generation."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from reawarp.composition.patterns import PATTERN_FAMILIES, PATTERN_RELATIONSHIPS


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
    flow: str
    source_structure: str | None
    sections: tuple[SectionPlan, ...]
    pattern_family: str
    pattern_relationship: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "bpm": self.bpm,
            "seed": self.seed,
            "structure": self.structure,
            "flow": self.flow,
            "source_structure": self.source_structure,
            "pattern_family": self.pattern_family,
            "pattern_relationship": self.pattern_relationship,
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
    # Classical phrase functions translated into electronic orchestration:
    # exposition, contrasting subject, development, recapitulation and coda.
    "classical_arc": (
        ("EXPOSITION_I", .18, .30, "present"),
        ("EXPOSITION_II", .16, .42, "present"),
        ("DEVELOPMENT", .28, .78, "develop"),
        ("RECAPITULATION", .24, .58, "return"),
        ("CODA", .14, .16, "dissolve"),
    ),
    "sonata_mutation": (
        ("SUBJECT_A", .17, .34, "present"),
        ("SUBJECT_B", .16, .55, "present"),
        ("DEVELOPMENT", .27, .86, "fragment"),
        ("FALSE_RETURN", .12, .46, "return"),
        ("REPRISE_TRANSFORMED", .18, .68, "return"),
        ("CODA", .10, .14, "dissolve"),
    ),
    "free_jazz": (
        ("SPARSE_PROPOSITION", .15, .22, "fragment"),
        ("COLLECTIVE_IMPROVISATION", .30, .82, "develop"),
        ("OPEN_SPACE", .13, .20, "fragment"),
        ("SECOND_WAVE", .24, .72, "develop"),
        ("AFTERIMAGE", .18, .26, "dissolve"),
    ),
    "free_jazz_episodic": (
        ("GESTURE_A", .18, .35, "present"),
        ("COUNTER_GESTURE", .17, .55, "develop"),
        ("COLLISION", .20, .90, "fragment"),
        ("DECOMPRESSION", .15, .18, "dissolve"),
        ("GESTURE_B", .18, .62, "develop"),
        ("RESIDUE", .12, .12, "dissolve"),
    ),
    "autechre_like": (
        ("SEED_OBJECT", .14, .26, "present"),
        ("RULE_ESTABLISHMENT", .19, .48, "present"),
        ("PHASE_DRIFT", .23, .72, "develop"),
        ("SYSTEM_BREAK", .16, .84, "fragment"),
        ("RECOMBINATION", .18, .62, "return"),
        ("RESIDUE", .10, .10, "dissolve"),
    ),
    "minimal_variation": (
        ("OBJECT", .28, .34, "present"),
        ("MICRO_SHIFT", .24, .42, "develop"),
        ("WITHDRAWAL", .16, .18, "fragment"),
        ("RETURN_CHANGED", .22, .48, "return"),
        ("FADE", .10, .10, "dissolve"),
    ),
    "hybrid": (
        ("EXPOSITION", .16, .30, "present"),
        ("GROOVE", .18, .55, "develop"),
        ("FREE_SECTION", .20, .82, "fragment"),
        ("REPRISE", .18, .58, "return"),
        ("DECONSTRUCTION", .16, .30, "fragment"),
        ("CODA", .12, .12, "dissolve"),
    ),
    # IRO Track 01-inspired organism arc: isolated signal, construction,
    # orbital counter-motion, collision, withdrawal, false memory and residue.
    "iro_metamorphosis": (
        ("SIGNAL_INTRO", .08, .12, "fragment"),
        ("CONSTRUCTION", .13, .34, "present"),
        ("ORBIT", .17, .54, "develop"),
        ("UPLIFT", .09, .72, "rhythmic"),
        ("COLLISION", .13, .88, "fragment"),
        ("OVERLOAD", .10, .96, "rhythmic"),
        ("NULL_DROP", .07, .12, "fragment"),
        ("AFTERSHOCK", .08, .48, "inversion"),
        ("UNRAVEL", .06, .28, "fragment"),
        ("FALSE_RETURN", .05, .42, "return"),
        ("RESIDUE_CODA", .04, .10, "dissolve"),
    ),
    # A more conventional but clearly articulated rise / arrival / void / return.
    "uplift_drop_return": (
        ("FRAGMENT_INTRO", .10, .16, "fragment"),
        ("ANCHOR_ESTABLISHMENT", .18, .38, "present"),
        ("MOTIF_DEVELOPMENT", .18, .52, "develop"),
        ("UPLIFT_A", .10, .68, "rhythmic"),
        ("UPLIFT_B", .10, .82, "develop"),
        ("ARRIVAL_PEAK", .10, .94, "present"),
        ("DROP_VOID", .08, .08, "fragment"),
        ("REBUILD", .08, .48, "inversion"),
        ("TRANSFORMED_RETURN", .05, .62, "return"),
        ("RESIDUE_OUTRO", .03, .10, "dissolve"),
    ),
    "two_movement": (
        ("MOVEMENT_I_SIGNAL", .10, .18, "fragment"),
        ("MOVEMENT_I_FORM", .16, .42, "present"),
        ("MOVEMENT_I_EXPANSION", .18, .72, "develop"),
        ("MOVEMENT_I_CADENCE", .06, .26, "dissolve"),
        ("INTERMOVEMENT_VOID", .04, .04, "fragment"),
        ("MOVEMENT_II_REENTRY", .12, .38, "return"),
        ("MOVEMENT_II_MUTATION", .18, .82, "fragment"),
        ("MOVEMENT_II_REASSEMBLY", .10, .60, "return"),
        ("FINAL_RESIDUE", .06, .12, "dissolve"),
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
        flow: str = "preset",
        pattern_family: str = "broken_funk",
        pattern_relationship: str = "interlock",
) -> CompositionPlan:
    """Allocate deterministic, bar-aligned sections over an exact render duration."""
    if duration_seconds <= 0 or bpm <= 0:
        raise ValueError("duration_seconds and bpm must be positive")
    if structure not in STRUCTURES:
        raise ValueError(f"unknown structure: {structure}")
    if flow not in {"preset", "mix", "mutate"}:
        raise ValueError("flow must be preset, mix, or mutate")
    if pattern_family not in PATTERN_FAMILIES:
        raise ValueError(f"unknown pattern family: {pattern_family}")
    if pattern_relationship not in PATTERN_RELATIONSHIPS:
        raise ValueError(f"unknown pattern relationship: {pattern_relationship}")
    if not 0 <= energy <= 1 or not 0 <= variation <= 1:
        raise ValueError("energy and variation must be between zero and one")

    rng = np.random.default_rng(np.random.SeedSequence([_seed_value(seed), 0x52454157]))
    template = STRUCTURES[structure]
    source_structure: str | None = None
    if flow == "mix" and structure not in {"hybrid"}:
        # A bounded cross-preset blend: retain the chosen form's opening and
        # ending while borrowing one middle movement from the contrasting form.
        alternatives = [name for name in STRUCTURES if name != structure]
        alternate_name = alternatives[int(rng.integers(0, len(alternatives)))]
        alternate = STRUCTURES[alternate_name]
        source_structure = alternate_name
        left = list(template)
        middle = list(alternate[1:-1])
        if middle:
            replace_count = max(1, min(len(middle), len(left) - 2))
            for offset in range(replace_count):
                target = 1 + offset
                if target < len(left) - 1:
                    left[target] = middle[offset % len(middle)]
        template = tuple(left)
    elif flow == "mutate":
        # Keep the form's dramatic contour, but re-sequence middle functions.
        middle = list(template[1:-1])
        if len(middle) > 1:
            order = rng.permutation(len(middle))
            template = (template[0], *(middle[int(i)] for i in order), template[-1])
    weights = np.asarray([item[1] for item in template], dtype=np.float64)
    if variation:
        noise = rng.normal(0.0, .18 * variation, len(weights))
        noise -= noise.mean()
        weights *= np.exp(np.clip(noise, -.30, .30))
    weights = np.maximum(weights, .07)
    weights /= weights.sum()

    bar_seconds = 240.0 / float(bpm)
    total_bars = max(1, int(round(duration_seconds / bar_seconds)))
    if total_bars < len(template):
        if total_bars == 1:
            selected = 1 if structure in {"evolving", "additive"} else 0
            template = (template[selected],)
        else:
            indices = np.linspace(0, len(template) - 1, total_bars).round().astype(int)
            template = tuple(template[int(index)] for index in indices)
        weights = np.asarray([item[1] for item in template], dtype=np.float64)
        weights /= weights.sum()
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
        is_outro = any(token in upper for token in ("OUTRO", "RESIDUAL", "CODA", "RELEASE"))
        is_silence = any(token in upper for token in ("NULL", "VOID", "SILENCE"))
        is_drop = "DROP" in upper
        is_sparse = is_silence or is_drop or any(
            token in upper for token in ("SUSPENSION", "EXPOSE", "AFTERSHOCK", "UNRAVEL")
        )
        is_intro = any(token in upper for token in ("INTRO", "SIGNAL"))
        is_uplift = "UPLIFT" in upper
        is_arrival = any(token in upper for token in ("PEAK", "COLLISION", "OVERLOAD", "ARRIVAL"))
        kick = not (is_outro or is_sparse or is_intro or is_silence)
        melody = not is_outro and motif != "dissolve" and not is_silence
        texture = not is_outro and not is_silence
        if is_sparse:
            melody = motif in {"present", "return"} and not is_silence
        if is_uplift:
            kick = True
            melody = True
        if is_arrival:
            kick = True
            texture = False
        if is_drop:
            kick = False
            texture = False
        if is_silence:
            kick = melody = texture = False
        register = int(rng.choice((-12, -7, 0, 5, 12))) if variation and motif in {"develop", "fragment"} else 0
        if "UPLIFT" in upper:
            register += int(rng.choice((5, 7, 12)))
        elif "DROP" in upper or is_silence:
            register -= int(rng.choice((5, 7, 12)))
        elif "RETURN" in upper:
            register = int(round(register * 0.5))
        support = float(np.clip(.98 - .43 * density, .52, .96))
        if is_silence:
            support = 0.0
        elif is_drop:
            support *= 0.12
        elif is_uplift:
            support = min(1.0, support * 1.18)
        elif is_arrival:
            support = min(1.0, support * 1.08)
        if section_energy > .78 and density > .62 and rng.random() < .65:
            texture = False
        # A real void is an orchestration state, not merely a low energy value.
        # Keep the time axis running while leaving only optional ambience/residue.
        if is_silence:
            texture = False
            ambience = True
            space = max(space, 0.72)
            density = 0.0
            support = 0.0
        elif is_drop:
            ambience = True
            space = max(space, 0.62)
        else:
            ambience = True

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
            ambience=ambience,
            motif_mode=motif,
            motif_register_semitones=register,
            percussion_density_scale=support,
        ))

    return CompositionPlan(
        duration_seconds=float(duration_seconds),
        bpm=float(bpm),
        seed=seed,
        structure=structure,
        flow=flow,
        source_structure=source_structure,
        sections=tuple(sections),
        pattern_family=pattern_family,
        pattern_relationship=pattern_relationship,
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
