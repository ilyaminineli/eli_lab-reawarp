"""Exact musical-time primitives, tempo maps, and meter maps."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import TypeAlias

Beat: TypeAlias = Fraction


def as_fraction(value: Fraction | int | float | str, *, max_denominator: int = 1_000_000) -> Fraction:
    """Convert user-facing numeric input into a stable rational musical value."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean values are not valid musical time")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("musical time must be finite")
        return Fraction(str(value)).limit_denominator(max_denominator)
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"invalid rational value: {value!r}") from exc
    raise TypeError(f"unsupported musical-time value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class TempoPoint:
    """Tempo at a beat position; interpolation describes the segment to the next point."""

    at_beats: Beat
    bpm: float
    interpolation_to_next: str = "step"

    def __post_init__(self) -> None:
        object.__setattr__(self, "at_beats", as_fraction(self.at_beats))
        if self.at_beats < 0:
            raise ValueError("tempo point cannot be before beat zero")
        if not math.isfinite(float(self.bpm)) or not 20.0 <= float(self.bpm) <= 400.0:
            raise ValueError("tempo must be between 20 and 400 BPM")
        if self.interpolation_to_next not in {"step", "linear"}:
            raise ValueError("tempo interpolation must be 'step' or 'linear'")
        object.__setattr__(self, "bpm", float(self.bpm))

    def to_dict(self) -> dict[str, object]:
        return {
            "at_beats": str(self.at_beats),
            "bpm": self.bpm,
            "interpolation_to_next": self.interpolation_to_next,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TempoPoint":
        return cls(
            at_beats=as_fraction(str(data["at_beats"])),
            bpm=float(data["bpm"]),
            interpolation_to_next=str(data.get("interpolation_to_next", "step")),
        )


@dataclass(frozen=True, slots=True)
class TempoMap:
    """Piecewise step/linear BPM map with centralised beat/second conversion."""

    points: tuple[TempoPoint, ...] = (TempoPoint(Fraction(0), 120.0),)

    def __post_init__(self) -> None:
        points = tuple(self.points)
        if not points:
            raise ValueError("tempo map must contain at least one point")
        if points[0].at_beats != 0:
            raise ValueError("tempo map must begin at beat zero")
        if any(a.at_beats >= b.at_beats for a, b in zip(points, points[1:])):
            raise ValueError("tempo points must be strictly increasing")
        object.__setattr__(self, "points", points)

    @classmethod
    def constant(cls, bpm: float) -> "TempoMap":
        return cls((TempoPoint(Fraction(0), bpm, "step"),))

    def bpm_at(self, beat: Beat | int | float | str) -> float:
        position = as_fraction(beat)
        if position < 0:
            raise ValueError("beat position cannot be negative")
        for index, point in enumerate(self.points):
            if index + 1 >= len(self.points) or position < self.points[index + 1].at_beats:
                if (
                        index + 1 < len(self.points)
                        and point.interpolation_to_next == "linear"
                ):
                    next_point = self.points[index + 1]
                    span = float(next_point.at_beats - point.at_beats)
                    offset = float(position - point.at_beats)
                    amount = min(1.0, max(0.0, offset / span))
                    return point.bpm + (next_point.bpm - point.bpm) * amount
                return point.bpm
        return self.points[-1].bpm

    @staticmethod
    def _segment_seconds(
            start_bpm: float, end_bpm: float, span_beats: float, linear: bool
    ) -> float:
        if span_beats <= 0:
            return 0.0
        if not linear or math.isclose(start_bpm, end_bpm, rel_tol=1e-12):
            return 60.0 * span_beats / start_bpm
        return 60.0 * span_beats * math.log(end_bpm / start_bpm) / (end_bpm - start_bpm)

    def beat_to_seconds(self, beat: Beat | int | float | str) -> float:
        """Integrate 60/BPM over musical beat position."""
        target = as_fraction(beat)
        if target < 0:
            raise ValueError("beat position cannot be negative")
        elapsed = 0.0
        for index, point in enumerate(self.points):
            if target <= point.at_beats:
                break
            next_point = self.points[index + 1] if index + 1 < len(self.points) else None
            segment_end = min(target, next_point.at_beats) if next_point else target
            span_total = (
                float(next_point.at_beats - point.at_beats)
                if next_point else float(segment_end - point.at_beats)
            )
            span_used = float(segment_end - point.at_beats)
            linear = bool(next_point and point.interpolation_to_next == "linear")
            if linear and next_point is not None:
                end_bpm = point.bpm + (next_point.bpm - point.bpm) * (
                        span_used / span_total
                )
            else:
                end_bpm = point.bpm
            elapsed += self._segment_seconds(point.bpm, end_bpm, span_used, linear)
            if segment_end >= target:
                break
        return elapsed

    def seconds_to_beat(
            self, seconds: float, *, max_denominator: int = 1_000_000
    ) -> Beat:
        """Invert the tempo map, returning a rational beat approximation."""
        if not math.isfinite(float(seconds)) or seconds < 0:
            raise ValueError("seconds must be finite and non-negative")
        remaining = float(seconds)
        for index, point in enumerate(self.points):
            next_point = self.points[index + 1] if index + 1 < len(self.points) else None
            if next_point is None:
                offset = remaining * point.bpm / 60.0
                return point.at_beats + Fraction(str(offset)).limit_denominator(max_denominator)
            span = float(next_point.at_beats - point.at_beats)
            linear = point.interpolation_to_next == "linear"
            full_seconds = self._segment_seconds(
                point.bpm, next_point.bpm, span, linear
            )
            if remaining <= full_seconds + 1e-12:
                if not linear or math.isclose(point.bpm, next_point.bpm, rel_tol=1e-12):
                    offset = remaining * point.bpm / 60.0
                else:
                    ratio = math.exp(
                        remaining * (next_point.bpm - point.bpm) / (60.0 * span)
                    )
                    instantaneous_bpm = point.bpm * ratio
                    offset = span * (instantaneous_bpm - point.bpm) / (
                            next_point.bpm - point.bpm
                    )
                offset = min(span, max(0.0, offset))
                return point.at_beats + Fraction(str(offset)).limit_denominator(max_denominator)
            remaining -= full_seconds
        return self.points[-1].at_beats

    def to_dict(self) -> list[dict[str, object]]:
        return [point.to_dict() for point in self.points]

    @classmethod
    def from_dict(cls, data: list[dict[str, object]]) -> "TempoMap":
        return cls(tuple(TempoPoint.from_dict(item) for item in data))


@dataclass(frozen=True, slots=True)
class MeterPoint:
    """Time signature beginning at an absolute beat position."""

    at_beats: Beat
    numerator: int = 4
    denominator: int = 4

    def __post_init__(self) -> None:
        object.__setattr__(self, "at_beats", as_fraction(self.at_beats))
        if self.at_beats < 0:
            raise ValueError("meter point cannot be before beat zero")
        if not 1 <= int(self.numerator) <= 32:
            raise ValueError("meter numerator must be between 1 and 32")
        if int(self.denominator) not in {1, 2, 4, 8, 16, 32, 64}:
            raise ValueError("meter denominator must be a power of two from 1 to 64")
        object.__setattr__(self, "numerator", int(self.numerator))
        object.__setattr__(self, "denominator", int(self.denominator))

    @property
    def bar_length_beats(self) -> Beat:
        return Fraction(self.numerator * 4, self.denominator)

    def to_dict(self) -> dict[str, object]:
        return {
            "at_beats": str(self.at_beats),
            "numerator": self.numerator,
            "denominator": self.denominator,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MeterPoint":
        return cls(
            at_beats=as_fraction(str(data["at_beats"])),
            numerator=int(data.get("numerator", 4)),
            denominator=int(data.get("denominator", 4)),
        )


@dataclass(frozen=True, slots=True)
class MeterMap:
    """Meter map independent of tempo and independent pattern/cycle lengths.

    A meter change begins a new bar. If it falls inside the previous meter's
    nominal bar, that partial bar still counts as one bar.
    """

    points: tuple[MeterPoint, ...] = (MeterPoint(Fraction(0), 4, 4),)

    def __post_init__(self) -> None:
        points = tuple(self.points)
        if not points:
            raise ValueError("meter map must contain at least one point")
        if points[0].at_beats != 0:
            raise ValueError("meter map must begin at beat zero")
        if any(a.at_beats >= b.at_beats for a, b in zip(points, points[1:])):
            raise ValueError("meter points must be strictly increasing")
        object.__setattr__(self, "points", points)

    def at(self, beat: Beat | int | float | str) -> MeterPoint:
        position = as_fraction(beat)
        if position < 0:
            raise ValueError("beat position cannot be negative")
        active = self.points[0]
        for point in self.points[1:]:
            if point.at_beats > position:
                break
            active = point
        return active

    def bar_and_beat(self, beat: Beat | int | float | str) -> tuple[int, Beat]:
        """Return a one-based bar number and zero-based quarter-note beat offset."""
        position = as_fraction(beat)
        if position < 0:
            raise ValueError("beat position cannot be negative")
        active_index = 0
        for index, point in enumerate(self.points):
            if point.at_beats > position:
                break
            active_index = index

        bars_before = 0
        for index in range(active_index):
            start = self.points[index].at_beats
            end = self.points[index + 1].at_beats
            bar_length = self.points[index].bar_length_beats
            segment_length = end - start
            bars_before += (segment_length.numerator * bar_length.denominator
                            + segment_length.denominator * bar_length.numerator - 1) // (
                                   segment_length.denominator * bar_length.numerator
                           )
        point = self.points[active_index]
        offset = position - point.at_beats
        bar_length = point.bar_length_beats
        bars_in_segment = int(offset // bar_length)
        beat_in_bar = offset - bars_in_segment * bar_length
        return bars_before + bars_in_segment + 1, beat_in_bar

    def to_dict(self) -> list[dict[str, object]]:
        return [point.to_dict() for point in self.points]

    @classmethod
    def from_dict(cls, data: list[dict[str, object]]) -> "MeterMap":
        return cls(tuple(MeterPoint.from_dict(item) for item in data))
