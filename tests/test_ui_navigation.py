import os
from fractions import Fraction

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.ui.main_window import MainWindow
from reawarp.ui.navigation import WorkspaceNavigator
from reawarp.ui.pages.score_automation import ScoreAutomationEditor


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def test_navigator_supports_nested_groups_and_emits_only_workspace_selections():
    _application()
    navigator = WorkspaceNavigator([
        ("COMPOSE", [
            ("Generator", "Compose a new project.", 0),
            ("Break Lab", "Transform break material.", 1),
        ]),
    ])
    selected = []
    navigator.workspaceSelected.connect(selected.append)

    navigator.register_workspace(
        ("COMPOSE", "GENERATOR", "ADVANCED"),
        "Motif Lab",
        "Inspect and transform shared motifs.",
        2,
    )
    assert navigator.workspace_count() == 3
    assert navigator.topLevelItemCount() == 1

    navigator.itemClicked.emit(navigator._workspace_items[2], 0)
    assert selected == [2]
    navigator.itemClicked.emit(navigator._group_items[("COMPOSE",)], 0)
    assert selected == [2]

    navigator.select_workspace(1)
    assert navigator.currentItem() is navigator._workspace_items[1]
    assert selected == [2]

    with pytest.raises(ValueError, match="already registered"):
        navigator.register_workspace(("COMPOSE",), "Duplicate", "Invalid", 1)


def test_main_window_navigation_keeps_workspace_stack_and_transport_in_sync():
    app = _application()
    window = MainWindow()
    expected_titles = ["GENERATOR", "BREAK LAB", "STEM MIXER", "FX LAB", "LIBRARY"]

    for index, expected_title in enumerate(expected_titles):
        window._set_workspace(index)
        assert window.workspace_stack.currentIndex() == index
        assert window.workspace_title.text() == expected_title
        assert window.navigator.currentItem() is window.navigator._workspace_items[index]
        assert window.transport_bar.isHidden() is (index not in (0, 2))

    window.navigator.itemClicked.emit(window.navigator._workspace_items[4], 0)
    assert window.workspace_stack.currentIndex() == 4
    assert "NO COMPOSITION" in window.project_context.text()

    window._set_workspace(99)
    assert window.workspace_stack.currentIndex() == 4
    window.close()
    app.processEvents()



def test_m18_score_automation_editor_builds_scoped_source_connections():
    _application()
    editor = ScoreAutomationEditor()
    score = Score(
        title="UI automation fixture",
        events=(
            MusicalEvent(
                "event-001", "melody", Fraction(0), Fraction(1),
                frequency_hz=440.0, parameters={"section_id": "development"},
            ),
            MusicalEvent(
                "event-002", "bass", Fraction(1), Fraction(1),
                frequency_hz=110.0, parameters={"section_id": "verse"},
            ),
        ),
    )
    editor.set_score(score)
    editor.scope.setCurrentIndex(editor.scope.findData("role"))
    assert [editor.scope_id.itemText(i) for i in range(editor.scope_id.count())] == [
        "bass", "melody"
    ]
    editor.scope.setCurrentIndex(editor.scope.findData("section"))
    assert [editor.scope_id.itemText(i) for i in range(editor.scope_id.count())] == [
        "development", "verse"
    ]
    editor.scope.setCurrentIndex(editor.scope.findData("event"))
    assert editor.scope_id.count() == 2
    editor.target.setCurrentIndex(editor.target.findData("synth.pitch"))
    editor.source_kind.setCurrentIndex(editor.source_kind.findData("lfo"))
    editor.lfo_waveform.setCurrentIndex(editor.lfo_waveform.findData("triangle"))
    editor.scope.setCurrentIndex(editor.scope.findData("role"))
    editor.scope_id.setCurrentText("melody")
    editor.retrigger.setCurrentIndex(editor.retrigger.findData("event"))
    editor.amount.setValue(3.0)

    editor._add_control()
    updated = editor.updated_score(score)

    assert len(updated.automation_sources) == 1
    assert len(updated.modulations) == 1
    assert updated.automation_sources[0].parameters["waveform"] == "triangle"
    assert updated.modulations[0].destination_target_id == "synth.pitch"
    assert updated.modulations[0].scope == "role"
    assert updated.modulations[0].scope_id == "melody"
    assert updated.modulations[0].retrigger == "event"
    assert editor.apply_button.isEnabled()
    assert len(editor.preview._values) > 2

    editor._remove_control()
    assert editor.updated_score(score).automation_sources == ()
    assert editor.updated_score(score).modulations == ()

    editor.source_kind.setCurrentIndex(editor.source_kind.findData("phrase_curve"))
    editor.source_values.setText("0.0, 0.35, 1.0, 0.2")
    editor._add_control()
    curve_score = editor.updated_score(score)
    assert curve_score.automation_sources[0].parameters["values"] == [
        0.0, 0.35, 1.0, 0.2
    ]
    editor._remove_control()
    assert editor.updated_score(score).automation_sources == ()


