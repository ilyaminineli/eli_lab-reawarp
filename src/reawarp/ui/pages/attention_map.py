"""Score-native M29 figure/ground attention map workspace."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from reawarp.score.attention import (
    attention_conflict_id,
    estimate_attention_descriptors,
)
from reawarp.score.orchestration_intent import (
    ATTENTION_DEPTHS,
    ATTENTION_ROLES,
    AttentionSpan,
    OrchestrationPlan,
    inspect_attention_conflicts,
    inspect_attention_handoffs,
    inspect_event_onset_conflicts,
)
from reawarp.ui.widgets.audio_preview import AudioPreview


class AttentionMapPage(QWidget):
    """Author arrangement attention intent and inspect possible perceptual conflicts."""

    planChanged = Signal(dict)
    reviewRequested = Signal(dict)
    translationCheckRequested = Signal(str)
    gestureRequested = Signal(dict)
    gestureRemoveRequested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._score: Any | None = None
        self._plan = OrchestrationPlan()
        self._selected_span_index: int | None = None
        self._diagnostics: dict[str, dict[str, Any]] = {}
        self._reviews: dict[str, dict[str, Any]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        heading = QLabel("ATTENTION MAP / FIGURE · GROUND · HAND-OFF")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        intro = QLabel(
            "Describe what the listener should follow, what supports it, and where attention "
            "moves. Descriptors are inspectable prompts—not mix rules or artistic scores. "
            "FOCUS and RECEDE add reversible Score gestures and rerender event-backed voices; "
            "they do not automate the master fader."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        span_group = QGroupBox("ARRANGEMENT ATTENTION SPANS")
        span_layout = QVBoxLayout(span_group)
        self.spans = QListWidget()
        self.spans.currentItemChanged.connect(self._span_selected)
        span_layout.addWidget(self.spans, 1)

        span_form_group = QGroupBox("SPAN / ROLE INTENT")
        form = QFormLayout(span_form_group)
        self.role = QComboBox()
        self.role.setEditable(True)
        self.role.setToolTip(
            "Score voice or orchestral role, for example melody, kick or texture."
        )
        form.addRow("Sound role", self.role)

        time_row = QHBoxLayout()
        self.start_beats = QLineEdit("0")
        self.start_beats.setPlaceholderText("0 or 3/2")
        self.end_beats = QLineEdit("8")
        self.end_beats.setPlaceholderText("exclusive end beat")
        time_row.addWidget(self.start_beats)
        time_row.addWidget(QLabel("→"))
        time_row.addWidget(self.end_beats)
        form.addRow("Exact beat range", time_row)

        self.depth = QComboBox()
        for value in sorted(ATTENTION_DEPTHS):
            self.depth.addItem(value.replace("_", " ").upper(), value)
        form.addRow("Figure / ground depth", self.depth)

        self.attention_role = QComboBox()
        for value in sorted(ATTENTION_ROLES):
            self.attention_role.addItem(value.replace("_", " ").upper(), value)
        form.addRow("Semantic orchestral role", self.attention_role)

        self.handoff_id = QLineEdit()
        self.handoff_id.setPlaceholderText("Shared ID on both sides of a hand-off")
        form.addRow("Atomic hand-off ID", self.handoff_id)
        self.intentional_overlap_id = QLineEdit()
        self.intentional_overlap_id.setPlaceholderText(
            "Shared ID to mark an intentional merge"
        )
        form.addRow("Intentional merge ID", self.intentional_overlap_id)

        self.register_low = QLineEdit()
        self.register_low.setPlaceholderText("e.g. 36")
        self.register_high = QLineEdit()
        self.register_high.setPlaceholderText("e.g. 72")
        register_row = QHBoxLayout()
        register_row.addWidget(self.register_low)
        register_row.addWidget(QLabel("to"))
        register_row.addWidget(self.register_high)
        form.addRow("Register / pitch coordinates", register_row)

        self.spectral_band = QLineEdit()
        self.spectral_band.setPlaceholderText("sub-low, low-mid, mid, high, broadband…")
        form.addRow("Spectral zone", self.spectral_band)

        self.onset_density = QLineEdit()
        self.onset_density.setPlaceholderText("events per beat")
        self.transient_strength = QLineEdit()
        self.transient_strength.setPlaceholderText("0–1 velocity proxy")
        self.sustain = QLineEdit()
        self.sustain.setPlaceholderText("0–1 occupancy proxy")
        self.spatial_position = QLineEdit()
        self.spatial_position.setPlaceholderText("-1 left · 0 centre · +1 right")
        self.prominence = QLineEdit()
        self.prominence.setPlaceholderText("0–1 intended prominence")
        self.register_shift = QLineEdit("0")
        self.register_shift.setPlaceholderText("-24..+24 semitones")
        for label, field in (
            ("Onset density", self.onset_density),
            ("Transient strength", self.transient_strength),
            ("Sustain", self.sustain),
            ("Spatial position", self.spatial_position),
            ("Intended prominence", self.prominence),
            ("Render register shift / semitones", self.register_shift),
        ):
            form.addRow(label, field)

        actions = QHBoxLayout()
        self.save_span_button = QPushButton("ADD / UPDATE")
        self.delete_span_button = QPushButton("DELETE")
        self.focus_button = QPushButton("FOCUS + RENDER")
        self.recede_button = QPushButton("RECEDE + RENDER")
        self.reset_gesture_button = QPushButton("RESET RENDER GESTURE")
        self.save_span_button.clicked.connect(self._save_span)
        self.delete_span_button.clicked.connect(self._delete_span)
        self.focus_button.clicked.connect(self._set_focus)
        self.recede_button.clicked.connect(self._set_recede)
        self.reset_gesture_button.clicked.connect(self._reset_render_gesture)
        for button in (
            self.save_span_button,
            self.delete_span_button,
            self.focus_button,
            self.recede_button,
            self.reset_gesture_button,
        ):
            actions.addWidget(button)
        form.addRow(actions)
        span_layout.addWidget(span_form_group)

        self.estimate_button = QPushButton(
            "ESTIMATE MISSING DESCRIPTORS FROM SCORE EVENTS"
        )
        self.estimate_button.clicked.connect(self._estimate_descriptors)
        span_layout.addWidget(self.estimate_button)
        self.span_status = QLabel(
            "Load a composition to inspect and edit its Score attention map."
        )
        self.span_status.setObjectName("muted")
        self.span_status.setWordWrap(True)
        span_layout.addWidget(self.span_status)
        left_layout.addWidget(span_group, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        diagnostic_group = QGroupBox("MASKING / FIGURE-GROUND INSPECTOR")
        diagnostic_layout = QVBoxLayout(diagnostic_group)
        self.handoff_status = QLabel("No attention hand-offs.")
        self.handoff_status.setWordWrap(True)
        self.handoff_status.setObjectName("muted")
        diagnostic_layout.addWidget(self.handoff_status)
        self.diagnostics = QListWidget()
        self.diagnostics.currentItemChanged.connect(self._diagnostic_selected)
        diagnostic_layout.addWidget(self.diagnostics, 1)
        review_row = QHBoxLayout()
        self.review_disposition = QComboBox()
        for label, value in (
            ("USEFUL / INTENTIONAL", "useful"),
            ("MASKED", "masked"),
            ("UNRESOLVED", "unresolved"),
        ):
            self.review_disposition.addItem(label, value)
        self.review_button = QPushButton("RECORD HUMAN REVIEW")
        self.review_button.clicked.connect(self._record_review)
        review_row.addWidget(self.review_disposition, 1)
        review_row.addWidget(self.review_button)
        diagnostic_layout.addLayout(review_row)
        self.review_notes = QPlainTextEdit()
        self.review_notes.setPlaceholderText(
            "Why is this overlap useful, masked, or unresolved? Record listening context and intent."
        )
        self.review_notes.setMaximumHeight(72)
        diagnostic_layout.addWidget(self.review_notes)
        self.diagnostic_status = QLabel(
            "Warnings appear only when temporal overlap coincides with declared register, "
            "spectral, transient, density, sustain or stereo evidence."
        )
        self.diagnostic_status.setWordWrap(True)
        self.diagnostic_status.setObjectName("muted")
        diagnostic_layout.addWidget(self.diagnostic_status)
        right_layout.addWidget(diagnostic_group, 2)

        translation_group = QGroupBox("PLAYBACK TRANSLATION CHECKS")
        translation_layout = QVBoxLayout(translation_group)
        translation_intro = QLabel(
            "Create disposable audition copies of the current master. The original stems, "
            "mix, routing and project archive remain unchanged."
        )
        translation_intro.setWordWrap(True)
        translation_intro.setObjectName("muted")
        translation_layout.addWidget(translation_intro)
        translation_actions = QHBoxLayout()
        self.mono_button = QPushButton("PLAY MONO FOLD-DOWN")
        self.low_volume_button = QPushButton("PLAY −20 dB CHECK")
        self.mono_button.clicked.connect(
            lambda: self.translationCheckRequested.emit("mono")
        )
        self.low_volume_button.clicked.connect(
            lambda: self.translationCheckRequested.emit("low_volume")
        )
        translation_actions.addWidget(self.mono_button)
        translation_actions.addWidget(self.low_volume_button)
        translation_layout.addLayout(translation_actions)
        self.translation_status = QLabel("No translation check rendered.")
        self.translation_status.setObjectName("muted")
        self.translation_status.setWordWrap(True)
        translation_layout.addWidget(self.translation_status)
        self.translation_preview = AudioPreview()
        translation_layout.addWidget(self.translation_preview, 1)
        right_layout.addWidget(translation_group, 1)
        splitter.addWidget(right)
        splitter.setSizes([520, 720])
        root.addWidget(splitter, 1)

        self._refresh_controls()

    @staticmethod
    def _optional_number(field: QLineEdit, name: str) -> float | None:
        raw = field.text().strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number or blank") from exc

    @staticmethod
    def _format_optional(value: float | None) -> str:
        return "" if value is None else f"{value:g}"

    def set_score(self, score: Any | None) -> None:
        self._score = score
        self._selected_span_index = None
        self.spans.blockSignals(True)
        self.spans.clear()
        if score is None:
            self._plan = OrchestrationPlan()
            self._reviews = {}
            self._refresh_diagnostics()
            self._refresh_controls()
            return
        raw_plan = score.orchestration_plan or score.metadata.get(
            "perceptual_orchestration"
        )
        try:
            self._plan = (
                OrchestrationPlan.from_dict(raw_plan)
                if raw_plan
                else OrchestrationPlan()
            )
        except (TypeError, ValueError, KeyError):
            self._plan = OrchestrationPlan()
            self.span_status.setText(
                "The project's orchestration plan could not be parsed; an empty view is shown."
            )
        self._reviews = dict(score.metadata.get("m29_attention_reviews", {}))
        roles = {
            str(event.voice_id)
            for event in score.events
            if getattr(event, "kind", None) not in {"marker", "control"}
        }
        roles.update(span.role for span in self._plan.attention)
        roles.update(str(name) for name in score.metadata.get("render_stems", ()))
        current_role = self.role.currentText()
        self.role.blockSignals(True)
        self.role.clear()
        for role in sorted(roles):
            self.role.addItem(role, role)
        if not roles:
            self.role.addItem("melody", "melody")
        if current_role:
            self.role.setCurrentText(current_role)
        self.role.blockSignals(False)
        self._refresh_span_list()
        self.spans.blockSignals(False)
        self._refresh_diagnostics()
        self._refresh_controls()

    def _refresh_span_list(self, selected: int | None = None) -> None:
        index = self._selected_span_index if selected is None else selected
        self.spans.blockSignals(True)
        self.spans.clear()
        for number, span in enumerate(self._plan.attention):
            label = (
                f"{span.role.upper()} · {span.depth.upper()} · "
                f"{span.attention_role.replace('_', ' ').upper()} · "
                f"{span.start_beats}–{span.end_beats}"
            )
            if span.handoff_id:
                label += f" · HANDOFF {span.handoff_id}"
            if span.intentional_overlap_id:
                label += f" · MERGE {span.intentional_overlap_id}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, number)
            self.spans.addItem(item)
        if index is not None and 0 <= index < self.spans.count():
            self.spans.setCurrentRow(index)
        self.spans.blockSignals(False)
        self._selected_span_index = (
            int(self.spans.currentItem().data(Qt.ItemDataRole.UserRole))
            if self.spans.currentItem() is not None
            else None
        )
        self._load_selected_span()

    def _load_selected_span(self) -> None:
        span = self._selected_span()
        if span is None:
            self.start_beats.setText("0")
            self.end_beats.setText("8")
            for field in (
                self.register_low,
                self.register_high,
                self.onset_density,
                self.transient_strength,
                self.sustain,
                self.spatial_position,
                self.prominence,
                self.spectral_band,
                self.handoff_id,
                self.intentional_overlap_id,
                self.register_shift,
            ):
                field.clear()
            self._refresh_controls()
            return
        self.role.setCurrentText(span.role)
        self.start_beats.setText(str(span.start_beats))
        self.end_beats.setText(str(span.end_beats))
        self.depth.setCurrentIndex(max(0, self.depth.findData(span.depth)))
        self.attention_role.setCurrentIndex(
            max(0, self.attention_role.findData(span.attention_role))
        )
        self.handoff_id.setText(span.handoff_id or "")
        self.intentional_overlap_id.setText(span.intentional_overlap_id or "")
        self.register_low.setText(self._format_optional(span.register_low))
        self.register_high.setText(self._format_optional(span.register_high))
        self.spectral_band.setText(span.spectral_band or "")
        self.onset_density.setText(self._format_optional(span.onset_density))
        self.transient_strength.setText(self._format_optional(span.transient_strength))
        self.sustain.setText(self._format_optional(span.sustain))
        self.spatial_position.setText(self._format_optional(span.spatial_position))
        self.prominence.setText(self._format_optional(span.prominence))
        self._refresh_controls()

    def _span_selected(
        self, item: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._selected_span_index = (
            int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None
        )
        self._load_selected_span()

    def _selected_span(self) -> AttentionSpan | None:
        if self._selected_span_index is None:
            return None
        if not 0 <= self._selected_span_index < len(self._plan.attention):
            return None
        return self._plan.attention[self._selected_span_index]

    def _emit_plan(
        self, spans: tuple[AttentionSpan, ...], message: str, selected: int | None
    ) -> None:
        try:
            updated = replace(self._plan, attention=spans)
        except ValueError as exc:
            self.span_status.setText(f"Attention map rejected: {exc}")
            return
        self._plan = updated
        self._selected_span_index = selected
        self.planChanged.emit(updated.to_dict())
        self._refresh_span_list(selected)
        self._refresh_diagnostics()
        self.span_status.setText(message)
        self._refresh_controls()

    def _save_span(self) -> None:
        try:
            from reawarp.score.time import as_fraction

            span = AttentionSpan(
                role=self.role.currentText().strip(),
                start_beats=as_fraction(self.start_beats.text().strip()),
                end_beats=as_fraction(self.end_beats.text().strip()),
                depth=str(self.depth.currentData()),
                handoff_id=self.handoff_id.text().strip() or None,
                register_low=self._optional_number(self.register_low, "register low"),
                register_high=self._optional_number(
                    self.register_high, "register high"
                ),
                spectral_band=self.spectral_band.text().strip() or None,
                attention_role=str(self.attention_role.currentData()),
                onset_density=self._optional_number(
                    self.onset_density, "onset density"
                ),
                transient_strength=self._optional_number(
                    self.transient_strength, "transient strength"
                ),
                sustain=self._optional_number(self.sustain, "sustain"),
                spatial_position=self._optional_number(
                    self.spatial_position, "spatial position"
                ),
                prominence=self._optional_number(self.prominence, "prominence"),
                intentional_overlap_id=self.intentional_overlap_id.text().strip()
                or None,
            )
        except (ValueError, ZeroDivisionError) as exc:
            self.span_status.setText(f"Invalid attention span: {exc}")
            return
        spans = list(self._plan.attention)
        selected = self._selected_span_index
        if selected is None:
            spans.append(span)
            selected = len(spans) - 1
            message = f"Added {span.role} · {span.depth} · {span.start_beats}–{span.end_beats} beats."
        else:
            spans[selected] = span
            message = f"Updated {span.role} · {span.depth} · {span.start_beats}–{span.end_beats} beats."
        self._emit_plan(tuple(spans), message, selected)

    def _delete_span(self) -> None:
        selected = self._selected_span()
        if selected is None:
            return
        removed = {self._selected_span_index}
        if selected.handoff_id:
            removed.update(
                index
                for index, span in enumerate(self._plan.attention)
                if span.handoff_id == selected.handoff_id
            )
        spans = tuple(
            span
            for index, span in enumerate(self._plan.attention)
            if index not in removed
        )
        self._emit_plan(
            spans,
            "Deleted selected attention span and its paired hand-off side, if present.",
            None,
        )

    def _set_focus(self) -> None:
        self._set_depth_operation("foreground")

    def _set_recede(self) -> None:
        self._set_depth_operation("background")

    def _set_depth_operation(self, depth: str) -> None:
        selected = self._selected_span()
        if selected is None:
            return
        prominence = selected.prominence
        if depth == "foreground":
            prominence = min(
                1.0, (prominence if prominence is not None else 0.70) + 0.15
            )
        else:
            prominence = max(
                0.0, (prominence if prominence is not None else 0.50) - 0.15
            )
        spans = list(self._plan.attention)
        spans[self._selected_span_index] = replace(
            selected,
            depth=depth,
            reserved_silence=False,
            prominence=prominence,
        )
        try:
            register_shift = self._optional_number(
                self.register_shift, "register shift"
            )
        except ValueError as exc:
            self.span_status.setText(f"Invalid render gesture: {exc}")
            return
        register_shift = 0.0 if register_shift is None else register_shift
        if not -24.0 <= register_shift <= 24.0:
            self.span_status.setText(
                "Register shift must be between -24 and +24 semitones."
            )
            return
        self._emit_plan(
            tuple(spans),
            f"{selected.role} assigned to {depth}; render gesture queued for its exact beat span.",
            self._selected_span_index,
        )
        self.gestureRequested.emit(
            {
                "role": selected.role,
                "start_beats": str(selected.start_beats),
                "end_beats": str(selected.end_beats),
                "action": "focus" if depth == "foreground" else "recede",
                "register_shift_semitones": register_shift,
            }
        )

    def _reset_render_gesture(self) -> None:
        selected = self._selected_span()
        if selected is None:
            return
        self.gestureRemoveRequested.emit(
            {
                "role": selected.role,
                "start_beats": str(selected.start_beats),
                "end_beats": str(selected.end_beats),
            }
        )

    def _estimate_descriptors(self) -> None:
        if self._score is None:
            self.span_status.setText("Load a Score before estimating descriptors.")
            return
        spans = estimate_attention_descriptors(
            self._score.events, self._plan.attention, fill_missing=True
        )
        self._emit_plan(
            spans,
            "Filled missing descriptors from symbolic Score events; these are not audio measurements.",
            self._selected_span_index,
        )

    def _refresh_diagnostics(self) -> None:
        self.diagnostics.blockSignals(True)
        self.diagnostics.clear()
        self._diagnostics = {}
        handoffs = inspect_attention_handoffs(self._plan)
        atomic = sum(item.get("valid", False) for item in handoffs)
        invalid = [item for item in handoffs if not item.get("valid", False)]
        self.handoff_status.setText(
            f"{atomic} atomic hand-off(s) · {len(invalid)} incomplete/non-atomic hand-off(s). "
            + (
                "Unpaired IDs need a matching opposite side at the same beat boundary."
                if invalid
                else "Hand-offs use exact rational-beat boundaries."
            )
        )
        warnings = list(inspect_attention_conflicts(self._plan))
        if self._score is not None:
            warnings.extend(inspect_event_onset_conflicts(self._score.events))
        for warning in warnings:
            warning_id = attention_conflict_id(warning)
            roles = " + ".join(warning.get("roles", ()))
            if warning.get("kind") == "onset_overlap":
                where = f"beat {warning.get('onset_beats')}"
                evidence = "simultaneous event onsets"
            else:
                where = f"beats {warning.get('start_beats')}–{warning.get('end_beats')}"
                evidence = "; ".join(warning.get("evidence", ()))
            item = QListWidgetItem(f"{roles} · {where} · {evidence}")
            item.setData(Qt.ItemDataRole.UserRole, warning_id)
            self.diagnostics.addItem(item)
            self._diagnostics[warning_id] = warning
        self.diagnostics.blockSignals(False)
        if self.diagnostics.count():
            self.diagnostics.setCurrentRow(0)
        else:
            self._diagnostic_selected(None, None)
        self.diagnostic_status.setText(
            f"{len(warnings)} diagnostic prompt(s) · heuristic descriptors only · "
            "no single clarity score or automatic EQ recommendation."
        )

    def _diagnostic_selected(
        self,
        item: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        warning_id = (
            str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None
        )
        review = self._reviews.get(warning_id or "", {})
        state = str(review.get("disposition", "unresolved"))
        index = self.review_disposition.findData(state)
        self.review_disposition.setCurrentIndex(max(0, index))
        self.review_notes.setPlainText(str(review.get("notes", "")))
        self.review_button.setEnabled(item is not None)

    def _record_review(self) -> None:
        item = self.diagnostics.currentItem()
        if item is None:
            self.diagnostic_status.setText(
                "Select a diagnostic before recording a review."
            )
            return
        warning_id = str(item.data(Qt.ItemDataRole.UserRole))
        warning = self._diagnostics.get(warning_id)
        if warning is None:
            return
        self.reviewRequested.emit(
            {
                "warning": warning,
                "disposition": str(self.review_disposition.currentData()),
                "notes": self.review_notes.toPlainText(),
            }
        )

    def set_review_records(self, reviews: dict[str, Any]) -> None:
        self._reviews = dict(reviews)
        self._diagnostic_selected(self.diagnostics.currentItem(), None)

    def set_translation_audio(self, audio: Any, sample_rate: int, message: str) -> None:
        self.translation_preview.set_audio(audio, sample_rate)
        self.translation_status.setText(message)

    def set_error(self, message: str) -> None:
        self.span_status.setText(message)
        self.diagnostic_status.setText(message)
        self.translation_status.setText(message)

    def _refresh_controls(self) -> None:
        loaded = self._score is not None
        has_span = self._selected_span() is not None
        self.save_span_button.setEnabled(loaded)
        self.delete_span_button.setEnabled(loaded and has_span)
        self.focus_button.setEnabled(loaded and has_span)
        self.recede_button.setEnabled(loaded and has_span)
        self.reset_gesture_button.setEnabled(loaded and has_span)
        self.estimate_button.setEnabled(loaded and bool(self._plan.attention))
        self.mono_button.setEnabled(loaded)
        self.low_volume_button.setEnabled(loaded)

    def closeEvent(self, event) -> None:
        self.translation_preview.set_audio(None)
        super().closeEvent(event)


__all__ = ["AttentionMapPage"]
