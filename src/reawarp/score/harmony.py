"""Deterministic, inspectable voice-leading assignment helpers."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class VoiceLeadingWeights:
    """Transparent soft-cost weights; they are not a universal musical-quality score."""

    motion: float = 1.0
    leap: float = 0.25
    common_tone_bonus: float = 0.5
    crossing: float = 2.0
    leap_threshold: float = 5.0

    def __post_init__(self) -> None:
        for name in ("motion", "leap", "common_tone_bonus", "crossing", "leap_threshold"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class VoiceLeadingResult:
    """Chosen source→target assignment and its inspectable component costs."""

    assignments: tuple[tuple[int, int, float, float], ...]
    total_cost: float
    cost_components: tuple[tuple[str, float], ...]
    crossed_pairs: tuple[tuple[int, int], ...]


def assign_voice_leading(
    source_pitches: Sequence[float],
    target_pitches: Sequence[float],
    *,
    weights: VoiceLeadingWeights = VoiceLeadingWeights(),
    allow_crossing: bool = True,
    maximum_leap: float | None = None,
    common_tone_tolerance: float = 1e-7,
) -> VoiceLeadingResult:
    """Assign adjacent sonority tones with deterministic exhaustive matching.

    Inputs are voice-ordered sequences. Equal voice counts are required in this
    first implementation. A hard maximum leap can reject assignments; when
    crossing is disabled, only order-preserving assignments are considered.
    For practical chord sizes the bounded exhaustive search is simple to audit
    and has no optional dependency or nondeterministic solver tie-break.
    """
    source = tuple(float(value) for value in source_pitches)
    target = tuple(float(value) for value in target_pitches)
    if not source or len(source) != len(target):
        raise ValueError("voice-leading requires equal, non-empty source and target voices")
    if len(source) > 8:
        raise ValueError("voice-leading currently supports up to eight simultaneous voices")
    if any(not math.isfinite(value) for value in (*source, *target)):
        raise ValueError("voice-leading pitches must be finite")
    if maximum_leap is not None and (
        not math.isfinite(float(maximum_leap)) or maximum_leap < 0
    ):
        raise ValueError("maximum_leap must be finite and non-negative")
    if not math.isfinite(float(common_tone_tolerance)) or common_tone_tolerance < 0:
        raise ValueError("common_tone_tolerance must be finite and non-negative")

    best_key: tuple[float, tuple[int, ...]] | None = None
    best_components: dict[str, float] | None = None
    best_crossings: tuple[tuple[int, int], ...] = ()
    best_assignment: tuple[int, ...] | None = None

    candidates = (
        (tuple(range(len(source))),)
        if not allow_crossing
        else itertools.permutations(range(len(target)))
    )
    for assignment in candidates:
        deltas = tuple(target[assignment[index]] - source[index] for index in range(len(source)))
        distances = tuple(abs(delta) for delta in deltas)
        if maximum_leap is not None and any(distance > maximum_leap for distance in distances):
            continue

        crossed = tuple(
            (left, right)
            for left in range(len(assignment))
            for right in range(left + 1, len(assignment))
            if assignment[left] > assignment[right]
        )
        motion_cost = weights.motion * sum(distances)
        leap_cost = weights.leap * sum(
            max(0.0, distance - weights.leap_threshold) ** 2
            for distance in distances
        )
        common_tones = sum(
            distance <= common_tone_tolerance for distance in distances
        )
        common_cost = -weights.common_tone_bonus * common_tones
        crossing_cost = weights.crossing * len(crossed)
        components = {
            "motion": float(motion_cost),
            "leap": float(leap_cost),
            "common_tone": float(common_cost),
            "crossing": float(crossing_cost),
        }
        total = float(sum(components.values()))
        key = (total, tuple(assignment))
        if best_key is None or key < best_key:
            best_key = key
            best_assignment = tuple(assignment)
            best_components = components
            best_crossings = crossed

    if best_assignment is None or best_components is None or best_key is None:
        raise ValueError("no voice-leading assignment satisfies the hard constraints")

    assignments = tuple(
        (index, target_index, source[index], target[target_index])
        for index, target_index in enumerate(best_assignment)
    )
    return VoiceLeadingResult(
        assignments=assignments,
        total_cost=best_key[0],
        cost_components=tuple(sorted(best_components.items())),
        crossed_pairs=best_crossings,
    )
