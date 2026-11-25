from fractions import Fraction

import numpy as np
import pytest

from reawarp import (
    AutomationLane,
    AutomationModulation,
    AutomationPoint,
    AutomationSource,
    MeterMap,
    MusicalEvent,
    Score,
    ScoreRenderer,
    TempoMap,
    TempoPoint,
)
from reawarp.score.automation import AutomationControlBus
from reawarp.score.timeline import RenderTimeline


def _timeline(sample_rate=48_000):
    return RenderTimeline(
        sample_rate,
        TempoMap((TempoPoint(Fraction(0), 120.0, "step"),)),
        MeterMap(),
    )


def test_scope_precedence_absolute_then_relative_and_legacy_global_lookup():
    lanes = (
        AutomationLane(
            "synth.pitch",
            (AutomationPoint(Fraction(0), 2.0),),
            unit="semitones",
        ),
        AutomationLane(
            "synth.pitch",
            (AutomationPoint(Fraction(0), 3.0),),
            unit="semitones",
            scope="section",
            scope_id="development",
        ),
        AutomationLane(
            "synth.pitch",
            (AutomationPoint(Fraction(0), 1.0),),
            unit="semitones",
            scope="role",
            scope_id="lead",
            value_mode="relative",
        ),
        AutomationLane(
            "synth.pitch",
            (AutomationPoint(Fraction(0), 2.0),),
            unit="semitones",
            scope="event",
            scope_id="note-a",
            value_mode="relative",
        ),
    )
    bus = AutomationControlBus(
        lanes,
        _timeline(),
        event_contexts={
            "note-a": {
                "role_id": "lead",
                "section_id": "development",
                "event_onset_frame": 0,
            }
        },
    )

    assert bus.value_at_frame("synth.pitch", 0) == pytest.approx(2.0)
    assert bus.value_for_context(
        "synth.pitch", 0, event_id="note-a"
    ) == pytest.approx(6.0)
    assert bus.value_for_context(
        "synth.pitch", 0, context={"role_id": "lead", "section_id": "other"}
    ) == pytest.approx(3.0)


def test_scoped_lane_requires_an_id_and_global_lane_forbids_one():
    with pytest.raises(ValueError, match="require a scope_id"):
        AutomationLane(
            "synth.gain",
            (AutomationPoint(Fraction(0), 0.5),),
            scope="role",
        )
    with pytest.raises(ValueError, match="cannot have a scope_id"):
        AutomationLane(
            "synth.gain",
            (AutomationPoint(Fraction(0), 0.5),),
            scope_id="lead",
        )


def test_deterministic_source_generators_are_bounded_and_reproducible():
    definitions = (
        AutomationSource(
            "lfo-a", "lfo", Fraction(0), Fraction(8),
            parameters={"period_beats": 2, "waveform": "triangle", "sample_count": 17},
            minimum=0.1, maximum=0.9,
        ),
        AutomationSource(
            "env-a", "envelope", Fraction(0), Fraction(8),
            parameters={"shape": [[0, 0], [0.2, 1], [1, 0.25]]},
        ),
        AutomationSource(
            "steps-a", "stepped", Fraction(0), Fraction(8),
            parameters={"values": [0.1, 0.8, 0.35], "step_beats": "1/2"},
        ),
        AutomationSource(
            "walk-a", "random_walk", Fraction(0), Fraction(8),
            parameters={"step_beats": "1/2", "step_size": 0.18, "initial": 0.5},
            seed=214,
        ),
        AutomationSource(
            "phrase-a", "phrase_curve", Fraction(0), Fraction(8),
            parameters={"values": [0.0, 0.8, 0.3, 1.0]},
        ),
    )
    for source in definitions:
        first = source.to_lane()
        second = source.to_lane()
        assert first.to_dict() == second.to_dict()
        assert all(source.minimum <= point.value <= source.maximum for point in first.points)
        assert first.points[0].at == source.start
        assert first.points[-1].at == source.end

    walk = definitions[3]
    other_identity = AutomationSource(
        "walk-b", "random_walk", Fraction(0), Fraction(8),
        parameters=walk.parameters, seed=walk.seed,
    )
    assert [p.value for p in walk.to_lane().points] != [
        p.value for p in other_identity.to_lane().points
    ]


