from fractions import Fraction
import json
import math

import pytest

from reawarp.composition.motifs import (
    MOTIF_IDENTITY_DIMENSIONS,
    Motif,
    MotifInstance,
    MotifNote,
    MotifPlan,
    motif_identity_contract,
    transform_motif_with_identity,
)
from reawarp.score import (
    MeterMap,
    MeterPoint,
    MotifResolutionPlan,
    MusicalEvent,
    Score,
    Sonority,
    TempoMap,
    resolve_motif_plan_to_score,
    tuning_from_score,
)


def _motif_plan():
    anchor = Motif(
        motif_id="motif-m19-5",
        role="melody",
        source_section="Anchor",
        source_start_bar=0,
        phrase_bars=1,
        pitch_center=60,
        notes=(
            MotifNote(
                0, 60, 2.0, 0.9, -0.1,
                articulation="legato", timbre="soft_sine",
            ),
            MotifNote(
                4, 64, 1.5, 0.72, 0.2,
                articulation="staccato", timbre="metallic_pluck",
            ),
        ),
    )
    repeat_contract = motif_identity_contract("repeat")
    bridge_contract = motif_identity_contract("repeat")
    return MotifPlan(
        anchor=anchor,
        instances=(
            MotifInstance(
                anchor.motif_id, 0, "Anchor", "establishment",
                0, 2, "repeat", ("repeat",), 16, anchor.notes,
                repeat_contract["preserved"], repeat_contract["changed"],
            ),
            MotifInstance(
                anchor.motif_id, 1, "Bridge", "development",
                2, 4, "repeat", ("repeat",), 16, anchor.notes,
                bridge_contract["preserved"], bridge_contract["changed"],
            ),
        ),
    )


def test_each_existing_motif_operation_declares_all_six_identity_dimensions():
    motif = _motif_plan().anchor
    for operation in (
        "repeat", "return", "displacement", "fragmentation",
        "augmentation", "diminution", "inversion", "retrograde",
        "rhythmic_shadow", "call_response", "dissolve",
    ):
        transformed, phrase_steps, contract = transform_motif_with_identity(
            motif, operation
        )
        assert transformed
        assert phrase_steps > 0
        assert set(contract["preserved"]) | set(contract["changed"]) == set(
            MOTIF_IDENTITY_DIMENSIONS
        )
        assert not (set(contract["preserved"]) & set(contract["changed"]))
        assert all(note.articulation for note in transformed)
        assert all(note.timbre for note in transformed)


def test_motif_to_sonority_binding_resolves_score_tuning_and_preserves_identity():
    score = Score(
        title="M19.5 tuning test",
        tempo_map=TempoMap.constant(120),
        meter_map=MeterMap((
            MeterPoint(Fraction(0), 4, 4),
            MeterPoint(Fraction(8), 3, 4),
        )),
        tuning_id="19edo",
        tuning_reference_pitch=69,
        tuning_reference_frequency_hz=440,
        tuning_divisions_per_period=19,
        tuning_period_ratio=2.0,
        metadata={"motif_plan": _motif_plan().to_dict()},
    )
    sonority = Sonority(
        "bridge-field", "8", "2",
        pitches=(42.0, 48.0, 55.0),
        bass_pitch=42.0,
    )
    resolved = resolve_motif_plan_to_score(
        _motif_plan(),
        score,
        sonorities_by_section={"Bridge": sonority},
    )
    tuning = tuning_from_score(score)
    assert resolved.tuning_id == "19edo"
    assert resolved.tuning_divisions_per_period == 19
    assert resolved.tuning_period_ratio == 2.0

    anchor_record, bridge_record = resolved.records
    assert anchor_record.preserved_dimensions == MOTIF_IDENTITY_DIMENSIONS
    assert bridge_record.target_sonority_id == "bridge-field"
    assert bridge_record.pitch_offset != 0
    assert bridge_record.preserved_dimensions == (
        "contour", "interval_profile", "rhythm", "articulation", "timbre",
    )
    assert bridge_record.changed_dimensions == ("register",)

    anchor_events = [item for item in resolved.events
                     if item.parameters["section_name"] == "Anchor"]
    bridge_events = [item for item in resolved.events
                     if item.parameters["section_name"] == "Bridge"]
    assert len(anchor_events) == 4
    assert len(bridge_events) == 4
    assert all(item.pitch is not None and item.frequency_hz is not None
               for item in resolved.events)
    assert all(
        item.frequency_hz == pytest.approx(tuning.frequency_for_pitch(item.pitch))
        for item in resolved.events
    )
    assert bridge_events[0].pitch == pytest.approx(42.0)
    assert bridge_events[0].articulation == "legato"
    assert bridge_events[0].parameters["timbre"] == "soft_sine"
    assert bridge_events[0].parameters["target_sonority_id"] == "bridge-field"
    assert bridge_events[0].onset_beats == Fraction(8)
    assert bridge_events[-1].onset_beats == Fraction(13)


def test_resolved_motif_plan_attaches_to_score_and_round_trips(tmp_path):
    score = Score(
        title="M19.5 persistence",
        meter_map=MeterMap((
            MeterPoint(Fraction(0), 4, 4),
            MeterPoint(Fraction(8), 3, 4),
        )),
        tuning_id="13edt",
        tuning_reference_pitch=0,
        tuning_reference_frequency_hz=100,
        tuning_divisions_per_period=13,
        tuning_period_ratio=3.0,
        metadata={"motif_plan": _motif_plan().to_dict()},
    )
    resolved = resolve_motif_plan_to_score(_motif_plan(), score)
    attached = resolved.attach_to_score(score)
    destination = attached.save(tmp_path / "motif-score.json")
    restored = Score.load(destination)
    restored_plan = MotifResolutionPlan.from_score(restored)
    assert restored_plan == resolved
    restored_motif_plan = MotifPlan.from_dict(restored.metadata["motif_plan"])
    assert restored_motif_plan == _motif_plan()
    assert restored.metadata["motif_plan"] == _motif_plan().to_dict()
    assert restored.metadata["motif_resolution"]["tuning"]["period_ratio"] == 3.0
    assert len([event for event in restored.events
                if event.parameters.get("planner") == "m19.5_motif"]) == len(resolved.events)
    assert restored.duration_beats == max(event.end_beats for event in resolved.events)


