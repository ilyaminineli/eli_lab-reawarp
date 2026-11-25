"""Deterministic, inspectable voice-leading assignment helpers."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class VoiceLeadingWeights:
    """Transparent soft-cost weights; they are not a universal musical-quality score.

    ``crossing`` is retained as the original M19.1 voice-crossing weight.
    M19.3 adds independent weights for leaving a role register, target-role
    affinity, motion-style preferences, and deliberate crossing.
    """

    motion: float = 1.0
    leap: float = 0.25
    common_tone_bonus: float = 0.5
    crossing: float = 2.0
    leap_threshold: float = 5.0
    register_crossing: float = 1.0
    target_role: float = 1.0
    contrary_motion: float = 1.0
    oblique_motion: float = 1.0
    parallel_motion: float = 1.0
    deliberate_crossing_bonus: float = 2.0

    def __post_init__(self) -> None:
        for name in (
            "motion", "leap", "common_tone_bonus", "crossing", "leap_threshold",
            "register_crossing", "target_role", "contrary_motion", "oblique_motion",
            "parallel_motion", "deliberate_crossing_bonus",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    def to_dict(self) -> dict[str, float]:
        return {
            "motion": float(self.motion),
            "leap": float(self.leap),
            "common_tone_bonus": float(self.common_tone_bonus),
            "crossing": float(self.crossing),
            "leap_threshold": float(self.leap_threshold),
            "register_crossing": float(self.register_crossing),
            "target_role": float(self.target_role),
            "contrary_motion": float(self.contrary_motion),
            "oblique_motion": float(self.oblique_motion),
            "parallel_motion": float(self.parallel_motion),
            "deliberate_crossing_bonus": float(self.deliberate_crossing_bonus),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "VoiceLeadingWeights":
        if not isinstance(data, dict):
            raise ValueError("voice-leading weights must be an object")
        allowed = {
            "motion", "leap", "common_tone_bonus", "crossing", "leap_threshold",
            "register_crossing", "target_role", "contrary_motion", "oblique_motion",
            "parallel_motion", "deliberate_crossing_bonus",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ValueError("unknown voice-leading weight(s): " + ", ".join(sorted(unknown)))
        return cls(**{key: value for key, value in data.items()})


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
        isinstance(maximum_leap, bool)
        or not math.isfinite(float(maximum_leap)) or maximum_leap < 0
    ):
        raise ValueError("maximum_leap must be finite and non-negative")
    if (
        isinstance(common_tone_tolerance, bool)
        or not math.isfinite(float(common_tone_tolerance))
        or common_tone_tolerance < 0
    ):
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
