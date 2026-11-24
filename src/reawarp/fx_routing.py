"""Portable role-aware inserts and two shared send/return buses.

The generator remains the dry, deterministic source of truth. This module
applies an optional offline FX pass after generation and never mutates input
stem buffers or their random streams.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from reawarp.fx import FX_PRESETS, normalise_fx_stages, render_pyo_fx
from reawarp.fx_automation import automation_envelope, normalise_fx_automation

FX_ROUTING_SCHEMA_VERSION = 1
FX_BUSES = ("space", "echo")
FX_DELAY_DIVISIONS: dict[str, float] = {
    "off": 0.0,
    "1/2": 2.0,
    "1/4": 1.0,
    "dotted_1/8": 0.75,
    "1/8": 0.5,
    "1/8_triplet": 1.0 / 3.0,
    "1/16": 0.25,
    "1/16_triplet": 1.0 / 6.0,
    "1/32": 0.125,
}


def _finite(value: Any, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number


def _chain_record(record: Mapping[str, Any], sample_rate: int) -> dict[str, Any]:
    kind = record.get("kind", "preset")
    wet = _finite(record.get("wet", 1.0), "chain wet", 0.0, 1.0)
    tail = _finite(record.get("tail_seconds", 1.5), "tail_seconds", 0.0, 12.0)
    if kind == "preset":
        preset = str(record.get("preset", "restrained_space"))
        if preset not in FX_PRESETS:
            raise ValueError(f"Unknown FX preset: {preset}")
        stages = normalise_fx_stages(FX_PRESETS[preset], sample_rate=sample_rate)
        return {"kind": "preset", "preset": preset, "stages": stages, "wet": wet, "tail_seconds": tail}
    if kind == "stages":
        stages = normalise_fx_stages(record.get("stages", []), sample_rate=sample_rate)
        return {"kind": "stages", "stages": stages, "wet": wet, "tail_seconds": tail}
    if kind == "bypass":
        return {"kind": "bypass", "wet": 0.0, "tail_seconds": 0.0, "stages": ()}
    raise ValueError(f"Unknown route kind: {kind}")


def default_fx_routing(stem_names: Sequence[str] = ()) -> dict[str, Any]:
    """Build a conservative route map: every stem dry, every send closed."""
    return {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "master_wet": 1.0,
        "stems": {
            str(name): {
                "insert": {"kind": "bypass", "wet": 0.0, "tail_seconds": 0.0},
                "sends": {"space": 0.0, "echo": 0.0},
            }
            for name in stem_names
        },
        "buses": {
            "space": {"chain": "restrained_space", "wet": 0.18, "tail_seconds": 2.0, "delay_sync": "off"},
            "echo": {"chain": "tape_echo", "wet": 0.0, "tail_seconds": 1.5, "delay_sync": "off"},
        },
    }


def build_role_audition_matrix(stem_names: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Create four restrained, comparable role-routing starting points.

    Names are classified conservatively. Unknown stem names remain completely
    dry rather than receiving an assumed effect assignment.
    """
    def role_of(name: str) -> str:
        token = str(name).lower()
        if "kick" in token or "sub" in token or "bass" in token:
            return "kick"
        if "snare" in token or "clap" in token:
            return "snare"
        if any(part in token for part in ("hat", "cymbal", "ride", "shaker", "tamb")):
            return "hats"
        if "break" in token or "loop" in token:
            return "break"
        if any(part in token for part in ("melody", "lead", "arp")):
            return "melody"
        if any(part in token for part in ("ambience", "texture", "noise", "pad")):
            return "ambience"
        return "other"

    roles = {name: role_of(name) for name in stem_names}
    definitions = {
        "percussion_focus": {
            "sends": {"snare": (0.02, 0.00), "hats": (0.06, 0.02), "break": (0.04, 0.01)},
            "space_wet": 0.12, "echo_wet": 0.05,
        },
        "melody_foreground": {
            "sends": {"melody": (0.08, 0.04), "hats": (0.02, 0.00), "break": (0.02, 0.00)},
            "space_wet": 0.14, "echo_wet": 0.08,
        },
        "ambience_background": {
            "sends": {"ambience": (0.16, 0.00), "melody": (0.02, 0.00)},
            "space_wet": 0.16, "echo_wet": 0.00,
        },
        "combined_roles": {
            "sends": {
                "snare": (0.02, 0.00), "hats": (0.04, 0.01), "break": (0.04, 0.01),
                "melody": (0.07, 0.03), "ambience": (0.12, 0.00),
            },
            "space_wet": 0.14, "echo_wet": 0.06,
        },
    }
    matrix: dict[str, dict[str, Any]] = {}
    for profile, spec in definitions.items():
        routing = default_fx_routing(stem_names)
        for stem, role in roles.items():
            send = spec["sends"].get(role)
            if send is None:
                continue
            routing["stems"][stem]["sends"] = {"space": send[0], "echo": send[1]}
        routing["buses"]["space"]["wet"] = spec["space_wet"]
        routing["buses"]["echo"]["wet"] = spec["echo_wet"]
        matrix[profile] = routing
    return matrix