def test_lfo_modulation_supports_explicit_event_retrigger_phase():
    source = AutomationSource(
        "slow-pulse",
        "lfo",
        Fraction(0),
        Fraction(4),
        parameters={
            "period_beats": 4,
            "phase_cycles": 0.25,
            "center": 0.5,
            "depth": 0.5,
            "sample_count": 9,
        },
    )
    lane = AutomationLane(
        "synth.pitch",
        (AutomationPoint(Fraction(0), 0.0),),
        unit="semitones",
    )
    modulation = AutomationModulation(
        source_id="slow-pulse",
        destination_target_id="synth.pitch",
        amount=6.0,
        polarity="bipolar",
        retrigger="event",
        scope="role",
        scope_id="lead",
        minimum=-12.0,
        maximum=12.0,
    )
    bus = AutomationControlBus(
        (lane,),
        _timeline(),
        sources=(source,),
        modulations=(modulation,),
        event_contexts={
            "note-a": {
                "role_id": "lead",
                "event_onset_frame": 48_000,
            }
        },
    )

    assert bus._context("note-a", None)["role_id"] == "lead"
    assert bus._sources["slow-pulse"].to_lane().evaluate(Fraction(0)) == pytest.approx(1.0)
    assert bus._source_lanes["slow-pulse"].evaluate(Fraction(0)) == pytest.approx(1.0)
    assert bus._modulations["synth.pitch"][0].scope_id == "lead"
    assert bus.value_for_context(
        "synth.pitch", 48_000, event_id="note-a"
    ) == pytest.approx(6.0)
    assert bus.value_for_context(
        "synth.pitch", 48_000,
        context={"role_id": "bass", "event_onset_frame": 48_000},
    ) == pytest.approx(0.0)


def test_control_rate_smoothing_and_hysteresis_reduce_small_steps():
    lane = AutomationLane(
        "synth.gain",
        (
            AutomationPoint(Fraction(0), 0.0),
            AutomationPoint(Fraction(1), 0.6),
        ),
        unit="normalized",
        smoothing_seconds=0.25,
        hysteresis=0.05,
    )
    bus = AutomationControlBus((lane,), _timeline())
    samples = bus.sample(
        "synth.gain", 0, 36_001, step_frames=12_000
    )

    assert samples.frames.tolist() == [0, 12_000, 24_000, 36_000]
    assert samples.values[0] == pytest.approx(0.0)
    assert samples.values[1] < 0.3
    assert samples.values[2] > samples.values[1]
    assert samples.values[2] < 0.6


def test_score_round_trip_preserves_scopes_sources_and_modulation():
    score = Score(
        title="M18 serialisation fixture",
        automation=(
            AutomationLane(
                "synth.cutoff",
                (
                    AutomationPoint(Fraction(0), 500.0),
                    AutomationPoint(Fraction(8), 4_000.0),
                ),
                unit="Hz",
                scope="role",
                scope_id="melody",
                value_mode="relative",
                smoothing_seconds=0.04,
                hysteresis=1.5,
            ),
        ),
        automation_sources=(
            AutomationSource(
                "breathing", "lfo", Fraction(0), Fraction(8),
                parameters={"period_beats": 8, "depth": 0.2},
                seed=23,
            ),
        ),
        modulations=(
            AutomationModulation(
                "breathing", "synth.cutoff", amount=800.0,
                retrigger="section", smoothing_seconds=0.03,
                minimum=100.0, maximum=12_000.0,
                base_value=2_400.0,
                scope="role", scope_id="melody",
            ),
        ),
    )

    restored = Score.from_dict(score.to_dict())
    assert restored.to_dict() == score.to_dict()


def test_old_score_json_without_m18_fields_remains_readable():
    old_record = {
        "format": "eli_lab_reawarp_score",
        "schema_version": 1,
        "title": "Legacy M17 score",
        "ppq": 960,
        "events": [],
        "automation": [{
            "target_id": "synth.gain",
            "points": [{"at": "0", "value": 0.5}],
            "unit": "normalized",
        }],
    }
    score = Score.from_dict(old_record)
    assert score.automation[0].scope == "global"
    assert score.automation[0].value_mode == "absolute"
    assert score.automation_sources == ()
    assert score.modulations == ()


