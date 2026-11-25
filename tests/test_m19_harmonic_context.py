from fractions import Fraction
import math

import pytest

from reawarp.score import (
    EqualTemperamentTuning,
    Pitch,
    PitchField,
    Score,
    Sonority,
    VoiceLeadingWeights,
    assign_voice_leading,
)


def test_equal_temperament_and_non_octave_period_tuning_round_trip():
    twelve = EqualTemperamentTuning()
    assert twelve.frequency_for_pitch(69) == pytest.approx(440.0)
    assert twelve.frequency_for_pitch(81) == pytest.approx(880.0)
    assert twelve.pitch_for_frequency(220.0) == pytest.approx(57.0)

    nineteen = EqualTemperamentTuning(
        divisions_per_period=19,
        period_ratio=2.0,
        reference_pitch=0.0,
        reference_frequency_hz=100.0,
        identifier="19edo",
    )
    assert nineteen.frequency_for_pitch(19) == pytest.approx(200.0)
    assert nineteen.pitch_for_frequency(200.0) == pytest.approx(19.0)

    tritave = EqualTemperamentTuning(
        divisions_per_period=13,
        period_ratio=3.0,
        reference_pitch=0.0,
        reference_frequency_hz=100.0,
        identifier="13edt",
    )
    assert tritave.frequency_for_pitch(13) == pytest.approx(300.0)
    assert tritave.pitch_for_frequency(300.0) == pytest.approx(13.0)


def test_pitch_value_and_frequency_conversion_retains_tuning_identity():
    tuning = EqualTemperamentTuning(
        divisions_per_period=19, reference_pitch=0, reference_frequency_hz=100,
        identifier="19edo",
    )
    pitch = Pitch.from_value(7.5, tuning)
    restored = Pitch.from_frequency(pitch.frequency_hz, tuning)
    assert restored.value == pytest.approx(7.5)
    assert restored.tuning_id == "19edo"


def test_pitch_field_separates_hard_vocabulary_from_soft_weights():
    tuning = EqualTemperamentTuning()
    soft = PitchField(
        mode="collection",
        pitch_collection=(0, 2, 4, 5, 7, 9, 11),
        stability_weights={"60": 1.0},
        tension_weights={"61": 0.7},
        hard_constraint=False,
    )
    assert soft.evaluate(61, tuning).allowed is True
    assert soft.evaluate(60, tuning).stability == pytest.approx(1.0)
    assert soft.evaluate(61, tuning).tension == pytest.approx(0.7)

    hard = PitchField(
        mode="collection",
        pitch_collection=(0, 2, 4, 5, 7, 9, 11),
        hard_constraint=True,
        minimum_pitch=48,
        maximum_pitch=84,
    )
    candidates = hard.candidates((60, 61, 62, 90), tuning)
    assert tuple(item.pitch for item in candidates) == (60.0, 62.0)


def test_pitch_field_accepts_ambiguous_and_uncentred_contexts():
    field = PitchField.from_score_context({
        "mode": "ambiguous",
        "pitch_collection": [0, 1, 6, 7],
        "hard_constraint": True,
    })
    tuning = EqualTemperamentTuning()
    assert field.centre_pitch is None
    assert field.evaluate(60, tuning).allowed is True
    assert field.evaluate(62, tuning).allowed is False


def test_sonorities_and_optional_context_round_trip_in_score():
    sonority = Sonority(
        sonority_id="spectral-a",
        onset_beats="3/2",
        duration_beats="2",
        pitches=(48.0, 55.25, 63.5, 70.0),
        bass_pitch=36.0,
        tension=0.8,
        transform="spectral_derive",
    )
    score = Score(
        title="M19 context test",
        tuning_id="19edo",
        tuning_reference_pitch=0.0,
        tuning_reference_frequency_hz=100.0,
        tuning_divisions_per_period=19,
        harmonic_context={
            "mode": "spectral",
            "centre_pitch": 48.0,
            "pitch_collection": [0.0, 7.0, 12.5],
            "allowed_intervals": [0.0, 7.0, 12.5],
            "stability_weights": {"48": 1.0},
            "tension_weights": {"63.5": 0.4},
            "hard_constraint": False,
        },
        sonorities=(sonority.to_score_record(),),
    )
    restored = Score.from_dict(score.to_dict())
    assert restored.to_dict() == score.to_dict()
    assert restored.sonorities[0]["onset_beats"] == "3/2"


