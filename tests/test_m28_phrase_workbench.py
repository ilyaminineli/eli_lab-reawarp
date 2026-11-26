from __future__ import annotations

import os
from fractions import Fraction

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from reawarp.composition.phrases import (
    MotifFamily, MotifIdentity, PhrasePlan, PhraseSpan,
    build_phrase_candidate_batch, freeze_phrase_candidate,
)
from reawarp.core.project import ReawarpProject
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.time import TempoMap
from reawarp.ui.main_window import MainWindow
from reawarp.ui.pages.phrase_workbench import PhraseWorkbenchPage


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def _score():
    events = (
        MusicalEvent(
            event_id="phrase-lead-01", voice_id="melody",
            onset_beats=Fraction(0), duration_beats=Fraction(1, 2),
            kind="note", pitch=60,
        ),
        MusicalEvent(
            event_id="phrase-lead-02", voice_id="melody",
            onset_beats=Fraction(3, 2), duration_beats=Fraction(1, 2),
            kind="note", pitch=64,
        ),
        MusicalEvent(
            event_id="neighbour-kick", voice_id="kick",
            onset_beats=Fraction(11, 2), duration_beats=Fraction(1, 4),
            kind="hit",
        ),
    )
    return Score(
        title="M28 workbench fixture",
        tempo_map=TempoMap.constant(120),
        events=events,
        metadata={
            "sample_rate": 22_050,
            "duration_seconds": 4.0,
            "frame_count": 88_200,
            "render_stems": ["melody", "kick"],
        },
    )


def _project():
    from reawarp import GenerationConfig

    config = GenerationConfig(
        duration=4.0, sample_rate=22_050, seed="m28-workbench-ui",
        include_melody=False, include_texture=False, include_ambience=False,
    )
    stems = {
        name: np.zeros((config.frame_count, 2), dtype=np.float32)
        for name in ("melody", "kick")
    }
    return ReawarpProject(
        config=config, sample_rate=config.sample_rate, stems=stems,
        score=_score(),
    )


def _attached_score():
    score = _score()
    family = MotifFamily("motif-lead", versions=(MotifIdentity("motif-lead"),))
    phrase = PhraseSpan(
        phrase_id="phrase-main",
        start_beats=Fraction(0),
        end_beats=Fraction(4),
        function="presentation",
        state="open",
        motif_ids=("motif-lead",),
        roles=("melody",),
        event_ids=("phrase-lead-01", "phrase-lead-02"),
    )
    second = PhraseSpan(
        phrase_id="phrase-response",
        start_beats=Fraction(4),
        end_beats=Fraction(8),
        function="response",
        event_ids=("neighbour-kick",),
    )
    return PhrasePlan((phrase, second), (family,)).attach_to_score(score)


def test_phrase_workbench_edits_rational_spans_and_emits_candidate_requests():
    _application()
    page = PhraseWorkbenchPage()
    page.set_score(_score())

    saved = []
    batches = []
    page.phraseSaveRequested.connect(saved.append)
    page.batchRequested.connect(batches.append)

    page.phrase_id.setText("phrase-irregular")
    page.start_beats.setText("1/4")
    page.end_beats.setText("13/4")
    page.function.setCurrentIndex(page.function.findData("suspension"))
    page.state.setCurrentIndex(page.state.findData("open"))
    page.motif_ids.setText("motif-new")
    page.roles.setText("melody, texture")
    page.save_phrase_button.click()

    assert saved == [{
        "phrase_id": "phrase-irregular",
        "start_beats": "1/4",
        "end_beats": "13/4",
        "function": "suspension",
        "custom_function": None,
        "state": "open",
        "motif_ids": ["motif-new"],
        "roles": ["melody", "texture"],
    }]

    page.set_score(_attached_score(), selected_phrase_id="phrase-main")
    assert page.selected_phrase_id == "phrase-main"
    assert page.start_beats.text() == "0"
    assert page.end_beats.text() == "4"

    page.candidate_count.setValue(3)
    page.seed.setText("stable-workbench-seed")
    page.ladder.setCurrentIndex(page.ladder.findData("subtle"))
    page.policy.setCurrentIndex(page.policy.findData("open"))
    page.generate_button.click()
    assert batches[-1] == {
        "phrase_id": "phrase-main",
        "count": 3,
        "root_seed": "stable-workbench-seed",
        "variation_ladder": "subtle",
        "development_policy": "open",
    }
    page.close()


