import math

import pytest

from reawarp.score import (
    EqualTemperamentTuning,
    PitchField,
    Score,
    Sonority,
    derive_spectral_sonority,
    displace_register,
    expand_contract_sonority,
    generate_sonority,
    invert_sonority,
    replace_sonority_voice,
    resolve_sonority_frequencies,
    rotate_sonority,
    transpose_sonority,
)


def _source_sonority():
    return Sonority(
        sonority_id="seed",
        onset_beats="3/2",
        duration_beats="2",
        pitches=(48.0, 55.0, 60.0),
        bass_pitch=36.0,
        tension=0.25,
    )


def test_sonority_generation_is_reproducible_and_seeded():
    tuning = EqualTemperamentTuning()
    field = PitchField(
        mode="centred",
        centre_pitch=60.0,
        centre_weight=3.0,
    )
    first = generate_sonority(
        field, tuning, sonority_id="generated-a",
        voice_count=4, minimum_pitch=48, maximum_pitch=76,
        minimum_spacing=3, maximum_spacing=12,
        seed=1819, temperature=0.5,
    )
    repeated = generate_sonority(
        field, tuning, sonority_id="generated-a",
        voice_count=4, minimum_pitch=48, maximum_pitch=76,
        minimum_spacing=3, maximum_spacing=12,
        seed=1819, temperature=0.5,
    )
    assert first == repeated
    assert first.pitches == tuple(sorted(first.pitches))
    assert len(first.pitches) == 4
    assert all(3 <= b - a <= 12 for a, b in zip(first.pitches, first.pitches[1:]))
    assert first.transform == "generated"
    assert first.transform_parameters["seed"] == 1819


def test_generation_respects_hard_collection_constraints():
    tuning = EqualTemperamentTuning()
    field = PitchField(
        mode="collection",
        pitch_collection=(0, 2, 4, 5, 7, 9, 11),
        hard_constraint=True,
    )
    generated = generate_sonority(
        field, tuning, sonority_id="major-field",
        voice_count=5, minimum_pitch=48, maximum_pitch=84,
        minimum_spacing=2, seed="field-seed", temperature=0,
    )
    assert all(
        any(
            math.isclose(
                (pitch - item) / tuning.divisions_per_period,
                round((pitch - item) / tuning.divisions_per_period),
                abs_tol=1e-7,
            )
            for item in field.pitch_collection
        )
        for pitch in generated.pitches
    )


def test_soft_collection_preference_does_not_forbid_chromatic_candidates():
    tuning = EqualTemperamentTuning()
    field = PitchField(
        mode="collection",
        pitch_collection=(0, 2, 4, 5, 7, 9, 11),
        hard_constraint=False,
    )
    generated = generate_sonority(
        field, tuning, sonority_id="soft-field",
        voice_count=4, minimum_pitch=60, maximum_pitch=72,
        minimum_spacing=1, vocabulary_weight=10, temperature=0,
    )
    assert len(generated.pitches) == 4
    assert all(
        any(
            math.isclose(
                (pitch - item) / tuning.divisions_per_period,
                round((pitch - item) / tuning.divisions_per_period),
                abs_tol=1e-7,
            )
            for item in field.pitch_collection
        )
        for pitch in generated.pitches
    )
    assert field.evaluate(61, tuning).allowed is True


def test_generation_fails_explicitly_when_spacing_cannot_fit_voice_count():
    with pytest.raises(ValueError, match="spacing constraints"):
        generate_sonority(
            None, EqualTemperamentTuning(), sonority_id="impossible",
            voice_count=4, minimum_pitch=60, maximum_pitch=62,
            minimum_spacing=1.5, temperature=0,
        )


def test_rotate_transpose_and_invert_preserve_timeline_and_provenance():
    source = _source_sonority()
    tuning = EqualTemperamentTuning()
    rotated = rotate_sonority(source, tuning, steps=1, sonority_id="rotated")
    transposed = transpose_sonority(source, 3.5, sonority_id="transposed")
    inverted = invert_sonority(source, 60, sonority_id="inverted")

    assert rotated.pitches == (55.0, 60.0, 60.0)
    assert transposed.pitches == (51.5, 58.5, 63.5)
    assert inverted.pitches == (60.0, 65.0, 72.0)
    for transformed in (rotated, transposed, inverted):
        assert transformed.onset_beats == source.onset_beats
        assert transformed.duration_beats == source.duration_beats
        assert transformed.source_sonority_id == source.sonority_id
        assert transformed.transform_parameters["source_transform"] == "original"


