"""Standard MIDI 1.0 import/export through the optional Mido adapter."""

from __future__ import annotations

import json
import math
from bisect import bisect_right
import re
from collections import defaultdict, deque
from fractions import Fraction
from pathlib import Path
from typing import Any

from reawarp.score.attention import apply_attention_gesture_to_event
from reawarp.score.events import AutomationLane, AutomationPoint, MusicalEvent
from reawarp.score.model import Score
from reawarp.score.pitch import EqualTemperamentTuning, tuning_from_score
from reawarp.score.render import build_score_control_bus
from reawarp.score.time import (
    MeterMap, MeterPoint, TempoMap, TempoPoint, as_fraction,
)


def _mido():
    try:
        import mido
    except ImportError as exc:
        raise RuntimeError(
            'MIDI support is optional. Install it with: python -m pip install -e ".[midi]"'
        ) from exc
    return mido


def _to_tick(beat: Fraction, ppq: int) -> int:
    return max(0, int(math.floor(float(beat) * ppq + 0.5)))


def _automation_beat(score: Score, lane: AutomationLane, point: AutomationPoint) -> Fraction:
    if lane.time_basis == "beats":
        return point.at
    if lane.time_basis == "seconds":
        return score.seconds_to_beat(float(point.at))
    sample_rate = int(score.metadata.get("sample_rate", 0))
    if sample_rate <= 0:
        raise ValueError(
            f"automation lane {lane.target_id!r} uses frames but score metadata "
            "does not contain a positive sample_rate"
        )
    return score.seconds_to_beat(float(point.at) / sample_rate)


def _tempo_samples(score: Score, resolution: Fraction) -> list[tuple[Fraction, float]]:
    if resolution <= 0:
        raise ValueError("tempo_ramp_resolution must be positive")
    values: dict[Fraction, float] = {}
    points = score.tempo_map.points
    for index, point in enumerate(points):
        values[point.at_beats] = point.bpm
        if index + 1 >= len(points) or point.interpolation_to_next != "linear":
            continue
        following = points[index + 1]
        cursor = point.at_beats + resolution
        span = following.at_beats - point.at_beats
        while cursor < following.at_beats:
            amount = float((cursor - point.at_beats) / span)
            values[cursor] = point.bpm + (following.bpm - point.bpm) * amount
            cursor += resolution
    return sorted(values.items(), key=lambda item: item[0])


def _midi_compatible_text(value: Any) -> str:
    """Return a Latin-1-safe label for MIDI text meta events.

    Reawarp's complete Unicode title and event data are stored in ASCII-escaped
    JSON text events. Human-facing MIDI track names use replacement only for
    characters that the Standard MIDI text encoding cannot represent.
    """
    return str(value).encode("latin-1", errors="replace").decode("latin-1")


def _drum_note(event: MusicalEvent) -> int | None:
    lane = event.voice_id.lower()
    source_kind = str(event.parameters.get("source_kind", "")).lower()
    token = f"{lane} {source_kind}"
    if "kick" in token:
        return 36
    if "snare" in token or "clap" in token:
        return 38
    if "hat" in token or "cymbal" in token:
        return 42
    return None


def _midi_semitone_frequency(note: int) -> float:
    """Frequency of a standard MIDI 1.0 note number."""
    if isinstance(note, bool) or not 0 <= int(note) <= 127:
        raise ValueError("MIDI note number must be between 0 and 127")
    return 440.0 * (2.0 ** ((int(note) - 69) / 12.0))


def _event_frequency(event: MusicalEvent, score: Score) -> float | None:
    if event.pitch is not None:
        return tuning_from_score(score).frequency_for_pitch(event.pitch)
    if event.frequency_hz is not None:
        return float(event.frequency_hz)
    return None


_MIDI_NOTE_THRESHOLDS = tuple(
    440.0 * (2.0 ** ((note + 0.5 - 69.0) / 12.0))
    for note in range(127)
)


def _midi_note_from_frequency(frequency_hz: float) -> int:
    """Resolve Hz to the nearest standard MIDI semitone (ties round upward).

    Comparing against geometric midpoint frequencies avoids losing the side of
    a half-semitone boundary when a logarithm rounds adjacent float frequencies
    to the same semitone coordinate.
    """
    frequency = float(frequency_hz)
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("MIDI note frequency must be positive and finite")
    return bisect_right(_MIDI_NOTE_THRESHOLDS, frequency)


