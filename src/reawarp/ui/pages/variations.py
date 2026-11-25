"""Candidate selection and critical-listening workspace."""
from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from reawarp.ui.widgets.audio_preview import AudioPreview


class VariationBrowserPage(QWidget):
    batchRequested = Signal(dict)
    cancelRequested = Signal()
    candidateSelected = Signal(str)
    candidateAction = Signal(str, str)
    notesChanged = Signal(str, str)
    compareRequested = Signal(str)
    listeningSetRequested = Signal(str)
    auditionRequested = Signal(str)
    loadProjectRequested = Signal()
    listeningItemRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        heading = QLabel("VARIATION BROWSER / CRITICAL LISTENING")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel(
            "Keep a frozen source, generate comparable candidates and select by listening. "
            "A/B copies are level-matched; analysis reports signal differences, never artistic scores."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)
        project_actions = QHBoxLayout()
        self.load_project_button = QPushButton("LOAD EXPORTED PROJECT / SESSION")
        self.load_project_button.clicked.connect(self.loadProjectRequested.emit)
        project_actions.addWidget(self.load_project_button)
        project_actions.addStretch(1)
        root.addLayout(project_actions)

        controls = QGroupBox("CANDIDATE BATCH")
        controls_layout = QVBoxLayout(controls)
        top = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("STEM / ROLE VARIATIONS", "stems")
        self.mode.addItem("FULL COMPOSITION VARIATIONS", "full_project")
        self.mode.addItem("SAMPLE-BANK VARIATIONS", "sample_bank")
        self.mode.addItem("SCORE AUTOMATION VARIATIONS", "automation")
        self.mode.addItem("SOUND-OBJECT VARIATIONS", "sound_object")
        top.addWidget(self.mode, 2)
        top.addWidget(QLabel("COUNT"))
        self.count = QSpinBox()
        self.count.setRange(1, 16)
        self.count.setValue(4)
        top.addWidget(self.count)
        self.blind = QCheckBox("HIDE CANDIDATE IDENTITY")
        self.blind.setChecked(True)
        self.blind.setToolTip("Keep candidate labels anonymous during the first listening pass.")
        top.addWidget(self.blind)
        controls_layout.addLayout(top)
        self.targets = QListWidget()
        self.targets.setMaximumHeight(92)
        self.targets.setToolTip("Choose one or more stems. Pair selections are regenerated together.")
        controls_layout.addWidget(self.targets)
        actions = QHBoxLayout()
        self.generate_button = QPushButton("GENERATE BATCH")
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setEnabled(False)
        self.generate_button.clicked.connect(self._request_batch)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        actions.addWidget(self.generate_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        controls_layout.addLayout(actions)
        root.addWidget(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("CANDIDATES"))
        self.candidates = QListWidget()
        self.candidates.currentItemChanged.connect(self._selected_changed)
        left_layout.addWidget(self.candidates, 1)
        state_actions = QHBoxLayout()
        self.keep_button = QPushButton("KEEP")
        self.discard_button = QPushButton("DISCARD")
        self.promote_button = QPushButton("PROMOTE")
        for button, state in (
            (self.keep_button, "kept"), (self.discard_button, "discarded"),
            (self.promote_button, "promoted"),
        ):
            button.clicked.connect(lambda _checked=False, value=state: self._action(value))
            state_actions.addWidget(button)
        left_layout.addLayout(state_actions)
        branch_actions = QHBoxLayout()
        self.branch_button = QPushButton("BRANCH FROM SELECTED")
        self.restore_button = QPushButton("RESTORE FROZEN BASE")
        self.branch_button.clicked.connect(lambda: self._action("branched"))
        self.restore_button.clicked.connect(lambda: self.candidateAction.emit("restore", "base"))
        branch_actions.addWidget(self.branch_button)
        branch_actions.addWidget(self.restore_button)
        left_layout.addLayout(branch_actions)
        left.setMinimumWidth(260)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        details_row = QHBoxLayout()
        self.candidate_title = QLabel("NO CANDIDATE SELECTED")
        self.candidate_title.setObjectName("sectionTitle")
        details_row.addWidget(self.candidate_title, 1)
        self.reveal = QCheckBox("SHOW CHANGES")
        self.reveal.setChecked(False)
        details_row.addWidget(self.reveal)
        right_layout.addLayout(details_row)
        self.details = QLabel("Candidate parameters remain hidden until requested.")
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        right_layout.addWidget(self.details)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Listening notes — identity, role clarity, negative space, transient preservation…")
        self.notes.setMaximumHeight(76)
        self.notes.textChanged.connect(self._notes_changed)
        right_layout.addWidget(self.notes)

        compare_row = QHBoxLayout()
        self.compare_stage = QComboBox()
        for label, stage in (
            ("DRY MASTER", "dry_master"), ("DRY STEM", "dry_stem"),
            ("DIRECT", "direct"), ("PROCESSED STEM", "processed"), ("INSERT", "insert"), ("SPACE SEND", "send.space"),
            ("ECHO SEND", "send.echo"), ("SPACE RETURN", "return.space"),
            ("ECHO RETURN", "return.echo"), ("FX MASTER", "master"),
        ):
            self.compare_stage.addItem(label, stage)
        compare_row.addWidget(self.compare_stage)
        self.compare_button = QPushButton("MATCHED A/B + DIFFERENCE")
        self.play_a_button = QPushButton("PLAY A")
        self.play_b_button = QPushButton("PLAY B")
        self.play_diff_button = QPushButton("PLAY Δ")
        self.play_listening_button = QPushButton("PLAY LISTENING SET")
        self.compare_button.clicked.connect(self._compare)
        self.play_a_button.clicked.connect(lambda: self.auditionRequested.emit("reference"))
        self.play_b_button.clicked.connect(lambda: self.auditionRequested.emit("candidate"))
        self.play_diff_button.clicked.connect(lambda: self.auditionRequested.emit("difference"))
        for button in (self.compare_button, self.play_a_button, self.play_b_button, self.play_diff_button, self.play_listening_button):
            compare_row.addWidget(button)
        self.play_listening_button.clicked.connect(lambda: self.auditionRequested.emit("listening"))
        right_layout.addLayout(compare_row)

        listening_row = QHBoxLayout()
        listening_row.addWidget(QLabel("LISTENING SET"))
        self.listening_set = QComboBox()
        for label, key in (
            ("FULL MIX", "full_mix"), ("ISOLATED ROLES", "isolated_roles"),
            ("ROLE PAIRS", "role_pairs"), ("TRANSITIONS", "transitions"),
            ("OPENING", "opening"), ("MIDDLE", "middle"), ("ENDING", "ending"),
            ("SUBTRACTION", "subtraction"),
        ):
            self.listening_set.addItem(label, key)
        self.listening_set.currentIndexChanged.connect(
            lambda: self.listeningSetRequested.emit(str(self.listening_set.currentData()))
        )
        listening_row.addWidget(self.listening_set, 1)
        self.listening_item = QComboBox()
        self.listening_item.currentIndexChanged.connect(
            lambda: self.listeningItemRequested.emit(str(self.listening_item.currentData()))
            if self.listening_item.currentData() is not None else None
        )
        listening_row.addWidget(self.listening_item, 1)
        right_layout.addLayout(listening_row)

        previews = QSplitter(Qt.Orientation.Horizontal)
        self.reference_preview = AudioPreview()
        self.candidate_preview = AudioPreview()
        self.difference_preview = AudioPreview()
        previews.addWidget(self._preview_panel("REFERENCE / A", self.reference_preview))
        previews.addWidget(self._preview_panel("CANDIDATE / B", self.candidate_preview))
        previews.addWidget(self._preview_panel("DIFFERENCE", self.difference_preview))
        right_layout.addWidget(previews, 1)
        splitter.addWidget(right)
        splitter.setSizes([320, 900])
        root.addWidget(splitter, 1)

        self._records: dict[str, Any] = {}
        self._selected_id: str | None = None
        self._notes_loading = False
        self._stems: tuple[str, ...] = ()
        self._sound_objects: tuple[tuple[str, str], ...] = ()
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.blind.toggled.connect(self._refresh_candidate_labels)
        self.reveal.toggled.connect(self._refresh_details)

    @staticmethod
    def _preview_panel(title: str, preview: AudioPreview) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 2, 2)
        label = QLabel(title)
        label.setObjectName("muted")
        layout.addWidget(label)
        layout.addWidget(preview, 1)
        return panel

    def set_stems(self, names: list[str] | tuple[str, ...]) -> None:
        self._stems = tuple(names)
        self._populate_targets()

    def set_sound_objects(self, patches: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> None:
        self._sound_objects = tuple((str(patch_id), str(name)) for patch_id, name in patches)
        self._populate_targets()

    def _populate_targets(self) -> None:
        mode = str(self.mode.currentData() or "stems")
        self.targets.clear()
        if mode not in {"stems", "automation", "sound_object"}:
            return
        if mode == "sound_object":
            choices = self._sound_objects
            for patch_id, name in choices:
                item = QListWidgetItem(f"SOUND OBJECT · {name}")
                item.setData(Qt.ItemDataRole.UserRole, patch_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.targets.addItem(item)
            if choices:
                self.targets.item(0).setCheckState(Qt.CheckState.Checked)
            return
        for name in self._stems:
            item = QListWidgetItem(name.replace("_", " ").upper())
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        default = "melody" if "melody" in self._stems else (self._stems[0] if self._stems else None)
        if default:
            for index in range(self.targets.count()):
                item = self.targets.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == default:
                    item.setCheckState(Qt.CheckState.Checked)
                    break

    def _mode_changed(self, *_args: Any) -> None:
        mode = str(self.mode.currentData() or "stems")
        self.targets.setEnabled(mode in {"stems", "sound_object", "automation"})
        self._populate_targets()

    def _request_batch(self) -> None:
        selected = [
            self.targets.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.targets.count())
            if self.targets.item(i).checkState() == Qt.CheckState.Checked
        ]
        mode = str(self.mode.currentData() or "stems")
        if mode in {"stems", "sound_object"} and not selected:
            self.candidate_title.setText(
                "SELECT A STEM" if mode == "stems" else "INDEX OR SELECT A SOUND OBJECT IN THE LIBRARY"
            )
            return
        self.batchRequested.emit({
            "mode": mode, "targets": selected, "count": self.count.value(),
            "label": "Variation batch",
        })

    def set_batch_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def set_candidates(self, records: list[Any], *, selected_id: str | None = None) -> None:
        previous = selected_id or self._selected_id
        self._records = {str(item.candidate_id): item for item in records}
        self.candidates.blockSignals(True)
        self.candidates.clear()
        for index, record in enumerate(records):
            candidate_id = str(record.candidate_id)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, candidate_id)
            self.candidates.addItem(item)
        self._refresh_candidate_labels()
        selected_index = 0
        if previous:
            for index in range(self.candidates.count()):
                if self.candidates.item(index).data(Qt.ItemDataRole.UserRole) == previous:
                    selected_index = index
                    break
        self.candidates.setCurrentRow(selected_index if self.candidates.count() else -1)
        self.candidates.blockSignals(False)
        self._selected_id = previous
        self._selected_changed(self.candidates.currentItem(), None)

    def _refresh_candidate_labels(self, *_args: Any) -> None:
        for index in range(self.candidates.count()):
            item = self.candidates.item(index)
            candidate_id = str(item.data(Qt.ItemDataRole.UserRole))
            record = self._records.get(candidate_id)
            if record is None:
                continue
            if self.blind.isChecked():
                label = f"CANDIDATE {chr(65 + (index % 26))}"
            else:
                label = f"{record.label} · {record.selection_state.upper()}"
            item.setText(label)

    def _refresh_details(self, *_args: Any) -> None:
        record = self._records.get(self._selected_id or "")
        if record is None:
            self.details.setText("Candidate parameters remain hidden until requested.")
            return
        if self.reveal.isChecked() and not self.blind.isChecked():
            changed = json_summary(record.changed_parameters)
            self.details.setText(
                f"MODE {record.mode.upper()} · TARGETS {', '.join(record.targets) or 'FULL PROJECT'}\n"
                f"SEED {record.variation_seed} · {changed}\n"
                f"TECHNICAL FLAGS {', '.join(record.technical_flags) or 'NONE'}"
            )
        else:
            self.details.setText("Candidate parameters hidden · select by listening before revealing changes.")

    def _selected_changed(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if item is None:
            self._selected_id = None
            self.candidate_title.setText("NO CANDIDATE SELECTED")
            self._refresh_details()
            return
        candidate_id = str(item.data(Qt.ItemDataRole.UserRole))
        self._selected_id = candidate_id
        record = self._records.get(candidate_id)
        self.candidate_title.setText("CANDIDATE" if self.blind.isChecked() else getattr(record, "label", candidate_id))
        self._notes_loading = True
        self.notes.setPlainText(getattr(record, "notes", "") if record is not None else "")
        self._notes_loading = False
        self._refresh_details()
        self.candidateSelected.emit(candidate_id)

    def _notes_changed(self) -> None:
        if self._notes_loading or not self._selected_id:
            return
        self.notesChanged.emit(self._selected_id, self.notes.toPlainText())

    def _action(self, state: str) -> None:
        if self._selected_id:
            self.candidateAction.emit(state, self._selected_id)

    def _compare(self) -> None:
        if self._selected_id:
            self.compareRequested.emit(self._selected_id)

    def set_comparison(self, reference, candidate, difference, sample_rate: int) -> None:
        self.reference_preview.set_audio(reference, sample_rate)
        self.candidate_preview.set_audio(candidate, sample_rate)
        self.difference_preview.set_audio(difference, sample_rate)

    def set_listening_items(self, buffers: dict[str, np.ndarray]) -> None:
        self.listening_item.blockSignals(True)
        self.listening_item.clear()
        for label in buffers:
            self.listening_item.addItem(label, label)
        self.listening_item.blockSignals(False)
        if self.listening_item.count():
            self.listening_item.setCurrentIndex(0)
            self.listeningItemRequested.emit(str(self.listening_item.currentData()))

    def set_listening_audio(self, audio: np.ndarray | None, sample_rate: int) -> None:
        self.difference_preview.set_audio(audio, sample_rate)

    @property
    def selected_candidate_id(self) -> str | None:
        return self._selected_id


def json_summary(value: Any) -> str:
    import json
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= 280 else text[:277] + "..."
