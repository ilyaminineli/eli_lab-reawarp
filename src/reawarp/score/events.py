"""Synthesizer-independent musical events and automation lanes."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from reawarp.score.time import Beat, as_fraction

_EVENT_KINDS = {"note", "hit", "grain", "trigger", "control", "marker"}


def _json_copy(value: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("event parameters must contain JSON-compatible finite values") from exc


@dataclass(frozen=True, slots=True)
class MusicalEvent:
    """A musical intention expressed in score time, not in renderer-specific seconds."""

    event_id: str
    voice_id: str
    onset_beats: Beat
    duration_beats: Beat
    kind: str = "note"
    pitch: float | None = None
    frequency_hz: float | None = None
    velocity: float = 0.8
    articulation: str = "default"
    parameters: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    source_id: str | None = None
    seed: int | None = None
    channel: int | None = None
    tuning_id: str = "12tet"

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if not self.voice_id.strip():
            raise ValueError("voice_id cannot be empty")
        onset = as_fraction(self.onset_beats)
        duration = as_fraction(self.duration_beats)
        if onset < 0:
            raise ValueError("event onset cannot be negative")
        if duration < 0:
            raise ValueError("event duration cannot be negative")
        if self.kind not in _EVENT_KINDS:
            raise ValueError(f"unsupported event kind: {self.kind}")
        if self.pitch is not None and not math.isfinite(float(self.pitch)):
            raise ValueError("pitch must be finite")
        if self.frequency_hz is not None and (
                not math.isfinite(float(self.frequency_hz)) or self.frequency_hz <= 0
        ):
            raise ValueError("frequency_hz must be positive and finite")
        if self.kind == "note" and self.pitch is None and self.frequency_hz is None:
            raise ValueError("note events require pitch or frequency_hz")
        if not math.isfinite(float(self.velocity)) or not 0.0 <= self.velocity <= 1.0:
            raise ValueError("velocity must be between zero and one")
        if self.channel is not None and not 0 <= int(self.channel) <= 15:
            raise ValueError("MIDI channel must be between 0 and 15")
        if self.seed is not None and not isinstance(self.seed, int):
            raise ValueError("seed must be an integer or None")
        if not self.tuning_id.strip():
            raise ValueError("tuning_id cannot be empty")
        if not self.articulation.strip():
            raise ValueError("articulation cannot be empty")
        object.__setattr__(self, "onset_beats", onset)
        object.__setattr__(self, "duration_beats", duration)
        object.__setattr__(self, "pitch", None if self.pitch is None else float(self.pitch))
        object.__setattr__(
            self, "frequency_hz", None if self.frequency_hz is None else float(self.frequency_hz)
        )
        object.__setattr__(self, "velocity", float(self.velocity))
        object.__setattr__(self, "parameters", _json_copy(dict(self.parameters)))
        object.__setattr__(self, "tags", tuple(str(tag) for tag in self.tags))
        if self.channel is not None:
            object.__setattr__(self, "channel", int(self.channel))

    @property
    def end_beats(self) -> Beat:
        return self.onset_beats + self.duration_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "voice_id": self.voice_id,
            "onset_beats": str(self.onset_beats),
            "duration_beats": str(self.duration_beats),
            "kind": self.kind,
            "pitch": self.pitch,
            "frequency_hz": self.frequency_hz,
            "velocity": self.velocity,
            "articulation": self.articulation,
            "parameters": self.parameters,
            "tags": list(self.tags),
            "source_id": self.source_id,
            "seed": self.seed,
            "channel": self.channel,
            "tuning_id": self.tuning_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MusicalEvent":
        return cls(
            event_id=str(data["event_id"]),
            voice_id=str(data["voice_id"]),
            onset_beats=as_fraction(str(data["onset_beats"])),
            duration_beats=as_fraction(str(data["duration_beats"])),
            kind=str(data.get("kind", "note")),
            pitch=None if data.get("pitch") is None else float(data["pitch"]),
            frequency_hz=(
                None if data.get("frequency_hz") is None else float(data["frequency_hz"])
            ),
            velocity=float(data.get("velocity", 0.8)),
            articulation=str(data.get("articulation", "default")),
            parameters=dict(data.get("parameters", {})),
            tags=tuple(data.get("tags", ())),
            source_id=data.get("source_id"),
            seed=data.get("seed"),
            channel=data.get("channel"),
            tuning_id=str(data.get("tuning_id", "12tet")),
        )


@dataclass(frozen=True, slots=True)
class AutomationPoint:
    at: Fraction
    value: float

    def __post_init__(self) -> None:
        position = as_fraction(self.at)
        if position < 0:
            raise ValueError("automation point cannot be before zero")
        if not math.isfinite(float(self.value)):
            raise ValueError("automation value must be finite")
        object.__setattr__(self, "at", position)
        object.__setattr__(self, "value", float(self.value))

    def to_dict(self) -> dict[str, Any]:
        return {"at": str(self.at), "value": self.value}


@dataclass(frozen=True, slots=True)
class AutomationLane:
    """Versionable control curve with an explicit clock, unit, and interpolation policy."""

    target_id: str
    points: tuple[AutomationPoint, ...]
    unit: str = "normalized"
    time_basis: str = "beats"
    interpolation: str = "linear"
    loop_length: Fraction | None = None
    smoothing_seconds: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("automation target_id cannot be empty")
        if self.time_basis not in {"beats", "seconds", "frames"}:
            raise ValueError("automation time_basis must be beats, seconds, or frames")
        if self.interpolation not in {"step", "linear", "cubic", "exponential"}:
            raise ValueError("unsupported automation interpolation")
        points = tuple(self.points)
        if not points:
            raise ValueError("automation lane must contain at least one point")
        if any(a.at >= b.at for a, b in zip(points, points[1:])):
            raise ValueError("automation points must be strictly increasing")
        if self.loop_length is not None:
            loop = as_fraction(self.loop_length)
            if loop <= 0:
                raise ValueError("automation loop_length must be positive")
            object.__setattr__(self, "loop_length", loop)
        if not math.isfinite(float(self.smoothing_seconds)) or self.smoothing_seconds < 0:
            raise ValueError("smoothing_seconds must be finite and non-negative")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("automation minimum cannot exceed maximum")
        object.__setattr__(self, "points", points)

    def evaluate(self, at: Fraction | int | float | str) -> float:
        """Evaluate the lane; smoothing is retained as playback metadata for the host."""
        position = as_fraction(at)
        if position < 0:
            raise ValueError("automation evaluation position cannot be negative")
        if self.loop_length is not None:
            position %= self.loop_length
        if position <= self.points[0].at:
            value = self.points[0].value
        elif position >= self.points[-1].at:
            value = self.points[-1].value
        else:
            segment = next(
                i for i in range(len(self.points) - 1)
                if self.points[i].at <= position <= self.points[i + 1].at
            )
            left, right = self.points[segment], self.points[segment + 1]
            t = float((position - left.at) / (right.at - left.at))
            if self.interpolation == "step":
                value = left.value
            elif self.interpolation == "linear":
                value = left.value + (right.value - left.value) * t
            elif self.interpolation == "exponential":
                if left.value == 0 or right.value == 0 or left.value * right.value < 0:
                    value = left.value + (right.value - left.value) * t
                else:
                    sign = 1.0 if left.value > 0 else -1.0
                    value = sign * abs(left.value) * (
                            abs(right.value) / abs(left.value)
                    ) ** t
            else:
                previous = self.points[segment - 1] if segment > 0 else left
                following = (
                    self.points[segment + 2]
                    if segment + 2 < len(self.points) else right
                )
                span = float(right.at - left.at)
                tangent_left = (
                    (right.value - previous.value) / float(right.at - previous.at) * span
                    if previous.at != left.at else right.value - left.value
                )
                tangent_right = (
                    (following.value - left.value) / float(following.at - left.at) * span
                    if following.at != right.at else right.value - left.value
                )
                t2, t3 = t * t, t * t * t
                h00 = 2 * t3 - 3 * t2 + 1
                h10 = t3 - 2 * t2 + t
                h01 = -2 * t3 + 3 * t2
                h11 = t3 - t2
                value = (
                        h00 * left.value + h10 * tangent_left
                        + h01 * right.value + h11 * tangent_right
                )
        if self.minimum is not None:
            value = max(float(self.minimum), value)
        if self.maximum is not None:
            value = min(float(self.maximum), value)
        return float(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "points": [point.to_dict() for point in self.points],
            "unit": self.unit,
            "time_basis": self.time_basis,
            "interpolation": self.interpolation,
            "loop_length": None if self.loop_length is None else str(self.loop_length),
            "smoothing_seconds": self.smoothing_seconds,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationLane":
        return cls(
            target_id=str(data["target_id"]),
            points=tuple(
                AutomationPoint(as_fraction(str(item["at"])), float(item["value"]))
                for item in data["points"]
            ),
            unit=str(data.get("unit", "normalized")),
            time_basis=str(data.get("time_basis", "beats")),
            interpolation=str(data.get("interpolation", "linear")),
            loop_length=(
                None if data.get("loop_length") is None
                else as_fraction(str(data["loop_length"]))
            ),
            smoothing_seconds=float(data.get("smoothing_seconds", 0.0)),
            minimum=None if data.get("minimum") is None else float(data["minimum"]),
            maximum=None if data.get("maximum") is None else float(data["maximum"]),
        )
