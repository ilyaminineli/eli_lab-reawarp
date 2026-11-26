from __future__ import annotations

import json
from fractions import Fraction

import pytest

from reawarp.score import MusicalEvent, Score, apply_attention_gesture
from reawarp.score.attention import apply_attention_gesture_to_event


def _track_messages(track):
    absolute_tick = 0
    output = []
    for message in track:
        absolute_tick += int(message.time)
        output.append((absolute_tick, message))
    return output


def _reawarp_score_meta(midi):
    for track in midi.tracks:
        for message in track:
            if (
                message.is_meta and message.type == "text"
                and message.text.startswith("REAWARP_SCORE:")
            ):
                return json.loads(message.text[len("REAWARP_SCORE:"):])
    raise AssertionError("REAWARP_SCORE metadata was not written")


def test_m29_focus_midi_plays_transposed_bounded_note_and_roundtrips_source(tmp_path):
    mido = pytest.importorskip("mido")
    source = Score(events=(
        MusicalEvent(
            event_id="lead-focus",
            voice_id="lead",
            onset_beats=Fraction(1, 4),
            duration_beats=Fraction(1),
            kind="note",
            pitch=60,
            velocity=0.8,
            parameters={"pan": 0.6},
            tags=("motif",),
            source_id="phrase-a",
        ),
    ))
    focused = apply_attention_gesture(
        source,
        role="lead",
        start_beats=0,
        end_beats=2,
        action="focus",
        register_shift_semitones=12,
    )

    path = focused.export_midi(tmp_path / "m29-focus.mid")
    midi = mido.MidiFile(str(path))
    lead_track = next(
        track for track in midi.tracks
        if track and track[0].type == "track_name" and track[0].name == "lead"
    )
    messages = _track_messages(lead_track)
    note_on = next(
        (tick, msg) for tick, msg in messages
        if not msg.is_meta and msg.type == "note_on" and msg.velocity > 0
    )
    note_off = next(
        (tick, msg) for tick, msg in messages
        if not msg.is_meta and msg.type == "note_off"
    )
    pan = next(
        msg for _tick, msg in messages
        if not msg.is_meta and msg.type == "control_change" and msg.control == 10
    )
    assert note_on[1].note == 72
    assert note_off[0] - note_on[0] == 1008  # 1.05 beats at 960 PPQ
    assert pan.value == 81  # 0.6 × Focus's 0.45 pan factor

    event_payload = next(
        json.loads(msg.text[len("REAWARP_EVENT:"):])
        for _tick, msg in messages
        if msg.is_meta and msg.type == "text"
        and msg.text.startswith("REAWARP_EVENT:")
    )
    assert event_payload["pitch"] == 60
    assert event_payload["midi_note"] == 72
    assert event_payload["m29_midi_action"] == "focus"
    assert event_payload["m29_midi_rendered"]["pitch"] == 72
    assert event_payload["m29_midi_rendered"]["duration_beats"] == "21/20"

    restored = Score.from_midi(path)
    assert restored.events == source.events
    assert restored.metadata["m29_attention_gestures"] == (
        focused.metadata["m29_attention_gestures"]
    )


def test_m29_recede_midi_omits_same_events_and_restores_canonical_score(tmp_path):
    mido = pytest.importorskip("mido")
    source = Score(events=tuple(
        MusicalEvent(
            event_id=f"lead-{index:02d}",
            voice_id="lead",
            onset_beats=Fraction(index, 4),
            duration_beats=Fraction(1, 8),
            kind="note",
            pitch=60 + (index % 5),
            velocity=0.6,
            parameters={"pan": 0.0},
        )
        for index in range(40)
    ))
    receded = apply_attention_gesture(
        source,
        role="lead",
        start_beats=0,
        end_beats=12,
        action="recede",
    )
    gestures = receded.metadata["m29_attention_gestures"]
    expected = [
        apply_attention_gesture_to_event(event, gestures)
        for event in source.events
    ]
    expected_ids = {
        event.event_id for event in expected if event is not None
    }
    omitted_ids = {
        event.event_id for event in expected if event is None
    }
    assert 0 < len(omitted_ids) < len(source.events)

    path = receded.export_midi(tmp_path / "m29-recede.mid")
    midi = mido.MidiFile(str(path))
    note_on_payloads = [
        json.loads(message.text[len("REAWARP_EVENT:"):])
        for track in midi.tracks for message in track
        if message.is_meta and message.type == "text"
        and message.text.startswith("REAWARP_EVENT:")
    ]
    exported_ids = {item["event_id"] for item in note_on_payloads}
    assert exported_ids == expected_ids
    assert all(item["m29_midi_action"] == "recede" for item in note_on_payloads)

    source_extension = _reawarp_score_meta(midi)["m29_midi_render_export"]
    assert source_extension["schema_version"] == 1
    assert {
        item["event_id"] for item in source_extension["omitted_events"]
    } == omitted_ids

    restored = Score.from_midi(path)
    assert restored.events == source.events
    assert restored.metadata["m29_attention_gestures"] == gestures


def test_midi_without_m29_gestures_keeps_existing_event_timing_and_metadata(tmp_path):
    pytest.importorskip("mido")
    source = Score(events=(
        MusicalEvent(
            event_id="plain-note",
            voice_id="lead",
            onset_beats=Fraction(1, 2),
            duration_beats=Fraction(3, 4),
            kind="note",
            pitch=64,
            velocity=0.75,
        ),
    ))
    path = source.export_midi(tmp_path / "plain.mid")
    restored = Score.from_midi(path)
    assert restored.events[0].onset_beats == Fraction(1, 2)
    assert restored.events[0].duration_beats == Fraction(3, 4)
    assert "m29_midi_render_export" not in _reawarp_score_meta(
        __import__("mido").MidiFile(str(path))
    )
