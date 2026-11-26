"""M29 attention descriptors, render gestures and human review provenance.

Descriptors and review records are symbolic Score metadata; translation checks use
disposable audio copies. Reversible gestures are resolved against render-time event
copies, leaving canonical Score events and source assets unchanged. Descriptor
estimates are not psychoacoustic measurements or artistic quality scores.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from fractions import Fraction
from typing import Any, Iterable, Mapping

import numpy as np

from reawarp.score.orchestration_intent import AttentionSpan


ATTENTION_REVIEW_STATES = frozenset({"useful", "masked", "unresolved"})


def _stable_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False, default=str,
    )


def attention_conflict_id(conflict: Mapping[str, Any]) -> str:
    """Stable identity for a diagnostic, independent of its displayed list position."""
    payload = {
        key: conflict[key]
        for key in (
            "kind", "roles", "semantic_roles", "start_beats", "end_beats",
            "onset_beats", "event_ids", "evidence", "handoff_id",
        )
        if key in conflict
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def estimate_attention_descriptors(
    events: Iterable[Any],
    spans: Iterable[AttentionSpan],
    *,
    fill_missing: bool = True,
) -> tuple[AttentionSpan, ...]:
    """Fill optional descriptors from Score events, not from psychoacoustic audio analysis.

    Register uses note pitch coordinates; onset density is events per beat;
    transient strength and prominence use event velocity proxies; sustain is
    occupied-beat ratio; spatial position uses authored pan/spatial parameters.
    Existing authored descriptors are retained when fill_missing=True.
    """
    event_list = tuple(events)
    result: list[AttentionSpan] = []
    aliases = {"hats": "hat", "synthetic_break": "break"}
    for span in spans:
        role = aliases.get(span.role, span.role)
        selected = [
            event for event in event_list
            if aliases.get(str(getattr(event, "voice_id", "")),
                           str(getattr(event, "voice_id", ""))) == role
            and span.start_beats <= event.onset_beats < span.end_beats
            and getattr(event, "kind", None) not in {"marker", "control"}
        ]
        duration = float(span.end_beats - span.start_beats)
        transient_events = [
            event for event in selected if event.kind in {"hit", "trigger", "grain"}
        ]
        panned = [
            float(event.parameters.get(
                "spatial_position", event.parameters.get("pan")
            ))
            for event in selected
            if event.parameters.get(
                "spatial_position", event.parameters.get("pan")
            ) is not None
        ]
        values: dict[str, float | None] = {
            "onset_density": len(selected) / duration if duration > 0.0 else None,
            "transient_strength": (
                float(np.mean([event.velocity for event in transient_events]))
                if transient_events else None
            ),
            "sustain": (
                min(1.0, sum(float(event.duration_beats) for event in selected) / duration)
                if selected and duration > 0.0 else None
            ),
            "spatial_position": float(np.mean(panned)) if panned else None,
            "prominence": (
                float(np.mean([event.velocity for event in selected]))
                if selected else None
            ),
        }
        pitches = [
            float(event.pitch) for event in selected
            if getattr(event, "kind", None) == "note" and event.pitch is not None
        ]
        changes: dict[str, Any] = {}
        for name, value in values.items():
            current = getattr(span, name)
            if value is not None and (not fill_missing or current is None):
                if name == "spatial_position":
                    value = float(np.clip(value, -1.0, 1.0))
                elif name != "onset_density":
                    value = float(np.clip(value, 0.0, 1.0))
                changes[name] = value
        if pitches:
            if not fill_missing or span.register_low is None:
                changes["register_low"] = min(pitches)
            if not fill_missing or span.register_high is None:
                changes["register_high"] = max(pitches)
        result.append(replace(span, **changes) if changes else span)
    return tuple(result)


def record_attention_review(
    score: Any,
    conflict: Mapping[str, Any],
    *,
    disposition: str,
    notes: str = "",
) -> Any:
    """Return a Score with human disposition and diagnostic provenance attached."""
    if disposition not in ATTENTION_REVIEW_STATES:
        raise ValueError(f"unsupported attention review disposition: {disposition}")
    conflict_id = attention_conflict_id(conflict)
    metadata = copy.deepcopy(score.metadata)
    reviews = copy.deepcopy(metadata.get("m29_attention_reviews", {}))
    plan = score.orchestration_plan or {}
    plan_fingerprint = hashlib.sha256(
        _stable_json(plan).encode("utf-8")
    ).hexdigest() if plan else None
    reviews[conflict_id] = {
        "schema_version": 1,
        "conflict_id": conflict_id,
        "conflict": copy.deepcopy(dict(conflict)),
        "disposition": disposition,
        "notes": str(notes).strip(),
        "plan_fingerprint": plan_fingerprint,
    }
    metadata["m29_attention_reviews"] = reviews
    return replace(score, metadata=metadata)


def build_attention_translation_check(
    audio: Any,
    mode: str,
    *,
    attenuation_db: float = 20.0,
) -> np.ndarray:
    """Create a disposable mono-fold or low-level audition copy."""
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim not in {1, 2}:
        raise ValueError("translation-check audio must be mono or frame-major multichannel")
    if not np.all(np.isfinite(source)):
        raise ValueError("translation-check audio must contain only finite samples")
    if mode == "mono":
        if source.ndim == 1:
            mono = source.copy()
        else:
            if source.shape[1] not in {1, 2}:
                raise ValueError("mono check currently supports mono or stereo sources")
            mono = source.mean(axis=1, dtype=np.float32)
        result = np.repeat(mono[:, None], 2, axis=1)
        return np.ascontiguousarray(result, dtype=np.float32)
    if mode == "low_volume":
        attenuation = float(attenuation_db)
        if not np.isfinite(attenuation) or not 0.0 <= attenuation <= 60.0:
            raise ValueError("attenuation_db must be finite and between 0 and 60")
        gain = np.float32(10.0 ** (-attenuation / 20.0))
        return np.ascontiguousarray(source.copy() * gain, dtype=np.float32)
    raise ValueError(f"unsupported translation check: {mode}")




ATTENTION_GESTURE_ACTIONS = frozenset({"focus", "recede"})
ATTENTION_GESTURE_SCHEMA_VERSION = 1
_RECEDE_EVENT_DROP_PROBABILITY = 0.14
_PROTECTED_ATTENTION_ROLES = frozenset({
    "kick", "bass", "sub", "sub_bass", "low_frequency",
})


def _attention_gesture_key(role: str, start: Any, end: Any) -> str:
    from reawarp.score.time import as_fraction

    payload = (
        f"reawarp:m29-attention-gesture:v1:{role}:"
        f"{as_fraction(start)}:{as_fraction(end)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _validated_attention_gestures(records: Any) -> tuple[dict[str, Any], ...]:
    from reawarp.score.time import as_fraction

    if records is None:
        return ()
    if not isinstance(records, (list, tuple)):
        raise ValueError("m29_attention_gestures must be a list")
    result = []
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise ValueError(f"attention gesture {index} must be an object")
        item = dict(raw)
        if int(item.get("schema_version", 0)) != ATTENTION_GESTURE_SCHEMA_VERSION:
            raise ValueError(f"attention gesture {index} has an unsupported schema version")
        role = str(item.get("role", "")).strip()
        if not role:
            raise ValueError(f"attention gesture {index} requires a role")
        start = as_fraction(str(item.get("start_beats", "")))
        end = as_fraction(str(item.get("end_beats", "")))
        if start < 0 or end <= start:
            raise ValueError(f"attention gesture {index} requires 0 <= start < end")
        action = str(item.get("action", ""))
        if action not in ATTENTION_GESTURE_ACTIONS:
            raise ValueError(f"attention gesture {index} has an unsupported action")
        shift = float(item.get("register_shift_semitones", 0.0))
        if not np.isfinite(shift) or not -24.0 <= shift <= 24.0:
            raise ValueError(
                f"attention gesture {index} register shift must be finite and within -24..24"
            )
        gesture_id = str(item.get("gesture_id", "")).strip()
        if not gesture_id:
            gesture_id = _attention_gesture_key(role, start, end)
        result.append({
            "schema_version": ATTENTION_GESTURE_SCHEMA_VERSION,
            "gesture_id": gesture_id,
            "role": role,
            "start_beats": str(start),
            "end_beats": str(end),
            "action": action,
            "register_shift_semitones": shift,
        })
    return tuple(result)


def apply_attention_gesture(
    score: Any,
    *,
    role: str,
    start_beats: Any,
    end_beats: Any,
    action: str,
    register_shift_semitones: float = 0.0,
) -> Any:
    """Return a Score with one reversible, rational-beat figure/ground gesture.

    The gesture is stored as provenance, not baked into Score events or source audio.
    Renderer-side copies resolve it for events whose onsets fall in the half-open span.
    """
    from reawarp.score.model import Score
    from reawarp.score.time import as_fraction

    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    role = str(role).strip()
    if not role:
        raise ValueError("attention gesture role cannot be empty")
    start, end = as_fraction(start_beats), as_fraction(end_beats)
    if start < 0 or end <= start:
        raise ValueError("attention gesture requires 0 <= start < end")
    if action not in ATTENTION_GESTURE_ACTIONS:
        raise ValueError("attention gesture action must be focus or recede")
    shift = float(register_shift_semitones)
    if not np.isfinite(shift) or not -24.0 <= shift <= 24.0:
        raise ValueError("register_shift_semitones must be finite and within -24..24")
    aliases = {"hats": "hat", "synthetic_break": "break"}
    canonical_role = aliases.get(role, role)
    has_event_material = any(
        aliases.get(str(event.voice_id), str(event.voice_id)) == canonical_role
        and start <= event.onset_beats < end
        and event.kind not in {"control", "marker"}
        for event in score.events
    )
    if not has_event_material:
        raise ValueError(
            f"no event-backed Score material for role {role!r} in "
            f"the selected beat span; whole-field layers are not part of this render slice"
        )

    metadata = copy.deepcopy(score.metadata)
    records = _validated_attention_gestures(metadata.get("m29_attention_gestures", []))
    gesture_id = _attention_gesture_key(role, start, end)
    updated = [
        item for item in records
        if item["gesture_id"] != gesture_id
    ]
    updated.append({
        "schema_version": ATTENTION_GESTURE_SCHEMA_VERSION,
        "gesture_id": gesture_id,
        "role": role,
        "start_beats": str(start),
        "end_beats": str(end),
        "action": action,
        "register_shift_semitones": shift,
    })
    updated.sort(key=lambda item: (
        as_fraction(item["start_beats"]),
        as_fraction(item["end_beats"]),
        item["role"],
        item["gesture_id"],
    ))
    metadata["m29_attention_gestures"] = list(updated)
    return replace(score, metadata=metadata)


def remove_attention_gesture(
    score: Any,
    *,
    role: str,
    start_beats: Any,
    end_beats: Any,
) -> Any:
    """Remove the exact role/span gesture and return the unchanged base Score events."""
    from reawarp.score.model import Score
    from reawarp.score.time import as_fraction

    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    role = str(role).strip()
    start, end = as_fraction(start_beats), as_fraction(end_beats)
    if not role or start < 0 or end <= start:
        raise ValueError("attention gesture removal requires a role and 0 <= start < end")
    gesture_id = _attention_gesture_key(role, start, end)
    metadata = copy.deepcopy(score.metadata)
    records = _validated_attention_gestures(metadata.get("m29_attention_gestures", []))
    remaining = [item for item in records if item["gesture_id"] != gesture_id]
    if len(remaining) == len(records):
        return score
    if remaining:
        metadata["m29_attention_gestures"] = list(remaining)
    else:
        metadata.pop("m29_attention_gestures", None)
    return replace(score, metadata=metadata)


def reconcile_attention_gestures(
    score: Any,
    attention_spans: Iterable[AttentionSpan],
) -> tuple[Any, int]:
    """Drop render gestures whose exact role/span no longer exists in the attention plan."""
    from reawarp.score.model import Score

    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    aliases = {"hats": "hat", "synthetic_break": "break"}
    valid = {
        (
            aliases.get(span.role, span.role),
            str(span.start_beats),
            str(span.end_beats),
        )
        for span in attention_spans
    }
    metadata = copy.deepcopy(score.metadata)
    records = _validated_attention_gestures(
        metadata.get("m29_attention_gestures", [])
    )
    remaining = [
        item for item in records
        if (
            aliases.get(item["role"], item["role"]),
            item["start_beats"],
            item["end_beats"],
        ) in valid
    ]
    removed = len(records) - len(remaining)
    if not removed:
        return score, 0
    if remaining:
        metadata["m29_attention_gestures"] = list(remaining)
    else:
        metadata.pop("m29_attention_gestures", None)
    return replace(score, metadata=metadata), removed


def apply_attention_gesture_to_event(
    event: Any,
    gestures: Any,
) -> Any | None:
    """Transform one render-time event copy using the matching M29 gesture.

    Recede's event thinning is deterministic and excludes kick/sub and explicitly
    tagged anchors. Articulation, optional register translation and spatial cues
    affect only this event's render representation; the canonical Score stays intact.
    """
    from reawarp.score.time import as_fraction

    if getattr(event, "kind", None) in {"control", "marker"}:
        return event
    records = _validated_attention_gestures(gestures)
    if not records:
        return event
    aliases = {"hats": "hat", "synthetic_break": "break"}
    role = aliases.get(str(event.voice_id), str(event.voice_id))
    matching = []
    for item in records:
        gesture_role = aliases.get(item["role"], item["role"])
        start = as_fraction(item["start_beats"])
        end = as_fraction(item["end_beats"])
        if gesture_role == role and start <= event.onset_beats < end:
            matching.append((end - start, -start, item))
    if not matching:
        return event
    # When authored spans overlap, prefer the most local instruction.
    gesture = min(matching, key=lambda item: (item[0], item[1]))[2]
    action = gesture["action"]
    gesture_id = gesture["gesture_id"]
    parameters = dict(event.parameters)
    tags = {str(value).casefold() for value in getattr(event, "tags", ())}
    source_kind = str(parameters.get("source_kind", "")).casefold()
    protected = (
        role in _PROTECTED_ATTENTION_ROLES
        or source_kind in {"kick", "sub", "bass"}
        or bool(tags & {"anchor", "low_frequency_foundation", "sub_anchor"})
        or str(parameters.get("attention_role", "")).casefold()
        in {"anchor", "low_frequency_foundation"}
    )

    if action == "recede" and not protected:
        material = f"reawarp:m29-recede:{gesture_id}:{event.event_id}".encode("utf-8")
        value = int.from_bytes(
            hashlib.blake2b(material, digest_size=8).digest(), "little"
        ) / float(1 << 64)
        if value < _RECEDE_EVENT_DROP_PROBABILITY:
            return None

    changes: dict[str, Any] = {"parameters": parameters}
    if getattr(event, "kind", None) == "note":
        shift = float(gesture["register_shift_semitones"])
        if shift:
            if event.pitch is not None:
                changes["pitch"] = float(event.pitch) + shift
            if event.frequency_hz is not None:
                changes["frequency_hz"] = float(event.frequency_hz) * (
                    2.0 ** (shift / 12.0)
                )
        duration = as_fraction(event.duration_beats)
        if duration > 0:
            base_gate = as_fraction(str(
                parameters.get("gate_duration_beats", duration)
            ))
            gate_ratio = 1.08 if action == "focus" else 0.58
            floor = min(Fraction(1, 64), duration)
            gate = max(floor, min(duration, base_gate * Fraction(str(gate_ratio))))
            parameters["gate_duration_beats"] = str(gate)
            changes["articulation"] = "legato" if action == "focus" else "staccato"

    if not protected:
        try:
            pan = float(parameters.get("pan", parameters.get("spatial_position", 0.0)))
        except (TypeError, ValueError):
            pan = 0.0
        pan = float(np.clip(pan, -1.0, 1.0))
        if action == "focus":
            parameters["m29_pan_factor"] = 0.45
            parameters["m29_spatial_width_factor"] = 0.82
        else:
            material = f"reawarp:m29-space:{gesture_id}:{event.event_id}".encode("utf-8")
            side = -1.0 if (
                int.from_bytes(hashlib.blake2b(material, digest_size=1).digest(), "little") & 1
            ) == 0 else 1.0
            if abs(pan) < 0.08:
                parameters["m29_pan_offset"] = side * 0.18
            else:
                parameters["m29_pan_factor"] = 1.25
            parameters["m29_spatial_width_factor"] = 1.18
    parameters["m29_attention_gesture_id"] = gesture_id
    parameters["m29_attention_action"] = action
    return replace(event, **changes)


__all__ = [
    "ATTENTION_GESTURE_ACTIONS",
    "ATTENTION_GESTURE_SCHEMA_VERSION",
    "ATTENTION_REVIEW_STATES",
    "apply_attention_gesture",
    "apply_attention_gesture_to_event",
    "attention_conflict_id",
    "build_attention_translation_check",
    "estimate_attention_descriptors",
    "record_attention_review",
    "reconcile_attention_gestures",
    "remove_attention_gesture",
]
