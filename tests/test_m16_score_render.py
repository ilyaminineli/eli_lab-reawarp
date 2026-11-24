import json
from fractions import Fraction

import numpy as np
import pytest

from reawarp import (
    AutomationLane,
    AutomationPoint,
    GenerationConfig,
    MeterMap,
    MeterPoint,
    MusicalEvent,
    ReawarpEngine,
    Score,
    ScoreRenderer,
    TempoMap,
    TempoPoint,
)
from reawarp.score.automation import AutomationTarget, AutomationTargetRegistry
from reawarp.score.timeline import RenderTimeline


def test_timeline_maps_step_tempo_and_meter_changes_to_sample_frames():
    tempo = TempoMap((
        TempoPoint(Fraction(0), 120.0, "step"),
        TempoPoint(Fraction(4), 60.0, "step"),
    ))
    meter = MeterMap((
        MeterPoint(Fraction(0), 4, 4),
        MeterPoint(Fraction(4), 3, 4),
    ))
    timeline = RenderTimeline(48_000, tempo, meter)

    assert timeline.beat_to_frame(Fraction(4)) == 96_000
    assert timeline.beat_to_frame(Fraction(8)) == 288_000
    assert timeline.frame_to_beat(96_000) == Fraction(4)
    assert timeline.bar_and_beat(Fraction(4)) == (2, Fraction(0))
    assert timeline.bar_and_beat(Fraction(7)) == (3, Fraction(0))
    assert timeline.frame_bar_and_beat(96_000) == (2, Fraction(0))


def test_timeline_integrates_linear_tempo_ramp_without_linear_seconds_guess():
    timeline = RenderTimeline(
        48_000,
        TempoMap((
            TempoPoint(Fraction(0), 120.0, "linear"),
            TempoPoint(Fraction(8), 60.0, "step"),
        )),
        MeterMap(),
    )
    expected_seconds = 60.0 * 8.0 * np.log(0.5) / (60.0 - 120.0)
    assert timeline.beat_to_frame(Fraction(8)) == int(
        np.floor(expected_seconds * 48_000 + 0.5)
    )
    assert timeline.beat_to_frame(Fraction(8)) > timeline.beat_to_frame(Fraction(4))


