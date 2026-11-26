"""Versioned role-aware mixer: per-stem inserts, tap-point sends and fixed returns.

The render contract keeps dry stems immutable. Inserts operate per stem before
the master, and SPACE/ECHO are fixed auxiliary returns. Schemas v1–v3 are
migrated in memory to v4. Sidechains are one-way detector-to-gain controls, not
an arbitrary routing graph or feedback bus.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from reawarp.fx import FX_PRESETS, normalise_fx_stages, render_pyo_fx
from reawarp.fx_automation import automation_envelope, normalise_fx_automation
from reawarp.score.automation import AutomationControlBus
from reawarp.sidechain import normalise_sidechain_routes, render_sidechain_gain_envelope

FX_ROUTING_SCHEMA_VERSION = 4
LEGACY_FX_ROUTING_SCHEMA_VERSION = 1
PREVIOUS_FX_ROUTING_SCHEMA_VERSION = 3
EARLIER_FX_ROUTING_SCHEMA_VERSION = 2
FX_BUSES = ("space", "echo")
SEND_TAP_POINTS = (
    "pre_insert_pre_fader",
    "pre_insert_post_fader",
    "post_insert_pre_fader",
    "post_insert_post_fader",
)
FX_DELAY_DIVISIONS: dict[str, float] = {
    "off": 0.0, "1/2": 2.0, "1/4": 1.0, "dotted_1/8": 0.75,
    "1/8": 0.5, "1/8_triplet": 1.0 / 3.0, "1/16": 0.25,
    "1/16_triplet": 1.0 / 6.0, "1/32": 0.125,
}


class FXRenderCancelledError(RuntimeError):
    """Raised at safe boundaries when a background FX render is cancelled."""


def _check_cancel(cancel_event: Any | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise FXRenderCancelledError("FX render cancelled")


def _finite(value: Any, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number


def classify_fx_role(stem_name: str) -> str:
    """Infer a conservative musical role from a generated stem identifier."""
    token = str(stem_name).casefold().replace("-", "_")
    if any(part in token for part in ("kick", "sub", "bass", "low_end")):
        return "kick"
    if any(part in token for part in ("snare", "clap", "rim")):
        return "snare"
    if any(part in token for part in ("hat", "cymbal", "ride", "shaker", "tamb")):
        return "hats"
    if any(part in token for part in ("break", "loop", "sample_break", "synthetic_break")):
        return "break"
    if any(part in token for part in ("melody", "lead", "arp", "keys", "voice")):
        return "melody"
    if any(part in token for part in ("texture", "noise", "granular", "drone")):
        return "texture"
    if any(part in token for part in ("ambience", "ambient", "pad", "atmosphere")):
        return "ambience"
    return "other"


def _bypass_insert() -> dict[str, Any]:
    return {"kind": "bypass", "wet": 0.0, "tail_seconds": 0.0}


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
        return _bypass_insert()
    raise ValueError(f"Unknown route kind: {kind}")


def _base_routing(stem_names: Sequence[str], *, routing_mode: str) -> dict[str, Any]:
    return {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "routing_mode": routing_mode,
        "master_wet": 1.0,
        "stems": {
            str(name): {
                "insert": _bypass_insert(),
                "sends": {"space": 0.0, "echo": 0.0},
                "send_taps": {
                    "space": "post_insert_post_fader",
                    "echo": "post_insert_post_fader",
                },
                "gain_db": 0.0,
                "pan": 0.0,
                "mute": False,
                "solo": False,
            }
            for name in stem_names
        },
        "buses": {
            "space": {
                "chain": "restrained_space", "wet": 0.18,
                "tail_seconds": 2.0, "delay_sync": "off",
                "alignment_policy": "start_aligned",
            },
            "echo": {
                "chain": "tape_echo", "wet": 0.0,
                "tail_seconds": 1.5, "delay_sync": "off",
                "alignment_policy": "start_aligned",
            },
        },
        "sidechains": [],
    }


def default_fx_routing(stem_names: Sequence[str] = ()) -> dict[str, Any]:
    """Explicit manual, fully dry routing for intentional A/B and reset."""
    return _base_routing(stem_names, routing_mode="manual")


def routing_defaults_for_project(stem_names: Sequence[str] = ()) -> dict[str, Any]:
    """Return the automatic role-aware routing used for new projects/renders."""
    return role_aware_fx_routing(stem_names)


def role_effect_profile(stem_name: str) -> dict[str, Any]:
    """Inspectable default effect assignment for a generated stem identifier."""
    role = classify_fx_role(stem_name)
    profiles = {
        "kick": {"insert": None, "space": 0.0, "echo": 0.0, "description": "dry low-end anchor"},
        "snare": {"insert": "restrained_space", "space": 0.05, "echo": 0.015, "description": "short room and restrained punctuation"},
        "hats": {"insert": "digital_fracture", "space": 0.055, "echo": 0.02, "description": "light texture and small rhythmic reflections"},
        "break": {"insert": "digital_fracture", "space": 0.04, "echo": 0.02, "description": "blend the loop while retaining its attack"},
        "melody": {"insert": "metallic_machine", "space": 0.075, "echo": 0.035, "description": "foreground separation and sparse replies"},
        "texture": {"insert": "restrained_space", "space": 0.10, "echo": 0.01, "description": "place continuous material behind foreground"},
        "ambience": {"insert": None, "space": 0.035, "echo": 0.0, "description": "a little shared room without extra echo"},
        "other": {"insert": None, "space": 0.0, "echo": 0.0, "description": "unknown role; left dry rather than guessed"},
    }
    return {"role": role, **profiles[role]}


def role_aware_fx_routing(stem_names: Sequence[str] = ()) -> dict[str, Any]:
    """Assign inserts and shared sends from role identity; unknown stems stay dry.

    This is the desktop's normal new-project starting point. It removes the need
    to hand-enable effect sends for each stem while protecting kick/sub energy.
    """
    routing = _base_routing(stem_names, routing_mode="role_auto")
    role_defaults = {
        "kick": {"insert": _bypass_insert(), "sends": (0.0, 0.0)},
        "snare": {
            "insert": {"kind": "preset", "preset": "restrained_space", "wet": 0.08, "tail_seconds": 0.8},
            "sends": (0.05, 0.015),
        },
        "hats": {
            "insert": {"kind": "preset", "preset": "digital_fracture", "wet": 0.07, "tail_seconds": 0.5},
            "sends": (0.055, 0.02),
        },
        "break": {
            "insert": {"kind": "preset", "preset": "digital_fracture", "wet": 0.10, "tail_seconds": 0.65},
            "sends": (0.04, 0.02),
        },
        "melody": {
            "insert": {"kind": "preset", "preset": "metallic_machine", "wet": 0.07, "tail_seconds": 1.0},
            "sends": (0.075, 0.035),
        },
        "texture": {
            "insert": {"kind": "preset", "preset": "restrained_space", "wet": 0.10, "tail_seconds": 1.6},
            "sends": (0.10, 0.01),
        },
        "ambience": {
            "insert": _bypass_insert(),
            "sends": (0.035, 0.0),
        },
    }
    for name in stem_names:
        role = classify_fx_role(name)
        spec = role_defaults.get(role)
        if spec is None:
            continue
        route = routing["stems"][str(name)]
        route["insert"] = dict(spec["insert"])
        route["sends"] = {
            "space": float(spec["sends"][0]),
            "echo": float(spec["sends"][1]),
        }
    routing["buses"]["space"]["wet"] = 0.16
    routing["buses"]["echo"]["wet"] = 0.07
    return routing


def build_role_audition_matrix(stem_names: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Create four restrained comparison routes without hand-editing stem names."""
    role_sends = {
        "percussion_focus": {
            "snare": (0.04, 0.01), "hats": (0.06, 0.02), "break": (0.04, 0.01),
            "space_wet": 0.13, "echo_wet": 0.05,
        },
        "melody_foreground": {
            "melody": (0.08, 0.04), "hats": (0.02, 0.0), "break": (0.02, 0.0),
            "space_wet": 0.14, "echo_wet": 0.08,
        },
        "ambience_background": {
            "ambience": (0.12, 0.0), "texture": (0.10, 0.0), "melody": (0.02, 0.0),
            "space_wet": 0.16, "echo_wet": 0.0,
        },
        "combined_roles": {
            "snare": (0.04, 0.01), "hats": (0.045, 0.015), "break": (0.04, 0.015),
            "melody": (0.07, 0.03), "ambience": (0.08, 0.0), "texture": (0.08, 0.0),
            "space_wet": 0.15, "echo_wet": 0.06,
        },
    }
    result = {}
    for name, spec in role_sends.items():
        route = role_aware_fx_routing(stem_names)
        route["routing_mode"] = name
        for stem in stem_names:
            send = spec.get(classify_fx_role(stem))
            if send is None:
                route["stems"][stem]["sends"] = {"space": 0.0, "echo": 0.0}
            else:
                route["stems"][stem]["sends"] = {"space": send[0], "echo": send[1]}
        route["buses"]["space"]["wet"] = spec["space_wet"]
        route["buses"]["echo"]["wet"] = spec["echo_wet"]
        result[name] = route
    return result


