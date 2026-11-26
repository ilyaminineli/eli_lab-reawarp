from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject
from reawarp.composition.brief import (
    CompositionBrief,
    quick_mutation_contracts,
)
from reawarp.ui.pages.composition_intent import CompositionIntentEditor


_APP = None


def _application():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
        app = _APP
    return app


def _config():
    return GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m27-project-roundtrip",
        complexity=0.25,
        include_melody=False,
        include_texture=False,
        include_ambience=False,
    )


def test_engine_resolves_brief_and_records_mutation_audit_in_project(tmp_path):
    config = _config()
    brief = CompositionBrief(
        brief_id="machine-pulse",
        artistic_question="Can a fixed pulse tolerate unstable surroundings?",
        mutation_contracts=quick_mutation_contracts(("arrangement_density", "complexity")),
    )
    project = ReawarpEngine().generate(
        config,
        composition_brief=brief,
        bounded_exploration=True,
    )

    assert project.metadata["m27_composition_brief"] == brief.to_dict()
    assert project.metadata["m27_resolved_intent"]["brief_fingerprint"] == brief.fingerprint
    exploration = project.metadata["m27_bounded_exploration"]
    assert set(exploration["field_changes"]) == {"arrangement_density", "complexity"}
    assert project.config.seed == config.seed
    assert project.config.sample_rate == config.sample_rate
    assert project.composition_brief.fingerprint == brief.fingerprint

    output = project.export(tmp_path / "m27-project", bit_depth=24)
    reopened = ReawarpProject.load(output)
    assert reopened.composition_brief.to_dict() == brief.to_dict()
    assert reopened.metadata["m27_resolved_intent"] == project.metadata["m27_resolved_intent"]
    assert reopened.metadata["m27_bounded_exploration"] == exploration


def test_generation_without_a_brief_stays_legacy_and_does_not_write_back_one(tmp_path):
    project = ReawarpEngine().generate(_config())
    assert "m27_composition_brief" not in project.metadata
    assert project.composition_brief.authorship == "legacy"
    output = project.export(tmp_path / "legacy-project", bit_depth=24)
    reopened = ReawarpProject.load(output)
    assert "m27_composition_brief" not in reopened.metadata
    assert reopened.composition_brief.authorship == "legacy"


def test_generator_intent_editor_round_trips_materials_permissions_and_pitch_world():
    app = _application()
    editor = CompositionIntentEditor()
    editor.brief_id.setText("editor-study")
    editor.artistic_question.setText("How does the anchor survive?")
    editor.listening_mode.setText("close listening")
    editor.material_labels["A"].setText("Dry pulse")
    editor.material_roles["A"].setCurrentIndex(
        editor.material_roles["A"].findData("kick")
    )
    editor.material_labels["B"].setText("Metal answer")
    editor.anchor_kind.setCurrentIndex(editor.anchor_kind.findData("motif"))
    editor.anchor_material.setCurrentIndex(editor.anchor_material.findData("A"))
    editor.anchor_description.setText("The pulse remains identifiable.")
    editor.ending_mode.setCurrentIndex(editor.ending_mode.findData("residue"))
    editor.pitch_scale.setCurrentText("whole_tone")
    editor.pitch_root.setCurrentIndex(editor.pitch_root.findData(3))
    editor.mutation_checks["arrangement_density"].setChecked(True)
    editor.bounded_exploration.setChecked(True)

    config = _config()
    brief = editor.build_brief(config)
    assert brief.materials[0].material_id == "A"
    assert brief.materials[0].source_asset_ids == ()
    assert brief.anchor.material_id == "A"
    assert brief.pitch_world.scale == "whole_tone"
    assert brief.pitch_world.root == 3
    assert brief.mutation_contracts[0].mutable_fields == ("arrangement_density",)

    # Dormant tempo/duration bounds are ignored unless those fields are granted permission.
    editor.bpm_min.setValue(120.0)
    editor.bpm_max.setValue(80.0)
    editor.duration_min.setValue(30.0)
    editor.duration_max.setValue(20.0)
    assert editor.build_brief(config).tempo_form_policy.bpm_bounds == (60.0, 220.0)
    assert editor.build_brief(config).tempo_form_policy.duration_bounds == (5.0, 180.0)

    restored = CompositionIntentEditor()
    restored.set_brief(brief, exploration_enabled=True)
    assert restored.has_user_content()
    assert restored.exploration_enabled() is True
    assert restored.build_brief(config).to_dict() == brief.to_dict()
    editor.close()
    restored.close()
    app.processEvents()
