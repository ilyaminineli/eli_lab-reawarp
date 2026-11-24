"""Frame-accurate mapping between rational score time and the audio clock."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from reawarp.score.time import Beat, MeterMap, TempoMap, as_fraction


@dataclass(frozen=True, slots=True)
class RenderTimeline:
    """One conversion boundary for beats, seconds, sample frames, bars, and meter."""

    sample_rate: int
    tempo_map: TempoMap
    meter_map: MeterMap

    def __post_init__(self) -> None:
        if isinstance(self.sample_rate, bool) or int(self.sample_rate) <= 0:
            raise ValueError("sample_rate must be a positive integer")
        object.__setattr__(self, "sample_rate", int(self.sample_rate))

    def beat_to_seconds(self, beat: Beat | int | float | str) -> float:
        return self.tempo_map.beat_to_seconds(beat)

    def seconds_to_beat(self, seconds: float) -> Beat:
        return self.tempo_map.seconds_to_beat(seconds)

    def beat_to_frame(self, beat: Beat | int | float | str) -> int:
        """Convert an exact beat to its nearest sample frame; ties round upward."""
        seconds = self.beat_to_seconds(beat)
        return max(0, int(math.floor(seconds * self.sample_rate + 0.5)))

    def frame_to_seconds(self, frame: int) -> float:
        if isinstance(frame, bool) or int(frame) != frame or int(frame) < 0:
            raise ValueError("frame must be a non-negative integer")
        return int(frame) / float(self.sample_rate)

    def frame_to_beat(self, frame: int) -> Beat:
        return self.seconds_to_beat(self.frame_to_seconds(frame))

    def seconds_to_frame(self, seconds: float) -> int:
        if not math.isfinite(float(seconds)) or float(seconds) < 0.0:
            raise ValueError("seconds must be finite and non-negative")
        return max(0, int(math.floor(float(seconds) * self.sample_rate + 0.5)))

    def meter_at(self, beat: Beat | int | float | str):
        return self.meter_map.at(beat)

    def bar_and_beat(self, beat: Beat | int | float | str) -> tuple[int, Beat]:
        """Return one-based bar and zero-based quarter-note beat offset."""
        return self.meter_map.bar_and_beat(beat)

    def frame_bar_and_beat(self, frame: int) -> tuple[int, Beat]:
        return self.bar_and_beat(self.frame_to_beat(frame))

    def beat_span_to_frames(
        self,
        onset: Beat | int | float | str,
        duration: Beat | int | float | str,
    ) -> tuple[int, int]:
        start_beat = as_fraction(onset)
        length = as_fraction(duration)
        if start_beat < 0 or length < 0:
            raise ValueError("beat positions and durations cannot be negative")
        start = self.beat_to_frame(start_beat)
        end = self.beat_to_frame(start_beat + length)
        if length == 0:
            end = start + 1
        return start, end