def normalise_fx_routing(
    payload: Mapping[str, Any], stem_names: Sequence[str], sample_rate: int
) -> dict[str, Any]:
    """Validate routing JSON and fill omitted stems/buses with dry defaults."""
    if not isinstance(payload, Mapping) or payload.get("schema_version") != FX_ROUTING_SCHEMA_VERSION:
        raise ValueError(f"FX routing schema_version must be {FX_ROUTING_SCHEMA_VERSION}")
    defaults = default_fx_routing(stem_names)
    source_stems = payload.get("stems", {})
    source_buses = payload.get("buses", {})
    if not isinstance(source_stems, Mapping) or not isinstance(source_buses, Mapping):
        raise ValueError("routing stems and buses must be JSON objects")
    unknown_stems = set(source_stems) - set(stem_names)
    if unknown_stems:
        raise ValueError("routing references unknown stem(s): " + ", ".join(sorted(map(str, unknown_stems))))

    stems: dict[str, Any] = {}
    for name in stem_names:
        raw = source_stems.get(name, defaults["stems"][name])
        if not isinstance(raw, Mapping):
            raise ValueError(f"routing for stem {name!r} must be an object")
        insert = raw.get("insert", {"kind": "bypass"})
        sends = raw.get("sends", {})
        if not isinstance(insert, Mapping) or not isinstance(sends, Mapping):
            raise ValueError(f"insert and sends for stem {name!r} must be JSON objects")
        unknown_buses = set(sends) - set(FX_BUSES)
        if unknown_buses:
            raise ValueError(f"stem {name!r} references unknown bus(es): {', '.join(map(str, unknown_buses))}")
        stems[name] = {
            "insert": _chain_record(insert, sample_rate),
            "sends": {
                bus: _finite(sends.get(bus, 0.0), f"{name}.{bus} send", 0.0, 1.0)
                for bus in FX_BUSES
            },
        }

    unknown_bus_names = set(source_buses) - set(FX_BUSES)
    if unknown_bus_names:
        raise ValueError("unknown FX bus(es): " + ", ".join(sorted(map(str, unknown_bus_names))))
    buses: dict[str, Any] = {}
    for bus in FX_BUSES:
        raw = source_buses.get(bus, defaults["buses"][bus])
        if not isinstance(raw, Mapping):
            raise ValueError(f"bus {bus!r} must be an object")
        preset = str(raw.get("chain", defaults["buses"][bus]["chain"]))
        wet = _finite(raw.get("wet", defaults["buses"][bus]["wet"]), f"{bus}.wet", 0.0, 1.0)
        tail = _finite(raw.get("tail_seconds", defaults["buses"][bus]["tail_seconds"]),
                       f"{bus}.tail_seconds", 0.0, 12.0)
        division = str(raw.get("delay_sync", "off"))
        if preset not in FX_PRESETS:
            raise ValueError(f"Unknown bus preset for {bus}: {preset}")
        if division not in FX_DELAY_DIVISIONS:
            raise ValueError(f"Unknown {bus} delay division: {division}")
        buses[bus] = {
            "chain": preset,
            "wet": wet,
            "tail_seconds": tail,
            "delay_sync": division,
        }
    return {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "master_wet": _finite(payload.get("master_wet", 1.0), "master_wet", 0.0, 1.0),
        "stems": stems,
        "buses": buses,
    }


def load_fx_routing(path: str | Path, stem_names: Sequence[str], sample_rate: int) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return normalise_fx_routing(payload, stem_names, sample_rate)