def test_score_renderer_installs_generated_sources_and_event_phase_context():
    score = Score(
        events=(
            MusicalEvent(
                event_id="lead-note",
                voice_id="lead",
                onset_beats=Fraction(2),
                duration_beats=Fraction(1),
                kind="note",
                frequency_hz=440.0,
                parameters={"section_id": "B"},
            ),
        ),
        automation_sources=(
            AutomationSource(
                "pulse", "lfo", Fraction(0), Fraction(4),
                parameters={"period_beats": 4, "phase_cycles": 0.25, "sample_count": 9},
            ),
        ),
        modulations=(
            AutomationModulation(
                "pulse", "synth.pitch", amount=6.0, retrigger="event"
            ),
        ),
    )
    result = ScoreRenderer().render(score, 48_000)

    assert "source.pulse" in result.controls.target_ids
    assert result.controls.value_for_context(
        "synth.pitch",
        result.schedule[0].start_frame,
        event_id="lead-note",
    ) == pytest.approx(6.0)
    assert np.isfinite(result.stems["lead"]).all()


def test_source_time_stays_beat_addressed_through_tempo_ramps():
    tempo = TempoMap((
        TempoPoint(Fraction(0), 120.0, "linear"),
        TempoPoint(Fraction(8), 60.0, "step"),
    ))
    timeline = RenderTimeline(48_000, tempo, MeterMap())
    source = AutomationSource(
        "ramp-pulse", "phrase_curve", Fraction(0), Fraction(8),
        parameters={"values": [0.0, 1.0]},
    )
    bus = AutomationControlBus(
        (), timeline, sources=(source,)
    )

    middle = timeline.beat_to_frame(Fraction(4))
    end = timeline.beat_to_frame(Fraction(8))
    assert bus.value_at_frame("source.ramp-pulse", middle) == pytest.approx(0.5, abs=0.002)
    assert bus.value_at_frame("source.ramp-pulse", end) == pytest.approx(1.0)



def test_score_renderer_applies_role_activity_and_velocity_scale_only_to_target_voice():
    events = (
        MusicalEvent(
            event_id="lead-a",
            voice_id="lead",
            onset_beats=Fraction(0),
            duration_beats=Fraction(1),
            kind="note",
            frequency_hz=440.0,
            velocity=0.8,
        ),
        MusicalEvent(
            event_id="bass-a",
            voice_id="bass",
            onset_beats=Fraction(0),
            duration_beats=Fraction(1),
            kind="note",
            frequency_hz=110.0,
            velocity=0.8,
        ),
    )

    def constant_voice(scheduled, sample_rate, controls):
        del sample_rate, controls
        return np.ones(scheduled.duration_frames, dtype=np.float32)

    base = ScoreRenderer().render(
        Score(events=events),
        48_000,
        voice_renderers={"lead": constant_voice, "bass": constant_voice},
    )
    controlled = ScoreRenderer().render(
        Score(
            events=events,
            automation=(
                AutomationLane(
                    "event.velocity_scale",
                    (AutomationPoint(Fraction(0), 0.5),),
                    unit="ratio",
                    scope="role",
                    scope_id="lead",
                ),
                AutomationLane(
                    "role.activity",
                    (AutomationPoint(Fraction(0), 0.25),),
                    unit="normalized",
                    scope="role",
                    scope_id="lead",
                ),
            ),
        ),
        48_000,
        voice_renderers={"lead": constant_voice, "bass": constant_voice},
    )

    np.testing.assert_allclose(
        controlled.stems["lead"], base.stems["lead"] * 0.125, atol=1e-7
    )
    np.testing.assert_array_equal(controlled.stems["bass"], base.stems["bass"])


def test_event_probability_is_a_stable_score_render_gate():
    event = MusicalEvent(
        event_id="probability-gate",
        voice_id="hats",
        onset_beats=Fraction(0),
        duration_beats=Fraction(1, 4),
        kind="hit",
        velocity=1.0,
    )
    score = Score(
        events=(event,),
        automation=(
            AutomationLane(
                "event.probability",
                (AutomationPoint(Fraction(0), 0.0),),
                unit="normalized",
            ),
        ),
    )
    first = ScoreRenderer().render(score, 48_000)
    second = ScoreRenderer().render(score, 48_000)
    assert first.schedule[0].event.event_id == "probability-gate"
    assert "hats" not in first.stems
    assert first.stems.keys() == second.stems.keys()



