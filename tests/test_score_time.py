from fractions import Fraction

import pytest

from reawarp.score.time import MeterMap, MeterPoint, TempoMap, TempoPoint


def test_constant_tempo_maps_beats_and_seconds_both_directions():
    tempo = TempoMap.constant(120)
    assert tempo.beat_to_seconds(Fraction(4)) == pytest.approx(2.0)
    assert tempo.seconds_to_beat(2.0) == Fraction(4)
    assert tempo.bpm_at(Fraction(7, 3)) == pytest.approx(120.0)


def test_step_tempo_change_integrates_each_segment():
    tempo = TempoMap((
        TempoPoint(Fraction(0), 120, "step"),
        TempoPoint(Fraction(4), 60, "step"),
    ))
    assert tempo.beat_to_seconds(Fraction(6)) == pytest.approx(4.0)
    assert tempo.seconds_to_beat(4.0) == Fraction(6)


def test_linear_tempo_ramp_integrates_and_inverts_reciprocal_bpm():
    tempo = TempoMap((
        TempoPoint(Fraction(0), 60, "linear"),
        TempoPoint(Fraction(4), 120, "step"),
    ))
    elapsed = tempo.beat_to_seconds(Fraction(4))
    assert elapsed == pytest.approx(4.0 * 60.0 * __import__("math").log(2.0) / 60.0)
    assert float(tempo.seconds_to_beat(elapsed)) == pytest.approx(4.0, abs=1e-6)
    assert tempo.bpm_at(Fraction(2)) == pytest.approx(90.0)


def test_meter_map_tracks_bar_number_and_quarter_note_offset():
    meter = MeterMap((
        MeterPoint(Fraction(0), 4, 4),
        MeterPoint(Fraction(8), 7, 8),
    ))
    assert meter.bar_and_beat(Fraction(0)) == (1, Fraction(0))
    assert meter.bar_and_beat(Fraction(6)) == (2, Fraction(2))
    assert meter.bar_and_beat(Fraction(8)) == (3, Fraction(0))
    assert meter.bar_and_beat(Fraction(10)) == (3, Fraction(2))
    assert meter.at(Fraction(9)).bar_length_beats == Fraction(7, 2)


def test_time_maps_reject_unsorted_or_invalid_points():
    with pytest.raises(ValueError):
        TempoMap((TempoPoint(Fraction(1), 120),))
    with pytest.raises(ValueError):
        TempoMap((TempoPoint(Fraction(0), 120), TempoPoint(Fraction(0), 90)))
    with pytest.raises(ValueError):
        MeterPoint(Fraction(0), 4, 3)
