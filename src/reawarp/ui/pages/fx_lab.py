"""Offline FX Lab workspace backed by the optional Pyo DSP engine."""

from __future__ import annotations

from pathlib import Path
import numpy as np
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from reawarp.export.wav import write_wav
from reawarp.fx import FX_PRESET_DESCRIPTIONS, FX_PRESETS, render_pyo_fx
from reawarp.ui.audio_player import AudioPlayer
from reawarp.ui.widgets.audio_preview import AudioPreview
from reawarp.ui.workers import RenderWorker


def _playable(audio: np.ndarray) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 2 and samples.shape[1] == 1:
        return samples[:, 0]
    return samples


class FxLabPage(QWidget):
    """Load a source, render a non-destructive FX pass, compare, and export."""

    def __init__(self, player: AudioPlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player = player
        self.source_audio: np.ndarray | None = None
        self.processed_audio: np.ndarray | None = None
        self.sample_rate = 48_000
        self.source_path: Path | None = None
        self._worker: RenderWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("FX LAB / OFFLINE SOUND DESIGN")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        source_group = QGroupBox("SOURCE / NON-DESTRUCTIVE INPUT")
        source_layout = QHBoxLayout(source_group)
        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setPlaceholderText("Choose a mono or stereo audio file…")
        source_layout.addWidget(self.path_field, 1)
        browse_button = QPushButton("BROWSE…")
        browse_button.clicked.connect(self._browse)
        source_layout.addWidget(browse_button)
        layout.addWidget(source_group)

        controls_group = QGroupBox("PROCESSING CHAIN")
        controls = QFormLayout(controls_group)
        self.preset = QComboBox()
        for name in FX_PRESETS:
            self.preset.addItem(name.replace("_", " ").upper(), name)
        self.preset.currentIndexChanged.connect(self._update_description)
        controls.addRow("Chain architecture", self.preset)

        self.description = QLabel()
        self.description.setObjectName("muted")
        self.description.setWordWrap(True)
        controls.addRow("Intent", self.description)

        wet_row = QHBoxLayout()
        self.wet = QSlider(Qt.Orientation.Horizontal)
        self.wet.setRange(0, 100)
        self.wet.setValue(75)
        self.wet_label = QLabel("0.75")
        self.wet_label.setMinimumWidth(42)
        wet_row.addWidget(self.wet, 1)
        wet_row.addWidget(self.wet_label)
        self.wet.valueChanged.connect(
            lambda value: self.wet_label.setText(f"{value / 100.0:.2f}")
        )
        controls.addRow("Global wet / dry", wet_row)

        self.tail = QDoubleSpinBox()
        self.tail.setRange(0.0, 12.0)
        self.tail.setDecimals(1)
        self.tail.setSingleStep(0.5)
        self.tail.setValue(1.5)
        self.tail.setSuffix(" s")
        self.tail.setToolTip("Additional render time for effect tails; it does not time-stretch the source.")
        controls.addRow("Tail allowance", self.tail)
        layout.addWidget(controls_group)

        actions = QHBoxLayout()
        self.render_button = QPushButton("RENDER FX")
        self.render_button.clicked.connect(self._render)
        self.play_source_button = QPushButton("PLAY SOURCE")
        self.play_source_button.clicked.connect(self._play_source)
        self.play_result_button = QPushButton("PLAY PROCESSED")
        self.play_result_button.clicked.connect(self._play_processed)
        self.save_button = QPushButton("EXPORT WAV…")
        self.save_button.clicked.connect(self._save)
        for button in (
            self.render_button,
            self.play_source_button,
            self.play_result_button,
            self.save_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)

        preview_row = QHBoxLayout()
        source_box = QGroupBox("DRY REFERENCE")
        source_box_layout = QVBoxLayout(source_box)
        self.source_preview = AudioPreview()
        source_box_layout.addWidget(self.source_preview)
        processed_box = QGroupBox("PROCESSED RESULT")
        processed_box_layout = QVBoxLayout(processed_box)
        self.processed_preview = AudioPreview()
        processed_box_layout.addWidget(self.processed_preview)
        preview_row.addWidget(source_box, 1)
        preview_row.addWidget(processed_box, 1)
        layout.addLayout(preview_row, 1)

        self.status = QLabel(
            "Pyo is an optional offline processor. Load a source, choose a chain, and render a separate result."
        )
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self._update_description()
        self._set_result_available(False)
        self.play_source_button.setEnabled(False)

    def _update_description(self, *_args: Any) -> None:
        name = str(self.preset.currentData() or "restrained_space")
        self.description.setText(FX_PRESET_DESCRIPTIONS[name])

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose source audio",
            str(Path.cwd()),
            "Audio files (*.wav *.flac *.aif *.aiff *.ogg);;All files (*.*)",
        )
        if not path:
            return
        try:
            import soundfile as sf

            audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            if audio.ndim != 2 or audio.shape[1] not in (1, 2):
                raise ValueError("Only mono and stereo source files are supported.")
            if audio.shape[0] == 0:
                raise ValueError("The selected audio file is empty.")
            audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
        except Exception as exc:
            self.status.setText(f"Could not load source audio: {exc}")
            return

        self.source_audio = np.ascontiguousarray(audio, dtype=np.float32)
        self.processed_audio = None
        self.sample_rate = int(sample_rate)
        self.source_path = Path(path)
        self.path_field.setText(str(self.source_path))
        self.source_preview.set_audio(self.source_audio, self.sample_rate)
        self.processed_preview.set_audio(None)
        self.play_source_button.setEnabled(True)
        self._set_result_available(False)
        self.status.setText(
            f"Loaded {self.source_path.name} · {len(audio) / self.sample_rate:.2f}s · "
            f"{self.sample_rate:,} Hz · {audio.shape[1]} channel(s). Original file is untouched."
        )

    def _set_result_available(self, available: bool) -> None:
        self.play_result_button.setEnabled(available)
        self.save_button.setEnabled(available)

    def _render(self) -> None:
        if self.source_audio is None:
            self.status.setText("Choose a source file before rendering.")
            return
        if self._worker is not None:
            return
        source = self.source_audio.copy()
        sample_rate = self.sample_rate
        preset = str(self.preset.currentData())
        wet = self.wet.value() / 100.0
        tail = self.tail.value()
        self.render_button.setEnabled(False)
        self.status.setText(f"Rendering {preset.replace('_', ' ')} offline…")
        worker = RenderWorker(
            lambda: render_pyo_fx(
                source, sample_rate, preset=preset, wet=wet, tail_seconds=tail
            )
        )
        self._worker = worker
        worker.signals.finished.connect(self._render_finished)
        worker.signals.error.connect(self._render_failed)
        QThreadPool.globalInstance().start(worker)

    def _render_finished(self, result: object) -> None:
        self._worker = None
        self.render_button.setEnabled(True)
        if not isinstance(result, np.ndarray):
            self.status.setText("FX worker returned an unexpected result.")
            return
        self.processed_audio = result
        self.processed_preview.set_audio(result, self.sample_rate)
        self._set_result_available(True)
        peak = float(np.max(np.abs(result))) if result.size else 0.0
        duration = len(result) / float(self.sample_rate)
        self.status.setText(
            f"Render complete · {duration:.2f}s · peak {peak:.3f} · "
            "dry source retained separately."
        )

    def _render_failed(self, message: str) -> None:
        self._worker = None
        self.render_button.setEnabled(True)
        self._set_result_available(False)
        self.status.setText(message)

    def _play_source(self) -> None:
        if self.source_audio is None:
            return
        try:
            self.player.start(_playable(self.source_audio), self.sample_rate)
        except Exception as exc:
            self.status.setText(f"Playback failed: {exc}")

    def _play_processed(self) -> None:
        if self.processed_audio is None:
            return
        try:
            self.player.start(_playable(self.processed_audio), self.sample_rate)
        except Exception as exc:
            self.status.setText(f"Playback failed: {exc}")

    def _save(self) -> None:
        if self.processed_audio is None:
            return
        default_name = (
            f"{self.source_path.stem}_fx.wav" if self.source_path else "reawarp_fx.wav"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export processed audio", default_name, "WAV audio (*.wav)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".wav":
            destination = destination.with_suffix(".wav")
        try:
            write_wav(destination, self.processed_audio, self.sample_rate, 24)
        except Exception as exc:
            self.status.setText(f"Export failed: {exc}")
            return
        self.status.setText(f"Exported processed audio to {destination.resolve()}")
