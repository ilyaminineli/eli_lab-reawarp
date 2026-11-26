"""M29 attention descriptors, listening checks and human review provenance.

These helpers operate on audition/analysis copies and symbolic Score metadata.
They do not rewrite production audio or claim to measure artistic quality.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
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


__all__ = [
    "ATTENTION_REVIEW_STATES",
    "attention_conflict_id",
    "build_attention_translation_check",
    "estimate_attention_descriptors",
    "record_attention_review",
]
