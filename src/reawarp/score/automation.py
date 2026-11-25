"""Typed automation targets, deterministic control sources, and a shared control bus."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, Mapping

import numpy as np

from reawarp.score.events import AutomationLane, AutomationPoint
from reawarp.score.time import as_fraction
from reawarp.score.timeline import RenderTimeline


def _finite_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("automation parameters must be finite JSON-compatible values") from exc


@dataclass(frozen=True, slots=True)
class AutomationTarget:
    """Typed destination contract for one synthesis, composition, spatial, FX, or MIDI control."""

    target_id: str
    domain: str
    unit: str
    value_type: str = "continuous"
    minimum: float | None = None
    maximum: float | None = None
    interpolation: tuple[str, ...] = ("step", "linear", "smooth", "cubic", "exponential")
    smoothing_seconds: float = 0.0
    hysteresis: float = 0.0
    update_clock: str = "control"
    control_rate_hz: float = 1_000.0

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("automation target_id cannot be empty")
        if self.domain not in {
            "synthesis", "composition", "spatial", "fx", "transport", "midi", "custom"
        }:
            raise ValueError("unsupported automation target domain")
        if self.value_type not in {"continuous", "integer", "boolean", "discrete"}:
            raise ValueError("unsupported automation value type")
        if not self.unit.strip():
            raise ValueError("automation target unit cannot be empty")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("automation target minimum cannot exceed maximum")
        if not self.interpolation or any(
            item not in {"step", "linear", "smooth", "cubic", "exponential"}
            for item in self.interpolation
        ):
            raise ValueError("automation target has unsupported interpolation modes")
        if not math.isfinite(float(self.smoothing_seconds)) or self.smoothing_seconds < 0:
            raise ValueError("target smoothing_seconds must be finite and non-negative")
        if not math.isfinite(float(self.hysteresis)) or self.hysteresis < 0:
            raise ValueError("target hysteresis must be finite and non-negative")
        if self.update_clock not in {"sample", "control", "event"}:
            raise ValueError("automation update_clock must be sample, control, or event")
        if not math.isfinite(float(self.control_rate_hz)) or self.control_rate_hz <= 0:
            raise ValueError("automation control_rate_hz must be positive and finite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "domain": self.domain,
            "unit": self.unit,
            "value_type": self.value_type,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "interpolation": list(self.interpolation),
            "smoothing_seconds": self.smoothing_seconds,
            "hysteresis": self.hysteresis,
            "update_clock": self.update_clock,
            "control_rate_hz": self.control_rate_hz,
        }


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
                    update_clock="event",
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
            if (
                point.interpolation_to_next is not None
                and point.interpolation_to_next not in target.interpolation
            ):
                raise ValueError(
                    f"per-point interpolation {point.interpolation_to_next!r} "
                    f"is not supported by {lane.target_id!r}"
                )
            if target.minimum is not None and point.value < target.minimum:
                raise ValueError(
                    f"automation value for {lane.target_id!r} is below target minimum {target.minimum}"
                )
            if target.maximum is not None and point.value > target.maximum:
                raise ValueError(
                    f"automation value for {lane.target_id!r} exceeds target maximum {target.maximum}"
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
    AutomationTarget("synth.attack", "synthesis", "seconds", minimum=0.0, maximum=30.0),
    AutomationTarget("synth.decay", "synthesis", "seconds", minimum=0.0, maximum=30.0),
    AutomationTarget("synth.release", "synthesis", "seconds", minimum=0.0, maximum=30.0),
    AutomationTarget("synth.modulation.depth", "synthesis", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("synth.modulation.rate", "synthesis", "Hz", minimum=0.0, maximum=40.0),
    AutomationTarget("synth.wavetable.position", "synthesis", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("synth.partial.balance", "synthesis", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("synth.grain.size", "synthesis", "milliseconds", minimum=1.0, maximum=500.0),
    AutomationTarget("synth.grain.position", "synthesis", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("synth.grain.density", "synthesis", "Hz", minimum=0.0, maximum=200.0),
    AutomationTarget("event.velocity_scale", "composition", "ratio", minimum=0.0, maximum=2.0),
    AutomationTarget("event.probability", "composition", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("role.activity", "composition", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("role.density", "composition", "events_per_beat", minimum=0.0, maximum=64.0),
    AutomationTarget("role.syncopation", "composition", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("role.articulation", "composition", "index", value_type="integer", minimum=0, maximum=127, update_clock="event"),
    AutomationTarget("sample.mix", "composition", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("spatial.pan", "spatial", "normalized", minimum=-1.0, maximum=1.0),
    AutomationTarget("spatial.width", "spatial", "ratio", minimum=0.0, maximum=2.0),
    AutomationTarget("fx.insert.wet", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.send.space", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.send.echo", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.return.space.wet", "fx", "normalized", minimum=0.0, maximum=1.0),
    AutomationTarget("fx.return.echo.wet", "fx", "normalized", minimum=0.0, maximum=1.0),
))


@dataclass(frozen=True, slots=True)
class AutomationSource:
    """Serializable deterministic generator for a reusable, beat-addressed control source.

    Supported kinds are lfo, envelope, stepped, random_walk, and phrase_curve.
    Generated source lanes use the virtual target ID source.<source_id>.
    """

    source_id: str
    kind: str
    start: Fraction
    end: Fraction
    parameters: dict[str, Any] | None = None
    seed: int = 0
    minimum: float = 0.0
    maximum: float = 1.0
    interpolation: str = "linear"

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("automation source_id cannot be empty")
        if self.kind not in {"lfo", "envelope", "stepped", "random_walk", "phrase_curve"}:
            raise ValueError("unsupported automation source kind")
        start, end = as_fraction(self.start), as_fraction(self.end)
        if start < 0 or end <= start:
            raise ValueError("automation source requires 0 <= start < end")
        if self.minimum > self.maximum:
            raise ValueError("automation source minimum cannot exceed maximum")
        if not math.isfinite(float(self.minimum)) or not math.isfinite(float(self.maximum)):
            raise ValueError("automation source bounds must be finite")
        if self.interpolation not in {"step", "linear", "smooth", "cubic", "exponential"}:
            raise ValueError("unsupported automation source interpolation")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("automation source seed must be an integer")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "parameters", _finite_json_object(self.parameters or {}))

    @property
    def target_id(self) -> str:
        return f"source.{self.source_id}"

    def _positions(self, count: int) -> list[Fraction]:
        return [
            self.start + (self.end - self.start) * Fraction(index, count - 1)
            for index in range(count)
        ]

    def to_lane(self) -> AutomationLane:
        """Generate a reproducible lane without mutating the source definition."""
        duration = self.end - self.start
        parameters = self.parameters or {}
        points: list[AutomationPoint] = []

        if self.kind == "lfo":
            count = int(parameters.get("sample_count", 128))
            if not 2 <= count <= 4096:
                raise ValueError("LFO sample_count must be between 2 and 4096")
            period = float(parameters.get("period_beats", 4.0))
            phase = float(parameters.get("phase_cycles", 0.0))
            center = float(parameters.get("center", 0.5))
            depth = float(parameters.get("depth", 0.5))
            waveform = str(parameters.get("waveform", "sine"))
            if not math.isfinite(period) or period <= 0 or not all(
                math.isfinite(value) for value in (phase, center, depth)
            ):
                raise ValueError("LFO period, phase, centre, and depth must be finite; period > 0")
            if waveform not in {"sine", "triangle", "square", "saw"}:
                raise ValueError("LFO waveform must be sine, triangle, square, or saw")
            positions = self._positions(count)
            for index, position in enumerate(positions):
                cycles = float((position - self.start) / Fraction(str(period))) + phase
                phase_value = cycles % 1.0
                if waveform == "triangle":
                    wave = 1.0 - 4.0 * abs(phase_value - 0.5)
                elif waveform == "square":
                    wave = 1.0 if phase_value < 0.5 else -1.0
                elif waveform == "saw":
                    wave = 2.0 * phase_value - 1.0
                else:
                    wave = math.sin(2.0 * math.pi * cycles)
                segment_curve = (
                    "step" if waveform == "square" and index < len(positions) - 1
                    else None
                )
                points.append(AutomationPoint(
                    position, center + depth * wave, segment_curve
                ))

        elif self.kind in {"envelope", "phrase_curve"}:
            if self.kind == "envelope":
                shape = parameters.get("shape", [[0.0, 0.0], [0.15, 1.0], [1.0, 0.0]])
                interpolation = str(parameters.get("curve", "smooth"))
            else:
                values = parameters.get("values", [0.0, 0.7, 0.35, 1.0])
                if not isinstance(values, list) or len(values) < 2:
                    raise ValueError("phrase_curve requires at least two values")
                shape = [[index / (len(values) - 1), value] for index, value in enumerate(values)]
                interpolation = str(parameters.get("curve", self.interpolation))
            if not isinstance(shape, list) or len(shape) < 2:
                raise ValueError(f"{self.kind} requires at least two [position, value] points")
            if interpolation not in {"step", "linear", "smooth", "cubic", "exponential"}:
                raise ValueError("unsupported source curve interpolation")
            normalized: list[tuple[float, float]] = []
            for item in shape:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    raise ValueError("source shape points must be [normalized_position, value]")
                at, value = float(item[0]), float(item[1])
                if not math.isfinite(at) or not math.isfinite(value) or not 0.0 <= at <= 1.0:
                    raise ValueError("source shape positions must be within 0..1 and values finite")
                normalized.append((at, value))
            if normalized[0][0] != 0.0 or normalized[-1][0] != 1.0:
                raise ValueError("source shape must begin at 0 and end at 1")
            if any(a[0] >= b[0] for a, b in zip(normalized, normalized[1:])):
                raise ValueError("source shape positions must be strictly increasing")
            for index, (at, value) in enumerate(normalized):
                points.append(AutomationPoint(
                    self.start + duration * Fraction(str(at)),
                    value,
                    interpolation if index < len(normalized) - 1 else None,
                ))

        elif self.kind == "stepped":
            values = parameters.get("values", [0.0, 1.0, 0.5, 0.8])
            step_beats = as_fraction(str(parameters.get("step_beats", 1)))
            repeat = bool(parameters.get("repeat", True))
            if not isinstance(values, list) or not values:
                raise ValueError("stepped source requires a non-empty values list")
            if step_beats <= 0:
                raise ValueError("stepped source step_beats must be positive")
            cursor = self.start
            index = 0
            while cursor < self.end:
                value = float(values[index % len(values)] if repeat else values[min(index, len(values) - 1)])
                if not math.isfinite(value):
                    raise ValueError("stepped source values must be finite")
                points.append(AutomationPoint(cursor, value, "step"))
                cursor += step_beats
                index += 1
                if index > 100_000:
                    raise ValueError("stepped source exceeds 100000 points")
            points.append(AutomationPoint(self.end, points[-1].value))

        else:
            step_beats = as_fraction(str(parameters.get("step_beats", 1)))
            step_size = float(parameters.get("step_size", 0.12))
            initial = float(parameters.get("initial", (self.minimum + self.maximum) / 2.0))
            if step_beats <= 0 or not math.isfinite(step_size) or step_size < 0:
                raise ValueError("random_walk step_beats must be positive and step_size non-negative")
            if not self.minimum <= initial <= self.maximum:
                raise ValueError("random_walk initial value must lie inside source bounds")
            seed_material = f"reawarp:automation-source:v1:{self.seed}:{self.source_id}".encode("utf-8")
            seed = int.from_bytes(hashlib.blake2b(seed_material, digest_size=8).digest(), "little")
            rng = np.random.default_rng(seed)
            cursor = self.start
            value = initial
            points.append(AutomationPoint(cursor, value))
            index = 0
            while cursor < self.end:
                cursor = min(self.end, cursor + step_beats)
                value += float(rng.uniform(-step_size, step_size))
                span = self.maximum - self.minimum
                if span > 0:
                    period = 2.0 * span
                    folded = (value - self.minimum) % period
                    value = self.minimum + (folded if folded <= span else period - folded)
                else:
                    value = self.minimum
                points.append(AutomationPoint(cursor, value, "linear"))
                index += 1
                if index > 100_000:
                    raise ValueError("random_walk source exceeds 100000 points")

        clipped = tuple(
            AutomationPoint(
                point.at,
                min(self.maximum, max(self.minimum, point.value)),
                point.interpolation_to_next,
            )
            for point in points
        )
        return AutomationLane(
            target_id=self.target_id,
            points=clipped,
            unit="normalized",
            time_basis="beats",
            interpolation=self.interpolation,
            minimum=self.minimum,
            maximum=self.maximum,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "start": str(self.start),
            "end": str(self.end),
            "parameters": self.parameters,
            "seed": self.seed,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "interpolation": self.interpolation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationSource":
        return cls(
            source_id=str(data["source_id"]),
            kind=str(data["kind"]),
            start=as_fraction(str(data["start"])),
            end=as_fraction(str(data["end"])),
            parameters=dict(data.get("parameters", {})),
            seed=int(data.get("seed", 0)),
            minimum=float(data.get("minimum", 0.0)),
            maximum=float(data.get("maximum", 1.0)),
            interpolation=str(data.get("interpolation", "linear")),
        )


@dataclass(frozen=True, slots=True)
class AutomationModulation:
    """Explicit connection from a generated source to one typed destination."""

    source_id: str
    destination_target_id: str
    amount: float = 0.25
    polarity: str = "bipolar"
    mode: str = "add"
    retrigger: str = "free"
    smoothing_seconds: float = 0.0
    hysteresis: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    scope: str = "global"
    scope_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.destination_target_id.strip():
            raise ValueError("modulation source and destination IDs cannot be empty")
        if self.polarity not in {"unipolar", "bipolar"}:
            raise ValueError("modulation polarity must be unipolar or bipolar")
        if self.mode not in {"add", "multiply"}:
            raise ValueError("modulation mode must be add or multiply")
        if self.retrigger not in {"free", "event", "role", "section"}:
            raise ValueError("modulation retrigger must be free, event, role, or section")
        if not math.isfinite(float(self.amount)):
            raise ValueError("modulation amount must be finite")
        if not math.isfinite(float(self.smoothing_seconds)) or self.smoothing_seconds < 0:
            raise ValueError("modulation smoothing_seconds must be finite and non-negative")
        if not math.isfinite(float(self.hysteresis)) or self.hysteresis < 0:
            raise ValueError("modulation hysteresis must be finite and non-negative")
        if self.minimum is not None and not math.isfinite(float(self.minimum)):
            raise ValueError("modulation minimum must be finite")
        if self.maximum is not None and not math.isfinite(float(self.maximum)):
            raise ValueError("modulation maximum must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("modulation minimum cannot exceed maximum")
        if self.scope not in {"global", "section", "role", "event"}:
            raise ValueError("modulation scope must be global, section, role, or event")
        if self.scope == "global" and self.scope_id is not None:
            raise ValueError("global modulation cannot have a scope_id")
        if self.scope != "global" and not str(self.scope_id or "").strip():
            raise ValueError(f"{self.scope} modulation requires a scope_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "destination_target_id": self.destination_target_id,
            "amount": self.amount,
            "polarity": self.polarity,
            "mode": self.mode,
            "retrigger": self.retrigger,
            "smoothing_seconds": self.smoothing_seconds,
            "hysteresis": self.hysteresis,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "scope": self.scope,
            "scope_id": self.scope_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationModulation":
        return cls(
            source_id=str(data["source_id"]),
            destination_target_id=str(data["destination_target_id"]),
            amount=float(data.get("amount", 0.25)),
            polarity=str(data.get("polarity", "bipolar")),
            mode=str(data.get("mode", "add")),
            retrigger=str(data.get("retrigger", "free")),
            smoothing_seconds=float(data.get("smoothing_seconds", 0.0)),
            hysteresis=float(data.get("hysteresis", 0.0)),
            minimum=None if data.get("minimum") is None else float(data["minimum"]),
            maximum=None if data.get("maximum") is None else float(data["maximum"]),
            scope=str(data.get("scope", "global")),
            scope_id=None if data.get("scope_id") is None else str(data["scope_id"]),
        )


@dataclass(frozen=True, slots=True)
class AutomationSamples:
    """Control-rate samples whose positions are absolute frames on the render clock."""

    frames: np.ndarray
    values: np.ndarray


class AutomationControlBus:
    """Evaluate scoped lanes and deterministic modulation on one absolute frame clock.

    Scope precedence is global → section → role → event. Absolute lanes replace the
    value at their level; relative lanes add an offset. A caller with no context sees
    only the global lane, preserving the original value_at_frame API.
    """

    _SCOPE_ORDER = {"global": 0, "section": 1, "role": 2, "event": 3}

    def __init__(
        self,
        lanes: Iterable[AutomationLane],
        timeline: RenderTimeline,
        *,
        source_sample_rate: int | None = None,
        registry: AutomationTargetRegistry = DEFAULT_AUTOMATION_TARGETS,
        allow_custom_targets: bool = True,
        sources: Iterable[AutomationSource] = (),
        modulations: Iterable[AutomationModulation] = (),
        event_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.timeline = timeline
        self.source_sample_rate = int(source_sample_rate or timeline.sample_rate)
        if self.source_sample_rate <= 0:
            raise ValueError("source_sample_rate must be positive")
        self.registry = registry
        self._lanes: dict[str, list[AutomationLane]] = {}
        self._targets: dict[str, AutomationTarget | None] = {}
        self._event_contexts = {
            str(key): dict(value) for key, value in (event_contexts or {}).items()
        }
        source_items = tuple(sources)
        source_lanes = {
            source.source_id: source.to_lane() for source in source_items
        }
        lane_items = tuple(lanes) + tuple(source_lanes.values())
        lane_keys: set[tuple[str, str, str | None]] = set()
        for lane in lane_items:
            key = (lane.target_id, lane.scope, lane.scope_id)
            if key in lane_keys:
                raise ValueError(
                    "duplicate automation lane target/scope: "
                    f"{lane.target_id}/{lane.scope}/{lane.scope_id}"
                )
            lane_keys.add(key)
            target = registry.validate_lane(
                lane,
                allow_custom=allow_custom_targets or lane.target_id.startswith("source."),
            )
            self._lanes.setdefault(lane.target_id, []).append(lane)
            self._targets[lane.target_id] = target
        for target_lanes in self._lanes.values():
            target_lanes.sort(key=lambda lane: self._SCOPE_ORDER[lane.scope])
        self._sources = {source.source_id: source for source in source_items}
        # Materialise generated curves once; control sampling should be O(1) in
        # source generation cost, not regenerate an entire random walk per sample.
        self._source_lanes = source_lanes
        self._modulations: dict[str, list[AutomationModulation]] = {}
        for modulation in modulations:
            if modulation.source_id not in self._sources:
                raise ValueError(f"unknown modulation source: {modulation.source_id}")
            destination = modulation.destination_target_id
            target = registry.resolve(destination)
            if target is None and not allow_custom_targets:
                raise ValueError(f"unregistered modulation destination: {destination}")
            self._targets.setdefault(destination, target)
            self._modulations.setdefault(destination, []).append(modulation)

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self._lanes, *self._modulations)))

    def target(self, target_id: str) -> AutomationTarget | None:
        if target_id not in self._lanes and target_id not in self._modulations:
            raise KeyError(f"automation target not found: {target_id}")
        return self._targets.get(target_id)

    def _lane_position(self, lane: AutomationLane, frame: int) -> Fraction:
        frame = max(0, int(frame))
        if lane.time_basis == "beats":
            return self.timeline.frame_to_beat(frame)
        seconds = Fraction(frame, self.timeline.sample_rate)
        if lane.time_basis == "seconds":
            return seconds
        return seconds * self.source_sample_rate

    def _context(self, event_id: str | None, context: Mapping[str, Any] | None) -> dict[str, Any]:
        result = dict(self._event_contexts.get(str(event_id), {})) if event_id is not None else {}
        if context:
            result.update(context)
        return result

    def _value_before_modulation(
        self,
        target_id: str,
        frame: int,
        *,
        default_value: float | None,
        context: Mapping[str, Any],
    ) -> float | None:
        value = None if default_value is None else float(default_value)
        role_id = context.get("role_id")
        section_id = context.get("section_id")
        event_id = context.get("event_id")
        for lane in self._lanes.get(target_id, ()):
            if lane.scope == "global":
                matches = True
            elif lane.scope == "section":
                matches = section_id is not None and str(section_id) == lane.scope_id
            elif lane.scope == "role":
                matches = role_id is not None and str(role_id) == lane.scope_id
            else:
                matches = event_id is not None and str(event_id) == lane.scope_id
            if not matches:
                continue
            lane_value = lane.evaluate(
                self._lane_position(lane, frame),
                before_first=value,
            )
            if lane.value_mode == "relative":
                value = (0.0 if value is None else value) + lane_value
            else:
                value = lane_value
        return value

    def value_for_context(
        self,
        target_id: str,
        frame: int,
        *,
        event_id: str | None = None,
        default_value: float | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> float:
        """Resolve global/section/role/event precedence and then apply modulations."""
        if isinstance(frame, bool) or int(frame) != frame or int(frame) < 0:
            raise ValueError("frame must be a non-negative integer")
        if target_id not in self._lanes and target_id not in self._modulations:
            raise KeyError(f"automation lane not found: {target_id}")
        resolved_context = self._context(event_id, context)
        resolved_context["event_id"] = event_id or resolved_context.get("event_id")
        value = self._value_before_modulation(
            target_id, int(frame), default_value=default_value, context=resolved_context
        )
        for modulation in self._modulations.get(target_id, ()):
            scope_key = {
                "global": None,
                "section": "section_id",
                "role": "role_id",
                "event": "event_id",
            }[modulation.scope]
            if scope_key is not None and str(resolved_context.get(scope_key)) != modulation.scope_id:
                continue
            source_lane = self._source_lanes[modulation.source_id]
            origin_key = {
                "free": None,
                "event": "event_onset_frame",
                "role": "role_onset_frame",
                "section": "section_onset_frame",
            }[modulation.retrigger]
            origin = resolved_context.get(origin_key) if origin_key else None
            source_frame = max(0, int(frame) - int(origin)) if origin is not None else int(frame)
            source_position = self._lane_position(source_lane, source_frame)
            if origin is not None:
                source_position += self._sources[modulation.source_id].start
            source_value = source_lane.evaluate(source_position)
            signal = (
                2.0 * source_value - 1.0
                if modulation.polarity == "bipolar"
                else min(1.0, max(0.0, source_value))
            )
            base = 0.0 if value is None else value
            if modulation.mode == "multiply":
                value = base * (1.0 + signal * modulation.amount)
            else:
                value = base + signal * modulation.amount
            if modulation.minimum is not None:
                value = max(modulation.minimum, value)
            if modulation.maximum is not None:
                value = min(modulation.maximum, value)
        if value is None:
            value = 0.0
        target = self._targets.get(target_id)
        if target is not None:
            if target.minimum is not None:
                value = max(target.minimum, value)
            if target.maximum is not None:
                value = min(target.maximum, value)
        return float(value)

    def value_at_frame(
        self,
        target_id: str,
        frame: int,
        *,
        default_value: float | None = None,
    ) -> float:
        return self.value_for_context(target_id, frame, default_value=default_value)

    def _smoothing_parameters(
        self,
        target_id: str,
        event_id: str | None,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[float, float, bool]:
        target = self._targets.get(target_id)
        smoothing = target.smoothing_seconds if target is not None else 0.0
        hysteresis = target.hysteresis if target is not None else 0.0
        continuous = target is None or target.value_type == "continuous"
        resolved_context = self._context(event_id, context)
        resolved_context["event_id"] = event_id or resolved_context.get("event_id")
        for lane in self._lanes.get(target_id, ()):
            applies = (
                lane.scope == "global"
                or (lane.scope == "role" and resolved_context.get("role_id") == lane.scope_id)
                or (lane.scope == "section" and resolved_context.get("section_id") == lane.scope_id)
                or (lane.scope == "event" and resolved_context.get("event_id") == lane.scope_id)
            )
            if applies:
                smoothing = max(smoothing, lane.smoothing_seconds)
                hysteresis = max(hysteresis, lane.hysteresis)
        for modulation in self._modulations.get(target_id, ()):
            scope_key = {
                "global": None,
                "section": "section_id",
                "role": "role_id",
                "event": "event_id",
            }[modulation.scope]
            if scope_key is not None and str(resolved_context.get(scope_key)) != modulation.scope_id:
                continue
            smoothing = max(smoothing, modulation.smoothing_seconds)
            hysteresis = max(hysteresis, modulation.hysteresis)
        return smoothing, hysteresis, continuous

    def sample(
        self,
        target_id: str,
        start_frame: int,
        end_frame: int,
        *,
        step_frames: int = 64,
        default_value: float | None = None,
        event_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> AutomationSamples:
        """Sample a lane at a fixed control rate; end_frame is exclusive.

        Hysteresis is applied as a deadband before a deterministic one-pole smoother.
        Both operate on requested control-rate samples, not on the audio-rate buffer.
        """
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
            (
                self.value_for_context(
                    target_id,
                    int(frame),
                    event_id=event_id,
                    default_value=default_value,
                    context=context,
                )
                for frame in frames
            ),
            dtype=np.float64,
            count=len(frames),
        )
        if len(values):
            smoothing, hysteresis, continuous = self._smoothing_parameters(
                target_id, event_id, context
            )
            if continuous and hysteresis > 0.0:
                held = float(values[0])
                for index in range(1, len(values)):
                    candidate = float(values[index])
                    if abs(candidate - held) < hysteresis:
                        values[index] = held
                    else:
                        held = candidate
            if continuous and smoothing > 0.0 and len(values) > 1:
                alpha = 1.0 - math.exp(
                    -float(step_frames) / (float(self.timeline.sample_rate) * smoothing)
                )
                for index in range(1, len(values)):
                    values[index] = values[index - 1] + alpha * (
                        values[index] - values[index - 1]
                    )
        return AutomationSamples(frames=frames, values=values.astype(np.float32))


__all__ = [
    "AutomationControlBus",
    "AutomationModulation",
    "AutomationSamples",
    "AutomationSource",
    "AutomationTarget",
    "AutomationTargetRegistry",
    "DEFAULT_AUTOMATION_TARGETS",
]
