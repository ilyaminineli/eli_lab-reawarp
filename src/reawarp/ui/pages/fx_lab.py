"""Editable offline FX-chain workspace backed by the optional Pyo DSP engine."""

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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from reawarp.export.wav import write_wav
from reawarp.fx import (
    FX_PRESET_DESCRIPTIONS,
    FX_PRESETS,
    FX_STAGE_DEFAULTS,
    FX_STAGE_DESCRIPTIONS,
    FX_STAGE_PARAMETERS,
    default_fx_stage,
    load_fx_chain,
    normalise_fx_stages,
    render_pyo_fx,
    save_fx_chain,
)
from reawarp.ui.audio_player import AudioPlayer
from reawarp.ui.widgets.audio_preview import AudioPreview
from reawarp.ui.workers import RenderWorker


def _playable(audio: np.ndarray) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 2 and samples.shape[1] == 1:
        return samples[:, 0]
    return samples


class FxLabPage(QWidget):
    """Load audio, build a serial chain, compare dry/wet, and export safely."""

    def __init__(self, player: AudioPlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player = player
        self.source_audio: np.ndarray | None = None
        self.processed_audio: np.ndarray | None = None
        self.sample_rate = 48_000
        self.source_path: Path | None = None
        self._worker: RenderWorker | None = None
        self._stages: list[dict[str, float | str]] = [
            dict(stage) for stage in FX_PRESETS["restrained_space"]
        ]
        self._parameter_widgets: dict[str, QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading = QLabel("FX LAB / EDITABLE OFFLINE PROCESSING")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        source_group = QGroupBox("SOURCE / NON-DESTRUCTIVE INPUT")
        source_layout = QHBoxLayout(source_group)
        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setPlaceholderText("Choose a mono or stereo audio file…")
        source_layout.addWidget(self.path_field, 1)
        self.source_button = QPushButton("BROWSE…")
        self.source_button.clicked.connect(self._browse)
        source_layout.addWidget(self.source_button)
        layout.addWidget(source_group)

        self.controls_group = QGroupBox("SERIAL EFFECT CHAIN")
        controls_layout = QVBoxLayout(self.controls_group)

        preset_row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem("CUSTOM CHAIN", "__custom__")
        for name in FX_PRESETS:
            self.preset.addItem(name.replace("_", " ").upper(), name)
        self.preset.setCurrentIndex(1)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        preset_row.addWidget(QLabel("Starting point"))
        preset_row.addWidget(self.preset, 1)
        self.chain_name = QLineEdit("restrained_space")
        self.chain_name.setMaximumWidth(220)
        self.chain_name.setPlaceholderText("Chain name")
        preset_row.addWidget(QLabel("Name"))
        preset_row.addWidget(self.chain_name)
        controls_layout.addLayout(preset_row)

        self.description = QLabel()
        self.description.setObjectName("muted")
        self.description.setWordWrap(True)
        controls_layout.addWidget(self.description)

        editor_row = QHBoxLayout()
        stage_group = QGroupBox("ORDER / PROCESSING STAGES")
        stage_layout = QVBoxLayout(stage_group)
        add_row = QHBoxLayout()
        self.add_kind = QComboBox()
        for kind in FX_STAGE_DEFAULTS:
            self.add_kind.addItem(kind.replace("_", " ").upper(), kind)
        add_row.addWidget(self.add_kind, 1)
        self.add_button = QPushButton("ADD")
        self.add_button.clicked.connect(self._add_stage)
        add_row.addWidget(self.add_button)
        stage_layout.addLayout(add_row)

        self.stage_list = QListWidget()
        self.stage_list.setMinimumWidth(205)
        self.stage_list.currentRowChanged.connect(self._select_stage)
        stage_layout.addWidget(self.stage_list, 1)

        reorder_row = QHBoxLayout()
        self.remove_button = QPushButton("REMOVE")
        self.remove_button.clicked.connect(self._remove_stage)
        self.up_button = QPushButton("MOVE UP")
        self.up_button.clicked.connect(lambda: self._move_stage(-1))
        self.down_button = QPushButton("MOVE DOWN")
        self.down_button.clicked.connect(lambda: self._move_stage(1))
        for button in (self.remove_button, self.up_button, self.down_button):
            reorder_row.addWidget(button)
        stage_layout.addLayout(reorder_row)
        editor_row.addWidget(stage_group, 1)

        parameter_group = QGroupBox("SELECTED STAGE / PARAMETERS")
        parameter_layout = QVBoxLayout(parameter_group)
        self.stage_help = QLabel("Select a stage to edit its parameters.")
        self.stage_help.setObjectName("muted")
        self.stage_help.setWordWrap(True)
        parameter_layout.addWidget(self.stage_help)
        self.stage_form = QFormLayout()
        parameter_layout.addLayout(self.stage_form)
        parameter_layout.addStretch(1)
        editor_row.addWidget(parameter_group, 1)
        controls_layout.addLayout(editor_row, 1)

        global_row = QHBoxLayout()
        global_row.addWidget(QLabel("Global wet / dry"))
        self.wet = QSlider(Qt.Orientation.Horizontal)
        self.wet.setRange(0, 100)
        self.wet.setValue(75)
        global_row.addWidget(self.wet, 1)
        self.wet_label = QLabel("0.75")
        self.wet_label.setMinimumWidth(42)
        global_row.addWidget(self.wet_label)

        global_row.addWidget(QLabel("Tail"))
        self.tail = QDoubleSpinBox()
        self.tail.setRange(0.0, 12.0)
        self.tail.setDecimals(1)
        self.tail.setSingleStep(0.5)
        self.tail.setValue(1.5)
        self.tail.setSuffix(" s")
        self.tail.setMaximumWidth(100)
        global_row.addWidget(self.tail)
        controls_layout.addLayout(global_row)

        chain_actions = QHBoxLayout()
        self.load_chain_button = QPushButton("LOAD CHAIN JSON…")
        self.load_chain_button.clicked.connect(self._load_chain)
        self.save_chain_button = QPushButton("SAVE CHAIN JSON…")
        self.save_chain_button.clicked.connect(self._save_chain)
        chain_actions.addWidget(self.load_chain_button)
        chain_actions.addWidget(self.save_chain_button)
        chain_actions.addStretch(1)
        self.stage_count = QLabel("3 / 12 stages")
        self.stage_count.setObjectName("muted")
        chain_actions.addWidget(self.stage_count)
        controls_layout.addLayout(chain_actions)
        layout.addWidget(self.controls_group)

        actions = QHBoxLayout()
        self.render_button = QPushButton("RENDER CHAIN")
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
            "Build an ordered chain, render it offline, compare against the dry source, and export a new file."
        )
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.wet.valueChanged.connect(self._global_mix_changed)
        self.wet.valueChanged.connect(
            lambda value: self.wet_label.setText(f"{value / 100.0:.2f}")
        )
        self.tail.valueChanged.connect(self._invalidate_result)
        self._refresh_stage_list(selected=0)
        self._update_description()
        self._set_result_available(False)
        self.play_source_button.setEnabled(False)
        self._update_stage_buttons()

    def _preset_changed(self, *_args: Any) -> None:
        name = self.preset.currentData()
        if name not in FX_PRESETS:
            self._update_description()
            return
        self._stages = [dict(stage) for stage in FX_PRESETS[str(name)]]
        self.chain_name.setText(str(name))
        self._refresh_stage_list(selected=0)
        self._update_description()
        self._invalidate_result()

    def _update_description(self) -> None:
        name = self.preset.currentData()
        if name in FX_PRESET_DESCRIPTIONS:
            self.description.setText(FX_PRESET_DESCRIPTIONS[str(name)])
        else:
            self.description.setText(
                "Custom serial chain. Effects run in the order shown; use stage mix "
                "for parallel dry/wet blends and keep an eye on the combined level."
            )

    def _mark_custom(self) -> None:
        index = self.preset.findData("__custom__")
        if index >= 0 and self.preset.currentIndex() != index:
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(index)
            self.preset.blockSignals(False)
        self._update_description()

    def _refresh_stage_list(self, selected: int = -1) -> None:
        self.stage_list.blockSignals(True)
        self.stage_list.clear()
        for index, stage in enumerate(self._stages, start=1):
            kind = str(stage["type"])
            self.stage_list.addItem(QListWidgetItem(f"{index:02d}  /  {kind.upper()}"))
        if self._stages:
            selected = max(0, min(selected, len(self._stages) - 1))
            self.stage_list.setCurrentRow(selected)
        else:
            self.stage_list.setCurrentRow(-1)
        self.stage_list.blockSignals(False)
        self._select_stage(self.stage_list.currentRow())
        self.stage_count.setText(f"{len(self._stages)} / 12 stages")
        self._update_stage_buttons()

    def _clear_stage_form(self) -> None:
        while self.stage_form.rowCount():
            self.stage_form.removeRow(0)
        self._parameter_widgets.clear()

    def _select_stage(self, row: int) -> None:
        self._clear_stage_form()
        if row < 0 or row >= len(self._stages):
            self.stage_help.setText("Select a stage to edit its parameters.")
            self._update_stage_buttons()
            return

        stage = self._stages[row]
        kind = str(stage["type"])
        self.stage_help.setText(FX_STAGE_DESCRIPTIONS[kind])
        for field, spec in FX_STAGE_PARAMETERS[kind].items():
            minimum, maximum, step, decimals, suffix = spec
            if field in {"cutoff_hz", "center_hz"}:
                maximum = min(maximum, float(self.sample_rate) * 0.45)
            control = QDoubleSpinBox()
            control.setRange(minimum, maximum)
            control.setSingleStep(step)
            control.setDecimals(decimals)
            control.setSuffix(suffix)
            control.setValue(float(stage[field]))
            control.valueChanged.connect(
                lambda value, key=field: self._update_stage_parameter(key, value)
            )
            self.stage_form.addRow(field.replace("_", " ").title(), control)
            self._parameter_widgets[field] = control
        self._update_stage_buttons()

    def _update_stage_parameter(self, field: str, value: float) -> None:
        row = self.stage_list.currentRow()
        if row < 0 or row >= len(self._stages):
            return
        self._stages[row][field] = float(value)
        self._mark_custom()
        item = self.stage_list.item(row)
        if item is not None:
            item.setText(f"{row + 1:02d}  /  {str(self._stages[row]['type']).upper()}  ·  edited")
        self._invalidate_result()

    def _update_stage_buttons(self) -> None:
        row = self.stage_list.currentRow()
        has_row = 0 <= row < len(self._stages)
        self.remove_button.setEnabled(has_row and len(self._stages) > 1)
        self.up_button.setEnabled(has_row and row > 0)
        self.down_button.setEnabled(has_row and row < len(self._stages) - 1)
        self.add_button.setEnabled(len(self._stages) < 12)

    def _add_stage(self) -> None:
        if len(self._stages) >= 12:
            return
        kind = str(self.add_kind.currentData())
        self._stages.append(default_fx_stage(kind))
        self._mark_custom()
        self._refresh_stage_list(selected=len(self._stages) - 1)
        self._invalidate_result()

    def _remove_stage(self) -> None:
        row = self.stage_list.currentRow()
        if len(self._stages) <= 1 or not 0 <= row < len(self._stages):
            return
        del self._stages[row]
        self._mark_custom()
        self._refresh_stage_list(selected=min(row, len(self._stages) - 1))
        self._invalidate_result()

    def _move_stage(self, direction: int) -> None:
        row = self.stage_list.currentRow()
        target = row + int(direction)
        if not 0 <= row < len(self._stages) or not 0 <= target < len(self._stages):
            return
        self._stages[row], self._stages[target] = self._stages[target], self._stages[row]
        self._mark_custom()
        self._refresh_stage_list(selected=target)
        self._invalidate_result()

    def _global_mix_changed(self, *_args: Any) -> None:
        self._invalidate_result()

    def _invalidate_result(self, *_args: Any) -> None:
        self.processed_audio = None
        self.processed_preview.set_audio(None)
        self._set_result_available(False)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose source audio",
            str(self.source_path.parent if self.source_path else Path.cwd()),
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
            normalise_fx_stages(self._stages, sample_rate=int(sample_rate))
        except Exception as exc:
            self.status.setText(f"Could not load source audio: {exc}")
            return

        self.source_audio = np.ascontiguousarray(audio, dtype=np.float32)
        self.sample_rate = int(sample_rate)
        self.source_path = Path(path)
        self.path_field.setText(str(self.source_path))
        self.source_preview.set_audio(self.source_audio, self.sample_rate)
        self.play_source_button.setEnabled(True)
        self._invalidate_result()
        self._refresh_stage_list(selected=self.stage_list.currentRow())
        self.status.setText(
            f"Loaded {self.source_path.name} · {len(audio) / self.sample_rate:.2f}s · "
            f"{self.sample_rate:,} Hz · {audio.shape[1]} channel(s). Original file is untouched."
        )

    def _load_chain(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load FX chain", str(Path.cwd()), "Reawarp FX chain (*.json)"
        )
        if not path:
            return
        try:
            chain = load_fx_chain(path, sample_rate=self.sample_rate)
        except Exception as exc:
            self.status.setText(f"Could not load FX chain: {exc}")
            return

        self._stages = [dict(stage) for stage in chain["stages"]]
        self.chain_name.setText(chain["name"])
        self.wet.setValue(round(float(chain["wet"]) * 100))
        self.tail.setValue(float(chain["tail_seconds"]))
        self._mark_custom()
        self._refresh_stage_list(selected=0)
        self._invalidate_result()
        self.status.setText(
            f"Loaded chain {chain['name']} · {len(self._stages)} ordered stage(s)."
        )

    def _save_chain(self) -> None:
        default = f"{self.chain_name.text().strip() or 'reawarp_chain'}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save FX chain", default, "Reawarp FX chain (*.json)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        try:
            saved = save_fx_chain(
                destination,
                name=self.chain_name.text().strip(),
                stages=self._stages,
                wet=self.wet.value() / 100.0,
                tail_seconds=self.tail.value(),
            )
        except Exception as exc:
            self.status.setText(f"Could not save FX chain: {exc}")
            return
        self.status.setText(f"Saved portable FX chain to {saved.resolve()}")

    def _set_rendering(self, rendering: bool) -> None:
        self.render_button.setEnabled(not rendering)
        self.source_button.setEnabled(not rendering)
        self.controls_group.setEnabled(not rendering)

    def _render(self) -> None:
        if self.source_audio is None:
            self.status.setText("Choose a source file before rendering.")
            return
        if self._worker is not None:
            return
        try:
            stages = normalise_fx_stages(self._stages, sample_rate=self.sample_rate)
        except Exception as exc:
            self.status.setText(f"Invalid effect chain: {exc}")
            return

        source = self.source_audio.copy()
        sample_rate = self.sample_rate
        wet = self.wet.value() / 100.0
        tail = self.tail.value()
        chain_name = self.chain_name.text().strip() or "custom chain"
        self._set_rendering(True)
        self.status.setText(
            f"Rendering {chain_name} · {len(stages)} ordered stage(s) offline…"
        )
        worker = RenderWorker(
            lambda: render_pyo_fx(
                source,
                sample_rate,
                preset=None,
                stages=stages,
                wet=wet,
                tail_seconds=tail,
            )
        )
        self._worker = worker
        worker.signals.finished.connect(self._render_finished)
        worker.signals.error.connect(self._render_failed)
        QThreadPool.globalInstance().start(worker)

    def _render_finished(self, result: object) -> None:
        self._worker = None
        self._set_rendering(False)
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
        self._set_rendering(False)
        self._set_result_available(False)
        self.status.setText(message)

    def _set_result_available(self, available: bool) -> None:
        self.play_result_button.setEnabled(available)
        self.save_button.setEnabled(available)

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
