from __future__ import annotations

import os
from fractions import Fraction
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from reawarp.composition.arrangement import create_arrangement
from reawarp.composition.phrases import PhrasePlan, PhraseSpan
from reawarp.composition.transitions import (
    TransitionPhase, TransitionPlan, compile_transition_plans,
)
from reawarp.score import MusicalEvent, Score
from reawarp.ui.pages.arrangement_editor import ArrangementEditorPage

_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def _score():
    score = Score(
        title="M33 UI fixture",
        events=(
            MusicalEvent("event-a", "lead", 1, 1, pitch=60),
            MusicalEvent("event-b", "lead", 5, 1, pitch=62),
        ),
    )
    return PhrasePlan(phrases=(
        PhraseSpan("phrase-a", 0, 4, "presentation", event_ids=("event-a",)),
        PhraseSpan("phrase-b", 4, 8, "continuation", event_ids=("event-b",)),
    )).attach_to_score(score)


def test_arrangement_editor_emits_edit_and_checklist_actions():
    _application()
    page = ArrangementEditorPage()
    source = _score()
    page.set_score(source)
    assert page.create_button.isEnabled()

    created = []
    page.createRequested.connect(lambda: created.append(True))
    page.create_button.click()
    assert created == [True]

    arranged = create_arrangement(source)
    page.set_score(arranged)
    assert page.items.count() == 2
    assert page.move_button.isEnabled()
    clip_id = page.selected_clip_id
    assert clip_id is not None

    moves, duplicates, trims, reorder, mute, freeze, prints = [], [], [], [], [], [], []
    page.moveRequested.connect(lambda *args: moves.append(args))
    page.duplicateRequested.connect(lambda *args: duplicates.append(args))
    page.trimRequested.connect(lambda *args: trims.append(args))
    page.reorderRequested.connect(lambda *args: reorder.append(args))
    page.muteRequested.connect(lambda *args: mute.append(args))
    page.freezeRequested.connect(freeze.append)
    page.printRequested.connect(prints.append)

    page.move_to.setText("3/2")
    page.move_button.click()
    assert moves == [(clip_id, "3/2")]
    page.duplicate_at.setText("12")
    page.duplicate_button.click()
    assert duplicates == [(clip_id, "12")]
    page.trim_start.setText("1")
    page.trim_end.setText("3")
    page.trim_button.click()
    assert trims == [(clip_id, "1", "3")]
    page.mute_button.click()
    assert mute == [(clip_id, True)]
    page.freeze_button.click()
    page.print_button.click()
    assert freeze == [clip_id]
    assert prints == [clip_id]

    checklist = []
    page.checklistChanged.connect(lambda *args: checklist.append(args))
    page.checks["mono"].click()
    assert checklist == [("mono", True)]
    page.close()


def test_arrangement_editor_filters_candidate_replacement_by_phrase():
    _application()
    page = ArrangementEditorPage()
    arranged = create_arrangement(_score())
    page.set_score(arranged)
    selected = page.selected_clip_id
    page.set_candidates([
        SimpleNamespace(
            phrase_id="phrase-a", candidate_id="candidate-a", operation="transposition",
        ),
        SimpleNamespace(
            phrase_id="phrase-b", candidate_id="candidate-b", operation="fragmentation",
        ),
    ])
    replace_actions = []
    page.replaceRequested.connect(lambda *args: replace_actions.append(args))
    assert page.candidate.count() == 1
    assert page.candidate.currentData() == "candidate-a"
    page.replace_button.click()
    assert replace_actions == [(selected, "candidate-a")]
    page.close()


def test_arrangement_editor_exposes_m30_relink_choices_for_selected_cue():
    _application()
    score = _score()
    transition = TransitionPlan(
        transition_id="ui-transition",
        source_phrase_id="phrase-a",
        target_phrase_id="phrase-b",
        transition_type="additive",
        phases=(
            TransitionPhase("preparation", 2, 3),
            TransitionPhase("change", 3, 4),
            TransitionPhase("arrival", 4, 5),
        ),
        changed_dimensions=("roles",),
        preserved_dimensions=("motif",),
        participating_roles=("lead",),
        source_state={},
        target_state={},
        seed_name="ui-relink",
        seed=4,
    )
    page = ArrangementEditorPage()
    page.set_score(create_arrangement(compile_transition_plans(score, (transition,))))
    cue_item = next(
        page.items.item(index)
        for index in range(page.items.count())
        if page.items.item(index).data(Qt.ItemDataRole.UserRole + 1) == "transition"
    )
    page.items.setCurrentItem(cue_item)
    assert page.transition_source.currentData() == "phrase-a"
    assert page.transition_target.currentData() == "phrase-b"

    requests = []
    page.relinkTransitionRequested.connect(lambda *args: requests.append(args))
    page.transition_source.setCurrentIndex(
        page.transition_source.findData("phrase-b")
    )
    page.transition_target.setCurrentIndex(
        page.transition_target.findData("phrase-a")
    )
    page.relink_button.click()
    assert requests == [("ui-transition", "phrase-b", "phrase-a")]
    page.close()
