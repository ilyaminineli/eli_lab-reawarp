"""Score-tuning-aware motif resolution, sonority binding, and event emission."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any, Mapping

from reawarp.composition.motifs import (
    MOTIF_IDENTITY_DIMENSIONS,
    MotifPlan,
    motif_identity_contract,
)
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.pitch import Sonority, tuning_from_score
from reawarp.score.time import as_fraction


@dataclass(frozen=True, slots=True)
class MotifResolutionRecord:
    """Transformation and identity contract for one arrangement section."""

    motif_id: str
    section_index: int
    section_name: str
    operation: str
    preserved_dimensions: tuple[str, ...]
    changed_dimensions: tuple[str, ...]
    source_sonority_id: str | None = None
    target_sonority_id: str | None = None
    pitch_offset: float = 0.0

    def __post_init__(self) -> None:
        if not self.motif_id or not self.section_name or not self.operation:
            raise ValueError(
                "motif resolution record requires motif, section, and operation IDs"
            )
        if not math.isfinite(float(self.pitch_offset)):
            raise ValueError("motif pitch_offset must be finite")
        preserved = tuple(self.preserved_dimensions)
        changed = tuple(self.changed_dimensions)
        if len(preserved) != len(set(preserved)) or len(changed) != len(set(changed)):
            raise ValueError("motif identity dimensions must be unique")
        if set(preserved) & set(changed):
            raise ValueError(
                "a motif identity dimension cannot be both preserved and changed"
            )
        if set(preserved) | set(changed) != set(MOTIF_IDENTITY_DIMENSIONS):
            raise ValueError("motif identity contract must declare all six dimensions")
        object.__setattr__(
            self,
            "preserved_dimensions",
            tuple(item for item in MOTIF_IDENTITY_DIMENSIONS if item in preserved),
        )
        object.__setattr__(
            self,
            "changed_dimensions",
            tuple(item for item in MOTIF_IDENTITY_DIMENSIONS if item in changed),
        )
        object.__setattr__(self, "pitch_offset", float(self.pitch_offset))

    def to_dict(self) -> dict[str, object]:
        return {
            "motif_id": self.motif_id,
            "section_index": self.section_index,
            "section_name": self.section_name,
            "operation": self.operation,
            "preserved_dimensions": list(self.preserved_dimensions),
            "changed_dimensions": list(self.changed_dimensions),
            "source_sonority_id": self.source_sonority_id,
            "target_sonority_id": self.target_sonority_id,
            "pitch_offset": self.pitch_offset,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MotifResolutionRecord":
        return cls(
            motif_id=str(data.get("motif_id", "")),
            section_index=int(data.get("section_index", 0)),
            section_name=str(data.get("section_name", "")),
            operation=str(data.get("operation", "repeat")),
            preserved_dimensions=tuple(
                str(x) for x in data.get("preserved_dimensions", ())
            ),
            changed_dimensions=tuple(
                str(x) for x in data.get("changed_dimensions", ())
            ),
            source_sonority_id=(
                None
                if data.get("source_sonority_id") is None
                else str(data["source_sonority_id"])
            ),
            target_sonority_id=(
                None
                if data.get("target_sonority_id") is None
                else str(data["target_sonority_id"])
            ),
            pitch_offset=float(data.get("pitch_offset", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class MotifResolutionPlan:
    """Resolved motif events and tuning/sonority transformation provenance."""

    motif_id: str
    tuning_id: str
    tuning_reference_pitch: float
    tuning_reference_frequency_hz: float
    tuning_divisions_per_period: int
    tuning_period_ratio: float
    voice_id: str
    records: tuple[MotifResolutionRecord, ...]
    events: tuple[MusicalEvent, ...]

    def __post_init__(self) -> None:
        if not self.motif_id or not self.tuning_id or not self.voice_id:
            raise ValueError("motif resolution requires motif, tuning, and voice IDs")
        if (
            not math.isfinite(float(self.tuning_reference_pitch))
            or not math.isfinite(float(self.tuning_reference_frequency_hz))
            or self.tuning_reference_frequency_hz <= 0
            or isinstance(self.tuning_divisions_per_period, bool)
            or self.tuning_divisions_per_period < 1
            or not math.isfinite(float(self.tuning_period_ratio))
            or self.tuning_period_ratio <= 1
        ):
            raise ValueError("motif resolution tuning data is invalid")
        events = tuple(self.events)
        if any(not isinstance(item, MusicalEvent) for item in events):
            raise ValueError("motif resolution events must be MusicalEvent records")
        if any(
            item.voice_id != self.voice_id
            or item.kind != "note"
            or item.parameters.get("planner") != "m19.5_motif"
            for item in events
        ):
            raise ValueError("motif resolution events must belong to its note voice")
        event_ids = [item.event_id for item in events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("motif resolution event IDs must be unique")
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(
            self,
            "events",
            tuple(sorted(events, key=lambda item: (item.onset_beats, item.event_id))),
        )

    def to_dict(self, *, include_events: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "format": "eli_lab_reawarp_motif_resolution",
            "schema_version": 1,
            "motif_id": self.motif_id,
            "voice_id": self.voice_id,
            "tuning": {
                "id": self.tuning_id,
                "reference_pitch": self.tuning_reference_pitch,
                "reference_frequency_hz": self.tuning_reference_frequency_hz,
                "divisions_per_period": self.tuning_divisions_per_period,
                "period_ratio": self.tuning_period_ratio,
            },
            "records": [item.to_dict() for item in self.records],
            "event_ids": [item.event_id for item in self.events],
        }
        if include_events:
            data["events"] = [item.to_dict() for item in self.events]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MotifResolutionPlan":
        if data.get("format") != "eli_lab_reawarp_motif_resolution":
            raise ValueError("data is not a Reawarp motif resolution plan")
        if int(data.get("schema_version", 1)) != 1:
            raise ValueError("unsupported motif resolution schema version")
        tuning = data.get("tuning", {})
        if not isinstance(tuning, Mapping):
            raise ValueError("motif resolution tuning must be an object")
        return cls(
            motif_id=str(data.get("motif_id", "")),
            voice_id=str(data.get("voice_id", "")),
            tuning_id=str(tuning.get("id", "12tet")),
            tuning_reference_pitch=float(tuning.get("reference_pitch", 69.0)),
            tuning_reference_frequency_hz=float(
                tuning.get("reference_frequency_hz", 440.0)
            ),
            tuning_divisions_per_period=int(tuning.get("divisions_per_period", 12)),
            tuning_period_ratio=float(tuning.get("period_ratio", 2.0)),
            records=tuple(
                MotifResolutionRecord.from_dict(item)
                for item in data.get("records", ())
            ),
            events=tuple(
                MusicalEvent.from_dict(item) for item in data.get("events", ())
            ),
        )

    def attach_to_score(self, score: Score, *, replace_existing: bool = True) -> Score:
        """Return a new Score with resolved motif notes and a compact provenance record."""
        previous_record = score.metadata.get("motif_resolution", {})
        previous_ids = set(
            previous_record.get("event_ids", ())
            if isinstance(previous_record, dict)
            else ()
        )
        retained = tuple(
            event
            for event in score.events
            if not (
                replace_existing
                and event.event_id in previous_ids
                and event.parameters.get("planner") == "m19.5_motif"
            )
        )
        retained_ids = {event.event_id for event in retained}
        collisions = retained_ids & {event.event_id for event in self.events}
        if collisions:
            raise ValueError(
                "motif event IDs collide with existing Score events: "
                + ", ".join(sorted(collisions))
            )
        metadata = dict(score.metadata)
        metadata["motif_resolution"] = self.to_dict(include_events=False)
        return replace(
            score,
            events=retained + self.events,
            metadata=metadata,
        )

    @classmethod
    def from_score(cls, score: Score) -> "MotifResolutionPlan":
        record = score.metadata.get("motif_resolution")
        if not isinstance(record, dict):
            raise ValueError("Score does not contain motif_resolution metadata")
        event_ids = tuple(str(item) for item in record.get("event_ids", ()))
        by_id = {event.event_id: event for event in score.events}
        missing = set(event_ids) - set(by_id)
        if missing:
            raise ValueError(
                "Score is missing motif event(s): " + ", ".join(sorted(missing))
            )
        data = dict(record)
        data["events"] = [by_id[item].to_dict() for item in event_ids]
        return cls.from_dict(data)


def _midi_frequency(note: float) -> float:
    return 440.0 * (2.0 ** ((float(note) - 69.0) / 12.0))


def _beat_at_bar(meter_map, zero_based_bar: int) -> Fraction:
    """Resolve a zero-based bar boundary through meter changes."""
    if isinstance(zero_based_bar, bool) or zero_based_bar < 0:
        raise ValueError("bar index must be a non-negative integer")
    target_bar = int(zero_based_bar) + 1
    bars_before = 0
    points = meter_map.points
    for index, point in enumerate(points):
        start = point.at_beats
        bar_length = point.bar_length_beats
        if index + 1 < len(points):
            end = points[index + 1].at_beats
            span = end - start
            bars_in_segment = int(math.ceil(float(span / bar_length) - 1e-12))
            if target_bar <= bars_before + bars_in_segment:
                return start + (target_bar - bars_before - 1) * bar_length
            bars_before += bars_in_segment
        else:
            return start + (target_bar - bars_before - 1) * bar_length
    raise ValueError(f"bar {target_bar} is outside the meter map")


def _stable_event_id(
    motif_id: str,
    section_index: int,
    phrase_index: int,
    note_index: int,
    onset: Fraction,
) -> str:
    payload = (
        f"m19.5:{motif_id}:{section_index}:{phrase_index}:{note_index}:{onset}"
    ).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).hexdigest()
    return f"motif-{digest}"


def resolve_motif_plan_to_score(
    plan: MotifPlan,
    score: Score,
    *,
    sonorities_by_section: Mapping[str, Sonority] | None = None,
    voice_id: str | None = None,
) -> MotifResolutionPlan:
    """Resolve an M15 motif plan through Score tuning and optional sonority anchors.

    Existing M15 motif pitches are standard MIDI semitone values. They are first
    converted to their exact equal-tempered frequencies, then mapped into the
    Score's tuning coordinates. A target sonority translates the motif as a
    whole so its centre meets the sonority bass/root anchor. This retains the
    motif's contour, interval profile, rhythm, articulation and timbre; register
    is marked changed when the sonority requires a transposition.
    """
    if not isinstance(plan, MotifPlan):
        raise ValueError("plan must be a MotifPlan")
    tuning = tuning_from_score(score)
    resolved_voice = voice_id or plan.anchor.role or "motif"
    sonority_map = dict(sonorities_by_section or {})
    anchor_frequency = _midi_frequency(plan.anchor.pitch_center)
    anchor_coordinate = tuning.pitch_for_frequency(anchor_frequency)
    records: list[MotifResolutionRecord] = []
    events: list[MusicalEvent] = []

    for instance in plan.instances:
        sonority = sonority_map.get(instance.section_name)
        if sonority is None:
            sonority = sonority_map.get(str(instance.section_index))
        target_anchor = None
        if sonority is not None:
            if not isinstance(sonority, Sonority):
                raise ValueError(
                    "sonorities_by_section values must be Sonority objects"
                )
            target_anchor = (
                sonority.bass_pitch
                if sonority.bass_pitch is not None
                else min(sonority.pitches)
            )
        pitch_offset = (
            0.0 if target_anchor is None else float(target_anchor) - anchor_coordinate
        )

        base_contract = motif_identity_contract(instance.operation)
        preserved = set(instance.preserved_dimensions or base_contract["preserved"])
        if abs(pitch_offset) > 1e-9:
            preserved.discard("register")
        preserved_dimensions = tuple(
            item for item in MOTIF_IDENTITY_DIMENSIONS if item in preserved
        )
        changed_dimensions = tuple(
            item for item in MOTIF_IDENTITY_DIMENSIONS if item not in preserved
        )
        records.append(
            MotifResolutionRecord(
                motif_id=instance.motif_id,
                section_index=instance.section_index,
                section_name=instance.section_name,
                operation=(
                    instance.operation
                    if sonority is None
                    else f"{instance.operation}+sonority_anchor"
                ),
                preserved_dimensions=preserved_dimensions,
                changed_dimensions=changed_dimensions,
                source_sonority_id=(
                    None if sonority is None else sonority.source_sonority_id
                ),
                target_sonority_id=None if sonority is None else sonority.sonority_id,
                pitch_offset=pitch_offset,
            )
        )

        section_start = _beat_at_bar(score.meter_map, instance.start_bar)
        section_end = _beat_at_bar(score.meter_map, instance.end_bar)
        if section_end <= section_start:
            continue
        phrase_period = Fraction(max(1, int(instance.phrase_steps)), 4)
        cursor = Fraction(0)
        phrase_index = 0
        while section_start + cursor < section_end:
            for note_index, note in enumerate(instance.notes):
                note_offset = Fraction(int(note.step), 4)
                onset = section_start + cursor + note_offset
                if onset >= section_end:
                    continue
                source_frequency = _midi_frequency(note.midi_note)
                source_coordinate = tuning.pitch_for_frequency(source_frequency)
                pitch = float(source_coordinate + pitch_offset)
                frequency = float(tuning.frequency_for_pitch(pitch))
                duration = as_fraction(float(note.duration_steps)) / 4
                duration = min(duration, section_end - onset)
                if duration <= 0:
                    continue
                event_id = _stable_event_id(
                    plan.anchor.motif_id,
                    instance.section_index,
                    phrase_index,
                    note_index,
                    onset,
                )
                parameters = {
                    "planner": "m19.5_motif",
                    "motif_id": instance.motif_id,
                    "motif_operation": instance.operation,
                    "motif_operations": list(instance.operations),
                    "motif_preserved_dimensions": list(preserved_dimensions),
                    "motif_changed_dimensions": list(changed_dimensions),
                    "motif_phrase_index": phrase_index,
                    "motif_note_index": note_index,
                    "motif_source_midi_note": int(note.midi_note),
                    "motif_source_frequency_hz": source_frequency,
                    "motif_pitch_offset": pitch_offset,
                    "section_index": instance.section_index,
                    "section_name": instance.section_name,
                    "timbre": note.timbre,
                    "pan": float(note.pan),
                }
                if sonority is not None:
                    parameters["target_sonority_id"] = sonority.sonority_id
                    if sonority.source_sonority_id is not None:
                        parameters["source_sonority_id"] = sonority.source_sonority_id
                events.append(
                    MusicalEvent(
                        event_id=event_id,
                        voice_id=resolved_voice,
                        onset_beats=onset,
                        duration_beats=duration,
                        kind="note",
                        pitch=pitch,
                        frequency_hz=frequency,
                        velocity=float(note.velocity),
                        articulation=note.articulation,
                        parameters=parameters,
                        tags=("motif", "m19.5", instance.operation),
                        source_id=instance.motif_id,
                        seed=int.from_bytes(
                            hashlib.blake2b(
                                event_id.encode("utf-8"), digest_size=4
                            ).digest(),
                            "big",
                        ),
                        tuning_id=score.tuning_id,
                    )
                )
            cursor += phrase_period
            phrase_index += 1

    return MotifResolutionPlan(
        motif_id=plan.anchor.motif_id,
        tuning_id=score.tuning_id,
        tuning_reference_pitch=score.tuning_reference_pitch,
        tuning_reference_frequency_hz=score.tuning_reference_frequency_hz,
        tuning_divisions_per_period=score.tuning_divisions_per_period,
        tuning_period_ratio=score.tuning_period_ratio,
        voice_id=resolved_voice,
        records=tuple(records),
        events=tuple(events),
    )