def _score_with_control_lanes():
    return Score(
        title="M16 score clock fixture",
        tempo_map=TempoMap((
            TempoPoint(Fraction(0), 120.0, "step"),
            TempoPoint(Fraction(4), 60.0, "step"),
        )),
        meter_map=MeterMap((
            MeterPoint(Fraction(0), 4, 4),
            MeterPoint(Fraction(4), 3, 4),
        )),
        events=(
            MusicalEvent(
                event_id="lead-a",
                voice_id="lead",
                onset_beats=Fraction(0),
                duration_beats=Fraction(1),
                kind="note",
                frequency_hz=440.0,
                velocity=0.5,
                parameters={"pan": -0.25},
            ),
            MusicalEvent(
                event_id="lead-b",
                voice_id="lead",
                onset_beats=Fraction(4),
                duration_beats=Fraction(1),
                kind="note",
                frequency_hz=660.0,
                velocity=0.5,
                parameters={"pan": 0.25},
            ),
        ),
        automation=(
            AutomationLane(
                target_id="synth.cutoff",
                points=(
                    AutomationPoint(Fraction(0), 100.0),
                    AutomationPoint(Fraction(4), 500.0),
                ),
                unit="Hz",
                time_basis="beats",
                interpolation="linear",
                minimum=20.0,
                maximum=18_000.0,
            ),
            AutomationLane(
                target_id="fx.send.space",
                points=(
                    AutomationPoint(Fraction(0), 0.0),
                    AutomationPoint(Fraction(6), 0.6),
                ),
                unit="normalized",
                time_basis="beats",
                interpolation="linear",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        metadata={"sample_rate": 48_000, "duration_seconds": 6.0},
    )


def test_score_renderer_uses_score_event_schedule_for_synthesis():
    score = _score_with_control_lanes()
    seen = []

    def voice(scheduled, sample_rate, controls):
        seen.append((
            scheduled.event.event_id,
            scheduled.start_frame,
            scheduled.bar_number,
            controls.value_at_frame("synth.cutoff", scheduled.start_frame),
        ))
        return np.ones(scheduled.duration_frames, dtype=np.float32)

    result = ScoreRenderer().render(score, 48_000, voice_renderers={"lead": voice})

    assert result.frame_count == 288_000
    assert [(item.event.event_id, item.start_frame) for item in result.schedule] == [
        ("lead-a", 0),
        ("lead-b", 96_000),
    ]
    assert seen[0][:3] == ("lead-a", 0, 1)
    assert seen[1][:3] == ("lead-b", 96_000, 2)
    assert seen[0][3] == pytest.approx(100.0)
    assert seen[1][3] == pytest.approx(500.0)
    assert result.stems["lead"].shape == (288_000, 2)
    assert np.isfinite(result.render_master()).all()
    assert result.stems["lead"][0, 0] > result.stems["lead"][0, 1]


def test_automation_control_bus_samples_synthesis_and_fx_on_the_same_frame_clock():
    result = ScoreRenderer().render(_score_with_control_lanes(), 48_000)
    cutoff = result.controls.sample("synth.cutoff", 0, 96_001, step_frames=48_000)
    space = result.controls.sample("fx.send.space", 0, 96_001, step_frames=48_000)

    assert cutoff.frames.tolist() == [0, 48_000, 96_000]
    assert cutoff.values.tolist() == pytest.approx([100.0, 300.0, 500.0])
    assert space.frames.tolist() == [0, 48_000, 96_000]
    assert space.values.tolist() == pytest.approx([0.0, 0.2, 0.4])


def test_frame_based_automation_keeps_its_source_sample_rate_after_resampling():
    score = Score(
        events=(
            MusicalEvent(
                event_id="frame-note",
                voice_id="tone",
                onset_beats=Fraction(0),
                duration_beats=Fraction(1),
                kind="note",
                frequency_hz=220.0,
            ),
        ),
        automation=(
            AutomationLane(
                target_id="custom.frame_control",
                points=(
                    AutomationPoint(Fraction(0), 0.0),
                    AutomationPoint(Fraction(48_000), 1.0),
                ),
                unit="normalized",
                time_basis="frames",
                interpolation="linear",
            ),
        ),
        metadata={"sample_rate": 48_000},
    )
    result = ScoreRenderer().render(score, 96_000, frame_count=96_001)
    assert result.controls.value_at_frame("custom.frame_control", 48_000) == pytest.approx(0.5)
    assert result.controls.value_at_frame("custom.frame_control", 96_000) == pytest.approx(1.0)


def test_typed_automation_registry_rejects_wrong_units_ranges_and_invalid_midi_targets():
    registry = AutomationTargetRegistry((
        AutomationTarget("synth.cutoff", "synthesis", "Hz", minimum=20.0, maximum=18_000.0),
    ))
    wrong_unit = AutomationLane(
        "synth.cutoff", (AutomationPoint(Fraction(0), 0.5),), unit="normalized"
    )
    with pytest.raises(ValueError, match="requires 'Hz'"):
        registry.validate_lane(wrong_unit)
    too_high = AutomationLane(
        "synth.cutoff", (AutomationPoint(Fraction(0), 19_000.0),), unit="Hz"
    )
    with pytest.raises(ValueError, match="exceeds target"):
        registry.validate_lane(too_high)
    with pytest.raises(ValueError, match="unregistered"):
        registry.validate_lane(AutomationLane(
            "midi.cc.16.1", (AutomationPoint(Fraction(0), 0.5),), unit="normalized"
        ))
    assert registry.resolve("midi.cc.1.74").domain == "midi"


def test_score_renderer_is_deterministic_and_rejects_invalid_voice_output():
    score = Score(events=(
        MusicalEvent(
            event_id="hit-a",
            voice_id="kick",
            onset_beats=Fraction(0),
            duration_beats=Fraction(1, 8),
            kind="hit",
            velocity=0.8,
            seed=211,
        ),
    ))
    first = ScoreRenderer().render(score, 22_050)
    second = ScoreRenderer().render(score, 22_050)
    np.testing.assert_array_equal(first.stems["kick"], second.stems["kick"])

    def invalid_voice(scheduled, sample_rate, controls):
        return np.full(scheduled.duration_frames, np.nan, dtype=np.float32)

    with pytest.raises(ValueError, match="non-finite"):
        ScoreRenderer().render(score, 22_050, voice_renderers={"kick": invalid_voice})


def test_score_renderer_rejects_misaligned_voice_buffers_and_bad_rate():
    score = Score(events=(
        MusicalEvent(
            event_id="short-note",
            voice_id="lead",
            onset_beats=Fraction(0),
            duration_beats=Fraction(1, 2),
            kind="note",
            pitch=69,
        ),
    ))

    def too_short(scheduled, sample_rate, controls):
        return np.zeros(scheduled.duration_frames - 1, dtype=np.float32)

    with pytest.raises(ValueError, match="exactly"):
        ScoreRenderer().render(score, 48_000, voice_renderers={"lead": too_short})
    with pytest.raises(ValueError, match="sample_rate"):
        ScoreRenderer().render(score, 0)


def test_engine_exposes_score_native_render_entrypoint_and_project_score_provenance(tmp_path):
    engine = ReawarpEngine()
    project = engine.generate(GenerationConfig(
        duration=5.0,
        bpm=120.0,
        sample_rate=22_050,
        seed="m16-provenance",
        include_melody=True,
        include_texture=False,
        include_ambience=False,
    ))
    score = project.to_score()
    provenance = score.metadata["render_provenance"]
    assert provenance["sample_rate"] == 22_050
    assert provenance["frame_count"] == project.frame_count
    assert provenance["engine_algorithm_version"] == engine.VERSION
    assert provenance["score_renderer_version"] == ScoreRenderer.VERSION

    rendered = engine.render_score(score, sample_rate=22_050)
    assert rendered.frame_count == project.frame_count
    assert "melody" in rendered.stems

    exported = project.export(tmp_path / "m16-export")
    project_record = json.loads((exported / "project.json").read_text(encoding="utf-8"))
    assert project_record["renderer_version"] == f"legacy-generator/{engine.VERSION}"
    assert project_record["render_provenance"]["frame_count"] == project.frame_count
