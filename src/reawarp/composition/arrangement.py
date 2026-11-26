"""M33 Score-native arrangement editing, freeze, print lineage and finishing gates."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import secrets
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from reawarp.composition.phrases import PhrasePlan, PhraseSpan
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.time import as_fraction

ARRANGEMENT_FORMAT = "eli_lab_reawarp_arrangement"
ARRANGEMENT_SCHEMA_VERSION = 1
ARRANGEMENT_METADATA_KEY = "m33_arrangement"
MAX_EDIT_HISTORY = 50
CHECKLIST_ITEMS = (
    "form_review",
    "ending_review",
    "subtraction",
    "identity_invariance",
    "context",
    "low_volume",
    "mono",
    "peak_headroom",
    "missing_sources",
    "export_integrity",
)


def _json_copy(value: Any, name: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite JSON-compatible values") from exc


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _beat(value: Any, name: str) -> Fraction:
    try:
        result = as_fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{name} must be an exact rational beat value") from exc
    if result < 0:
        raise ValueError(f"{name} cannot be negative")
    return result


def _unique(values: Any, name: str) -> tuple[str, ...]:
    result = tuple(str(item).strip() for item in values)
    if any(not item for item in result) or len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique, non-empty strings")
    return result


def _score_snapshot(score: Score) -> dict[str, Any]:
    data = score.to_dict()
    metadata = dict(data.get("metadata", {}))
    metadata.pop(ARRANGEMENT_METADATA_KEY, None)
    data["metadata"] = metadata
    return data


def _score_fingerprint(score: Score) -> str:
    return _fingerprint(_score_snapshot(score))


def _record_fingerprint(record: Mapping[str, Any]) -> str:
    payload = dict(record)
    payload.pop("fingerprint", None)
    return _fingerprint(payload)


@dataclass(frozen=True, slots=True)
class ArrangementClip:
    """One placement of one phrase definition on the arrangement timeline."""

    clip_id: str
    phrase_id: str
    source_phrase_id: str
    start_beats: Fraction
    end_beats: Fraction
    source_start_beats: Fraction
    source_end_beats: Fraction
    event_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    muted: bool = False
    frozen: bool = False
    label: str = ""
    candidate_id: str | None = None
    parent_clip_id: str | None = None
    role_map: Mapping[str, str] | None = None
    original_velocities: Mapping[str, float] | None = None
    origin: str = "generated"
    revision: int = 0

    def __post_init__(self) -> None:
        for name in ("clip_id", "phrase_id", "source_phrase_id"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"arrangement {name} cannot be empty")
            object.__setattr__(self, name, value)
        start = _beat(self.start_beats, "clip start")
        end = _beat(self.end_beats, "clip end")
        source_start = _beat(self.source_start_beats, "clip source start")
        source_end = _beat(self.source_end_beats, "clip source end")
        if end <= start or source_end <= source_start:
            raise ValueError("arrangement clips require positive source and destination spans")
        if end - start != source_end - source_start:
            raise ValueError("arrangement clips do not time-stretch; source and destination spans must match")
        if self.origin not in {"generated", "candidate", "manual", "printed"}:
            raise ValueError("unsupported arrangement clip origin")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("clip revision must be a non-negative integer")
        event_ids = _unique(self.event_ids, "clip event IDs")
        source_event_ids = _unique(self.source_event_ids, "clip source event IDs")
        role_map = {} if self.role_map is None else dict(self.role_map)
        if any(not str(key).strip() or not str(value).strip() for key, value in role_map.items()):
            raise ValueError("clip role map requires non-empty role names")
        velocities = {} if self.original_velocities is None else dict(self.original_velocities)
        for event_id, velocity in velocities.items():
            if event_id not in event_ids or not math.isfinite(float(velocity)) or not 0 <= float(velocity) <= 1:
                raise ValueError("clip mute snapshots must map current events to valid velocities")
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        object.__setattr__(self, "source_start_beats", source_start)
        object.__setattr__(self, "source_end_beats", source_end)
        object.__setattr__(self, "event_ids", event_ids)
        object.__setattr__(self, "source_event_ids", source_event_ids)
        object.__setattr__(self, "role_map", {str(k): str(v) for k, v in role_map.items()})
        object.__setattr__(self, "original_velocities", {
            str(k): float(v) for k, v in velocities.items()
        })
        object.__setattr__(self, "label", str(self.label).strip())
        if self.candidate_id is not None:
            candidate = str(self.candidate_id).strip()
            if not candidate:
                raise ValueError("candidate_id must be non-empty or None")
            object.__setattr__(self, "candidate_id", candidate)
        if self.parent_clip_id is not None:
            object.__setattr__(self, "parent_clip_id", str(self.parent_clip_id).strip())

    @property
    def duration_beats(self) -> Fraction:
        return self.end_beats - self.start_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "phrase_id": self.phrase_id,
            "source_phrase_id": self.source_phrase_id,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "source_start_beats": str(self.source_start_beats),
            "source_end_beats": str(self.source_end_beats),
            "event_ids": list(self.event_ids),
            "source_event_ids": list(self.source_event_ids),
            "muted": self.muted,
            "frozen": self.frozen,
            "label": self.label,
            "candidate_id": self.candidate_id,
            "parent_clip_id": self.parent_clip_id,
            "role_map": dict(self.role_map),
            "original_velocities": dict(self.original_velocities),
            "origin": self.origin,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArrangementClip":
        return cls(
            clip_id=str(data.get("clip_id", "")),
            phrase_id=str(data.get("phrase_id", "")),
            source_phrase_id=str(data.get("source_phrase_id", data.get("phrase_id", ""))),
            start_beats=data.get("start_beats", "0"),
            end_beats=data.get("end_beats", "1"),
            source_start_beats=data.get("source_start_beats", "0"),
            source_end_beats=data.get("source_end_beats", "1"),
            event_ids=tuple(data.get("event_ids", ())),
            source_event_ids=tuple(data.get("source_event_ids", data.get("event_ids", ()))),
            muted=bool(data.get("muted", False)),
            frozen=bool(data.get("frozen", False)),
            label=str(data.get("label", "")),
            candidate_id=data.get("candidate_id"),
            parent_clip_id=data.get("parent_clip_id"),
            role_map=data.get("role_map", {}),
            original_velocities=data.get("original_velocities", {}),
            origin=str(data.get("origin", "generated")),
            revision=int(data.get("revision", 0)),
        )


@dataclass(frozen=True, slots=True)
class ArrangementPlan:
    """Validated view of the versioned M33 state stored in Score metadata."""

    arrangement_id: str
    revision: int
    clips: tuple[ArrangementClip, ...]
    parent_arrangement_id: str | None = None
    checklist: Mapping[str, bool] | None = None

    def __post_init__(self) -> None:
        if not str(self.arrangement_id).strip():
            raise ValueError("arrangement ID cannot be empty")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("arrangement revision must be a non-negative integer")
        clips = tuple(
            item if isinstance(item, ArrangementClip) else ArrangementClip.from_dict(item)
            for item in self.clips
        )
        if len({item.clip_id for item in clips}) != len(clips):
            raise ValueError("arrangement clip IDs must be unique")
        if len({item.phrase_id for item in clips}) != len(clips):
            raise ValueError("each arrangement clip requires its own phrase identity")
        checklist = dict(self.checklist or {})
        unknown = set(checklist) - set(CHECKLIST_ITEMS)
        if unknown:
            raise ValueError("unknown finishing checklist item(s): " + ", ".join(sorted(unknown)))
        if any(not isinstance(value, bool) for value in checklist.values()):
            raise ValueError("finishing checklist values must be boolean")
        object.__setattr__(self, "clips", tuple(sorted(
            clips, key=lambda item: (item.start_beats, item.end_beats, item.clip_id)
        )))
        object.__setattr__(self, "checklist", {
            item: bool(checklist.get(item, False)) for item in CHECKLIST_ITEMS
        })

    @classmethod
    def from_score(cls, score: Score) -> "ArrangementPlan":
        record = score.metadata.get(ARRANGEMENT_METADATA_KEY)
        if not isinstance(record, dict):
            raise ValueError("Score has no M33 arrangement; create one from its M28 phrases")
        if record.get("format") != ARRANGEMENT_FORMAT:
            raise ValueError("unsupported M33 arrangement format")
        if int(record.get("schema_version", 0)) != ARRANGEMENT_SCHEMA_VERSION:
            raise ValueError("unsupported M33 arrangement schema version")
        if record.get("fingerprint") != _record_fingerprint(record):
            raise ValueError("M33 arrangement fingerprint does not match its contents")
        if record.get("score_fingerprint") != _score_fingerprint(score):
            raise ValueError("Score changed outside M33; rebuild the arrangement before editing")
        plan = cls(
            arrangement_id=str(record.get("arrangement_id", "")),
            revision=int(record.get("revision", 0)),
            clips=tuple(ArrangementClip.from_dict(item) for item in record.get("clips", ())),
            parent_arrangement_id=record.get("parent_arrangement_id"),
            checklist=record.get("checklist", {}),
        )
        phrase_plan = PhrasePlan.from_score(score)
        phrases = {item.phrase_id: item for item in phrase_plan.phrases}
        by_id = {event.event_id: event for event in score.events}
        for clip in plan.clips:
            phrase = phrases.get(clip.phrase_id)
            if phrase is None:
                raise ValueError(f"arrangement clip references missing phrase: {clip.phrase_id}")
            if (phrase.start_beats, phrase.end_beats) != (clip.start_beats, clip.end_beats):
                raise ValueError(f"arrangement clip timing differs from phrase {clip.phrase_id}")
            if tuple(phrase.event_ids) != tuple(clip.event_ids):
                raise ValueError(f"arrangement clip event references differ from phrase {clip.phrase_id}")
            missing = set(clip.event_ids) - set(by_id)
            if missing:
                raise ValueError("arrangement references missing Score events: " + ", ".join(sorted(missing)))
            for event_id in clip.event_ids:
                event = by_id[event_id]
                if event.onset_beats < clip.start_beats or event.end_beats > clip.end_beats:
                    raise ValueError(f"event {event_id} falls outside arrangement clip {clip.clip_id}")
        return plan


def _record_for_score(score: Score) -> dict[str, Any]:
    raw = score.metadata.get(ARRANGEMENT_METADATA_KEY)
    if not isinstance(raw, dict):
        raise ValueError("Score has no M33 arrangement; create one first")
    record = _json_copy(raw, "M33 arrangement")
    if record.get("format") != ARRANGEMENT_FORMAT or int(record.get("schema_version", 0)) != ARRANGEMENT_SCHEMA_VERSION:
        raise ValueError("unsupported M33 arrangement schema")
    if record.get("fingerprint") != _record_fingerprint(record):
        raise ValueError("M33 arrangement fingerprint does not match its contents")
    if record.get("score_fingerprint") != _score_fingerprint(score):
        raise ValueError("Score changed outside M33; rebuild the arrangement before editing")
    ArrangementPlan.from_score(score)
    return record


def _clean_score(score: Score) -> Score:
    metadata = dict(score.metadata)
    metadata.pop(ARRANGEMENT_METADATA_KEY, None)
    return replace(score, metadata=metadata)


def _with_record(score: Score, record: dict[str, Any]) -> Score:
    clean = _clean_score(score)
    record = _json_copy(record, "M33 arrangement")
    record["score_fingerprint"] = _score_fingerprint(clean)
    record["fingerprint"] = _record_fingerprint(record)
    metadata = dict(clean.metadata)
    metadata[ARRANGEMENT_METADATA_KEY] = record
    result = replace(clean, metadata=metadata)
    ArrangementPlan.from_score(result)
    return result


def _initial_clips(score: Score) -> tuple[ArrangementClip, ...]:
    plan = PhrasePlan.from_score(score)
    freeze_records = score.metadata.get("m28_phrase_freezes", {})
    clips = []
    for phrase in plan.phrases:
        frozen_record = freeze_records.get(phrase.phrase_id, {}) if isinstance(freeze_records, dict) else {}
        candidate_id = frozen_record.get("candidate_id") if isinstance(frozen_record, dict) else None
        clips.append(ArrangementClip(
            clip_id="clip-" + secrets.token_hex(8),
            phrase_id=phrase.phrase_id,
            source_phrase_id=phrase.phrase_id,
            start_beats=phrase.start_beats,
            end_beats=phrase.end_beats,
            source_start_beats=phrase.start_beats,
            source_end_beats=phrase.end_beats,
            event_ids=phrase.event_ids,
            source_event_ids=phrase.event_ids,
            frozen=bool(frozen_record),
            label=phrase.function.replace("_", " ").title(),
            candidate_id=candidate_id,
            origin="candidate" if candidate_id else "generated",
        ))
    return tuple(clips)


def create_arrangement(score: Score) -> Score:
    """Create an editable arrangement from the current M28 PhrasePlan.

    A complete pre-arrangement Score snapshot is retained as the explicit
    REVERT TO GENERATION destination. No events are rewritten at creation.
    """
    if not isinstance(score, Score):
        raise TypeError("score must be a Reawarp Score")
    if ARRANGEMENT_METADATA_KEY in score.metadata:
        ArrangementPlan.from_score(score)
        return score
    phrase_plan = PhrasePlan.from_score(score)
    phrase_plan.validate_score(score)
    if not phrase_plan.phrases:
        raise ValueError("define at least one phrase before creating an arrangement")
    base = _score_snapshot(score)
    record = {
        "format": ARRANGEMENT_FORMAT,
        "schema_version": ARRANGEMENT_SCHEMA_VERSION,
        "arrangement_id": "arr-" + secrets.token_hex(8),
        "parent_arrangement_id": None,
        "revision": 0,
        "generation_base_score": base,
        "clips": [item.to_dict() for item in _initial_clips(score)],
        "checklist": {item: False for item in CHECKLIST_ITEMS},
        "prints": [],
        "edit_history": [],
        "redo_history": [],
        "audit_log": [],
    }
    return _with_record(score, record)


def _record_core(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _json_copy(value, f"arrangement {key}")
        for key, value in record.items()
        if key not in {
            "revision", "score_fingerprint", "fingerprint",
            "edit_history", "redo_history", "audit_log",
        }
    }


def _commit_edit(
    original: Score,
    updated: Score,
    *,
    action: str,
    details: Mapping[str, Any],
    record_updates: Mapping[str, Any] | None = None,
) -> Score:
    record = _record_for_score(original)
    clean_after = _clean_score(updated)
    before_record = _record_core(record)
    after_record = copy.deepcopy(before_record)
    after_record.update(_json_copy(dict(record_updates or {}), "arrangement edit"))
    entry = {
        "edit_id": "edit-" + secrets.token_hex(8),
        "actor": "composer",
        "action": str(action),
        "revision": int(record.get("revision", 0)) + 1,
        "details": _json_copy(dict(details), "edit details"),
        "source_score_fingerprint": _score_fingerprint(original),
        "result_score_fingerprint": _score_fingerprint(clean_after),
        "before_score": _score_snapshot(original),
        "after_score": _score_snapshot(clean_after),
        "before_record": before_record,
        "after_record": after_record,
    }
    history = list(record.get("edit_history", []))
    history.append(entry)
    record.update(after_record)
    record["revision"] = entry["revision"]
    record["edit_history"] = history[-MAX_EDIT_HISTORY:]
    record["redo_history"] = []
    audit = list(record.get("audit_log", []))
    audit.append({
        "edit_id": entry["edit_id"], "revision": entry["revision"],
        "action": str(action), "actor": "composer",
        "source_score_fingerprint": entry["source_score_fingerprint"],
        "result_score_fingerprint": entry["result_score_fingerprint"],
        "details": _json_copy(dict(details), "edit audit"),
    })
    record["audit_log"] = audit[-200:]
    return _with_record(clean_after, record)


def _phrase_map(score: Score) -> tuple[PhrasePlan, dict[str, PhraseSpan]]:
    plan = PhrasePlan.from_score(score)
    return plan, {item.phrase_id: item for item in plan.phrases}


def _replace_phrases(score: Score, changes: Mapping[str, PhraseSpan]) -> Score:
    plan, phrases = _phrase_map(score)
    phrases.update(changes)
    updated = PhrasePlan(
        phrases=tuple(phrases.values()), motif_families=plan.motif_families
    )
    return updated.attach_to_score(score)


def _shift_transition_plans(score: Score, phrase_id: str, delta: Fraction) -> Score:
    if not score.metadata.get("m30_transition_plans"):
        return score
    from reawarp.composition.transitions import (
        compile_transition_plans, transition_plans_from_score,
    )
    plans = transition_plans_from_score(score)
    shifted = []
    for plan in plans:
        if phrase_id not in {plan.source_phrase_id, plan.target_phrase_id}:
            continue
        phases = tuple(replace(
            phase, start_beats=phase.start_beats + delta,
            end_beats=phase.end_beats + delta,
        ) for phase in plan.phases)
        shifted.append(replace(plan, phases=phases))
    if not shifted:
        return score
    try:
        return compile_transition_plans(score, shifted)
    except ValueError:
        # Moving a single phrase can temporarily detach a transition from the
        # phrase boundary it was authored for. Keep the original silent cue
        # and let the composer reposition it explicitly in the M33 cue editor.
        return score


def _shift_ending_plans_after(score: Score, boundary: Fraction, delta: Fraction) -> Score:
    if not score.metadata.get("m30_ending_plans"):
        return score
    from reawarp.composition.endings import (
        compile_ending_plans, ending_plans_from_score,
    )
    plans = ending_plans_from_score(score)
    shifted = []
    for plan in plans:
        if plan.start_beats >= boundary:
            shifted.append(replace(
                plan, start_beats=plan.start_beats + delta,
                end_beats=plan.end_beats + delta,
            ))
    return compile_ending_plans(score, shifted) if shifted else score


def move_clip(score: Score, clip_id: str, start_beats: Any) -> Score:
    """Move a phrase placement; preserve its exact duration and all event identity."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    target = _beat(start_beats, "new clip start")
    delta = target - clip.start_beats
    if delta == 0:
        return score
    new_start, new_end = target, target + clip.duration_beats
    by_id = {event.event_id: event for event in score.events}
    events = tuple(
        replace(by_id[event_id], onset_beats=by_id[event_id].onset_beats + delta)
        if event_id in set(clip.event_ids) else event
        for event in score.events
    )
    phrase = _phrase_map(score)[1][clip.phrase_id]
    shifted_phrase = replace(
        phrase,
        start_beats=new_start,
        end_beats=new_end,
        boundaries=tuple(replace(item, at_beats=item.at_beats + delta) for item in phrase.boundaries),
    )
    updated = _replace_phrases(replace(score, events=events), {clip.phrase_id: shifted_phrase})
    updated = _shift_transition_plans(updated, clip.phrase_id, delta)
    last_end = max((item.end_beats for item in clips), default=clip.end_beats)
    if clip.end_beats == last_end:
        updated = _shift_ending_plans_after(updated, clip.end_beats, delta)
    moved = replace(
        clip, start_beats=new_start, end_beats=new_end,
        revision=clip.revision + 1, origin="manual",
    )
    clips = [moved if item.clip_id == clip_id else item for item in clips]
    return _commit_edit(
        score, updated, action="move_clip",
        details={"clip_id": clip_id, "from": str(clip.start_beats), "to": str(target)},
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def duplicate_clip(score: Score, clip_id: str, start_beats: Any | None = None) -> Score:
    """Duplicate phrase events with new identities and an explicit source link."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    source = next((item for item in clips if item.clip_id == clip_id), None)
    if source is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    target_start = source.end_beats if start_beats is None else _beat(start_beats, "duplicate start")
    delta = target_start - source.start_beats
    id_map = {event_id: f"m33-{secrets.token_hex(12)}" for event_id in source.event_ids}
    by_id = {event.event_id: event for event in score.events}
    clones = []
    for event_id in source.event_ids:
        event = by_id[event_id]
        clones.append(replace(
            event,
            event_id=id_map[event_id],
            onset_beats=event.onset_beats + delta,
        ))
    new_phrase_id = f"{source.phrase_id}-copy-{secrets.token_hex(4)}"
    source_phrase = _phrase_map(score)[1][source.phrase_id]
    new_start = target_start
    new_end = target_start + source.duration_beats
    duplicate_phrase = replace(
        source_phrase,
        phrase_id=new_phrase_id,
        start_beats=new_start,
        end_beats=new_end,
        event_ids=tuple(id_map[item] for item in source.event_ids),
        boundaries=tuple(replace(item, at_beats=item.at_beats + delta) for item in source_phrase.boundaries),
        notes=(source_phrase.notes + " · duplicated in M33").strip(" ·"),
    )
    updated = replace(score, events=tuple((*score.events, *clones)))
    updated = _replace_phrases(updated, {new_phrase_id: duplicate_phrase})
    duplicate = ArrangementClip(
        clip_id="clip-" + secrets.token_hex(8),
        phrase_id=new_phrase_id,
        source_phrase_id=source.source_phrase_id,
        start_beats=new_start,
        end_beats=new_end,
        source_start_beats=source.source_start_beats,
        source_end_beats=source.source_end_beats,
        event_ids=tuple(id_map[item] for item in source.event_ids),
        source_event_ids=source.source_event_ids,
        muted=source.muted,
        frozen=source.frozen,
        label=(source.label + " · copy").strip(" ·"),
        candidate_id=source.candidate_id,
        parent_clip_id=source.clip_id,
        role_map=source.role_map,
        original_velocities={
            id_map[key]: value for key, value in source.original_velocities.items()
            if key in id_map
        },
        origin="manual",
    )
    clips.append(duplicate)
    return _commit_edit(
        score, updated, action="duplicate_clip",
        details={
            "source_clip_id": source.clip_id, "new_clip_id": duplicate.clip_id,
            "new_phrase_id": new_phrase_id, "start_beats": str(new_start),
        },
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def trim_clip(score: Score, clip_id: str, start_beats: Any, end_beats: Any) -> Score:
    """Trim a phrase to a rational-beat sub-span, cropping notes at exact edges."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if clip.frozen:
        raise ValueError("frozen arrangement material cannot be trimmed; branch or duplicate it")
    start, end = _beat(start_beats, "trim start"), _beat(end_beats, "trim end")
    if start < clip.start_beats or end > clip.end_beats or end <= start:
        raise ValueError("trim bounds must be a positive sub-span of the selected clip")
    by_id = {event.event_id: event for event in score.events}
    kept: list[MusicalEvent] = []
    removed = set()
    for event_id in clip.event_ids:
        event = by_id[event_id]
        if event.duration_beats == 0:
            if start <= event.onset_beats < end:
                kept.append(event)
            else:
                removed.add(event_id)
            continue
        clipped_start = max(event.onset_beats, start)
        clipped_end = min(event.end_beats, end)
        if clipped_end <= clipped_start:
            removed.add(event_id)
            continue
        kept.append(replace(
            event, onset_beats=clipped_start, duration_beats=clipped_end - clipped_start
        ))
    events = tuple(
        event for event in score.events
        if event.event_id not in removed and event.event_id not in set(clip.event_ids)
    ) + tuple(kept)
    phrase = _phrase_map(score)[1][clip.phrase_id]
    updated_phrase = replace(
        phrase, start_beats=start, end_beats=end,
        event_ids=tuple(event.event_id for event in kept),
        boundaries=tuple(item for item in phrase.boundaries if start <= item.at_beats <= end),
    )
    updated = _replace_phrases(replace(score, events=events), {clip.phrase_id: updated_phrase})
    source_start = clip.source_start_beats + (start - clip.start_beats)
    source_end = clip.source_end_beats - (clip.end_beats - end)
    updated_clip = replace(
        clip, start_beats=start, end_beats=end,
        source_start_beats=source_start, source_end_beats=source_end,
        event_ids=tuple(event.event_id for event in kept),
        source_event_ids=tuple(
            event_id for event_id in clip.source_event_ids if event_id not in removed
        ),
        original_velocities={
            event_id: velocity for event_id, velocity in clip.original_velocities.items()
            if event_id not in removed
        },
        revision=clip.revision + 1, origin="manual",
    )
    clips = [updated_clip if item.clip_id == clip_id else item for item in clips]
    return _commit_edit(
        score, updated, action="trim_clip",
        details={"clip_id": clip_id, "start_beats": str(start), "end_beats": str(end),
                 "removed_event_ids": sorted(removed)},
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def reorder_clip(score: Score, clip_id: str, target_index: int) -> Score:
    """Move a clip to a new timeline order, compacting the phrase sequence without overlaps."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    ordered = sorted(clips, key=lambda item: (item.start_beats, item.end_beats, item.clip_id))
    current = next((i for i, item in enumerate(ordered) if item.clip_id == clip_id), None)
    if current is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if isinstance(target_index, bool) or not isinstance(target_index, int):
        raise ValueError("target arrangement index must be an integer")
    if not 0 <= target_index < len(ordered):
        raise ValueError("target arrangement index falls outside the clip sequence")
    selected = ordered.pop(current)
    ordered.insert(target_index, selected)
    from reawarp.composition.endings import ending_plans_from_score
    original_endings = ending_plans_from_score(score)
    original_end = max(item.end_beats for item in clips)
    cursor = min(item.start_beats for item in clips)
    result = score
    for item in ordered:
        if item.start_beats != cursor:
            result = move_clip(result, item.clip_id, cursor)
        cursor += item.duration_beats
    if result is score:
        return score
    # Collapse the internal per-move records into one reversible arrangement edit.
    # A cue's ending offset is relative to the end of the phrase sequence.
    # Keep that offset after the reordering pass, rather than inheriting the
    # temporary positions used while clips are moved one at a time.
    new_end = cursor
    current_endings = {
        item.ending_id: item for item in ending_plans_from_score(result)
    }
    for ending in original_endings:
        old_offset = ending.start_beats - original_end
        desired_start = new_end + old_offset
        current_ending = current_endings.get(ending.ending_id)
        if current_ending is not None and current_ending.start_beats != desired_start:
            result = move_ending(result, ending.ending_id, desired_start)
    latest = _record_for_score(result)
    original_record = record
    before_score = _score_snapshot(score)
    after_score = _score_snapshot(_clean_score(result))
    combined_entry = {
        "edit_id": "edit-" + secrets.token_hex(8), "actor": "composer",
        "action": "reorder_clip", "revision": int(original_record["revision"]) + 1,
        "details": {"clip_id": clip_id, "from_index": current, "to_index": target_index},
        "source_score_fingerprint": _score_fingerprint(score),
        "result_score_fingerprint": _score_fingerprint(_clean_score(result)),
        "before_score": before_score, "after_score": after_score,
        "before_record": _record_core(original_record),
        "after_record": _record_core(latest),
    }
    latest["revision"] = combined_entry["revision"]
    latest["edit_history"] = (
        list(original_record.get("edit_history", [])) + [combined_entry]
    )[-MAX_EDIT_HISTORY:]
    latest["redo_history"] = []
    latest["audit_log"] = (
        list(original_record.get("audit_log", [])) + [{
            "edit_id": combined_entry["edit_id"], "revision": combined_entry["revision"],
            "action": "reorder_clip", "actor": "composer",
            "source_score_fingerprint": combined_entry["source_score_fingerprint"],
            "result_score_fingerprint": combined_entry["result_score_fingerprint"],
            "details": combined_entry["details"],
        }]
    )[-200:]
    return _with_record(_clean_score(result), latest)


def set_clip_muted(score: Score, clip_id: str, muted: bool) -> Score:
    """Mute/unmute an arrangement clip without deleting or regenerating its events."""
    if not isinstance(muted, bool):
        raise ValueError("muted must be boolean")
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if clip.muted == muted:
        return score
    snapshots = dict(clip.original_velocities)
    events = []
    for event in score.events:
        if event.event_id not in set(clip.event_ids) or event.kind not in {"note", "hit"}:
            events.append(event)
            continue
        if muted:
            snapshots[event.event_id] = event.velocity
            events.append(replace(event, velocity=0.0))
        else:
            events.append(replace(event, velocity=snapshots.get(event.event_id, event.velocity)))
    updated = replace(score, events=tuple(events))
    new_clip = replace(
        clip, muted=muted, original_velocities=snapshots if muted else {},
        revision=clip.revision + 1, origin="manual",
    )
    clips = [new_clip if item.clip_id == clip_id else item for item in clips]
    return _commit_edit(
        score, updated, action="mute_clip" if muted else "unmute_clip",
        details={"clip_id": clip_id, "muted": muted},
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def exchange_clip_layer(score: Score, clip_id: str, source_role: str, target_role: str) -> Score:
    """Exchange a phrase layer's Score voice identity without changing source samples."""
    source_role, target_role = str(source_role).strip(), str(target_role).strip()
    if not source_role or not target_role or source_role == target_role:
        raise ValueError("layer exchange requires two different non-empty voice IDs")
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if clip.frozen:
        raise ValueError("frozen arrangement material cannot exchange layers")
    selected = set(clip.event_ids)
    changed = False
    events = []
    for event in score.events:
        if event.event_id in selected and event.voice_id == source_role:
            events.append(replace(event, voice_id=target_role))
            changed = True
        else:
            events.append(event)
    if not changed:
        raise ValueError(f"clip {clip_id} contains no events in voice {source_role!r}")
    role_map = dict(clip.role_map)
    role_map[source_role] = target_role
    updated = replace(score, events=tuple(events))
    phrase = _phrase_map(score)[1][clip.phrase_id]
    phrase_events = [event for event in updated.events if event.event_id in selected]
    roles = list(phrase.roles)
    if source_role not in {event.voice_id for event in phrase_events}:
        roles = [item for item in roles if item != source_role]
    if target_role not in roles:
        roles.append(target_role)
    updated = _replace_phrases(updated, {
        clip.phrase_id: replace(phrase, roles=tuple(roles))
    })
    new_clip = replace(
        clip, role_map=role_map, revision=clip.revision + 1, origin="manual"
    )
    clips = [new_clip if item.clip_id == clip_id else item for item in clips]
    return _commit_edit(
        score, updated, action="exchange_layer",
        details={"clip_id": clip_id, "source_role": source_role, "target_role": target_role},
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def replace_clip_with_candidate(score: Score, clip_id: str, candidate: Any) -> Score:
    """Replace a phrase placement with a selected M28 candidate and retain its lineage."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if clip.frozen:
        raise ValueError("frozen arrangement material cannot be replaced; branch or duplicate it")
    if str(getattr(candidate, "phrase_id", "")) != clip.source_phrase_id:
        raise ValueError("candidate belongs to a different source phrase")
    if tuple(getattr(candidate, "source_event_ids", ())) != clip.source_event_ids:
        raise ValueError(
            "candidate source events no longer match this arrangement clip; regenerate the candidate"
        )
    candidate_score = getattr(candidate, "candidate_score", None)
    if not isinstance(candidate_score, Score):
        raise TypeError("candidate must contain a canonical candidate_score")
    candidate_plan = PhrasePlan.from_score(candidate_score)
    candidate_phrase = next(
        (item for item in candidate_plan.phrases if item.phrase_id == candidate.phrase_id), None
    )
    if candidate_phrase is None:
        raise ValueError("candidate Score is missing its phrase definition")
    by_id = {event.event_id: event for event in candidate_score.events}
    source_events = [by_id[item] for item in candidate.target_event_ids if item in by_id]
    if len(source_events) != len(candidate.target_event_ids):
        raise ValueError("candidate references missing source events")
    duration = candidate_phrase.duration_beats
    shift = clip.start_beats - candidate_phrase.start_beats
    id_map = {event.event_id: f"m33-{secrets.token_hex(12)}" for event in source_events}
    replacements = tuple(replace(
        event, event_id=id_map[event.event_id], onset_beats=event.onset_beats + shift
    ) for event in source_events)
    old_ids = set(clip.event_ids)
    events = tuple(event for event in score.events if event.event_id not in old_ids) + replacements
    new_end = clip.start_beats + duration
    new_phrase = replace(
        candidate_phrase,
        phrase_id=clip.phrase_id,
        start_beats=clip.start_beats,
        end_beats=new_end,
        event_ids=tuple(id_map[item.event_id] for item in source_events),
        boundaries=tuple(replace(
            item, at_beats=item.at_beats + shift
        ) for item in candidate_phrase.boundaries),
    )
    updated = _replace_phrases(replace(score, events=events), {clip.phrase_id: new_phrase})
    new_clip = replace(
        clip,
        end_beats=new_end,
        source_start_beats=candidate_phrase.start_beats,
        source_end_beats=candidate_phrase.end_beats,
        event_ids=tuple(id_map[item.event_id] for item in source_events),
        source_event_ids=tuple(getattr(candidate, "source_event_ids", clip.source_event_ids)),
        muted=False,
        frozen=False,
        candidate_id=str(candidate.candidate_id),
        original_velocities={},
        origin="candidate",
        revision=clip.revision + 1,
    )
    clips = [new_clip if item.clip_id == clip_id else item for item in clips]
    return _commit_edit(
        score, updated, action="replace_clip",
        details={
            "clip_id": clip_id, "candidate_id": str(candidate.candidate_id),
            "operation": str(candidate.operation),
            "seed_name": str(candidate.seed_name), "seed": int(candidate.seed),
            "source_event_ids": list(candidate.source_event_ids),
            "target_event_ids": list(candidate.target_event_ids),
            "generator_version": str(candidate.generator_version),
            "base_score_fingerprint": str(candidate.base_score_fingerprint),
            "base_phrase_fingerprint": str(candidate.base_phrase_fingerprint),
            "transformation": candidate.transformation.to_dict(),
            "config_delta": dict(candidate.config_delta),
            "context_event_ids": dict(candidate.context_event_ids),
            "replaced_event_ids": sorted(old_ids),
        },
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def freeze_clip(score: Score, clip_id: str) -> Score:
    """Freeze the selected arrangement material against content replacement."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if clip.frozen:
        return score
    frozen = replace(clip, frozen=True, revision=clip.revision + 1)
    clips = [frozen if item.clip_id == clip_id else item for item in clips]
    return _commit_edit(
        score, score, action="freeze_clip",
        details={"clip_id": clip_id, "event_ids": list(clip.event_ids)},
        record_updates={"clips": [item.to_dict() for item in clips]},
    )


def move_transition(score: Score, transition_id: str, start_beats: Any) -> Score:
    """Move an M30 transition cue while preserving its three phase durations."""
    from reawarp.composition.transitions import (
        compile_transition_plans, transition_plans_from_score,
    )
    record = _record_for_score(score)
    plans = transition_plans_from_score(score)
    target = next((item for item in plans if item.transition_id == transition_id), None)
    if target is None:
        raise ValueError(f"unknown transition cue: {transition_id}")
    start = _beat(start_beats, "transition start")
    delta = start - target.start_beats
    if delta == 0:
        return score
    shifted = replace(target, phases=tuple(replace(
        phase, start_beats=phase.start_beats + delta,
        end_beats=phase.end_beats + delta,
    ) for phase in target.phases))
    updated = compile_transition_plans(score, (shifted,))
    return _commit_edit(
        score, updated, action="move_transition",
        details={"transition_id": transition_id, "from": str(target.start_beats), "to": str(start)},
    )


def move_ending(score: Score, ending_id: str, start_beats: Any) -> Score:
    """Move an M30 ending cue while retaining its strategy and duration."""
    from reawarp.composition.endings import compile_ending_plans, ending_plans_from_score
    record = _record_for_score(score)
    plans = ending_plans_from_score(score)
    target = next((item for item in plans if item.ending_id == ending_id), None)
    if target is None:
        raise ValueError(f"unknown ending cue: {ending_id}")
    start = _beat(start_beats, "ending start")
    delta = start - target.start_beats
    if delta == 0:
        return score
    shifted = replace(
        target, start_beats=start, end_beats=target.end_beats + delta
    )
    updated = compile_ending_plans(score, (shifted,))
    return _commit_edit(
        score, updated, action="move_ending",
        details={"ending_id": ending_id, "from": str(target.start_beats), "to": str(start)},
    )


def relink_transition(
    score: Score, transition_id: str, source_phrase_id: str, target_phrase_id: str,
) -> Score:
    """Relink an M30 cue after manual reordering, preserving its phase durations.

    The preparation is anchored to the outgoing phrase end and the arrival must
    extend into the new target phrase. If the existing phase lengths cannot fit,
    the composer must shorten/re-author the cue rather than silently distort it.
    """
    _record_for_score(score)
    from reawarp.composition.transitions import (
        TransitionPhase, compile_transition_plans, transition_plans_from_score,
    )

    plans = transition_plans_from_score(score)
    original = next((item for item in plans if item.transition_id == transition_id), None)
    if original is None:
        raise ValueError(f"unknown transition cue: {transition_id}")
    phrase_plan = PhrasePlan.from_score(score)
    phrases = {item.phrase_id: item for item in phrase_plan.phrases}
    source = phrases.get(str(source_phrase_id))
    target = phrases.get(str(target_phrase_id))
    if source is None or target is None:
        raise ValueError("transition relink requires two existing Score phrases")
    if source.phrase_id == target.phrase_id or source.start_beats >= target.start_beats:
        raise ValueError("transition source must precede a different target phrase")
    preparation_length = original.phases[0].duration_beats
    change_length = original.phases[1].duration_beats
    arrival_length = original.phases[2].duration_beats
    preparation_start = source.end_beats - preparation_length
    change_start = source.end_beats
    change_end = change_start + change_length
    arrival_end = change_end + arrival_length
    if preparation_start < source.start_beats:
        raise ValueError("existing preparation phase is longer than the new source phrase")
    if not target.start_beats < arrival_end <= target.end_beats:
        raise ValueError(
            "existing change/arrival durations do not reach and fit inside the new target phrase"
        )
    updated_plan = replace(
        original,
        source_phrase_id=source.phrase_id,
        target_phrase_id=target.phrase_id,
        phases=(
            TransitionPhase(
                "preparation", preparation_start, change_start,
                original.phases[0].intent,
            ),
            TransitionPhase(
                "change", change_start, change_end, original.phases[1].intent,
            ),
            TransitionPhase(
                "arrival", change_end, arrival_end, original.phases[2].intent,
            ),
        ),
        rationale=(original.rationale + " · relinked in M33").strip(" ·"),
    )
    updated = compile_transition_plans(score, (updated_plan,))
    return _commit_edit(
        score, updated, action="relink_transition",
        details={
            "transition_id": transition_id,
            "source_phrase_id": source.phrase_id,
            "target_phrase_id": target.phrase_id,
            "start_beats": str(preparation_start),
        },
    )


def set_checklist_item(score: Score, item: str, checked: bool) -> Score:
    if item not in CHECKLIST_ITEMS or not isinstance(checked, bool):
        raise ValueError("unknown checklist item or non-boolean completion state")
    record = _record_for_score(score)
    checklist = dict(record.get("checklist", {}))
    if checklist.get(item, False) == checked:
        return score
    checklist[item] = checked
    return _commit_edit(
        score, score, action="checklist",
        details={"item": item, "checked": checked},
        record_updates={"checklist": checklist},
    )


def record_print(
    score: Score, clip_id: str, *, path: str | Path, sha256: str,
    sample_rate: int, frame_count: int, renderer: str = "ScoreRenderer",
) -> Score:
    """Record a verified, external printed WAV object with source and renderer lineage."""
    record = _record_for_score(score)
    clips = [ArrangementClip.from_dict(item) for item in record["clips"]]
    clip = next((item for item in clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".wav":
        raise ValueError("printed WAV file does not exist or does not use a .wav extension")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != str(sha256).lower():
        raise ValueError("printed WAV hash does not match the supplied digest")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("printed sample rate must be a positive integer")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise ValueError("printed frame count must be a positive integer")
    from reawarp.export.wav import read_wav
    audio, actual_sample_rate = read_wav(source)
    if actual_sample_rate != sample_rate or len(audio) != frame_count:
        raise ValueError("printed WAV header does not match the supplied sample rate/frame count")
    prints = list(record.get("prints", []))
    print_record = {
        "print_id": "print-" + secrets.token_hex(8),
        "clip_id": clip.clip_id,
        "phrase_id": clip.phrase_id,
        "candidate_id": clip.candidate_id,
        "source_event_ids": list(clip.source_event_ids),
        "event_ids": list(clip.event_ids),
        "path": str(source),
        "file_name": source.name,
        "sha256": digest,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": frame_count / sample_rate,
        "renderer": str(renderer),
        "arrangement_revision": int(record.get("revision", 0)),
        "score_fingerprint": str(record.get("score_fingerprint", "")),
    }
    prints.append(print_record)
    return _commit_edit(
        score, score, action="print_clip",
        details=print_record, record_updates={"prints": prints},
    )


def branch_arrangement(score: Score) -> Score:
    """Create a new editable arrangement branch without altering its source events."""
    record = _record_for_score(score)
    old_id = str(record["arrangement_id"])
    clips = [
        replace(ArrangementClip.from_dict(item), frozen=False).to_dict()
        for item in record.get("clips", [])
    ]
    return _commit_edit(
        score, score, action="branch_arrangement",
        details={"parent_arrangement_id": old_id},
        record_updates={
            "arrangement_id": "arr-" + secrets.token_hex(8),
            "parent_arrangement_id": old_id,
            "clips": clips,
            "prints": [],
        },
    )


def refresh_arrangement_fingerprint(score: Score) -> Score:
    """Refresh the M33 guard after an intentional external Score/render update.

    This is not a musical edit: it acknowledges a Score revision made through
    another Reawarp workspace while retaining the current arrangement history.
    """
    raw = score.metadata.get(ARRANGEMENT_METADATA_KEY)
    if not isinstance(raw, dict):
        return score
    record = _json_copy(raw, "M33 arrangement")
    record["score_fingerprint"] = _score_fingerprint(_clean_score(score))
    record["fingerprint"] = _record_fingerprint(record)
    clean = _clean_score(score)
    metadata = dict(clean.metadata)
    metadata[ARRANGEMENT_METADATA_KEY] = record
    result = replace(clean, metadata=metadata)
    ArrangementPlan.from_score(result)
    return result


def revert_to_generation(score: Score) -> Score:
    """Return to the immutable pre-arrangement Score snapshot as a reversible edit."""
    record = _record_for_score(score)
    base_data = record.get("generation_base_score")
    if not isinstance(base_data, dict):
        raise ValueError("arrangement is missing its generation base snapshot")
    base = Score.from_dict(_json_copy(base_data, "generation base Score"))
    clips = _initial_clips(base)
    return _commit_edit(
        score, base, action="revert_to_generation",
        details={"restored_generation_base": True, "clip_count": len(clips)},
        record_updates={
            "clips": [item.to_dict() for item in clips],
            "checklist": {item: False for item in CHECKLIST_ITEMS},
            "prints": [],
        },
    )


def undo_arrangement_edit(score: Score) -> Score:
    record = _record_for_score(score)
    history = list(record.get("edit_history", []))
    if not history:
        raise ValueError("there is no arrangement edit to undo")
    entry = history.pop()
    restored = Score.from_dict(entry["before_score"])
    updated = copy.deepcopy(record)
    updated.update(_json_copy(entry["before_record"], "undo arrangement snapshot"))
    updated["revision"] = int(record.get("revision", 0)) + 1
    updated["edit_history"] = history
    updated["redo_history"] = list(record.get("redo_history", [])) + [entry]
    audit = list(record.get("audit_log", []))
    audit.append({
        "edit_id": "undo-" + secrets.token_hex(8), "revision": updated["revision"],
        "action": "undo", "actor": "composer", "details": {"undid_edit_id": entry["edit_id"]},
    })
    updated["audit_log"] = audit[-200:]
    return _with_record(restored, updated)


def redo_arrangement_edit(score: Score) -> Score:
    record = _record_for_score(score)
    redo = list(record.get("redo_history", []))
    if not redo:
        raise ValueError("there is no arrangement edit to redo")
    entry = redo.pop()
    restored = Score.from_dict(entry["after_score"])
    updated = copy.deepcopy(record)
    updated.update(_json_copy(entry["after_record"], "redo arrangement snapshot"))
    updated["revision"] = int(record.get("revision", 0)) + 1
    updated["edit_history"] = list(record.get("edit_history", [])) + [entry]
    updated["redo_history"] = redo
    audit = list(record.get("audit_log", []))
    audit.append({
        "edit_id": "redo-" + secrets.token_hex(8), "revision": updated["revision"],
        "action": "redo", "actor": "composer", "details": {"redid_edit_id": entry["edit_id"]},
    })
    updated["audit_log"] = audit[-200:]
    return _with_record(restored, updated)


def clip_score_for_render(score: Score, clip_id: str) -> Score:
    """Return an isolated Score snapshot suitable for offline print-to-WAV rendering."""
    plan = ArrangementPlan.from_score(score)
    clip = next((item for item in plan.clips if item.clip_id == clip_id), None)
    if clip is None:
        raise ValueError(f"unknown arrangement clip: {clip_id}")
    if clip.muted:
        raise ValueError("muted clips cannot be printed")
    selected = set(clip.event_ids)
    events = tuple(event for event in score.events if event.event_id in selected)
    if not events:
        raise ValueError("selected arrangement clip has no printable Score events")
    voices = sorted({event.voice_id for event in events if event.kind not in {"control", "marker"}})
    metadata = dict(score.metadata)
    for key in (
        ARRANGEMENT_METADATA_KEY, "m28_phrase_plan", "m28_phrase_plan_fingerprint",
        "m28_phrase_freezes", "m30_transition_plans", "m30_transition_fingerprint",
        "m30_ending_plans", "m30_ending_fingerprint", "m30_section_memory",
        "m30_section_memory_fingerprint", "m29_attention_gestures",
        "m29_attention_gesture_fingerprint", "m29_attention_reviews",
    ):
        metadata.pop(key, None)
    metadata["render_stems"] = voices
    return replace(
        score, events=events, metadata=metadata,
        bass_plan=None, sonority_plan=None, orchestration_plan=None,
        sonorities=(),
    )


def arrangement_timeline(score: Score) -> list[dict[str, Any]]:
    """Return phrase clips and M30 cue objects in exact timeline order."""
    plan = ArrangementPlan.from_score(score)
    phrase_by_id = {
        item.phrase_id: item for item in PhrasePlan.from_score(score).phrases
    }
    items = [{
        "item_id": clip.clip_id, "kind": "phrase", "label": clip.label or clip.phrase_id,
        "phrase_id": clip.phrase_id,
        "section_id": phrase_by_id[clip.phrase_id].parent_section_id,
        "start_beats": str(clip.start_beats),
        "end_beats": str(clip.end_beats), "muted": clip.muted, "frozen": clip.frozen,
    } for clip in plan.clips]
    from reawarp.composition.endings import ending_plans_from_score
    from reawarp.composition.transitions import transition_plans_from_score
    for transition in transition_plans_from_score(score):
        items.append({
            "item_id": transition.transition_id, "kind": "transition",
            "label": transition.transition_type.replace("_", " ").title(),
            "start_beats": str(transition.start_beats), "end_beats": str(transition.end_beats),
            "muted": False, "frozen": True,
        })
    for ending in ending_plans_from_score(score):
        items.append({
            "item_id": ending.ending_id, "kind": "ending",
            "label": ending.strategy.replace("_", " ").title(),
            "start_beats": str(ending.start_beats), "end_beats": str(ending.end_beats),
            "muted": False, "frozen": True,
        })
    return sorted(items, key=lambda item: (
        Fraction(item["start_beats"]), Fraction(item["end_beats"]),
        item["kind"], item["item_id"],
    ))


def arrangement_snapshot(score: Score) -> dict[str, Any]:
    """Portable M33 snapshot for project/delivery exports."""
    plan = ArrangementPlan.from_score(score)
    record = _record_for_score(score)
    return {
        "format": ARRANGEMENT_FORMAT,
        "schema_version": ARRANGEMENT_SCHEMA_VERSION,
        "arrangement": record,
        "timeline": arrangement_timeline(score),
        "clips": [item.to_dict() for item in plan.clips],
        "all_finishing_checks_complete": all(plan.checklist.values()),
        "open_finishing_checks": [key for key, value in plan.checklist.items() if not value],
        "edit_count": len(record.get("edit_history", [])),
        "print_count": len(record.get("prints", [])),
    }


def copy_print_assets(record: Mapping[str, Any], directory: str | Path) -> list[dict[str, Any]]:
    """Copy verified print-to-track assets into an export folder; missing files stay visible."""
    import shutil

    destination = Path(directory)
    exported: list[dict[str, Any]] = []
    for item in record.get("prints", []):
        if not isinstance(item, dict):
            continue
        source = Path(str(item.get("path", ""))).expanduser()
        result = {key: value for key, value in item.items() if key != "path"}
        if not source.is_file():
            result["export_status"] = "missing"
            exported.append(result)
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != item.get("sha256"):
            result["export_status"] = "changed"
            exported.append(result)
            continue
        safe_name = "".join(
            char if char.isalnum() or char in "._-" else "_"
            for char in str(item.get("file_name") or source.name)
        )
        if not safe_name or safe_name in {".", ".."}:
            safe_name = f"{item.get('print_id', 'print')}.wav"
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / safe_name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            target = destination / f"{item.get('print_id', 'print')}-{safe_name}"
        shutil.copy2(source, target)
        result["export_path"] = target.as_posix()
        result["export_status"] = "copied"
        exported.append(result)
    return exported


__all__ = [
    "ARRANGEMENT_FORMAT", "ARRANGEMENT_METADATA_KEY", "ARRANGEMENT_SCHEMA_VERSION",
    "CHECKLIST_ITEMS", "ArrangementClip", "ArrangementPlan", "arrangement_snapshot",
    "arrangement_timeline", "branch_arrangement", "clip_score_for_render",
    "copy_print_assets", "create_arrangement", "duplicate_clip", "exchange_clip_layer",
    "freeze_clip", "move_clip", "move_ending", "move_transition", "record_print",
    "redo_arrangement_edit", "reorder_clip", "replace_clip_with_candidate",
    "refresh_arrangement_fingerprint", "relink_transition", "revert_to_generation", "set_checklist_item", "set_clip_muted", "trim_clip",
    "undo_arrangement_edit",
]