def test_phrase_workbench_shows_motif_invariants_and_exposes_context_audition():
    _application()
    score = _attached_score()
    batch = build_phrase_candidate_batch(
        score, "phrase-main", count=2, root_seed=44,
        operations=("transposition", "fragmentation"),
        batch_id="workbench-candidates",
    )
    page = PhraseWorkbenchPage()
    page.set_score(score, selected_phrase_id="phrase-main")
    page.set_candidates(list(batch.candidates), selected_id=batch.candidates[0].candidate_id)

    assert page.candidate_list.count() == 2
    assert "CHANGED" in page.candidate_details.text()
    assert "PRESERVED" in page.candidate_details.text()

    requested = []
    frozen = []
    branches = []
    restored = []
    page.auditionRequested.connect(lambda target, context: requested.append((target, context)))
    page.freezeRequested.connect(lambda candidate_id, note: frozen.append((candidate_id, note)))
    page.branchRequested.connect(lambda phrase_id, seed: branches.append((phrase_id, seed)))
    page.restoreRequested.connect(restored.append)

    page.selection_notes.setPlainText("Keep the return recognisable.")
    page.audition_target.setCurrentIndex(page.audition_target.findData("candidate"))
    page.audition_context.setCurrentIndex(
        page.audition_context.findData("after_predecessor")
    )
    page.render_audition_button.click()
    assert requested == [("candidate", "after_predecessor")]

    page.freeze_button.click()
    assert frozen == [
        (batch.candidates[0].candidate_id, "Keep the return recognisable.")
    ]

    freeze_record = {
        "candidate_id": batch.candidates[0].candidate_id,
        "frozen_event_ids": list(batch.candidates[0].target_event_ids),
    }
    frozen_score = batch.candidates[0].candidate_score
    metadata = {
        **frozen_score.metadata,
        "m28_phrase_freezes": {"phrase-main": freeze_record},
    }
    from dataclasses import replace
    page.set_score(replace(frozen_score, metadata=metadata), selected_phrase_id="phrase-main")
    assert page.branch_button.isEnabled()
    assert page.restore_button.isEnabled()
    assert not page.delete_phrase_button.isEnabled()
    page.branch_button.click()
    page.restore_button.click()
    assert branches == [("phrase-main", page.seed.text())]
    assert restored == ["phrase-main"]
    page.close()


def test_main_window_phrase_workbench_freeze_and_restore_preserve_project_score():
    _application()
    window = MainWindow()
    window.project = _project()
    initial = window.project.to_score()
    window.phrase_workbench.set_score(initial)

    window._phrase_save_requested({
        "phrase_id": "phrase-ui",
        "start_beats": "0",
        "end_beats": "4",
        "function": "presentation",
        "custom_function": None,
        "state": "closed",
        "motif_ids": ["motif-ui"],
        "roles": ["melody"],
    })
    edited = window.project.to_score()
    phrase = next(
        item for item in PhrasePlan.from_score(edited).phrases
        if item.phrase_id == "phrase-ui"
    )
    assert phrase.event_ids == ("phrase-lead-01", "phrase-lead-02")
    assert phrase.start_beats == Fraction(0)
    assert phrase.end_beats == Fraction(4)

    candidate = build_phrase_candidate_batch(
        edited, "phrase-ui", count=1, root_seed=8,
        operations=("transposition",), batch_id="main-window-freeze",
    ).candidates[0]
    window._phrase_candidates = {candidate.candidate_id: candidate}
    window._phrase_freeze_requested(candidate.candidate_id, "Selected in the Workbench.")
    frozen = window.project.to_score()
    record = frozen.metadata["m28_phrase_freezes"]["phrase-ui"]
    assert record["candidate_id"] == candidate.candidate_id
    assert record["selection_note"] == "Selected in the Workbench."

    window._phrase_restore_requested("phrase-ui")
    restored = window.project.to_score()
    assert "phrase-ui" not in restored.metadata["m28_phrase_freezes"]
    for event_id in phrase.event_ids:
        original = next(item for item in edited.events if item.event_id == event_id)
        actual = next(item for item in restored.events if item.event_id == event_id)
        assert actual.to_dict() == original.to_dict()
    window.close()


def test_main_window_registers_phrase_workbench_without_shifting_existing_workspace_ids():
    app = _application()
    window = MainWindow()
    assert window.workspace_stack.count() == 7
    expected = ["GENERATOR", "BREAK LAB", "STEM MIXER", "FX LAB", "LIBRARY", "VARIATION BROWSER"]
    for index, title in enumerate(expected):
        window._set_workspace(index)
        assert window.workspace_title.text() == title
    window._set_workspace(6)
    assert window.workspace_title.text() == "PHRASE WORKBENCH"
    assert window.workspace_stack.currentWidget() is window.phrase_workbench
    assert window.navigator._workspace_items[6] is not None
    window.close()
    app.processEvents()
