"""M4 desktop instrument: generation, break lab, playback, and stem mixing."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer, QThreadPool, QEvent
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject
from reawarp.composition.director import STRUCTURES
from reawarp.composition.patterns import PATTERN_FAMILIES, PATTERN_RELATIONSHIPS
from reawarp.export.wav import write_wav
from reawarp.fx_routing import render_fx_routing, render_master_with_returns, save_fx_routing
from reawarp.samples.io import read_sample
from reawarp.synthesis.profiles import (
    HAT_PROFILES, KICK_PROFILES, MELODY_PROFILES, SNARE_PROFILES,
    SUBTRACTIVE_VOICES,
)
from reawarp.transforms import BREAK_TRANSFORMS, auto_slice
from reawarp.ui.audio_player import AudioPlayer
from reawarp.ui.pages.fx_lab import FxLabPage
from reawarp.ui.pages.fx_routing import FXRoutingEditor
from reawarp.ui.pages.library import LibraryPage
from reawarp.ui.theme import APP_STYLE
from reawarp.ui.widgets.audio_preview import AudioPreview
from reawarp.ui.widgets.stem_row import StemRow
from reawarp.ui.workers import RenderWorker


class MainWindow(QMainWindow):
    """First production-oriented Reawarp desktop application."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reawarp — 再変形")
        self.resize(1440, 920)
        self.setMinimumSize(1080, 700)
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

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)
        brand = QLabel("再変形")
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        subtitle = QLabel("REAWARP  /  MATHEMATICAL AUDIO LAB")
        subtitle.setObjectName("muted")
        header_layout.addWidget(subtitle)
        header_layout.addStretch(1)
        self.header_state = QLabel("OFFLINE RENDER ENGINE")
        self.header_state.setObjectName("sectionTitle")
        header_layout.addWidget(self.header_state)
        root_layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_generator_page(), "GENERATOR")
        self.tabs.addTab(self._build_break_page(), "BREAK LAB")
        self.tabs.addTab(self._build_mixer_page(), "STEM MIXER")
        self.fx_lab_page = FxLabPage(self.player, self)
        self.tabs.addTab(self.fx_lab_page, "FX LAB")
        self.library_page = LibraryPage(self)
        self.tabs.addTab(self.library_page, "LIBRARY")
        root_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready — define constraints, generate, listen, and select.")

    def _build_generator_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        panel = QWidget()
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(410)
        panel_layout = QVBoxLayout(panel)
        control_tabs = QTabWidget()
        form_page, voices_page, rhythm_page = QWidget(), QWidget(), QWidget()
        form_layout = QVBoxLayout(form_page)
        voices_layout = QVBoxLayout(voices_page)
        rhythm_layout = QVBoxLayout(rhythm_page)

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
        self.pattern_follow_structure = QCheckBox("Auto-switch patterns at formal sections")
        self.pattern_follow_structure.setChecked(False)
        self.pattern_follow_structure.setToolTip(
            "When enabled, change the break pattern family at formal section boundaries. "
            "Off preserves the existing break phrase grammar."
        )
        form.addRow("Pattern development", self.pattern_follow_structure)
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
        profile_form.addRow("Percussion synthesis", self.percussion_synthesis)
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

        form_layout.addStretch(1)
        voices_layout.addStretch(1)
        rhythm_layout.addStretch(1)
        control_tabs.addTab(form_page, "FORM")
        control_tabs.addTab(voices_page, "VOICES")
        control_tabs.addTab(rhythm_page, "RHYTHM")
        panel_layout.addWidget(control_tabs, 1)

        self.generate_button = QPushButton("GENERATE COMPOSITION")
        self.generate_button.setObjectName("primaryAction")
        self.generate_button.clicked.connect(self._generate)
        panel_layout.addWidget(self.generate_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        panel_layout.addWidget(self.progress)
        panel_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        layout.addWidget(scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._build_transport_bar())
        self.preview = AudioPreview()
        right_layout.addWidget(self.preview, 1)
        self.render_summary = QLabel(
            "WAITING FOR RENDER  /  48 kHz · FLOAT32 · STEREO\n"
            "Waveform and time-frequency preview appear here after generation."
        )
        self.render_summary.setObjectName("muted")
        self.render_summary.setWordWrap(True)
        right_layout.addWidget(self.render_summary)
        layout.addWidget(right, 1)
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
        layout.addWidget(self.preview_source)
        layout.addWidget(QLabel("OUTPUT"))
        self.output_device = QComboBox()
        self.output_device.setMinimumWidth(180)
        layout.addWidget(self.output_device)
        self.play_button = QPushButton("PLAY")
        self.play_button.clicked.connect(self._toggle_playback)
        layout.addWidget(self.play_button)
        stop = QPushButton("STOP")
        stop.clicked.connect(self.player.stop)
        stop.clicked.connect(self._playback_stopped)
        layout.addWidget(stop)
        self.transport_position = QLabel("00:00.0 / 00:00.0")
        self.transport_position.setObjectName("muted")
        layout.addWidget(self.transport_position)
        layout.addStretch(1)
        return bar

    def _build_break_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        controls = QWidget()
        controls.setMinimumWidth(310)
        controls.setMaximumWidth(380)
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
        scroll.setWidget(controls)
        layout.addWidget(scroll)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        self.break_preview = AudioPreview()
        preview_layout.addWidget(self.break_preview, 1)
        self.break_analysis_summary = QLabel(
            "Transient markers appear in amber. Preview is non-destructive; source files are never rewritten."
        )
        self.break_analysis_summary.setObjectName("muted")
        self.break_analysis_summary.setWordWrap(True)
        preview_layout.addWidget(self.break_analysis_summary)
        layout.addWidget(preview_panel, 1)
        return page

    def _build_mixer_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
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

        self.mixer_scroll = QScrollArea()
        self.mixer_scroll.setWidgetResizable(True)
        self.mixer_content = QWidget()
        self.mixer_rows_layout = QVBoxLayout(self.mixer_content)
        self.mixer_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.mixer_rows_layout.setSpacing(6)
        self.mixer_scroll.setWidget(self.mixer_content)
        layout.addWidget(self.mixer_scroll, 1)

        note = QLabel(
            "Gain and pan affect audition and the exported master. Stem WAVs remain the original aligned render buffers. "
            "Regeneration uses independent deterministic streams."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        return page

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
        return GenerationConfig(
            bpm=self.bpm.value(),
            duration=self.duration.value(),
            structure=self.structure.currentText(),
            composition_flow=self.composition_flow.currentText(),
            pattern_family=self.pattern_family.currentText(),
            pattern_relationship=self.pattern_relationship.currentText(),
            pattern_follow_structure=self.pattern_follow_structure.isChecked(),
            synth_palette=self.synth_palette.currentText(),
            percussion_synthesis=self.percussion_synthesis.currentText(),
            composition_energy=self.composition_energy.value(),
            composition_variation=self.composition_variation.value(),
            sample_rate=48_000,
            seed=seed,
            complexity=self.complexity.value() / 100.0,
            include_melody=self.melody_enabled.isChecked(),
            include_texture=self.texture_enabled.isChecked(),
            include_ambience=self.ambience_enabled.isChecked(),
            ambience_level=self.ambience_level.value(),
            sample_paths={"break": self._break_path} if self._break_path else {},
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
        self.player.stop()
        self._playback_stopped()
        self.project = result
        self._fx_processed_stems = {}
        self._fx_bus_returns = {}
        self._fx_routing_metadata = {}
        self._rebuild_mixer()
        self.fx_routing_editor.set_stems(list(result.stems), result.sample_rate)
        self.preview_source.blockSignals(True)
        self.preview_source.clear()
        self.preview_source.addItem("MASTER MIX", "master")
        for name in result.stems:
            self.preview_source.addItem(name.replace("_", " ").upper(), name)
        self.preview_source.blockSignals(False)
        self.preview_source.setCurrentIndex(0)
        self.export_button.setEnabled(True)
        self._refresh_preview()
        self.render_summary.setText(
            f"{result.duration:.2f} s · {result.sample_rate:,} Hz · "
            f"{len(result.stems)} stems · {len(result.events)} events · "
            f"seed {result.config.seed} · algorithm {result.metadata.get('algorithm_version', '?')}"
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
            "noise_texture", "ambience", "sample_kick", "sample_snare",
            "sample_hat", "sample_break",
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
        self.fx_routing_editor = FXRoutingEditor()
        self.fx_routing_editor.changed.connect(self._refresh_preview)
        layout.addWidget(self.fx_routing_editor)

    def _select_stem(self, name: str) -> None:
        index = self.preview_source.findData(name)
        if index >= 0:
            self.preview_source.setCurrentIndex(index)
        self.tabs.setCurrentIndex(0)

    def _routing_signature(self) -> str:
        import hashlib
        payload = json.dumps(self.fx_routing_editor.routing(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _ensure_routing_render(self) -> None:
        if self.project is None:
            return
        signature = self._routing_signature()
        if self._fx_routing_metadata.get("_routing_signature") == signature:
            return
        processed, metadata = render_fx_routing(
            self.project.stems, self.project.sample_rate, self.fx_routing_editor.routing()
        )
        self._fx_bus_returns = metadata.pop("bus_returns_audio", {})
        self._fx_processed_stems = processed
        metadata["_routing_signature"] = signature
        self._fx_routing_metadata = metadata

    def _processed_stem(self, name: str) -> np.ndarray:
        assert self.project is not None
        self._ensure_routing_render()
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

    def _render_mix(self) -> np.ndarray | None:
        if self.project is None:
            return None
        self._ensure_routing_render()
        mixed = {name: self._processed_stem(name) for name in self.project.stems}
        routing = self.fx_routing_editor.routing()
        return render_master_with_returns(
            mixed, self._fx_bus_returns, frames=self.project.frame_count,
            master_wet=float(routing["master_wet"]),
        )

    def _current_preview_audio(self) -> np.ndarray | None:
        if self.project is None:
            return None
        selection = self.preview_source.currentData()
        if selection == "master":
            return self._render_mix()
        if selection in self.project.stems:
            return self._processed_stem(selection)
        return None

    def _refresh_preview(self, *_args: Any) -> None:
        """Schedule a preview refresh after rapid control changes settle."""
        self._preview_refresh_timer.start()

    def _apply_preview_refresh(self) -> None:
        audio = self._current_preview_audio()
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
            self.statusBar().showMessage("Generate a loop before auditioning audio.")
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
        try:
            output = self.project.export(
                directory, bit_depth=24, include_stems=True, include_master=True
            )
            master = self._render_mix()
            if master is not None:
                write_wav(output / "master.wav", master, self.project.sample_rate, 24)
            self._ensure_routing_render()
            routing_path = save_fx_routing(
                output / "fx_routing.json", self.fx_routing_editor.routing(),
                list(self.project.stems), self.project.sample_rate,
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
