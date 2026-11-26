"""Deterministic sonority generation and provenance-preserving transforms."""

from __future__ import annotations

import hashlib
import math
import random
from typing import Sequence

from reawarp.score.pitch import PitchCandidate, PitchField, Sonority, TuningSystem


def _finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _candidate_score(
    candidate: PitchCandidate,
    *,
    stability_weight: float,
    tension_weight: float,
    vocabulary_weight: float,
    interval_weight: float,
) -> float:
    score = stability_weight * candidate.stability - tension_weight * candidate.tension
    if candidate.in_pitch_collection:
        score += vocabulary_weight
    if candidate.in_allowed_intervals:
        score += interval_weight
    if not math.isfinite(score):
        raise ValueError("pitch-field weights produced a non-finite candidate score")
    return score


def _stable_path_key(seed: int | str, path: Sequence[PitchCandidate]) -> str:
    values = ",".join(f"{item.pitch:.10g}" for item in path)
    payload = f"reawarp:m19.2:{seed!s}:{values}".encode("utf-8")
    return hashlib.blake2b(payload, digest_size=12).hexdigest()


def generate_sonority(
    pitch_field: PitchField | None,
    tuning: TuningSystem,
    *,
    sonority_id: str,
    onset_beats: str | int | float = "0",
    duration_beats: str | int | float = "4",
    voice_count: int = 4,
    minimum_pitch: float = 48.0,
    maximum_pitch: float = 84.0,
    pitch_step: float = 1.0,
    minimum_spacing: float = 0.0,
    maximum_spacing: float | None = None,
    bass_pitch: float | None = None,
    seed: int | str = 0,
    stability_weight: float = 1.0,
    tension_weight: float = 1.0,
    vocabulary_weight: float = 0.75,
    interval_weight: float = 0.25,
    temperature: float = 0.35,
    beam_width: int = 96,
) -> Sonority:
    """Generate a seeded sonority from hard constraints and soft pitch preferences.

    Hard constraints remove candidates. Soft collection/interval matches,
    stability and tension only bias selection. The bounded beam search applies
    spacing constraints and stable seed-derived tie breaking; temperature controls
    variation among the best complete voicings. No chord-function assumptions
    are introduced.
    """
    if not isinstance(sonority_id, str) or not sonority_id.strip():
        raise ValueError("sonority_id cannot be empty")
    if isinstance(seed, bool) or not isinstance(seed, (int, str)):
        raise ValueError("seed must be an integer or string")
    if (
        isinstance(voice_count, bool)
        or not isinstance(voice_count, int)
        or not 1 <= voice_count <= 8
    ):
        raise ValueError("voice_count must be an integer between 1 and 8")
    if (
        isinstance(beam_width, bool)
        or not isinstance(beam_width, int)
        or not 1 <= beam_width <= 512
    ):
        raise ValueError("beam_width must be an integer between 1 and 512")

    low = _finite(minimum_pitch, "minimum_pitch")
    high = _finite(maximum_pitch, "maximum_pitch")
    step = _finite(pitch_step, "pitch_step")
    min_gap = _finite(minimum_spacing, "minimum_spacing")
    temp = _finite(temperature, "temperature")
    weights = {
        "stability_weight": _finite(stability_weight, "stability_weight"),
        "tension_weight": _finite(tension_weight, "tension_weight"),
        "vocabulary_weight": _finite(vocabulary_weight, "vocabulary_weight"),
        "interval_weight": _finite(interval_weight, "interval_weight"),
    }
    max_gap = (
        None if maximum_spacing is None else _finite(maximum_spacing, "maximum_spacing")
    )
    if low > high:
        raise ValueError("minimum_pitch cannot exceed maximum_pitch")
    if step <= 0:
        raise ValueError("pitch_step must be positive")
    if min_gap < 0 or (max_gap is not None and max_gap < min_gap):
        raise ValueError("spacing requires 0 <= minimum_spacing <= maximum_spacing")
    if temp < 0:
        raise ValueError("temperature must be non-negative")
    if bass_pitch is not None:
        bass_pitch = _finite(bass_pitch, "bass_pitch")

    field = pitch_field or PitchField()
    if not isinstance(field, PitchField):
        raise ValueError("pitch_field must be a PitchField or None")
    if (
        bass_pitch is not None
        and field.hard_constraint
        and not field.evaluate(bass_pitch, tuning).allowed
    ):
        raise ValueError("bass_pitch violates hard pitch-field constraints")

    candidate_count = int(math.floor((high - low) / step + 1e-9))
    if candidate_count > 512:
        raise ValueError("pitch range creates more than 512 candidate steps")
    candidates = []
    for index in range(candidate_count):
        pitch = low + index * step
        candidate = field.evaluate(pitch, tuning)
        if candidate.allowed:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("pitch field produced no candidates in the requested register")

    scored = [
        (candidate, _candidate_score(candidate, **weights)) for candidate in candidates
    ]
    states: list[tuple[tuple[PitchCandidate, ...], float]] = [((), 0.0)]
    for _voice in range(voice_count):
        expanded: list[tuple[tuple[PitchCandidate, ...], float]] = []
        for path, total in states:
            previous = path[-1].pitch if path else None
            for candidate, candidate_value in scored:
                if previous is not None:
                    gap = candidate.pitch - previous
                    if gap < min_gap - 1e-9:
                        continue
                    if max_gap is not None and gap > max_gap + 1e-9:
                        continue
                expanded.append((path + (candidate,), total + candidate_value))
        if not expanded:
            raise ValueError(
                "no complete sonority satisfies the pitch and voice-spacing constraints"
            )
        expanded.sort(
            key=lambda item: (
                -item[1],
                _stable_path_key(seed, item[0]),
            )
        )
        states = expanded[:beam_width]

    if temp == 0.0:
        selected, _score = states[0]
    else:
        best = max(score for _path, score in states)
        sampling_weights = [
            math.exp(max(-60.0, min(0.0, (score - best) / temp)))
            for _path, score in states
        ]
        rng = random.Random(f"reawarp-m19.2:{type(seed).__name__}:{seed}")
        selected, _score = rng.choices(states, weights=sampling_weights, k=1)[0]

    selected_pitches = tuple(item.pitch for item in selected)
    average_tension = sum(item.tension for item in selected) / len(selected)
    return Sonority(
        sonority_id=sonority_id,
        onset_beats=str(onset_beats),
        duration_beats=str(duration_beats),
        pitches=selected_pitches,
        bass_pitch=bass_pitch,
        tension=average_tension,
        transform="generated",
        transform_parameters={
            "seed": seed,
            "tuning_id": tuning.identifier,
            "pitch_mode": field.mode,
            "voice_count": voice_count,
            "minimum_pitch": low,
            "maximum_pitch": high,
            "pitch_step": step,
            "minimum_spacing": min_gap,
            "maximum_spacing": max_gap,
            "temperature": temp,
            **weights,
        },
    )


