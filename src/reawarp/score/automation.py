"""Typed automation targets and a shared score-to-frame control bus."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

import numpy as np

from reawarp.score.events import AutomationLane
from reawarp.score.timeline import RenderTimeline


@dataclass(frozen=True, slots=True)
class AutomationTarget:
    """Typed destination contract for one synthesis, FX, transport, or MIDI control."""

    target_id: str
    domain: str
    unit: str
    value_type: str = "continuous"
    minimum: float | None = None
    maximum: float | None = None
    interpolation: tuple[str, ...] = ("step", "linear", "cubic", "exponential")

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("automation target_id cannot be empty")
        if self.domain not in {"synthesis", "fx", "transport", "midi", "custom"}:
            raise ValueError("unsupported automation target domain")
        if self.value_type not in {"continuous", "integer", "boolean", "discrete"}:
            raise ValueError("unsupported automation value type")
        if not self.unit.strip():
            raise ValueError("automation target unit cannot be empty")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("automation target minimum cannot exceed maximum")
        if not self.interpolation or any(
            item not in {"step", "linear", "cubic", "exponential"}
            for item in self.interpolation
        ):
            raise ValueError("automation target has unsupported interpolation modes")


class AutomationTargetRegistry:
    """Registry for typed destinations. Unknown custom targets remain opt-in."""

    _MIDI_CC = re.compile(r"^midi\.cc\.(\d+)\.(\d+)$")

    def __init__(self, targets: Iterable[AutomationTarget] = ()) -> None:
        self._targets: dict[str, AutomationTarget] = {}
        for target in targets:
            self.register(target)

    def register(self, target: AutomationTarget) -> None:
        if target.target_id in self._targets:
            raise ValueError(f"automation target already registered: {target.target_id}")
        self._targets[target.target_id] = target

    def resolve(self, target_id: str) -> AutomationTarget | None:
        target = self._targets.get(target_id)
        if target is not None:
            return target
        match = self._MIDI_CC.fullmatch(target_id)
        if match:
            channel, controller = int(match.group(1)), int(match.group(2))
            if 0 <= channel <= 15 and 0 <= controller <= 127:
                return AutomationTarget(
                    target_id=target_id,
                    domain="midi",
                    unit="normalized",
                    minimum=0.0,
                    maximum=1.0,
                )
        return None

    def validate_lane(
        self,
        lane: AutomationLane,
        *,
        allow_custom: bool = False,
    ) -> AutomationTarget | None:
        target = self.resolve(lane.target_id)
        if target is None:
            if allow_custom:
                return None
            raise ValueError(f"unregistered automation target: {lane.target_id}")
        if lane.unit.casefold() != target.unit.casefold():
            raise ValueError(
                f"automation lane {lane.target_id!r} uses {lane.unit!r}; "
                f"target requires {target.unit!r}"
            )
        if lane.interpolation not in target.interpolation:
            raise ValueError(
                f"interpolation {lane.interpolation!r} is not supported by {lane.target_id!r}"
            )
        if lane.minimum is not None and target.minimum is not None:
            if lane.minimum < target.minimum:
                raise ValueError(f"automation lane {lane.target_id!r} exceeds target minimum")
        if lane.maximum is not None and target.maximum is not None:
            if lane.maximum > target.maximum:
                raise ValueError(f"automation lane {lane.target_id!r} exceeds target maximum")
        for point in lane.points:
            if target.minimum is not None and point.value < target.minimum:
                raise ValueError(
                    f"automation value for {lane.target_id!r} is below {target.minimum}"
                )
            if target.maximum is not None and point.value > target.maximum:
                raise ValueError(
                    f"automation value for {lane.target_id!r} exceeds {target.maximum}"
                )
            if target.value_type == "boolean" and point.value not in (0.0, 1.0):
                raise ValueError(f"{lane.target_id!r} accepts only boolean values")
            if target.value_type == "integer" and not float(point.value).is_integer():
                raise ValueError(f"{lane.target_id!r} accepts only integer values")
        return target

    @property
    def targets(self) -> tuple[AutomationTarget, ...]:
        return tuple(self._targets.values())


DEFAULT_AUTOMATION_TARGETS = AutomationTargetRegistry((
    AutomationTarget("synth.cutoff", "synthesis", "Hz", minimum=20.0, maximum=18_000.0),
    AutomationTarget("synth.resonance", "synthesis", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("synth.gain", "synthesis", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("synth.pitch", "synthesis", "semitones", minimum=-48.0, maximum=48.0),
    AutomationTarget("fx.insert.wet", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.send.space", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.send.echo", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.return.space.wet", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.return.echo.wet", "fx", "normalized", minimum=0.0, maximum=1.0),
))


@dataclass(frozen=True, slots=True)
class AutomationSamples:
    """Control-rate samples whose positions are absolute frames on the render clock."""

    frames: np.ndarray
    values: np.ndarray


class AutomationControlBus:
    """Evaluate all score control lanes against one absolute sample-frame timeline."""

    def __init__(
        self,
        lanes: Iterable[AutomationLane],
        timeline: RenderTimeline,
        *,
        source_sample_rate: int | None = None,
        registry: AutomationTargetRegistry = DEFAULT_AUTOMATION_TARGETS,
        allow_custom_targets: bool = True,
    ) -> None:
        self.timeline = timeline
        self.source_sample_rate = int(source_sample_rate or timeline.sample_rate)
        if self.source_sample_rate <= 0:
            raise ValueError("source_sample_rate must be positive")
        self.registry = registry
        self._lanes: dict[str, AutomationLane] = {}
        self._targets: dict[str, AutomationTarget | None] = {}
        for lane in lanes:
            if lane.target_id in self._lanes:
                raise ValueError(f"duplicate automation lane target: {lane.target_id}")
            target = registry.validate_lane(lane, allow_custom=allow_custom_targets)
            self._lanes[lane.target_id] = lane
            self._targets[lane.target_id] = target

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self._lanes)

    def target(self, target_id: str) -> AutomationTarget | None:
        if target_id not in self._lanes:
            raise KeyError(f"automation lane not found: {target_id}")
        return self._targets[target_id]

    def _lane_position(self, lane: AutomationLane, frame: int) -> Fraction:
        if lane.time_basis == "beats":
            return self.timeline.frame_to_beat(frame)
        seconds = Fraction(int(frame), self.timeline.sample_rate)
        if lane.time_basis == "seconds":
            return seconds
        return seconds * self.source_sample_rate

    def value_at_frame(self, target_id: str, frame: int) -> float:
        if isinstance(frame, bool) or int(frame) != frame or int(frame) < 0:
            raise ValueError("frame must be a non-negative integer")
        lane = self._lanes.get(target_id)
        if lane is None:
            raise KeyError(f"automation lane not found: {target_id}")
        return lane.evaluate(self._lane_position(lane, int(frame)))

    def sample(
        self,
        target_id: str,
        start_frame: int,
        end_frame: int,
        *,
        step_frames: int = 64,
    ) -> AutomationSamples:
        """Sample a lane at a fixed control rate; end_frame is exclusive."""
        if start_frame < 0 or end_frame < start_frame:
            raise ValueError("automation sample range must be non-negative and ordered")
        if step_frames <= 0:
            raise ValueError("step_frames must be positive")
        frames = (
            np.empty(0, dtype=np.int64)
            if start_frame == end_frame
            else np.arange(start_frame, end_frame, step_frames, dtype=np.int64)
        )
        values = np.fromiter(
            (self.value_at_frame(target_id, int(frame)) for frame in frames),
            dtype=np.float64,
            count=len(frames),
        ).astype(np.float32)
        return AutomationSamples(frames=frames, values=values)