def test_modulation_only_destination_uses_explicit_base_value():
    source = AutomationSource(
        "quiet-lfo", "lfo", Fraction(0), Fraction(4),
        parameters={"period_beats": 4, "center": 0.5, "depth": 0.5, "phase_cycles": 0.0},
    )
    modulation = AutomationModulation(
        "quiet-lfo",
        "synth.cutoff",
        amount=0.0,
        base_value=2_400.0,
        minimum=20.0,
        maximum=18_000.0,
    )
    bus = AutomationControlBus(
        (), _timeline(), sources=(source,), modulations=(modulation,)
    )

    assert bus.value_at_frame("synth.cutoff", 0, default_value=0.0) == pytest.approx(2_400.0)


def test_probability_one_never_skips_an_event_and_generated_triggers_share_parent_seed():
    from reawarp.score.render import _stable_event_probability_seed

    parent = MusicalEvent(
        event_id="kick-no-explicit-seed",
        voice_id="kick",
        onset_beats=Fraction(0),
        duration_beats=Fraction(1, 4),
        kind="hit",
    )
    generated_trigger = MusicalEvent(
        event_id="sample-trigger-kick-no-explicit-seed",
        voice_id="kick",
        onset_beats=Fraction(0),
        duration_beats=Fraction(1, 4),
        kind="trigger",
        articulation="sample-trigger",
        tags=("sample",),
    )
    assert _stable_event_probability_seed(parent) == _stable_event_probability_seed(
        generated_trigger
    )

    score = Score(
        events=(parent,),
        automation=(
            AutomationLane(
                "event.probability",
                (AutomationPoint(Fraction(0), 1.0),),
                unit="normalized",
            ),
        ),
    )
    result = ScoreRenderer().render(score, 48_000)
    assert "kick" in result.stems



def test_source_is_inactive_outside_its_declared_absolute_beat_window():
    source = AutomationSource(
        "late-envelope",
        "lfo",
        Fraction(4),
        Fraction(8),
        parameters={
            "period_beats": 4,
            "phase_cycles": 0.25,
            "center": 0.5,
            "depth": 0.5,
            "sample_count": 9,
        },
    )
    modulation = AutomationModulation(
        "late-envelope",
        "synth.pitch",
        amount=6.0,
    )
    bus = AutomationControlBus(
        (),
        _timeline(),
        sources=(source,),
        modulations=(modulation,),
    )

    assert bus.value_at_frame("synth.pitch", 0, default_value=0.0) == pytest.approx(0.0)
    assert bus.value_at_frame("synth.pitch", 96_000, default_value=0.0) == pytest.approx(6.0)
    assert bus.value_at_frame("synth.pitch", 228_000, default_value=0.0) == pytest.approx(0.0)



def test_scoped_modulation_base_value_does_not_leak_to_other_roles():
    source = AutomationSource(
        "lead-only-lfo",
        "lfo",
        Fraction(0),
        Fraction(4),
        parameters={
            "period_beats": 4,
            "phase_cycles": 0.25,
            "center": 0.5,
            "depth": 0.5,
            "sample_count": 9,
        },
    )
    modulation = AutomationModulation(
        "lead-only-lfo",
        "synth.cutoff",
        amount=600.0,
        base_value=2_400.0,
        scope="role",
        scope_id="lead",
        retrigger="event",
    )
    bus = AutomationControlBus(
        (),
        _timeline(),
        sources=(source,),
        modulations=(modulation,),
        event_contexts={
            "lead-note": {"role_id": "lead", "event_onset_frame": 0},
        },
    )

    assert bus.value_for_context(
        "synth.cutoff", 0, event_id="lead-note", default_value=0.0
    ) == pytest.approx(3_000.0)
    value, active = bus.value_and_active_for_context(
        "synth.cutoff", 0, default_value=0.0,
        context={"role_id": "bass"},
    )
    assert value == pytest.approx(0.0)
    assert active is False
    inactive = bus.sample(
        "synth.cutoff", 0, 480, step_frames=48,
        default_value=0.0, context={"role_id": "bass"},
    )
    assert inactive.active is not None
    assert not bool(np.any(inactive.active))