def _event_note(event: MusicalEvent, score: Score) -> int | None:
    frequency = _event_frequency(event, score)
    if frequency is None:
        return _drum_note(event)
    return _midi_note_from_frequency(frequency)


def _default_channel(event: MusicalEvent, voice_order: dict[str, int]) -> int:
    if event.kind in {"hit", "trigger"} and _drum_note(event) is not None:
        return 9
    index = voice_order[event.voice_id]
    return index if index < 9 else 10 + ((index - 9) % 6)


def score_to_midi(
        score: Score,
        path: str | Path,
        *,
        ticks_per_beat: int | None = None,
        tempo_ramp_resolution: str | Fraction = "1/4",
) -> Path:
    """Export notes, MIDI CC automation, tempo, and meter to a type-1 MIDI file.

    Fractional pitches are rounded to the nearest MIDI 1.0 note for playback.
    Exact pitch, frequency, event identity, and Reawarp metadata are embedded
    in text meta events so a Reawarp-to-Reawarp round trip remains lossless.
    M29 Focus/Recede gestures are resolved into MIDI note pitch, population and
    gate length while the canonical source events and gesture provenance remain
    recoverable when the file is imported back into Reawarp.
    Linear tempo ramps are approximated by discrete tempo events.
    """
    mido = _mido()
    ppq = int(ticks_per_beat or score.ppq)
    if not 24 <= ppq <= 32_767:
        raise ValueError("ticks_per_beat must be between 24 and 32767")
    resolution = as_fraction(tempo_ramp_resolution)
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    midi_file = mido.MidiFile(type=1, ticks_per_beat=ppq)

    conductor_items: list[tuple[int, int, int, Any]] = []
    conductor_items.append((
        0, -20, 0,
        mido.MetaMessage("track_name", name=_midi_compatible_text(score.title), time=0),
    ))
    gestures = score.metadata.get("m29_attention_gestures", ())
    gesture_export_enabled = bool(gestures)
    voices = sorted({event.voice_id for event in score.events})
    voice_order = {voice: index for index, voice in enumerate(voices)}
    gesture_controls = None
    if gesture_export_enabled:
        sample_rate = int(score.metadata.get("sample_rate", 48_000) or 48_000)
        gesture_controls = build_score_control_bus(score, sample_rate)
    export_rows: list[tuple[MusicalEvent, MusicalEvent, int, Fraction, int | None, float | None]] = []
    omitted_gesture_events: list[dict[str, Any]] = []
    pan_cc_events: list[dict[str, Any]] = []
    for source_event in score.events:
        rendered_event = (
            apply_attention_gesture_to_event(source_event, gestures)
            if gesture_export_enabled else source_event
        )
        if rendered_event is None:
            if _event_note(source_event, score) is not None:
                omitted_gesture_events.append(source_event.to_dict())
            continue
        note = _event_note(rendered_event, score)
        if note is None:
            continue
        midi_duration = rendered_event.duration_beats
        if (
            gesture_export_enabled
            and rendered_event.parameters.get("m29_attention_gesture_id")
            and rendered_event.kind == "note"
        ):
            midi_duration = as_fraction(str(
                rendered_event.parameters.get(
                    "gate_duration_beats", rendered_event.duration_beats
                )
            ))
            midi_duration = max(Fraction(1, 64), min(
                rendered_event.duration_beats, midi_duration
            ))
        pan_cc_value = None
        midi_width = None
        if rendered_event.parameters.get("m29_attention_gesture_id"):
            try:
                source_pan = float(rendered_event.parameters.get("pan", 0.0))
            except (TypeError, ValueError):
                source_pan = 0.0
            frame = gesture_controls.timeline.beat_to_frame(
                source_event.onset_beats
            ) if gesture_controls is not None else 0
            if (
                gesture_controls is not None
                and "spatial.pan" in gesture_controls.target_ids
            ):
                source_pan = gesture_controls.value_for_context(
                    "spatial.pan", frame,
                    event_id=source_event.event_id,
                    default_value=source_pan,
                )
            midi_pan = max(-1.0, min(1.0,
                source_pan * float(rendered_event.parameters.get("m29_pan_factor", 1.0))
                + float(rendered_event.parameters.get("m29_pan_offset", 0.0))
            ))
            source_width = 1.0
            if (
                gesture_controls is not None
                and "spatial.width" in gesture_controls.target_ids
            ):
                source_width = gesture_controls.value_for_context(
                    "spatial.width", frame,
                    event_id=source_event.event_id,
                    default_value=1.0,
                )
            midi_width = max(0.0, min(2.0,
                source_width * float(rendered_event.parameters.get(
                    "m29_spatial_width_factor", 1.0
                ))
            ))
            pan_cc_value = max(0, min(
                127, int(round((midi_pan + 1.0) * 63.5))
            ))
            channel = source_event.channel if source_event.channel is not None else _default_channel(
                source_event, voice_order
            )
            pan_cc_events.append({
                "voice_id": source_event.voice_id,
                "channel": channel,
                "tick": _to_tick(source_event.onset_beats, ppq),
                "control": 10,
                "value": pan_cc_value,
            })
        export_rows.append((
            source_event, rendered_event, note, midi_duration,
            pan_cc_value, midi_width,
        ))

    score_meta = {
        "title": score.title,
        "tuning": {
            "id": score.tuning_id,
            "reference_pitch": score.tuning_reference_pitch,
            "reference_frequency_hz": score.tuning_reference_frequency_hz,
            "divisions_per_period": score.tuning_divisions_per_period,
            "period_ratio": score.tuning_period_ratio,
        },
        "sonorities": list(score.sonorities),
        "sonority_plan": score.sonority_plan,
        "bass_plan": score.bass_plan,
        "orchestration_plan": score.orchestration_plan,
        "metadata": score.metadata,
    }
    if gesture_export_enabled:
        score_meta["m29_midi_render_export"] = {
            "schema_version": 1,
            "omitted_events": omitted_gesture_events,
            "pan_cc_events": pan_cc_events,
        }
    conductor_items.append((
        0, -10, 1,
        mido.MetaMessage(
            "text",
            text="REAWARP_SCORE:" + json.dumps(
                score_meta, ensure_ascii=True, separators=(",", ":"), allow_nan=False
            ),
            time=0,
        ),
    ))
    for index, (beat, bpm) in enumerate(_tempo_samples(score, resolution)):
        tempo = int(round(60_000_000.0 / bpm))
        conductor_items.append((
            _to_tick(beat, ppq), 0, index + 2,
            mido.MetaMessage("set_tempo", tempo=tempo, time=0),
        ))
    for index, point in enumerate(score.meter_map.points):
        conductor_items.append((
            _to_tick(point.at_beats, ppq), 1, index,
            mido.MetaMessage(
                "time_signature",
                numerator=point.numerator,
                denominator=point.denominator,
                time=0,
            ),
        ))

    def make_track(name: str, items: list[tuple[int, int, int, Any]]) -> None:
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=_midi_compatible_text(name), time=0))
        previous_tick = 0
        for tick, _priority, _sequence, message in sorted(
                items, key=lambda item: (item[0], item[1], item[2])
        ):
            message.time = max(0, tick - previous_tick)
            previous_tick = tick
            track.append(message)
        midi_file.tracks.append(track)

    make_track("CONDUCTOR", conductor_items)

    voice_items: dict[str, list[tuple[int, int, int, Any]]] = {
        voice: [] for voice in voices
    }
    sequence = 0
    for source_event, rendered_event, note, midi_duration, pan_cc_value, midi_width in export_rows:
        event = source_event
        channel = event.channel if event.channel is not None else _default_channel(
            event, voice_order
        )
        start_tick = _to_tick(event.onset_beats, ppq)
        length_tick = max(1, _to_tick(midi_duration, ppq))
        end_tick = start_tick + length_tick
        velocity = max(1, min(127, int(round(event.velocity * 127.0))))
        payload = event.to_dict()
        resolved_frequency = _event_frequency(event, score)
        payload.update({
            "midi_channel": channel,
            "midi_note": note,
            "reawarp_pitch_coordinate": event.pitch,
            "reawarp_resolved_frequency_hz": resolved_frequency,
            "reawarp_tuning_id": score.tuning_id,
            "reawarp_tuning_period_ratio": score.tuning_period_ratio,
        })
        if rendered_event.parameters.get("m29_attention_gesture_id"):
            payload["m29_midi_gesture_id"] = str(
                rendered_event.parameters["m29_attention_gesture_id"]
            )
            payload["m29_midi_action"] = str(
                rendered_event.parameters.get("m29_attention_action", "")
            )
            midi_pan = -1.0 + 2.0 * float(pan_cc_value) / 127.0
            payload["m29_midi_rendered"] = {
                "pitch": rendered_event.pitch,
                "frequency_hz": rendered_event.frequency_hz,
                "duration_beats": str(midi_duration),
                "articulation": rendered_event.articulation,
                "pan": midi_pan,
                "spatial_width_factor": midi_width,
            }
            sequence += 1
            voice_items[event.voice_id].append((
                start_tick, 0, sequence,
                mido.Message(
                    "control_change",
                    channel=channel,
                    control=10,
                    value=int(pan_cc_value),
                    time=0,
                ),
            ))
        sequence += 1
        voice_items[event.voice_id].append((
            start_tick, 1, sequence,
            mido.MetaMessage(
                "text",
                text="REAWARP_EVENT:" + json.dumps(
                    payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False
                ),
                time=0,
            ),
        ))
        sequence += 1
        voice_items[event.voice_id].append((
            start_tick, 2, sequence,
            mido.Message(
                "note_on", note=note, velocity=velocity, channel=channel, time=0
            ),
        ))
        sequence += 1
        voice_items[event.voice_id].append((
            end_tick, 0, sequence,
            mido.Message(
                "note_off", note=note, velocity=0, channel=channel, time=0
            ),
        ))

    for voice in voices:
        make_track(voice, voice_items[voice])

    automation_items: list[tuple[int, int, int, Any]] = []
    automation_items.append((
        0, -10, 0,
        mido.MetaMessage("track_name", name="AUTOMATION", time=0),
    ))
    sequence = 0
    cc_pattern = re.compile(r"^midi\.cc\.(\d+)\.(\d+)$")
    for lane in score.automation:
        payload = json.dumps(
            lane.to_dict(), ensure_ascii=True, separators=(",", ":"), allow_nan=False
        )
        sequence += 1
        automation_items.append((
            0, -5, sequence,
            mido.MetaMessage("text", text="REAWARP_AUTOMATION:" + payload, time=0),
        ))
        match = cc_pattern.match(lane.target_id)
        if not match:
            continue
        channel, controller = int(match.group(1)), int(match.group(2))
        if not 0 <= channel <= 15 or not 0 <= controller <= 127:
            raise ValueError(f"invalid MIDI CC target: {lane.target_id}")
        for point in lane.points:
            beat = _automation_beat(score, lane, point)
            tick = _to_tick(beat, ppq)
            if lane.minimum is not None and lane.maximum is not None:
                span = lane.maximum - lane.minimum
                normalized = (
                    (point.value - lane.minimum) / span if span else 0.0
                )
            else:
                normalized = point.value
            value = max(0, min(127, int(round(normalized * 127.0))))
            sequence += 1
            automation_items.append((
                tick, 0, sequence,
                mido.Message(
                    "control_change",
                    channel=channel,
                    control=controller,
                    value=value,
                    time=0,
                ),
            ))
    if len(automation_items) > 1:
        make_track("AUTOMATION", automation_items)

    midi_file.save(str(output))
    return output


