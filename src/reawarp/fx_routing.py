"""Portable, role-aware per-stem inserts and shared FX send/return routing.

Routing is an offline project pass. It never changes the generated source stems
or consumes the composition engine's random streams. Pyo is imported only when
an enabled route actually needs processing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from reawarp.fx import FX_PRESETS, load_fx_chain, normalise_fx_stages, render_pyo_fx

FX_ROUTING_SCHEMA_VERSION = 1
FX_BUSES = ("space", "echo")
FX_ROUTING_DEFAULTS: dict[str, Any] = {
    "schema_version": FX_ROUTING_SCHEMA_VERSION,
    "master_wet": 1.0,
    "stems": {},
    "buses": {
        "space": {"chain": "restrained_space", "wet": 0.18, "tail_seconds": 2.0},
        "echo": {"chain": "tape_echo", "wet": 0.0, "tail_seconds": 1.0},
    },
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
    if kind == "chain_file":
        path = str(record.get("path", "")).strip()
        if not path:
            raise ValueError("chain_file route requires a path")
        chain = load_fx_chain(path, sample_rate=sample_rate)
        return {"kind": "stages", "stages": chain["stages"], "wet": wet if "wet" in record else chain["wet"],
                "tail_seconds": tail if "tail_seconds" in record else chain["tail_seconds"], "source_path": path}
    if kind == "bypass":
        return {"kind": "bypass", "wet": 0.0, "tail_seconds": 0.0, "stages": ()}
    raise ValueError(f"Unknown route kind: {kind}")


def default_fx_routing(stem_names: Sequence[str] = ()) -> dict[str, Any]:
    """Build a fresh routing document with explicit, conservative defaults."""
    return {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "master_wet": 1.0,
        "stems": {
            str(name): {"insert": {"kind": "bypass", "wet": 0.0, "tail_seconds": 0.0},
                        "sends": {"space": 0.0, "echo": 0.0}}
            for name in stem_names
        },
        "buses": {
            "space": {"chain": "restrained_space", "wet": 1.0, "tail_seconds": 2.0},
            "echo": {"chain": "tape_echo", "wet": 1.0, "tail_seconds": 1.5},
        },
    }


def normalise_fx_routing(
    payload: Mapping[str, Any], stem_names: Sequence[str], sample_rate: int
) -> dict[str, Any]:
    """Validate project routing and fill missing stems/buses without side effects."""
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
        if not isinstance(insert, Mapping):
            raise ValueError(f"insert for stem {name!r} must be an object")
        sends = raw.get("sends", {})
        if not isinstance(sends, Mapping):
            raise ValueError(f"sends for stem {name!r} must be an object")
        unknown_buses = set(sends) - set(FX_BUSES)
        if unknown_buses:
            raise ValueError(f"stem {name!r} references unknown bus(es): {', '.join(map(str, unknown_buses))}")
        stems[name] = {
            "insert": _chain_record(insert, sample_rate),
            "sends": {bus: _finite(sends.get(bus, 0.0), f"{name}.{bus} send", 0.0, 1.0) for bus in FX_BUSES},
        }
    buses: dict[str, Any] = {}
    unknown_bus_names = set(source_buses) - set(FX_BUSES)
    if unknown_bus_names:
        raise ValueError("unknown FX bus(es): " + ", ".join(sorted(map(str, unknown_bus_names))))
    for bus in FX_BUSES:
        raw = source_buses.get(bus, defaults["buses"][bus])
        if not isinstance(raw, Mapping):
            raise ValueError(f"bus {bus!r} must be an object")
        preset = str(raw.get("chain", "restrained_space" if bus == "space" else "tape_echo"))
        wet = _finite(raw.get("wet", 1.0), f"{bus}.wet", 0.0, 1.0)
        tail = _finite(raw.get("tail_seconds", 1.5), f"{bus}.tail_seconds", 0.0, 12.0)
        if preset not in FX_PRESETS:
            raise ValueError(f"Unknown bus preset for {bus}: {preset}")
        buses[bus] = {"chain": preset, "wet": wet, "tail_seconds": tail}
    return {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "master_wet": _finite(payload.get("master_wet", 1.0), "master_wet", 0.0, 1.0),
        "stems": stems,
        "buses": buses,
    }


def load_fx_routing(path: str | Path, stem_names: Sequence[str], sample_rate: int) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return normalise_fx_routing(payload, stem_names, sample_rate)


def save_fx_routing(path: str | Path, routing: Mapping[str, Any], stem_names: Sequence[str], sample_rate: int) -> Path:
    normalised = normalise_fx_routing(routing, stem_names, sample_rate)
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(normalised, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def _render_chain(audio: np.ndarray, sample_rate: int, chain: Mapping[str, Any]) -> np.ndarray:
    if chain["kind"] == "bypass" or float(chain["wet"]) <= 0.0:
        return np.asarray(audio, dtype=np.float32).copy()
    preset = chain["preset"] if chain["kind"] == "preset" else None
    stages = None if preset else chain["stages"]
    return render_pyo_fx(audio, sample_rate, preset=preset, stages=stages,
                         wet=float(chain["wet"]), tail_seconds=float(chain["tail_seconds"]))


def _fit_frames(audio: np.ndarray, frames: int, channels: int) -> np.ndarray:
    result = np.asarray(audio, dtype=np.float32)
    if result.ndim == 1:
        result = result[:, None]
    if result.shape[1] == 1 and channels == 2:
        result = np.repeat(result, 2, axis=1)
    if result.shape[1] != channels:
        raise ValueError("FX processor changed channel count")
    if len(result) < frames:
        result = np.pad(result, ((0, frames - len(result)), (0, 0)))
    return np.ascontiguousarray(result[:frames], dtype=np.float32)


def render_fx_routing(
    dry_stems: Mapping[str, np.ndarray], sample_rate: int, routing: Mapping[str, Any]
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Render inserts and shared post-insert sends, returning processed copies.

    Returns aligned stem outputs (dry stem plus its insert delta) and metadata
    including shared bus returns. Bus return buffers are intentionally kept
    separate so a mix can audition/export them without altering any dry stem.
    """
    if not dry_stems:
        return {}, {"schema_version": 1, "buses": {}, "master_wet": 1.0}
    names = tuple(dry_stems)
    first = np.asarray(dry_stems[names[0]], dtype=np.float32)
    if first.ndim != 2 or first.shape[1] != 2:
        raise ValueError("routing currently expects stereo generated stems")
    frames, channels = first.shape
    config = normalise_fx_routing(routing, names, sample_rate)
    outputs: dict[str, np.ndarray] = {}
    bus_inputs = {bus: np.zeros((frames, channels), dtype=np.float32) for bus in FX_BUSES}
    bus_tail_frames = 0
    active_stems: list[str] = []
    active_stems_by_bus: dict[str, list[str]] = {bus: [] for bus in FX_BUSES}
    for name, source in dry_stems.items():
        dry = np.asarray(source, dtype=np.float32)
        if dry.shape != (frames, channels):
            raise ValueError("all stems must share the same frame and channel dimensions")
        record = config["stems"][name]
        if record["insert"]["kind"] == "bypass" or record["insert"]["wet"] <= 0.0:
            processed = dry.copy()
        else:
            processed = _render_chain(dry.copy(), sample_rate, record["insert"])
        processed = _fit_frames(processed, frames, channels)
        outputs[name] = np.ascontiguousarray(processed, dtype=np.float32)
        for bus, amount in record["sends"].items():
            if amount > 0:
                bus_inputs[bus] += processed * float(amount)
                if name not in active_stems:
                    active_stems.append(name)
                if name not in active_stems_by_bus[bus]:
                    active_stems_by_bus[bus].append(name)
    returns: dict[str, np.ndarray] = {}
    for bus, source in bus_inputs.items():
        record = config["buses"][bus]
        if not np.any(source) or record["wet"] <= 0.0:
            continue
        rendered = render_pyo_fx(source, sample_rate, preset=record["chain"],
                                 wet=record["wet"], tail_seconds=record["tail_seconds"])
        desired = frames + int(round(record["tail_seconds"] * sample_rate))
        returns[bus] = _fit_frames(rendered, desired, channels)
    metadata = {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "master_wet": config["master_wet"],
        "stems": {
            name: {
                "insert": {"kind": record["insert"]["kind"],
                           "preset": record["insert"].get("preset"),
                           "wet": record["insert"]["wet"],
                           "tail_seconds": record["insert"]["tail_seconds"]},
                "sends": dict(record["sends"]),
            }
            for name, record in config["stems"].items()
        },
        "buses": config["buses"],
        "rendered_returns": list(returns),
        "active_send_stems": active_stems,
        "active_send_stems_by_bus": active_stems_by_bus,
    }
    metadata["bus_returns_audio"] = returns
    return outputs, metadata


def render_master_with_returns(
    processed_stems: Mapping[str, np.ndarray], bus_returns: Mapping[str, np.ndarray],
    *, frames: int | None = None, master_wet: float = 1.0
) -> np.ndarray:
    """Sum aligned processed stems and shared returns without modifying inputs."""
    all_buffers = [*processed_stems.values(), *bus_returns.values()]
    if frames is None:
        frames = max((len(item) for item in all_buffers), default=0)
    master = np.zeros((frames, 2), dtype=np.float32)
    for audio in all_buffers:
        value = np.asarray(audio, dtype=np.float32)
        count = min(frames, len(value))
        master[:count] += value[:count]
    peak = float(np.max(np.abs(master))) if master.size else 0.0
    ceiling = 10.0 ** (-1.0 / 20.0)
    if peak > ceiling:
        master *= ceiling / peak
    return np.clip(master * float(master_wet), -1.0, 1.0).astype(np.float32, copy=False)
