"""M31 graphical editor over the existing M21 sound-object model."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from reawarp.synthesis.sound_object import (
    LAYER_ROLES, SoundObjectLayer, SoundObjectPatch, sound_object_editor_model,
)
from reawarp.ui.widgets.audio_preview import AudioPreview


class SoundObjectEditorPage(QWidget):
    """Edit patch identity/layers, audition aligned layers, and print a new asset."""

    createRequested = Signal(str, str)
    refreshRequested = Signal()
    saveRequested = Signal(object)
    auditionRequested = Signal(object, str)
    printRequested = Signal(object, str, int, str)
    playRequested = Signal(object, int)
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._patches: dict[str, SoundObjectPatch] = {}
        self._patch: SoundObjectPatch | None = None
        self._loading = False
        self._preview_audio = None
        self._preview_rate = 48_000

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)
        title = QLabel("SOUND OBJECT WORKSHOP / SOURCE → MATERIAL → ROLE")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        intro = QLabel(
            "Import a linked source, edit frame-addressed transient/body/tail layers, "
            "audition each layer or the complete object, and print a new versioned WAV "
            "asset with source hashes and render lineage."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)

        toolbar = QHBoxLayout()
        self.patch_picker = QComboBox()
        self.patch_picker.currentIndexChanged.connect(self._patch_selected)
        self.new_button = QPushButton("IMPORT SOURCE")
        self.new_button.clicked.connect(self._import_source)
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        self.save_button = QPushButton("SAVE REVISION")
        self.save_button.clicked.connect(self._save_patch)
        toolbar.addWidget(QLabel("OBJECT"))
        toolbar.addWidget(self.patch_picker, 1)
        toolbar.addWidget(self.new_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.save_button)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("LAYERS / TRANSIENT • BODY • TAIL"))
        self.layer_picker = QListWidget()
        self.layer_picker.currentRowChanged.connect(self._layer_selected)
        left_layout.addWidget(self.layer_picker, 1)
        left.setMinimumWidth(210)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        identity = QGroupBox("OBJECT IDENTITY / SOURCE")
        identity_form = QFormLayout(identity)
        self.name = QLineEdit()
        self.processing_id = QLineEdit()
        self.processing_id.setReadOnly(True)
        self.sample_rate = QLabel("—")
        self.version = QLabel("No object selected")
        identity_form.addRow("Object name", self.name)
        identity_form.addRow("Processing identity", self.processing_id)
        identity_form.addRow("Sample rate", self.sample_rate)
        identity_form.addRow("Revision", self.version)
        right_layout.addWidget(identity)

        layer = QGroupBox("LAYER SHAPE / FRAME CLOCK")
        form = QFormLayout(layer)
        self.layer_role = QComboBox()
        for role in sorted(LAYER_ROLES):
            self.layer_role.addItem(role.upper(), role)
        form.addRow("Material region", self.layer_role)
        self.start_frame = QSpinBox()
        self.start_frame.setRange(0, 2_000_000_000)
        self.end_frame = QSpinBox()
        self.end_frame.setRange(1, 2_000_000_000)
        self.source_start = QSpinBox()
        self.source_start.setRange(0, 2_000_000_000)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0.0, 4.0)
        self.gain.setDecimals(4)
        self.gain.setSingleStep(0.05)
        self.pan = QDoubleSpinBox()
        self.pan.setRange(-1.0, 1.0)
        self.pan.setDecimals(3)
        self.pan.setSingleStep(0.05)
        self.attack = QDoubleSpinBox()
        self.decay = QDoubleSpinBox()
        self.release = QDoubleSpinBox()
        for control in (self.attack, self.decay, self.release):
            control.setRange(0.0, 30.0)
            control.setDecimals(4)
            control.setSuffix(" s")
            control.setSingleStep(0.01)
        self.sustain = QDoubleSpinBox()
        self.sustain.setRange(0.0, 1.0)
        self.sustain.setDecimals(3)
        form.addRow("Object start", self.start_frame)
        form.addRow("Object end", self.end_frame)
        form.addRow("Source offset", self.source_start)
        form.addRow("Gain / linear", self.gain)
        form.addRow("Pan / normalized", self.pan)
        form.addRow("Attack", self.attack)
        form.addRow("Decay", self.decay)
        form.addRow("Sustain", self.sustain)
        form.addRow("Release", self.release)
        right_layout.addWidget(layer)
        splitter.addWidget(right)
        splitter.setSizes([230, 530])
        root.addWidget(splitter, 2)

        audition = QGroupBox("ALIGNED AUDITION / PRINT")
        audition_layout = QVBoxLayout(audition)
        actions = QHBoxLayout()
        self.audition_layer_button = QPushButton("AUDITION SELECTED LAYER")
        self.audition_layer_button.clicked.connect(self._audition_layer)
        self.audition_object_button = QPushButton("AUDITION FULL OBJECT")
        self.audition_object_button.clicked.connect(self._audition_object)
        self.play_button = QPushButton("PLAY PREVIEW")
        self.play_button.clicked.connect(self._play_preview)
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        for button in (
            self.audition_layer_button, self.audition_object_button,
            self.play_button, self.cancel_button,
        ):
            actions.addWidget(button)
        audition_layout.addLayout(actions)

        print_row = QHBoxLayout()
        self.output_rate = QComboBox()
        for rate in (22_050, 44_100, 48_000, 88_200, 96_000):
            self.output_rate.addItem(f"{rate:,} Hz", rate)
        self.target_role = QComboBox()
        for role in (
            "texture", "kick", "snare", "hat", "percussion",
            "bass", "lead", "melody", "ambience", "fx",
        ):
            self.target_role.addItem(role.upper(), role)
        self.print_button = QPushButton("PRINT TO NEW WAV ASSET…")
        self.print_button.clicked.connect(self._print_object)
        print_row.addWidget(QLabel("Output rate"))
        print_row.addWidget(self.output_rate)
        print_row.addWidget(QLabel("Role"))
        print_row.addWidget(self.target_role)
        print_row.addWidget(self.print_button)
        audition_layout.addLayout(print_row)

        self.preview = AudioPreview()
        self.preview.setMinimumHeight(180)
        audition_layout.addWidget(self.preview, 1)
        self.status = QLabel("Import a source or select a saved sound object.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        audition_layout.addWidget(self.status)
        root.addWidget(audition, 2)
        self.set_busy(False)

    def set_patches(self, patches: list[SoundObjectPatch] | tuple[SoundObjectPatch, ...]) -> None:
        selected = self._patch.patch_id if self._patch is not None else None
        self._patches = {item.patch_id: item for item in patches}
        self._loading = True
        self.patch_picker.clear()
        for patch_id, patch in sorted(self._patches.items(), key=lambda pair: pair[1].name.casefold()):
            self.patch_picker.addItem(patch.name, patch_id)
        index = self.patch_picker.findData(selected) if selected else -1
        if index < 0 and self.patch_picker.count():
            index = 0
        self.patch_picker.setCurrentIndex(index)
        self._loading = False
        self._patch_selected(index)

    def select_patch(self, patch_id: str) -> None:
        index = self.patch_picker.findData(str(patch_id))
        if index >= 0:
            self.patch_picker.setCurrentIndex(index)

    def _patch_selected(self, index: int) -> None:
        if self._loading or index < 0:
            self._patch = None
            return
        patch_id = self.patch_picker.itemData(index)
        self._patch = self._patches.get(str(patch_id))
        self._loading = True
        self.layer_picker.clear()
        if self._patch is not None:
            model = sound_object_editor_model(self._patch)
            identity = model["identity"]
            self.name.setText(identity["name"])
            self.processing_id.setText(identity["processing_identity_id"])
            self.sample_rate.setText(f'{model["clock"]["sample_rate_hz"]:,} Hz')
            self.version.setText(f'{identity["patch_id"]} · schema {model["schema_version"]}')
            for item in self._patch.layers:
                row = QListWidgetItem(f"{item.role.upper()}  /  {item.layer_id}")
                row.setData(Qt.ItemDataRole.UserRole, item.layer_id)
                self.layer_picker.addItem(row)
            self.layer_picker.setCurrentRow(0 if self._patch.layers else -1)
            self.status.setText(
                f"{len(self._patch.sources)} source(s) · {len(self._patch.layers)} layer(s) · "
                f"{len(self._patch.transformations)} recorded transformation(s)"
            )
        self._loading = False
        if self._patch is not None and self._patch.layers:
            self._load_layer(self._patch.layers[0])

    def _layer_selected(self, index: int) -> None:
        if self._loading or self._patch is None or index < 0:
            return
        layer_id = self.layer_picker.item(index).data(Qt.ItemDataRole.UserRole)
        item = next((value for value in self._patch.layers if value.layer_id == layer_id), None)
        if item is not None:
            self._load_layer(item)

    def _load_layer(self, item: SoundObjectLayer) -> None:
        self._loading = True
        self.layer_role.setCurrentIndex(max(0, self.layer_role.findData(item.role)))
        self.start_frame.setValue(item.start_frame)
        self.end_frame.setValue(item.end_frame)
        self.source_start.setValue(item.source_start_frame)
        self.gain.setValue(item.gain)
        self.pan.setValue(item.pan)
        self.attack.setValue(item.envelope.attack_seconds)
        self.decay.setValue(item.envelope.decay_seconds)
        self.sustain.setValue(item.envelope.sustain_level)
        self.release.setValue(item.envelope.release_seconds)
        self._loading = False

    def edited_patch(self) -> SoundObjectPatch:
        if self._patch is None:
            raise ValueError("select or import a sound object first")
        layers = list(self._patch.layers)
        row = self.layer_picker.currentRow()
        if row >= 0:
            item = layers[row]
            envelope = replace(
                item.envelope, attack_seconds=self.attack.value(),
                decay_seconds=self.decay.value(), sustain_level=self.sustain.value(),
                release_seconds=self.release.value(),
            )
            layers[row] = replace(
                item, role=str(self.layer_role.currentData()),
                start_frame=self.start_frame.value(), end_frame=self.end_frame.value(),
                source_start_frame=self.source_start.value(), gain=self.gain.value(),
                pan=self.pan.value(), envelope=envelope,
            )
        return replace(
            self._patch,
            name=self.name.text().strip() or self._patch.name,
            layers=tuple(layers),
        )

    def _save_patch(self) -> None:
        try:
            self.saveRequested.emit(self.edited_patch())
        except Exception as exc:
            self.set_status(f"Cannot save sound object: {exc}")

    def _audition_layer(self) -> None:
        try:
            patch = self.edited_patch()
            row = self.layer_picker.currentRow()
            if row < 0:
                raise ValueError("select a layer to audition")
            self.auditionRequested.emit(patch, patch.layers[row].layer_id)
        except Exception as exc:
            self.set_status(f"Cannot audition layer: {exc}")

    def _audition_object(self) -> None:
        try:
            self.auditionRequested.emit(self.edited_patch(), "")
        except Exception as exc:
            self.set_status(f"Cannot audition object: {exc}")

    def _import_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import sound-object source", "",
            "Audio files (*.wav *.flac *.aiff *.aif *.ogg)",
        )
        if path:
            self.createRequested.emit(path, Path(path).stem)

    def _print_object(self) -> None:
        try:
            patch = self.edited_patch()
            filename = patch.name.replace(" ", "_") + "_print.wav"
            path, _ = QFileDialog.getSaveFileName(
                self, "Print sound object to a new asset", filename, "WAV audio (*.wav)"
            )
            if path:
                if not path.casefold().endswith(".wav"):
                    path += ".wav"
                self.printRequested.emit(
                    patch, path, int(self.output_rate.currentData()),
                    str(self.target_role.currentData()),
                )
        except Exception as exc:
            self.set_status(f"Cannot prepare sound-object print: {exc}")

    def set_preview(self, audio: Any, sample_rate: int, *, label: str = "Rendered preview") -> None:
        import numpy as np

        self._preview_audio = np.asarray(audio, dtype=np.float32).copy()
        self._preview_rate = int(sample_rate)
        self.preview.set_audio(self._preview_audio, self._preview_rate)
        self.set_status(
            f"{label} · {len(self._preview_audio):,} frames · {self._preview_rate:,} Hz"
        )

    def _play_preview(self) -> None:
        if self._preview_audio is None:
            self.set_status("Render a layer or full object before playback.")
            return
        self.playRequested.emit(self._preview_audio.copy(), self._preview_rate)

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.new_button, self.refresh_button, self.save_button,
            self.audition_layer_button, self.audition_object_button, self.print_button,
        ):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def set_status(self, message: str) -> None:
        self.status.setText(str(message))
