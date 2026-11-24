"""Extensible pitch/tuning contracts with a built-in equal-temperament reference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class TuningSystem(Protocol):
    """Adapter interface for equal, just, regular-temperament, or custom tunings."""

    identifier: str

    def frequency_for_pitch(self, pitch: float) -> float:
        """Return frequency in Hz for a tuning-system pitch coordinate."""

    def pitch_for_frequency(self, frequency_hz: float) -> float:
        """Return the tuning-system pitch coordinate nearest a frequency."""


@dataclass(frozen=True, slots=True)
class EqualTemperamentTuning:
    """Equal divisions of a period, defaulting to twelve-tone equal temperament."""

    divisions_per_period: int = 12
    period_ratio: float = 2.0
    reference_pitch: float = 69.0
    reference_frequency_hz: float = 440.0
    identifier: str = "12tet"

    def __post_init__(self) -> None:
        if self.divisions_per_period < 1:
            raise ValueError("divisions_per_period must be positive")
        if not math.isfinite(self.period_ratio) or self.period_ratio <= 1.0:
            raise ValueError("period_ratio must be finite and greater than one")
        if not math.isfinite(self.reference_pitch):
            raise ValueError("reference_pitch must be finite")
        if not math.isfinite(self.reference_frequency_hz) or self.reference_frequency_hz <= 0:
            raise ValueError("reference_frequency_hz must be positive and finite")
        if not self.identifier.strip():
            raise ValueError("tuning identifier cannot be empty")

    def frequency_for_pitch(self, pitch: float) -> float:
        if not math.isfinite(float(pitch)):
            raise ValueError("pitch must be finite")
        return self.reference_frequency_hz * self.period_ratio ** (
                (float(pitch) - self.reference_pitch) / self.divisions_per_period
        )

    def pitch_for_frequency(self, frequency_hz: float) -> float:
        if not math.isfinite(float(frequency_hz)) or frequency_hz <= 0:
            raise ValueError("frequency_hz must be positive and finite")
        return self.reference_pitch + self.divisions_per_period * math.log(
            float(frequency_hz) / self.reference_frequency_hz, self.period_ratio
        )


@dataclass(frozen=True, slots=True)
class Pitch:
    """A pitch coordinate plus its exact frequency and tuning provenance."""

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
    def from_frequency(
            cls, frequency_hz: float, tuning: TuningSystem
    ) -> "Pitch":
        return cls(
            value=tuning.pitch_for_frequency(float(frequency_hz)),
            frequency_hz=float(frequency_hz),
            tuning_id=tuning.identifier,
        )