def build_fx_variation_routings(
    stem_names: Sequence[str],
    sample_rate: int,
    base_routing: Mapping[str, Any] | None = None,
    *,
    project_context: Mapping[str, Any] | None = None,
    variation_seed: int = 211,
    count: int = 4,
    bpm: float = 120.0,
) -> list[dict[str, Any]]:
    """Create deterministic, role-aware FX alternatives for one frozen project.

    Candidate values are derived from the project context, variation seed,
    candidate index and stem identity. The same generation and settings produce
    the same routing alternatives. Only routing parameters change; source audio,
    Score events and generation random streams are never touched.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError("FX variation count must be between 1 and 8")
    if isinstance(variation_seed, bool) or not isinstance(variation_seed, int):
        raise ValueError("variation_seed must be an integer")
    tempo = _finite(bpm, "bpm", 1.0, 1000.0)
    names = tuple(str(name) for name in stem_names)
    base = normalise_fx_routing(
        base_routing if base_routing is not None else role_aware_fx_routing(names),
        names, int(sample_rate),
    )
    context = dict(project_context or {})
    context_json = json.dumps(
        {"context": context, "variation_seed": variation_seed},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
        allow_nan=False,
    )
    root_digest = hashlib.blake2b(context_json.encode("utf-8"), digest_size=16).digest()
    root_seed = int.from_bytes(root_digest[:8], "little", signed=False)

    profiles = (
        ("space_depth", "A shared dark room with slightly longer role tails."),
        ("metallic_motion", "Narrow resonant inserts and restrained frequency movement."),
        ("digital_fracture", "Short saturation/filter/delay gestures on rhythmic roles."),
        ("rhythmic_echo", "Tempo-related echoes and phrase replies without changing the source rhythm."),
        ("soft_contrast", "Reduced insert density with selective space and clear dry anchors."),
        ("hybrid_texture", "Role-specific contrast between dry anchors, fractured percussion and spacious layers."),
        ("close_room", "Shorter, closer inserts and restrained shared returns."),
        ("open_space", "Wider shared spatial contribution with conservative direct inserts."),
    )
    output: list[dict[str, Any]] = []
    for index in range(count):
        profile_name, description = profiles[index % len(profiles)]
        routing = copy.deepcopy(base)
        routing["routing_mode"] = "manual"
        for name in names:
            role = classify_fx_role(name)
            route = routing["stems"][name]
            stem_digest = hashlib.blake2b(
                root_seed.to_bytes(8, "little") + index.to_bytes(4, "little")
                + name.encode("utf-8"), digest_size=8,
            ).digest()
            rng = np.random.default_rng(int.from_bytes(stem_digest, "little"))
            wet_scale = float(rng.uniform(0.82, 1.18))
            space_scale = float(rng.uniform(0.85, 1.25))
            echo_scale = float(rng.uniform(0.75, 1.30))

            # Never perturb the low-frequency foundation in generated variants.
            if role == "kick":
                route["insert"] = _bypass_insert()
                route["sends"] = {"space": 0.0, "echo": 0.0}
                continue

            if profile_name in {"space_depth", "open_space", "close_room"}:
                preset_by_role = {
                    "snare": "restrained_space", "hats": "restrained_space",
                    "break": "restrained_space", "melody": "metallic_machine",
                    "texture": "restrained_space",
                }
                preset = preset_by_role.get(role)
                if preset:
                    route["insert"] = {
                        "kind": "preset", "preset": preset,
                        "wet": float(np.clip(
                            (0.055 if role in {"snare", "hats", "break"} else 0.075)
                            * wet_scale, 0.025, 0.16,
                        )),
                        "tail_seconds": (
                            0.55 if profile_name == "close_room" else
                            2.4 if profile_name == "open_space" else 1.8
                        ),
                    }
                route["sends"]["space"] = float(np.clip(
                    route["sends"]["space"] * space_scale
                    + (0.025 if profile_name == "open_space" else 0.0),
                    0.0, 0.22,
                ))
                route["sends"]["echo"] = float(np.clip(
                    route["sends"]["echo"] * echo_scale, 0.0, 0.12
                ))
            elif profile_name == "metallic_motion":
                preset_by_role = {
                    "snare": "metallic_machine", "hats": "digital_fracture",
                    "break": "metallic_machine", "melody": "metallic_machine",
                    "texture": "metallic_machine",
                }
                preset = preset_by_role.get(role)
                if preset:
                    route["insert"] = {
                        "kind": "preset", "preset": preset,
                        "wet": float(np.clip(
                            (0.085 if role in {"melody", "texture"} else 0.06)
                            * wet_scale, 0.025, 0.18,
                        )),
                        "tail_seconds": 1.4,
                    }
                route["sends"]["space"] = float(np.clip(
                    route["sends"]["space"] * space_scale, 0.0, 0.16
                ))
                route["sends"]["echo"] = float(np.clip(
                    route["sends"]["echo"] * echo_scale, 0.0, 0.10
                ))
            elif profile_name == "digital_fracture":
                preset_by_role = {
                    "snare": "digital_fracture", "hats": "digital_fracture",
                    "break": "digital_fracture", "melody": "metallic_machine",
                    "texture": "digital_fracture",
                }
                preset = preset_by_role.get(role)
                if preset:
                    route["insert"] = {
                        "kind": "preset", "preset": preset,
                        "wet": float(np.clip(
                            (0.11 if role in {"hats", "break", "texture"} else 0.075)
                            * wet_scale, 0.03, 0.20,
                        )),
                        "tail_seconds": 0.8,
                    }
                route["sends"]["space"] = float(np.clip(
                    route["sends"]["space"] * 0.75, 0.0, 0.12
                ))
                route["sends"]["echo"] = float(np.clip(
                    route["sends"]["echo"] * echo_scale + 0.015, 0.0, 0.13
                ))
            elif profile_name == "rhythmic_echo":
                preset_by_role = {
                    "snare": "tape_echo", "hats": "tape_echo",
                    "break": "tape_echo", "melody": "tape_echo",
                }
                preset = preset_by_role.get(role)
                if preset:
                    route["insert"] = {
                        "kind": "preset", "preset": preset,
                        "wet": float(np.clip(
                            (0.055 if role in {"snare", "hats"} else 0.085)
                            * wet_scale, 0.02, 0.16,
                        )),
                        "tail_seconds": 1.5,
                    }
                route["sends"]["space"] = float(np.clip(
                    route["sends"]["space"] * 0.8, 0.0, 0.12
                ))
                route["sends"]["echo"] = float(np.clip(
                    route["sends"]["echo"] * echo_scale + 0.025, 0.0, 0.16
                ))
            elif profile_name == "soft_contrast":
                if role in {"snare", "hats", "break", "melody", "texture"}:
                    insert = route["insert"]
                    if insert["kind"] != "bypass":
                        insert["wet"] = float(np.clip(
                            float(insert.get("wet", 0.0)) * 0.62 * wet_scale,
                            0.0, 0.12,
                        ))
                route["sends"]["space"] = float(np.clip(
                    route["sends"]["space"] * 0.72, 0.0, 0.12
                ))
                route["sends"]["echo"] = float(np.clip(
                    route["sends"]["echo"] * 0.65, 0.0, 0.08
                ))
            else:  # hybrid_texture
                if role in {"hats", "break"}:
                    route["insert"] = {
                        "kind": "preset", "preset": "digital_fracture",
                        "wet": float(np.clip(0.09 * wet_scale, 0.03, 0.16)),
                        "tail_seconds": 0.7,
                    }
                elif role in {"melody", "texture"}:
                    route["insert"] = {
                        "kind": "preset", "preset": "metallic_machine",
                        "wet": float(np.clip(0.075 * wet_scale, 0.03, 0.15)),
                        "tail_seconds": 1.8,
                    }
                route["sends"]["space"] = float(np.clip(
                    route["sends"]["space"] * space_scale, 0.0, 0.18
                ))
                route["sends"]["echo"] = float(np.clip(
                    route["sends"]["echo"] * echo_scale, 0.0, 0.12
                ))

        if profile_name in {"space_depth", "open_space", "close_room"}:
            routing["buses"]["space"].update({
                "chain": "restrained_space",
                "wet": float(np.clip(
                    (0.13 if profile_name == "close_room" else
                     0.22 if profile_name == "open_space" else 0.18)
                    * float(np.random.default_rng(root_seed + index).uniform(0.92, 1.08)),
                    0.06, 0.28,
                )),
                "tail_seconds": 1.0 if profile_name == "close_room" else 3.0,
            })
            routing["buses"]["echo"]["wet"] = 0.025
        elif profile_name == "rhythmic_echo":
            routing["buses"]["echo"].update({
                "chain": "tape_echo",
                "wet": float(np.random.default_rng(root_seed + index).uniform(0.07, 0.12)),
                "tail_seconds": 1.7,
                "delay_sync": "1/8" if tempo >= 95.0 else "1/4",
            })
        elif profile_name == "digital_fracture":
            routing["buses"]["echo"].update({
                "chain": "tape_echo",
                "wet": float(np.random.default_rng(root_seed + index).uniform(0.04, 0.09)),
                "tail_seconds": 1.0,
                "delay_sync": "1/16" if tempo >= 120.0 else "1/8",
            })
        elif profile_name == "metallic_motion":
            routing["buses"]["space"].update({
                "chain": "restrained_space", "wet": 0.16, "tail_seconds": 2.0,
            })
            routing["buses"]["echo"]["wet"] = 0.02
        elif profile_name == "soft_contrast":
            routing["buses"]["space"].update({"wet": 0.11, "tail_seconds": 1.2})
            routing["buses"]["echo"]["wet"] = 0.0
        else:
            routing["buses"]["space"].update({"wet": 0.17, "tail_seconds": 2.2})
            routing["buses"]["echo"]["wet"] = 0.045

        normalized = normalise_fx_routing(routing, names, int(sample_rate))
        candidate_seed = hashlib.blake2b(
            root_seed.to_bytes(8, "little") + index.to_bytes(4, "little"),
            digest_size=6,
        ).hexdigest()
        output.append({
            "candidate_id": f"fx_{index + 1:02d}_{profile_name}",
            "label": profile_name.replace("_", " ").title(),
            "description": description,
            "seed": candidate_seed,
            "routing": normalized,
        })
    return output


def normalise_fx_routing(
    payload: Mapping[str, Any], stem_names: Sequence[str], sample_rate: int
) -> dict[str, Any]:
    """Validate v1–v4 JSON and return the canonical v4 representation."""
    if not isinstance(payload, Mapping):
        raise ValueError("FX routing must be a JSON object")
    version = payload.get("schema_version")
    if version not in {
        LEGACY_FX_ROUTING_SCHEMA_VERSION,
        EARLIER_FX_ROUTING_SCHEMA_VERSION,
        PREVIOUS_FX_ROUTING_SCHEMA_VERSION,
        FX_ROUTING_SCHEMA_VERSION,
    }:
        raise ValueError("FX routing schema_version must be 1, 2, 3 or 4")
    mode = str(payload.get("routing_mode", "manual"))
    if mode not in {"manual", "role_auto", "percussion_focus", "melody_foreground",
                    "ambience_background", "combined_roles"}:
        raise ValueError(f"unsupported routing_mode: {mode}")
    # v1/v2 are historical authored sessions: keep their manual values.
    if version in {LEGACY_FX_ROUTING_SCHEMA_VERSION, EARLIER_FX_ROUTING_SCHEMA_VERSION} and mode == "manual":
        defaults = default_fx_routing(stem_names)
    elif mode in {"percussion_focus", "melody_foreground", "ambience_background", "combined_roles"}:
        defaults = build_role_audition_matrix(stem_names)[mode]
    elif mode == "role_auto":
        defaults = role_aware_fx_routing(stem_names)
    else:
        defaults = role_aware_fx_routing(stem_names) if version == FX_ROUTING_SCHEMA_VERSION else default_fx_routing(stem_names)

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
        send_taps = raw.get("send_taps", {})
        if not isinstance(insert, Mapping) or not isinstance(sends, Mapping) or not isinstance(send_taps, Mapping):
            raise ValueError(f"insert, sends and send_taps for stem {name!r} must be JSON objects")
        unknown_buses = set(sends) - set(FX_BUSES)
        unknown_taps = set(send_taps) - set(FX_BUSES)
        if unknown_buses or unknown_taps:
            raise ValueError(f"stem {name!r} references an unknown send bus")
        normalized_taps = {}
        for bus in FX_BUSES:
            tap = str(send_taps.get(bus, "post_insert_post_fader"))
            if tap not in SEND_TAP_POINTS:
                raise ValueError(
                    f"{name}.{bus} send tap must be one of {', '.join(SEND_TAP_POINTS)}"
                )
            normalized_taps[bus] = tap
        for boolean_name in ("mute", "solo"):
            if boolean_name in raw and not isinstance(raw[boolean_name], bool):
                raise ValueError(f"{name}.{boolean_name} must be a boolean")
        profile = role_effect_profile(name)
        stems[name] = {
            "role": profile["role"],
            "insert": _chain_record(insert, sample_rate),
            "sends": {
                bus: _finite(sends.get(bus, 0.0), f"{name}.{bus} send", 0.0, 1.0)
                for bus in FX_BUSES
            },
            "send_taps": normalized_taps,
            "gain_db": _finite(raw.get("gain_db", 0.0), f"{name}.gain_db", -60.0, 12.0),
            "pan": _finite(raw.get("pan", 0.0), f"{name}.pan", -1.0, 1.0),
            "mute": bool(raw.get("mute", False)),
            "solo": bool(raw.get("solo", False)),
        }

    unknown_bus_names = set(source_buses) - set(FX_BUSES)
    if unknown_bus_names:
        raise ValueError("unknown FX bus(es): " + ", ".join(sorted(map(str, unknown_bus_names))))
    sidechains = normalise_sidechain_routes(
        payload.get("sidechains", ()), stem_names, int(sample_rate)
    )
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
        alignment = str(raw.get("alignment_policy", "start_aligned"))
        if alignment != "start_aligned":
            raise ValueError(f"{bus}.alignment_policy must be start_aligned")
        if preset not in FX_PRESETS:
            raise ValueError(f"Unknown bus preset for {bus}: {preset}")
        if division not in FX_DELAY_DIVISIONS:
            raise ValueError(f"Unknown {bus} delay division: {division}")
        if bus == "space" and division != "off":
            raise ValueError("Tempo-synchronised delay is available on the ECHO bus only")
        if division != "off" and not any(
            stage.get("type") == "delay" for stage in FX_PRESETS[preset]
        ):
            raise ValueError(f"Bus preset {preset!r} has no delay stage to synchronise")
        buses[bus] = {
            "chain": preset, "wet": wet, "tail_seconds": tail,
            "delay_sync": division, "alignment_policy": alignment,
        }
    return {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "routing_mode": mode,
        "master_wet": _finite(payload.get("master_wet", 1.0), "master_wet", 0.0, 1.0),
        "stems": stems, "buses": buses, "sidechains": sidechains,
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


def automation_envelope_wrapper(
    automation: Mapping[str, Any], target: str, *, frames: int, sample_rate: int,
    bpm: float, default: float,
) -> np.ndarray:
    points = automation.get("lanes", {}).get(target)
    return automation_envelope(
        points, frames=frames, sample_rate=sample_rate, bpm=bpm, default_value=default
    )


def _control_bus_envelope(
    controls: AutomationControlBus, target: str, *, frames: int,
    sample_rate: int, default: float,
) -> np.ndarray:
    if target not in controls.target_ids:
        return np.full(frames, float(default), dtype=np.float32)
    if frames <= 0:
        return np.zeros(max(0, frames), dtype=np.float32)
    step = controls.recommended_step_frames(target)
    if step is None:
        raise ValueError(
            f"event-clock target {target!r} cannot drive a continuous FX routing lane"
        )
    sampled = controls.sample(
        target, 0, frames, step_frames=step, default_value=float(default)
    )
    if not len(sampled.frames):
        return np.full(frames, float(default), dtype=np.float32)
    positions = np.arange(frames, dtype=np.float64)
    return np.interp(
        positions, sampled.frames.astype(np.float64), sampled.values.astype(np.float64),
        left=float(sampled.values[0]), right=float(sampled.values[-1]),
    ).astype(np.float32)


def _tempo_stages(
    bus_record: Mapping[str, Any], sample_rate: int, bpm: float
) -> tuple[dict[str, Any], ...]:
    preset = str(bus_record["chain"])
    stages = [dict(stage) for stage in FX_PRESETS[preset]]
    division = str(bus_record.get("delay_sync", "off"))
    if division != "off":
        delay_seconds = (60.0 / bpm) * FX_DELAY_DIVISIONS[division]
        delay_stage = next((stage for stage in stages if stage.get("type") == "delay"), None)
        if delay_stage is None:
            raise ValueError(f"Bus preset {preset!r} has no delay stage to synchronise")
        delay_stage["delay_seconds"] = delay_seconds
    return normalise_fx_stages(stages, sample_rate=sample_rate)


def _apply_pan(audio: np.ndarray, pan: float) -> np.ndarray:
    result = np.asarray(audio, dtype=np.float32).copy()
    value = _finite(pan, "pan", -1.0, 1.0)
    # Constant-power balance pan; centre remains unity on both channels.
    if value < 0.0:
        result[:, 1] *= math.cos(abs(value) * math.pi / 2.0)
    elif value > 0.0:
        result[:, 0] *= math.cos(value * math.pi / 2.0)
    return result


def measure_signal(audio: np.ndarray, *, sample_rate: int) -> dict[str, Any]:
    """Peak/RMS/crest/headroom at a named signal boundary; silence is finite."""
    value = np.asarray(audio, dtype=np.float64)
    if value.ndim == 1:
        value = value[:, None]
    if value.ndim != 2 or not np.isfinite(value).all():
        raise ValueError("meter input must be a finite mono or multichannel array")
    peak = float(np.max(np.abs(value))) if value.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(value)))) if value.size else 0.0
    floor = 1e-12
    peak_dbfs = max(-240.0, 20.0 * math.log10(max(peak, floor)))
    rms_dbfs = max(-240.0, 20.0 * math.log10(max(rms, floor)))
    crest_db = max(0.0, peak_dbfs - rms_dbfs) if rms > 0 else 0.0
    return {
        "frames": int(len(value)),
        "duration_seconds": len(value) / float(sample_rate),
        "channels": int(value.shape[1]),
        "peak": peak,
        "peak_dbfs": peak_dbfs,
        "rms": rms,
        "rms_dbfs": rms_dbfs,
        "crest_factor_db": crest_db,
        "headroom_db": max(0.0, -peak_dbfs),
    }



def match_audition_level(
    audio: np.ndarray,
    *,
    target_rms_dbfs: float = -18.0,
    peak_ceiling: float = 0.95,
) -> tuple[np.ndarray, dict[str, float]]:
    """Create a level-matched audition copy without changing production audio.

    RMS is matched where headroom allows. Gain is capped so the resulting peak
    never exceeds the explicit ceiling. Silence remains silence.
    """
    target = _finite(target_rms_dbfs, "target_rms_dbfs", -60.0, -3.0)
    ceiling = _finite(peak_ceiling, "peak_ceiling", 0.1, 1.0)
    value = np.asarray(audio, dtype=np.float32)
    if value.ndim not in {1, 2} or (value.ndim == 2 and value.shape[1] not in {1, 2}):
        raise ValueError("audition audio must be mono or stereo")
    if not np.isfinite(value).all():
        raise ValueError("audition audio must contain only finite samples")
    source = value.copy()
    rms = float(np.sqrt(np.mean(np.square(source, dtype=np.float64)))) if source.size else 0.0
    peak = float(np.max(np.abs(source))) if source.size else 0.0
    target_rms = 10.0 ** (target / 20.0)
    if rms <= 1e-12 or peak <= 1e-12:
        gain = 1.0
    else:
        requested = target_rms / rms
        gain = min(requested, ceiling / peak)
    matched = np.ascontiguousarray(source * gain, dtype=np.float32)
    matched_rms = (
        float(np.sqrt(np.mean(np.square(matched, dtype=np.float64))))
        if matched.size else 0.0
    )
    matched_peak = float(np.max(np.abs(matched))) if matched.size else 0.0
    return matched, {
        "target_rms_dbfs": target,
        "input_rms_dbfs": max(-240.0, 20.0 * math.log10(max(rms, 1e-12))),
        "output_rms_dbfs": max(-240.0, 20.0 * math.log10(max(matched_rms, 1e-12))),
        "input_peak": peak,
        "output_peak": matched_peak,
        "peak_ceiling": ceiling,
        "linear_gain": gain,
        "rms_target_reached": bool(
            rms <= 1e-12 or abs(matched_rms - target_rms) <= max(1e-8, target_rms * 1e-4)
        ),
    }


def render_fx_routing(
    dry_stems: Mapping[str, np.ndarray],
    sample_rate: int,
    routing: Mapping[str, Any] | None = None,
    *,
    bpm: float = 120.0,
    automation: Mapping[str, Any] | None = None,
    controls: AutomationControlBus | None = None,
    attention_gestures: Sequence[Mapping[str, Any]] | None = None,
    mix_controls: Mapping[str, Mapping[str, Any]] | None = None,
    include_audition_audio: bool = False,
    cancel_event: Any | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Render stem inserts and fixed SPACE/ECHO returns without mutating sources.

    Insert law is a linear dry/wet crossfade. Each send selects one of four
    pre/post-insert and pre/post-fader taps. Sends are gain contributions into
    an auxiliary bus; bus returns are wet-only and never re-add their dry input.
    Stem event buffers are immutable; direct inserts and return tails may extend
    the mix frame count. Built-in FX are start-aligned (zero declared latency).
    """
    _check_cancel(cancel_event)
    if not dry_stems:
        return {}, {
            "schema_version": FX_ROUTING_SCHEMA_VERSION, "buses": {},
            "master_wet": 1.0, "rendered_returns": [],
            "active_send_stems_by_bus": {}, "sidechains": [], "meters": {},
        }
    tempo = _finite(bpm, "bpm", 1.0, 1000.0)
    if controls is not None and automation is not None:
        raise ValueError("pass either legacy automation JSON or score controls, not both")
    if controls is not None and controls.timeline.sample_rate != int(sample_rate):
        raise ValueError("score automation control bus sample rate must match FX render rate")
    if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
        raise ValueError("sample_rate must be positive")
    attention_records = tuple(attention_gestures) if attention_gestures is not None else ()
    if attention_records and controls is None:
        raise ValueError(
            "M29 attention send gestures require the Score control bus timeline"
        )
    names = tuple(dry_stems)
    first = np.asarray(dry_stems[names[0]], dtype=np.float32)
    if first.ndim == 1:
        channels = 1
        first_stereo = _stereo(first, 1)
    elif first.ndim == 2 and first.shape[1] in {1, 2}:
        channels = int(first.shape[1])
        first_stereo = _stereo(first, channels)
    else:
        raise ValueError("dry stems must be mono or stereo")
    frames = len(first_stereo)
    config = normalise_fx_routing(
        routing if routing is not None else routing_defaults_for_project(names),
        names, int(sample_rate),
    )
    lanes = (
        normalise_fx_automation(automation, names)
        if controls is None else {"schema_version": 1, "lanes": {}}
    )
    mix = mix_controls or {}
    effective: dict[str, dict[str, Any]] = {}
    solo_active = False
    for name in names:
        route = config["stems"][name]
        controls_for_stem = mix.get(name, {})
        gain = _finite(
            controls_for_stem.get("gain", 10.0 ** (float(route["gain_db"]) / 20.0)),
            f"{name} mixer gain", 0.0, 4.0,
        )
        pan = _finite(controls_for_stem.get("pan", route["pan"]), f"{name} mixer pan", -1.0, 1.0)
        muted = bool(controls_for_stem.get("mute", route["mute"]))
        solo = bool(controls_for_stem.get("solo", route["solo"]))
        solo_active = solo_active or solo
        effective[name] = {"gain": gain, "pan": pan, "mute": muted, "solo": solo}
    audible = {
        name for name, values in effective.items()
        if not values["mute"] and (not solo_active or values["solo"])
    }

    # Sidechain detectors read the immutable source stem pre-insert/pre-fader.
    # Multiple routes to one target are combined by taking the strongest
    # requested reduction, avoiding surprise cumulative attenuation.
    sidechain_gains = {
        name: np.ones(frames, dtype=np.float32) for name in names
    }
    sidechain_summaries: list[dict[str, Any]] = []
    for sidechain in config["sidechains"]:
        _check_cancel(cancel_event)
        if sidechain["source_stem"] not in audible:
            sidechain_summaries.append({
                **sidechain,
                "bypassed": True,
                "bypass_reason": "source muted or excluded by solo",
                "max_reduction_db": 0.0,
                "mean_reduction_db": 0.0,
                "active_fraction": 0.0,
                "detector_peak_dbfs": -240.0,
            })
            continue
        try:
            gain_curve, summary = render_sidechain_gain_envelope(
                np.asarray(dry_stems[sidechain["source_stem"]], dtype=np.float32),
                frames,
                int(sample_rate),
                sidechain,
                cancel_event=cancel_event,
            )
        except InterruptedError as exc:
            raise FXRenderCancelledError("FX render cancelled") from exc
        sidechain_gains[sidechain["target_stem"]] = np.minimum(
            sidechain_gains[sidechain["target_stem"]], gain_curve
        ).astype(np.float32, copy=False)
        sidechain_summaries.append({**sidechain, **summary, "bypassed": False})

    bus_inputs = {bus: np.zeros((frames, channels), dtype=np.float32) for bus in FX_BUSES}
    active_stems_by_bus: dict[str, list[str]] = {bus: [] for bus in FX_BUSES}
    outputs: dict[str, np.ndarray] = {}
    inserts: dict[str, np.ndarray] = {}
    sends_audio: dict[str, dict[str, np.ndarray]] = {name: {} for name in names}
    direct_audio: dict[str, np.ndarray] = {}
    tails: dict[str, dict[str, Any]] = {}
    meter_direct: dict[str, Any] = {}
    meter_insert: dict[str, Any] = {}
    meter_sends: dict[str, dict[str, Any]] = {name: {} for name in names}

    for name, source in dry_stems.items():
        _check_cancel(cancel_event)
        dry_value = np.asarray(source, dtype=np.float32)
        dry = _stereo(dry_value, channels)
        if dry.shape != (frames, channels):
            raise ValueError("all dry stems must share the same frame and channel dimensions")
        if not np.isfinite(dry).all():
            raise ValueError(f"dry stem {name!r} contains non-finite samples")
        dry = dry.copy()
        dry *= sidechain_gains[name][:, None]
        direct_audio[name] = dry.copy()
        route = config["stems"][name]
        insert = route["insert"]
        insert_target = f"stem.{name}.insert_wet"
        insert_points = lanes["lanes"].get(insert_target)
        insert_controlled = controls is not None and insert_target in controls.target_ids
        insert_can_open = (
            insert["kind"] != "bypass" and (
                float(insert["wet"]) > 0.0
                or any(float(point["value"]) > 0.0 for point in (insert_points or ()))
                or insert_controlled
            )
        )
        if insert_can_open:
            processed_full = _stereo(
                _render_chain(dry, int(sample_rate), insert, wet=1.0), channels
            )
            _check_cancel(cancel_event)
            if insert_controlled:
                insert_level = _control_bus_envelope(
                    controls, insert_target, frames=frames,
                    sample_rate=int(sample_rate), default=float(insert["wet"]),
                )
            elif insert_points:
                insert_level = automation_envelope_wrapper(
                    lanes, insert_target, frames=frames,
                    sample_rate=int(sample_rate), bpm=tempo, default=float(insert["wet"]),
                )
            else:
                insert_level = np.full(frames, float(insert["wet"]), dtype=np.float32)
        else:
            processed_full = dry.copy()
            insert_level = np.zeros(frames, dtype=np.float32)

        processed_to_source = _pad_to(processed_full, frames)
        post_insert = (
            dry * (1.0 - insert_level[:, None])
            + processed_to_source * insert_level[:, None]
        ).astype(np.float32)
        # Any additional insert tail follows the last insert automation value.
        insert_tail = (
            processed_full[frames:] * float(insert_level[-1])
            if len(processed_full) > frames and frames else
            processed_full[frames:] if len(processed_full) > frames else
            np.empty((0, channels), dtype=np.float32)
        )
        if len(insert_tail):
            post_insert = np.concatenate((post_insert, insert_tail), axis=0)
        inserts[name] = post_insert.copy()
        direct_output = post_insert.copy()
        # CLI/portable routing has no separate GUI fader, so its v2 route
        # record owns direct mute/solo/gain/pan. The desktop passes explicit
        # mix_controls and applies those same controls after this cached pass.
        if mix_controls is None:
            if name not in audible:
                direct_output.fill(0.0)
            else:
                direct_output *= float(effective[name]["gain"])
                if channels == 2:
                    direct_output = _apply_pan(
                        direct_output, float(effective[name]["pan"])
                    )
        outputs[name] = np.ascontiguousarray(direct_output, dtype=np.float32)
        tails[name] = {
            "insert_tail_frames": max(0, len(post_insert) - frames),
            "insert_tail_seconds": max(0, len(post_insert) - frames) / float(sample_rate),
        }
        meter_direct[name] = measure_signal(dry, sample_rate=int(sample_rate))
        meter_insert[name] = measure_signal(post_insert, sample_rate=int(sample_rate))

        for bus, static_amount in route["sends"].items():
            _check_cancel(cancel_event)
            target = f"stem.{name}.send.{bus}"
            points = lanes["lanes"].get(target)
            send_frames = max(frames, len(dry), len(post_insert))
            if controls is not None and target in controls.target_ids:
                send_level = _control_bus_envelope(
                    controls, target, frames=send_frames,
                    sample_rate=int(sample_rate), default=float(static_amount),
                )
            elif points:
                send_level = automation_envelope_wrapper(
                    lanes, target, frames=send_frames,
                    sample_rate=int(sample_rate), bpm=tempo, default=float(static_amount),
                )
            else:
                send_level = np.full(send_frames, float(static_amount), dtype=np.float32)

            if attention_records:
                from reawarp.score.attention import build_attention_send_envelope

                gesture_level = build_attention_send_envelope(
                    attention_records,
                    role=name,
                    bus=bus,
                    timeline=controls.timeline,
                    frames=send_frames,
                )
                send_level = np.clip(
                    send_level * gesture_level, 0.0, 1.0
                ).astype(np.float32, copy=False)

            tap = route["send_taps"][bus]
            pre_insert = tap.startswith("pre_insert")
            post_fader = tap.endswith("post_fader")
            selected = dry if pre_insert else post_insert
            selected = _pad_to(selected, send_frames).copy()
            fader = effective[name]
            if name not in audible:
                send_level = np.zeros_like(send_level)
            elif post_fader:
                selected *= float(fader["gain"])
                selected = _apply_pan(selected, float(fader["pan"])) if channels == 2 else selected
            contribution = np.ascontiguousarray(selected * send_level[:, None], dtype=np.float32)
            sends_audio[name][bus] = contribution.copy()
            meter_sends[name][bus] = measure_signal(contribution, sample_rate=int(sample_rate))
            if np.any(contribution):
                target_buffer = bus_inputs[bus]
                if len(contribution) > len(target_buffer):
                    target_buffer = _pad_to(target_buffer, len(contribution))
                target_buffer[:len(contribution)] += contribution
                bus_inputs[bus] = target_buffer
                if name not in active_stems_by_bus[bus]:
                    active_stems_by_bus[bus].append(name)

    returns: dict[str, np.ndarray] = {}
    meter_returns: dict[str, Any] = {}
    for bus, source in bus_inputs.items():
        _check_cancel(cancel_event)
        record = config["buses"][bus]
        target = f"bus.{bus}.wet"
        points = lanes["lanes"].get(target)
        if controls is not None and target in controls.target_ids:
            requested_wet = _control_bus_envelope(
                controls, target, frames=max(len(source), 1),
                sample_rate=int(sample_rate), default=float(record["wet"]),
            )
        elif points:
            requested_wet = automation_envelope_wrapper(
                lanes, target, frames=max(len(source), 1),
                sample_rate=int(sample_rate), bpm=tempo, default=float(record["wet"]),
            )
        else:
            requested_wet = np.full(
                max(len(source), 1), float(record["wet"]), dtype=np.float32
            )
        if not np.any(source) or not np.any(requested_wet):
            meter_returns[bus] = measure_signal(
                np.zeros((0, channels), dtype=np.float32), sample_rate=int(sample_rate)
            )
            continue
        stages = tuple(
            {**stage, "mix": 1.0} for stage in _tempo_stages(
                record, int(sample_rate), tempo
            )
        )
        processed = _stereo(
            render_pyo_fx(
                source, int(sample_rate), preset=None, stages=stages,
                wet=1.0, tail_seconds=float(record["tail_seconds"]),
            ), channels,
        )
        _check_cancel(cancel_event)
        wet_envelope = _control_bus_envelope(
            controls, target, frames=len(processed),
            sample_rate=int(sample_rate), default=float(record["wet"]),
        ) if controls is not None and target in controls.target_ids else (
            automation_envelope_wrapper(
                lanes, target, frames=len(processed), sample_rate=int(sample_rate),
                bpm=tempo, default=float(record["wet"]),
            ) if points else np.full(len(processed), float(record["wet"]), dtype=np.float32)
        )
        returns[bus] = np.ascontiguousarray(processed * wet_envelope[:, None], dtype=np.float32)
        meter_returns[bus] = measure_signal(returns[bus], sample_rate=int(sample_rate))

    meter_master_input = {}
    for name in names:
        meter_master_input[name] = measure_signal(outputs[name], sample_rate=int(sample_rate))
    tail_report = {
        bus: {
            "input_frames": int(len(bus_inputs[bus])),
            "return_frames": int(len(returns.get(bus, ()))),
            "tail_frames": max(0, len(returns.get(bus, ())) - len(bus_inputs[bus])),
            "tail_seconds": max(0, len(returns.get(bus, ())) - len(bus_inputs[bus])) / float(sample_rate),
            "latency_frames": 0,
            "alignment_policy": config["buses"][bus]["alignment_policy"],
        }
        for bus in FX_BUSES
    }
    metadata = {
        "schema_version": FX_ROUTING_SCHEMA_VERSION,
        "routing_mode": config["routing_mode"],
        "master_wet": config["master_wet"],
        "bpm": tempo,
        "stems": config["stems"],
        "buses": config["buses"],
        "sidechains": config["sidechains"],
        "sidechain_summaries": sidechain_summaries,
        "rendered_returns": list(returns),
        "active_send_stems_by_bus": active_stems_by_bus,
        "automation_lanes": list(controls.target_ids) if controls is not None else list(lanes["lanes"]),
        "automation_source": "score-control-bus" if controls is not None else "legacy-json",
        "send_semantics": {
            "tap_points": list(SEND_TAP_POINTS),
            "pre_fader": "send is unaffected by fader gain/pan; explicit mute and non-solo exclusion still gate it",
            "post_fader": "send receives the current fader gain and pan",
            "pre_insert": "send taps the immutable dry stem",
            "post_insert": "send taps the dry/wet insert output including its tail",
            "return": "wet-only auxiliary output; dry send signal remains on the direct path",
        },
        "tails": tail_report,
        "latency": {bus: {"frames": 0, "policy": "start_aligned"} for bus in FX_BUSES},
        "meters": {
            "direct": meter_direct,
            "insert": meter_insert,
            "sends": meter_sends,
            "returns": meter_returns,
            "sidechain": {
                item["route_id"]: {
                    key: item[key] for key in (
                        "source_stem", "target_stem", "max_reduction_db",
                        "mean_reduction_db", "active_fraction",
                        "detector_peak_dbfs", "bypassed",
                    ) if key in item
                }
                for item in sidechain_summaries
            },
            "post_insert_stems": meter_master_input,
        },
    }
    metadata["bus_returns_audio"] = returns
    if include_audition_audio:
        metadata["audition_audio"] = {
            "direct": direct_audio,
            "insert": inserts,
            "sends": sends_audio,
            "returns": {bus: audio.copy() for bus, audio in returns.items()},
            "sidechain_gain": {
                name: curve.copy() for name, curve in sidechain_gains.items()
            },
        }
    return outputs, metadata


