from fractions import Fraction

import numpy as np

from reawarp import GenerationConfig, ReawarpEngine, ScoreRenderer
from reawarp.score.timeline import RenderTimeline


def _config():
    return GenerationConfig(
        duration=5.0,
        bpm=137.0,
        sample_rate=22_050,
        seed="m17.5-score-first-cutover",
        include_melody=True,
        include_texture=True,
        include_ambience=True,
        complexity=0.34,
    )


def test_plan_score_emits_rational_beat_events_before_rendering():
    config = _config()
    engine = ReawarpEngine()

    first = engine.plan_score(config)
    second = engine.plan_score(config)

    assert first.metadata["score_origin"] == "score_first_generation"
    assert first.metadata["planner_event_timebase"] == (
        "rational_quarter_note_beats_from_sixteenth_grid"
    )
    assert first.events
    assert first.to_dict() == second.to_dict()
    assert all(isinstance(event.onset_beats, Fraction) for event in first.events)
    assert all((event.onset_beats * 4).denominator == 1 for event in first.events if "step" in event.parameters)
    assert all("time" not in event.parameters for event in first.events)
    assert {event.voice_id for event in first.events} >= {
        "kick", "snare", "hat", "break", "melody", "noise_texture", "ambience"
    }
    assert any(event.kind == "marker" and event.voice_id == "noise_texture" for event in first.events)
    assert any(event.kind == "marker" and event.voice_id == "ambience" for event in first.events)


def test_generate_uses_score_renderer_and_projects_legacy_events_from_score():
    config = _config()
    engine = ReawarpEngine()
    project = engine.generate(config)

    assert project.score is not None
    assert project.to_score() is project.score
    assert project.score.metadata["score_origin"] == "score_first_generation"
    assert project.score.metadata["renderer_version"] == "reawarp-score-renderer/1.0.0"
    assert project.score.metadata["render_provenance"]["event_source"] == "Score.events"
    assert project.score.metadata["render_provenance"]["event_timebase"].startswith(
        "rational quarter-note beats"
    )

    event_ids = {event.event_id for event in project.score.events}
    assert {record["score_event_id"] for record in project.events} == event_ids
    for record in project.events:
        score_event = next(
            event for event in project.score.events
            if event.event_id == record["score_event_id"]
        )
        assert record["time"] == project.score.tempo_map.beat_to_seconds(
            score_event.onset_beats
        )

    assert set(project.stems) >= {
        "kick", "snare", "hats", "synthetic_break",
        "melody", "noise_texture", "ambience",
    }
    for stem in project.stems.values():
        assert stem.shape == (config.frame_count, 2)
        assert stem.dtype == np.float32
        assert np.isfinite(stem).all()

    timeline = RenderTimeline(
        config.sample_rate, project.score.tempo_map, project.score.meter_map
    )
    rendered = engine.render_score(
        project.score, sample_rate=config.sample_rate, frame_count=project.frame_count
    )
    assert rendered.frame_count == config.frame_count
    assert rendered.score is project.score
    for scheduled in rendered.schedule:
        assert scheduled.start_frame == timeline.beat_to_frame(
            scheduled.event.onset_beats
        )
    assert rendered.schedule


def test_score_first_project_roundtrip_keeps_the_canonical_score(tmp_path):
    project = ReawarpEngine().generate(_config())
    export_dir = project.export(tmp_path / "m17.5-project")
    from reawarp import ReawarpProject

    reopened = ReawarpProject.load(export_dir)
    assert reopened.score is not None
    assert reopened.to_score().to_dict() == project.to_score().to_dict()
    assert reopened.events == project.events
    assert reopened.metadata["renderer_version"] == "reawarp-score-renderer/1.0.0"


def test_legacy_generator_remains_available_as_a_migration_comparison():
    config = _config()
    legacy = ReawarpEngine().generate_legacy(config)

    assert legacy.score is None
    legacy_renderer = legacy.metadata.get("renderer_version")
    if legacy_renderer is None:
        legacy_renderer = "legacy-generator/" + str(legacy.metadata["algorithm_version"])
    assert legacy_renderer.startswith("legacy-generator/")
    assert legacy.to_score().metadata["render_provenance"]["event_source"] == (
        "ReawarpProject.events"
    )
