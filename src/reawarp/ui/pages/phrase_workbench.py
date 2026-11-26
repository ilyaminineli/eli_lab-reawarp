"""Score-native M28 phrase workbench and contextual audition controls."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from reawarp.composition.phrases import (
    PHRASE_FUNCTIONS, PHRASE_STATES, PhrasePlan,
)
from reawarp.ui.widgets.audio_preview import AudioPreview


class PhraseWorkbenchPage(QWidget):
    """Edit phrase grammar, develop candidates and audition them in context."""

    phraseSaveRequested = Signal(dict)
    phraseDeleteRequested = Signal(str)
    batchRequested = Signal(dict)
    freezeRequested = Signal(str, str)
    branchRequested = Signal(str, str)
    restoreRequested = Signal(str)
    auditionRequested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._score: Any | None = None
        self._plan: PhrasePlan | None = None
        self._candidates: dict[str, Any] = {}
        self._selected_phrase_id: str | None = None
        self._selected_candidate_id: str | None = None
        self._busy = False
        self._loading_phrase = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        heading = QLabel("PHRASE WORKBENCH / MOTIF DEVELOPMENT")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel(
            "Work with irregular phrase spans on the Score beat clock. Generate offline "
            "alternatives from a fixed source, then listen alone or in neighbouring context. "
            "No quality score selects a winner and frozen material is never regenerated implicitly."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)

        define_group = QGroupBox("PHRASE GRAMMAR")
        define_form = QFormLayout(define_group)
        identity_row = QHBoxLayout()
        self.phrase_id = QLineEdit("phrase-01")
        self.phrase_id.setPlaceholderText("Unique phrase ID")
        self.phrase_id.setToolTip("Stable identity used by candidate and freeze lineage.")
        identity_row.addWidget(self.phrase_id, 1)
        self.function = QComboBox()
        for function in sorted(PHRASE_FUNCTIONS):
            self.function.addItem(function.replace("_", " ").upper(), function)
        self.function.addItem("CUSTOM…", "custom")
        identity_row.addWidget(self.function, 1)
        define_form.addRow("Identity / function", identity_row)

        span_row = QHBoxLayout()
        self.start_beats = QLineEdit("0")
        self.start_beats.setPlaceholderText("e.g. 0 or 3/2")
        self.start_beats.setToolTip("Exact rational start beat; for example 13/4.")
        self.end_beats = QLineEdit("8")
        self.end_beats.setPlaceholderText("e.g. 11/2")
        self.end_beats.setToolTip("Exact rational end beat, exclusive.")
        span_row.addWidget(QLabel("START"))
        span_row.addWidget(self.start_beats)
        span_row.addWidget(QLabel("END"))
        span_row.addWidget(self.end_beats)
        self.state = QComboBox()
        for state in sorted(PHRASE_STATES):
            self.state.addItem(state.upper(), state)
        span_row.addWidget(self.state)
        define_form.addRow("Rational beat span / state", span_row)

        self.custom_function = QLineEdit()
        self.custom_function.setPlaceholderText("Custom function name (optional)")
        define_form.addRow("Custom function", self.custom_function)
        self.motif_ids = QLineEdit()
        self.motif_ids.setPlaceholderText("motif-A, motif-B")
        define_form.addRow("Motif family IDs", self.motif_ids)
        self.roles = QLineEdit()
        self.roles.setPlaceholderText("lead, bass, texture")
        define_form.addRow("Roles", self.roles)

        define_actions = QHBoxLayout()
        self.save_phrase_button = QPushButton("ADD / UPDATE PHRASE")
        self.delete_phrase_button = QPushButton("DELETE PHRASE")
        self.save_phrase_button.clicked.connect(self._save_phrase)
        self.delete_phrase_button.clicked.connect(self._delete_phrase)
        define_actions.addWidget(self.save_phrase_button)
        define_actions.addWidget(self.delete_phrase_button)
        define_actions.addStretch(1)
        define_form.addRow(define_actions)
        root.addWidget(define_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        phrase_panel = QWidget()
        phrase_layout = QVBoxLayout(phrase_panel)
        phrase_layout.setContentsMargins(0, 0, 0, 0)
        phrase_layout.addWidget(QLabel("PHRASES IN SCORE"))
        self.phrases = QListWidget()
        self.phrases.currentItemChanged.connect(self._phrase_selected)
        phrase_layout.addWidget(self.phrases, 1)
        self.phrase_summary = QLabel("No phrase plan attached.")
        self.phrase_summary.setObjectName("muted")
        self.phrase_summary.setWordWrap(True)
        phrase_layout.addWidget(self.phrase_summary)
        phrase_panel.setMinimumWidth(230)
        splitter.addWidget(phrase_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        batch_group = QGroupBox("DEVELOPMENT / CANDIDATE BATCH")
        batch_form = QFormLayout(batch_group)
        batch_top = QHBoxLayout()
        self.candidate_count = QSpinBox()
        self.candidate_count.setRange(1, 16)
        self.candidate_count.setValue(4)
        self.ladder = QComboBox()
        self.ladder.addItem("SUBTLE", "subtle")
        self.ladder.addItem("MODERATE", "moderate")
        self.ladder.addItem("DISRUPTIVE", "disruptive")
        self.policy = QComboBox()
        self.policy.addItem("ONE PRINCIPAL CHANGE", "one_principal_change")
        self.policy.addItem("OPEN DEVELOPMENT", "open")
        batch_top.addWidget(QLabel("COUNT"))
        batch_top.addWidget(self.candidate_count)
        batch_top.addWidget(self.ladder)
        batch_top.addWidget(self.policy, 1)
        batch_form.addRow("Variation policy", batch_top)
        seed_row = QHBoxLayout()
        self.seed = QLineEdit("20261126")
        self.seed.setPlaceholderText("Reproducible root seed")
        self.generate_button = QPushButton("GENERATE CANDIDATES")
        self.generate_button.clicked.connect(self._request_batch)
        seed_row.addWidget(self.seed, 1)
        seed_row.addWidget(self.generate_button)
        batch_form.addRow("Root seed", seed_row)
        root_seed_note = QLabel(
            "The same seed, phrase source and request reproduce the same candidate order."
        )
        root_seed_note.setObjectName("muted")
        root_seed_note.setWordWrap(True)
        batch_form.addRow(root_seed_note)
        right_layout.addWidget(batch_group)

        candidate_splitter = QSplitter(Qt.Orientation.Horizontal)
        candidate_left = QWidget()
        candidate_left_layout = QVBoxLayout(candidate_left)
        candidate_left_layout.setContentsMargins(0, 0, 0, 0)
        candidate_left_layout.addWidget(QLabel("CANDIDATES"))
        self.candidates = QListWidget()
        self.candidates.currentItemChanged.connect(self._candidate_selected)
        candidate_left_layout.addWidget(self.candidates, 1)
        candidate_actions = QHBoxLayout()
        self.freeze_button = QPushButton("FREEZE SELECTED")
        self.branch_button = QPushButton("BRANCH FROZEN")
        self.restore_button = QPushButton("RESTORE BASE")
        self.freeze_button.clicked.connect(self._freeze)
        self.branch_button.clicked.connect(self._branch)
        self.restore_button.clicked.connect(self._restore)
        candidate_actions.addWidget(self.freeze_button)
        candidate_actions.addWidget(self.branch_button)
        candidate_actions.addWidget(self.restore_button)
        candidate_left_layout.addLayout(candidate_actions)
        candidate_left.setMinimumWidth(250)
        candidate_splitter.addWidget(candidate_left)

        candidate_details = QWidget()
        detail_layout = QVBoxLayout(candidate_details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.candidate_title = QLabel("NO CANDIDATE SELECTED")
        self.candidate_title.setObjectName("sectionTitle")
        detail_layout.addWidget(self.candidate_title)
        self.candidate_details = QLabel(
            "Select a candidate to inspect its transformation and motif invariants."
        )
        self.candidate_details.setWordWrap(True)
        self.candidate_details.setObjectName("muted")
        detail_layout.addWidget(self.candidate_details)
        self.selection_notes = QPlainTextEdit()
        self.selection_notes.setPlaceholderText(
            "Selection notes — what changed perceptually, what identity remained, "
            "and what should be retained on a later return…"
        )
        self.selection_notes.setMaximumHeight(76)
        detail_layout.addWidget(self.selection_notes)
        candidate_splitter.addWidget(candidate_details)
        candidate_splitter.setSizes([280, 460])
        right_layout.addWidget(candidate_splitter, 1)

        audition_group = QGroupBox("CONTEXTUAL AUDITION")
        audition_layout = QVBoxLayout(audition_group)
        audition_controls = QHBoxLayout()
        self.audition_target = QComboBox()
        self.audition_target.addItem("SOURCE PHRASE", "base")
        self.audition_target.addItem("SELECTED CANDIDATE", "candidate")
        self.audition_context = QComboBox()
        self.audition_context.addItem("PHRASE ALONE", "solo")
        self.audition_context.addItem("AFTER PREDECESSOR", "after_predecessor")
        self.audition_context.addItem("BEFORE SUCCESSOR", "before_successor")
        self.render_audition_button = QPushButton("RENDER & PLAY")
        self.render_audition_button.clicked.connect(self._request_audition)
        audition_controls.addWidget(self.audition_target, 1)
        audition_controls.addWidget(self.audition_context, 1)
        audition_controls.addWidget(self.render_audition_button)
        audition_layout.addLayout(audition_controls)
        self.audition_status = QLabel(
            "Audition renders only the selected phrase/context window. The project stems are not changed."
        )
        self.audition_status.setObjectName("muted")
        self.audition_status.setWordWrap(True)
        audition_layout.addWidget(self.audition_status)
        self.audition_preview = AudioPreview()
        audition_layout.addWidget(self.audition_preview, 1)
        right_layout.addWidget(audition_group, 1)

        splitter.addWidget(right)
        splitter.setSizes([280, 930])
        root.addWidget(splitter, 1)

        self._refresh_controls()

    def set_score(self, score: Any | None) -> None:
        self._score = score
        try:
            self._plan = PhrasePlan.from_score(score) if score is not None else PhrasePlan(())
        except ValueError:
            self._plan = PhrasePlan(())
        self._refresh_phrases()
        self._refresh_controls()

    def _refresh_phrases(self, selected_id: str | None = None) -> None:
        selected = selected_id or self._selected_phrase_id
        self.phrases.blockSignals(True)
        self.phrases.clear()
        freezes = (
            self._score.metadata.get("m28_phrase_freezes", {})
            if self._score is not None else {}
        )
        for phrase in self._plan.phrases if self._plan is not None else ():
            frozen = phrase.phrase_id in freezes
            state = " · FROZEN" if frozen else ""
            label = (
                f"{phrase.phrase_id}  ·  {phrase.start_beats}–{phrase.end_beats} beats"
                f"  ·  {phrase.function.upper()}{state}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, phrase.phrase_id)
            self.phrases.addItem(item)
            if phrase.phrase_id == selected:
                self.phrases.setCurrentItem(item)
        self.phrases.blockSignals(False)
        if self.phrases.currentItem() is None and self.phrases.count():
            self.phrases.setCurrentRow(0)
        if not self.phrases.count():
            self._selected_phrase_id = None
            self.phrase_summary.setText(
                "No phrases defined. Enter rational start/end beats above and add a phrase."
            )
        self._refresh_controls()

    def _phrase_selected(
        self, item: QListWidgetItem | None, _previous: QListWidgetItem | None,
    ) -> None:
        self._selected_phrase_id = (
            str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None
        )
        phrase = self._selected_phrase()
        if phrase is None:
            self.phrase_summary.setText("No phrase selected.")
            self._refresh_controls()
            return
        self._loading_phrase = True
        self.phrase_id.setText(phrase.phrase_id)
        self.start_beats.setText(str(phrase.start_beats))
        self.end_beats.setText(str(phrase.end_beats))
        index = self.function.findData(
            phrase.function if phrase.function in PHRASE_FUNCTIONS else "custom"
        )
        self.function.setCurrentIndex(max(0, index))
        self.custom_function.setText(phrase.custom_function or "")
        self.state.setCurrentIndex(max(0, self.state.findData(phrase.state)))
        self.motif_ids.setText(", ".join(phrase.motif_ids))
        self.roles.setText(", ".join(phrase.roles))
        self._loading_phrase = False
        freezes = (
            self._score.metadata.get("m28_phrase_freezes", {})
            if self._score is not None else {}
        )
        frozen = freezes.get(phrase.phrase_id)
        event_count = len(phrase.event_ids)
        self.phrase_summary.setText(
            f"{phrase.function.upper()} · {phrase.state.upper()} · "
            f"{phrase.duration_beats} beats · {event_count} event(s)"
            + (
                f"\nFROZEN · {frozen.get('candidate_id', '')}"
                if isinstance(frozen, dict) else "\nNOT FROZEN"
            )
        )
        self._candidates.clear()
        self._candidate_selected(None, None)
        self._refresh_controls()

    def _selected_phrase(self):
        if self._plan is None or not self._selected_phrase_id:
            return None
        return next(
            (item for item in self._plan.phrases if item.phrase_id == self._selected_phrase_id),
            None,
        )

    def _selected_candidate(self):
        return self._candidates.get(self._selected_candidate_id or "")

    def _save_phrase(self) -> None:
        if self._score is None:
            self.audition_status.setText("Generate or load a project before defining phrases.")
            return
        phrase_id = self.phrase_id.text().strip()
        if not phrase_id:
            self.audition_status.setText("Phrase ID cannot be empty.")
            return
        function = str(self.function.currentData() or "continuation")
        custom_function = self.custom_function.text().strip() or None
        if function == "custom":
            function = custom_function or ""
        payload = {
            "phrase_id": phrase_id,
            "start_beats": self.start_beats.text().strip(),
            "end_beats": self.end_beats.text().strip(),
            "function": function,
            "custom_function": custom_function if function not in PHRASE_FUNCTIONS else None,
            "state": str(self.state.currentData() or "closed"),
            "motif_ids": [
                item.strip() for item in self.motif_ids.text().split(",") if item.strip()
            ],
            "roles": [
                item.strip() for item in self.roles.text().split(",") if item.strip()
            ],
        }
        self.phraseSaveRequested.emit(payload)

    def _delete_phrase(self) -> None:
        if self._selected_phrase_id:
            self.phraseDeleteRequested.emit(self._selected_phrase_id)

    def _request_batch(self) -> None:
        if not self._selected_phrase_id:
            self.audition_status.setText("Select or define a phrase before generating candidates.")
            return
        payload = {
            "phrase_id": self._selected_phrase_id,
            "count": self.candidate_count.value(),
            "root_seed": self.seed.text().strip(),
            "variation_ladder": str(self.ladder.currentData()),
            "development_policy": str(self.policy.currentData()),
        }
        self.batchRequested.emit(payload)

    def set_candidates(self, candidates: list[Any], selected_id: str | None = None) -> None:
        self._candidates = {str(item.candidate_id): item for item in candidates}
        self.candidates.blockSignals(True)
        self.candidates.clear()
        for candidate in candidates:
            item = QListWidgetItem(
                f"CANDIDATE {candidate.index:02d}  ·  {candidate.operation.replace('_', ' ').upper()}"
            )
            item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
            self.candidates.addItem(item)
            if candidate.candidate_id == selected_id:
                self.candidates.setCurrentItem(item)
        self.candidates.blockSignals(False)
        if self.candidates.currentItem() is None and self.candidates.count():
            self.candidates.setCurrentRow(0)
        self._candidate_selected(self.candidates.currentItem(), None)
        self._refresh_controls()

    def _candidate_selected(
        self, item: QListWidgetItem | None, _previous: QListWidgetItem | None,
    ) -> None:
        if item is None:
            self._selected_candidate_id = None
            self.candidate_title.setText("NO CANDIDATE SELECTED")
            self.candidate_details.setText(
                "Generate a candidate batch to inspect transformation provenance."
            )
            self._refresh_controls()
            return
        candidate_id = str(item.data(Qt.ItemDataRole.UserRole))
        self._selected_candidate_id = candidate_id
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            return
        change = ", ".join(candidate.transformation.changed_dimensions) or "none"
        preserved = ", ".join(candidate.transformation.preserved_dimensions)
        self.candidate_title.setText(f"CANDIDATE {candidate.index:02d} · {candidate.operation.upper()}")
        self.candidate_details.setText(
            f"CHANGED  ·  {change}\nPRESERVED  ·  {preserved}\n"
            f"SEED  ·  {candidate.seed} ({candidate.seed_name})\n"
            f"BASE  ·  {candidate.base_phrase_fingerprint[:16]}…"
        )
        self._refresh_controls()

    def _freeze(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            return
        self.freezeRequested.emit(
            candidate.candidate_id, self.selection_notes.toPlainText()
        )

    def _branch(self) -> None:
        if not self._selected_phrase_id:
            return
        self.branchRequested.emit(
            self._selected_phrase_id, self.seed.text().strip()
        )

    def _restore(self) -> None:
        if self._selected_phrase_id:
            self.restoreRequested.emit(self._selected_phrase_id)

    def _request_audition(self) -> None:
        if self._score is None or not self._selected_phrase_id:
            self.audition_status.setText("Select a phrase and load a project first.")
            return
        target = str(self.audition_target.currentData())
        if target == "candidate" and self._selected_candidate() is None:
            self.audition_status.setText("Select a candidate before candidate audition.")
            return
        self.auditionRequested.emit(
            target, str(self.audition_context.currentData())
        )

    def set_audition_busy(self, busy: bool, message: str = "") -> None:
        self._busy = bool(busy)
        self.render_audition_button.setEnabled(not busy)
        if message:
            self.audition_status.setText(message)
        self._refresh_controls()

    def set_audition_audio(
        self, audio: Any | None, sample_rate: int, *, message: str = "",
    ) -> None:
        self.audition_preview.set_audio(audio, sample_rate)
        if message:
            self.audition_status.setText(message)

    def set_batch_busy(self, busy: bool) -> None:
        self.generate_button.setEnabled(not busy)
        if busy:
            self.generate_button.setText("GENERATING…")
        else:
            self.generate_button.setText("GENERATE CANDIDATES")
        self._refresh_controls()

    def set_error(self, message: str) -> None:
        self.audition_status.setText(message)

    def _refresh_controls(self) -> None:
        has_score = self._score is not None
        has_phrase = self._selected_phrase() is not None
        candidate = self._selected_candidate()
        freezes = (
            self._score.metadata.get("m28_phrase_freezes", {})
            if self._score is not None else {}
        )
        frozen = bool(
            self._selected_phrase_id and self._selected_phrase_id in freezes
        )
        self.save_phrase_button.setEnabled(has_score)
        self.delete_phrase_button.setEnabled(has_phrase and not frozen)
        self.generate_button.setEnabled(has_phrase and not frozen and not self._busy)
        self.freeze_button.setEnabled(candidate is not None and not frozen and not self._busy)
        self.branch_button.setEnabled(frozen and not self._busy)
        self.restore_button.setEnabled(frozen and not self._busy)
        self.render_audition_button.setEnabled(
            has_phrase and not self._busy
        )

    @property
    def selected_phrase_id(self) -> str | None:
        return self._selected_phrase_id

    @property
    def selected_candidate_id(self) -> str | None:
        return self._selected_candidate_id

    @property
    def candidates(self) -> dict[str, Any]:
        return dict(self._candidates)

    def closeEvent(self, event) -> None:
        self.audition_preview.set_audio(None)
        super().closeEvent(event)


__all__ = ["PhraseWorkbenchPage"]