def test_legacy_score_has_no_harmonic_context_by_default():
    score = Score.from_dict({
        "format": "eli_lab_reawarp_score",
        "schema_version": 1,
        "events": [],
        "automation": [],
    })
    assert score.harmonic_context is None
    assert score.sonorities == ()


@pytest.mark.parametrize("context", [
    {"mode": "made_up"},
    {"mode": "collection", "pitch_collection": [0, math.inf]},
    {"mode": "spectral", "stability_weights": {"x": math.nan}},
])
def test_harmonic_context_rejects_invalid_records(context):
    with pytest.raises(ValueError):
        Score(harmonic_context=context)


def test_score_rejects_duplicate_or_invalid_sonorities():
    first = Sonority("one", "0", "1", (60.0,)).to_score_record()
    with pytest.raises(ValueError, match="unique"):
        Score(sonorities=(first, first))
    with pytest.raises(ValueError):
        Sonority("bad", "-1", "1", (60.0,))
    with pytest.raises(ValueError):
        Sonority("bad2", "0", "0", (60.0,))


def test_voice_leading_prefers_common_tones_and_is_deterministic():
    weights = VoiceLeadingWeights(
        motion=1.0, leap=0.0, common_tone_bonus=2.0,
        crossing=0.0,
    )
    first = assign_voice_leading((60, 64, 67), (62, 64, 69), weights=weights)
    second = assign_voice_leading((60, 64, 67), (62, 64, 69), weights=weights)
    assert first == second
    assert first.assignments[1][1] == 1
    assert dict(first.cost_components)["common_tone"] == pytest.approx(-2.0)


def test_voice_leading_hard_constraints_and_order_preservation():
    with pytest.raises(ValueError, match="hard constraints"):
        assign_voice_leading((48, 60), (72, 84), maximum_leap=12)

    no_cross = assign_voice_leading(
        (60, 67), (72, 55),
        allow_crossing=False,
        weights=VoiceLeadingWeights(crossing=10),
    )
    assert tuple(item[1] for item in no_cross.assignments) == (1, 0)
    assert no_cross.crossed_pairs == ()

    crossed = assign_voice_leading(
        (60, 67), (72, 55),
        allow_crossing=True,
        weights=VoiceLeadingWeights(
            motion=0.0, leap=0.0, common_tone_bonus=0.0, crossing=0.0,
        ),
    )
    assert tuple(item[1] for item in crossed.assignments) == (0, 1)
    assert crossed.crossed_pairs == ((0, 1),)


def test_voice_leading_rejects_unsupported_voice_counts():
    with pytest.raises(ValueError, match="equal"):
        assign_voice_leading((60, 64), (62,))
    with pytest.raises(ValueError, match="eight"):
        assign_voice_leading(range(9), range(9))

def test_modal_and_intervallic_pitch_fields_are_explicit_and_round_trip():
    tuning = EqualTemperamentTuning()
    modal = PitchField(
        mode="modal",
        pitch_collection=(0, 2, 3, 5, 7, 9, 10),
        hard_constraint=True,
    )
    assert modal.evaluate(62, tuning).allowed is True
    assert modal.evaluate(64, tuning).allowed is False

    intervallic = PitchField(
        mode="intervallic",
        centre_pitch=60.0,
        allowed_intervals=(0.0, 3.5, 7.0),
        hard_constraint=True,
    )
    assert intervallic.evaluate(63.5, tuning).allowed is True
    assert intervallic.evaluate(75.0, tuning).allowed is True
    assert intervallic.evaluate(64.0, tuning).allowed is False

    with pytest.raises(ValueError, match="requires centre_pitch and allowed_intervals"):
        PitchField(mode="intervallic", allowed_intervals=(0.0, 7.0))

    score = Score(harmonic_context={
        "mode": "modal",
        "pitch_collection": [0.0, 2.0, 3.0, 5.0, 7.0, 9.0, 10.0],
        "hard_constraint": True,
    })
    restored = Score.from_dict(score.to_dict())
    assert restored.to_dict() == score.to_dict()


def test_explicit_interval_constraints_without_a_centre_are_rejected():
    with pytest.raises(ValueError, match="allowed_intervals require centre_pitch"):
        Score(harmonic_context={
            "mode": "spectral",
            "allowed_intervals": [0.0, 7.0],
            "hard_constraint": True,
        })
