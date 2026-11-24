"""Structure-aware pattern grammar and motif transformation utilities."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class PatternEvent:
    step: int
    velocity: float = 0.7
    accent: float = 0.0
    pitch_offset: int = 0
    duration_steps: float = 1.0
    pan: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# Representative generators from the composition atlas. These are building
# blocks rather than a claim to exhaustively encode every possible rhythm.
PATTERN_FAMILIES: dict[str, tuple[int, ...]] = {
    "broken_funk": (0, 3, 6, 8, 11, 14),
    "half_time": (0, 8, 12),
    "straight": (0, 4, 8, 12),
    "sparse": (0, 10),
    "asymmetric_5": (0, 3, 7, 11, 14),
    "asymmetric_7": (0, 2, 5, 8, 11, 13),
    "interlock_a": (0, 5, 9, 14),
    "interlock_b": (3, 7, 11, 15),
    "offbeat_cells": (2, 6, 10, 14),
    "clave_displaced": (0, 3, 6, 10, 12),
    "free_cells": (0, 2, 7, 9, 13),
    "ghost_break": (0, 3, 6, 7, 10, 12, 14),
    "omission": (0, 4, 10, 12),
    "rotating_cycle": (0, 5, 10, 15),
    "irregular_burst": (0, 1, 6, 7, 13),
    "dense_cloud": (0, 1, 3, 4, 6, 8, 9, 11, 12, 14),
    "ratchet": (0, 2, 3, 4, 10, 11, 12),
    "cross_accent": (0, 3, 6, 9, 12, 15),
    "phase_shadow": (0, 4, 8, 12),
    "broken_regularity": (0, 4, 7, 8, 12, 15),
}

PATTERN_RELATIONSHIPS = ("unison", "interlock", "shadow", "call_response", "counter_accent")

MOTIF_TRANSFORMS = (
    "identity", "retrograde", "inversion", "augmentation",
    "diminution", "fragment", "reorder", "displace",
)


def pattern_for_section(
    family: str,
    *,
    section_index: int,
    section_name: str,
    variation: float,
    rng: np.random.Generator,
    density: float = 1.0,
) -> tuple[int, ...]:
    """Adapt a pattern family to section role using bounded deterministic edits."""
    if family not in PATTERN_FAMILIES:
        raise ValueError(f"unknown pattern family: {family}")
    if not 0 <= variation <= 1 or not 0 <= density <= 1:
        raise ValueError("variation and density must be between zero and one")
    base = list(PATTERN_FAMILIES[family])
    name = section_name.upper()
    if any(token in name for token in ("SUSPENSION", "EXPOSE", "RESIDUAL", "CODA")):
        target_density = min(density, 0.48)
    elif any(token in name for token in ("DEVELOP", "MUTATION", "COLLISION", "DRIFT")):
        target_density = min(1.0, density * (1.0 + 0.35 * variation))
    else:
        target_density = density
    keep = max(1, int(round(len(base) * np.clip(target_density, 0.15, 1.0))))
    if keep < len(base):
        chosen = [base[0]]
        rest = base[1:]
        if keep > 1:
            chosen.extend(sorted(rng.choice(rest, size=keep - 1, replace=False).tolist()))
        base = chosen
    if section_index > 0 and variation > 0:
        shift = int(rng.integers(0, 4)) if rng.random() < variation else 0
        base = sorted({(step + shift) % 16 for step in base})
        if rng.random() < variation * 0.4:
            candidate = int(rng.integers(1, 16))
            if candidate not in base:
                base.append(candidate)
                base.sort()
    return tuple(base)


def relate_patterns(
    first: Iterable[int],
    second: Iterable[int],
    *,
    relationship: str,
    cycle_steps: int = 16,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Create common pattern relationships: unison, interlock, shadow, or response."""
    a, b = tuple(sorted(set(first))), tuple(sorted(set(second)))
    if cycle_steps < 1:
        raise ValueError("cycle_steps must be positive")
    if relationship == "unison":
        return a, a
    if relationship == "interlock":
        return a, tuple(step for step in b if step not in set(a))
    if relationship == "shadow":
        return a, tuple(sorted({(step + max(1, cycle_steps // 8)) % cycle_steps for step in a}))
    if relationship == "call_response":
        midpoint = cycle_steps / 2.0
        return (
            tuple(step for step in a if step < midpoint),
            tuple(step for step in b if step >= midpoint),
        )
    if relationship == "counter_accent":
        return a, tuple(step for step in b if step not in set(a))
    raise ValueError(f"unknown pattern relationship: {relationship}")


def evolve_phrase(
    events: Iterable[PatternEvent],
    *,
    transform: str,
    rng: np.random.Generator,
    amount: float = 0.5,
    cycle_steps: int = 16,
) -> tuple[PatternEvent, ...]:
    """Apply one named, bounded transformation to a phrase event sequence."""
    source = tuple(events)
    if transform not in MOTIF_TRANSFORMS:
        raise ValueError(f"unknown motif transform: {transform}")
    if not 0 <= amount <= 1 or cycle_steps < 1:
        raise ValueError("amount must be 0..1 and cycle_steps positive")
    if transform == "identity" or not source:
        return source
    if transform == "retrograde":
        return tuple(
            PatternEvent(
                step=max(0, cycle_steps - event.step - 1),
                velocity=event.velocity, accent=event.accent,
                pitch_offset=event.pitch_offset, duration_steps=event.duration_steps,
                pan=-event.pan,
            )
            for event in reversed(source)
        )
    if transform == "inversion":
        centre = float(np.mean([event.pitch_offset for event in source]))
        return tuple(PatternEvent(
            event.step, event.velocity, event.accent,
            int(round(2 * centre - event.pitch_offset)),
            event.duration_steps, -event.pan,
        ) for event in source)
    if transform == "augmentation":
        factor = 1.0 + amount
        return tuple(PatternEvent(
            int(round(event.step * factor)), event.velocity, event.accent,
            event.pitch_offset, event.duration_steps * factor, event.pan,
        ) for event in source if event.step * factor < cycle_steps)
    if transform == "diminution":
        factor = max(0.25, 1.0 - 0.65 * amount)
        return tuple(PatternEvent(
            int(round(event.step * factor)), event.velocity, event.accent,
            event.pitch_offset, max(0.25, event.duration_steps * factor), event.pan,
        ) for event in source)
    if transform == "fragment":
        keep = max(1, int(round(len(source) * (1.0 - 0.75 * amount))))
        indices = np.sort(rng.choice(len(source), size=keep, replace=False))
        return tuple(source[int(index)] for index in indices)
    if transform == "reorder":
        order = rng.permutation(len(source))
        steps = sorted(event.step for event in source)
        return tuple(
            PatternEvent(
                steps[i], source[int(order[i])].velocity, source[int(order[i])].accent,
                source[int(order[i])].pitch_offset, source[int(order[i])].duration_steps,
                source[int(order[i])].pan,
            ) for i in range(len(source))
        )
    if transform == "displace":
        max_shift = max(1, int(round(3 * amount)))
        shift = int(rng.integers(-max_shift, max_shift + 1))
        return tuple(PatternEvent(
            (event.step + shift) % cycle_steps, event.velocity, event.accent,
            event.pitch_offset, event.duration_steps, event.pan,
        ) for event in source)
    return source
