"""Persistent musical motifs and deterministic cross-role phrase transformations."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class MotifNote:
    step: int
    midi_note: int
    duration_steps: float
    velocity: float
    pan: float
    source_x: float = 0.0
    source_y: float = 0.0
    articulation: str = "default"
    timbre: str = "default"

    def to_dict(self) -> dict[str, int | float | str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotifNote":
        return cls(
            step=int(data["step"]),
            midi_note=int(data["midi_note"]),
            duration_steps=float(data["duration_steps"]),
            velocity=float(data.get("velocity", 0.8)),
            pan=float(data.get("pan", 0.0)),
            source_x=float(data.get("source_x", 0.0)),
            source_y=float(data.get("source_y", 0.0)),
            articulation=str(data.get("articulation", "default")),
            timbre=str(data.get("timbre", "default")),
        )


@dataclass(frozen=True, slots=True)
class Motif:
    motif_id: str
    role: str
    source_section: str
    source_start_bar: int
    phrase_bars: int
    pitch_center: int
    notes: tuple[MotifNote, ...]

    @property
    def phrase_steps(self) -> int:
        return self.phrase_bars * 16

    def to_dict(self) -> dict[str, Any]:
        return {
            "motif_id": self.motif_id,
            "role": self.role,
            "source_section": self.source_section,
            "source_start_bar": self.source_start_bar,
            "phrase_bars": self.phrase_bars,
            "pitch_center": self.pitch_center,
            "notes": [note.to_dict() for note in self.notes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Motif":
        return cls(
            motif_id=str(data["motif_id"]),
            role=str(data.get("role", "melody")),
            source_section=str(data.get("source_section", "SOURCE_PHRASE")),
            source_start_bar=int(data.get("source_start_bar", 0)),
            phrase_bars=int(data.get("phrase_bars", 1)),
            pitch_center=int(data.get("pitch_center", 60)),
            notes=tuple(MotifNote.from_dict(item) for item in data.get("notes", ())),
        )


@dataclass(frozen=True, slots=True)
class MotifInstance:
    motif_id: str
    section_index: int
    section_name: str
    function: str
    start_bar: int
    end_bar: int
    operation: str
    operations: tuple[str, ...]
    phrase_steps: int
    notes: tuple[MotifNote, ...]
    preserved_dimensions: tuple[str, ...] = ()
    changed_dimensions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "motif_id": self.motif_id,
            "section_index": self.section_index,
            "section_name": self.section_name,
            "function": self.function,
            "start_bar": self.start_bar,
            "end_bar": self.end_bar,
            "operation": self.operation,
            "operations": list(self.operations),
            "phrase_steps": self.phrase_steps,
            "notes": [note.to_dict() for note in self.notes],
            "preserved_dimensions": list(self.preserved_dimensions),
            "changed_dimensions": list(self.changed_dimensions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotifInstance":
        return cls(
            motif_id=str(data["motif_id"]),
            section_index=int(data.get("section_index", 0)),
            section_name=str(data.get("section_name", "")),
            function=str(data.get("function", "continuation")),
            start_bar=int(data.get("start_bar", 0)),
            end_bar=int(data.get("end_bar", 0)),
            operation=str(data.get("operation", "repeat")),
            operations=tuple(str(item) for item in data.get("operations", ())),
            phrase_steps=int(data.get("phrase_steps", 16)),
            notes=tuple(MotifNote.from_dict(item) for item in data.get("notes", ())),
            preserved_dimensions=tuple(
                str(item) for item in data.get("preserved_dimensions", ())
            ),
            changed_dimensions=tuple(
                str(item) for item in data.get("changed_dimensions", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class MotifPlan:
    anchor: Motif
    instances: tuple[MotifInstance, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "anchor": self.anchor.to_dict(),
            "instances": [instance.to_dict() for instance in self.instances],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotifPlan":
        if int(data.get("schema_version", 1)) != 1:
            raise ValueError("unsupported motif plan schema version")
        anchor = data.get("anchor")
        if not isinstance(anchor, dict):
            raise ValueError("motif plan requires an anchor object")
        return cls(
            anchor=Motif.from_dict(anchor),
            instances=tuple(
                MotifInstance.from_dict(item) for item in data.get("instances", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class MotifAccent:
    role: str
    step: int
    velocity: float
    pan: float
    kind: str
    pattern_style: str
    motif_id: str
    motif_relation: str


MOTIF_IDENTITY_DIMENSIONS = (
    "contour",
    "interval_profile",
    "rhythm",
    "register",
    "articulation",
    "timbre",
)

_MOTIF_IDENTITY_BY_OPERATION = {
    "repeat": (
        "contour",
        "interval_profile",
        "rhythm",
        "register",
        "articulation",
        "timbre",
    ),
    "return": (
        "contour",
        "interval_profile",
        "rhythm",
        "register",
        "articulation",
        "timbre",
    ),
    "displacement": (
        "contour",
        "interval_profile",
        "rhythm",
        "register",
        "articulation",
        "timbre",
    ),
    "fragmentation": ("articulation", "timbre"),
    "augmentation": (
        "contour",
        "interval_profile",
        "register",
        "articulation",
        "timbre",
    ),
    "diminution": ("contour", "interval_profile", "register", "articulation", "timbre"),
    "inversion": ("rhythm", "articulation", "timbre"),
    "retrograde": ("register", "articulation", "timbre"),
    "rhythmic_shadow": (
        "contour",
        "interval_profile",
        "rhythm",
        "register",
        "articulation",
        "timbre",
    ),
    "call_response": ("articulation", "timbre"),
    "dissolve": ("articulation", "timbre"),
}


def motif_identity_contract(operation: str) -> dict[str, tuple[str, ...]]:
    """Declare exactly which named motif dimensions survive an operation.

    A retained dimension is a structural contract, not a claim that the
    transformation is perceptually successful in every context.
    """
    try:
        preserved = _MOTIF_IDENTITY_BY_OPERATION[operation]
    except KeyError as exc:
        raise ValueError(f"unknown motif transformation: {operation}") from exc
    changed = tuple(
        dimension
        for dimension in MOTIF_IDENTITY_DIMENSIONS
        if dimension not in preserved
    )
    return {"preserved": preserved, "changed": changed}


def _clip(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _stable_index(seed: int | str, section_index: int, purpose: str, count: int) -> int:
    payload = f"{seed}:{section_index}:{purpose}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "little") % max(1, count)


def _extract_anchor_motif(
    melody_events: Sequence[Any],
    sections: Sequence[Any],
    phrase_directives: Sequence[Any],
    bpm: float,
    seed: int | str,
) -> Motif | None:
    if not melody_events or bpm <= 0:
        return None
    directives = {int(item.index): item for item in phrase_directives}
    windows = []
    for section in sections:
        phrase_bars = max(1, min(2, int(section.phrase_bars)))
        start_bar = int(section.start_bar)
        start_step = start_bar * 16
        end_step = start_step + phrase_bars * 16
        selected = sorted(
            (
                event
                for event in melody_events
                if start_step <= int(event.step) < end_step
            ),
            key=lambda event: (int(event.step), int(event.midi_note)),
        )
        if len(selected) < 2:
            continue
        function = str(getattr(directives.get(int(section.index)), "function", ""))
        priority = (
            3
            if function == "establishment"
            else (2 if str(section.motif_mode) == "present" else 1)
        )
        windows.append(
            (
                (priority, len(selected), -start_bar),
                section,
                start_bar,
                phrase_bars,
                selected,
            )
        )

    if windows:
        _rank, source_section, start_bar, phrase_bars, selected = max(
            windows, key=lambda item: item[0]
        )
        source_name = str(source_section.name)
    else:
        ordered = sorted(
            melody_events, key=lambda event: (int(event.step), int(event.midi_note))
        )
        if len(ordered) < 2:
            return None
        start_bar = int(ordered[0].step) // 16
        phrase_bars = max(
            1, min(2, int(math.ceil((int(ordered[-1].step) - start_bar * 16 + 1) / 16)))
        )
        end_step = start_bar * 16 + phrase_bars * 16
        selected = [
            event for event in ordered if start_bar * 16 <= int(event.step) < end_step
        ]
        if len(selected) < 2:
            selected = ordered[:8]
            start_bar = int(selected[0].step) // 16
            phrase_bars = 1
        source_name = "SOURCE_PHRASE"

    phrase_steps = phrase_bars * 16
    step_seconds = 60.0 / float(bpm) / 4.0
    notes = [
        MotifNote(
            step=int(event.step) - start_bar * 16,
            midi_note=int(event.midi_note),
            duration_steps=_clip(float(event.duration) / step_seconds, 0.5, 16.0),
            velocity=_clip(float(event.velocity), 0.0, 1.0),
            pan=_clip(float(event.pan), -1.0, 1.0),
            source_x=float(getattr(event, "source_x", 0.0)),
            source_y=float(getattr(event, "source_y", 0.0)),
            articulation=str(getattr(event, "articulation", "default")),
            timbre=str(
                getattr(event, "timbre", getattr(event, "synthesis_profile", "default"))
            ),
        )
        for event in selected
        if 0 <= int(event.step) - start_bar * 16 < phrase_steps
    ]
    notes.sort(key=lambda note: (note.step, note.midi_note))
    if not notes:
        return None
    if len(notes) > 12:
        indexes = sorted(
            {int(round(index * (len(notes) - 1) / 11)) for index in range(12)}
        )
        notes = [notes[index] for index in indexes]
    pitches = sorted(note.midi_note for note in notes)
    pitch_center = int(round(pitches[len(pitches) // 2]))
    identity_payload = {
        "seed": str(seed),
        "source_section": source_name,
        "start_bar": start_bar,
        "phrase_bars": phrase_bars,
        "notes": [note.to_dict() for note in notes],
    }
    digest = hashlib.blake2s(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        ),
        digest_size=6,
    ).hexdigest()
    return Motif(
        motif_id=f"motif-{digest}",
        role="melody",
        source_section=source_name,
        source_start_bar=start_bar,
        phrase_bars=phrase_bars,
        pitch_center=pitch_center,
        notes=tuple(notes),
    )


def transform_motif_with_identity(
    motif: Motif,
    operation: str,
) -> tuple[tuple[MotifNote, ...], int, dict[str, tuple[str, ...]]]:
    """Transform motif material and return its explicit identity contract."""
    contract = motif_identity_contract(operation)
    phrase_steps = motif.phrase_steps
    source = list(motif.notes)
    if operation in {"repeat", "return"}:
        notes = source
    elif operation == "displacement":
        notes = [replace(n, step=(n.step + 1) % phrase_steps) for n in source]
    elif operation == "fragmentation":
        notes = [n for index, n in enumerate(source) if index == 0 or index % 2 == 0]
    elif operation == "augmentation":
        phrase_steps *= 2
        notes = [
            replace(n, step=n.step * 2, duration_steps=min(24.0, n.duration_steps * 2))
            for n in source
        ]
    elif operation == "diminution":
        phrase_steps = max(8, phrase_steps // 2)
        notes = [
            replace(
                n,
                step=min(phrase_steps - 1, int(round(n.step * 0.5))),
                duration_steps=max(0.5, n.duration_steps * 0.5),
            )
            for n in source
        ]
    elif operation == "inversion":
        notes = [
            replace(n, midi_note=2 * motif.pitch_center - n.midi_note) for n in source
        ]
    elif operation == "retrograde":
        notes = [
            replace(n, step=phrase_steps - 1 - n.step, pan=-n.pan)
            for n in reversed(source)
        ]
    elif operation == "rhythmic_shadow":
        notes = [
            replace(n, step=(n.step + 2) % phrase_steps, velocity=n.velocity * 0.82)
            for n in source
        ]
    elif operation == "call_response":
        half = max(4, phrase_steps // 2)
        notes = []
        for note in source:
            local = note.step % half
            notes.append(replace(note, step=local))
            if local + half < phrase_steps:
                notes.append(
                    replace(
                        note,
                        step=local + half,
                        midi_note=2 * motif.pitch_center - note.midi_note,
                        velocity=note.velocity * 0.78,
                        pan=-note.pan,
                    )
                )
    else:  # dissolve
        notes = [
            replace(
                note,
                velocity=note.velocity * (0.86 if index == 0 else 0.62),
            )
            for index, note in enumerate(source)
            if index == 0 or index % 3 == 0
        ]

    notes = [
        replace(
            note,
            step=int(note.step) % phrase_steps,
            midi_note=int(note.midi_note),
            duration_steps=_clip(note.duration_steps, 0.35, 24.0),
            velocity=_clip(note.velocity, 0.0, 1.0),
            pan=_clip(note.pan, -1.0, 1.0),
            source_x=float(note.source_x),
            source_y=float(note.source_y),
        )
        for note in notes
    ]
    notes.sort(key=lambda note: (note.step, note.midi_note))
    return tuple(notes), phrase_steps, contract


def transform_motif(motif: Motif, operation: str) -> tuple[tuple[MotifNote, ...], int]:
    """Backwards-compatible motif transform; identity detail is available separately."""
    notes, phrase_steps, _contract = transform_motif_with_identity(motif, operation)
    return notes, phrase_steps


def _operation_for_section(section: Any, directive: Any, seed: int | str) -> str:
    function = str(getattr(directive, "function", "continuation"))
    mode = str(section.motif_mode)
    if function == "return":
        return "return"
    if function == "false_return":
        return "displacement"
    if function == "contrast":
        return "call_response"
    if function in {"silence", "outro", "residue"} or mode == "dissolve":
        return (
            "dissolve"
            if function in {"residue", "outro"} or mode == "dissolve"
            else "fragmentation"
        )
    if mode == "present":
        return "repeat"
    if mode == "fragment":
        return "fragmentation"
    if mode == "inversion":
        return "inversion"
    if mode == "rhythmic" or function == "uplift":
        return "diminution" if function == "uplift" else "rhythmic_shadow"
    if mode == "develop" or function == "development":
        options = (
            "displacement",
            "retrograde",
            "inversion",
            "augmentation",
            "rhythmic_shadow",
        )
        return options[
            _stable_index(seed, int(section.index), "development", len(options))
        ]
    return "repeat"


def build_motif_plan(
    melody_events: Sequence[Any],
    composition_plan: Any,
    phrase_directives: Sequence[Any],
    *,
    bpm: float,
    seed: int | str,
) -> MotifPlan | None:
    """Extract one stable source phrase and transform it within every section."""
    anchor = _extract_anchor_motif(
        melody_events, composition_plan.sections, phrase_directives, bpm, seed
    )
    if anchor is None:
        return None
    directives = {int(item.index): item for item in phrase_directives}
    instances = []
    for section in composition_plan.sections:
        directive = directives.get(int(section.index))
        operation = _operation_for_section(section, directive, seed)
        notes, phrase_steps, contract = transform_motif_with_identity(anchor, operation)
        instances.append(
            MotifInstance(
                motif_id=anchor.motif_id,
                section_index=int(section.index),
                section_name=str(section.name),
                function=str(getattr(directive, "function", "continuation")),
                start_bar=int(section.start_bar),
                end_bar=int(section.end_bar),
                operation=operation,
                operations=(operation,),
                phrase_steps=phrase_steps,
                notes=notes,
                preserved_dimensions=contract["preserved"],
                changed_dimensions=contract["changed"],
            )
        )
    return MotifPlan(anchor=anchor, instances=tuple(instances))


def render_motif_events(
    plan: MotifPlan,
    *,
    bpm: float,
    duration_seconds: float,
) -> list[Any]:
    """Repeat each transformed motif inside its section on the shared 16th grid."""
    from reawarp.generators.melody import MelodyEvent, midi_to_frequency

    if bpm <= 0 or duration_seconds <= 0:
        raise ValueError("bpm and duration_seconds must be positive")
    step_seconds = 60.0 / float(bpm) / 4.0
    result = []
    for instance in plan.instances:
        start_step = instance.start_bar * 16
        end_step = instance.end_bar * 16
        period = max(1, int(instance.phrase_steps))
        cursor = phrase_index = 0
        while start_step + cursor < end_step:
            for note in instance.notes:
                absolute_step = start_step + cursor + note.step
                if absolute_step >= end_step:
                    continue
                time_seconds = absolute_step * step_seconds
                if time_seconds >= duration_seconds:
                    continue
                duration = max(step_seconds * 0.35, note.duration_steps * step_seconds)
                duration = min(
                    duration,
                    duration_seconds - time_seconds,
                    (end_step - absolute_step) * step_seconds,
                )
                if duration <= 0:
                    continue
                result.append(
                    MelodyEvent(
                        step=absolute_step,
                        time=time_seconds,
                        frequency=midi_to_frequency(note.midi_note),
                        midi_note=note.midi_note,
                        duration=duration,
                        velocity=note.velocity,
                        pan=note.pan,
                        source_x=note.source_x,
                        source_y=note.source_y,
                        motif_id=instance.motif_id,
                        motif_transform=instance.operation,
                        phrase_index=phrase_index,
                    )
                )
            cursor += period
            phrase_index += 1
    return sorted(result, key=lambda event: (event.step, event.midi_note))


def build_motif_role_accents(
    plan: MotifPlan,
    *,
    bpm: float,
    duration_seconds: float,
) -> tuple[MotifAccent, ...]:
    """Derive quiet hat shadows and snare call/response answers from the motif."""
    if bpm <= 0:
        raise ValueError("bpm must be positive")
    step_seconds = 60.0 / float(bpm) / 4.0
    accents: list[MotifAccent] = []
    seen: set[tuple[str, int]] = set()
    for instance in plan.instances:
        if instance.function not in {"development", "contrast", "uplift"}:
            continue
        start_step = instance.start_bar * 16
        end_step = min(
            instance.end_bar * 16, int(math.ceil(duration_seconds / step_seconds))
        )
        period = max(1, instance.phrase_steps)
        cursor = 0
        while start_step + cursor < end_step:
            for index, note in enumerate(instance.notes):
                if index % 2 == 1:
                    step = start_step + cursor + note.step + 2
                    if step < end_step and ("hat", step) not in seen:
                        seen.add(("hat", step))
                        accents.append(
                            MotifAccent(
                                "hat",
                                step,
                                _clip(note.velocity * 0.22, 0.04, 0.24),
                                _clip(note.pan * 0.65, -0.45, 0.45),
                                "motif_shadow",
                                "motif_shadow",
                                instance.motif_id,
                                "shadow",
                            )
                        )
                if instance.operation == "call_response" and index % 2 == 0:
                    step = start_step + cursor + note.step + max(4, period // 2)
                    if step < end_step and ("snare", step) not in seen:
                        seen.add(("snare", step))
                        accents.append(
                            MotifAccent(
                                "snare",
                                step,
                                _clip(note.velocity * 0.19, 0.035, 0.20),
                                _clip(-note.pan * 0.5, -0.35, 0.35),
                                "motif_response",
                                "motif_response",
                                instance.motif_id,
                                "response",
                            )
                        )
            cursor += period
    return tuple(sorted(accents, key=lambda item: (item.step, item.role)))
