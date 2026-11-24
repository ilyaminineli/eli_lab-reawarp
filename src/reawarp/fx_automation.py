"""Beat-addressed, deterministic FX automation lanes.

Automation is evaluated offline from musical beats to sample frames. It contains
no random sources and can therefore be replayed identically for the same tempo,
sample rate, routing, and lane data.
"""
from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from reawarp.score.automation import (
    AutomationTarget,
    AutomationTargetRegistry,
    DEFAULT_AUTOMATION_TARGETS,
)
from reawarp.score.events import AutomationLane, AutomationPoint
from reawarp.score.model import Score

FX_AUTOMATION_SCHEMA_VERSION = 1
FX_AUTOMATION_CURVES = ("hold", "linear", "smooth")
FX_AUTOMATION_MAX_POINTS = 128


def _number(value: Any, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number


def automation_targets(stem_names: Sequence[str]) -> tuple[str, ...]:
    """Return the small, explicit set of automatable routing controls."""
    targets = ["bus.space.wet", "bus.echo.wet"]
    for name in stem_names:
        targets.extend((
            f"stem.{name}.insert_wet",
            f"stem.{name}.send.space",
            f"stem.{name}.send.echo",
        ))
    return tuple(targets)


def normalise_fx_automation(
    payload: Mapping[str, Any] | None,
    stem_names: Sequence[str],
) -> dict[str, Any]:
    """Validate automation JSON and normalise ordered beat/value/curve points."""
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise ValueError("FX automation must be a JSON object")
    version = payload.get("schema_version", FX_AUTOMATION_SCHEMA_VERSION)
    if version != FX_AUTOMATION_SCHEMA_VERSION:
        raise ValueError(f"Unsupported FX automation schema: {version!r}")
    lanes = payload.get("lanes", {})
    if not isinstance(lanes, Mapping):
        raise ValueError("FX automation lanes must be a JSON object")
    allowed = set(automation_targets(stem_names))
    unknown = set(lanes) - allowed
    if unknown:
        raise ValueError("Unknown automation target(s): " + ", ".join(sorted(map(str, unknown))))

    result: dict[str, list[dict[str, float | str]]] = {}
    for target, raw_points in lanes.items():
        if not isinstance(raw_points, Sequence) or isinstance(raw_points, (str, bytes)):
            raise ValueError(f"Automation lane {target!r} must be a point array")
        if not 1 <= len(raw_points) <= FX_AUTOMATION_MAX_POINTS:
            raise ValueError(
                f"Automation lane {target!r} must contain 1–{FX_AUTOMATION_MAX_POINTS} points"
            )
        points: list[dict[str, float | str]] = []
        previous = -1.0
        for index, raw in enumerate(raw_points, start=1):
            if not isinstance(raw, Mapping):
                raise ValueError(f"{target} point {index} must be an object")
            beat = _number(raw.get("beat"), f"{target} point {index} beat", 0.0, 1_000_000.0)
            value = _number(raw.get("value"), f"{target} point {index} value", 0.0, 1.0)
            curve = str(raw.get("curve", "linear"))
            if curve not in FX_AUTOMATION_CURVES:
                raise ValueError(
                    f"{target} point {index} curve must be one of {', '.join(FX_AUTOMATION_CURVES)}"
                )
            if beat <= previous:
                raise ValueError(f"{target} points must have strictly increasing beat positions")
            previous = beat
            points.append({"beat": beat, "value": value, "curve": curve})
        result[str(target)] = points
    return {"schema_version": FX_AUTOMATION_SCHEMA_VERSION, "lanes": result}


def automation_envelope(
    points: Sequence[Mapping[str, Any]] | None,
    *,
    frames: int,
    sample_rate: int,
    bpm: float,
    default_value: float,
) -> np.ndarray:
    """Evaluate a musical automation lane into a float32 per-frame envelope.

    The first point does not retroactively affect the start of the track: the
    supplied default is held until that point. The last point holds indefinitely.
    The curve stored on a point defines the segment leading to the next point.
    """
    if frames < 0:
        raise ValueError("frames cannot be negative")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    tempo = _number(bpm, "bpm", 1.0, 1000.0)
    default = _number(default_value, "default_value", 0.0, 1.0)
    envelope = np.full(int(frames), default, dtype=np.float32)
    if frames == 0 or not points:
        return envelope

    normalized = []
    previous = -1.0
    for index, point in enumerate(points, start=1):
        beat = _number(point.get("beat"), f"point {index} beat", 0.0, 1_000_000.0)
        value = _number(point.get("value"), f"point {index} value", 0.0, 1.0)
        curve = str(point.get("curve", "linear"))
        if curve not in FX_AUTOMATION_CURVES:
            raise ValueError(f"unsupported automation curve: {curve}")
        if beat <= previous:
            raise ValueError("automation points must be strictly increasing")
        previous = beat
        frame = int(round(beat * 60.0 * int(sample_rate) / tempo))
        normalized.append((frame, value, curve))

    for index, (start, value, curve) in enumerate(normalized):
        start = min(max(0, start), frames)
        if index + 1 >= len(normalized):
            envelope[start:] = value
            break
        end, next_value, _ = normalized[index + 1]
        end = min(max(start, end), frames)
        if end <= start:
            continue
        if curve == "hold":
            envelope[start:end] = value
            continue
        phase = np.arange(end - start, dtype=np.float64) / float(end - start)
        if curve == "smooth":
            phase = phase * phase * (3.0 - 2.0 * phase)
        envelope[start:end] = (value + (next_value - value) * phase).astype(np.float32)
    return envelope


def load_fx_automation(
    path: str | Path, stem_names: Sequence[str]
) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return normalise_fx_automation(payload, stem_names)


def save_fx_automation(
    path: str | Path,
    automation: Mapping[str, Any],
    stem_names: Sequence[str],
) -> Path:
    payload = normalise_fx_automation(automation, stem_names)
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination



def fx_automation_registry(stem_names: Sequence[str]) -> AutomationTargetRegistry:
    """Build a typed registry for the existing M13 FX target identifiers."""
    targets = list(DEFAULT_AUTOMATION_TARGETS.targets)
    known = {target.target_id for target in targets}
    for target_id in automation_targets(stem_names):
        if target_id in known:
            continue
        targets.append(AutomationTarget(
            target_id=target_id,
            domain="fx",
            unit="normalized",
            minimum=0.0,
            maximum=1.0,
            interpolation=("step", "linear", "smooth"),
        ))
        known.add(target_id)
    return AutomationTargetRegistry(targets)


def fx_automation_to_score_lanes(
    payload: Mapping[str, Any] | None,
    stem_names: Sequence[str],
) -> tuple[AutomationLane, ...]:
    """Convert M13 schema-v1 JSON into typed beat-addressed score lanes.

    M13 stores interpolation per point. The score keeps that exact segment
    policy on AutomationPoint.interpolation_to_next instead of flattening a
    mixed hold/linear/smooth lane to one lane-wide curve.
    """
    normalized = normalise_fx_automation(payload, stem_names)
    lanes: list[AutomationLane] = []
    curve_map = {"hold": "step", "linear": "linear", "smooth": "smooth"}
    for target_id, raw_points in normalized["lanes"].items():
        points = tuple(
            AutomationPoint(
                at=Fraction(str(point["beat"])),
                value=float(point["value"]),
                interpolation_to_next=curve_map[str(point["curve"])],
            )
            for point in raw_points
        )
        lanes.append(AutomationLane(
            target_id=target_id,
            points=points,
            unit="normalized",
            time_basis="beats",
            interpolation="linear",
            minimum=0.0,
            maximum=1.0,
        ))
    return tuple(lanes)


def score_lanes_to_fx_automation(
    lanes: Sequence[AutomationLane],
    stem_names: Sequence[str],
) -> dict[str, Any]:
    """Project typed score lanes back to the unchanged M13 schema-v1 contract."""
    allowed = set(automation_targets(stem_names))
    curve_map = {"step": "hold", "linear": "linear", "smooth": "smooth"}
    payload_lanes: dict[str, list[dict[str, Any]]] = {}
    for lane in lanes:
        if lane.target_id not in allowed:
            continue
        if lane.time_basis != "beats":
            raise ValueError(
                f"M13 FX automation target {lane.target_id!r} requires beat-addressed points"
            )
        points: list[dict[str, Any]] = []
        for point in lane.points:
            interpolation = point.interpolation_to_next or lane.interpolation
            curve = curve_map.get(interpolation)
            if curve is None:
                raise ValueError(
                    f"cannot export {interpolation!r} interpolation to M13 FX automation"
                )
            points.append({
                "beat": float(point.at),
                "value": float(point.value),
                "curve": curve,
            })
        payload_lanes[lane.target_id] = points
    return normalise_fx_automation(
        {"schema_version": FX_AUTOMATION_SCHEMA_VERSION, "lanes": payload_lanes},
        stem_names,
    )


def attach_fx_automation_to_score(
    score: Score,
    payload: Mapping[str, Any],
    stem_names: Sequence[str] | None = None,
) -> Score:
    """Merge a legacy M13 automation document into a score without losing lanes."""
    names = tuple(stem_names or score.metadata.get("render_stems", ()))
    if not names:
        names = tuple(sorted({
            event.voice_id for event in score.events
            if event.voice_id not in {"sample_break"}
        }))
    converted = fx_automation_to_score_lanes(payload, names)
    merged = {lane.target_id: lane for lane in score.automation}
    for lane in converted:
        merged[lane.target_id] = lane
    metadata = dict(score.metadata)
    metadata["fx_automation_compatibility"] = {
        "schema_version": FX_AUTOMATION_SCHEMA_VERSION,
        "target_stems": list(names),
        "source_contract": "M13 fx_automation schema v1",
        "segment_curves": "preserved per AutomationPoint.interpolation_to_next",
    }
    return replace(score, automation=tuple(merged.values()), metadata=metadata)


def score_to_fx_automation(
    score: Score,
    stem_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Export a score's FX lanes through the established M13 JSON interface."""
    names = tuple(
        stem_names
        or score.metadata.get("fx_automation_compatibility", {}).get("target_stems", ())
        or score.metadata.get("render_stems", ())
    )
    if not names:
        names = tuple(sorted({
            lane.target_id.split(".")[1]
            for lane in score.automation
            if lane.target_id.startswith("stem.") and len(lane.target_id.split(".")) >= 4
        }))
    return score_lanes_to_fx_automation(score.automation, names)