def score_from_midi(path: str | Path) -> Score:
    """Import MIDI notes, CC curves, tempo, and meter into a Reawarp score."""
    mido = _mido()
    source = Path(path).expanduser()
    midi_file = mido.MidiFile(str(source))
    ppq = int(midi_file.ticks_per_beat)
    tempo_by_tick: dict[int, float] = {}
    meter_by_tick: dict[int, tuple[int, int]] = {}
    custom_score: dict[str, Any] = {}
    custom_events: dict[tuple[int, int, int], deque[dict[str, Any]]] = defaultdict(deque)
    custom_automation: list[AutomationLane] = []
    note_records: list[tuple[int, str, int, int, int, int, dict[str, Any] | None]] = []
    cc_points: dict[str, dict[Fraction, float]] = defaultdict(dict)
    m29_pan_cc_events: set[tuple[str, int, int, int, int]] = set()

    for track_index, track in enumerate(midi_file.tracks):
        absolute_tick = 0
        track_name = f"Track {track_index + 1}"
        track_messages: list[tuple[int, Any]] = []
        for message in track:
            absolute_tick += int(message.time)
            track_messages.append((absolute_tick, message))
            if message.type == "track_name":
                track_name = str(message.name)
        active_notes: dict[tuple[int, int], deque[tuple[int, int, dict[str, Any] | None]]] = defaultdict(deque)
        for tick, message in track_messages:
            if message.is_meta:
                if message.type == "set_tempo":
                    tempo_by_tick[tick] = 60_000_000.0 / float(message.tempo)
                elif message.type == "time_signature":
                    meter_by_tick[tick] = (int(message.numerator), int(message.denominator))
                elif message.type == "text":
                    text = str(message.text)
                    if text.startswith("REAWARP_SCORE:"):
                        try:
                            custom_score = json.loads(text[len("REAWARP_SCORE:"):])
                            export_record = custom_score.get("m29_midi_render_export", {})
                            if (
                                isinstance(export_record, dict)
                                and export_record.get("schema_version") == 1
                            ):
                                for item in export_record.get("pan_cc_events", []):
                                    try:
                                        m29_pan_cc_events.add((
                                            str(item["voice_id"]),
                                            int(item["channel"]),
                                            int(item["control"]),
                                            int(item["tick"]),
                                            int(item["value"]),
                                        ))
                                    except (KeyError, TypeError, ValueError):
                                        continue
                        except json.JSONDecodeError:
                            pass
                    elif text.startswith("REAWARP_EVENT:"):
                        try:
                            payload = json.loads(text[len("REAWARP_EVENT:"):])
                            key = (
                                int(payload["midi_channel"]),
                                int(payload["midi_note"]),
                                tick,
                            )
                            custom_events[key].append(payload)
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                            pass
                    elif text.startswith("REAWARP_AUTOMATION:"):
                        try:
                            payload = json.loads(text[len("REAWARP_AUTOMATION:"):])
                            custom_automation.append(AutomationLane.from_dict(payload))
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                            pass
                continue

            if message.type == "control_change":
                if (
                    track_name,
                    int(message.channel),
                    int(message.control),
                    int(tick),
                    int(message.value),
                ) in m29_pan_cc_events:
                    continue
                target = f"midi.cc.{int(message.channel)}.{int(message.control)}"
                cc_points[target][Fraction(tick, ppq)] = float(message.value) / 127.0
                continue

            if message.type == "note_on" and message.velocity > 0:
                key = (int(message.channel), int(message.note))
                payload_queue = custom_events.get((key[0], key[1], tick))
                payload = payload_queue.popleft() if payload_queue else None
                active_notes[key].append((tick, int(message.velocity), payload))
                continue

            if message.type in {"note_off", "note_on"} and (
                    message.type == "note_off" or message.velocity == 0
            ):
                key = (int(message.channel), int(message.note))
                if active_notes[key]:
                    start_tick, velocity, payload = active_notes[key].popleft()
                    note_records.append((
                        track_index, track_name, key[0], key[1],
                        start_tick, max(start_tick + 1, tick), {
                            "velocity": velocity,
                            "payload": payload,
                        },
                    ))

        track_end = sum(int(message.time) for message in track)
        for (channel, note), opened in active_notes.items():
            while opened:
                start_tick, velocity, payload = opened.popleft()
                note_records.append((
                    track_index, track_name, channel, note,
                    start_tick, max(start_tick + 1, track_end), {
                        "velocity": velocity,
                        "payload": payload,
                    },
                ))

    if 0 not in tempo_by_tick:
        tempo_by_tick[0] = 120.0
    tempo_map = TempoMap(tuple(
        TempoPoint(Fraction(tick, ppq), bpm, "step")
        for tick, bpm in sorted(tempo_by_tick.items())
    ))
    if 0 not in meter_by_tick:
        meter_by_tick[0] = (4, 4)
    meter_map = MeterMap(tuple(
        MeterPoint(Fraction(tick, ppq), numerator, denominator)
        for tick, (numerator, denominator) in sorted(meter_by_tick.items())
    ))

    tuning_data = custom_score.get("tuning", {}) if custom_score else {}
    tuning_id = str(tuning_data.get("id", "12tet"))
    reference_pitch = float(tuning_data.get("reference_pitch", 69.0))
    reference_hz = float(tuning_data.get("reference_frequency_hz", 440.0))
    divisions = int(tuning_data.get("divisions_per_period", 12))
    period_ratio = float(tuning_data.get("period_ratio", 2.0))
    tuning = EqualTemperamentTuning(
        divisions_per_period=divisions,
        period_ratio=period_ratio,
        reference_pitch=reference_pitch,
        reference_frequency_hz=reference_hz,
        identifier=tuning_id,
    )

    events: list[MusicalEvent] = []
    used_ids: set[str] = set()
    for record_index, (
            track_index, track_name, channel, note, start_tick, end_tick, details
    ) in enumerate(sorted(note_records, key=lambda item: (item[4], item[0], item[2], item[3]))):
        velocity = int(details["velocity"])
        payload = details["payload"]
        if payload is not None:
            original = dict(payload)
            m29_rendered = bool(original.get("m29_midi_gesture_id"))
            event_id = str(original.get("event_id", f"midi-event-{record_index:06d}"))
            if event_id in used_ids:
                event_id = f"{event_id}-{record_index}"
            used_ids.add(event_id)
            onset = (
                as_fraction(str(original.get("onset_beats", Fraction(start_tick, ppq))))
                if m29_rendered else Fraction(start_tick, ppq)
            )
            duration = (
                as_fraction(str(original.get(
                    "duration_beats", Fraction(end_tick - start_tick, ppq)
                )))
                if m29_rendered else Fraction(end_tick - start_tick, ppq)
            )
            events.append(MusicalEvent(
                event_id=event_id,
                voice_id=str(original.get("voice_id", track_name)),
                onset_beats=onset,
                duration_beats=duration,
                kind=str(original.get("kind", "note")),
                pitch=(
                    None if original.get("pitch") is None else float(original["pitch"])
                ),
                frequency_hz=(
                    None if original.get("frequency_hz") is None
                    else float(original["frequency_hz"])
                ),
                velocity=(
                    float(original.get("velocity", float(velocity) / 127.0))
                    if m29_rendered else float(velocity) / 127.0
                ),
                articulation=str(original.get("articulation", "default")),
                parameters=dict(original.get("parameters", {})),
                tags=tuple(original.get("tags", ())),
                source_id=original.get("source_id"),
                seed=original.get("seed"),
                channel=(
                    None if original.get("channel") is None else int(original["channel"])
                ) if m29_rendered else channel,
                tuning_id=str(original.get("tuning_id", tuning_id)),
            ))
        else:
            midi_frequency = _midi_semitone_frequency(note)
            events.append(MusicalEvent(
                event_id=f"midi-event-{record_index:06d}",
                voice_id=track_name,
                onset_beats=Fraction(start_tick, ppq),
                duration_beats=Fraction(end_tick - start_tick, ppq),
                kind="note",
                pitch=tuning.pitch_for_frequency(midi_frequency),
                frequency_hz=midi_frequency,
                velocity=float(velocity) / 127.0,
                channel=channel,
                tuning_id=tuning_id,
            ))

    midi_render_export = (
        custom_score.get("m29_midi_render_export", {}) if custom_score else {}
    )
    if (
        isinstance(midi_render_export, dict)
        and midi_render_export.get("schema_version") == 1
        and isinstance(midi_render_export.get("omitted_events", []), list)
    ):
        for raw_event in midi_render_export.get("omitted_events", []):
            if not isinstance(raw_event, dict):
                continue
            try:
                source_event = MusicalEvent.from_dict(raw_event)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if source_event.event_id in used_ids:
                continue
            used_ids.add(source_event.event_id)
            events.append(source_event)

    automation_by_target = {lane.target_id: lane for lane in custom_automation}
    for target, point_values in cc_points.items():
        if target in automation_by_target:
            continue
        automation_by_target[target] = AutomationLane(
            target_id=target,
            points=tuple(
                AutomationPoint(at, value)
                for at, value in sorted(point_values.items())
            ),
            unit="normalized",
            time_basis="beats",
            interpolation="step",
            minimum=0.0,
            maximum=1.0,
        )

    metadata = dict(custom_score.get("metadata", {})) if custom_score else {}
    metadata["midi_import"] = {
        "source_file": source.name,
        "source_type": int(midi_file.type),
        "source_ppq": ppq,
    }
    title = str(custom_score.get("title", source.stem)) if custom_score else source.stem
    return Score(
        title=title,
        ppq=ppq,
        tempo_map=tempo_map,
        meter_map=meter_map,
        events=tuple(events),
        automation=tuple(automation_by_target.values()),
        tuning_id=tuning_id,
        tuning_reference_pitch=reference_pitch,
        tuning_reference_frequency_hz=reference_hz,
        tuning_divisions_per_period=divisions,
        tuning_period_ratio=period_ratio,
        sonorities=tuple(custom_score.get("sonorities", ())),
        sonority_plan=custom_score.get("sonority_plan"),
        bass_plan=custom_score.get("bass_plan"),
        orchestration_plan=custom_score.get("orchestration_plan"),
        metadata=metadata,
    )
