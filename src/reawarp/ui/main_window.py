"""M4 desktop instrument: generation, break lab, playback, and stem mixing."""

from __future__ import annotations

import copy
import json
import logging
import secrets
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer, QThreadPool, QEvent
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSystemTrayIcon, QStackedWidget, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject
from reawarp.composition.director import STRUCTURES
from reawarp.composition.patterns import PATTERN_FAMILIES, PATTERN_RELATIONSHIPS
from reawarp.export.project_archive import export_project_package
from reawarp.fx_routing import (
    build_fx_variation_routings, match_audition_level, measure_signal,
    render_fx_routing, render_master_with_returns,
)
from reawarp.fx_automation import (
    attach_fx_automation_to_score, fx_automation_registry,
)
from reawarp.score.render import build_score_control_bus
from reawarp.samples.io import read_sample
from reawarp.samples.catalog import (
    classify_sample_role, default_sample_for_role, discover_bundled_samples,
    sample_library_counts,
)
from reawarp.mathematics.theory import ROOT_NAMES, SCALE_STEPS
from reawarp.synthesis.profiles import (
    HAT_PROFILES, KICK_PROFILES, MELODY_PROFILES, SNARE_PROFILES,
    SUBTRACTIVE_VOICES,
)
from reawarp.transforms import BREAK_TRANSFORMS, auto_slice
from reawarp.ui.audio_player import AudioPlayer
from reawarp.ui.pages.fx_lab import FxLabPage
from reawarp.ui.pages.fx_automation import FXAutomationEditor
from reawarp.ui.pages.fx_routing import FXRoutingEditor
from reawarp.ui.pages.score_automation import ScoreAutomationEditor
from reawarp.ui.pages.library import LibraryPage
from reawarp.ui.pages.variations import VariationBrowserPage
from reawarp.ui.navigation import WorkspaceNavigator
from reawarp.ui.theme import APP_STYLE
from reawarp.ui.widgets.audio_preview import AudioPreview
from reawarp.ui.widgets.stem_row import StemRow
from reawarp.ui.workers import CancellableRenderWorker
logger = logging.getLogger("reawarp.ui")

from reawarp.variations import (
    VariationBatch, VariationBatchService, VariationCandidate, VariationCandidateRecord, VariationRequest,
    build_listening_set, clone_project, matched_ab, project_audio,
    project_fingerprint, variation_session_metadata,
)


