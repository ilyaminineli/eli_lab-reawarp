"""M32 critical-listening sessions, reversible audition transforms and diagnostics.

All audition operations return disposable buffers or Score copies. They never
mutate production stems, generation settings, or deterministic render state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from reawarp.core.project import ReawarpProject
from reawarp.fx_routing import measure_signal

LISTENING_SESSION_FORMAT = "eli_lab_reawarp_critical_listening_session"
LISTENING_SESSION_SCHEMA_VERSION = 1
ANALYSIS_WINDOW_FRAMES = 4096
ANALYSIS_HOP_FRAMES = 2048
SILENCE_FLOOR_DBFS = -60.0
REPORT_PROMPTS = {
    "identity": "What remains recognisable? Which anchor, material or sound-family identity is carrying the piece?",
    "continuity": "Does the temporal flow feel connected, interrupted or deliberately discontinuous?",
    "contrast": "Are foreground, background, density and section contrasts legible?",
    "legibility": "Can the important events and relationships be followed at normal and reduced playback levels?",
    "motif_development": "Does the motif remain identifiable while its role or material changes?",
    "orchestration": "Are register, role, overlap, masking and negative space balanced?",
    "pacing": "Does the music have room to establish, depart, arrive and leave?",
    "surprise": "Which changes are genuinely surprising, and which feel predictable or arbitrary?",
    "emotional_coherence": "Does the sequence of gestures support a coherent emotional trajectory?",
    "technical_integrity": "Are clipping, tails, silence, phase, mono translation and spectral conflicts acceptable?",
}


def _json_copy(value: Any, field_name: str) -> Any:
    try:
        return json.loads(json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False
        ))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite JSON-compatible data") from exc


def _audio_copy(value: Any, name: str) -> np.ndarray:
    audio = np.asarray(value, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or audio.shape[1] not in {1, 2}:
        raise ValueError(f"{name} must be mono or stereo audio")
    if not np.isfinite(audio).all():
        raise ValueError(f"{name} must contain only finite samples")
    return np.ascontiguousarray(audio.copy())


def audio_fingerprint(audio: Any) -> str:
    value = _audio_copy(audio, "audio")
    digest = hashlib.sha256()
    digest.update(str(value.shape).encode("ascii"))
    digest.update(value.astype("<f4", copy=False).tobytes())
    return digest.hexdigest()


def _stem_for_role(role: str) -> str:
    return {"hat": "hats", "break": "synthetic_break"}.get(str(role), str(role))


def _project_revision(project: ReawarpProject) -> str:
    value = project.metadata.get("project_revision", project.metadata.get("revision", 0))
    return str(value)


@dataclass(frozen=True, slots=True)
class AuditionTransform:
    """Audition-only transform provenance; production audio is never referenced mutably."""

    transform_id: str
    operation: str
    project_fingerprint: str
    candidate_id: str | None
    parameters: Mapping[str, Any]
    before_audio_sha256: str
    after_audio_sha256: str
    sample_rate: int
    decision: str = "unreviewed"
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in ("transform_id", "operation", "project_fingerprint"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.schema_version != 1:
            raise ValueError("unsupported audition transform schema")
        if isinstance(self.sample_rate, bool) or int(self.sample_rate) <= 0:
            raise ValueError("audition sample_rate must be positive")
        if self.decision not in {"unreviewed", "kept_for_review", "restored", "discarded"}:
            raise ValueError("invalid audition transform decision")
        for name in ("before_audio_sha256", "after_audio_sha256"):
            value = str(getattr(self, name)).casefold()
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a SHA-256 digest")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "sample_rate", int(self.sample_rate))
        object.__setattr__(self, "parameters", _json_copy(dict(self.parameters), "transform parameters"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "transform_id": self.transform_id,
            "operation": self.operation,
            "project_fingerprint": self.project_fingerprint,
            "candidate_id": self.candidate_id,
            "parameters": dict(self.parameters),
            "before_audio_sha256": self.before_audio_sha256,
            "after_audio_sha256": self.after_audio_sha256,
            "sample_rate": self.sample_rate,
            "decision": self.decision,
        }


@dataclass(frozen=True, slots=True)
class AuditionResult:
    label: str
    audio: np.ndarray
    sample_rate: int
    transform: AuditionTransform
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.label).strip():
            raise ValueError("audition label cannot be empty")
        if self.sample_rate <= 0:
            raise ValueError("audition sample_rate must be positive")
        value = _audio_copy(self.audio, "audition result")
        value.setflags(write=False)
        object.__setattr__(self, "audio", value)
        object.__setattr__(self, "diagnostics", _json_copy(dict(self.diagnostics), "audition diagnostics"))


class ListeningEditHistory:
    """Small undo/redo history for disposable audition buffers."""

    def __init__(self, base_audio: Any, *, sample_rate: int) -> None:
        if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = int(sample_rate)
        self._snapshots: list[np.ndarray] = [_audio_copy(base_audio, "history base audio")]
        self._records: list[dict[str, Any]] = []
        self._index = 0

    @property
    def current(self) -> np.ndarray:
        return self._snapshots[self._index].copy()

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._snapshots) - 1

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._records))

    def push(self, audio: Any, transform: AuditionTransform) -> None:
        value = _audio_copy(audio, "history transform")
        if value.shape != self._snapshots[0].shape:
            raise ValueError("audition history transforms must preserve frame/channel shape")
        self._records = self._records[:self._index]
        self._snapshots = self._snapshots[:self._index + 1]
        self._snapshots.append(value)
        self._records.append({"transform": transform.to_dict(), "decision": "unreviewed"})
        self._index += 1

    def undo(self) -> np.ndarray:
        if not self.can_undo:
            raise IndexError("no audition transform to restore")
        self._records[self._index - 1]["decision"] = "restored"
        self._index -= 1
        return self.current

    def redo(self) -> np.ndarray:
        if not self.can_redo:
            raise IndexError("no audition transform to redo")
        self._index += 1
        return self.current

    def keep_current(self) -> dict[str, Any]:
        if self._index == 0:
            raise ValueError("the unmodified audition has no transform to keep")
        self._records[self._index - 1]["decision"] = "kept_for_review"
        return copy.deepcopy(self._records[self._index - 1])


def new_listening_session(
    project: ReawarpProject,
    *,
    candidate_ids: Sequence[str] = (),
    analysis_enabled: bool = True,
    playback_level_dbfs: float = -18.0,
) -> dict[str, Any]:
    from reawarp.variations import project_fingerprint
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    level = float(playback_level_dbfs)
    if not math.isfinite(level) or not -60.0 <= level <= -3.0:
        raise ValueError("playback_level_dbfs must be between -60 and -3 dBFS")
    return {
        "format": LISTENING_SESSION_FORMAT,
        "schema_version": LISTENING_SESSION_SCHEMA_VERSION,
        "session_id": f"listen-{uuid.uuid4().hex[:16]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_fingerprint": project_fingerprint(project),
        "project_revision": _project_revision(project),
        "sample_rate": int(project.sample_rate),
        "candidate_ids": list(dict.fromkeys(str(item) for item in candidate_ids)),
        "analysis_enabled": bool(analysis_enabled),
        "playback_level_dbfs": level,
        "audition_transforms": [],
        "level_checks": [],
        "subtraction_history": [],
        "invariance_trials": [],
        "technical_analysis": {},
        "human_notes": {key: "" for key in REPORT_PROMPTS},
        "listening_policy": "human_judgement_only_no_artistic_score_or_auto_ranking",
    }


def validate_listening_session(session: Mapping[str, Any]) -> dict[str, Any]:
    value = _json_copy(dict(session), "listening session")
    if value.get("format") != LISTENING_SESSION_FORMAT:
        raise ValueError("not a Reawarp critical-listening session")
    if value.get("schema_version") != LISTENING_SESSION_SCHEMA_VERSION:
        raise ValueError("unsupported critical-listening session schema")
    required = (
        "session_id", "project_fingerprint", "project_revision", "sample_rate",
        "audition_transforms", "level_checks", "human_notes",
    )
    if any(key not in value for key in required):
        raise ValueError("critical-listening session is missing required provenance")
    if not isinstance(value["human_notes"], dict):
        raise ValueError("human_notes must be an object")
    value["human_notes"] = {
        key: str(value["human_notes"].get(key, "")) for key in REPORT_PROMPTS
    }
    return value


def attach_listening_session(project: ReawarpProject, session: Mapping[str, Any]) -> ReawarpProject:
    """Return a metadata-only project copy; stems and Score remain untouched."""
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    value = validate_listening_session(session)
    metadata = copy.deepcopy(project.metadata)
    metadata["m32_listening_session"] = value
    return replace(project, metadata=metadata)


def update_human_notes(session: Mapping[str, Any], notes: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_listening_session(session)
    unknown = set(notes) - set(REPORT_PROMPTS)
    if unknown:
        raise ValueError("unknown listening report dimensions: " + ", ".join(sorted(unknown)))
    value["human_notes"].update({key: str(note).strip() for key, note in notes.items()})
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    return validate_listening_session(value)


def record_session_event(
    session: Mapping[str, Any], collection: str, record: Mapping[str, Any]
) -> dict[str, Any]:
    value = validate_listening_session(session)
    allowed = {"audition_transforms", "level_checks", "subtraction_history", "invariance_trials"}
    if collection not in allowed:
        raise ValueError(f"unsupported listening session collection: {collection}")
    if not isinstance(value[collection], list):
        raise ValueError(f"{collection} must be an array")
    value[collection].append(_json_copy(dict(record), f"{collection} record"))
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    return value


def build_subtraction_pass(
    project: ReawarpProject,
    roles: Sequence[str],
    percentage: int,
    *,
    candidate_id: str | None = None,
    label: str | None = None,
    analysis_enabled: bool = True,
) -> AuditionResult:
    """Attenuate selected role contributions in an audition-only master copy."""
    from reawarp.variations import project_fingerprint
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    if isinstance(percentage, bool) or int(percentage) != percentage or not 0 <= int(percentage) <= 100:
        raise ValueError("subtraction percentage must be an integer from 0 to 100")
    selected = tuple(dict.fromkeys(_stem_for_role(str(item)) for item in roles))
    if not selected:
        raise ValueError("select at least one role for subtraction")
    missing = [name for name in selected if name not in project.stems]
    if missing:
        raise KeyError("project does not contain selected role(s): " + ", ".join(missing))
    master = _audio_copy(project.render_master(), "project master")
    before_hash = audio_fingerprint(master)
    output = master.astype(np.float64)
    amount = int(percentage) / 100.0
    for name in selected:
        stem = _audio_copy(project.stems[name], f"stem {name}")
        if stem.shape != master.shape:
            raise ValueError(f"stem {name!r} is not frame/channel aligned with the project master")
        output -= stem.astype(np.float64) * amount
    result = np.ascontiguousarray(output, dtype=np.float32)
    after_hash = audio_fingerprint(result)
    transform = AuditionTransform(
        transform_id=f"subtract-{uuid.uuid4().hex[:12]}",
        operation="role_subtraction",
        project_fingerprint=project_fingerprint(project),
        candidate_id=candidate_id,
        parameters={
            "roles": list(selected),
            "percentage": int(percentage),
            "label": str(label or f"Without {', '.join(selected)} · {percentage}%").strip(),
            "production_edit": False,
        },
        before_audio_sha256=before_hash,
        after_audio_sha256=after_hash,
        sample_rate=project.sample_rate,
    )
    return AuditionResult(
        label=str(label or f"WITHOUT {', '.join(selected).upper()} · {percentage}%"),
        audio=result,
        sample_rate=project.sample_rate,
        transform=transform,
        diagnostics={"analysis": analyse_audio(result, project.sample_rate, enabled=analysis_enabled)},
    )


def build_invariance_probe(
    project: ReawarpProject,
    *,
    anchor_roles: Sequence[str],
    removed_roles: Sequence[str],
    identity_label: str,
    candidate_id: str | None = None,
    analysis_enabled: bool = True,
) -> AuditionResult:
    """Create an explicit removal probe; the identity judgement remains human-authored."""
    anchors = tuple(dict.fromkeys(str(item) for item in anchor_roles))
    removed = tuple(dict.fromkeys(str(item) for item in removed_roles))
    if not str(identity_label).strip():
        raise ValueError("invariance probe requires a human-readable identity label")
    if not anchors:
        raise ValueError("invariance probe requires at least one declared anchor role")
    overlap = set(anchors) & set(removed)
    if overlap:
        raise ValueError("anchor roles cannot also be removed: " + ", ".join(sorted(overlap)))
    result = build_subtraction_pass(
        project, removed, 100, candidate_id=candidate_id,
        label=f"INVARIANCE · {identity_label}",
        analysis_enabled=analysis_enabled,
    )
    params = dict(result.transform.parameters)
    params.update({
        "anchor_roles": list(anchors),
        "removed_roles": list(removed),
        "identity_label": str(identity_label).strip(),
        "human_identity_survives": None,
        "question": "Does the declared identity remain perceptible without the removed material?",
    })
    transform = replace(result.transform, operation="invariance_removal_probe", parameters=params)
    return AuditionResult(
        label=result.label, audio=result.audio, sample_rate=result.sample_rate,
        transform=transform, diagnostics=result.diagnostics,
    )


def _phrase_plan(project: ReawarpProject):
    from reawarp.composition.phrases import PhrasePlan
    plan = PhrasePlan.from_score(project.to_score())
    if not plan.phrases:
        raise ValueError("the project Score has no phrase spans for contextual audition")
    return plan


def _phrase_roles(project: ReawarpProject, phrase) -> tuple[str, ...]:
    if phrase.roles:
        return tuple(dict.fromkeys(_stem_for_role(item) for item in phrase.roles))
    score = project.to_score()
    event_ids = set(phrase.event_ids)
    return tuple(dict.fromkeys(
        _stem_for_role(event.voice_id)
        for event in score.events if event.event_id in event_ids
    ))


def _phrase_audio(
    project: ReawarpProject, *, start_beat: Any, end_beat: Any, roles: Sequence[str]
) -> np.ndarray:
    from reawarp.score.timeline import RenderTimeline
    score = project.to_score()
    timeline = RenderTimeline(project.sample_rate, score.tempo_map, score.meter_map)
    start_frame = min(project.frame_count, timeline.beat_to_frame(start_beat))
    end_frame = min(project.frame_count, timeline.beat_to_frame(end_beat))
    if end_frame <= start_frame:
        raise ValueError("selected phrase context falls outside the rendered project")
    available = tuple(dict.fromkeys(_stem_for_role(item) for item in roles))
    if not available:
        raise ValueError("the selected phrase context has no declared roles")
    missing = [name for name in available if name not in project.stems]
    if missing:
        raise KeyError("phrase context roles are missing from project stems: " + ", ".join(missing))
    result = np.zeros((end_frame - start_frame, 2), dtype=np.float32)
    for name in available:
        stem = _audio_copy(project.stems[name], f"phrase context {name}")
        if stem.shape[1] == 1:
            stem = np.repeat(stem, 2, axis=1)
        result += stem[start_frame:end_frame]
    return result


def _altered_register(
    project: ReawarpProject, phrase_id: str, semitones: int, *,
    candidate_id: str | None, cancel_event: Any | None = None,
    analysis_enabled: bool = True,
) -> AuditionResult:
    from reawarp.composition.phrases import PhrasePlan
    from reawarp.core.engine import ReawarpEngine
    from reawarp.score.timeline import RenderTimeline
    score = project.to_score()
    plan = PhrasePlan.from_score(score)
    phrases = list(sorted(plan.phrases, key=lambda item: (item.start_beats, item.end_beats)))
    phrase_index = next((i for i, item in enumerate(phrases) if item.phrase_id == phrase_id), None)
    if phrase_index is None:
        raise KeyError(f"unknown phrase ID: {phrase_id}")
    phrase = phrases[phrase_index]
    selected_ids = set(phrase.event_ids)
    if not selected_ids:
        raise ValueError("selected phrase has no events to transpose")
    if isinstance(semitones, bool) or int(semitones) != semitones or not -48 <= int(semitones) <= 48:
        raise ValueError("register shift must be an integer from -48 to 48 semitones")
    if int(semitones) == 0:
        raise ValueError("altered-register audition requires a non-zero semitone shift")
    ratio = 2.0 ** (int(semitones) / 12.0)
    shifted = []
    changed = 0
    for event in score.events:
        if event.event_id not in selected_ids or event.kind != "note":
            shifted.append(event)
            continue
        pitch = None if event.pitch is None else float(event.pitch) + int(semitones)
        frequency = None if event.frequency_hz is None else float(event.frequency_hz) * ratio
        shifted.append(replace(event, pitch=pitch, frequency_hz=frequency))
        changed += 1
    if not changed:
        raise ValueError("selected phrase contains no pitched note events")
    audition_score = replace(score, events=tuple(shifted))
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("altered-register audition cancelled")
    rendered = ReawarpEngine().render_score(
        audition_score, config=project.config, frame_count=project.frame_count,
        cancel_event=cancel_event,
    )
    timeline = RenderTimeline(project.sample_rate, score.tempo_map, score.meter_map)
    start_frame = min(project.frame_count, timeline.beat_to_frame(phrase.start_beats))
    end_frame = min(project.frame_count, timeline.beat_to_frame(phrase.end_beats))
    audio = rendered.render_master()[start_frame:end_frame].copy()
    from reawarp.variations import project_fingerprint
    original = project.render_master()[start_frame:end_frame].copy()
    transform = AuditionTransform(
        transform_id=f"register-{uuid.uuid4().hex[:12]}",
        operation="altered_register",
        project_fingerprint=project_fingerprint(project),
        candidate_id=candidate_id,
        parameters={
            "phrase_id": phrase_id,
            "semitones": int(semitones),
            "frequency_ratio": ratio,
            "changed_note_events": changed,
            "render_path": "ReawarpEngine.render_score disposable Score copy",
            "production_edit": False,
        },
        before_audio_sha256=audio_fingerprint(original),
        after_audio_sha256=audio_fingerprint(audio),
        sample_rate=project.sample_rate,
    )
    return AuditionResult(
        label=f"ALTERED REGISTER · {phrase_id} · {semitones:+d} st",
        audio=audio,
        sample_rate=project.sample_rate,
        transform=transform,
        diagnostics={"analysis": analyse_audio(audio, project.sample_rate, enabled=analysis_enabled)},
    )


def build_contextual_audition_set(
    project: ReawarpProject,
    context: str = "full_track",
    *,
    phrase_id: str | None = None,
    roles: Sequence[str] = (),
    subtraction_percent: int = 35,
    register_semitones: int = 12,
    candidate_id: str | None = None,
    analysis_enabled: bool = True,
    cancel_event: Any | None = None,
) -> dict[str, AuditionResult]:
    """Return disposable listening contexts derived from an unchanged project."""
    from reawarp.variations import project_fingerprint
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("contextual audition cancelled")
    selected = project.render_master()
    before_hash = audio_fingerprint(selected)
    if context == "full_track":
        result_audio = selected.copy()
        label = "FULL TRACK"
        params = {"context": context, "roles": [], "production_edit": False}
    elif context in {"opening", "middle", "ending"}:
        spans = {"opening": (0.0, 1 / 3), "middle": (1 / 3, 2 / 3), "ending": (2 / 3, 1)}
        start, end = spans[context]
        lo, hi = int(round(len(selected) * start)), int(round(len(selected) * end))
        result_audio = selected[lo:hi].copy()
        label = context.upper()
        params = {"context": context, "frame_start": lo, "frame_end": hi, "production_edit": False}
    elif context in {"solo_phrase", "predecessor_to_candidate", "candidate_to_successor", "full_section"}:
        if not phrase_id:
            raise ValueError(f"{context} requires a selected phrase ID")
        plan = _phrase_plan(project)
        ordered = list(sorted(plan.phrases, key=lambda item: (item.start_beats, item.end_beats)))
        index = next((i for i, item in enumerate(ordered) if item.phrase_id == phrase_id), None)
        if index is None:
            raise KeyError(f"unknown phrase ID: {phrase_id}")
        phrase = ordered[index]
        if context == "solo_phrase":
            start_beat, end_beat, selected_phrases = phrase.start_beats, phrase.end_beats, [phrase]
        elif context == "predecessor_to_candidate":
            previous = ordered[index - 1] if index > 0 else phrase
            start_beat, end_beat = previous.start_beats, phrase.end_beats
            selected_phrases = [previous, phrase] if index > 0 else [phrase]
        elif context == "candidate_to_successor":
            following = ordered[index + 1] if index + 1 < len(ordered) else phrase
            start_beat, end_beat = phrase.start_beats, following.end_beats
            selected_phrases = [phrase, following] if index + 1 < len(ordered) else [phrase]
        else:
            section_id = phrase.parent_section_id
            if section_id is None:
                raise ValueError("selected phrase has no parent section; choose a phrase context instead")
            selected_phrases = [item for item in ordered if item.parent_section_id == section_id]
            start_beat = min(item.start_beats for item in selected_phrases)
            end_beat = max(item.end_beats for item in selected_phrases)
        context_roles = tuple(dict.fromkeys(
            role for item in selected_phrases for role in _phrase_roles(project, item)
        ))
        result_audio = _phrase_audio(
            project, start_beat=start_beat, end_beat=end_beat, roles=context_roles
        )
        label = {
            "solo_phrase": "SOLO PHRASE",
            "predecessor_to_candidate": "PREDECESSOR → CANDIDATE",
            "candidate_to_successor": "CANDIDATE → SUCCESSOR",
            "full_section": "FULL SECTION",
        }[context] + f" · {phrase_id}"
        params = {
            "context": context, "phrase_id": phrase_id,
            "phrase_ids": [item.phrase_id for item in selected_phrases],
            "start_beats": str(start_beat), "end_beats": str(end_beat),
            "roles": list(context_roles), "production_edit": False,
        }
    elif context == "reduced_density":
        result = build_subtraction_pass(
            project, roles, subtraction_percent, candidate_id=candidate_id,
            label=f"REDUCED DENSITY · {subtraction_percent}%",
            analysis_enabled=analysis_enabled,
        )
        return {result.label: result}
    elif context == "altered_register":
        if not phrase_id:
            raise ValueError("altered_register requires a selected phrase ID")
        result = _altered_register(
            project, phrase_id, register_semitones, candidate_id=candidate_id,
            cancel_event=cancel_event, analysis_enabled=analysis_enabled,
        )
        return {result.label: result}
    elif context == "invariance":
        if not roles:
            raise ValueError("invariance requires roles to remove")
        anchors = tuple(name for name in project.stems if name not in set(roles))
        result = build_invariance_probe(
            project, anchor_roles=anchors, removed_roles=roles,
            identity_label=" / ".join(anchors) or "declared project identity",
            candidate_id=candidate_id, analysis_enabled=analysis_enabled,
        )
        return {result.label: result}
    else:
        raise ValueError(f"unsupported listening context: {context}")
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("contextual audition cancelled")
    transform = AuditionTransform(
        transform_id=f"context-{uuid.uuid4().hex[:12]}",
        operation="context_crop",
        project_fingerprint=project_fingerprint(project),
        candidate_id=candidate_id,
        parameters=params,
        before_audio_sha256=before_hash,
        after_audio_sha256=audio_fingerprint(result_audio),
        sample_rate=project.sample_rate,
    )
    return {label: AuditionResult(label, result_audio, project.sample_rate, transform)}


def _spectral_occupancy(audio: np.ndarray, sample_rate: int) -> dict[str, Any]:
    value = np.asarray(audio, dtype=np.float64)
    mono = np.mean(value, axis=1) if value.ndim == 2 else value
    if len(mono) == 0 or not np.any(mono):
        return {
            "window_frames": ANALYSIS_WINDOW_FRAMES,
            "hop_frames": ANALYSIS_HOP_FRAMES,
            "bands": {"low": 0.0, "mid": 0.0, "high": 0.0},
            "note": "silent input; occupancy is undefined and shown as zero",
        }
    frame = min(ANALYSIS_WINDOW_FRAMES, len(mono))
    hop = min(ANALYSIS_HOP_FRAMES, max(1, frame // 2))
    window = np.hanning(frame)
    spectra = []
    for start in range(0, max(1, len(mono) - frame + 1), hop):
        segment = mono[start:start + frame]
        if len(segment) < frame:
            segment = np.pad(segment, (0, frame - len(segment)))
        spectra.append(np.square(np.abs(np.fft.rfft(segment * window))))
    power = np.mean(np.stack(spectra), axis=0)
    power_db = 10.0 * np.log10(np.maximum(power, 1e-24))
    peak_db = float(np.max(power_db))
    frequency = np.fft.rfftfreq(frame, 1.0 / float(sample_rate))
    bands = {
        "low": (20.0, min(250.0, sample_rate / 2.0)),
        "mid": (250.0, min(4_000.0, sample_rate / 2.0)),
        "high": (4_000.0, sample_rate / 2.0),
    }
    occupancy = {}
    for name, (lower, upper) in bands.items():
        mask = (frequency >= lower) & (frequency < upper)
        occupancy[name] = float(np.mean(power_db[mask] >= peak_db - 60.0)) if np.any(mask) else 0.0
    return {
        "window_frames": frame,
        "hop_frames": hop,
        "reference": "mean windowed power; occupancy threshold is -60 dB relative to analysis peak",
        "bands": occupancy,
    }


def analyse_audio(audio: Any, sample_rate: int, *, enabled: bool = True) -> dict[str, Any]:
    """Describe technical evidence only; never emits an artistic score."""
    if not enabled:
        return {"enabled": False, "metrics": {}, "warnings": [], "parameters": {}}
    if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
        raise ValueError("sample_rate must be positive")
    value = _audio_copy(audio, "analysis audio")
    metrics = measure_signal(value, sample_rate=int(sample_rate))
    frame_peak = np.max(np.abs(value), axis=1) if len(value) else np.zeros(0)
    silence_threshold = 10.0 ** (SILENCE_FLOOR_DBFS / 20.0)
    silent_frames = int(np.count_nonzero(frame_peak <= silence_threshold))
    last_active = int(np.flatnonzero(frame_peak > silence_threshold)[-1]) if np.any(
        frame_peak > silence_threshold
    ) else -1
    trailing = len(value) - last_active - 1 if last_active >= 0 else len(value)
    clipped = np.abs(value) >= 0.999
    clipped_count = int(np.count_nonzero(clipped))
    clip_fraction = float(clipped_count / max(1, value.size))
    if value.shape[1] == 2 and len(value):
        left, right = value[:, 0].astype(np.float64), value[:, 1].astype(np.float64)
        stereo_rms = float(np.sqrt(np.mean(value.astype(np.float64) ** 2)))
        mono_rms = float(np.sqrt(np.mean(((left + right) * 0.5) ** 2)))
        mono_loss_db = 20.0 * math.log10(max(mono_rms, 1e-12) / max(stereo_rms, 1e-12))
        left_c, right_c = left - np.mean(left), right - np.mean(right)
        denom = float(np.linalg.norm(left_c) * np.linalg.norm(right_c))
        lr_correlation = float(np.dot(left_c, right_c) / denom) if denom > 1e-12 else 0.0
    else:
        mono_loss_db, lr_correlation = 0.0, 1.0
    levels = {}
    for offset in (0, -12, -24, -36):
        scaled = np.ascontiguousarray(value * (10.0 ** (offset / 20.0)), dtype=np.float32)
        levels[str(offset)] = measure_signal(scaled, sample_rate=int(sample_rate))
    metrics.update({
        "clipped_sample_count": clipped_count,
        "clipped_sample_fraction": clip_fraction,
        "silence_ratio": float(silent_frames / max(1, len(value))),
        "silence_floor_dbfs": SILENCE_FLOOR_DBFS,
        "active_end_frame": last_active,
        "trailing_silence_seconds": trailing / float(sample_rate),
        "mono_fold_level_loss_db": mono_loss_db,
        "left_right_correlation": lr_correlation,
        "spectral_occupancy": _spectral_occupancy(value, int(sample_rate)),
        "playback_level_checks_db": levels,
    })
    warnings = []
    if clipped_count:
        warnings.append({
            "code": "clipping",
            "severity": "critical" if clip_fraction >= 0.001 else "warning",
            "message": "Samples reach or exceed the -0.01 dBFS diagnostic threshold.",
            "evidence": {"sample_count": clipped_count, "fraction": clip_fraction, "threshold": 0.999},
        })
    if metrics["silence_ratio"] >= 0.85:
        warnings.append({
            "code": "high_silence_ratio",
            "severity": "info",
            "message": "Most frames are below the declared silence floor; inspect whether this is intentional.",
            "evidence": {"ratio": metrics["silence_ratio"], "floor_dbfs": SILENCE_FLOOR_DBFS},
        })
    if value.shape[1] == 2 and mono_loss_db < -6.0:
        warnings.append({
            "code": "mono_fold_level_loss",
            "severity": "warning",
            "message": "Mono fold-down loses more than 6 dB relative to the stereo RMS.",
            "evidence": {"loss_db": mono_loss_db, "left_right_correlation": lr_correlation},
        })
    if value.shape[1] == 2 and lr_correlation < -0.7:
        warnings.append({
            "code": "anti_correlated_channels",
            "severity": "warning",
            "message": "Left and right channels are strongly anti-correlated.",
            "evidence": {"correlation": lr_correlation},
        })
    return {
        "enabled": True, "metrics": metrics, "warnings": warnings,
        "parameters": {
            "analysis_window_frames": ANALYSIS_WINDOW_FRAMES,
            "analysis_hop_frames": ANALYSIS_HOP_FRAMES,
            "silence_floor_dbfs": SILENCE_FLOOR_DBFS,
            "clipping_threshold": 0.999,
            "spectral_occupancy": "windowed mean power; -60 dB relative peak",
        },
    }


def _transient_activity(audio: Any, sample_rate: int) -> np.ndarray:
    value = _audio_copy(audio, "transient analysis")
    mono = np.mean(value, axis=1)
    frame_size = max(1, int(round(sample_rate * 0.01)))
    count = max(0, int(math.ceil(len(mono) / frame_size)))
    if count == 0:
        return np.zeros(0, dtype=bool)
    envelope = np.zeros(count, dtype=np.float64)
    for index in range(count):
        chunk = mono[index * frame_size:(index + 1) * frame_size]
        envelope[index] = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
    flux = np.maximum(0.0, np.diff(envelope, prepend=envelope[:1]))
    positive = flux[flux > 0]
    if not len(positive):
        return np.zeros(count, dtype=bool)
    threshold = max(float(np.quantile(positive, 0.90)), float(np.median(positive) * 3.0))
    return flux >= threshold


def analyse_project(project: ReawarpProject, *, enabled: bool = True) -> dict[str, Any]:
    """Analyse a project snapshot and attach evidence-bearing warnings by signal boundary."""
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    if not enabled:
        return {
            "enabled": False, "project_fingerprint": None, "master": {},
            "stems": {}, "transient_overlap": [], "warnings": [], "parameters": {},
        }
    from reawarp.variations import project_fingerprint
    master_result = analyse_audio(project.render_master(), project.sample_rate, enabled=True)
    stem_results = {
        name: analyse_audio(audio, project.sample_rate, enabled=True)
        for name, audio in sorted(project.stems.items())
    }
    transient = {
        name: _transient_activity(audio, project.sample_rate)
        for name, audio in sorted(project.stems.items())
    }
    overlap, warnings = [], list(master_result["warnings"])
    names = sorted(transient)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1:]:
            left, right = transient[left_name], transient[right_name]
            frames = min(len(left), len(right))
            if frames == 0:
                continue
            left_active, right_active = left[:frames], right[:frames]
            union = int(np.count_nonzero(left_active | right_active))
            shared = int(np.count_nonzero(left_active & right_active))
            ratio = float(shared / union) if union else 0.0
            if union:
                overlap.append({
                    "roles": [left_name, right_name],
                    "shared_onset_frames_10ms": shared,
                    "union_onset_frames_10ms": union,
                    "overlap_ratio": ratio,
                })
            if ratio >= 0.65 and shared >= 4:
                warnings.append({
                    "code": "transient_overlap", "severity": "info",
                    "message": "Two roles have frequent coincident positive-energy changes; audition masking and groove interaction.",
                    "evidence": {
                        "roles": [left_name, right_name], "overlap_ratio": ratio,
                        "shared_onset_frames_10ms": shared, "frame_size_ms": 10,
                    },
                })
    return {
        "enabled": True,
        "project_fingerprint": project_fingerprint(project),
        "sample_rate": project.sample_rate,
        "master": master_result["metrics"],
        "stems": {name: item["metrics"] for name, item in stem_results.items()},
        "transient_overlap": overlap,
        "warnings": warnings,
        "parameters": {
            **master_result["parameters"],
            "transient_frame_ms": 10,
            "overlap_ratio_threshold": 0.65,
            "overlap_minimum_shared_frames": 4,
        },
    }


def apply_playback_level(
    audio: Any, *, level_dbfs: float = -18.0, peak_ceiling: float = 0.95
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return a playback-only scaled copy and a record of the actual gain."""
    from reawarp.fx_routing import match_audition_level
    level = float(level_dbfs)
    if not math.isfinite(level) or not -60.0 <= level <= -3.0:
        raise ValueError("level_dbfs must be between -60 and -3")
    source = _audio_copy(audio, "playback level source")
    matched, report = match_audition_level(
        source, target_rms_dbfs=level, peak_ceiling=peak_ceiling
    )
    return matched.copy(), {
        **report,
        "requested_playback_level_dbfs": level,
        "production_audio_unchanged": True,
        "source_audio_sha256": audio_fingerprint(source),
        "audition_audio_sha256": audio_fingerprint(matched),
    }