def _transformed(
    source: Sonority,
    *,
    sonority_id: str,
    pitches: Sequence[float],
    transform: str,
    parameters: dict[str, object],
    bass_pitch: float | None = None,
) -> Sonority:
    if not isinstance(sonority_id, str) or not sonority_id.strip():
        raise ValueError("sonority_id cannot be empty")
    return Sonority(
        sonority_id=sonority_id,
        onset_beats=source.onset_beats,
        duration_beats=source.duration_beats,
        pitches=tuple(sorted(_finite(value, "transformed pitch") for value in pitches)),
        bass_pitch=(
            source.bass_pitch
            if bass_pitch is None
            else _finite(bass_pitch, "bass_pitch")
        ),
        tension=source.tension,
        transform=transform,
        source_sonority_id=source.sonority_id,
        transform_parameters={
            "source_transform": source.transform,
            **parameters,
        },
    )


def rotate_sonority(
    source: Sonority,
    tuning: TuningSystem,
    *,
    steps: int = 1,
    sonority_id: str,
) -> Sonority:
    """Raise a selected number of low voices by one tuning period."""
    if isinstance(steps, bool) or not isinstance(steps, int):
        raise ValueError("rotation steps must be an integer")
    pitches = tuple(sorted(source.pitches))
    count = steps % len(pitches)
    shifted = tuple(
        pitch + (tuning.divisions_per_period if index < count else 0.0)
        for index, pitch in enumerate(pitches)
    )
    bass = source.bass_pitch
    if bass is not None and count:
        bass += tuning.divisions_per_period
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=shifted,
        transform="rotate",
        parameters={"steps": steps, "period_steps": tuning.divisions_per_period},
        bass_pitch=bass,
    )


def transpose_sonority(
    source: Sonority,
    interval_steps: float,
    *,
    sonority_id: str,
) -> Sonority:
    """Move all voices and the optional bass reference by tuning steps."""
    interval = _finite(interval_steps, "interval_steps")
    bass = None if source.bass_pitch is None else source.bass_pitch + interval
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=tuple(value + interval for value in source.pitches),
        transform="transpose",
        parameters={"interval_steps": interval},
        bass_pitch=bass,
    )