class MainWindow(QMainWindow):
    """First production-oriented Reawarp desktop application."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reawarp — 再変形")
        self.resize(1440, 920)
        self.setMinimumSize(1024, 640)
        self.setStyleSheet(APP_STYLE)

        self.project: ReawarpProject | None = None
        self._break_path: str | None = None
        self._break_audio: np.ndarray | None = None
        self._worker: CancellableRenderWorker | None = None
        self._export_worker: CancellableRenderWorker | None = None
        self._pending_export_destination: Path | None = None
        self._variation_counts: dict[str, int] = {}
        self._variation_origin_project: ReawarpProject | None = None
        self._variation_base_project: ReawarpProject | None = None
        self._variation_parent_candidate_id: str | None = None
        self._variation_active_candidate_id: str | None = None
        self._variation_candidates: dict[str, VariationCandidate] = {}
        self._variation_branch_base: ReawarpProject | None = None
        self._variation_batch_worker: CancellableRenderWorker | None = None
        self._variation_compare_worker: CancellableRenderWorker | None = None
        self._variation_compare_signature: tuple[str, str] | None = None
        self._variation_ab_buffers: dict[str, np.ndarray] = {}
        self._variation_listening_buffers: dict[str, np.ndarray] = {}
        self._variation_session_epoch = 0
        self._mix_rows: dict[str, StemRow] = {}
        self._fx_processed_stems: dict[str, np.ndarray] = {}
        self._fx_bus_returns: dict[str, np.ndarray] = {}
        self._fx_routing_metadata: dict[str, Any] = {}
        self._fx_audition_audio: dict[str, Any] = {}
        self._fx_worker: CancellableRenderWorker | None = None
        self._fx_pending_signature: str | None = None
        self._fx_variation_worker: CancellableRenderWorker | None = None
        self._fx_variation_renders: dict[str, dict[str, Any]] = {}
        self._fx_variation_cache_dir: Path | None = None
        self._fx_variation_signature: str | None = None
        self._fx_queued_signature: str | None = None
        self._fx_project_revision = 0
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self._tray_icon: QSystemTrayIcon | None = None
        self.player = AudioPlayer(self)
        self.player.finished.connect(self._playback_finished)

        self._build_interface()
        self._build_tray_icon()
        self._refresh_devices()

        # Coalesce rapid mixer changes so the visual analysis is not rebuilt for
        # every slider tick. The timer runs on the GUI clock, never the audio clock.
        self._preview_refresh_timer = QTimer(self)
        self._preview_refresh_timer.setSingleShot(True)
        self._preview_refresh_timer.setInterval(80)
        self._preview_refresh_timer.timeout.connect(self._apply_preview_refresh)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_transport)
        self._timer.start()

    def _build_interface(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        app_header = QFrame()
        app_header.setObjectName("header")
        app_header_layout = QHBoxLayout(app_header)
        app_header_layout.setContentsMargins(20, 9, 20, 9)
        brand = QLabel("再変形")
        brand.setObjectName("brand")
        app_header_layout.addWidget(brand)
        subtitle = QLabel("REAWARP  /  MATHEMATICAL AUDIO LAB")
        subtitle.setObjectName("muted")
        app_header_layout.addWidget(subtitle)
        app_header_layout.addStretch(1)
        self.header_state = QLabel("OFFLINE RENDER ENGINE")
        self.header_state.setObjectName("sectionTitle")
        app_header_layout.addWidget(self.header_state)
        root_layout.addWidget(app_header)

        # One shared transport serves the current composition in the workspaces
        # where project audition is the primary task. FX Lab keeps its own A/B
        # source/result controls while using the same underlying audio player.
        self.transport_bar = self._build_transport_bar()

        generator_page = self._build_generator_page()
        break_page = self._build_break_page()
        mixer_page = self._build_mixer_page()
        self.fx_lab_page = FxLabPage(self.player, self)
        self.fx_lab_page.applyChainRequested.connect(self._apply_fx_lab_chain_to_stem)
        self.library_page = LibraryPage(self)
        self.library_page.sampleSelected.connect(self._accept_library_sample)
        self.variation_page = VariationBrowserPage(self)
        self.variation_page.batchRequested.connect(self._start_variation_batch)
        self.variation_page.cancelRequested.connect(self._cancel_variation_batch)
        self.variation_page.candidateSelected.connect(self._variation_candidate_selected)
        self.variation_page.candidateAction.connect(self._variation_candidate_action)
        self.variation_page.notesChanged.connect(self._variation_notes_changed)
        self.variation_page.compareRequested.connect(self._variation_compare)
        self.variation_page.listeningSetRequested.connect(self._variation_listening_set)
        self.variation_page.auditionRequested.connect(self._variation_audition)
        self.variation_page.loadProjectRequested.connect(self._load_variation_project)
        self.variation_page.listeningItemRequested.connect(self._variation_listening_item)

        self.workspace_stack = QStackedWidget()
        # Keep the historical attribute as a small compatibility bridge for
        # code/tests that query the number of workspace pages.
        self.tabs = self.workspace_stack
        for workspace in (
            generator_page, break_page, mixer_page, self.fx_lab_page, self.library_page,
            self.variation_page,
        ):
            self.workspace_stack.addWidget(workspace)

        self._workspace_info = [
            ("GENERATOR", "Define form, rhythm, synthesis and source material."),
            ("BREAK LAB", "Analyse, transform and reuse break material in the composition."),
            ("STEM MIXER", "Shape the relationships between generated musical roles."),
            ("FX LAB", "Build reusable non-destructive processing chains and compare results."),
            ("LIBRARY", "Find, organise and reuse the sounds and variations in your Reawarp ecosystem."),
            ("VARIATION BROWSER", "Generate comparable candidates, audition matched A/B and preserve selection lineage."),
        ]
        self.navigator = WorkspaceNavigator(
            [
                ("COMPOSE", [
                    ("Generator", "Create the composition plan and its coordinated sound sources.", 0),
                    ("Break Lab", "Transform source breaks for use by the composition engine.", 1),
                    ("Variations", "Batch-generate candidates and compare them before choosing.", 5),
                ]),
                ("PRODUCE", [
                    ("Stem Mixer", "Balance generated roles and shared processing returns.", 2),
                    ("FX Lab", "Design and audition reusable offline effect chains.", 3),
                ]),
                ("ASSETS", [
                    ("Library", "Browse and organise reusable samples, stems and variations.", 4),
                ]),
            ]
        )
        self.navigator.workspaceSelected.connect(self._set_workspace)

        workspace_header = QFrame()
        workspace_header.setObjectName("workspaceHeader")
        header_layout = QVBoxLayout(workspace_header)
        header_layout.setContentsMargins(18, 9, 18, 8)
        title_row = QHBoxLayout()
        self.workspace_title = QLabel()
        self.workspace_title.setObjectName("workspaceTitle")
        title_row.addWidget(self.workspace_title)
        title_row.addStretch(1)
        self.project_context = QLabel()
        self.project_context.setObjectName("projectContext")
        self.project_context.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.project_context)
        header_layout.addLayout(title_row)
        self.workspace_description = QLabel()
        self.workspace_description.setObjectName("muted")
        self.workspace_description.setWordWrap(True)
        header_layout.addWidget(self.workspace_description)
        root_layout.addWidget(workspace_header)
        root_layout.addWidget(self.transport_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(12)
        body_layout.addWidget(self.navigator)
        body_layout.addWidget(self.workspace_stack, 1)
        root_layout.addWidget(body, 1)

        self.setCentralWidget(root)
        self._update_project_context()
        self._set_workspace(0)
        self.statusBar().showMessage(
            "Ready — one project, connected workspaces, deterministic offline rendering."
        )

    def _set_workspace(self, index: int) -> None:
        if not 0 <= int(index) < self.workspace_stack.count():
            return
        index = int(index)
        self.workspace_stack.setCurrentIndex(index)
        self.navigator.select_workspace(index)
        title, description = self._workspace_info[index]
        self.workspace_title.setText(title)
        self.workspace_description.setText(description)
        self.transport_bar.setVisible(index in (0, 2, 5))

    def _update_project_context(self) -> None:
        if self.project is None:
            self.project_context.setText(
                "NO COMPOSITION  ·  Generate a project to connect the production workspaces."
            )
            return
        self.project_context.setText(
            f"PROJECT READY  ·  {self.project.duration:.1f} s  ·  "
            f"{len(self.project.stems)} STEMS  ·  {self.project.sample_rate:,} Hz  ·  "
            f"SEED {self.project.config.seed}"
        )

    def _build_generator_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        panel = QWidget()
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(450)
        panel_layout = QVBoxLayout(panel)
        controls_page = QWidget()
        controls_layout = QVBoxLayout(controls_page)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)
        # Form, rhythm, source and voice controls are one connected workflow,
        # not separate feature tabs that hide the Generate action.
        form_layout = controls_layout
        voices_layout = controls_layout
        rhythm_layout = controls_layout

        global_group = QGroupBox("COMPOSITION FORM")
        form = QFormLayout(global_group)
        self.bpm = QDoubleSpinBox()
        self.bpm.setRange(60, 220)
        self.bpm.setDecimals(1)
        self.bpm.setSingleStep(0.5)
        self.bpm.setValue(137)
        form.addRow("Tempo / BPM", self.bpm)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(5, 180)
        self.duration.setToolTip("Offline composition duration, up to 180 seconds (3 minutes).")
        self.duration.setDecimals(1)
        self.duration.setSingleStep(0.5)
        self.duration.setValue(24)
        form.addRow("Duration / sec", self.duration)
        self.structure = QComboBox()
        self.structure.addItems(list(STRUCTURES))
        self.structure.setCurrentText("evolving")
        form.addRow("Formal trajectory", self.structure)
        self.composition_flow = QComboBox()
        self.composition_flow.addItems(["preset", "mix", "mutate"])
        self.composition_flow.setToolTip(
            "Preset keeps the selected form; mix borrows movements from another form; mutate reorders inner movements."
        )
        form.addRow("Structure flow", self.composition_flow)
        self.pattern_family = QComboBox()
        self.pattern_family.addItems(list(PATTERN_FAMILIES))
        self.pattern_family.setCurrentText("broken_funk")
        form.addRow("Pattern family", self.pattern_family)
        self.pattern_relationship = QComboBox()
        self.pattern_relationship.addItems(list(PATTERN_RELATIONSHIPS))
        self.pattern_relationship.setCurrentText("interlock")
        form.addRow("Pattern relationship", self.pattern_relationship)
        self.pattern_follow_structure = QCheckBox("Automatically evolve all drum parts")
        self.pattern_follow_structure.setChecked(True)
        self.pattern_follow_structure.setToolTip(
            "Kick, snare and hat patterns evolve with section functions. Returns recall the opening anchor; "
            "fills and phase changes stay bounded by the variation budget."
        )
        form.addRow("Drum arrangement", self.pattern_follow_structure)
        self.drum_change_intensity = QDoubleSpinBox()
        self.drum_change_intensity.setRange(0.0, 1.0)
        self.drum_change_intensity.setSingleStep(0.05)
        self.drum_change_intensity.setValue(0.68)
        self.drum_change_intensity.setToolTip(
            "How strongly drum roles mutate between sections and phrase cycles."
        )
        form.addRow("Drum evolution", self.drum_change_intensity)
        self.drum_part_cycle_bars = QComboBox()
        for bars in (1, 2, 4):
            self.drum_part_cycle_bars.addItem(f"{bars} bar" if bars == 1 else f"{bars} bars", bars)
        self.drum_part_cycle_bars.setCurrentIndex(1)
        form.addRow("Drum phrase cycle", self.drum_part_cycle_bars)
        self.composition_energy = QDoubleSpinBox()
        self.composition_energy.setRange(0.0, 1.0)
        self.composition_energy.setSingleStep(0.05)
        self.composition_energy.setValue(0.62)
        self.composition_energy.setToolTip("Composition energy is not master output gain.")
        form.addRow("Composition energy", self.composition_energy)
        self.composition_variation = QDoubleSpinBox()
        self.composition_variation.setRange(0.0, 1.0)
        self.composition_variation.setSingleStep(0.05)
        self.composition_variation.setValue(0.45)
        self.composition_variation.setToolTip(
            "Changes section proportions and bounded macro values, not hit probability.")
        form.addRow("Structural variation", self.composition_variation)

        self.complexity = QSlider(Qt.Orientation.Horizontal)
        self.complexity.setRange(0, 100)
        self.complexity.setValue(68)
        self.complexity_label = QLabel("0.68")
        complexity_row = QHBoxLayout()
        complexity_row.addWidget(self.complexity, 1)
        complexity_row.addWidget(self.complexity_label)
        complexity_widget = QWidget()
        complexity_widget.setLayout(complexity_row)
        self.complexity.valueChanged.connect(
            lambda value: self.complexity_label.setText(f"{value / 100:.2f}")
        )
        form.addRow("Complexity", complexity_widget)

        seed_row = QHBoxLayout()
        self.seed = QLineEdit("20261123")
        seed_row.addWidget(self.seed, 1)
        randomize = QPushButton("↻")
        randomize.setFixedWidth(36)
        randomize.setToolTip("Generate a new reproducible seed")
        randomize.clicked.connect(
            lambda: self.seed.setText(str(secrets.randbelow(2 ** 31 - 1) + 1))
        )
        seed_row.addWidget(randomize)
        seed_widget = QWidget()
        seed_widget.setLayout(seed_row)
        form.addRow("Random seed", seed_widget)
        form_layout.addWidget(global_group)

        axes_group = QGroupBox("COMPOSITION AXES")
        axes_form = QFormLayout(axes_group)

        def axis_control(value: float, tooltip: str) -> QDoubleSpinBox:
            control = QDoubleSpinBox()
            control.setRange(0.0, 1.0)
            control.setSingleStep(0.05)
            control.setValue(value)
            control.setToolTip(tooltip)
            return control

        self.arrangement_density = axis_control(
            0.55, "Controls the amount of activity in kick, snare and break roles."
        )
        self.rhythmic_syncopation = axis_control(
            0.52, "Controls off-grid tension and the prominence of upper rhythmic shadows."
        )
        self.arrangement_instability = axis_control(
            0.40, "Controls how far texture and section-level rhythmic details drift."
        )
        self.melodic_activity = axis_control(
            0.62, "Controls melodic entrances and note activity independently of drum density."
        )
        self.melody_register_semitones = QSpinBox()
        self.melody_register_semitones.setRange(-24, 24)
        self.melody_register_semitones.setValue(0)
        self.melody_register_semitones.setToolTip(
            "Offsets the motif's register by semitones; section shifts remain phrase-aware."
        )
        self.tonal_brightness = axis_control(
            0.55, "Sets the tonal brightness target independently of composition energy."
        )
        self.spatial_intent = axis_control(
            0.52, "Controls the space/ambience intention independently of brightness and density."
        )
        for label, control in (
            ("Arrangement density", self.arrangement_density),
            ("Rhythmic syncopation", self.rhythmic_syncopation),
            ("Instability", self.arrangement_instability),
            ("Melodic activity", self.melodic_activity),
            ("Melody register / st", self.melody_register_semitones),
            ("Tonal brightness", self.tonal_brightness),
            ("Spatial intent", self.spatial_intent),
        ):
            axes_form.addRow(label, control)
        form_layout.addWidget(axes_group)

        modules = QGroupBox("GENERATOR MODULES")
        modules_layout = QVBoxLayout(modules)
        self.melody_enabled = QCheckBox("Geometric / FM melody")
        self.melody_enabled.setChecked(True)
        self.texture_enabled = QCheckBox("Evolving noise texture")
        self.texture_enabled.setChecked(True)
        self.ambience_enabled = QCheckBox("Slow harmonic ambience")
        self.ambience_enabled.setChecked(True)
        modules_layout.addWidget(self.melody_enabled)
        modules_layout.addWidget(self.texture_enabled)
        modules_layout.addWidget(self.ambience_enabled)
        ambience_row = QWidget()
        ambience_layout = QHBoxLayout(ambience_row)
        ambience_layout.setContentsMargins(0, 0, 0, 0)
        ambience_layout.addWidget(QLabel("Ambience level"))
        self.ambience_level = QDoubleSpinBox()
        self.ambience_level.setRange(0.0, 1.0)
        self.ambience_level.setSingleStep(0.05)
        self.ambience_level.setValue(0.16)
        ambience_layout.addWidget(self.ambience_level)
        modules_layout.addWidget(ambience_row)
        voices_layout.addWidget(modules)

        source_group = QGroupBox("BUNDLED PERCUSSION SOURCES")
        source_form = QFormLayout(source_group)
        self.sample_selectors: dict[str, QComboBox] = {}
        self.sample_library = {
            role: discover_bundled_samples(role=role)
            for role in ("kick", "snare", "hat")
        }
        for role, label in (("kick", "Kick source"), ("snare", "Snare source"), ("hat", "Hat / cymbal")):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            selector = QComboBox()
            selector.addItem("NONE · SYNTH ONLY", None)
            samples = self.sample_library[role]
            for asset in samples:
                selector.addItem(asset.label, str(asset.path))
            preferred = default_sample_for_role(role)
            if preferred is not None:
                selected_index = selector.findData(str(preferred.path))
                if selected_index >= 0:
                    selector.setCurrentIndex(selected_index)
            self.sample_selectors[role] = selector
            row_layout.addWidget(selector, 1)
            browse_sample = QPushButton("…")
            browse_sample.setFixedWidth(34)
            browse_sample.setToolTip(f"Choose a custom {role} sample")
            browse_sample.clicked.connect(
                lambda _checked=False, selected_role=role: self._choose_drum_sample(selected_role)
            )
            row_layout.addWidget(browse_sample)
            source_form.addRow(label, row)

        sample_counts = sample_library_counts()
        self.sample_library_note = QLabel(
            f"LOCAL LIBRARY  ·  {sample_counts['kick']} kick · "
            f"{sample_counts['snare']} snare / clap · {sample_counts['hat']} hat / cymbal sources"
        )
        self.sample_library_note.setObjectName("muted")
        self.sample_library_note.setWordWrap(True)
        source_form.addRow(self.sample_library_note)
        voices_layout.addWidget(source_group)

        automation_group = QGroupBox("DRUM PART AUTOMATION")
        automation_form = QFormLayout(automation_group)
        self.auto_drum_sample_switching = QCheckBox("Switch sample parts through the track")
        self.auto_drum_sample_switching.setChecked(True)
        self.auto_drum_sample_switching.setToolTip(
            "Selects among the available samples for each role at section or phrase-cycle boundaries. "
            "Returns recall the established opening sample."
        )
        automation_form.addRow(self.auto_drum_sample_switching)
        self.include_indexed_library_samples = QCheckBox("Include indexed Library assets")
        self.include_indexed_library_samples.setChecked(True)
        self.include_indexed_library_samples.setToolTip(
            "Adds indexed audio with matching kick/snare/hat roles or recognizable file/folder names to the role banks."
        )
        automation_form.addRow(self.include_indexed_library_samples)
        self.sample_features_note = QLabel(
            "Feature-guided choice uses indexed spectral centroid, flatness, onset density and crest factor. "
            "Index the sample folder in Library to unlock those descriptors for bundled sounds."
        )
        self.sample_features_note.setObjectName("muted")
        self.sample_features_note.setWordWrap(True)
        automation_form.addRow(self.sample_features_note)
        self.drum_sample_automation = QComboBox()
        self.drum_sample_automation.addItem("AUTOMATIC · PHRASE AWARE", "automatic")
        self.drum_sample_automation.addItem("CHANGE AT EACH SECTION", "section")
        self.drum_sample_automation.addItem("CHANGE BY DRUM CYCLE", "cycle")
        self.drum_sample_automation.addItem("FIXED · ONE SOUND PER ROLE", "fixed")
        automation_form.addRow("Switch schedule", self.drum_sample_automation)
        voices_layout.addWidget(automation_group)

        hybrid_group = QGroupBox("PERCUSSION SOURCE ENGINE")
        hybrid_form = QFormLayout(hybrid_group)
        self.percussion_source_mode = QComboBox()
        self.percussion_source_mode.addItem("AUTOMATIC · SECTION-AWARE", "automatic")
        self.percussion_source_mode.addItem("SYNTHESIS ONLY", "synth")
        self.percussion_source_mode.addItem("HYBRID · FIXED BLEND", "hybrid")
        self.percussion_source_mode.addItem("SAMPLE ONLY", "sample")
        hybrid_form.addRow("Source mode", self.percussion_source_mode)
        self.percussion_hybrid_architecture = QComboBox()
        self.percussion_hybrid_architecture.addItem("TRANSIENT SAMPLE + SYNTH BODY", "transient_body")
        self.percussion_hybrid_architecture.addItem("PARALLEL FULL LAYERS", "layered")
        self.percussion_hybrid_architecture.addItem("FEATURE-GUIDED HYBRID", "feature_guided")
        self.percussion_hybrid_architecture.setToolTip(
            "Transient/body mode uses the sample onset and synthesized body. Parallel mode blends full layers. "
            "Feature-guided mode steers synthesized brightness, pitch and transient energy from the selected asset's analysis."
        )
        hybrid_form.addRow("Hybrid architecture", self.percussion_hybrid_architecture)
        self.percussion_sample_mix = QDoubleSpinBox()
        self.percussion_sample_mix.setRange(0.0, 1.0)
        self.percussion_sample_mix.setSingleStep(0.05)
        self.percussion_sample_mix.setValue(0.46)
        hybrid_form.addRow("Sample contribution", self.percussion_sample_mix)
        self.hybrid_transient_ms = QDoubleSpinBox()
        self.hybrid_transient_ms.setRange(5.0, 200.0)
        self.hybrid_transient_ms.setSingleStep(1.0)
        self.hybrid_transient_ms.setValue(28.0)
        hybrid_form.addRow("Transient window / ms", self.hybrid_transient_ms)
        voices_layout.addWidget(hybrid_group)

        profiles = QGroupBox("SYNTH VOICE CATALOGUE")
        profile_form = QFormLayout(profiles)
        self.kick_profile = QComboBox()
        self.kick_profile.addItems(["auto", *KICK_PROFILES.keys()])
        profile_form.addRow("Kick", self.kick_profile)
        self.snare_profile = QComboBox()
        self.snare_profile.addItems(["auto", *SNARE_PROFILES.keys()])
        profile_form.addRow("Snare", self.snare_profile)
        self.hat_profile = QComboBox()
        self.hat_profile.addItems(["auto", *HAT_PROFILES.keys()])
        profile_form.addRow("Hi-hat", self.hat_profile)
        self.melody_profile = QComboBox()
        self.melody_profile.addItems(["auto", *MELODY_PROFILES.keys()])
        profile_form.addRow("Melody voice", self.melody_profile)
        self.synth_palette = QComboBox()
        self.synth_palette.addItems(["subtractive", "hybrid", "fm", "additive", "modal", "inharmonic", "granular", "physical"])
        self.synth_palette.setToolTip(
            "Select the lead synthesis family. Experimental families retain the NumPy reference renderer."
        )
        profile_form.addRow("Lead synthesis", self.synth_palette)
        self.percussion_synthesis = QComboBox()
        self.percussion_synthesis.addItems(["minimal", "extended", "samples"])
        self.percussion_synthesis.setCurrentText("minimal")
        self.percussion_synthesis.setToolTip(
            "Minimal uses dry transient/body/tail synthesis; extended adds resonant detail; "
            "samples uses the profiled legacy drum synthesis."
        )
        profile_form.addRow("Synth drum architecture", self.percussion_synthesis)
        self.melody_scale = QComboBox()
        self.melody_scale.addItems(list(SCALE_STEPS))
        self.melody_scale.setCurrentText("chromatic")
        profile_form.addRow("Melody pitch field", self.melody_scale)
        self.melody_root = QComboBox()
        for pitch_class, name in enumerate(ROOT_NAMES):
            self.melody_root.addItem(name, pitch_class)
        self.melody_root.setCurrentIndex(0)
        profile_form.addRow("Pitch-field root", self.melody_root)
        voices_layout.addWidget(profiles)

        groove = QGroupBox("BREAK RHYTHM GRAMMAR")
        groove_form = QFormLayout(groove)
        self.break_style = QComboBox()
        self.break_style.addItems(["broken_funk", "half_time", "straight", "sparse", "auto"])
        groove_form.addRow("Pattern", self.break_style)
        self.break_density = QDoubleSpinBox()
        self.break_density.setRange(0.0, 1.0)
        self.break_density.setSingleStep(0.05)
        self.break_density.setValue(0.50)
        self.break_density.setToolTip(
            "Controls the number of supporting events; the metric anchors stay in place."
        )
        groove_form.addRow("Density", self.break_density)
        self.break_variation = QDoubleSpinBox()
        self.break_variation.setRange(0.0, 1.0)
        self.break_variation.setSingleStep(0.05)
        self.break_variation.setValue(0.25)
        self.break_variation.setToolTip(
            "Probability of a phrase edit at the end of each cycle; high values may add a second local edit."
        )
        groove_form.addRow("Phrase variation", self.break_variation)
        self.break_cycle_bars = QComboBox()
        self.break_cycle_bars.addItem("1 bar", 1)
        self.break_cycle_bars.addItem("2 bars", 2)
        self.break_cycle_bars.addItem("4 bars", 4)
        self.break_cycle_bars.setCurrentIndex(1)
        groove_form.addRow("Repeat cycle", self.break_cycle_bars)
        rhythm_layout.addWidget(groove)

        source_group = QGroupBox("SOURCE MATERIAL")
        source_layout = QVBoxLayout(source_group)
        self.break_path_label = QLabel("No break sample selected")
        self.break_path_label.setObjectName("muted")
        self.break_path_label.setWordWrap(True)
        source_layout.addWidget(self.break_path_label)
        browse = QPushButton("LOAD BREAK SAMPLE…")
        browse.clicked.connect(self._choose_break_sample)
        source_layout.addWidget(browse)
        rhythm_layout.addWidget(source_group)

        controls_layout.addStretch(1)
        panel_layout.addWidget(controls_page, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(285)
        scroll.setWidget(panel)

        # The primary action lives outside the scrollable control stack so it
        # remains visible even when the user explores every advanced module.
        left_panel = QWidget()
        left_panel.setMinimumWidth(285)
        left_panel.setMaximumWidth(450)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(9)
        control_caption = QLabel("COMPOSITION WORKFLOW")
        control_caption.setObjectName("sectionTitle")
        left_layout.addWidget(control_caption)
        left_layout.addWidget(scroll, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = AudioPreview()
        right_layout.addWidget(self.preview, 1)
        self.render_summary = QLabel(
            "WAITING FOR RENDER  /  48 kHz · FLOAT32 · STEREO\n"
            "Waveform and time-frequency preview appear here after generation."
        )
        self.render_summary.setObjectName("muted")
        self.render_summary.setWordWrap(True)
        right_layout.addWidget(self.render_summary)
        workflow_row = QHBoxLayout()
        workflow_row.addWidget(QLabel("CONTINUE IN"))
        self.open_mixer_button = QPushButton("STEM MIXER")
        self.open_fx_button = QPushButton("FX LAB")
        self.open_library_button = QPushButton("LIBRARY")
        self.open_mixer_button.clicked.connect(lambda: self._set_workspace(2))
        self.open_fx_button.clicked.connect(lambda: self._set_workspace(3))
        self.open_library_button.clicked.connect(lambda: self._set_workspace(4))
        for action in (self.open_mixer_button, self.open_fx_button, self.open_library_button):
            action.setEnabled(False)
            workflow_row.addWidget(action)
        workflow_row.addStretch(1)
        right_layout.addLayout(workflow_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([370, 900])

        action_bar = QFrame()
        action_bar.setObjectName("generatorActionBar")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(16, 11, 16, 11)
        action_copy = QVBoxLayout()
        action_title = QLabel("GENERATE A TRACK")
        action_title.setObjectName("sectionTitle")
        action_copy.addWidget(action_title)
        action_flow = QLabel("FORM  →  DRUM PARTS  →  SAMPLE LIBRARY  →  SYNTHESIS  →  RENDER")
        action_flow.setObjectName("muted")
        action_copy.addWidget(action_flow)
        action_layout.addLayout(action_copy, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(90)
        self.progress.setVisible(False)
        action_layout.addWidget(self.progress)
        self.cancel_background_button = QPushButton("CANCEL")
        self.cancel_background_button.setEnabled(False)
        self.cancel_background_button.setVisible(False)
        self.cancel_background_button.clicked.connect(self._cancel_background_job)
        action_layout.addWidget(self.cancel_background_button)
        self.generate_button = QPushButton("GENERATE TRACK  →")
        self.generate_button.setObjectName("primaryAction")
        self.generate_button.setMinimumHeight(54)
        self.generate_button.setMinimumWidth(230)
        self.generate_button.setToolTip(
            "Build one connected composition: persistent motif, section role orchestration, "
            "phrase-aware transitions, hybrid sources and aligned stems."
        )
        self.generate_button.clicked.connect(self._generate)
        action_layout.addWidget(self.generate_button)
        self.randomise_button = QPushButton("FULL RANDOMISE")
        self.randomise_button.setMinimumHeight(54)
        self.randomise_button.setToolTip(
            "Randomise every generator setting except BPM and duration. "
            "The generated values are written into the visible controls."
        )
        self.randomise_button.clicked.connect(self._randomise_all_parameters)
        action_layout.addWidget(self.randomise_button)
        layout.addWidget(action_bar)
        layout.addWidget(splitter, 1)
        return page

    def _build_tray_icon(self) -> None:
        # The repository now has one authoritative application icon.
        icon_path = Path(__file__).resolve().parent / "resources" / "icons" / "Icon.ico"
        icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        if not self._tray_available or icon.isNull():
            return
        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip("Reawarp — 再変形")
        menu = QMenu(self)
        show_action = QAction("Show Reawarp", self)
        show_action.triggered.connect(self._restore_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(quit_action)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._tray_activated)
        self._tray_icon.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _shutdown(self) -> None:
        """Stop all GUI timers and audio, then wait for active offline rendering."""
        self._timer.stop()
        self._preview_refresh_timer.stop()
        self.player.stop()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        workers = (
            self._worker, self._export_worker, self._variation_batch_worker,
            self._variation_compare_worker, self._fx_worker, self._fx_variation_worker,
        )
        for worker in workers:
            if worker is not None:
                worker.cancel()
        pool = QThreadPool.globalInstance()
        pool.clear()
        pool.waitForDone(-1)
        self._worker = None
        self._export_worker = None
        self._variation_batch_worker = None
        self._variation_compare_worker = None
        self._fx_worker = None
        self._fx_variation_worker = None
        self._clear_fx_variation_cache()

    def _quit_from_tray(self) -> None:
        self._shutdown()
        QApplication.instance().quit()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        # Closing the main window always exits. Hiding to tray was confusing
        # because the terminal process kept running after the user closed it.
        self._shutdown()
        event.accept()
        super().closeEvent(event)

    def _build_transport_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("transportBar")
        bar.setStyleSheet(
            "QFrame { background: #101010; border: 1px solid #303030; border-radius: 1px; }"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.addWidget(QLabel("AUDITION"))
        self.preview_source = QComboBox()
        self.preview_source.addItem("MASTER MIX", "master")
        self.preview_source.currentIndexChanged.connect(self._refresh_preview)
        self.preview_source.setMinimumWidth(175)
        self.preview_source.setEnabled(False)
        layout.addWidget(self.preview_source)
        layout.addWidget(QLabel("OUTPUT"))
        self.output_device = QComboBox()
        self.output_device.setMinimumWidth(180)
        layout.addWidget(self.output_device)
        self.fx_render_state = QLabel("FX NOT RENDERED")
        self.fx_render_state.setObjectName("muted")
        layout.addWidget(self.fx_render_state)
        self.retry_fx_button = QPushButton("PRE-RENDER FX")
        self.retry_fx_button.setToolTip(
            "Render all configured inserts and shared returns without modifying dry source stems."
        )
        self.retry_fx_button.clicked.connect(self._retry_fx_render)
        layout.addWidget(self.retry_fx_button)
        self.play_button = QPushButton("PLAY")
        self.play_button.clicked.connect(self._toggle_playback)
        self.play_button.setEnabled(False)
        layout.addWidget(self.play_button)
        self.stop_button = QPushButton("STOP")
        self.stop_button.clicked.connect(self.player.stop)
        self.stop_button.clicked.connect(self._playback_stopped)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        self.transport_position = QLabel("00:00.0 / 00:00.0")
        self.transport_position.setObjectName("muted")
        layout.addWidget(self.transport_position)
        layout.addStretch(1)
        return bar

    def _build_break_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        controls = QWidget()
        controls.setMinimumWidth(0)
        controls.setMaximumWidth(420)
        control_layout = QVBoxLayout(controls)

        source = QGroupBox("BREAK SOURCE")
        source_layout = QVBoxLayout(source)
        self.break_source_label = QLabel("No source loaded")
        self.break_source_label.setObjectName("muted")
        self.break_source_label.setWordWrap(True)
        source_layout.addWidget(self.break_source_label)
        choose = QPushButton("CHOOSE AUDIO FILE…")
        choose.clicked.connect(self._choose_break_sample)
        source_layout.addWidget(choose)
        analyze = QPushButton("ANALYZE TRANSIENTS")
        analyze.clicked.connect(self._analyze_break)
        source_layout.addWidget(analyze)
        control_layout.addWidget(source)

        transform_group = QGroupBox("TRANSFORMATION CHAIN")
        transform_layout = QGridLayout(transform_group)
        self.break_transform_checks: dict[str, QCheckBox] = {}
        for index, name in enumerate(BREAK_TRANSFORMS):
            check = QCheckBox(name.replace("_", " "))
            check.setToolTip(f"Apply {name.replace('_', ' ')} to the imported break")
            self.break_transform_checks[name] = check
            transform_layout.addWidget(check, index // 2, index % 2)
        control_layout.addWidget(transform_group)

        params = QGroupBox("MUTATION PARAMETERS")
        param_form = QFormLayout(params)
        self.slice_count = QSpinBox()
        self.slice_count.setRange(2, 128)
        self.slice_count.setValue(16)
        param_form.addRow("Maximum slices", self.slice_count)
        self.stutter_repeats = QSpinBox()
        self.stutter_repeats.setRange(2, 32)
        self.stutter_repeats.setValue(4)
        param_form.addRow("Stutter repeats", self.stutter_repeats)
        self.dropout_probability = QDoubleSpinBox()
        self.dropout_probability.setRange(0, 1)
        self.dropout_probability.setSingleStep(0.05)
        self.dropout_probability.setValue(0.18)
        param_form.addRow("Dropout probability", self.dropout_probability)
        self.pitch_semitones = QDoubleSpinBox()
        self.pitch_semitones.setRange(-24, 24)
        self.pitch_semitones.setValue(0)
        param_form.addRow("Pitch shift / semitones", self.pitch_semitones)
        self.stretch_factor = QDoubleSpinBox()
        self.stretch_factor.setRange(0.25, 4)
        self.stretch_factor.setSingleStep(0.05)
        self.stretch_factor.setValue(1.0)
        param_form.addRow("Time stretch / ratio", self.stretch_factor)
        self.gate_rate = QDoubleSpinBox()
        self.gate_rate.setRange(0.1, 100)
        self.gate_rate.setValue(8)
        param_form.addRow("Gate rate / Hz", self.gate_rate)
        self.gate_duty = QDoubleSpinBox()
        self.gate_duty.setRange(0.05, 1)
        self.gate_duty.setSingleStep(0.05)
        self.gate_duty.setValue(0.62)
        param_form.addRow("Gate duty", self.gate_duty)
        self.grain_size = QDoubleSpinBox()
        self.grain_size.setRange(5, 1000)
        self.grain_size.setValue(80)
        param_form.addRow("Grain size / ms", self.grain_size)
        self.grain_density = QDoubleSpinBox()
        self.grain_density.setRange(0.25, 4)
        self.grain_density.setValue(1.5)
        param_form.addRow("Grain density", self.grain_density)
        self.freeze_position = QDoubleSpinBox()
        self.freeze_position.setRange(0, 1)
        self.freeze_position.setValue(0.25)
        param_form.addRow("Freeze position", self.freeze_position)
        control_layout.addWidget(params)
        control_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(250)
        scroll.setWidget(controls)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.break_preview = AudioPreview()
        preview_layout.addWidget(self.break_preview, 1)
        self.break_analysis_summary = QLabel(
            "Load a break, inspect its transients, then reuse the source in your composition. "
            "All analysis and transformation controls are non-destructive."
        )
        self.break_analysis_summary.setObjectName("muted")
        self.break_analysis_summary.setWordWrap(True)
        preview_layout.addWidget(self.break_analysis_summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 900])
        layout.addWidget(splitter, 1)
        return page

    def _build_mixer_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("STEM MATRIX")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.export_button = QPushButton("EXPORT MASTER + STEMS + MIDI…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_project)
        header.addWidget(self.export_button)
        layout.addLayout(header)

        self.mixer_stack = QStackedWidget()
        empty_state = QFrame()
        empty_state.setObjectName("emptyState")
        empty_layout = QVBoxLayout(empty_state)
        empty_layout.setContentsMargins(30, 35, 30, 35)
        empty_layout.addStretch(1)
        empty_title = QLabel("A composition belongs here.")
        empty_title.setObjectName("workspaceTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_copy = QLabel(
            "The Stem Mixer is connected to the Generator. Create a composition first; "
            "its dry stems, routing, automation and export controls will appear here."
        )
        empty_copy.setObjectName("muted")
        empty_copy.setWordWrap(True)
        empty_copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_copy)
        go_generate = QPushButton("OPEN GENERATOR")
        go_generate.setObjectName("primaryAction")
        go_generate.setMaximumWidth(220)
        go_generate.clicked.connect(lambda: self._set_workspace(0))
        empty_layout.addWidget(go_generate, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self.mixer_stack.addWidget(empty_state)

        mixer_content_page = QWidget()
        mixer_layout = QVBoxLayout(mixer_content_page)
        mixer_layout.setContentsMargins(0, 0, 0, 0)
        mixer_layout.setSpacing(9)
        self.mixer_scroll = QScrollArea()
        self.mixer_scroll.setWidgetResizable(True)
        self.mixer_content = QWidget()
        self.mixer_rows_layout = QVBoxLayout(self.mixer_content)
        self.mixer_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.mixer_rows_layout.setSpacing(6)
        self.mixer_scroll.setWidget(self.mixer_content)
        mixer_layout.addWidget(self.mixer_scroll, 1)

        note = QLabel(
            "Effects follow musical roles automatically: low-end anchors stay dry while "
            "snare, hats, breaks, melody and texture receive restrained inserts and shared sends. "
            "Dry stem files remain immutable; the same cached routing render feeds preview and export."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        mixer_layout.addWidget(note)
        self.fx_workspace_tabs = QTabWidget()
        self.fx_routing_editor = FXRoutingEditor()
        self.fx_routing_editor.changed.connect(self._refresh_routing)
        self.fx_routing_editor.auditionRequested.connect(self._audition_fx_component)
        self.fx_routing_editor.mixerStateRequested.connect(self._apply_routing_mixer_state)
        self.fx_routing_editor.preRenderRequested.connect(self._pre_render_channel_fx)
        self.fx_routing_editor.variationsRequested.connect(self._generate_fx_variations)
        self.fx_routing_editor.variationAuditionRequested.connect(self._audition_fx_variation)
        self.fx_routing_editor.variationApplyRequested.connect(self._apply_fx_variation)
        routing_scroll = QScrollArea()
        routing_scroll.setWidgetResizable(True)
        routing_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        routing_scroll.setWidget(self.fx_routing_editor)

        self.fx_automation_editor = FXAutomationEditor()
        self.fx_automation_editor.changed.connect(self._refresh_routing)
        automation_scroll = QScrollArea()
        automation_scroll.setWidgetResizable(True)
        automation_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        automation_scroll.setWidget(self.fx_automation_editor)

        self.score_automation_editor = ScoreAutomationEditor()
        self.score_automation_editor.applyRequested.connect(self._apply_score_automation)
        score_automation_scroll = QScrollArea()
        score_automation_scroll.setWidgetResizable(True)
        score_automation_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        score_automation_scroll.setWidget(self.score_automation_editor)

        self.fx_workspace_tabs.addTab(routing_scroll, "ROUTING")
        self.fx_workspace_tabs.addTab(automation_scroll, "FX AUTOMATION")
        self.fx_workspace_tabs.addTab(score_automation_scroll, "SCORE CONTROL")
        mixer_layout.addWidget(self.fx_workspace_tabs, 2)
        self.mixer_stack.addWidget(mixer_content_page)
        self.mixer_stack.setCurrentIndex(0)
        layout.addWidget(self.mixer_stack, 1)
        return page

    def _accept_library_sample(self, role: str, path: str) -> None:
        """Route a Library selection into its corresponding Generator source role."""
        source_path = str(Path(path).expanduser().resolve())
        if role in self.sample_selectors:
            selector = self.sample_selectors[role]
            selected = selector.findData(source_path)
            if selected < 0:
                selector.addItem(f"{Path(source_path).name} · LIBRARY", source_path)
                selected = selector.count() - 1
            selector.setCurrentIndex(selected)
        elif role == "break":
            try:
                audio = read_sample(source_path, 48_000)
            except Exception as exc:
                self._show_error(f"Could not load Library break sample: {exc}")
                return
            self._break_path = source_path
            self._break_audio = audio
            self.break_path_label.setText(Path(source_path).name)
            self.break_source_label.setText(source_path)
            self._analyze_break()
        else:
            self._show_error(f"Unsupported Generator source role: {role}")
            return

        self._set_workspace(0)
        self.statusBar().showMessage(
            f"Library source connected to Generator · {role.upper()} · {Path(source_path).name}",
            8000,
        )

    def _choose_drum_sample(self, role: str) -> None:
        selector = self.sample_selectors.get(role)
        if selector is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Choose {role} sample",
            str(Path.cwd()),
            "Audio files (*.wav *.flac *.aiff *.aif *.ogg);;All files (*.*)",
        )
        if not path:
            return
        selected = selector.findData(path)
        if selected < 0:
            selector.addItem(f"{Path(path).name} · CUSTOM", path)
            selected = selector.count() - 1
        selector.setCurrentIndex(selected)

    def _choose_break_sample(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a break sample", str(Path.cwd()),
            "Audio files (*.wav *.flac *.aiff *.aif *.ogg);;All files (*.*)",
        )
        if not path:
            return
        try:
            audio = read_sample(path, 48_000)
        except Exception as exc:
            self._show_error(f"Could not read break sample: {exc}")
            return
        self._break_path = path
        self._break_audio = audio
        self.break_path_label.setText(Path(path).name)
        self.break_source_label.setText(path)
        self._analyze_break()

    def _analyze_break(self) -> None:
        if self._break_audio is None:
            self.break_analysis_summary.setText("Choose a break sample to analyze it.")
            return
        slices = auto_slice(self._break_audio, 48_000, max_slices=self.slice_count.value())
        markers = [item.start for item in slices[1:]]
        self.break_preview.set_audio(self._break_audio, 48_000, markers)
        self.break_analysis_summary.setText(
            f"{len(slices)} regions · {len(markers)} transient boundaries · "
            f"{len(self._break_audio) / 48_000:.2f} s · original file untouched"
        )

    def _read_config(self) -> GenerationConfig:
        seed_text = self.seed.text().strip() or "20261123"
        seed: int | str = int(seed_text) if seed_text.lstrip("-+").isdigit() else seed_text
        transforms = tuple(
            name for name, checkbox in self.break_transform_checks.items()
            if checkbox.isChecked()
        )
        sample_paths: dict[str, str] = {}
        sample_metadata: dict[str, dict[str, Any]] = {}
        sample_banks: dict[str, tuple[dict[str, Any], ...]] = {}

        # Pull indexed descriptors once for the whole generation request. The
        # Generator then builds role banks from bundled material and assets the
        # user has already indexed in Library; no audio is copied or re-written.
        indexed_assets: list[Any] = []
        if self.include_indexed_library_samples.isChecked():
            try:
                from reawarp.library.store import SampleLibrary
                with SampleLibrary() as library:
                    indexed_assets = library.search(asset_type="sample", limit=500)
            except Exception as exc:
                self.statusBar().showMessage(
                    f"Indexed Library bank unavailable; using bundled samples only: {exc}", 8000
                )

        indexed_by_path = {
            str(Path(asset.path).expanduser().resolve()): asset
            for asset in indexed_assets
        }

        def add_bank_entry(
            entries: list[dict[str, Any]],
            path_value: str,
            role: str,
            *,
            label: str | None = None,
            metadata: dict[str, Any] | None = None,
            features: dict[str, Any] | None = None,
            sha256: str = "",
            asset_id: str | None = None,
        ) -> None:
            path = Path(path_value).expanduser().resolve()
            if not path.is_file() or any(item["path"] == str(path) for item in entries):
                return
            entry_metadata = dict(metadata or {})
            entry_metadata.setdefault("role", role)
            entries.append({
                "path": str(path),
                "label": label or path.name,
                "asset_id": asset_id or path.name,
                "sha256": sha256,
                "metadata": entry_metadata,
                "features": dict(features or {}),
            })

        for role, selector in self.sample_selectors.items():
            selected_path = selector.currentData()
            if not selected_path:
                continue
            selected_resolved = str(Path(str(selected_path)).expanduser().resolve())
            sample_paths[role] = selected_resolved
            selected_indexed = indexed_by_path.get(selected_resolved)
            matching = next(
                (
                    asset for asset in self.sample_library.get(role, [])
                    if str(Path(asset.path).expanduser().resolve()) == selected_resolved
                ),
                None,
            )
            anchor_metadata = {
                "provider": "indexed_library" if selected_indexed else (
                    "bundled_sample_library" if matching else "custom_sample"
                ),
                "relative_path": (
                    str(Path(selected_indexed.path).name) if selected_indexed
                    else matching.relative_path if matching
                    else Path(selected_resolved).name
                ),
                "role": role,
                "source_name": Path(selected_resolved).name,
            }
            sample_metadata[role] = anchor_metadata

            bank: list[dict[str, Any]] = []
            add_bank_entry(
                bank,
                selected_resolved,
                role,
                label=Path(selected_resolved).name,
                metadata=anchor_metadata,
                features=selected_indexed.features if selected_indexed else {},
                sha256=selected_indexed.sha256 if selected_indexed else "",
                asset_id=selected_indexed.asset_id if selected_indexed else None,
            )

            if self.auto_drum_sample_switching.isChecked():
                # Bundled samples form the default role vocabulary. If already
                # indexed, their measured descriptors are attached by exact path.
                for asset in discover_bundled_samples(role=role):
                    resolved = str(asset.path.expanduser().resolve())
                    indexed = indexed_by_path.get(resolved)
                    add_bank_entry(
                        bank, resolved, role,
                        label=asset.label,
                        metadata={
                            "provider": "indexed_bundled" if indexed else "bundled_sample_library",
                            "relative_path": asset.relative_path,
                            "role": role,
                            "source_name": asset.path.name,
                        },
                        features=indexed.features if indexed else {},
                        sha256=indexed.sha256 if indexed else "",
                        asset_id=indexed.asset_id if indexed else None,
                    )

                # Add other indexed sounds that have a usable role, including
                # files the user assigned by name/folder when indexing.
                if self.include_indexed_library_samples.isChecked():
                    for asset in indexed_assets:
                        resolved = str(Path(asset.path).expanduser().resolve())
                        if asset.role in {"kick", "snare", "hat"}:
                            detected_role = asset.role
                        else:
                            detected_role = classify_sample_role(asset.path)
                        if detected_role != role:
                            continue
                        add_bank_entry(
                            bank, resolved, role,
                            label=asset.file_name,
                            metadata={
                                "provider": "indexed_library",
                                "role": role,
                                "source_name": asset.file_name,
                                **dict(asset.metadata or {}),
                            },
                            features=asset.features,
                            sha256=asset.sha256,
                            asset_id=asset.asset_id,
                        )

                # Keep the selector choice as the anchor; the remaining bank is
                # bounded so a large project library cannot balloon render RAM.
                bank = bank[:65]
            sample_banks[role] = tuple(bank)

        if self._break_path:
            sample_paths["break"] = self._break_path
            sample_metadata["break"] = {
                "provider": "break_lab",
                "source_name": Path(self._break_path).name,
            }
        return GenerationConfig(
            bpm=self.bpm.value(),
            duration=self.duration.value(),
            structure=self.structure.currentText(),
            composition_flow=self.composition_flow.currentText(),
            pattern_family=self.pattern_family.currentText(),
            pattern_relationship=self.pattern_relationship.currentText(),
            pattern_follow_structure=self.pattern_follow_structure.isChecked(),
            drum_change_intensity=self.drum_change_intensity.value(),
            drum_part_cycle_bars=int(self.drum_part_cycle_bars.currentData()),
            synth_palette=self.synth_palette.currentText(),
            percussion_synthesis=self.percussion_synthesis.currentText(),
            percussion_source_mode=str(self.percussion_source_mode.currentData()),
            percussion_hybrid_architecture=str(self.percussion_hybrid_architecture.currentData()),
            percussion_sample_mix=self.percussion_sample_mix.value(),
            hybrid_transient_ms=self.hybrid_transient_ms.value(),
            melody_scale=self.melody_scale.currentText(),
            melody_root=int(self.melody_root.currentData()),
            composition_energy=self.composition_energy.value(),
            composition_variation=self.composition_variation.value(),
            arrangement_density=self.arrangement_density.value(),
            rhythmic_syncopation=self.rhythmic_syncopation.value(),
            arrangement_instability=self.arrangement_instability.value(),
            melodic_activity=self.melodic_activity.value(),
            melody_register_semitones=self.melody_register_semitones.value(),
            tonal_brightness=self.tonal_brightness.value(),
            spatial_intent=self.spatial_intent.value(),
            sample_rate=48_000,
            seed=seed,
            complexity=self.complexity.value() / 100.0,
            include_melody=self.melody_enabled.isChecked(),
            include_texture=self.texture_enabled.isChecked(),
            include_ambience=self.ambience_enabled.isChecked(),
            ambience_level=self.ambience_level.value(),
            sample_paths=sample_paths,
            sample_metadata=sample_metadata,
            sample_banks=sample_banks,
            drum_sample_automation=(
                str(self.drum_sample_automation.currentData())
                if self.auto_drum_sample_switching.isChecked() else "fixed"
            ),
            kick_profile=self.kick_profile.currentText(),
            snare_profile=self.snare_profile.currentText(),
            hat_profile=self.hat_profile.currentText(),
            melody_profile=self.melody_profile.currentText(),
            break_style=self.break_style.currentText(),
            break_density=self.break_density.value(),
            break_variation=self.break_variation.value(),
            break_cycle_bars=int(self.break_cycle_bars.currentData()),
            break_transforms=transforms,
            break_slice_count=self.slice_count.value(),
            break_stutter_repeats=self.stutter_repeats.value(),
            break_dropout_probability=self.dropout_probability.value(),
            break_pitch_semitones=self.pitch_semitones.value(),
            break_time_stretch=self.stretch_factor.value(),
            break_gate_rate_hz=self.gate_rate.value(),
            break_gate_duty=self.gate_duty.value(),
            break_grain_size_ms=self.grain_size.value(),
            break_grain_density=self.grain_density.value(),
            break_spectral_freeze_position=self.freeze_position.value(),
        )

    def _randomise_all_parameters(self) -> None:
        """Randomise every exposed generator setting while preserving tempo and length."""
        from reawarp.randomization import random_generation_config

        bpm = float(self.bpm.value())
        duration = float(self.duration.value())
        try:
            base = self._read_config()
            seed = secrets.randbelow(2 ** 31 - 1) + 1
            config = random_generation_config(base, seed=seed)
            config = replace(config, bpm=bpm, duration=duration)
            self._apply_config_to_controls(config)
        except Exception as exc:
            self._show_error(f"Could not randomise generator settings: {exc}")
            return
        self.seed.setText(str(seed))
        self.statusBar().showMessage(
            f"Full generator randomisation prepared · {bpm:g} BPM · {duration:g}s · "
            f"seed {seed}. Settings remain editable; press GENERATE TRACK to render.",
            12000,
        )

    def _apply_config_to_controls(self, config: GenerationConfig) -> None:
        """Reflect a randomised GenerationConfig in the visible Generator controls."""
        self.structure.setCurrentText(config.structure)
        self.composition_flow.setCurrentText(config.composition_flow)
        self.pattern_family.setCurrentText(config.pattern_family)
        self.pattern_relationship.setCurrentText(config.pattern_relationship)
        self.pattern_follow_structure.setChecked(config.pattern_follow_structure)
        self.drum_change_intensity.setValue(config.drum_change_intensity)
        self.drum_part_cycle_bars.setCurrentIndex(
            max(0, self.drum_part_cycle_bars.findData(config.drum_part_cycle_bars))
        )
        self.composition_energy.setValue(config.composition_energy)
        self.composition_variation.setValue(config.composition_variation)
        self.complexity.setValue(round(config.complexity * 100))
        self.arrangement_density.setValue(config.arrangement_density)
        self.rhythmic_syncopation.setValue(config.rhythmic_syncopation)
        self.arrangement_instability.setValue(config.arrangement_instability)
        self.melodic_activity.setValue(config.melodic_activity)
        self.melody_register_semitones.setValue(config.melody_register_semitones)
        self.tonal_brightness.setValue(config.tonal_brightness)
        self.spatial_intent.setValue(config.spatial_intent)
        self.melody_enabled.setChecked(config.include_melody)
        self.texture_enabled.setChecked(config.include_texture)
        self.ambience_enabled.setChecked(config.include_ambience)
        self.ambience_level.setValue(config.ambience_level)
        self.drum_sample_automation.setCurrentIndex(
            max(0, self.drum_sample_automation.findData(config.drum_sample_automation))
        )
        self.auto_drum_sample_switching.setChecked(
            config.drum_sample_automation != "fixed"
        )
        self.percussion_source_mode.setCurrentIndex(
            max(0, self.percussion_source_mode.findData(config.percussion_source_mode))
        )
        self.percussion_hybrid_architecture.setCurrentIndex(
            max(0, self.percussion_hybrid_architecture.findData(
                config.percussion_hybrid_architecture
            ))
        )
        self.percussion_sample_mix.setValue(config.percussion_sample_mix)
        self.hybrid_transient_ms.setValue(config.hybrid_transient_ms)
        self.kick_profile.setCurrentText(config.kick_profile)
        self.snare_profile.setCurrentText(config.snare_profile)
        self.hat_profile.setCurrentText(config.hat_profile)
        self.melody_profile.setCurrentText(config.melody_profile)
        self.synth_palette.setCurrentText(config.synth_palette)
        self.percussion_synthesis.setCurrentText(config.percussion_synthesis)
        self.melody_scale.setCurrentText(config.melody_scale)
        self.melody_root.setCurrentIndex(config.melody_root)
        self.break_style.setCurrentText(config.break_style)
        self.break_density.setValue(config.break_density)
        self.break_variation.setValue(config.break_variation)
        self.break_cycle_bars.setCurrentIndex(
            max(0, self.break_cycle_bars.findData(config.break_cycle_bars))
        )
        for name, checkbox in self.break_transform_checks.items():
            checkbox.setChecked(name in config.break_transforms)
        self.slice_count.setValue(config.break_slice_count)
        self.stutter_repeats.setValue(config.break_stutter_repeats)
        self.dropout_probability.setValue(config.break_dropout_probability)
        self.pitch_semitones.setValue(config.break_pitch_semitones)
        self.stretch_factor.setValue(config.break_time_stretch)
        self.gate_rate.setValue(config.break_gate_rate_hz)
        self.gate_duty.setValue(config.break_gate_duty)
        self.grain_size.setValue(config.break_grain_size_ms)
        self.grain_density.setValue(config.break_grain_density)
        self.freeze_position.setValue(config.break_spectral_freeze_position)

    def _generate(self) -> None:
        try:
            config = self._read_config()
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._clear_variation_session()
        self._run_render(
            lambda cancel_event: ReawarpEngine().generate(config, cancel_event=cancel_event),
            "Generating full loop…",
        )

    def _apply_score_automation(self) -> None:
        """Apply the staged M18 score controls without mutating the source project."""
        if self.project is None:
            return
        try:
            edited_score = self.score_automation_editor.updated_score(
                self.project.to_score()
            )
        except Exception as exc:
            self._show_error(f"Could not prepare score automation: {exc}")
            return
        base_project = self.project
        self._run_render(
            lambda cancel_event: self._render_score_automation_project(
                base_project, edited_score, cancel_event=cancel_event
            ),
            "Applying score automation and re-rendering event-backed voices…",
        )

    @staticmethod
    def _render_score_automation_project(
        project: ReawarpProject,
        score,
        *,
        cancel_event: object | None = None,
    ) -> ReawarpProject:
        """Render a controlled Score and retain the specialist whole-field layers."""
        rendered = ReawarpEngine().render_score(
            score, config=project.config, cancel_event=cancel_event
        )
        canonical_score = rendered.score or score
        stems = {
            name: np.asarray(audio, dtype=np.float32).copy()
            for name, audio in project.stems.items()
        }
        aliases = {"hat": "hats", "break": "synthetic_break"}
        event_voices = {
            event.voice_id for event in canonical_score.events
            if event.kind not in {"control", "marker"}
        }
        empty = np.zeros((rendered.frame_count, 2), dtype=np.float32)
        peak_ceiling = 10.0 ** (-1.0 / 20.0)
        for voice_id in sorted(event_voices):
            name = aliases.get(voice_id, voice_id)
            audio = rendered.stems.get(voice_id)
            updated = empty.copy() if audio is None else np.asarray(
                audio, dtype=np.float32
            ).copy()
            peak = float(np.max(np.abs(updated))) if updated.size else 0.0
            if peak > peak_ceiling:
                updated *= peak_ceiling / peak
            stems[name] = updated

        automation_summary = {
            "source_count": len(canonical_score.automation_sources),
            "modulation_count": len(canonical_score.modulations),
            "control_targets": sorted({
                lane.target_id for lane in canonical_score.automation
            } | {
                item.destination_target_id for item in canonical_score.modulations
            }),
            "renderer": "ScoreRenderer",
            "event_backed_voices_re_rendered": sorted(event_voices),
            "whole_field_layers_preserved": [
                name for name in ("noise_texture", "ambience") if name in stems
            ],
        }
        score_metadata = dict(canonical_score.metadata)
        score_metadata["m18_score_automation"] = automation_summary
        score_metadata["render_stems"] = list(stems)
        controlled_score = replace(canonical_score, metadata=score_metadata)
        project_metadata = dict(project.metadata)
        project_metadata["m18_score_automation"] = automation_summary
        return ReawarpProject(
            config=project.config,
            sample_rate=project.sample_rate,
            stems=stems,
            events=list(project.events),
            metadata=project_metadata,
            score=controlled_score,
        )

    def _clear_variation_session(self) -> None:
        self._variation_session_epoch += 1
        if hasattr(self, "variation_page"):
            self.variation_page.set_batch_busy(False)
        if self._variation_batch_worker is not None:
            self._variation_batch_worker.cancel()
            self._variation_batch_worker = None
        self._variation_origin_project = None
        self._variation_base_project = None
        self._variation_parent_candidate_id = None
        self._variation_active_candidate_id = None
        self._variation_candidates.clear()
        self._variation_branch_base = None
        self._variation_ab_buffers.clear()
        self._variation_listening_buffers.clear()
        if self._variation_compare_worker is not None:
            self._variation_compare_worker.cancel()
            self._variation_compare_worker = None
        if hasattr(self, "variation_page"):
            self.variation_page.set_candidates([])

    def _load_variation_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Load Reawarp project or variation session", str(Path.cwd())
        )
        if not directory:
            return
        self._clear_variation_session()
        self._run_render(
            lambda cancel_event: ReawarpProject.load(directory, cancel_event=cancel_event),
            "Loading project, candidates and listening history…",
        )

    def _restore_variation_session(self, project: ReawarpProject) -> None:
        saved = getattr(project, "variation_candidates", {})
        if not saved or "base" not in saved:
            return
        origin = clone_project(saved["base"], readonly=True)
        self._variation_origin_project = origin
        self._variation_base_project = origin
        if "branch_base" in saved:
            self._variation_branch_base = clone_project(saved["branch_base"], readonly=True)
        session = project.metadata.get("m23_variations", {})
        self._variation_active_candidate_id = session.get("active_candidate_id")
        for key, candidate_project in saved.items():
            if key in {"base", "branch_base"}:
                continue
            record_data = candidate_project.metadata.get("m23_candidate")
            if not isinstance(record_data, dict):
                continue
            record = VariationCandidateRecord.from_dict(record_data)
            self._variation_candidates[record.candidate_id] = VariationCandidate(
                record, candidate_project
            )
        if (
            self._variation_branch_base is not None
            and self._variation_active_candidate_id in self._variation_candidates
        ):
            active = self._variation_candidates[self._variation_active_candidate_id]
            self._variation_parent_candidate_id = active.record.candidate_id
        self.variation_page.set_stems(list(project.stems))
        self.variation_page.set_candidates(
            [item.record for item in self._variation_candidates.values()],
            selected_id=self._variation_active_candidate_id,
        )

    def _refresh_sound_object_targets(self) -> None:
        try:
            from reawarp.library.store import SampleLibrary
            with SampleLibrary() as library:
                patches = library.search_sound_objects(limit=256)
            self.variation_page.set_sound_objects([
                (patch.patch_id, patch.name) for patch in patches
            ])
        except Exception as exc:
            self.statusBar().showMessage(f"Sound-object catalogue unavailable: {exc}", 6000)

    def _render_sound_object_candidate(
        self, base: ReawarpProject, index: int, variation_seed: int,
        request: VariationRequest, cancel_event: object,
    ) -> ReawarpProject:
        """Render deterministic M21 patch variations as non-destructive project stems."""
        from pathlib import Path
        import hashlib
        import re
        from reawarp.library.store import SampleLibrary
        from reawarp.samples.io import read_sample
        from reawarp.synthesis.sound_object import (
            HybridVoiceRenderer, SoundObjectPatch, TransformationRecord,
            derive_sound_object_seed, resample_audio_non_destructive,
        )

        if not request.targets:
            raise ValueError("select at least one sound-object patch from the local library")
        stems = {
            name: np.asarray(audio, dtype=np.float32).copy()
            for name, audio in base.stems.items()
        }
        variants = copy.deepcopy(base.metadata.get("sound_object_variants", []))
        with SampleLibrary() as library:
            for patch_id in request.targets:
                if cancel_event.is_set():
                    raise RuntimeError("sound-object batch cancelled")
                patch = library.get_sound_object(str(patch_id))
                if patch is None:
                    raise KeyError(f"sound-object patch not found: {patch_id}")
                source_audio: dict[str, np.ndarray] = {}
                for source in patch.sources:
                    required_frames = max(
                        (
                            layer.source_start_frame + layer.frame_count
                            for layer in patch.layers if layer.source_id == source.source_id
                        ),
                        default=patch.duration_frames,
                    )
                    if source.source_kind == "asset":
                        if source.asset_id:
                            asset = library.get_asset(source.asset_id)
                            if asset is None:
                                raise KeyError(
                                    f"sound-object source asset not indexed: {source.asset_id}"
                                )
                            if asset.sha256.casefold() != str(source.asset_sha256).casefold():
                                raise ValueError(
                                    f"source hash changed for sound-object asset {source.asset_id}"
                                )
                            source_path = Path(asset.path)
                        else:
                            source_path = Path(str(source.uri))
                            digest = hashlib.sha256()
                            with source_path.open("rb") as handle:
                                for block in iter(lambda: handle.read(1024 * 1024), b""):
                                    digest.update(block)
                            if digest.hexdigest().casefold() != str(source.asset_sha256).casefold():
                                raise ValueError(
                                    f"source hash changed for sound-object URI {source.uri}"
                                )
                        audio = read_sample(source_path, patch.sample_rate)
                    else:
                        source_seed = derive_sound_object_seed(
                            patch.seed, patch.patch_id, source.source_id
                        )
                        rng = np.random.default_rng(source_seed)
                        frames = required_frames
                        time = np.arange(frames, dtype=np.float64) / patch.sample_rate
                        model = str(source.source_model or "").casefold()
                        frequency = float(
                            patch.pitch_model.get("frequency_hz", 220.0)
                        )
                        noise = rng.normal(0.0, 1.0, frames)
                        if "impulse" in model or "noise" in model:
                            decay = 18.0 if "impulse" in model else 5.0
                            audio = noise * np.exp(-time * decay)
                        elif "modal" in model or "reson" in model or "sine" in model:
                            ratios = [
                                float(item.get("ratio", 1.0))
                                for item in patch.spectrum.get("partials", [])
                            ] or [1.0, 1.414, 2.17]
                            partials = [
                                np.sin(2.0 * np.pi * frequency * ratio * time)
                                / (1.0 + partial_index)
                                for partial_index, ratio in enumerate(ratios)
                            ]
                            audio = np.sum(partials, axis=0)
                            if "tail" in model:
                                audio *= np.exp(-time * 3.5)
                        else:
                            audio = noise * np.exp(-time * 1.5)
                        audio = np.asarray(audio, dtype=np.float32)
                    if len(audio) < required_frames:
                        audio = np.pad(audio, (0, required_frames - len(audio)))
                    source_audio[source.source_id] = np.asarray(
                        audio[:required_frames], dtype=np.float32
                    )

                rng = np.random.default_rng(
                    derive_sound_object_seed(variation_seed, patch.patch_id, "m23-variation")
                )
                updated_layers = []
                for layer in patch.layers:
                    gain_scale = float(rng.uniform(0.84, 1.16))
                    decay_scale = float(rng.uniform(0.82, 1.18))
                    release_scale = float(rng.uniform(0.86, 1.14))
                    envelope = replace(
                        layer.envelope,
                        decay_seconds=float(np.clip(
                            layer.envelope.decay_seconds * decay_scale, 0.0, 30.0
                        )),
                        release_seconds=float(np.clip(
                            layer.envelope.release_seconds * release_scale, 0.0, 30.0
                        )),
                    )
                    updated_layers.append(replace(
                        layer,
                        gain=float(np.clip(layer.gain * gain_scale, 0.0, 4.0)),
                        envelope=envelope,
                    ))
                spectrum = copy.deepcopy(patch.spectrum)
                for partial in spectrum.get("partials", []):
                    partial["gain"] = float(np.clip(
                        float(partial.get("gain", 1.0)) * rng.uniform(0.84, 1.16),
                        0.0, 4.0,
                    ))
                modulation = copy.deepcopy(patch.modulation)
                if modulation and "depth" in modulation:
                    modulation["depth"] = float(np.clip(
                        float(modulation["depth"]) * rng.uniform(0.8, 1.2),
                        0.0, 1.0,
                    ))
                processing_id = f"{patch.processing_identity_id}:m23:{variation_seed}"
                transform = TransformationRecord(
                    operation="m23_seeded_hybrid_variation",
                    seed=int(variation_seed),
                    parameters={
                        "candidate_index": int(index),
                        "layer_gain_range": [0.84, 1.16],
                        "envelope_decay_range": [0.82, 1.18],
                        "envelope_release_range": [0.86, 1.14],
                    },
                    preserved_dimensions=(
                        "source_identity", "source_hashes", "layer_roles",
                        "phase_groups", "pitch_model",
                    ),
                    changed_dimensions=(
                        "processing_identity", "layer_gain", "envelope",
                        "spectral_partial_gain", "modulation_depth",
                    ),
                )
                variant_patch = replace(
                    patch,
                    seed=int(variation_seed),
                    processing_identity_id=processing_id,
                    layers=tuple(updated_layers),
                    spectrum=spectrum,
                    modulation=modulation,
                    transformations=patch.transformations + (transform,),
                )
                rendered = HybridVoiceRenderer().render(
                    variant_patch, source_audio,
                    frame_count=variant_patch.duration_frames,
                )
                rendered_audio = rendered.audio
                if patch.sample_rate != base.sample_rate:
                    rendered_audio, resample_record = resample_audio_non_destructive(
                        rendered_audio, patch.sample_rate, base.sample_rate,
                        seed=int(variation_seed),
                    )
                    variant_patch = replace(
                        variant_patch,
                        transformations=variant_patch.transformations + (resample_record,),
                    )
                if len(rendered_audio) > base.frame_count:
                    raise ValueError(
                        f"sound-object patch {patch.name!r} exceeds project duration"
                    )
                safe_patch_id = re.sub(r"[^A-Za-z0-9_-]+", "_", patch.patch_id).strip("_")
                stem_name = f"sound_object_{safe_patch_id or 'patch'}"
                if stem_name in stems and stem_name not in request.targets:
                    stem_name = f"{stem_name}_{index:02d}"
                audio = np.zeros((base.frame_count, 2), dtype=np.float32)
                audio[:len(rendered_audio)] = rendered_audio
                stems[stem_name] = audio
                variants.append({
                    "patch_id": patch.patch_id,
                    "name": patch.name,
                    "source_identity_id": patch.source_identity_id,
                    "source_hashes": list(patch.source_hashes),
                    "original_processing_identity_id": patch.processing_identity_id,
                    "processing_identity_id": variant_patch.processing_identity_id,
                    "seed": variation_seed,
                    "stem": stem_name,
                    "patch": variant_patch.to_dict(),
                    "diagnostics": rendered.diagnostics,
                })

        score = base.to_score()
        score_metadata = copy.deepcopy(score.metadata)
        score_metadata["render_stems"] = list(stems)
        score_metadata["m23_sound_object_variants"] = variants
        project_metadata = copy.deepcopy(base.metadata)
        project_metadata["sound_object_variants"] = variants
        project_metadata["m23_sound_object_variation_seed"] = variation_seed
        return ReawarpProject(
            config=base.config,
            sample_rate=base.sample_rate,
            stems=stems,
            events=copy.deepcopy(base.events),
            metadata=project_metadata,
            score=replace(score, metadata=score_metadata),
        )

    def _start_variation_batch(self, payload: dict[str, Any]) -> None:
        if self.project is None:
            self.statusBar().showMessage("Generate or load a project before creating variations.")
            return
        if self._worker is not None or self._variation_batch_worker is not None:
            return
        try:
            request = VariationRequest.from_dict(payload)
        except Exception as exc:
            self._show_error(f"Invalid variation request: {exc}")
            return
        if self._variation_origin_project is None:
            self._variation_origin_project = clone_project(self.project, readonly=True)
            self._variation_base_project = self._variation_origin_project
        base = self._variation_branch_base or self._variation_base_project
        if base is None:
            self.statusBar().showMessage("The frozen source project is unavailable.")
            return
        self.variation_page.set_batch_busy(True)
        epoch = self._variation_session_epoch
        parent_candidate_id = self._variation_parent_candidate_id

        def operation(cancel_event):
            batch = VariationBatchService().generate_batch(
                base, request, parent_candidate_id=parent_candidate_id,
                cancel_event=cancel_event,
                sound_object_renderer=(
                    self._render_sound_object_candidate
                    if request.mode == "sound_object" else None
                ),
            )
            return epoch, batch

        worker = CancellableRenderWorker(operation)
        self._variation_batch_worker = worker
        worker.signals.finished.connect(self._variation_batch_finished)
        worker.signals.error.connect(
            lambda message, epoch=epoch: self._variation_batch_failed((epoch, message))
        )
        QThreadPool.globalInstance().start(worker)
        self.statusBar().showMessage(
            f"Generating {request.count} comparable candidates · {request.mode.replace('_', ' ')}…"
        )

    def _cancel_variation_batch(self) -> None:
        if self._variation_batch_worker is not None:
            self._variation_batch_worker.cancel()
            self.statusBar().showMessage("Cancellation requested · the active render will stop at a safe boundary.")

    def _variation_batch_finished(self, result: object) -> None:
        if (
            not isinstance(result, tuple) or len(result) != 2
            or result[0] != self._variation_session_epoch
            or not isinstance(result[1], VariationBatch)
        ):
            return
        self._variation_batch_worker = None
        self.variation_page.set_batch_busy(False)
        result = result[1]
        for candidate in result.candidates:
            self._variation_candidates[candidate.record.candidate_id] = candidate
        records = [item.record for item in self._variation_candidates.values()]
        selected = result.candidates[-1].record.candidate_id if result.candidates else None
        self.variation_page.set_candidates(records, selected_id=selected)
        self.statusBar().showMessage(
            f"Variation batch complete · {len(result.candidates)} candidate(s) · source project remains frozen.",
            8000,
        )
    def _variation_batch_failed(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        epoch, message = payload
        if epoch != self._variation_session_epoch:
            return
        self._variation_batch_worker = None
        self.variation_page.set_batch_busy(False)
        if str(message).startswith("CANCELLED:"):
            self.statusBar().showMessage(
                "Variation batch cancelled · frozen source and previously completed batches are intact.",
                8000,
            )
        else:
            self._show_error(f"Variation batch failed: {message}")

    def _variation_candidate_selected(self, candidate_id: str) -> None:
        if candidate_id in self._variation_candidates:
            self._variation_compare(candidate_id)

    def _variation_sync_candidate(self, candidate: VariationCandidate) -> None:
        record = candidate.record.to_dict()
        metadata = copy.deepcopy(candidate.project.metadata)
        metadata["m23_candidate"] = record
        candidate.project.metadata = metadata
        score = candidate.project.to_score()
        score_metadata = dict(score.metadata)
        score_metadata["m23_candidate"] = record
        candidate.project.score = replace(score, metadata=score_metadata)

    def _variation_candidate_action(self, action: str, candidate_id: str) -> None:
        if action == "restore":
            if self._variation_origin_project is None:
                return
            self._variation_active_candidate_id = None
            self._variation_base_project = self._variation_origin_project
            self._variation_branch_base = None
            self._variation_parent_candidate_id = None
            self._render_finished(clone_project(self._variation_origin_project))
            return
        candidate = self._variation_candidates.get(candidate_id)
        if candidate is None:
            return
        candidate.record.selection_state = action
        self._variation_sync_candidate(candidate)
        if action in {"promoted", "branched"}:
            self._variation_active_candidate_id = candidate_id
            self._render_finished(clone_project(candidate.project))
        if action == "branched":
            self._variation_branch_base = clone_project(candidate.project, readonly=True)
            self._variation_parent_candidate_id = candidate_id
        self.variation_page.set_candidates(
            [item.record for item in self._variation_candidates.values()],
            selected_id=candidate_id,
        )
        self.statusBar().showMessage(
            f"{candidate.record.label} · {candidate.record.selection_state.upper()}", 6000
        )

    def _variation_notes_changed(self, candidate_id: str, notes: str) -> None:
        candidate = self._variation_candidates.get(candidate_id)
        if candidate is None:
            return
        candidate.record.notes = str(notes)
        self._variation_sync_candidate(candidate)

    def _variation_candidate_stem(self, candidate: VariationCandidate) -> str | None:
        variants = candidate.project.metadata.get("sound_object_variants", [])
        targets = set(candidate.record.targets)
        for item in variants:
            if isinstance(item, dict) and item.get("patch_id") in targets:
                stem = str(item.get("stem", ""))
                if stem in candidate.project.stems:
                    return stem
        for target in candidate.record.targets:
            if target in candidate.project.stems:
                return target
        return next(iter(candidate.project.stems), None)

    def _variation_compare(self, candidate_id: str) -> None:
        candidate = self._variation_candidates.get(candidate_id)
        if candidate is None:
            return
        reference_project = (
            self._variation_candidates[candidate.record.parent_candidate_id].project
            if candidate.record.parent_candidate_id in self._variation_candidates
            else self._variation_origin_project
        )
        if reference_project is None:
            reference_project = self._variation_branch_base or self._variation_base_project
        if reference_project is None:
            return
        stage = str(self.variation_page.compare_stage.currentData() or "dry_master")
        stem = self._variation_candidate_stem(candidate)
        if stage == "dry_master":
            left, right = project_audio(reference_project), project_audio(candidate.project)
            try:
                self._show_variation_comparison(
                    matched_ab(left, right, sample_rate=reference_project.sample_rate)
                )
            except Exception as exc:
                self.statusBar().showMessage(f"Could not compare candidates: {exc}", 8000)
            return
        if stage == "dry_stem":
            if stem is None:
                return
            right = project_audio(candidate.project, stem=stem)
            left = (
                np.zeros_like(right) if stem not in reference_project.stems
                else project_audio(reference_project, stem=stem)
            )
            try:
                self._show_variation_comparison(
                    matched_ab(left, right, sample_rate=reference_project.sample_rate)
                )
            except Exception as exc:
                self.statusBar().showMessage(f"Could not compare candidates: {exc}", 8000)
            return

        if self._variation_compare_worker is not None:
            self._variation_compare_worker.cancel()
        signature = (candidate_id, stage)
        self._variation_compare_signature = signature
        self._routing_signature()  # synchronise portable fader state before snapshotting
        routing = self.fx_routing_editor.routing()
        legacy_automation = self.fx_automation_editor.automation()
        mix_controls = {
            name: {
                "gain": row.gain.value() / 100.0,
                "pan": row.pan.value() / 100.0,
                "mute": row.mute.isChecked(),
                "solo": row.solo.isChecked(),
            }
            for name, row in self._mix_rows.items()
        }
        reference_compare_project = reference_project
        if stem is not None and stem not in reference_project.stems:
            reference_stems = dict(reference_project.stems)
            reference_stems[stem] = np.zeros_like(candidate.project.stems[stem])
            reference_score = reference_project.to_score()
            reference_score_metadata = dict(reference_score.metadata)
            reference_score_metadata["render_stems"] = list(reference_stems)
            reference_compare_project = replace(
                reference_project,
                stems=reference_stems,
                score=replace(reference_score, metadata=reference_score_metadata),
            )
        projects = (reference_compare_project, candidate.project)

        def operation(cancel_event):
            rendered = []
            for project in projects:
                if cancel_event.is_set():
                    raise RuntimeError("variation comparison cancelled")
                score = project.to_score()
                controls = None
                if score.automation or score.automation_sources or score.modulations:
                    if legacy_automation:
                        score = attach_fx_automation_to_score(
                            score, legacy_automation, tuple(project.stems)
                        )
                    controls = build_score_control_bus(
                        score, project.sample_rate,
                        automation_registry=fx_automation_registry(tuple(project.stems)),
                    )
                dry_stems = {
                    name: np.asarray(audio, dtype=np.float32).copy()
                    for name, audio in project.stems.items()
                }
                processed, metadata = render_fx_routing(
                    dry_stems, project.sample_rate, routing,
                    bpm=project.config.bpm,
                    automation=legacy_automation if controls is None else None,
                    controls=controls,
                    mix_controls=mix_controls,
                    include_audition_audio=True,
                    cancel_event=cancel_event,
                )
                rendered.append((processed, metadata))
            return {"signature": signature, "rendered": rendered}

        worker = CancellableRenderWorker(operation)
        self._variation_compare_worker = worker
        worker.signals.finished.connect(self._variation_compare_finished)
        worker.signals.error.connect(
            lambda message, requested=signature: self._variation_compare_failed((requested, message))
        )
        QThreadPool.globalInstance().start(worker)
        self.statusBar().showMessage(f"Rendering matched comparison · {stage.replace('.', ' ').upper()}…")

    def _show_variation_comparison(self, result: dict[str, Any]) -> None:
        self._variation_ab_buffers = {
            "reference": result["reference"],
            "candidate": result["candidate"],
            "difference": result["difference"],
        }
        self.variation_page.set_comparison(
            result["reference"], result["candidate"], result["difference"],
            int(result["sample_rate"]),
        )
        report = result["difference_meter"]
        self.statusBar().showMessage(
            "Matched A/B · -18 dBFS RMS target where peak headroom permits · "
            f"difference peak {report['peak_dbfs']:.1f} dBFS",
            6000,
        )

    def _variation_compare_finished(self, result: object) -> None:
        if not isinstance(result, dict) or result.get("signature") != self._variation_compare_signature:
            return
        self._variation_compare_worker = None
        candidate_id, stage = result["signature"]
        candidate = self._variation_candidates.get(candidate_id)
        if candidate is None:
            return
        reference_project = (
            self._variation_candidates[candidate.record.parent_candidate_id].project
            if candidate.record.parent_candidate_id in self._variation_candidates
            else self._variation_origin_project
        )
        if reference_project is None:
            reference_project = self._variation_branch_base or self._variation_base_project
        if reference_project is None:
            return
        stem = self._variation_candidate_stem(candidate)

        def extract(item):
            processed, metadata = item
            audition = metadata.get("audition_audio", {})
            if stage == "direct":
                return audition["direct"][stem]
            if stage == "processed":
                return processed[stem]
            if stage == "insert":
                return audition["insert"][stem]
            if stage.startswith("send."):
                return audition["sends"][stem][stage.split(".", 1)[1]]
            if stage.startswith("return."):
                return audition["returns"][stage.split(".", 1)[1]]
            if stage == "master":
                return render_master_with_returns(
                    processed, metadata.get("bus_returns_audio", {}),
                    master_wet=float(metadata.get("master_wet", 1.0)),
                )
            raise ValueError(f"unsupported comparison stage: {stage}")

        try:
            left, right = extract(result["rendered"][0]), extract(result["rendered"][1])
            self._show_variation_comparison(
                matched_ab(left, right, sample_rate=reference_project.sample_rate)
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Could not compare routing stages: {exc}", 8000)

    def _variation_compare_failed(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        signature, message = payload
        if signature != self._variation_compare_signature:
            return
        self._variation_compare_worker = None
        if str(message).startswith("CANCELLED:"):
            return
        self.statusBar().showMessage(f"Variation comparison failed: {message}", 10000)


    def _variation_listening_set(self, preset: str) -> None:
        candidate_id = self.variation_page.selected_candidate_id
        selected = self._variation_candidates.get(candidate_id or "")
        project = selected.project if selected is not None else (
            self._variation_branch_base or self._variation_base_project
        )
        if project is None:
            return
        try:
            buffers = build_listening_set(project, preset)
        except Exception as exc:
            self.statusBar().showMessage(f"Listening set failed: {exc}", 8000)
            return
        self._variation_listening_buffers = {
            str(label): np.asarray(audio, dtype=np.float32).copy()
            for label, audio in buffers.items()
        }
        self.variation_page.set_listening_items(self._variation_listening_buffers)
        if buffers:
            self.statusBar().showMessage(
                f"Listening set · {preset.replace('_', ' ').upper()} · {len(buffers)} excerpt(s)",
                5000,
            )

    def _variation_listening_item(self, label: str) -> None:
        audio = self._variation_listening_buffers.get(label)
        if audio is None:
            return
        self._variation_ab_buffers["listening"] = audio
        sample_rate = (
            self._variation_candidates.get(self.variation_page.selected_candidate_id or "").project.sample_rate
            if self.variation_page.selected_candidate_id in self._variation_candidates
            else (self._variation_base_project.sample_rate if self._variation_base_project else 48_000)
        )
        self.variation_page.set_listening_audio(audio, sample_rate)

    def _variation_audition(self, source: str) -> None:
        audio = self._variation_ab_buffers.get(source)
        if audio is None:
            self.statusBar().showMessage("Run a matched comparison or choose a listening set first.")
            return
        project = self._variation_branch_base or self._variation_base_project or self.project
        if project is None:
            return
        if source == "listening":
            audio, _report = match_audition_level(audio)
        try:
            self.player.start(audio, project.sample_rate, device=self.output_device.currentData())
        except Exception as exc:
            self.statusBar().showMessage(f"Could not audition comparison: {exc}", 8000)

    def _project_with_variation_session(self) -> ReawarpProject:
        if self.project is None:
            raise RuntimeError("no active project")
        if self._variation_origin_project is None or not self._variation_candidates:
            return self.project
        origin = clone_project(self._variation_origin_project)
        origin_fingerprint = project_fingerprint(origin)
        origin.metadata.pop("m23_candidate", None)
        origin.metadata["m23_project_fingerprint"] = origin_fingerprint
        variation_projects: dict[str, ReawarpProject] = {"base": origin}
        branch_fingerprint = None
        if self._variation_branch_base is not None:
            branch = clone_project(self._variation_branch_base)
            branch_fingerprint = project_fingerprint(branch)
            branch.metadata.pop("m23_candidate", None)
            branch.metadata["m23_project_fingerprint"] = origin_fingerprint
            variation_projects["branch_base"] = branch
        for candidate_id, candidate in self._variation_candidates.items():
            self._variation_sync_candidate(candidate)
            variation_projects[candidate_id] = candidate.project
        session = variation_session_metadata(
            origin, self._variation_candidates,
            active_candidate_id=self._variation_active_candidate_id,
        )
        session["active_branch_fingerprint"] = branch_fingerprint
        metadata = copy.deepcopy(self.project.metadata)
        metadata.pop("m23_candidate", None)
        metadata["m23_active_candidate_id"] = self._variation_active_candidate_id
        metadata["m23_project_fingerprint"] = origin_fingerprint
        metadata["m23_variations"] = session
        return replace(self.project, metadata=metadata, variation_candidates=variation_projects)

    def _regenerate_stem(self, name: str) -> None:
        if self.project is None:
            return
        variation = self._variation_counts.get(name, 0) + 1
        self._variation_counts[name] = variation
        config = self.project.config
        base_project = self.project
        self._run_render(
            lambda cancel_event: ReawarpEngine().generate_variant(
                config, name, variation, base_project=base_project,
                cancel_event=cancel_event,
            ),
            f"Regenerating {name} · variation {variation}…",
        )

    def _cancel_background_job(self) -> None:
        cancelled = False
        for worker in (self._worker, self._export_worker):
            if worker is not None:
                worker.cancel()
                cancelled = True
        if cancelled:
            self.cancel_background_button.setEnabled(False)
            self.statusBar().showMessage(
                "Cancellation requested · the worker will stop at its next safe checkpoint.",
                8000,
            )

    def _run_render(self, operation: Any, message: str) -> None:
        if self._worker is not None:
            return
        self._set_busy(True, message)
        worker = CancellableRenderWorker(operation)
        self._worker = worker
        worker.signals.finished.connect(self._render_finished)
        worker.signals.error.connect(self._render_failed)
        QThreadPool.globalInstance().start(worker)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.generate_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_background_button.setVisible(busy or self._export_worker is not None)
        self.cancel_background_button.setEnabled(busy or self._export_worker is not None)
        for row in self._mix_rows.values():
            row.regen.setEnabled(not busy and row.can_regenerate)
        self.header_state.setText("RENDERING…" if busy else "OFFLINE RENDER ENGINE")
        if message:
            self.statusBar().showMessage(message)

    def _render_finished(self, result: object) -> None:
        self._worker = None
        if not isinstance(result, ReawarpProject):
            self._set_busy(False)
            self._show_error("Render worker returned an unexpected result.")
            return
        previous_names = tuple(self.project.stems) if self.project is not None else ()
        previous_routing = self.fx_routing_editor.routing() if previous_names else None
        previous_automation = self.fx_automation_editor.automation() if previous_names else None
        project_routing = result.metadata.get("project_fx_routing")
        project_automation = result.metadata.get("project_fx_automation")
        self.player.stop()
        self._playback_stopped()
        self.project = result
        asset_audit = result.metadata.get("project_asset_validation")
        file_audit = result.metadata.get("project_file_validation")
        audit_warnings = []
        if isinstance(asset_audit, dict):
            audit_warnings.extend(asset_audit.get("missing", []))
            audit_warnings.extend(asset_audit.get("changed", []))
        if isinstance(file_audit, dict):
            audit_warnings.extend(file_audit.get("missing", []))
            audit_warnings.extend(file_audit.get("changed", []))
        if audit_warnings:
            self.statusBar().showMessage(
                f"Project opened with {len(audit_warnings)} missing/changed asset or archive file(s). "
                "No replacement samples were selected; inspect project manifest and asset validation.",
                15000,
            )
        self._fx_project_revision += 1
        self.score_automation_editor.set_score(result.to_score())
        if self._fx_worker is not None:
            self._fx_worker.cancel()
        self._fx_worker = None
        self._fx_pending_signature = None
        self._fx_queued_signature = None
        self._fx_processed_stems = {}
        self._fx_bus_returns = {}
        self._fx_routing_metadata = {}
        self._fx_audition_audio = {}
        self.fx_routing_editor.set_variation_choices([])
        if self._fx_variation_worker is not None:
            self._fx_variation_worker.cancel()
            self._fx_variation_signature = None
        else:
            self._clear_fx_variation_cache()
        self.fx_routing_editor.set_meter_report({})
        self._rebuild_mixer()
        self.variation_page.set_stems(list(result.stems))
        self._refresh_sound_object_targets()
        self._restore_variation_session(result)
        self.fx_lab_page.set_project_sources(result.stems, result.sample_rate)
        self.mixer_stack.setCurrentIndex(1)
        self._update_project_context()
        self.preview_source.setEnabled(True)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.fx_routing_editor.set_stems(list(result.stems), result.sample_rate, result.config.bpm)
        self.fx_automation_editor.set_project(list(result.stems), result.config.bpm)
        if isinstance(project_routing, dict):
            self.fx_routing_editor.set_routing(project_routing)
        elif previous_routing is not None and previous_names == tuple(result.stems):
            self.fx_routing_editor.set_routing(previous_routing)
        if isinstance(project_automation, dict):
            self.fx_automation_editor.set_automation(project_automation)
        elif previous_automation is not None and previous_names == tuple(result.stems):
            self.fx_automation_editor.set_automation(previous_automation)
        self.preview_source.blockSignals(True)
        self.preview_source.clear()
        self.preview_source.addItem("MASTER MIX", "master")
        for name in result.stems:
            self.preview_source.addItem(name.replace("_", " ").upper(), name)
        self.preview_source.blockSignals(False)
        self.preview_source.setCurrentIndex(0)
        self.export_button.setEnabled(True)
        self.open_mixer_button.setEnabled(True)
        self.open_fx_button.setEnabled(True)
        self.open_library_button.setEnabled(True)
        self._refresh_preview()
        phrase_report = result.metadata.get("phrase_directives", [])
        phrase_line = " → ".join(
            str(item.get("function", "")).upper() for item in phrase_report
        )
        phrase_detail = " | ".join(
            f"{str(item.get('function', '')).upper()} "
            f"b{item.get('start_bar', 0) + 1}–{item.get('end_bar', 0)} "
            f"({float(item.get('start_bar', 0)) * 240.0 / result.config.bpm:.1f}–"
            f"{float(item.get('end_bar', 0)) * 240.0 / result.config.bpm:.1f}s)"
            for item in phrase_report
        )
        drum_plan = result.metadata.get("drum_arrangement", [])
        drum_line = " → ".join(
            f"{item.get('section_name', '').upper()} "
            f"[{item.get('kick_family', '')}/{item.get('snare_family', '')}/{item.get('hat_family', '')}]"
            for item in drum_plan
        )
        profile_map = result.metadata.get("drum_section_profiles", {})
        profile_line = " | ".join(
            f"{section}: {profile_map.get('kick', {}).get(section, '—')}/"
            f"{profile_map.get('snare', {}).get(section, '—')}/"
            f"{profile_map.get('hat', {}).get(section, '—')}"
            for section in profile_map.get("kick", {})
        )
        loaded_sources = [
            f"{role}:{source.get('source', {}).get('source_name', Path(source.get('path', role)).name)}"
            for role, source in result.metadata.get("sample_sources", {}).items()
        ]
        switch_summary = result.metadata.get("sample_switch_summary", {})
        bank_summary = " · ".join(
            f"{role.upper()} {details.get('bank_count', 0)} sounds / "
            f"{details.get('switch_count', 0)} switches"
            for role, details in switch_summary.items()
            if details.get("bank_count", 0)
        )
        switch_timeline = " | ".join(
            f"{role.upper()}: " + ", ".join(
                f"{item.get('section', '?')} → {item.get('label', item.get('to_index', '?'))}"
                for item in details.get("switch_points", [])
            )
            for role, details in switch_summary.items()
            if details.get("switch_points")
        )
        source_line = (
            f"{result.config.percussion_source_mode.upper()} · "
            f"{result.config.percussion_hybrid_architecture.replace('_', ' ')}"
        )
        motif_data = result.metadata.get("motif_plan") or {}
        motif_anchor = motif_data.get("anchor", {})
        motif_id = motif_anchor.get("motif_id")
        motif_instances = motif_data.get("instances", [])
        motif_line = " → ".join(
            f"{item.get('section_name', '?')}:{item.get('operation', '?')}"
            for item in motif_instances
        )
        transition_line = " · ".join(
            f"{item.get('gesture', '?')} @ bar {int(item.get('boundary_bar', 0)) + 1}"
            for item in result.metadata.get("transition_gestures", [])
        )
        role_line = " | ".join(
            f"{item.get('section_name', '?')}:"
            + "/".join(
                str(role.get("role", "")) for role in item.get("roles", [])
                if role.get("active")
            )
            for item in result.metadata.get("section_orchestration", [])
        )
        self.render_summary.setText(
            f"{result.duration:.2f} s · {result.sample_rate:,} Hz · "
            f"{len(result.stems)} stems · {len(result.events)} events · "
            f"seed {result.config.seed} · algorithm {result.metadata.get('algorithm_version', '?')}\n"
            f"PHRASES: {phrase_line or 'n/a'}"
            + (f"\nFORM MAP: {phrase_detail}" if phrase_detail else "")
            + (f"\nDRUM EVOLUTION: {drum_line}" if drum_line else "\nDRUM EVOLUTION: static mode")
            + (f"\nDRUM TIMBRES: {profile_line}" if profile_line else "")
            + f"\nSOURCE ENGINE: {source_line}"
            + (f"\nMOTIF: {motif_id} · {motif_line}" if motif_id else "")
            + (f"\nROLE PLAN: {role_line}" if role_line else "")
            + (f"\nTRANSITIONS: {transition_line}" if transition_line else "")
            + (f"\nSAMPLE BANKS: {bank_summary}" if bank_summary else "")
            + (f"\nSAMPLE SWITCHES: {switch_timeline}" if switch_timeline else "")
            + (f"\nSAMPLE MATERIAL: {', '.join(loaded_sources)}" if loaded_sources else "")
        )
        self.statusBar().showMessage(
            f"Render complete — {len(result.events)} events, {len(result.stems)} aligned stems",
            8000,
        )
        self._set_busy(False)

    def _render_failed(self, message: str) -> None:
        self._worker = None
        self._set_busy(False)
        if str(message).startswith("CANCELLED:"):
            self.statusBar().showMessage("Background render cancelled.", 8000)
            return
        # Workers print the complete traceback; keep the dialog concise so the
        # error can be copied from the terminal instead of a giant modal.
        first_line = str(message).splitlines()[0] if str(message) else "Unknown render error"
        self._show_error(first_line + "\n\nFull traceback was printed in the terminal.")

    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 10000)
        QMessageBox.warning(self, "Reawarp", message)

    def _rebuild_mixer(self) -> None:
        previous = {name: row.state() for name, row in self._mix_rows.items()}
        while self.mixer_rows_layout.count():
            item = self.mixer_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._mix_rows.clear()
        if self.project is None:
            return
        supported = {
            "kick", "snare", "hats", "synthetic_break", "melody",
            "noise_texture", "ambience", "sample_break",
        }
        for name in self.project.stems:
            row = StemRow(name, name in supported)
            if name in previous:
                row.restore(previous[name])
            row.selected.connect(self._select_stem)
            row.regenerate.connect(self._regenerate_stem)
            row.changed.connect(self._refresh_preview)
            self._mix_rows[name] = row
            self.mixer_rows_layout.addWidget(row)
        self.mixer_rows_layout.addStretch(1)

    def _select_stem(self, name: str) -> None:
        index = self.preview_source.findData(name)
        if index >= 0:
            self.preview_source.setCurrentIndex(index)
        self._set_workspace(0)

    def _apply_routing_mixer_state(self, states: dict[str, dict[str, Any]]) -> None:
        """Restore portable routing-file faders into the visible mixer rows."""
        for name, values in states.items():
            row = self._mix_rows.get(name)
            if row is None:
                continue
            gain = 10.0 ** (float(values.get("gain_db", 0.0)) / 20.0)
            row.gain.setValue(int(round(np.clip(gain, 0.0, 4.0) * 100)))
            row.pan.setValue(int(round(float(values.get("pan", 0.0)) * 100)))
            row.mute.setChecked(bool(values.get("mute", False)))
            row.solo.setChecked(bool(values.get("solo", False)))
        self._refresh_preview()

    def _clear_fx_variation_cache(self) -> None:
        """Release the previous on-disk audition batch and its route snapshots."""
        directory = self._fx_variation_cache_dir
        self._fx_variation_cache_dir = None
        self._fx_variation_renders.clear()
        self._fx_variation_signature = None
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        if hasattr(self, "fx_routing_editor"):
            self.fx_routing_editor.set_variation_choices([])

    def _apply_fx_lab_chain_to_stem(
        self, stem_name: str, stages: object, wet: float, tail_seconds: float
    ) -> None:
        if self.project is None:
            self.statusBar().showMessage("Generate or load a project before assigning a stem insert.")
            return
        try:
            self.fx_routing_editor.set_custom_insert(
                stem_name, list(stages), wet=float(wet),
                tail_seconds=float(tail_seconds),
            )
        except Exception as exc:
            self._show_error(f"Could not assign the FX Lab chain: {exc}")
            return
        self._set_workspace(2)
        self.statusBar().showMessage(
            f"Custom FX Lab chain assigned to {stem_name}; pre-render the channel FX to audition the mix.",
            8000,
        )

    def _retry_fx_render(self) -> None:
        """Clear the failed routing cache and retry the current snapshot."""
        if self.project is None or self._fx_worker is not None:
            return
        self._fx_routing_metadata = {}
        self._fx_processed_stems = {}
        self._fx_bus_returns = {}
        self._fx_audition_audio = {}
        self.fx_render_state.setText("FX RENDERING…")
        self.fx_render_state.setToolTip("")
        self.fx_render_state.setStyleSheet("")
        self.retry_fx_button.setEnabled(False)
        self._ensure_routing_render()

    def _pre_render_channel_fx(self) -> None:
        """Explicitly pre-render all current stem inserts and shared returns."""
        if self.project is None:
            self.statusBar().showMessage("Generate or load a composition before pre-rendering FX.")
            return
        if self._fx_worker is not None:
            self.statusBar().showMessage("Channel FX are already rendering in the background.")
            return
        if self._ensure_routing_render():
            self.statusBar().showMessage(
                "Current channel FX are already pre-rendered; PLAY now uses the processed stems and returns.",
                8000,
            )
        else:
            self.statusBar().showMessage(
                "Pre-rendering every channel insert and the shared SPACE/ECHO returns…",
                8000,
            )

    def _generate_fx_variations(self, count: int, variation_seed: int) -> None:
        """Render deterministic role-aware FX alternatives from the frozen project."""
        if self.project is None:
            self.statusBar().showMessage("Generate or load a composition before making FX variations.")
            return
        if self._fx_worker is not None:
            self.statusBar().showMessage(
                "Wait for the current channel FX pre-render to finish before generating variants.",
                8000,
            )
            return
        if self._fx_variation_worker is not None:
            return

        signature = self._routing_signature()
        project = self.project
        score = project.to_score()
        legacy_automation = copy.deepcopy(self.fx_automation_editor.automation())
        stem_names = tuple(project.stems)
        controls = None
        if score.automation or score.automation_sources or score.modulations:
            if legacy_automation:
                score = attach_fx_automation_to_score(score, legacy_automation, stem_names)
            controls = build_score_control_bus(
                score, project.sample_rate,
                automation_registry=fx_automation_registry(stem_names),
            )
        base_routing = copy.deepcopy(self.fx_routing_editor.routing())
        # render_fx_routing owns its working copies and never mutates source arrays.
        dry_stems = {
            name: np.asarray(audio, dtype=np.float32)
            for name, audio in project.stems.items()
        }
        sample_rate = int(project.sample_rate)
        bpm = float(project.config.bpm)
        project_context = {
            "config": project.config.to_dict(),
            "algorithm_version": project.metadata.get("algorithm_version"),
            "renderer_version": project.metadata.get("renderer_version"),
            "motif_plan": project.metadata.get("motif_plan"),
            "section_orchestration": project.metadata.get("section_orchestration"),
            "drum_arrangement": project.metadata.get("drum_arrangement"),
            "sample_switch_summary": project.metadata.get("sample_switch_summary"),
        }
        cache_dir = Path(tempfile.mkdtemp(prefix="reawarp-fx-variants-"))
        self._clear_fx_variation_cache()
        self._fx_variation_cache_dir = cache_dir
        self._fx_variation_signature = signature

        def operation(cancel_event):
            candidates = build_fx_variation_routings(
                stem_names, sample_rate, base_routing,
                project_context=project_context,
                variation_seed=int(variation_seed),
                count=int(count),
                bpm=bpm,
            )
            rendered_records = []
            for candidate in candidates:
                if cancel_event.is_set():
                    raise RuntimeError("FX variation render cancelled")
                processed, metadata = render_fx_routing(
                    dry_stems, sample_rate, candidate["routing"],
                    bpm=bpm,
                    automation=legacy_automation if controls is None else None,
                    controls=controls,
                    include_audition_audio=False,
                    cancel_event=cancel_event,
                )
                returns = metadata.pop("bus_returns_audio", {})
                master = render_master_with_returns(
                    processed, returns,
                    master_wet=float(candidate["routing"]["master_wet"]),
                )
                cache_path = cache_dir / f"{candidate['candidate_id']}.npy"
                np.save(cache_path, master, allow_pickle=False)
                rendered_records.append({
                    "candidate_id": candidate["candidate_id"],
                    "label": candidate["label"],
                    "description": candidate["description"],
                    "seed": candidate["seed"],
                    "routing": candidate["routing"],
                    "cache_path": str(cache_path),
                    "master_metrics": measure_signal(master, sample_rate=sample_rate),
                    "render_meters": metadata.get("meters", {}),
                })
                del master, processed, returns, metadata
            return {
                "signature": signature,
                "cache_dir": str(cache_dir),
                "records": rendered_records,
            }

        worker = CancellableRenderWorker(operation)
        self._fx_variation_worker = worker
        self.fx_routing_editor.generate_variations_button.setEnabled(False)
        self.statusBar().showMessage(
            f"Pre-rendering {count} role-aware FX alternatives from project seed "
            f"{project.config.seed} / variation seed {variation_seed}…",
            10000,
        )
        worker.signals.finished.connect(self._fx_variations_finished)
        worker.signals.error.connect(self._fx_variations_failed)
        QThreadPool.globalInstance().start(worker)

    def _fx_variations_finished(self, result: object) -> None:
        self._fx_variation_worker = None
        self.fx_routing_editor.generate_variations_button.setEnabled(True)
        if not isinstance(result, dict):
            self._fx_variations_failed("FX variation worker returned an invalid result.")
            return
        signature = str(result.get("signature", ""))
        if (
            signature != self._routing_signature()
            or signature != self._fx_variation_signature
        ):
            shutil.rmtree(str(result.get("cache_dir", "")), ignore_errors=True)
            self._clear_fx_variation_cache()
            self.statusBar().showMessage(
                "FX variation render discarded because the project or routing changed.",
                8000,
            )
            return
        self._fx_variation_renders = {
            str(item["candidate_id"]): item for item in result.get("records", [])
        }
        self.fx_routing_editor.set_variation_choices([
            (candidate_id, str(item["label"]))
            for candidate_id, item in self._fx_variation_renders.items()
        ])
        self.statusBar().showMessage(
            f"{len(self._fx_variation_renders)} FX alternatives pre-rendered. "
            "Play a variant, then USE ROUTE to make it the active Stem Mixer setting.",
            10000,
        )

    def _fx_variations_failed(self, message: object) -> None:
        self._fx_variation_worker = None
        if hasattr(self, "fx_routing_editor"):
            self.fx_routing_editor.generate_variations_button.setEnabled(True)
        self._clear_fx_variation_cache()
        detail = str(message)
        if "cancelled" in detail.casefold():
            self.statusBar().showMessage("FX variation rendering cancelled.", 8000)
        elif "pyo" in detail.casefold() or "portaudio" in detail.casefold():
            self.statusBar().showMessage(
                f"FX variation render needs the optional Pyo backend. Install with "
                f"python -m pip install -e \".[pyo]\" · {detail}",
                12000,
            )
        else:
            self._show_error(f"FX variation render failed: {detail}")

    def _audition_fx_variation(self, candidate_id: str) -> None:
        record = self._fx_variation_renders.get(str(candidate_id))
        if record is None or self.project is None:
            return
        if self._fx_variation_signature != self._routing_signature():
            self.statusBar().showMessage(
                "This FX batch is stale. Generate a fresh batch for the current routing.",
                8000,
            )
            return
        try:
            audio = np.load(record["cache_path"], allow_pickle=False)
            match_report = None
            if self.fx_routing_editor.match_audition_level():
                audio, match_report = match_audition_level(
                    audio, target_rms_dbfs=-18.0, peak_ceiling=0.95
                )
            self.player.stop()
            self.player.start(
                audio, self.project.sample_rate,
                device=self.output_device.currentData(),
            )
            self.play_button.setText("PAUSE")
            suffix = (
                f" · audition RMS {match_report['output_rms_dbfs']:.1f} dBFS"
                if match_report is not None else ""
            )
            self.statusBar().showMessage(
                f"Auditioning {record['label']}{suffix}; production routing and dry stems are unchanged.",
                8000,
            )
        except Exception as exc:
            self._show_error(f"Could not audition FX variation: {exc}")

    def _apply_fx_variation(self, candidate_id: str) -> None:
        record = self._fx_variation_renders.get(str(candidate_id))
        if record is None:
            return
        try:
            self.fx_routing_editor.set_routing(copy.deepcopy(record["routing"]))
        except Exception as exc:
            self._show_error(f"Could not apply FX variation route: {exc}")
            return
        self.statusBar().showMessage(
            f"Applied {record['label']} routing. Channels will be pre-rendered for the active project.",
            8000,
        )

    def _routing_signature(self) -> str:
        import hashlib

        score = self.project.to_score() if self.project is not None else None
        mixer_state = {
            name: {
                "gain": row.gain.value() / 100.0,
                "gain_db": 20.0 * float(np.log10(max(row.gain.value() / 100.0, 0.001))),
                "pan": row.pan.value() / 100.0,
                "mute": row.mute.isChecked(),
                "solo": row.solo.isChecked(),
            }
            for name, row in self._mix_rows.items()
        }
        self.fx_routing_editor.set_mixer_state(mixer_state)
        payload = {
            "project_revision": self._fx_project_revision,
            "routing": self.fx_routing_editor.routing(),
            "automation": self.fx_automation_editor.automation(),
            "mixer": mixer_state,
            "score_automation": (
                {
                    "lanes": [lane.to_dict() for lane in score.automation],
                    "sources": [source.to_dict() for source in score.automation_sources],
                    "modulations": [item.to_dict() for item in score.modulations],
                }
                if score is not None else None
            ),
            "bpm": float(self.project.config.bpm) if self.project is not None else 120.0,
        }
        encoded = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _ensure_routing_render(self) -> bool:
        """Start or confirm the cancellable FX cache render for the current snapshot."""
        if self.project is None:
            return False
        signature = self._routing_signature()
        if self._fx_routing_metadata.get("_routing_signature") == signature:
            return True
        if self._fx_worker is not None:
            if self._fx_pending_signature != signature:
                self._fx_queued_signature = signature
                self._fx_worker.cancel()
            return False

        score = self.project.to_score()
        legacy_automation = self.fx_automation_editor.automation()
        stem_names = tuple(self.project.stems)
        controls = None
        if score.automation or score.automation_sources or score.modulations:
            if legacy_automation:
                score = attach_fx_automation_to_score(
                    score, legacy_automation, stem_names
                )
            controls = build_score_control_bus(
                score,
                self.project.sample_rate,
                automation_registry=fx_automation_registry(stem_names),
            )

        # The routing renderer snapshots each input internally; retaining the
        # immutable project arrays here avoids a second full-project audio copy.
        dry_stems = {
            name: np.asarray(audio, dtype=np.float32)
            for name, audio in self.project.stems.items()
        }
        routing = self.fx_routing_editor.routing()
        mix_controls = {
            name: {
                "gain": row.gain.value() / 100.0,
                "pan": row.pan.value() / 100.0,
                "mute": row.mute.isChecked(),
                "solo": row.solo.isChecked(),
            }
            for name, row in self._mix_rows.items()
        }
        sample_rate = int(self.project.sample_rate)
        bpm = float(self.project.config.bpm)

        def operation(cancel_event):
            processed, metadata = render_fx_routing(
                dry_stems,
                sample_rate,
                routing,
                bpm=bpm,
                automation=legacy_automation if controls is None else None,
                controls=controls,
                mix_controls=mix_controls,
                include_audition_audio=True,
                cancel_event=cancel_event,
            )
            return {
                "signature": signature,
                "processed": processed,
                "metadata": metadata,
            }

        worker = CancellableRenderWorker(operation)
        self._fx_worker = worker
        self._fx_pending_signature = signature
        if hasattr(self, "fx_render_state"):
            self.fx_render_state.setText("FX RENDERING…")
            self.fx_render_state.setToolTip("")
            self.fx_render_state.setStyleSheet("")
        if hasattr(self, "retry_fx_button"):
            self.retry_fx_button.setEnabled(False)
        self._fx_queued_signature = None
        worker.signals.finished.connect(self._fx_render_finished)
        worker.signals.error.connect(
            lambda message, requested=signature: self._fx_render_failed(
                requested, message
            )
        )
        QThreadPool.globalInstance().start(worker)
        self.statusBar().showMessage("Rendering role-aware FX routing in background…")
        return False

    def _fx_render_finished(self, result: object) -> None:
        if not isinstance(result, dict):
            self._fx_render_failed(
                self._fx_pending_signature or "", "FX worker returned an invalid result."
            )
            return
        signature = str(result.get("signature", ""))
        if self._fx_pending_signature != signature:
            return
        self._fx_worker = None
        self._fx_pending_signature = None
        if signature == self._routing_signature():
            metadata = dict(result["metadata"])
            self._fx_bus_returns = {
                name: np.asarray(audio, dtype=np.float32).copy()
                for name, audio in metadata.pop("bus_returns_audio", {}).items()
            }
            self._fx_audition_audio = metadata.pop("audition_audio", {})
            self._fx_processed_stems = {
                name: np.asarray(audio, dtype=np.float32).copy()
                for name, audio in result["processed"].items()
            }
            metadata["_routing_signature"] = signature
            self._fx_routing_metadata = metadata
            if hasattr(self, "fx_render_state"):
                self.fx_render_state.setText(
                    f"FX READY · {len(metadata.get('rendered_returns', []))} RETURNS"
                )
                self.fx_render_state.setToolTip(
                    "Configured stem inserts and active SPACE/ECHO returns are pre-rendered."
                )
                self.fx_render_state.setStyleSheet("")
            if hasattr(self, "retry_fx_button"):
                self.retry_fx_button.setEnabled(False)
            logger.info(
                "FX routing render complete: %d processed stems; rendered returns=%s",
                len(self._fx_processed_stems), metadata.get("rendered_returns", []),
            )
            self.statusBar().showMessage(
                "Role-aware inserts and SPACE/ECHO returns are ready.", 5000
            )
        self._fx_queued_signature = None
        self._refresh_preview()

    def _fx_render_failed(self, signature: str, message: str) -> None:
        if self._fx_pending_signature != signature:
            return
        self._fx_worker = None
        self._fx_pending_signature = None
        cancelled = str(message).startswith("CANCELLED:")
        current_signature = self._routing_signature() if self.project is not None else ""
        if not cancelled and signature == current_signature and self.project is not None:
            self._fx_processed_stems = {
                name: np.asarray(audio, dtype=np.float32).copy()
                for name, audio in self.project.stems.items()
            }
            self._fx_bus_returns = {}
            self._fx_audition_audio = {}
            self._fx_routing_metadata = {
                "_routing_signature": signature,
                "error": str(message),
                "fallback": "dry_source_stems",
            }
            self.fx_routing_editor.set_meter_report({})
            logger.error("FX routing render failed; dry source stems retained:\n%s", message)
            if hasattr(self, "fx_render_state"):
                self.fx_render_state.setText("FX FAILED · DRY FALLBACK")
                self.fx_render_state.setToolTip(str(message))
                self.fx_render_state.setStyleSheet("color: #ff7777;")
            if hasattr(self, "retry_fx_button"):
                self.retry_fx_button.setEnabled(True)
            self.statusBar().showMessage(
                "FX render failed. Playback is using DRY stems, not processed audio. "
                "Full traceback is printed in the terminal. Use PRE-RENDER FX to retry.",
                20000,
            )
        self._fx_queued_signature = None
        self._refresh_preview()

    def _audition_fx_component(self, stage: str, stem: str) -> None:
        """Audition direct/insert/send/return/master stages from the cached routing pass."""
        if self.project is None:
            return
        if not self._ensure_routing_render():
            self.statusBar().showMessage("FX audition will be available when routing finishes.", 5000)
            return
        audio = None
        if stage == "master":
            audio = self._render_mix()
        elif stage == "return.space":
            audio = self._fx_bus_returns.get("space")
        elif stage == "return.echo":
            audio = self._fx_bus_returns.get("echo")
        elif stage == "direct":
            audio = self._fx_audition_audio.get("direct", {}).get(stem)
            if audio is None and stem in self.project.stems:
                audio = self.project.stems[stem]
        elif stage == "insert":
            audio = self._fx_audition_audio.get("insert", {}).get(stem)
        elif stage.startswith("send."):
            bus = stage.split(".", 1)[1]
            audio = self._fx_audition_audio.get("sends", {}).get(stem, {}).get(bus)
        if audio is None or not len(audio):
            self.statusBar().showMessage("This route has no rendered contribution to audition.", 5000)
            return
        audition_audio = np.asarray(audio, dtype=np.float32)
        match_report = None
        if self.fx_routing_editor.match_audition_level():
            audition_audio, match_report = match_audition_level(
                audition_audio, target_rms_dbfs=-18.0, peak_ceiling=0.95
            )
        try:
            self.player.stop()
            self.player.start(
                audition_audio,
                self.project.sample_rate,
                device=self.output_device.currentData(),
            )
            self.play_button.setText("PAUSE")
            self.preview_source.setCurrentIndex(0)
            suffix = (
                f" · matched {match_report['output_rms_dbfs']:.1f} dBFS RMS"
                if match_report is not None else ""
            )
            self.statusBar().showMessage(
                f"Auditioning {stage.upper()} · {stem}{suffix}", 5000
            )
        except Exception as exc:
            self._show_error(f"FX audition failed: {exc}")

    def _processed_stem(self, name: str) -> np.ndarray:
        assert self.project is not None
        if not self._ensure_routing_render():
            audio = self.project.stems[name]
        else:
            audio = self._fx_processed_stems.get(name, self.project.stems[name])
        row = self._mix_rows.get(name)
        if row is None:
            return audio
        solo_active = any(item.solo.isChecked() for item in self._mix_rows.values())
        if row.mute.isChecked() or (solo_active and not row.solo.isChecked()):
            return np.zeros_like(audio)
        result = audio.copy() * (row.gain.value() / 100.0)
        pan = row.pan.value() / 100.0
        if pan < 0:
            result[:, 1] *= float(np.cos(abs(pan) * np.pi / 2.0))
        elif pan > 0:
            result[:, 0] *= float(np.cos(pan * np.pi / 2.0))
        return result

    def _refresh_routing(self) -> None:
        """Invalidate all processed snapshots when routing controls change."""
        self._fx_routing_metadata = {}
        if hasattr(self, "fx_render_state"):
            self.fx_render_state.setText("FX NOT RENDERED")
            self.fx_render_state.setToolTip("")
            self.fx_render_state.setStyleSheet("")
        if hasattr(self, "retry_fx_button"):
            self.retry_fx_button.setEnabled(True)
        if self._fx_variation_worker is not None:
            self._fx_variation_worker.cancel()
            self._fx_variation_signature = None
            self.fx_routing_editor.set_variation_choices([])
        else:
            self._clear_fx_variation_cache()
        self._refresh_preview()

    def _render_mix(self) -> np.ndarray | None:
        if self.project is None:
            return None
        if not self._ensure_routing_render():
            return None
        mixed = {name: self._processed_stem(name) for name in self.project.stems}
        routing = self.fx_routing_editor.routing()
        active_sends = self._fx_routing_metadata.get("active_send_stems_by_bus", {})
        solo_active = any(row.solo.isChecked() for row in self._mix_rows.values())
        audible = {
            name for name, row in self._mix_rows.items()
            if not row.mute.isChecked() and (not solo_active or row.solo.isChecked())
        }
        audible_returns = {
            bus: audio for bus, audio in self._fx_bus_returns.items()
            if set(active_sends.get(bus, ())).intersection(audible)
        }
        master = render_master_with_returns(
            mixed, audible_returns, master_wet=float(routing["master_wet"]),
        )
        meters = self._fx_routing_metadata.setdefault("meters", {})
        meters["master"] = measure_signal(master, sample_rate=self.project.sample_rate)
        self.fx_routing_editor.set_meter_report(meters)
        return master

    def _current_preview_audio(self) -> np.ndarray | None:
        if self.project is None:
            return None
        selection = self.preview_source.currentData()
        # A failed FX pass intentionally leaves a labelled dry fallback. Keep
        # that audio playable rather than making the transport appear broken.
        if self._fx_routing_metadata.get("fallback") == "dry_source_stems":
            if selection == "master":
                dry = {
                    name: self._processed_stem(name)
                    for name in self.project.stems
                }
                return render_master_with_returns(
                    dry, {}, master_wet=float(self.fx_routing_editor.routing()["master_wet"])
                )
            if selection in self.project.stems:
                return self._processed_stem(selection)
            return None
        if not self._ensure_routing_render():
            return None
        if selection == "master":
            return self._render_mix()
        if selection in self.project.stems:
            return self._processed_stem(selection)
        return None

    def _refresh_preview(self, *_args: Any) -> None:
        """Schedule a preview refresh and sync portable fader state."""
        if self.project is not None and hasattr(self, "fx_routing_editor"):
            states = {
                name: {
                    "gain_db": 20.0 * float(
                        np.log10(max(row.gain.value() / 100.0, 0.001))
                    ),
                    "pan": row.pan.value() / 100.0,
                    "mute": row.mute.isChecked(),
                    "solo": row.solo.isChecked(),
                }
                for name, row in self._mix_rows.items()
            }
            self.fx_routing_editor.set_mixer_state(states)
        self._preview_refresh_timer.start()

    def _apply_preview_refresh(self) -> None:
        audio = self._current_preview_audio()
        if audio is None and self.project is not None and self._fx_worker is not None:
            self.statusBar().showMessage("FX routing is rendering; current playback is retained.", 3000)
            return
        self.preview.set_audio(audio, self.project.sample_rate if self.project else 48_000)
        if self.player.is_playing:
            if audio is None or not self.player.replace_audio(audio):
                self.player.stop()
                self._playback_stopped()

    def _refresh_devices(self) -> None:
        self.output_device.clear()
        self.output_device.addItem("System default", None)
        for index, name in self.player.devices():
            self.output_device.addItem(name, index)
        if not self.player.available:
            self.output_device.setToolTip(
                "SoundDevice/PortAudio is unavailable. Reinstall the [m4] extra "
                "and verify that the system audio runtime is present."
            )

    def _toggle_playback(self) -> None:
        if self.player.is_playing:
            if self.player.is_paused:
                self.player.resume()
                self.play_button.setText("PAUSE")
            else:
                self.player.pause()
                self.play_button.setText("RESUME")
            return
        audio = self._current_preview_audio()
        if audio is None or self.project is None:
            self.statusBar().showMessage(
                "Generate a loop or wait for the role-aware FX render before auditioning."
            )
            return
        try:
            self.player.start(
                audio, self.project.sample_rate, device=self.output_device.currentData()
            )
            self.play_button.setText("PAUSE")
        except Exception as exc:
            self._show_error(str(exc))

    def _playback_finished(self) -> None:
        self.play_button.setText("PLAY")
        if self.player.duration_frames > 0:
            sample_rate = self.project.sample_rate if self.project else 48_000
            duration = self.player.duration_frames / float(sample_rate)
            self.transport_position.setText(
                f"{duration // 60:02.0f}:{duration % 60:04.1f} / "
                f"{duration // 60:02.0f}:{duration % 60:04.1f}"
            )

    def _playback_stopped(self) -> None:
        self.play_button.setText("PLAY")
        self.transport_position.setText("00:00.0 / 00:00.0")

    def _update_transport(self) -> None:
        if not self.player.is_playing or self.player.duration_frames <= 0:
            return
        sample_rate = self.project.sample_rate if self.project else 48_000
        position = self.player.position_frames / float(sample_rate)
        duration = self.player.duration_frames / float(sample_rate)
        self.transport_position.setText(
            f"{position // 60:02.0f}:{position % 60:04.1f} / "
            f"{duration // 60:02.0f}:{duration % 60:04.1f}"
        )

    def _export_project(self) -> None:
        """Choose a parent folder and automatically render FX before delivery export."""
        if (
            self.project is None
            or self._export_worker is not None
            or self._pending_export_destination is not None
        ):
            return
        export_parent = QFileDialog.getExistingDirectory(
            self,
            "Choose a folder for the Reawarp delivery export",
            str(Path.cwd() / "output"),
        )
        if not export_parent:
            return

        score_title = str(self.project.to_score().title or "Reawarp")
        slug = "".join(
            character if character.isascii() and (
                character.isalnum() or character in "-_"
            ) else "-"
            for character in score_title
        ).strip("-_") or "Reawarp"
        destination = Path(export_parent) / f"{slug}_Reawarp_Export"
        suffix = 2
        while destination.exists():
            destination = Path(export_parent) / f"{slug}_Reawarp_Export_{suffix:02d}"
            suffix += 1

        self._pending_export_destination = destination
        self.export_button.setEnabled(False)
        if self._ensure_routing_render():
            self._pending_export_destination = None
            self._start_delivery_export(destination)
        else:
            self.statusBar().showMessage(
                "Delivery export queued. Reawarp will finish the current FX render "
                "and automatically write README, master, stems and MIDI.",
                12000,
            )

    def _start_delivery_export(self, destination: Path) -> None:
        """Snapshot the final routed master and launch the folder writer."""
        if self.project is None or self._export_worker is not None:
            self._pending_export_destination = destination
            return
        master = self._render_mix()
        if master is None:
            self._pending_export_destination = destination
            if not self._ensure_routing_render():
                self.statusBar().showMessage(
                    "Waiting for the current FX render before creating the delivery folder.",
                    10000,
                )
                return
            master = self._render_mix()
            if master is None:
                self._pending_export_destination = None
                self.export_button.setEnabled(self.project is not None)
                self.statusBar().showMessage(
                    "Could not produce a master render; delivery export was not created.",
                    10000,
                )
                return

        export_project = self._project_with_variation_session()
        master_snapshot = np.asarray(master, dtype=np.float32).copy()
        fx_status = (
            "dry_fallback"
            if self._fx_routing_metadata.get("fallback") == "dry_source_stems"
            else "rendered"
        )

        def operation(cancel_event):
            output = export_project_package(
                export_project,
                destination,
                master_audio=master_snapshot,
                bit_depth=24,
                include_midi=True,
                fx_render_status=fx_status,
                cancel_event=cancel_event,
            )
            return str(output)

        self._pending_export_destination = None
        self.export_button.setEnabled(False)
        self.cancel_background_button.setVisible(True)
        self.cancel_background_button.setEnabled(True)
        self.statusBar().showMessage(
            "Writing delivery folder: README.md, master.wav, dry stems and combined/per-voice MIDI…",
            10000,
        )
        worker = CancellableRenderWorker(operation)
        self._export_worker = worker
        worker.signals.finished.connect(self._export_finished)
        worker.signals.error.connect(self._export_failed)
        QThreadPool.globalInstance().start(worker)

    def _export_finished(self, result: object) -> None:
        self._export_worker = None
        self.export_button.setEnabled(self.project is not None)
        if self._worker is None:
            self.cancel_background_button.setEnabled(False)
            self.cancel_background_button.setVisible(False)
        self.statusBar().showMessage(f"Exported Reawarp delivery folder to {result}", 10000)

    def _export_failed(self, message: str) -> None:
        self._export_worker = None
        self.export_button.setEnabled(self.project is not None)
        if self._worker is None:
            self.cancel_background_button.setEnabled(False)
            self.cancel_background_button.setVisible(False)
        if str(message).startswith("CANCELLED:"):
            self.statusBar().showMessage("Delivery export cancelled.", 8000)
            return
        self._show_error(f"Export failed: {message}")
