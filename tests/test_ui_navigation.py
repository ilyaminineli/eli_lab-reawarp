import os
from fractions import Fraction

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
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
    expected_titles = [
        "GENERATOR", "BREAK LAB", "STEM MIXER", "FX LAB", "LIBRARY",
        "VARIATION BROWSER", "PHRASE WORKBENCH",
    ]

    for index, expected_title in enumerate(expected_titles):
        window._set_workspace(index)
        assert window.workspace_stack.currentIndex() == index
        assert window.workspace_title.text() == expected_title
        assert window.navigator.currentItem() is window.navigator._workspace_items[index]
        assert window.transport_bar.isHidden() is (index not in (0, 2, 5))

    window.navigator.itemClicked.emit(window.navigator._workspace_items[4], 0)
    assert window.workspace_stack.currentIndex() == 4
    assert "NO COMPOSITION" in window.project_context.text()

    window._set_workspace(99)
    assert window.workspace_stack.currentIndex() == 4
    window.close()
    app.processEvents()



def test_m23_variation_browser_blind_selection_notes_actions_and_batch_requests():
    _application()
    from reawarp.ui.pages.variations import VariationBrowserPage
    from reawarp.variations import VariationCandidateRecord

    page = VariationBrowserPage()
    page.set_stems(("kick", "snare", "melody"))
    requested = []
    actions = []
    notes = []
    selections = []
    page.batchRequested.connect(requested.append)
    page.candidateAction.connect(lambda action, candidate_id: actions.append((action, candidate_id)))
    page.notesChanged.connect(lambda candidate_id, note: notes.append((candidate_id, note)))
    page.candidateSelected.connect(selections.append)

    page._request_batch()
    assert requested[0]["mode"] == "stems"
    assert requested[0]["targets"] == ["melody"]
    assert requested[0]["count"] == 4

    def record(candidate_id, index):
        return VariationCandidateRecord(
            candidate_id=candidate_id, batch_id="ui-batch", index=index,
            label=f"Candidate {index:02d}", mode="stems", targets=("melody",),
            base_project_fingerprint="a" * 64, parent_candidate_id=None,
            root_seed=11, variation_seed=100 + index, seed_lineage={},
            changed_parameters={"targets": ["melody"]},
        )

    page.set_candidates([record("candidate-one", 1), record("candidate-two", 2)])
    assert page.candidates.item(0).text() == "CANDIDATE A"
    page.candidates.setCurrentRow(1)
    assert selections[-1] == "candidate-two"
    page.notes.setPlainText("Keep the negative space in the second half.")
    assert notes[-1] == (
        "candidate-two", "Keep the negative space in the second half."
    )
    page.keep_button.click()
    assert actions[-1] == ("kept", "candidate-two")
    page.blind.setChecked(False)
    assert "Candidate 02" in page.candidates.currentItem().text()
    page.reveal.setChecked(True)
    assert "melody" in page.details.text()

    page.mode.setCurrentIndex(page.mode.findData("sound_object"))
    page.set_sound_objects((("metal-impact", "Metal Impact"),))
    assert page.targets.item(0).data(Qt.ItemDataRole.UserRole) == "metal-impact"
    page._request_batch()
    assert requested[-1]["mode"] == "sound_object"
    assert requested[-1]["targets"] == ["metal-impact"]
    page.close()


def test_m23_sound_object_library_target_renders_with_separate_processing_identity(tmp_path, monkeypatch):
    _application()
    import threading
    from reawarp import GenerationConfig, ReawarpEngine
    from reawarp.library.store import SampleLibrary
    from reawarp.synthesis.sound_object import SoundObjectLayer, SoundObjectPatch, SoundObjectSource
    from reawarp.variations import VariationRequest

    patch = SoundObjectPatch(
        patch_id="metal-impact", name="Metal Impact", sample_rate=8_000, seed=51,
        source_identity_id="source:metal-impact",
        processing_identity_id="process:modal-body",
        sources=(SoundObjectSource(
            "osc", source_kind="procedural", sample_rate=8_000, source_model="sine",
        ),),
        layers=(SoundObjectLayer("body", "body", "osc", 0, 1024, gain=0.5),),
        pitch_model={"kind": "resonant", "frequency_hz": 330.0},
    )
    database = tmp_path / "objects.sqlite3"
    monkeypatch.setattr(
        "reawarp.library.store.default_database_path", lambda: database
    )
    with SampleLibrary(database) as library:
        library.save_sound_object(patch)

    config = GenerationConfig(
        duration=5.0, sample_rate=22_050, seed="m23-sound-object-ui",
        complexity=0.2, include_texture=False, include_ambience=False,
    )
    base = ReawarpEngine().generate(config)
    window = MainWindow()
    request = VariationRequest(
        mode="sound_object", targets=("metal-impact",), count=1
    )
    variant = window._render_sound_object_candidate(
        base, 1, 1_200_004, request, threading.Event()
    )
    variant_info = variant.metadata["sound_object_variants"][0]
    assert variant_info["source_identity_id"] == "source:metal-impact"
    assert variant_info["processing_identity_id"] != "process:modal-body"
    assert variant.sample_rate == base.sample_rate
    assert variant_info["stem"] in variant.stems
    assert variant.stems[variant_info["stem"]].shape == base.stems["kick"].shape
    assert variant.to_score().metadata["render_stems"] == list(variant.stems)
    window.close()


