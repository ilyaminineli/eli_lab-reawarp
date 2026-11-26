from __future__ import annotations

from dataclasses import replace
import json

import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.composition.phrases import PhrasePlan, PhraseSpan
from reawarp.core.project import ReawarpProject
from reawarp.listening import (
    ListeningEditHistory,
    analyse_audio,
    analyse_project,
    apply_playback_level,
    attach_listening_session,
    audio_fingerprint,
    build_contextual_audition_set,
    build_invariance_probe,
    build_subtraction_pass,
    listening_report_markdown,
    new_listening_session,
    record_session_event,
    update_human_notes,
    validate_listening_session,
)
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.time import TempoMap


def _project():
    config = GenerationConfig(
        duration=5.0, sample_rate=22_050, seed="m32-listening-fixture",
        include_melody=False, include_texture=False, include_ambience=False,
    )
    frames = config.frame_count
    t = np.arange(frames, dtype=np.float32) / config.sample_rate
    kick = np.column_stack((0.2 * np.sin(2 * np.pi * 60 * t),) * 2).astype(np.float32)
    melody = np.column_stack((0.1 * np.sin(2 * np.pi * 440 * t),) * 2).astype(np.float32)
    score = Score(
        title="M32 contexts",
        tempo_map=TempoMap.constant(120),
        events=(
            MusicalEvent("a", "melody", 0, 1, kind="note", pitch=60),
            MusicalEvent("b", "melody", 2, 1, kind="note", pitch=64),
            MusicalEvent("c", "melody", 4, 1, kind="note", pitch=67),
            MusicalEvent("d", "kick", 0, 1, kind="hit"),
        ),
        metadata={"sample_rate": config.sample_rate, "duration_seconds": 5.0},
    )
    return ReawarpProject(
        config=config, sample_rate=config.sample_rate,
        stems={"kick": kick, "melody": melody}, score=score,
    )


def _phrased_project():
    project = _project()
    score = project.to_score()
    plan = PhrasePlan(phrases=(
        PhraseSpan("phrase-a", 0, 2, "presentation", roles=("melody",), event_ids=("a",)),
        PhraseSpan("phrase-b", 2, 4, "continuation", roles=("melody",), event_ids=("b",)),
        PhraseSpan("phrase-c", 4, 6, "arrival", roles=("melody",), event_ids=("c",)),
    ))
    return replace(project, score=plan.attach_to_score(score))


def test_subtraction_pass_is_percentage_based_disposable_and_hash_auditable():
    project = _project()
    before = {key: value.copy() for key, value in project.stems.items()}
    baseline = project.render_master()
    result = build_subtraction_pass(project, ("kick",), 50, label="Half kick")
    np.testing.assert_allclose(result.audio, baseline - project.stems["kick"] * 0.5, atol=1e-6)
    assert result.transform.operation == "role_subtraction"
    assert result.transform.parameters["percentage"] == 50
    assert result.transform.parameters["production_edit"] is False
    assert result.transform.before_audio_sha256 == audio_fingerprint(baseline)
    for name, audio in before.items():
        np.testing.assert_array_equal(project.stems[name], audio)


def test_subtraction_history_supports_restore_redo_and_keep_decisions():
    project = _project()
    history = ListeningEditHistory(project.render_master(), sample_rate=project.sample_rate)
    first = build_subtraction_pass(project, ("kick",), 25)
    history.push(first.audio, first.transform)
    first_hash = audio_fingerprint(history.current)
    second = build_subtraction_pass(project, ("melody",), 60)
    history.push(second.audio, second.transform)
    second_hash = audio_fingerprint(history.current)
    assert history.can_undo
    np.testing.assert_array_equal(history.undo(), first.audio)
    assert audio_fingerprint(history.current) == first_hash
    np.testing.assert_array_equal(history.redo(), second.audio)
    assert audio_fingerprint(history.current) == second_hash
    assert history.keep_current()["decision"] == "kept_for_review"
    assert history.records[-1]["decision"] == "kept_for_review"


def test_phrase_contexts_use_exact_score_beats_and_role_scoped_buffers():
    project = _phrased_project()
    solo = build_contextual_audition_set(project, "solo_phrase", phrase_id="phrase-b")
    before = build_contextual_audition_set(
        project, "predecessor_to_candidate", phrase_id="phrase-b"
    )
    after = build_contextual_audition_set(
        project, "candidate_to_successor", phrase_id="phrase-b"
    )
    solo_audio = next(iter(solo.values())).audio
    before_audio = next(iter(before.values())).audio
    after_audio = next(iter(after.values())).audio
    assert len(solo_audio) == 22_050
    assert len(before_audio) == 44_100
    assert len(after_audio) == 44_100
    assert next(iter(solo.values())).transform.parameters["roles"] == ["melody"]


