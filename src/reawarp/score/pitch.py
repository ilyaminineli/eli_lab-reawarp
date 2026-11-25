"""Tuning-aware pitch coordinates and optional pitch-field evaluation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class TuningSystem(Protocol):
    """Adapter interface for equal, just, regular-temperament, or custom tunings."""

    identifier: str
    divisions_per_period: int
    period_ratio: float

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
    """A tuning-aware pitch candidate with inspectable vocabulary matches."""

    pitch: float
    frequency_hz: float
    stability: float = 0.0
    tension: float = 0.0
    allowed: bool = True
    in_pitch_collection: bool = True
    in_allowed_intervals: bool = True
    in_register: bool = True

    @property
    def preference(self) -> float:
        """Net declared preference; hard eligibility remains separate."""
        return self.stability - self.tension


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
    centre_weight: float = 0.0
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
        if not math.isfinite(float(self.centre_weight)) or self.centre_weight < 0:
            raise ValueError("centre_weight must be finite and non-negative")
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
            centre_weight=float(context.get("centre_weight", 0.0)),
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
        in_collection = (
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
        in_intervals = (
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
        allowed = in_range and in_collection and in_intervals
        key = f"{pitch:g}"
        pitch_class_key = f"{pitch % tuning.divisions_per_period:g}"
        stability_weights = self.stability_weights or {}
        tension_weights = self.tension_weights or {}
        stability = float(stability_weights.get(key, stability_weights.get(pitch_class_key, 0.0)))
        tension = float(tension_weights.get(key, tension_weights.get(pitch_class_key, 0.0)))
        if self.mode == "centred" and self.centre_pitch is not None:
            stability += self.centre_weight / (1.0 + abs(pitch - self.centre_pitch))
        return PitchCandidate(
            pitch=pitch,
            frequency_hz=tuning.frequency_for_pitch(pitch),
            stability=stability,
            tension=tension,
            allowed=(allowed or not self.hard_constraint),
            in_pitch_collection=in_collection,
            in_allowed_intervals=in_intervals,
            in_register=in_range,
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
    """A tuning-aware sonority on a rational-beat timeline.

    Pitch values remain in the Score's tuning coordinates. Transformations
    retain their immediate source ID and explicit parameters for inspection.
    """

    sonority_id: str
    onset_beats: str
    duration_beats: str
    pitches: tuple[float, ...]
    bass_pitch: float | None = None
    tension: float = 0.0
    transform: str = "original"
    source_sonority_id: str | None = None
    transform_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from reawarp.score.time import as_fraction

        if not isinstance(self.sonority_id, str) or not self.sonority_id.strip():
            raise ValueError("sonority_id cannot be empty")
        if not isinstance(self.transform, str) or not self.transform.strip():
            raise ValueError("sonority transform cannot be empty")
        onset = as_fraction(self.onset_beats)
        duration = as_fraction(self.duration_beats)
        if onset < 0 or duration <= 0:
            raise ValueError("sonority requires non-negative onset and positive duration")
        pitches = tuple(float(value) for value in self.pitches)
        if not pitches or any(not math.isfinite(value) for value in pitches):
            raise ValueError("sonority pitches must be non-empty and finite")
        if self.bass_pitch is not None and not math.isfinite(float(self.bass_pitch)):
            raise ValueError("bass_pitch must be finite")
        if not math.isfinite(float(self.tension)):
            raise ValueError("sonority tension must be finite")
        if self.source_sonority_id is not None and (
            not isinstance(self.source_sonority_id, str)
            or not self.source_sonority_id.strip()
        ):
            raise ValueError("source_sonority_id must be a non-empty string")
        if not isinstance(self.transform_parameters, Mapping):
            raise ValueError("transform_parameters must be an object")
        parameters = json.loads(json.dumps(
            dict(self.transform_parameters), ensure_ascii=False, allow_nan=False
        ))
        object.__setattr__(self, "onset_beats", str(onset))
        object.__setattr__(self, "duration_beats", str(duration))
        object.__setattr__(self, "pitches", pitches)
        object.__setattr__(self, "tension", float(self.tension))
        object.__setattr__(self, "transform_parameters", parameters)

    def to_score_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "sonority_id": self.sonority_id,
            "onset_beats": self.onset_beats,
            "duration_beats": self.duration_beats,
            "pitches": list(self.pitches),
            "bass_pitch": self.bass_pitch,
            "tension": self.tension,
            "transform": self.transform,
        }
        if self.source_sonority_id is not None:
            record["source_sonority_id"] = self.source_sonority_id
        if self.transform_parameters:
            record["transform_parameters"] = dict(self.transform_parameters)
        return record

    @classmethod
    def from_score_record(cls, record: Mapping[str, object]) -> "Sonority":
        if not isinstance(record, Mapping):
            raise ValueError("sonority record must be an object")
        return cls(
            sonority_id=str(record.get("sonority_id", "")),
            onset_beats=str(record.get("onset_beats", "0")),
            duration_beats=str(record.get("duration_beats", "1")),
            pitches=tuple(float(value) for value in record.get("pitches", ())),
            bass_pitch=(
                None if record.get("bass_pitch") is None
                else float(record["bass_pitch"])
            ),
            tension=float(record.get("tension", 0.0)),
            transform=str(record.get("transform", "original")),
            source_sonority_id=(
                None if record.get("source_sonority_id") is None
                else str(record["source_sonority_id"])
            ),
            transform_parameters=dict(record.get("transform_parameters", {})),
        )

def pitch_field_from_score(score) -> PitchField:
    """Construct the optional pitch field carried by a Score."""
    return PitchField.from_score_context(score.harmonic_context)


def tuning_from_score(
    score,
    *,
    period_ratio: float | None = None,
) -> EqualTemperamentTuning:
    """Build the Score tuning adapter, including its persisted period ratio."""
    resolved_period_ratio = (
        float(getattr(score, "tuning_period_ratio", 2.0))
        if period_ratio is None else float(period_ratio)
    )
    return EqualTemperamentTuning(
        divisions_per_period=score.tuning_divisions_per_period,
        period_ratio=resolved_period_ratio,
        reference_pitch=score.tuning_reference_pitch,
        reference_frequency_hz=score.tuning_reference_frequency_hz,
        identifier=score.tuning_id,
    )