def listening_report_markdown(session: Mapping[str, Any]) -> str:
    value = validate_listening_session(session)
    lines = [
        "# Reawarp Critical Listening Report",
        "",
        f"- Session: {value['session_id']}",
        f"- Project fingerprint: {value['project_fingerprint']}",
        f"- Project revision: {value['project_revision']}",
        f"- Sample rate: {value['sample_rate']:,} Hz",
        f"- Candidate IDs: {', '.join(value.get('candidate_ids', [])) or 'None recorded'}",
        "- Policy: human judgement only; no artistic score or automatic ranking.",
        "",
        "## Human listening prompts", "",
    ]
    for key, prompt in REPORT_PROMPTS.items():
        note = str(value["human_notes"].get(key, "")).strip()
        lines.extend([
            f"### {key.replace('_', ' ').title()}", "", prompt, "",
            note or "_No note recorded._", "",
        ])
    lines.extend(["## Audition history", ""])
    for entry in value.get("audition_transforms", []):
        params = json.dumps(entry.get("parameters", {}), ensure_ascii=False, sort_keys=True)
        lines.append(
            f"- **{entry.get('operation', 'audition')}** · "
            f"candidate {entry.get('candidate_id') or 'base'} · "
            f"decision {entry.get('decision', 'unreviewed')} · {params}"
        )
    if not value.get("audition_transforms"):
        lines.append("_No audition transforms recorded._")
    lines.extend(["", "## Playback level checks", ""])
    for entry in value.get("level_checks", []):
        lines.append(
            f"- Requested {entry.get('requested_playback_level_dbfs')} dBFS; "
            f"actual output RMS {entry.get('output_rms_dbfs')} dBFS; "
            f"gain {entry.get('linear_gain')}."
        )
    if not value.get("level_checks"):
        lines.append("_No playback-level checks recorded._")
    lines.extend(["", "## Technical diagnostics", ""])
    analysis = value.get("technical_analysis", {})
    if not analysis or not analysis.get("enabled", False):
        lines.append("Analysis was disabled for this session.")
    else:
        master = analysis.get("master", {})
        lines.append(
            f"- Master peak {master.get('peak_dbfs', 'n/a')} dBFS; "
            f"RMS {master.get('rms_dbfs', 'n/a')} dBFS; "
            f"silence ratio {master.get('silence_ratio', 'n/a')}."
        )
        for warning in analysis.get("warnings", []):
            evidence = json.dumps(warning.get("evidence", {}), ensure_ascii=False, sort_keys=True)
            lines.append(
                f"- **{str(warning.get('severity', 'info')).upper()}** "
                f"{warning.get('code', 'diagnostic')}: {warning.get('message', '')} "
                f"Evidence: {evidence}"
            )
        if not analysis.get("warnings"):
            lines.append("No technical warnings were raised by the selected analysis.")
    lines.extend([
        "",
        "## Interpretation", "",
        "Measurements describe the rendered signal and analysis settings. They do not establish artistic quality; human listening notes remain authoritative.",
        "",
    ])
    return "\n".join(lines)


__all__ = [
    "ANALYSIS_HOP_FRAMES", "ANALYSIS_WINDOW_FRAMES", "AuditionResult",
    "AuditionTransform", "LISTENING_SESSION_FORMAT", "LISTENING_SESSION_SCHEMA_VERSION",
    "ListeningEditHistory", "REPORT_PROMPTS", "analyse_audio", "analyse_project",
    "apply_playback_level", "attach_listening_session", "audio_fingerprint",
    "build_contextual_audition_set", "build_invariance_probe", "build_subtraction_pass",
    "listening_report_markdown", "new_listening_session", "record_session_event",
    "update_human_notes", "validate_listening_session",
]