def test_expand_contract_and_register_displacement_are_tuning_aware():
    source = _source_sonority()
    tuning = EqualTemperamentTuning()
    expanded = expand_contract_sonority(
        source, 1.5, sonority_id="expanded", centre_pitch=55,
    )
    contracted = expand_contract_sonority(
        source, 0.5, sonority_id="contracted", centre_pitch=55,
    )
    displaced = displace_register(
        source, tuning, -1, sonority_id="lower",
    )
    assert expanded.pitches == (44.5, 55.0, 62.5)
    assert contracted.pitches == (51.5, 55.0, 57.5)
    assert displaced.pitches == (36.0, 43.0, 48.0)
    assert displaced.bass_pitch == 24.0


def test_spectral_derivation_uses_the_tuning_period_and_preserves_ratios():
    source = _source_sonority()
    tuning = EqualTemperamentTuning()
    derived = derive_spectral_sonority(
        source, tuning, (1.0, 2.0, 3.0, 5.0),
        sonority_id="partials", base_pitch=48,
    )
    assert derived.pitches[0] == pytest.approx(48.0)
    assert derived.pitches[1] == pytest.approx(60.0)
    assert derived.pitches[2] == pytest.approx(48 + 12 * math.log2(3))
    assert derived.pitches[3] == pytest.approx(48 + 12 * math.log2(5))
    frequencies = resolve_sonority_frequencies(derived, tuning)
    assert frequencies[1] / frequencies[0] == pytest.approx(2.0)
    assert frequencies[2] / frequencies[0] == pytest.approx(3.0)


def test_spectral_derivation_supports_non_octave_periods():
    tuning = EqualTemperamentTuning(
        divisions_per_period=13, period_ratio=3.0,
        reference_pitch=0, reference_frequency_hz=100,
        identifier="13edt",
    )
    source = Sonority("source", "0", "1", (0.0,), bass_pitch=0.0)
    derived = derive_spectral_sonority(
        source, tuning, (1.0, 3.0, 9.0),
        sonority_id="tritave-partials", base_pitch=0,
    )
    assert derived.pitches == pytest.approx((0.0, 13.0, 26.0))


def test_voice_replacement_is_explicit_and_auditable():
    source = _source_sonority()
    replaced = replace_sonority_voice(
        source, 1, 56.25, sonority_id="mutation",
    )
    assert replaced.pitches == (48.0, 56.25, 60.0)
    assert replaced.transform == "replace_voice"
    assert replaced.transform_parameters["previous_pitch"] == 55.0
    assert replaced.transform_parameters["replacement_pitch"] == 56.25


def test_sonority_provenance_round_trips_and_extends_score_duration():
    sonority = transpose_sonority(
        _source_sonority(), 0.25, sonority_id="score-note",
    )
    restored_record = Sonority.from_score_record(sonority.to_score_record())
    assert restored_record == sonority

    score = Score(sonorities=(sonority.to_score_record(),))
    restored_score = Score.from_dict(score.to_dict())
    assert restored_score.to_dict() == score.to_dict()
    assert restored_score.duration_beats == pytest.approx(3.5)


def test_sonority_transform_validation_rejects_non_finite_parameters():
    source = _source_sonority()
    with pytest.raises(ValueError):
        transpose_sonority(source, math.inf, sonority_id="bad")
    with pytest.raises(ValueError):
        derive_spectral_sonority(
            source, EqualTemperamentTuning(), (1.0, 0.0),
            sonority_id="bad-spectrum",
        )
    with pytest.raises(ValueError):
        Sonority(
            "bad-params", "0", "1", (60.0,),
            transform_parameters={"factor": math.nan},
        )

def test_hard_pitch_field_rejects_disallowed_bass_reference():
    field = PitchField(
        mode="collection",
        pitch_collection=(0.0,),
        hard_constraint=True,
    )
    with pytest.raises(ValueError, match="bass_pitch violates hard pitch-field"):
        generate_sonority(
            field, EqualTemperamentTuning(),
            sonority_id="bad-bass-reference",
            voice_count=1,
            minimum_pitch=60,
            maximum_pitch=60,
            bass_pitch=61,
            temperature=0,
        )