def test_invariance_probe_requires_anchor_and_records_human_identity_question():
    project = _project()
    probe = build_invariance_probe(
        project, anchor_roles=("melody",), removed_roles=("kick",),
        identity_label="melody anchor",
    )
    assert probe.transform.operation == "invariance_removal_probe"
    assert probe.transform.parameters["human_identity_survives"] is None
    assert probe.transform.parameters["anchor_roles"] == ["melody"]
    with pytest.raises(ValueError, match="cannot also be removed"):
        build_invariance_probe(
            project, anchor_roles=("kick",), removed_roles=("kick",),
            identity_label="invalid",
        )


def test_altered_register_is_a_transposed_score_copy_not_a_project_edit():
    project = _phrased_project()
    original = project.to_score()
    result = build_contextual_audition_set(
        project, "altered_register", phrase_id="phrase-b", register_semitones=12,
    )
    audition = next(iter(result.values()))
    assert audition.transform.parameters["semitones"] == 12
    assert audition.transform.parameters["changed_note_events"] == 1
    assert project.to_score().to_dict() == original.to_dict()


def test_diagnostics_expose_measured_evidence_without_artistic_scoring():
    sample_rate = 8_000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    stereo = np.column_stack((
        1.1 * np.sin(2 * np.pi * 440 * time),
        -1.1 * np.sin(2 * np.pi * 440 * time),
    )).astype(np.float32)
    result = analyse_audio(stereo, sample_rate)
    assert result["metrics"]["clipped_sample_count"] > 0
    assert result["metrics"]["mono_fold_level_loss_db"] < -6.0
    assert result["metrics"]["spectral_occupancy"]["bands"]["mid"] > 0
    assert {item["code"] for item in result["warnings"]} >= {
        "clipping", "mono_fold_level_loss", "anti_correlated_channels",
    }
    assert all("severity" in item and "evidence" in item for item in result["warnings"])
    assert analyse_audio(stereo, sample_rate, enabled=False) == {
        "enabled": False, "metrics": {}, "warnings": [], "parameters": {},
    }


def test_project_diagnostics_include_role_measurements_and_transient_overlap():
    result = analyse_project(_project())
    assert result["enabled"] is True
    assert result["project_fingerprint"]
    assert set(result["stems"]) == {"kick", "melody"}
    assert "transient_overlap" in result
    disabled = analyse_project(_project(), enabled=False)
    assert disabled["enabled"] is False and disabled["master"] == {}


def test_playback_level_and_report_session_roundtrip_store_exact_provenance():
    project = _phrased_project()
    session = new_listening_session(
        project, candidate_ids=("candidate-abc",), playback_level_dbfs=-24,
    )
    audio = project.render_master()
    played, level_record = apply_playback_level(audio, level_dbfs=-24)
    assert played is not audio and level_record["production_audio_unchanged"] is True
    session = record_session_event(session, "level_checks", level_record)
    audition = build_subtraction_pass(project, ("kick",), 20)
    session = record_session_event(
        session, "audition_transforms", audition.transform.to_dict()
    )
    session = update_human_notes(session, {
        "identity": "The melody remains recognisable.",
        "contrast": "The kick removal exposes more space.",
    })
    attached = attach_listening_session(project, session)
    assert attached.metadata["m32_listening_session"]["project_fingerprint"] == session["project_fingerprint"]
    assert audio_fingerprint(attached.render_master()) == audio_fingerprint(project.render_master())
    restored = validate_listening_session(attached.metadata["m32_listening_session"])
    report = listening_report_markdown(restored)
    assert "The melody remains recognisable." in report
    assert "human judgement only" in report
    assert restored["candidate_ids"] == ["candidate-abc"]


def test_context_errors_are_explicit_when_phrase_metadata_is_missing():
    project = _project()
    with pytest.raises(ValueError, match="phrase spans"):
        build_contextual_audition_set(project, "solo_phrase", phrase_id="absent")
    with pytest.raises(ValueError, match="select at least one role"):
        build_subtraction_pass(project, (), 20)


def test_critical_listening_report_exports_readable_json_markdown_and_manifest(tmp_path):
    project = _phrased_project()
    session = new_listening_session(project, candidate_ids=("candidate-export",))
    session = update_human_notes(session, {
        "identity": "The opening motif survives the subtraction pass.",
        "technical_integrity": "No clipping was observed in the selected print.",
    })
    session["technical_analysis"] = analyse_project(project)
    attached = attach_listening_session(project, session)

    exported = attached.export(tmp_path / "m32-report-export")
    json_path = exported / "critical_listening_report.json"
    markdown_path = exported / "critical_listening_report.md"
    manifest_path = exported / "manifest.json"
    assert json_path.is_file() and markdown_path.is_file() and manifest_path.is_file()
    report = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert report["project_fingerprint"] == session["project_fingerprint"]
    assert "The opening motif survives" in markdown
    assert "Human listening prompts" in markdown
    assert manifest["critical_listening"]["json_file"] == "critical_listening_report.json"
    assert manifest["critical_listening"]["session_id"] == session["session_id"]