def render_master_with_returns(
    processed_stems: Mapping[str, np.ndarray],
    bus_returns: Mapping[str, np.ndarray],
    *,
    frames: int | None = None,
    master_wet: float = 1.0,
) -> np.ndarray:
    """Sum aligned post-insert stems and wet-only auxiliary returns."""
    wet = _finite(master_wet, "master_wet", 0.0, 1.0)
    all_buffers = [*processed_stems.values(), *bus_returns.values()]
    if frames is None:
        frames = max((len(item) for item in all_buffers), default=0)
    first = np.asarray(all_buffers[0]) if all_buffers else np.zeros((0, 2), dtype=np.float32)
    channels = 1 if first.ndim == 1 else int(first.shape[1])
    if channels not in {1, 2}:
        raise ValueError("master inputs must be mono or stereo")
    master = np.zeros((frames, channels), dtype=np.float32)
    for audio in all_buffers:
        value = _stereo(np.asarray(audio), channels)
        count = min(frames, len(value))
        master[:count] += value[:count]
    # Master gain precedes the output guard; retain mono/stereo channel count.
    master *= wet
    peak = float(np.max(np.abs(master))) if master.size else 0.0
    ceiling = 10.0 ** (-1.0 / 20.0)
    if peak > ceiling:
        master *= ceiling / peak
    return np.ascontiguousarray(master, dtype=np.float32)
