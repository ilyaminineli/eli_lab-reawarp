import json
from fractions import Fraction

import pytest

from reawarp import (
    AutomationLane,
    AutomationPoint,
    EqualTemperamentTuning,
    MusicalEvent,
    Pitch,
    Score,
)
from reawarp.score.time import MeterMap, MeterPoint, TempoMap, TempoPoint


def make_score():
    return Score(
        title="Rational Study",
        ppq=960,
        tempo_map=TempoMap((
            TempoPoint(Fraction(0), 112, "linear"),
            TempoPoint(Fraction(8), 136, "step"),
        )),
        meter_map=MeterMap((
            MeterPoint(Fraction(0), 4, 4),
            MeterPoint(Fraction(8), 7, 8),
        )),
        events=(
            MusicalEvent(
                event_id="note-01",
                voice_id="glass",
                onset_beats=Fraction(5, 12),
                duration_beats=Fraction(7, 8),
                pitch=60.5,
                frequency_hz=271.4,
                velocity=0.72,
                tags=("motif", "microtonal"),
            ),
        ),
        automation=(
            AutomationLane(
                target_id="synth.filter.cutoff",
                points=(
                    AutomationPoint(Fraction(0), 0.2),
                    AutomationPoint(Fraction(4), 0.9),
                ),
                unit="normalized",
                interpolation="linear",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        metadata={"seed": 211, "sample_rate": 48_000},
    )


def test_score_json_round_trip_preserves_rational_time_and_frequency(tmp_path):
    score = make_score()
    path = score.save(tmp_path / "score.json")
    loaded = Score.load(path)
    assert loaded.title == score.title
    assert loaded.events[0].onset_beats == Fraction(5, 12)
    assert loaded.events[0].duration_beats == Fraction(7, 8)
    assert loaded.events[0].pitch == 60.5
    assert loaded.events[0].frequency_hz == 271.4
    assert loaded.tempo_map.points == score.tempo_map.points
    assert loaded.meter_map.points == score.meter_map.points
    assert loaded.automation[0].evaluate(Fraction(2)) == pytest.approx(0.55)
    assert loaded.metadata["seed"] == 211


def test_automation_supports_step_linear_cubic_and_exponential_modes():
    points = (
        AutomationPoint(Fraction(0), 0.25),
        AutomationPoint(Fraction(1), 1.0),
        AutomationPoint(Fraction(2), 4.0),
    )
    step = AutomationLane("x", points, interpolation="step")
    linear = AutomationLane("x", points, interpolation="linear")
    cubic = AutomationLane("x", points, interpolation="cubic")
    exponential = AutomationLane("x", points, interpolation="exponential")
    assert step.evaluate(Fraction(1, 2)) == pytest.approx(0.25)
    assert linear.evaluate(Fraction(1, 2)) == pytest.approx(0.625)
    assert cubic.evaluate(Fraction(1)) == pytest.approx(1.0)
    assert exponential.evaluate(Fraction(1)) == pytest.approx(1.0)


def test_automation_looping_and_value_limits():
    lane = AutomationLane(
        "texture.density",
        (AutomationPoint(Fraction(0), -1.0), AutomationPoint(Fraction(2), 2.0)),
        loop_length=Fraction(2),
        minimum=0.0,
        maximum=1.0,
    )
    assert lane.evaluate(Fraction(0)) == 0.0
    assert lane.evaluate(Fraction(3)) == 0.5
    assert lane.evaluate(Fraction(2)) == 0.0


def test_pitch_interface_keeps_exact_frequency_and_supports_custom_equal_divisions():
    tuning = EqualTemperamentTuning(divisions_per_period=19, identifier="19edo")
    pitch = Pitch.from_value(71.25, tuning)
    recovered = Pitch.from_frequency(pitch.frequency_hz, tuning)
    assert pitch.tuning_id == "19edo"
    assert recovered.value == pytest.approx(71.25)
    assert recovered.frequency_hz == pytest.approx(pitch.frequency_hz)


def test_score_rejects_duplicate_event_ids_and_invalid_notes():
    event = MusicalEvent("same", "voice", Fraction(0), Fraction(1), pitch=60)
    with pytest.raises(ValueError, match="unique"):
        Score(events=(event, event))
    with pytest.raises(ValueError, match="require pitch"):
        MusicalEvent("bad", "voice", Fraction(0), Fraction(1), kind="note")
    with pytest.raises(ValueError, match="between zero and one"):
        MusicalEvent("bad-velocity", "voice", Fraction(0), Fraction(1), pitch=60, velocity=1.5)


def test_score_to_dict_is_json_serializable():
    payload = make_score().to_dict()
    assert json.loads(json.dumps(payload))["format"] == "eli_lab_reawarp_score"
