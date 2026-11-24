from fractions import Fraction

import pytest

mido = pytest.importorskip("mido")

from reawarp import AutomationLane, AutomationPoint, MusicalEvent, Score
from reawarp.score.time import MeterMap, MeterPoint, TempoMap, TempoPoint


def test_reawarp_midi_round_trip_preserves_microtonal_pitch_and_score_metadata(tmp_path):
    score = Score(
        title="MIDI Interchange",
        tempo_map=TempoMap((
            TempoPoint(Fraction(0), 70, "linear"),
            TempoPoint(Fraction(4), 130, "step"),
        )),
        meter_map=MeterMap((
            MeterPoint(Fraction(0), 4, 4),
            MeterPoint(Fraction(4), 7, 8),
        )),
        events=(
            MusicalEvent(
                "micro-note", "glass", Fraction(1, 3), Fraction(2, 3),
                pitch=60.5, frequency_hz=271.4, velocity=0.73,
                tags=("microtonal",), parameters={"colour": "silver"},
            ),
            MusicalEvent(
                "kick-hit", "kick", Fraction(0), Fraction(1, 16),
                kind="hit", velocity=0.9,
            ),
        ),
        automation=(
            AutomationLane(
                "midi.cc.0.1",
                (AutomationPoint(Fraction(0), 0.0), AutomationPoint(Fraction(2), 1.0)),
                unit="normalized", interpolation="linear", minimum=0.0, maximum=1.0,
            ),
            AutomationLane(
                "synth.filter.cutoff",
                (AutomationPoint(Fraction(0), 120.0), AutomationPoint(Fraction(3), 900.0)),
                unit="Hz", interpolation="exponential",
            ),
        ),
        metadata={"root_seed": 2026, "sample_rate": 48_000},
    )
    midi_path = score.export_midi(tmp_path / "interchange.mid")
    midi_file = mido.MidiFile(str(midi_path))
    assert midi_file.type == 1
    assert midi_file.ticks_per_beat == score.ppq
    assert any(msg.type == "set_tempo" for track in midi_file.tracks for msg in track)

    restored = Score.from_midi(midi_path)
    note = next(event for event in restored.events if event.event_id == "micro-note")
    assert note.pitch == pytest.approx(60.5)
    assert note.frequency_hz == pytest.approx(271.4)
    assert note.onset_beats == Fraction(1, 3)
    assert note.duration_beats == Fraction(2, 3)
    assert note.tags == ("microtonal",)
    assert note.parameters["colour"] == "silver"
    assert restored.title == score.title
    assert restored.metadata["root_seed"] == 2026
    assert restored.meter_map.points == score.meter_map.points
    assert any(lane.target_id == "midi.cc.0.1" for lane in restored.automation)
    assert any(lane.target_id == "synth.filter.cutoff" for lane in restored.automation)
    # MIDI 1.0 stores a sampled step approximation of a continuous tempo ramp.
    assert len(restored.tempo_map.points) > len(score.tempo_map.points)


def test_import_plain_midi_notes_cc_tempo_and_meter(tmp_path):
    midi_file = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name="Conductor", time=0))
    conductor.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=3, denominator=4, time=0))
    midi_file.tracks.append(conductor)

    voice = mido.MidiTrack()
    voice.append(mido.MetaMessage("track_name", name="Lead", time=0))
    voice.append(mido.Message("note_on", note=69, velocity=100, channel=0, time=240))
    voice.append(mido.Message("control_change", control=1, value=64, channel=0, time=0))
    voice.append(mido.Message("note_off", note=69, velocity=0, channel=0, time=240))
    midi_file.tracks.append(voice)

    path = tmp_path / "plain.mid"
    midi_file.save(path)
    score = Score.from_midi(path)
    assert score.ppq == 480
    assert score.title == "plain"
    assert score.events[0].voice_id == "Lead"
    assert score.events[0].onset_beats == Fraction(1, 2)
    assert score.events[0].duration_beats == Fraction(1, 2)
    assert score.events[0].pitch == pytest.approx(69.0)
    assert score.events[0].frequency_hz == pytest.approx(440.0)
    assert score.meter_map.points[0].numerator == 3
    lane = next(item for item in score.automation if item.target_id == "midi.cc.0.1")
    assert lane.points[0].value == pytest.approx(64 / 127)


def test_midi_import_closes_unmatched_note_at_track_end(tmp_path):
    midi_file = mido.MidiFile(type=0, ticks_per_beat=96)
    track = mido.MidiTrack()
    track.append(mido.Message("note_on", note=60, velocity=90, time=0))
    track.append(mido.MetaMessage("end_of_track", time=48))
    midi_file.tracks.append(track)
    path = tmp_path / "open_note.mid"
    midi_file.save(path)

    score = Score.from_midi(path)
    assert len(score.events) == 1
    assert score.events[0].duration_beats == Fraction(1, 2)