def save_fx_routing(
    path: str | Path, routing: Mapping[str, Any], stem_names: Sequence[str], sample_rate: int
) -> Path:
    normalised = normalise_fx_routing(routing, stem_names, sample_rate)
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(normalised, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return destination


def _render_chain(
    audio: np.ndarray, sample_rate: int, chain: Mapping[str, Any], *, wet: float = 1.0
) -> np.ndarray:
    if chain["kind"] == "bypass":
        return np.asarray(audio, dtype=np.float32).copy()
    preset = chain.get("preset") if chain["kind"] == "preset" else None
    stages = None if preset else chain["stages"]
    return render_pyo_fx(
        audio, sample_rate, preset=preset, stages=stages,
        wet=float(wet), tail_seconds=float(chain["tail_seconds"]),
    )


def _stereo(audio: np.ndarray, channels: int) -> np.ndarray:
    result = np.asarray(audio, dtype=np.float32)
    if result.ndim == 1:
        result = result[:, None]
    if result.shape[1] == 1 and channels == 2:
        result = np.repeat(result, 2, axis=1)
    if result.shape[1] != channels:
        raise ValueError("FX processor changed channel count")
    return np.ascontiguousarray(result, dtype=np.float32)


def _pad_to(audio: np.ndarray, frames: int) -> np.ndarray:
    if len(audio) >= frames:
        return audio[:frames]
    return np.pad(audio, ((0, frames - len(audio)), (0, 0)))


def _automation_lane(
    automation: Mapping[str, Any], target: str, *, frames: int, sample_rate: int,
    bpm: float, default: float,
) -> np.ndarray:
    points = automation.get("lanes", {}).get(target)
    return automation_envelope(
        points, frames=frames, sample_rate=sample_rate, bpm=bpm, default_value=default
    )


def _tempo_stages(bus_record: Mapping[str, Any], sample_rate: int, bpm: float) -> tuple[dict[str, Any], ...]:
    preset = str(bus_record["chain"])
    stages = [dict(stage) for stage in FX_PRESETS[preset]]
    division = str(bus_record.get("delay_sync", "off"))
    if division == "off":
        return normalise_fx_stages(stages, sample_rate=sample_rate)
    beat_count = FX_DELAY_DIVISIONS[division]
    delay_seconds = (60.0 / bpm) * beat_count
    delay_stage = next((stage for stage in stages if stage.get("type") == "delay"), None)
    if delay_stage is None:
        raise ValueError(
            f"Bus preset {preset!r} has no delay stage; choose a delay preset or turn sync off"
        )
    delay_stage["delay_seconds"] = delay_seconds
    return normalise_fx_stages(stages, sample_rate=sample_rate)


def render_fx_routing(
    dry_stems: Mapping[str, np.ndarray],
    sample_rate: int,
    routing: Mapping[str, Any],
    *,
    bpm: float = 120.0,
    automation: Mapping[str, Any] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Render per-stem inserts and shared returns with optional beat automation.

    Direct stem outputs stay frame-aligned. Insert tails remain available to
    shared sends, and shared return tails extend the final master. Inputs are
    never modified.
    """
    if not dry_stems:
        return {}, {"schema_version": 1, "buses": {}, "master_wet": 1.0,
                    "rendered_returns": [], "active_send_stems_by_bus": {}}
    tempo = _finite(bpm, "bpm", 1.0, 1000.0)
    names = tuple(dry_stems)
    first = _stereo(np.asarray(dry_stems[names[0]]), 2)
    frames, channels = first.shape
    config = normalise_fx_routing(routing, names, sample_rate)
    lanes = normalise_fx_automation(automation, names)
    bus_inputs = {bus: np.zeros((frames, channels), dtype=np.float32) for bus in FX_BUSES}
    active_stems_by_bus: dict[str, list[str]] = {bus: [] for bus in FX_BUSES}
    outputs: dict[str, np.ndarray] = {}

    for name, source in dry_stems.items():
        dry = _stereo(np.asarray(source), channels)
        if dry.shape != (frames, channels):
            raise ValueError("all stems must share the same frame and channel dimensions")
        record = config["stems"][name]
        insert = record["insert"]
        insert_target = f"stem.{name}.insert_wet"
        insert_points = lanes["lanes"].get(insert_target)
        insert_can_open = (
            float(insert["wet"]) > 0.0
            or any(float(point["value"]) > 0.0 for point in (insert_points or ()))
        )
        if insert["kind"] == "bypass" or not insert_can_open:
            processed_full = dry.copy()
            insert_level = np.zeros(frames, dtype=np.float32)
        else:
            # Render the full wet path once; automation then crossfades it against dry.
            processed_full = _stereo(
                _render_chain(dry, sample_rate, insert, wet=1.0), channels
            )
            insert_level = _automation_lane(
                lanes, insert_target, frames=frames, sample_rate=sample_rate,
                bpm=tempo, default=float(insert["wet"]),
            ) if insert_points else np.full(frames, float(insert["wet"]), dtype=np.float32)

        direct_processed = _pad_to(processed_full, frames)
        direct = dry * (1.0 - insert_level[:, None]) + direct_processed * insert_level[:, None]
        outputs[name] = np.ascontiguousarray(direct, dtype=np.float32)

        # Preserve insert tails on send paths. The last automation value is held
        # through the tail so no abrupt truncation is introduced at the source end.
        send_frames = max(frames, len(processed_full))
        send_source = _pad_to(processed_full, send_frames).copy()
        send_source[:frames] = direct
        if send_frames > frames:
            send_source[frames:] *= float(insert_level[-1]) if frames else 0.0

        for bus, static_amount in record["sends"].items():
            target = f"stem.{name}.send.{bus}"
            points = lanes["lanes"].get(target)
            envelope = _automation_lane(
                lanes, target, frames=send_frames, sample_rate=sample_rate,
                bpm=tempo, default=float(static_amount),
            ) if points else np.full(send_frames, float(static_amount), dtype=np.float32)
            if not np.any(envelope):
                continue
            contribution = send_source * envelope[:, None]
            target_buffer = bus_inputs[bus]
            if len(contribution) > len(target_buffer):
                target_buffer = _pad_to(target_buffer, len(contribution))
            target_buffer[:len(contribution)] += contribution
            bus_inputs[bus] = target_buffer
            if name not in active_stems_by_bus[bus]:
                active_stems_by_bus[bus].append(name)

    returns: dict[str, np.ndarray] = {}
    for bus, source in bus_inputs.items():
        record = config["buses"][bus]
        target = f"bus.{bus}.wet"
        points = lanes["lanes"].get(target)
        requested_wet = _automation_lane(
            lanes, target, frames=max(len(source), 1), sample_rate=sample_rate,
            bpm=tempo, default=float(record["wet"]),
        ) if points else np.full(max(len(source), 1), float(record["wet"]), dtype=np.float32)
        if not np.any(source) or not np.any(requested_wet):
            continue

        stages = _tempo_stages(record, sample_rate, tempo)
        processed = _stereo(
            render_pyo_fx(
                source, sample_rate, preset=None, stages=stages,
                wet=1.0, tail_seconds=float(record["tail_seconds"]),
            ),
            channels,
        )
        desired_frames = max(len(source), len(processed))
        base_signal = _pad_to(source, desired_frames)
        processed = _pad_to(processed, desired_frames)
        wet_envelope = _automation_lane(
            lanes, target, frames=desired_frames, sample_rate=sample_rate,
            bpm=tempo, default=float(record["wet"]),
        ) if points else np.full(desired_frames, float(record["wet"]), dtype=np.float32)
        returns[bus] = np.ascontiguousarray(
            base_signal * (1.0 - wet_envelope[:, None]) + processed * wet_envelope[:, None],
            dtype=np.float32,
        )

    metadata = {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "master_wet": config["master_wet"],
        "bpm": tempo,
        "stems": {
            name: {
                "insert": {
                    "kind": record["insert"]["kind"],
                    "preset": record["insert"].get("preset"),
                    "wet": record["insert"]["wet"],
                    "tail_seconds": record["insert"]["tail_seconds"],
                },
                "sends": dict(record["sends"]),
            }
            for name, record in config["stems"].items()
        },
        "buses": config["buses"],
        "rendered_returns": list(returns),
        "active_send_stems_by_bus": active_stems_by_bus,
        "automation_lanes": list(lanes["lanes"]),
    }
    metadata["bus_returns_audio"] = returns
    return outputs, metadata


def render_master_with_returns(
    processed_stems: Mapping[str, np.ndarray],
    bus_returns: Mapping[str, np.ndarray],
    *,
    frames: int | None = None,
    master_wet: float = 1.0,
) -> np.ndarray:
    """Sum aligned processed stems and shared returns without mutating inputs."""
    wet = _finite(master_wet, "master_wet", 0.0, 1.0)
    all_buffers = [*processed_stems.values(), *bus_returns.values()]
    if frames is None:
        frames = max((len(item) for item in all_buffers), default=0)
    master = np.zeros((frames, 2), dtype=np.float32)
    for audio in all_buffers:
        value = _stereo(np.asarray(audio), 2)
        count = min(frames, len(value))
        master[:count] += value[:count]
    peak = float(np.max(np.abs(master))) if master.size else 0.0
    ceiling = 10.0 ** (-1.0 / 20.0)
    if peak > ceiling:
        master *= ceiling / peak
    return np.clip(master * wet, -1.0, 1.0).astype(np.float32, copy=False)