def invert_sonority(
    source: Sonority,
    axis_pitch: float,
    *,
    sonority_id: str,
) -> Sonority:
    """Reflect every pitch around an explicit pitch-coordinate axis."""
    axis = _finite(axis_pitch, "axis_pitch")
    bass = None if source.bass_pitch is None else 2.0 * axis - source.bass_pitch
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=tuple(2.0 * axis - value for value in source.pitches),
        transform="invert",
        parameters={"axis_pitch": axis},
        bass_pitch=bass,
    )


def expand_contract_sonority(
    source: Sonority,
    factor: float,
    *,
    sonority_id: str,
    centre_pitch: float | None = None,
) -> Sonority:
    """Expand or contract intervals around an explicit, or derived, pivot."""
    scale = _finite(factor, "factor")
    if scale <= 0:
        raise ValueError("factor must be positive")
    centre = (
        _finite(centre_pitch, "centre_pitch")
        if centre_pitch is not None
        else (
            source.bass_pitch
            if source.bass_pitch is not None
            else sum(source.pitches) / len(source.pitches)
        )
    )
    pitches = tuple(centre + (value - centre) * scale for value in source.pitches)
    bass = (
        None
        if source.bass_pitch is None
        else centre + (source.bass_pitch - centre) * scale
    )
    transform = (
        "expand" if scale > 1.0 else "contract" if scale < 1.0 else "interval_scale"
    )
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=pitches,
        transform=transform,
        parameters={"factor": scale, "centre_pitch": centre},
        bass_pitch=bass,
    )


def displace_register(
    source: Sonority,
    tuning: TuningSystem,
    period_count: int,
    *,
    sonority_id: str,
) -> Sonority:
    """Move a whole sonority by an integer number of tuning periods."""
    if isinstance(period_count, bool) or not isinstance(period_count, int):
        raise ValueError("period_count must be an integer")
    shift = period_count * tuning.divisions_per_period
    bass = None if source.bass_pitch is None else source.bass_pitch + shift
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=tuple(value + shift for value in source.pitches),
        transform="register_displacement",
        parameters={
            "period_count": period_count,
            "period_steps": tuning.divisions_per_period,
        },
        bass_pitch=bass,
    )


def derive_spectral_sonority(
    source: Sonority,
    tuning: TuningSystem,
    partial_ratios: Sequence[float],
    *,
    sonority_id: str,
    base_pitch: float | None = None,
) -> Sonority:
    """Derive pitches from partial ratios using the tuning's period mapping."""
    ratios = tuple(_finite(value, "partial ratio") for value in partial_ratios)
    if not ratios or any(value <= 0 for value in ratios):
        raise ValueError(
            "partial_ratios must be a non-empty sequence of positive values"
        )
    base = (
        _finite(base_pitch, "base_pitch")
        if base_pitch is not None
        else (
            source.bass_pitch if source.bass_pitch is not None else min(source.pitches)
        )
    )
    pitches = tuple(
        base + tuning.divisions_per_period * math.log(ratio, tuning.period_ratio)
        for ratio in ratios
    )
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=pitches,
        transform="spectral_derive",
        parameters={
            "base_pitch": base,
            "partial_ratios": list(ratios),
            "tuning_id": tuning.identifier,
            "period_ratio": tuning.period_ratio,
            "divisions_per_period": tuning.divisions_per_period,
        },
        bass_pitch=base,
    )


def replace_sonority_voice(
    source: Sonority,
    voice_index: int,
    pitch: float,
    *,
    sonority_id: str,
) -> Sonority:
    """Replace one pitch in the ordered source voicing, preserving the others."""
    if isinstance(voice_index, bool) or not isinstance(voice_index, int):
        raise ValueError("voice_index must be an integer")
    if not 0 <= voice_index < len(source.pitches):
        raise ValueError("voice_index is outside the sonority")
    replacement = _finite(pitch, "replacement pitch")
    updated = list(sorted(source.pitches))
    previous = updated[voice_index]
    updated[voice_index] = replacement
    return _transformed(
        source,
        sonority_id=sonority_id,
        pitches=updated,
        transform="replace_voice",
        parameters={
            "voice_index": voice_index,
            "previous_pitch": previous,
            "replacement_pitch": replacement,
        },
    )


def resolve_sonority_frequencies(
    sonority: Sonority,
    tuning: TuningSystem,
) -> tuple[float, ...]:
    """Resolve pitch coordinates without quantising the stored pitches."""
    return tuple(tuning.frequency_for_pitch(value) for value in sonority.pitches)