def test_m23_variation_browser_cancel_button_emits_cooperative_cancel_request():
    _application()
    from reawarp.ui.pages.variations import VariationBrowserPage

    page = VariationBrowserPage()
    requested = []
    page.cancelRequested.connect(lambda: requested.append(True))
    page.set_batch_busy(True)
    assert page.cancel_button.isEnabled()
    page.cancel_button.click()
    assert requested == [True]
    page.set_batch_busy(False)
    assert not page.cancel_button.isEnabled()
    page.close()


def test_m23_promote_and_restore_recover_candidate_without_mutating_frozen_base():
    _application()
    from reawarp import GenerationConfig, ReawarpEngine
    from reawarp.variations import (
        VariationCandidate, VariationCandidateRecord, clone_project, project_fingerprint,
    )

    config = GenerationConfig(
        duration=5.0, sample_rate=22_050, seed="m23-ui-recovery",
        complexity=0.2, include_texture=False, include_ambience=False,
    )
    engine = ReawarpEngine()
    base = engine.generate(config)
    candidate_project = engine.generate_variant(
        config, "melody", 1_000_000_071, base_project=base
    )
    candidate_id = "m23-ui-candidate"
    record = VariationCandidateRecord(
        candidate_id=candidate_id, batch_id="m23-ui-batch", index=1,
        label="Candidate 01", mode="stems", targets=("melody",),
        base_project_fingerprint=project_fingerprint(base), parent_candidate_id=None,
        root_seed=config.seed, variation_seed=1_000_000_071, seed_lineage={},
        changed_parameters={"targets": ["melody"]},
    )
    window = MainWindow()
    window.project = base
    window._variation_origin_project = clone_project(base, readonly=True)
    window._variation_base_project = window._variation_origin_project
    window._variation_candidates[candidate_id] = VariationCandidate(
        record, candidate_project
    )
    accepted = []
    window._render_finished = accepted.append

    frozen_fingerprint = project_fingerprint(base)
    window._variation_candidate_action("promoted", candidate_id)
    assert window._variation_active_candidate_id == candidate_id
    assert accepted[-1] is not base
    np.testing.assert_array_equal(
        accepted[-1].stems["melody"], candidate_project.stems["melody"]
    )
    assert project_fingerprint(base) == frozen_fingerprint

    window._variation_candidate_action("restore", "base")
    assert window._variation_active_candidate_id is None
    assert project_fingerprint(accepted[-1]) == frozen_fingerprint
    assert project_fingerprint(base) == frozen_fingerprint
    window.close()


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

    editor._begin_preview_edit()
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



def test_m22_fx_editor_starts_with_role_auto_routing_and_exposes_send_taps():
    _application()
    from reawarp.ui.pages.fx_routing import FXRoutingEditor

    editor = FXRoutingEditor()
    editor.set_stems(
        ("kick", "snare", "hats", "synthetic_break", "melody", "noise_texture", "ambience"),
        48_000,
    )
    route = editor.routing()
    assert route["schema_version"] == 3
    assert route["routing_mode"] == "role_auto"
    assert route["stems"]["kick"]["insert"]["kind"] == "bypass"
    assert route["stems"]["kick"]["sends"] == {"space": 0.0, "echo": 0.0}
    assert route["stems"]["melody"]["sends"]["space"] > 0.0
    assert editor.match_audition_level() is True
    editor.match_level_checkbox.setChecked(False)
    assert editor.match_audition_level() is False
    editor.match_level_checkbox.setChecked(True)

    taps = []
    editor.auditionRequested.connect(lambda stage, stem: taps.append((stage, stem)))
    editor.send_taps["space"].setCurrentIndex(
        editor.send_taps["space"].findData("pre_insert_pre_fader")
    )
    assert editor.routing()["stems"]["kick"]["send_taps"]["space"] == "pre_insert_pre_fader"
    assert editor.routing()["routing_mode"] == "manual"

    editor._apply_dry_routing()
    assert editor.routing()["routing_mode"] == "manual"
    assert all(
        value == 0.0
        for route in editor.routing()["stems"].values()
        for value in route["sends"].values()
    )
    editor._apply_auto_routing()
    assert editor.routing()["routing_mode"] == "role_auto"

    editor.audition_stage.setCurrentIndex(editor.audition_stage.findData("master"))
    editor._request_audition()
    assert taps == [("master", "master")]
    editor.set_meter_report({
        "direct": {"kick": {"peak_dbfs": -20.0, "rms_dbfs": -30.0,
                            "crest_factor_db": 10.0, "headroom_db": 20.0}},
        "master": {"peak_dbfs": -8.0, "rms_dbfs": -18.0,
                   "crest_factor_db": 10.0, "headroom_db": 8.0},
    })
    assert "MASTER" in editor.meter_report.text()
    editor.close()


def test_m22_cancellable_worker_emits_result_and_honours_cancel():
    _application()
    from reawarp.ui.workers import CancellableRenderWorker

    completed = []
    failed = []
    worker = CancellableRenderWorker(lambda cancel: {"cancelled": cancel.is_set()})
    worker.signals.finished.connect(completed.append)
    worker.signals.error.connect(failed.append)
    worker.run()
    assert completed == [{"cancelled": False}]
    assert failed == []

    cancelled = CancellableRenderWorker(lambda cancel: "work")
    cancelled.signals.error.connect(failed.append)
    cancelled.cancel()
    cancelled.run()
    assert failed and failed[-1].startswith("CANCELLED:")