def test_score_tuning_period_ratio_is_backward_compatible_and_serializable():
    legacy = Score.from_dict({
        "format": "eli_lab_reawarp_score",
        "schema_version": 1,
        "events": [],
        "automation": [],
        "tuning": {"id": "legacy", "divisions_per_period": 12},
    })
    assert legacy.tuning_period_ratio == 2.0

    tritave = Score(
        tuning_id="13edt",
        tuning_reference_pitch=0,
        tuning_reference_frequency_hz=100,
        tuning_divisions_per_period=13,
        tuning_period_ratio=3.0,
    )
    restored = Score.from_dict(tritave.to_dict())
    assert restored.tuning_period_ratio == 3.0
    assert tuning_from_score(restored).frequency_for_pitch(13) == pytest.approx(300)


def test_midi_note_numbers_are_frequency_based_and_exact_reawarp_values_survive(tmp_path):
    mido = pytest.importorskip("mido")
    score = Score(
        title="Tritave MIDI export",
        tuning_id="13edt",
        tuning_reference_pitch=0,
        tuning_reference_frequency_hz=100,
        tuning_divisions_per_period=13,
        tuning_period_ratio=3.0,
        events=(
            MusicalEvent(
                event_id="micro-note",
                voice_id="micro-lead",
                onset_beats=Fraction(1, 2),
                duration_beats=Fraction(3, 4),
                kind="note",
                pitch=6.5,
                tuning_id="13edt",
            ),
        ),
    )
    expected_frequency = 100.0 * (3.0 ** (6.5 / 13.0))
    expected_float_note = 69.0 + 12.0 * math.log2(expected_frequency / 440.0)
    expected_midi_note = int(math.floor(expected_float_note + 0.5))

    midi_path = score.export_midi(tmp_path / "tritave.mid")
    midi = mido.MidiFile(str(midi_path))
    note_ons = [
        message for track in midi.tracks for message in track
        if not message.is_meta and message.type == "note_on" and message.velocity > 0
    ]
    assert len(note_ons) == 1
    assert note_ons[0].note == expected_midi_note

    event_payloads = [
        json.loads(message.text[len("REAWARP_EVENT:"):])
        for track in midi.tracks for message in track
        if message.is_meta and message.type == "text"
        and message.text.startswith("REAWARP_EVENT:")
    ]
    assert event_payloads[0]["pitch"] == 6.5
    assert event_payloads[0]["frequency_hz"] is None
    assert event_payloads[0]["reawarp_pitch_coordinate"] == 6.5
    assert event_payloads[0]["reawarp_resolved_frequency_hz"] == pytest.approx(
        expected_frequency
    )
    assert event_payloads[0]["reawarp_tuning_period_ratio"] == 3.0

    restored = Score.from_midi(midi_path)
    event = restored.events[0]
    assert event.pitch == 6.5
    assert event.frequency_hz is None
    assert restored.tuning_period_ratio == 3.0
    assert tuning_from_score(restored).frequency_for_pitch(event.pitch) == pytest.approx(
        expected_frequency
    )


def test_generic_midi_import_maps_standard_semitones_into_score_tuning(tmp_path):
    mido = pytest.importorskip("mido")
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="external lead", time=0))
    track.append(mido.MetaMessage(
        "text",
        text="REAWARP_SCORE:" + json.dumps({
            "title": "External tritave MIDI",
            "tuning": {
                "id": "13edt", "reference_pitch": 0,
                "reference_frequency_hz": 100, "divisions_per_period": 13,
                "period_ratio": 3.0,
            },
            "metadata": {},
        }),
        time=0,
    ))
    track.append(mido.Message("note_on", note=60, velocity=90, channel=0, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=480))
    path = tmp_path / "external.mid"
    midi.save(str(path))

    imported = Score.from_midi(path)
    event = imported.events[0]
    midi_frequency = 440.0 * (2.0 ** ((60 - 69) / 12.0))
    tuning = tuning_from_score(imported)
    assert event.frequency_hz == pytest.approx(midi_frequency)
    assert event.pitch == pytest.approx(tuning.pitch_for_frequency(midi_frequency))
    assert event.pitch != pytest.approx(60.0)
    assert tuning.frequency_for_pitch(event.pitch) == pytest.approx(midi_frequency)

def test_midi_note_rounding_is_stable_on_both_sides_of_every_semitone_midpoint():
    from reawarp.score.midi import _midi_note_from_frequency

    for lower_note in range(127):
        midpoint_hz = 440.0 * (2.0 ** ((lower_note + 0.5 - 69.0) / 12.0))
        just_below = math.nextafter(midpoint_hz, 0.0)
        just_above = math.nextafter(midpoint_hz, math.inf)
        assert _midi_note_from_frequency(just_below) == lower_note
        assert _midi_note_from_frequency(midpoint_hz) == lower_note + 1
        assert _midi_note_from_frequency(just_above) == lower_note + 1

    assert _midi_note_from_frequency(1e-200) == 0
    assert _midi_note_from_frequency(1e200) == 127
    with pytest.raises(ValueError, match="positive and finite"):
        _midi_note_from_frequency(0.0)
