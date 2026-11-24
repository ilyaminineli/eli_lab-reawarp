"""Canonical score adapters for existing deterministic composition planners."""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Iterable, Mapping, Sequence

from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.time import MeterMap, TempoMap


def _step_beats(step: int) -> Fraction:
    """Express a sixteenth-note grid position as an exact quarter-note beat."""
    if isinstance(step, bool) or int(step) != step or int(step) < 0:
        raise ValueError("step must be a non-negative integer")
    return Fraction(int(step), 4)


def _event_seed(seed_streams: Mapping[str, Any], stream_name: str | None) -> int | None:
    if not stream_name:
        return None
    value = seed_streams.get(stream_name)
    return int(value) if value is not None else None


def percussion_to_score_events(
    lanes: Mapping[str, Sequence[Any]],
    *,
    seed_streams: Mapping[str, Any] | None = None,
) -> tuple[MusicalEvent, ...]:
    """Convert planner percussion grid positions; never read legacy seconds."""
    streams = dict(seed_streams or {})
    result: list[MusicalEvent] = []
    index = 0
    for lane in sorted(lanes):
        for source in sorted(lanes[lane], key=lambda item: (int(item.step), str(item.kind or ""))):
            role = str(getattr(source, "lane", lane))
            kind = str(getattr(source, "kind", "") or "")
            result.append(MusicalEvent(
                event_id=f"perc-{index:07d}",
                voice_id=role,
                onset_beats=_step_beats(int(source.step)),
                duration_beats=Fraction(1, 4),
                kind="hit",
                velocity=float(source.velocity),
                parameters={
                    "pan": float(getattr(source, "pan", 0.0)),
                    "step": int(source.step),
                    "pattern_style": getattr(source, "pattern_style", None),
                    "motif_id": getattr(source, "motif_id", None),
                    "motif_relation": getattr(source, "motif_relation", None),
                    "source_kind": kind,
                    "planner": "percussion",
                },
                tags=("percussion", role, kind),
                source_id=getattr(source, "motif_id", None) or role,
                seed=_event_seed(streams, f"{role}_pattern"),
            ))
            index += 1
    return tuple(sorted(result, key=lambda event: (
        event.onset_beats, event.voice_id, event.event_id
    )))


def melody_to_score_events(
    events: Iterable[Any],
    *,
    bpm: float,
    seed: int | None = None,
    voice_id: str = 'melody',
) -> tuple[MusicalEvent, ...]:
    """Convert melody events; onset comes from the exact grid, duration is quantised to rational beats."""
    if bpm <= 0:
        raise ValueError("bpm must be positive")
    result: list[MusicalEvent] = []
    ordered = sorted(events, key=lambda item: (int(item.step), int(item.midi_note)))
    for index, source in enumerate(ordered):
        onset = _step_beats(int(source.step))
        raw_duration = Fraction(
            str(float(source.duration) * float(bpm) / 60.0)
        ).limit_denominator(15360)
        duration = max(Fraction(1, 64), raw_duration)
        result.append(MusicalEvent(
            event_id=f"melody-{index:07d}",
            voice_id=voice_id,
            onset_beats=onset,
            duration_beats=duration,
            kind="note",
            pitch=float(source.midi_note),
            frequency_hz=float(source.frequency),
            velocity=float(source.velocity),
            parameters={
                "pan": float(source.pan),
                "source_x": float(source.source_x),
                "source_y": float(source.source_y),
                "step": int(source.step),
                "motif_id": getattr(source, "motif_id", None),
                "motif_transform": getattr(source, "motif_transform", None),
                "phrase_index": getattr(source, "phrase_index", None),
                "synthesis_intent": "melody",
                "planner": "melody",
            },
            tags=("melody", "note"),
            source_id=getattr(source, "motif_id", None),
            seed=seed,
        ))
    return tuple(result)


def score_from_planner_events(
    *,
    percussion: Mapping[str, Sequence[Any]] | None = None,
    melody: Iterable[Any] = (),
    bpm: float = 120.0,
    seed_streams: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Score:
    """Assemble a score before audio rendering from planner-native grid decisions."""
    if bpm <= 0:
        raise ValueError("bpm must be positive")
    streams = dict(seed_streams or {})
    drum_events = percussion_to_score_events(percussion or {}, seed_streams=streams)
    melody_events = melody_to_score_events(
        melody, bpm=bpm, seed=_event_seed(streams, 'melody_pattern')
    )
    merged = tuple(sorted(
        (*drum_events, *melody_events),
        key=lambda event: (event.onset_beats, event.voice_id, event.event_id),
    ))
    return Score(
        title="Reawarp planner score",
        tempo_map=TempoMap.constant(float(bpm)),
        meter_map=MeterMap(),
        events=merged,
        metadata={
            "score_origin": "canonical_planner_events",
            "planner_event_timebase": "sixteenth_grid_as_rational_beats",
            "seed_streams": streams,
            **dict(metadata or {}),
        },
    )


def score_to_legacy_grid_events(score: Score) -> dict[str, list[dict[str, Any]]]:
    """Compatibility projection for old consumers at a constant tempo map."""
    tempos = score.tempo_map.points
    if len(tempos) != 1 or tempos[0].interpolation_to_next != "step":
        raise ValueError("legacy projection requires a single constant tempo map")
    result: dict[str, list[dict[str, Any]]] = {}
    for event in score.events:
        step = event.onset_beats * 4
        if step.denominator != 1:
            raise ValueError("legacy grid projection cannot represent non-sixteenth positions")
        result.setdefault(event.voice_id, []).append({
            "step": int(step),
            "time": float(score.tempo_map.beat_to_seconds(event.onset_beats)),
            "duration_beats": str(event.duration_beats),
            "velocity": event.velocity,
            "pan": float(event.parameters.get("pan", 0.0)),
            "kind": event.parameters.get("source_kind", event.kind),
            "pattern_style": event.parameters.get("pattern_style"),
            "motif_id": event.parameters.get("motif_id"),
            "motif_relation": event.parameters.get("motif_relation"),
            "midi_note": event.pitch,
            "frequency": event.frequency_hz,
        })
    for records in result.values():
        records.sort(key=lambda item: (item["step"], str(item["kind"] or "")))
    return result
