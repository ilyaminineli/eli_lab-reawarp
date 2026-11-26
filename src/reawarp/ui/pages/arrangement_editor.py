"""M33 arrangement editor: manual phrase assembly, edit history and finishing gates."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from reawarp.composition.arrangement import (
    CHECKLIST_ITEMS,
    ArrangementClip,
    ArrangementPlan,
    arrangement_timeline,
)
from reawarp.composition.endings import ending_plans_from_score
from reawarp.composition.phrases import PhrasePlan
from reawarp.composition.transitions import transition_plans_from_score


class ArrangementEditorPage(QWidget):
    """Curate frozen phrase material into a finished Score-native arrangement."""

    createRequested = Signal()
    moveRequested = Signal(str, str)
    duplicateRequested = Signal(str, str)
    trimRequested = Signal(str, str, str)
    reorderRequested = Signal(str, int)
    muteRequested = Signal(str, bool)
    exchangeRequested = Signal(str, str, str)
    replaceRequested = Signal(str, str)
    freezeRequested = Signal(str)
    branchRequested = Signal()
    revertRequested = Signal()
    undoRequested = Signal()
    redoRequested = Signal()
    printRequested = Signal(str)
    moveTransitionRequested = Signal(str, str)
    moveEndingRequested = Signal(str, str)
    relinkTransitionRequested = Signal(str, str, str)
    checklistChanged = Signal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._score: Any | None = None
        self._plan: ArrangementPlan | None = None
        self._clips: dict[str, ArrangementClip] = {}
        self._candidates: list[Any] = []
        self._selected_item_id: str | None = None
        self._selected_kind: str | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)
        heading = QLabel("ARRANGEMENT EDITOR / MANUAL COMPOSITION")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel(
            "Assemble the piece from selected M28 phrases. Move, duplicate, trim, mute, "
            "exchange or replace material on the exact Score beat clock. Frozen choices remain "
            "independent of generator changes; print selected material as a separate WAV object."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)

        toolbar = QHBoxLayout()
        self.create_button = QPushButton("CREATE FROM PHRASES")
        self.undo_button = QPushButton("UNDO")
        self.redo_button = QPushButton("REDO")
        self.branch_button = QPushButton("BRANCH ARRANGEMENT")
        self.revert_button = QPushButton("REVERT TO GENERATION")
        self.create_button.clicked.connect(self.createRequested.emit)
        self.undo_button.clicked.connect(self.undoRequested.emit)
        self.redo_button.clicked.connect(self.redoRequested.emit)
        self.branch_button.clicked.connect(self.branchRequested.emit)
        self.revert_button.clicked.connect(self.revertRequested.emit)
        for button in (
            self.create_button,
            self.undo_button,
            self.redo_button,
            self.branch_button,
            self.revert_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("ARRANGEMENT TIMELINE"))
        self.items = QListWidget()
        self.items.currentItemChanged.connect(self._item_selected)
        left_layout.addWidget(self.items, 1)
        self.summary = QLabel("No arrangement created.")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        left_layout.addWidget(self.summary)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        edit_group = QGroupBox("SELECTED PHRASE / CUE")
        edit = QFormLayout(edit_group)
        self.move_to = QLineEdit()
        self.move_to.setPlaceholderText("Exact start beat, e.g. 24 or 37/2")
        self.move_button = QPushButton("MOVE TO BEAT")
        self.move_button.clicked.connect(self._move)
        edit.addRow("New start", self.move_to)
        edit.addRow(self.move_button)

        self.duplicate_at = QLineEdit()
        self.duplicate_at.setPlaceholderText("Blank = append after this phrase")
        self.duplicate_button = QPushButton("DUPLICATE PHRASE")
        self.duplicate_button.clicked.connect(self._duplicate)
        edit.addRow("Duplicate at", self.duplicate_at)
        edit.addRow(self.duplicate_button)

        trim_row = QHBoxLayout()
        self.trim_start = QLineEdit()
        self.trim_start.setPlaceholderText("New start")
        self.trim_end = QLineEdit()
        self.trim_end.setPlaceholderText("New exclusive end")
        trim_row.addWidget(self.trim_start)
        trim_row.addWidget(QLabel("→"))
        trim_row.addWidget(self.trim_end)
        self.trim_button = QPushButton("TRIM")
        self.trim_button.clicked.connect(self._trim)
        edit.addRow("Trim beat range", trim_row)
        edit.addRow(self.trim_button)

        order_row = QHBoxLayout()
        self.earlier_button = QPushButton("MOVE EARLIER")
        self.later_button = QPushButton("MOVE LATER")
        self.earlier_button.clicked.connect(lambda: self._reorder(-1))
        self.later_button.clicked.connect(lambda: self._reorder(1))
        order_row.addWidget(self.earlier_button)
        order_row.addWidget(self.later_button)
        edit.addRow("Sequence", order_row)

        action_row = QHBoxLayout()
        self.mute_button = QPushButton("MUTE")
        self.freeze_button = QPushButton("FREEZE SELECTION")
        self.print_button = QPushButton("PRINT TO NEW WAV")
        self.mute_button.clicked.connect(self._toggle_mute)
        self.freeze_button.clicked.connect(self._freeze)
        self.print_button.clicked.connect(self._print)
        action_row.addWidget(self.mute_button)
        action_row.addWidget(self.freeze_button)
        action_row.addWidget(self.print_button)
        edit.addRow(action_row)

        self.layer_source = QLineEdit()
        self.layer_source.setPlaceholderText("Current voice / layer")
        self.layer_target = QLineEdit()
        self.layer_target.setPlaceholderText("Target voice / layer")
        self.exchange_button = QPushButton("EXCHANGE LAYER")
        self.exchange_button.clicked.connect(self._exchange)
        edit.addRow("Layer source", self.layer_source)
        edit.addRow("Layer target", self.layer_target)
        edit.addRow(self.exchange_button)

        self.candidate = QComboBox()
        self.candidate.setToolTip(
            "M28 candidate from the source phrase selected in Phrase Workbench."
        )
        self.replace_button = QPushButton("REPLACE WITH SELECTED CANDIDATE")
        self.replace_button.clicked.connect(self._replace)
        edit.addRow("M28 candidate", self.candidate)
        edit.addRow(self.replace_button)
        right_layout.addWidget(edit_group)

        cue_group = QGroupBox("M30 TRANSITION / ENDING CUES")
        cue_form = QFormLayout(cue_group)
        self.cue_start = QLineEdit()
        self.cue_start.setPlaceholderText("Exact cue start beat")
        self.move_cue_button = QPushButton("MOVE SELECTED CUE")
        self.move_cue_button.clicked.connect(self._move_cue)
        cue_form.addRow("Cue start", self.cue_start)
        cue_form.addRow(self.move_cue_button)
        self.transition_source = QComboBox()
        self.transition_target = QComboBox()
        self.relink_button = QPushButton("RELINK TO SELECTED PHRASES")
        self.relink_button.clicked.connect(self._relink_transition)
        cue_form.addRow("Outgoing phrase", self.transition_source)
        cue_form.addRow("Incoming phrase", self.transition_target)
        cue_form.addRow(self.relink_button)
        right_layout.addWidget(cue_group)

        checklist_group = QGroupBox("FINISHING CHECKLIST · HUMAN SIGN-OFF")
        checklist_layout = QVBoxLayout(checklist_group)
        self.checks: dict[str, QCheckBox] = {}
        labels = {
            "form_review": "Form and section arc reviewed",
            "ending_review": "Ending / final gesture reviewed",
            "subtraction": "Subtraction and negative space reviewed",
            "identity_invariance": "Identity and invariance tested",
            "context": "Phrase and transition context auditioned",
            "low_volume": "Low-volume translation checked",
            "mono": "Mono compatibility checked",
            "peak_headroom": "Peak and headroom checked",
            "missing_sources": "Missing / changed sources resolved",
            "export_integrity": "Export and package integrity checked",
        }
        for key in CHECKLIST_ITEMS:
            check = QCheckBox(labels[key])
            check.toggled.connect(
                lambda checked, item=key: self.checklistChanged.emit(
                    item, bool(checked)
                )
            )
            self.checks[key] = check
            checklist_layout.addWidget(check)
        right_layout.addWidget(checklist_group)
        right_layout.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        self.status = QLabel(
            "Create an arrangement after defining phrase spans in Phrase Workbench."
        )
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._refresh_controls()

    def set_candidates(self, candidates: list[Any] | tuple[Any, ...]) -> None:
        self._candidates = list(candidates)
        self._refresh_candidate_choices()
        self._refresh_controls()

    def set_score(self, score: Any | None) -> None:
        selected = self._selected_item_id
        self._score = score
        self._plan = None
        self._clips = {}
        if score is not None:
            try:
                self._plan = ArrangementPlan.from_score(score)
                self._clips = {item.clip_id: item for item in self._plan.clips}
            except ValueError:
                self._plan = None
        self._loading = True
        self.items.blockSignals(True)
        self.items.clear()
        if score is not None and self._plan is not None:
            for item in arrangement_timeline(score):
                kind = item["kind"]
                if kind == "phrase":
                    clip = self._clips[item["item_id"]]
                    state = " · MUTED" if clip.muted else ""
                    state += " · FROZEN" if clip.frozen else ""
                    state += f" · {clip.origin.upper()}"
                else:
                    state = " · CUE"
                section = (
                    f" · section {item['section_id']}"
                    if kind == "phrase" and item.get("section_id")
                    else ""
                )
                label = (
                    f"{item['start_beats']}–{item['end_beats']}  "
                    f"{kind.upper()}  {item['label']}{section}{state}"
                )
                row = QListWidgetItem(label)
                row.setData(Qt.ItemDataRole.UserRole, item["item_id"])
                row.setData(Qt.ItemDataRole.UserRole + 1, kind)
                self.items.addItem(row)
                if item["item_id"] == selected:
                    self.items.setCurrentItem(row)
        self.items.blockSignals(False)
        self._loading = False
        if self.items.currentItem() is None and self.items.count():
            self.items.setCurrentRow(0)
        elif self.items.currentItem() is not None:
            self._read_selected(self.items.currentItem())
        self._set_checklist()
        self._refresh_transition_choices()
        if self.items.currentItem() is not None:
            self._read_selected(self.items.currentItem())
        if self._plan is not None:
            done = sum(self._plan.checklist.values())
            self.summary.setText(
                f"{len(self._plan.clips)} phrase clips · revision {self._plan.revision} · "
                f"{done}/{len(CHECKLIST_ITEMS)} finishing checks complete"
            )
            self.status.setText(
                "Arrangement is Score-native. Printed WAVs are separate objects; the generation "
                "stems remain unchanged. Export includes the full Score, MIDI, edit history and print lineage."
            )
        elif score is None:
            self.summary.setText("No composition loaded.")
            self.status.setText("Generate or load a project, then define phrase spans.")
        else:
            self.summary.setText("No arrangement created.")
            self.status.setText(
                "Create an arrangement from the current M28 PhrasePlan. Existing Score material is not changed."
            )
        self._refresh_candidate_choices()
        self._refresh_controls()

    def _set_checklist(self) -> None:
        values = self._plan.checklist if self._plan is not None else {}
        for key, check in self.checks.items():
            check.blockSignals(True)
            check.setChecked(bool(values.get(key, False)))
            check.setEnabled(self._plan is not None)
            check.blockSignals(False)

    def _item_selected(
        self, item: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if item is None:
            self._selected_item_id = None
            self._selected_kind = None
        else:
            self._read_selected(item)
        self._refresh_candidate_choices()
        self._refresh_controls()

    def _read_selected(self, item: QListWidgetItem) -> None:
        self._selected_item_id = str(item.data(Qt.ItemDataRole.UserRole))
        self._selected_kind = str(item.data(Qt.ItemDataRole.UserRole + 1))
        selected = self._clips.get(self._selected_item_id)
        if selected is not None:
            self.move_to.setText(str(selected.start_beats))
            self.trim_start.setText(str(selected.start_beats))
            self.trim_end.setText(str(selected.end_beats))
            self.cue_start.clear()
        elif self._score is not None:
            cue_start = ""
            if self._selected_kind == "transition":
                cue = next(
                    (
                        x
                        for x in transition_plans_from_score(self._score)
                        if x.transition_id == self._selected_item_id
                    ),
                    None,
                )
                cue_start = str(cue.start_beats) if cue else ""
                if cue is not None:
                    self.transition_source.setCurrentIndex(
                        self.transition_source.findData(cue.source_phrase_id)
                    )
                    self.transition_target.setCurrentIndex(
                        self.transition_target.findData(cue.target_phrase_id)
                    )
            elif self._selected_kind == "ending":
                cue = next(
                    (
                        x
                        for x in ending_plans_from_score(self._score)
                        if x.ending_id == self._selected_item_id
                    ),
                    None,
                )
                cue_start = str(cue.start_beats) if cue else ""
            self.cue_start.setText(cue_start)

    def _refresh_transition_choices(self) -> None:
        previous_source = self.transition_source.currentData()
        previous_target = self.transition_target.currentData()
        self.transition_source.blockSignals(True)
        self.transition_target.blockSignals(True)
        self.transition_source.clear()
        self.transition_target.clear()
        if self._score is not None:
            try:
                for phrase in PhrasePlan.from_score(self._score).phrases:
                    label = (
                        f"{phrase.phrase_id} · {phrase.start_beats}–{phrase.end_beats}"
                    )
                    self.transition_source.addItem(label, phrase.phrase_id)
                    self.transition_target.addItem(label, phrase.phrase_id)
            except ValueError:
                pass
        for combo, value in (
            (self.transition_source, previous_source),
            (self.transition_target, previous_target),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.transition_source.blockSignals(False)
        self.transition_target.blockSignals(False)

    def _relink_transition(self) -> None:
        if self._selected_kind != "transition" or not self._selected_item_id:
            return
        source = self.transition_source.currentData()
        target = self.transition_target.currentData()
        if source and target:
            self.relinkTransitionRequested.emit(
                self._selected_item_id, str(source), str(target)
            )

    def _refresh_candidate_choices(self) -> None:
        self.candidate.blockSignals(True)
        self.candidate.clear()
        clip = self._clips.get(self._selected_item_id or "")
        if clip is not None:
            for item in self._candidates:
                if str(getattr(item, "phrase_id", "")) == clip.source_phrase_id:
                    label = (
                        f"{getattr(item, 'operation', 'candidate')} · "
                        f"{str(getattr(item, 'candidate_id', ''))[:18]}"
                    )
                    self.candidate.addItem(label, str(item.candidate_id))
        self.candidate.blockSignals(False)

    def _move(self) -> None:
        if self._selected_kind == "phrase" and self._selected_item_id:
            self.moveRequested.emit(self._selected_item_id, self.move_to.text().strip())

    def _duplicate(self) -> None:
        if self._selected_kind == "phrase" and self._selected_item_id:
            self.duplicateRequested.emit(
                self._selected_item_id, self.duplicate_at.text().strip()
            )

    def _trim(self) -> None:
        if self._selected_kind == "phrase" and self._selected_item_id:
            self.trimRequested.emit(
                self._selected_item_id,
                self.trim_start.text().strip(),
                self.trim_end.text().strip(),
            )

    def _reorder(self, delta: int) -> None:
        if (
            self._selected_kind != "phrase"
            or self._selected_item_id is None
            or self._plan is None
        ):
            return
        ordered = list(self._plan.clips)
        index = next(
            (
                i
                for i, item in enumerate(ordered)
                if item.clip_id == self._selected_item_id
            ),
            -1,
        )
        target = index + delta
        if 0 <= target < len(ordered):
            self.reorderRequested.emit(self._selected_item_id, target)

    def _toggle_mute(self) -> None:
        clip = self._clips.get(self._selected_item_id or "")
        if clip is not None:
            self.muteRequested.emit(clip.clip_id, not clip.muted)

    def _exchange(self) -> None:
        if self._selected_kind == "phrase" and self._selected_item_id:
            self.exchangeRequested.emit(
                self._selected_item_id,
                self.layer_source.text().strip(),
                self.layer_target.text().strip(),
            )

    def _replace(self) -> None:
        candidate_id = self.candidate.currentData()
        if self._selected_kind == "phrase" and self._selected_item_id and candidate_id:
            self.replaceRequested.emit(self._selected_item_id, str(candidate_id))

    def _freeze(self) -> None:
        if self._selected_kind == "phrase" and self._selected_item_id:
            self.freezeRequested.emit(self._selected_item_id)

    def _print(self) -> None:
        if self._selected_kind == "phrase" and self._selected_item_id:
            self.printRequested.emit(self._selected_item_id)

    def _move_cue(self) -> None:
        if not self._selected_item_id:
            return
        if self._selected_kind == "transition":
            self.moveTransitionRequested.emit(
                self._selected_item_id, self.cue_start.text().strip()
            )
        elif self._selected_kind == "ending":
            self.moveEndingRequested.emit(
                self._selected_item_id, self.cue_start.text().strip()
            )

    def _refresh_controls(self) -> None:
        has_plan = self._plan is not None
        clip = self._clips.get(self._selected_item_id or "")
        is_phrase = self._selected_kind == "phrase" and clip is not None
        is_cue = self._selected_kind in {"transition", "ending"}
        frozen = bool(clip and clip.frozen)
        self.create_button.setEnabled(self._score is not None and not has_plan)
        self.undo_button.setEnabled(
            has_plan
            and bool(self._score.metadata["m33_arrangement"].get("edit_history"))
        )
        self.redo_button.setEnabled(
            has_plan
            and bool(self._score.metadata["m33_arrangement"].get("redo_history"))
        )
        self.branch_button.setEnabled(has_plan)
        self.revert_button.setEnabled(has_plan)
        self.move_button.setEnabled(is_phrase)
        self.duplicate_button.setEnabled(is_phrase)
        self.trim_button.setEnabled(is_phrase and not frozen)
        self.earlier_button.setEnabled(
            is_phrase and self._plan is not None and len(self._plan.clips) > 1
        )
        self.later_button.setEnabled(
            is_phrase and self._plan is not None and len(self._plan.clips) > 1
        )
        self.mute_button.setEnabled(is_phrase)
        self.mute_button.setText("UNMUTE" if clip and clip.muted else "MUTE")
        self.freeze_button.setEnabled(is_phrase and not frozen)
        self.print_button.setEnabled(is_phrase and not (clip and clip.muted))
        self.exchange_button.setEnabled(is_phrase and not frozen)
        self.replace_button.setEnabled(
            is_phrase and not frozen and self.candidate.count() > 0
        )
        self.move_cue_button.setEnabled(is_cue)
        self.cue_start.setEnabled(is_cue)
        is_transition = self._selected_kind == "transition"
        self.transition_source.setEnabled(is_transition)
        self.transition_target.setEnabled(is_transition)
        self.relink_button.setEnabled(
            is_transition
            and self.transition_source.count() > 0
            and self.transition_target.count() > 0
            and self.transition_source.currentData()
            != self.transition_target.currentData()
        )
        for check in self.checks.values():
            check.setEnabled(has_plan)

    def set_status(self, message: str) -> None:
        self.status.setText(str(message))

    @property
    def selected_clip_id(self) -> str | None:
        if self._selected_kind == "phrase":
            return self._selected_item_id
        return None


__all__ = ["ArrangementEditorPage"]
