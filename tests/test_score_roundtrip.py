from fractions import Fraction

import pytest

from reawarp.score import (
    AutomationLane,
    AutomationPoint,
    MeterMap,
    MeterPoint,
    MusicalEvent,
    Score,
    TempoMap,
    TempoPoint,
)


def _fixture_score():
    return Score(
        title="M14 interchange fixture",
        ppq=960,
        tempo_map=TempoMap((
            TempoPoint(Fraction(0), 120.0, "step"),
            TempoPoint(Fraction(8), 100.0, "step"),
        )),
        meter_map=MeterMap((
            MeterPoint(Fraction(0), 4, 4),
            MeterPoint(Fraction(16), 7, 8),
        )),
        events=(
            MusicalEvent(
                event_id="kick-0001",
                voice_id="kick",
                onset_beats=Fraction(0),
                duration_beats=Fraction(1, 8),
                kind="hit",
                velocity=0.62,
                parameters={"source_kind": "kick", "source_variant": "anchor"},
                tags=("percussion", "anchor"),
                seed=91,
            ),
            MusicalEvent(
                event_id="lead-0001",
                voice_id="lead",
                onset_beats=Fraction(1, 2),
                duration_beats=Fraction(3, 4),
                kind="note",
                pitch=60.375,
                frequency_hz=261.625565,
                velocity=0.73,
                parameters={"oscillator": "subtractive", "cutoff_hz": 2400.0},
                tags=("lead", "motif"),
                source_id="motif-a",
                channel=1,
            ),
        ),
        automation=(
            AutomationLane(
                target_id="midi.cc.0.74",
                points=(
                    AutomationPoint(Fraction(0), 0.0),
                    AutomationPoint(Fraction(3, 2), 0.75),
                ),
                unit="normalized",
                time_basis="beats",
                interpolation="linear",
                minimum=0.0,
                maximum=1.0,
            ),
            AutomationLane(
                target_id="synth.cutoff",
                points=(
                    AutomationPoint(Fraction(0), 220.0),
                    AutomationPoint(Fraction(4), 3200.0),
                ),
                unit="Hz",
                time_basis="beats",
                interpolation="cubic",
                minimum=20.0,
                maximum=18_000.0,
            ),
        ),
        tuning_id="12tet",
        tuning_reference_pitch=69.0,
        tuning_reference_frequency_hz=440.0,
        tuning_divisions_per_period=12,
        metadata={"fixture": "m14", "sample_rate": 48_000},
    )


def test_score_json_save_load_preserves_rational_time_and_metadata(tmp_path):
    score = _fixture_score()
    destination = score.save(tmp_path / "score.json")
    restored = Score.load(destination)

    assert restored.to_dict() == score.to_dict()
    assert restored.events[1].onset_beats == Fraction(1, 2)
    assert restored.events[1].duration_beats == Fraction(3, 4)
    assert restored.automation == score.automation


def test_midi_round_trip_preserves_reawarp_events_maps_and_automation(tmp_path):
    pytest.importorskip("mido")
    score = _fixture_score()
    midi_path = score.export_midi(tmp_path / "score.mid")
    restored = Score.from_midi(midi_path)

    assert restored.title == score.title
    assert restored.ppq == score.ppq
    assert restored.tempo_map.to_dict() == score.tempo_map.to_dict()
    assert restored.meter_map.to_dict() == score.meter_map.to_dict()
    assert restored.automation == score.automation
    assert restored.metadata["fixture"] == "m14"
    assert restored.metadata["sample_rate"] == 48_000
    assert "midi_import" in restored.metadata

    original_events = {event.event_id: event for event in score.events}
    restored_events = {event.event_id: event for event in restored.events}
    assert set(restored_events) == set(original_events)
    for event_id, original in original_events.items():
        actual = restored_events[event_id]
        assert actual.voice_id == original.voice_id
        assert actual.onset_beats == original.onset_beats
        assert actual.duration_beats == original.duration_beats
        assert actual.kind == original.kind
        assert actual.pitch == original.pitch
        assert actual.frequency_hz == original.frequency_hz
        assert actual.parameters == original.parameters
        assert actual.tags == original.tags
        assert actual.source_id == original.source_id
        assert actual.channel == (original.channel if original.channel is not None else 9)
        assert actual.velocity == pytest.approx(round(original.velocity * 127) / 127)