def test_mixer_includes_separate_fx_and_score_control_editors():
    _application()
    window = MainWindow()
    assert window.fx_workspace_tabs.count() == 3
    assert window.fx_workspace_tabs.tabText(1) == "FX AUTOMATION"
    assert window.fx_workspace_tabs.tabText(2) == "SCORE CONTROL"
    window.close()


def test_m18_score_control_exposes_live_planner_synth_and_fx_destinations():
    _application()
    score = Score(
        title="M18 FX target fixture",
        metadata={"render_stems": ["kick", "melody"]},
    )
    editor = ScoreAutomationEditor()
    editor.set_score(score)
    targets = {
        editor.target.itemData(index)
        for index in range(editor.target.count())
    }

    assert {
        "role.density",
        "role.syncopation",
        "role.articulation",
        "synth.wavetable.position",
        "synth.partial.balance",
        "synth.grain.size",
        "synth.grain.position",
        "synth.grain.density",
        "stem.kick.insert_wet",
        "stem.melody.send.space",
        "stem.melody.send.echo",
        "bus.space.wet",
        "bus.echo.wet",
    }.issubset(targets)

    editor.target.setCurrentIndex(editor.target.findData("stem.melody.insert_wet"))
    assert editor.scope.currentData() == "global"
    assert not editor.scope.isEnabled()
    editor._add_control()
    assert not editor.scope.isEnabled()
    modulation = editor.updated_score(score).modulations[0]
    assert modulation.destination_target_id == "stem.melody.insert_wet"
    assert modulation.scope == "global"
    assert modulation.scope_id is None
    editor.close()


def test_m18_curve_preview_points_are_editable_only_for_curve_sources():
    _application()
    editor = ScoreAutomationEditor()
    editor.source_kind.setCurrentIndex(editor.source_kind.findData("phrase_curve"))
    editor.source_values.setText("0.0, 0.5, 1.0")
    editor._draft_source_preview_changed()
    assert editor.preview._editable is True
    assert editor.preview._values == (0.0, 0.5, 1.0)
    editor.source_kind.setCurrentIndex(editor.source_kind.findData("lfo"))
    assert editor.preview._editable is False
    editor.close()


def test_m18_score_control_can_edit_existing_curves_and_undo_the_change():
    _application()
    editor = ScoreAutomationEditor()
    score = Score(title="Curve editing fixture")
    editor.set_score(score)
    editor.source_kind.setCurrentIndex(editor.source_kind.findData("phrase_curve"))
    editor.source_values.setText("0.0, 0.4, 1.0")
    editor._add_control()

    editor._preview_values_changed([0.0, 0.8, 0.2])
    updated = editor.updated_score(score)
    assert updated.automation_sources[0].parameters["values"] == [0.0, 0.8, 0.2]
    assert editor.undo_button.isEnabled()

    editor._undo()
    reverted = editor.updated_score(score)
    assert reverted.automation_sources[0].parameters["values"] == [0.0, 0.4, 1.0]
    editor._clear_controls()
    assert editor.updated_score(score).automation_sources == ()
    editor._undo()
    assert len(editor.updated_score(score).automation_sources) == 1
    editor.close()


def test_m18_score_control_templates_populate_reviewable_source_drafts():
    _application()
    editor = ScoreAutomationEditor()
    editor.set_score(Score(title="Template fixture"))
    editor.template.setCurrentIndex(editor.template.findData("Slow filter sweep"))
    editor._apply_template()

    assert editor.target.currentData() == "synth.cutoff"
    assert editor.source_kind.currentData() == "lfo"
    assert editor.lfo_waveform.currentData() == "triangle"
    assert editor.scope.currentData() == "global"
    assert editor.period.value() == pytest.approx(16.0)
    assert editor.end_beat.value() == pytest.approx(64.0)
    editor.close()
