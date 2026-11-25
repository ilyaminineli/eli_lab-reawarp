"""Tuning-aware pitch coordinates and optional pitch-field evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class TuningSystem(Protocol):
    """Adapter interface for equal, just, regular-temperament, or custom tunings."""

    identifier: str
    divisions_per_period: int

    def frequency_for_pitch(self, pitch: float) -> float: ...
    def pitch_for_frequency(self, frequency_hz: float) -> float: ...


@dataclass(frozen=True, slots=True)
class EqualTemperamentTuning:
    """Equal divisions of a period; defaults to twelve-tone equal temperament."""

    divisions_per_period: int = 12
    period_ratio: float = 2.0
    reference_pitch: float = 69.0
    reference_frequency_hz: float = 440.0
    identifier: str = "12tet"

    def __post_init__(self) -> None:
        if isinstance(self.divisions_per_period, bool) or not isinstance(self.divisions_per_period, int) or self.divisions_per_period < 1:
            raise ValueError("divisions_per_period must be a positive integer")
        if not math.isfinite(self.period_ratio) or self.period_ratio <= 1.0:
            raise ValueError("period_ratio must be finite and greater than one")
        if not math.isfinite(self.reference_pitch):
            raise ValueError("reference_pitch must be finite")
        if not math.isfinite(self.reference_frequency_hz) or self.reference_frequency_hz <= 0:
            raise ValueError("reference_frequency_hz must be positive and finite")
        if not self.identifier.strip():
            raise ValueError("tuning identifier cannot be empty")

    def frequency_for_pitch(self, pitch: float) -> float:
        pitch = float(pitch)
        if not math.isfinite(pitch):
            raise ValueError("pitch must be finite")
        return self.reference_frequency_hz * self.period_ratio ** (
            (pitch - self.reference_pitch) / self.divisions_per_period
        )

    def pitch_for_frequency(self, frequency_hz: float) -> float:
        frequency_hz = float(frequency_hz)
        if not math.isfinite(frequency_hz) or frequency_hz <= 0:
            raise ValueError("frequency_hz must be positive and finite")
        return self.reference_pitch + self.divisions_per_period * math.log(
            frequency_hz / self.reference_frequency_hz, self.period_ratio
        )


@dataclass(frozen=True, slots=True)
class Pitch:
    """A pitch coordinate plus its frequency and tuning provenance."""

    value: float
    frequency_hz: float
    tuning_id: str = "12tet"

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("pitch value must be finite")
        if not math.isfinite(self.frequency_hz) or self.frequency_hz <= 0:
            raise ValueError("pitch frequency must be positive and finite")
        if not self.tuning_id.strip():
            raise ValueError("tuning_id cannot be empty")

    @classmethod
    def from_value(cls, value: float, tuning: TuningSystem) -> "Pitch":
        return cls(
            value=float(value),
            frequency_hz=tuning.frequency_for_pitch(float(value)),
            tuning_id=tuning.identifier,
        )

    @classmethod
    def from_frequency(cls, frequency_hz: float, tuning: TuningSystem) -> "Pitch":
        return cls(
            value=tuning.pitch_for_frequency(float(frequency_hz)),
            frequency_hz=float(frequency_hz),
            tuning_id=tuning.identifier,
        )


@dataclass(frozen=True, slots=True)
class PitchCandidate:
    """A tuning-aware pitch candidate with transparent soft preference data."""

    pitch: float
    frequency_hz: float
    stability: float = 0.0
    tension: float = 0.0
    allowed: bool = True


@dataclass(frozen=True, slots=True)
class PitchField:
    """Optional pitch vocabulary/hierarchy; an absent field means chromatic freedom.

    The field deliberately separates hard vocabulary constraints from soft
    stability/tension weights. A centre is just one possible source of hierarchy.
    """

    mode: str = "chromatic"
    centre_pitch: float | None = None
    pitch_collection: tuple[float, ...] = ()
    allowed_intervals: tuple[float, ...] = ()
    period_ratio: float = 2.0
    stability_weights: Mapping[str, float] | None = None
    tension_weights: Mapping[str, float] | None = None
    hard_constraint: bool = False
    minimum_pitch: float | None = None
    maximum_pitch: float | None = None

    MODES = frozenset({
        "chromatic", "collection", "centred", "intervallic",
        "spectral", "microtonal", "ambiguous",
    })

    def __post_init__(self) -> None:
        if self.mode not in self.MODES:
            raise ValueError(f"unsupported pitch-field mode: {self.mode}")
        if not math.isfinite(float(self.period_ratio)) or self.period_ratio <= 1.0:
            raise ValueError("period_ratio must be finite and greater than one")
        if self.centre_pitch is not None and not math.isfinite(float(self.centre_pitch)):
            raise ValueError("centre_pitch must be finite")
        for name, values in (
            ("pitch_collection", self.pitch_collection),
            ("allowed_intervals", self.allowed_intervals),
        ):
            if any(not math.isfinite(float(value)) for value in values):
                raise ValueError(f"{name} values must be finite")
        if self.mode == "collection" and not self.pitch_collection:
            raise ValueError("collection mode requires pitch_collection values")
        if self.minimum_pitch is not None and not math.isfinite(float(self.minimum_pitch)):
            raise ValueError("minimum_pitch must be finite")
        if self.maximum_pitch is not None and not math.isfinite(float(self.maximum_pitch)):
            raise ValueError("maximum_pitch must be finite")
        if (
            self.minimum_pitch is not None and self.maximum_pitch is not None
            and self.minimum_pitch > self.maximum_pitch
        ):
            raise ValueError("minimum_pitch cannot exceed maximum_pitch")
        for mapping_name, mapping in (
            ("stability_weights", self.stability_weights or {}),
            ("tension_weights", self.tension_weights or {}),
        ):
            if any(not math.isfinite(float(value)) for value in mapping.values()):
                raise ValueError(f"{mapping_name} must contain finite weights")

    @classmethod
    def from_score_context(cls, context: Mapping[str, object] | None) -> "PitchField":
        if context is None:
            return cls()
        return cls(
            mode=str(context.get("mode", "chromatic")),
            centre_pitch=None if context.get("centre_pitch") is None else float(context["centre_pitch"]),
            pitch_collection=tuple(float(value) for value in context.get("pitch_collection", ())),
            allowed_intervals=tuple(float(value) for value in context.get("allowed_intervals", ())),
            period_ratio=float(context.get("period_ratio", 2.0)),
            stability_weights=dict(context.get("stability_weights", {})),
            tension_weights=dict(context.get("tension_weights", {})),
            hard_constraint=bool(context.get("hard_constraint", False)),
            minimum_pitch=None if context.get("minimum_pitch") is None else float(context["minimum_pitch"]),
            maximum_pitch=None if context.get("maximum_pitch") is None else float(context["maximum_pitch"]),
        )

    def evaluate(self, pitch: float, tuning: TuningSystem) -> PitchCandidate:
        pitch = float(pitch)
        if not math.isfinite(pitch):
            raise ValueError("candidate pitch must be finite")
        in_range = (
            (self.minimum_pitch is None or pitch >= self.minimum_pitch)
            and (self.maximum_pitch is None or pitch <= self.maximum_pitch)
        )
        allowed_collection = (
            not self.pitch_collection
            or any(
                math.isclose(
                    ((pitch - value) / tuning.divisions_per_period)
                    - round((pitch - value) / tuning.divisions_per_period),
                    0.0,
                    abs_tol=1e-7,
                )
                for value in self.pitch_collection
            )
        )
        interval = pitch - self.centre_pitch if self.centre_pitch is not None else None
        allowed_intervals = (
            not self.allowed_intervals
            or interval is None
            or any(
                math.isclose(
                    interval - value
                    - round(interval / tuning.divisions_per_period) * tuning.divisions_per_period,
                    0.0,
                    abs_tol=1e-7,
                )
                for value in self.allowed_intervals
            )
        )
        allowed = in_range and allowed_collection and allowed_intervals
        key = f"{pitch:g}"
        pitch_class_key = f"{pitch % tuning.divisions_per_period:g}"
        stability_weights = self.stability_weights or {}
        tension_weights = self.tension_weights or {}
        stability = float(stability_weights.get(key, stability_weights.get(pitch_class_key, 0.0)))
        tension = float(tension_weights.get(key, tension_weights.get(pitch_class_key, 0.0)))
        return PitchCandidate(
            pitch=pitch,
            frequency_hz=tuning.frequency_for_pitch(pitch),
            stability=stability,
            tension=tension,
            allowed=(allowed or not self.hard_constraint),
        )

    def candidates(self, pitches: tuple[float, ...], tuning: TuningSystem) -> tuple[PitchCandidate, ...]:
        return tuple(
            candidate for candidate in (
                self.evaluate(pitch, tuning) for pitch in sorted(set(map(float, pitches)))
            )
            if candidate.allowed
        )


@dataclass(frozen=True, slots=True)
class Sonority:
    """Small immutable sonority primitive stored on a rational-beat timeline."""

    sonority_id: str
    onset_beats: str
    duration_beats: str
    pitches: tuple[float, ...]
    bass_pitch: float | None = None
    tension: float = 0.0
    transform: str = "original"

    def __post_init__(self) -> None:
        from reawarp.score.time import as_fraction
        if not self.sonority_id.strip():
            raise ValueError("sonority_id cannot be empty")
        onset = as_fraction(self.onset_beats)
        duration = as_fraction(self.duration_beats)
        if onset < 0 or duration <= 0:
            raise ValueError("sonority requires non-negative onset and positive duration")
        if any(not math.isfinite(float(pitch)) for pitch in self.pitches):
            raise ValueError("sonority pitches must be finite")
        if self.bass_pitch is not None and not math.isfinite(float(self.bass_pitch)):
            raise ValueError("bass_pitch must be finite")
        if not math.isfinite(float(self.tension)):
            raise ValueError("sonority tension must be finite")

    def to_score_record(self) -> dict[str, object]:
        return {
            "sonority_id": self.sonority_id,
            "onset_beats": self.onset_beats,
            "duration_beats": self.duration_beats,
            "pitches": list(self.pitches),
            "bass_pitch": self.bass_pitch,
            "tension": self.tension,
            "transform": self.transform,
        }

def pitch_field_from_score(score) -> PitchField:
    """Construct the optional pitch field carried by a Score."""
    return PitchField.from_score_context(score.harmonic_context)


def tuning_from_score(score, *, period_ratio: float = 2.0) -> EqualTemperamentTuning:
    """Build the Score's equal-period tuning adapter from its persisted tuning data."""
    return EqualTemperamentTuning(
        divisions_per_period=score.tuning_divisions_per_period,
        period_ratio=period_ratio,
        reference_pitch=score.tuning_reference_pitch,
        reference_frequency_hz=score.tuning_reference_frequency_hz,
        identifier=score.tuning_id,
    )
