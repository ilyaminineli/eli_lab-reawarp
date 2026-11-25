"""M4 desktop instrument: generation, break lab, playback, and stem mixing."""

from __future__ import annotations

import json
import secrets
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
from reawarp.export.wav import write_wav
from reawarp.fx_routing import (
    match_audition_level, measure_signal, render_fx_routing,
    render_master_with_returns, save_fx_routing,
)
from reawarp.fx_automation import (
    attach_fx_automation_to_score, fx_automation_registry, save_fx_automation,
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
from reawarp.ui.navigation import WorkspaceNavigator
from reawarp.ui.theme import APP_STYLE
from reawarp.ui.widgets.audio_preview import AudioPreview
from reawarp.ui.widgets.stem_row import StemRow
from reawarp.ui.workers import CancellableRenderWorker, RenderWorker


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
        self._worker: RenderWorker | None = None
        self._variation_counts: dict[str, int] = {}
        self._mix_rows: dict[str, StemRow] = {}
        self._fx_processed_stems: dict[str, np.ndarray] = {}
        self._fx_bus_returns: dict[str, np.ndarray] = {}
        self._fx_routing_metadata: dict[str, Any] = {}
        self._fx_audition_audio: dict[str, Any] = {}
        self._fx_worker: CancellableRenderWorker | None = None
        self._fx_pending_signature: str | None = None
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
        self.library_page = LibraryPage(self)
        self.library_page.sampleSelected.connect(self._accept_library_sample)

        self.workspace_stack = QStackedWidget()
        # Keep the historical attribute as a small compatibility bridge for
        # code/tests that query the number of workspace pages.
        self.tabs = self.workspace_stack
        for workspace in (
            generator_page, break_page, mixer_page, self.fx_lab_page, self.library_page
        ):
            self.workspace_stack.addWidget(workspace)

        self._workspace_info = [
            ("GENERATOR", "Define form, rhythm, synthesis and source material."),
            ("BREAK LAB", "Analyse, transform and reuse break material in the composition."),
            ("STEM MIXER", "Shape the relationships between generated musical roles."),
            ("FX LAB", "Build reusable non-destructive processing chains and compare results."),
            ("LIBRARY", "Find, organise and reuse the sounds and variations in your Reawarp ecosystem."),
        ]
        self.navigator = WorkspaceNavigator(
            [
                ("COMPOSE", [
                    ("Generator", "Create the composition plan and its coordinated sound sources.", 0),
                    ("Break Lab", "Transform source breaks for use by the composition engine.", 1),
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
        self.transport_bar.setVisible(index in (0, 2))

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
        pool = QThreadPool.globalInstance()
        pool.clear()
        pool.waitForDone(-1)
        self._worker = None

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
        self.export_button = QPushButton("EXPORT STEMS + MASTER…")
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

    def _generate(self) -> None:
        try:
            config = self._read_config()
        except Exception as exc:
            self._show_error(str(exc))
            return
        self._run_render(lambda: ReawarpEngine().generate(config), "Generating full loop…")

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
            lambda: self._render_score_automation_project(base_project, edited_score),
            "Applying score automation and re-rendering event-backed voices…",
        )

    @staticmethod
    def _render_score_automation_project(
        project: ReawarpProject,
        score,
    ) -> ReawarpProject:
        """Render a controlled Score and retain the specialist whole-field layers."""
        rendered = ReawarpEngine().render_score(score, config=project.config)
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

    def _regenerate_stem(self, name: str) -> None:
        if self.project is None:
            return
        variation = self._variation_counts.get(name, 0) + 1
        self._variation_counts[name] = variation
        config = self.project.config
        base_project = self.project
        self._run_render(
            lambda: ReawarpEngine().generate_variant(
                config, name, variation, base_project=base_project
            ),
            f"Regenerating {name} · variation {variation}…",
        )

    def _run_render(self, operation: Any, message: str) -> None:
        if self._worker is not None:
            return
        self._set_busy(True, message)
        worker = RenderWorker(operation)
        self._worker = worker
        worker.signals.finished.connect(self._render_finished)
        worker.signals.error.connect(self._render_failed)
        QThreadPool.globalInstance().start(worker)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.generate_button.setEnabled(not busy)
        self.progress.setVisible(busy)
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
        self.player.stop()
        self._playback_stopped()
        self.project = result
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
        self.fx_routing_editor.set_meter_report({})
        self._rebuild_mixer()
        self.mixer_stack.setCurrentIndex(1)
        self._update_project_context()
        self.preview_source.setEnabled(True)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.fx_routing_editor.set_stems(list(result.stems), result.sample_rate, result.config.bpm)
        self.fx_automation_editor.set_project(list(result.stems), result.config.bpm)
        if previous_routing is not None and previous_names == tuple(result.stems):
            self.fx_routing_editor.set_routing(previous_routing)
        if previous_automation is not None and previous_names == tuple(result.stems):
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
        self._show_error(message)

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

        dry_stems = {
            name: np.asarray(audio, dtype=np.float32).copy()
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
            self.statusBar().showMessage(
                "Role-aware inserts and SPACE/ECHO returns are ready.", 5000
            )
        queued = self._fx_queued_signature
        self._fx_queued_signature = None
        if queued is not None or signature != self._routing_signature():
            self._refresh_preview()
            return
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
            self.statusBar().showMessage(
                f"FX render failed; dry sources retained: {message}", 10000
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
        """Invalidate the offline FX cache only when routing controls change."""
        self._fx_routing_metadata = {}
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
        if not self._ensure_routing_render():
            return None
        selection = self.preview_source.currentData()
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
        if self.project is None:
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Export Reawarp project", str(Path.cwd())
        )
        if not directory:
            return
        if not self._ensure_routing_render():
            self.statusBar().showMessage(
                "FX routing is being rendered in the background. Export again when it is ready.",
                8000,
            )
            return
        try:
            output = self.project.export(
                directory, bit_depth=24, include_stems=True, include_master=True
            )
            master = self._render_mix()
            if master is None:
                self.statusBar().showMessage("FX master is not ready; export cancelled.", 8000)
                return
            if master is not None:
                write_wav(output / "master.wav", master, self.project.sample_rate, 24)
            self._ensure_routing_render()
            routing_path = save_fx_routing(
                output / "fx_routing.json", self.fx_routing_editor.routing(),
                list(self.project.stems), self.project.sample_rate,
            )
            automation_path = save_fx_automation(
                output / "fx_automation.json", self.fx_automation_editor.automation(),
                list(self.project.stems),
            )
            for bus, audio in self._fx_bus_returns.items():
                write_wav(output / "returns" / f"{bus}.wav", audio, self.project.sample_rate, 24)
            mix_data = {
                "schema_version": 1,
                "description": (
                    "Mixer settings are applied to master.wav; stem WAVs remain the original aligned render buffers."
                ),
                "stems": {name: row.state() for name, row in self._mix_rows.items()},
                "master_peak": (
                    float(np.max(np.abs(master))) if master is not None and master.size else 0.0
                ),
                "fx_routing": routing_path.name,
                "fx_automation": automation_path.name,
                "fx_returns": list(self._fx_bus_returns),
                "routing_render": self._fx_routing_metadata,
            }
            (output / "mix.json").write_text(
                json.dumps(mix_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            self._show_error(f"Export failed: {exc}")
            return
        self.statusBar().showMessage(
            f"Exported stems, master, and metadata to {output}", 10000
        )
