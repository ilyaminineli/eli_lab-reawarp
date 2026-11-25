"""M18 score-control editor for deterministic musical automation."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
import math
from typing import Any

import numpy as np

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from reawarp.fx_automation import automation_targets
from reawarp.score.automation import AutomationModulation, AutomationSource
from reawarp.score.model import Score


_TARGETS = (
    ("synth.cutoff", "Filter cutoff · Hz"),
    ("synth.resonance", "Filter resonance"),
    ("synth.gain", "Voice gain"),
    ("synth.pitch", "Pitch offset · semitones"),
    ("synth.attack", "Attack · seconds"),
    ("synth.decay", "Decay · seconds"),
    ("synth.release", "Release · seconds"),
    ("synth.modulation.depth", "Vibrato depth · normalized"),
    ("synth.modulation.rate", "Vibrato rate · Hz"),
    ("synth.wavetable.position", "Wavetable position"),
    ("synth.partial.balance", "Partial balance"),
    ("synth.grain.size", "Grain size · ms"),
    ("synth.grain.position", "Grain phase position"),
    ("synth.grain.density", "Grain density · Hz"),
    ("event.velocity_scale", "Event velocity scale"),
    ("event.probability", "Event probability"),
    ("role.activity", "Role activity"),
    ("role.density", "Role density · normalized"),
    ("role.syncopation", "Role syncopation"),
    ("role.articulation", "Role articulation · 0–4"),
    ("sample.mix", "Sample contribution"),
    ("spatial.pan", "Stereo pan"),
    ("spatial.width", "Stereo width"),
)

_TARGET_AMOUNTS = {
    "synth.cutoff": 1_200.0,
    "synth.resonance": 0.2,
    "synth.gain": 0.2,
    "synth.pitch": 2.0,
    "synth.attack": 0.03,
    "synth.decay": 0.20,
    "synth.release": 0.12,
    "synth.modulation.depth": 0.25,
    "synth.modulation.rate": 2.0,
    "synth.wavetable.position": 0.25,
    "synth.partial.balance": 0.25,
    "synth.grain.size": 60.0,
    "synth.grain.position": 0.25,
    "synth.grain.density": 30.0,
    "role.density": 0.5,
    "role.syncopation": 0.5,
    "role.articulation": 2.0,
    "event.velocity_scale": 0.25,
    "event.probability": 0.25,
    "role.activity": 0.25,
    "sample.mix": 0.2,
    "spatial.pan": 0.25,
    "spatial.width": 0.25,
}

_TARGET_BASE_VALUES = {
    "synth.cutoff": 2_400.0,
    "synth.attack": 0.02,
    "synth.decay": 0.24,
    "synth.release": 0.18,
    "synth.modulation.depth": 0.5,
    "synth.modulation.rate": 6.0,
    "synth.wavetable.position": 0.5,
    "synth.partial.balance": 0.5,
    "synth.grain.size": 80.0,
    "synth.grain.position": 0.5,
    "synth.grain.density": 50.0,
    "role.activity": 0.5,
    "role.density": 0.5,
    "role.syncopation": 0.5,
    "role.articulation": 2.0,
    "event.velocity_scale": 1.0,
    "event.probability": 0.5,
    "sample.mix": 0.5,
    "spatial.pan": 0.0,
    "spatial.width": 1.0,
    "synth.gain": 0.75,
}

_TARGET_RANGES = {
    "synth.cutoff": (20.0, 18_000.0),
    "synth.resonance": (0.0, 1.0),
    "synth.gain": (0.0, 1.0),
    "synth.pitch": (-48.0, 48.0),
    "synth.attack": (0.001, 2.0),
    "synth.decay": (0.01, 4.0),
    "synth.release": (0.02, 0.65),
    "synth.modulation.depth": (0.0, 1.0),
    "synth.modulation.rate": (0.0, 40.0),
    "synth.wavetable.position": (0.0, 1.0),
    "synth.partial.balance": (0.0, 1.0),
    "synth.grain.size": (1.0, 500.0),
    "synth.grain.position": (0.0, 1.0),
    "synth.grain.density": (0.0, 200.0),
    "role.density": (0.0, 1.0),
    "role.syncopation": (0.0, 1.0),
    "role.articulation": (0.0, 4.0),
    "event.velocity_scale": (0.0, 2.0),
    "event.probability": (0.0, 1.0),
    "role.activity": (0.0, 1.0),
    "sample.mix": (0.0, 1.0),
    "spatial.pan": (-1.0, 1.0),
    "spatial.width": (0.0, 2.0),
}


class AutomationCurvePreview(QWidget):
    """Compact curve editor with draggable normalized control points."""

    valuesChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(104)
        self.setMaximumHeight(136)
        self._values: tuple[float, ...] = ()
        self._editable = False
        self._drag_index: int | None = None

    def set_values(
        self,
        values: list[float] | tuple[float, ...],
        *,
        editable: bool = False,
    ) -> None:
        self._values = tuple(float(value) for value in values)
        self._editable = bool(editable)
        self._drag_index = None
        self.setToolTip(
            "Drag points vertically to edit this curve."
            if self._editable else "Generated automation curve preview."
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = self.rect().adjusted(8, 8, -8, -8)
        painter.fillRect(self.rect(), QColor("#0d1015"))
        painter.setPen(QPen(QColor("#252b35"), 1))
        for index in range(5):
            y = bounds.top() + bounds.height() * index / 4.0
            painter.drawLine(bounds.left(), int(y), bounds.right(), int(y))
        for index in range(9):
            x = bounds.left() + bounds.width() * index / 8.0
            painter.drawLine(int(x), bounds.top(), int(x), bounds.bottom())
        if len(self._values) < 2:
            painter.setPen(QColor("#818894"))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "ADD A SOURCE TO PREVIEW ITS SHAPE")
            painter.end()
            return
        low = 0.0 if self._editable else min(self._values)
        high = 1.0 if self._editable else max(self._values)
        span = max(1e-9, high - low)
        path = QPainterPath()
        points = []
        for index, value in enumerate(self._values):
            x = bounds.left() + bounds.width() * index / (len(self._values) - 1)
            y = bounds.bottom() - bounds.height() * (value - low) / span
            points.append(QPointF(x, y))
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor("#9b9cf6"), 2.0))
        painter.drawPath(path)
        if self._editable:
            painter.setPen(QPen(QColor("#d8d8ff"), 1.0))
            painter.setBrush(QColor("#9b9cf6"))
            for point in points:
                painter.drawEllipse(point, 4.0, 4.0)
        painter.setPen(QColor("#818894"))
        painter.drawText(bounds.adjusted(3, 2, -3, -2), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, f"{high:.3g}")
        painter.drawText(bounds.adjusted(3, 2, -3, -2), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, f"{low:.3g}")
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._editable or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        bounds = self.rect().adjusted(8, 8, -8, -8)
        if len(self._values) < 2 or bounds.width() <= 0 or bounds.height() <= 0:
            return
        x = float(event.position().x())
        positions = [
            bounds.left() + bounds.width() * index / (len(self._values) - 1)
            for index in range(len(self._values))
        ]
        nearest = min(range(len(positions)), key=lambda index: abs(positions[index] - x))
        if abs(positions[nearest] - x) <= 14.0:
            self._drag_index = nearest
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_index is None or not self._editable:
            return super().mouseMoveEvent(event)
        bounds = self.rect().adjusted(8, 8, -8, -8)
        if bounds.height() <= 0:
            return
        position = (bounds.bottom() - float(event.position().y())) / bounds.height()
        values = list(self._values)
        values[self._drag_index] = float(np.clip(position, 0.0, 1.0))
        self._values = tuple(values)
        self.valuesChanged.emit(list(self._values))
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._drag_index = None
        super().mouseReleaseEvent(event)


class ScoreAutomationEditor(QGroupBox):
    """Edit deterministic source-to-target relationships attached to a Score."""

    applyRequested = Signal()
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("M18 · SCORE CONTROL", parent)
        self._score: Score | None = None
        self._sources: list[AutomationSource] = []
        self._modulations: list[AutomationModulation] = []
        self._counter = 0

        root = QVBoxLayout(self)
        intro = QLabel(
            "Create beat-addressed control motion, connect it to a typed destination, "
            "and scope it to a role, section, or event. Applying controls re-renders "
            "Score-driven voices; texture and ambience field layers remain unchanged."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        form = QFormLayout()
        self._target_ranges = dict(_TARGET_RANGES)
        self.target = QComboBox()
        for target_id, label in _TARGETS:
            self.target.addItem(label, target_id)
        self.target.setCurrentIndex(0)
        self.target.currentIndexChanged.connect(self._target_changed)
        form.addRow("Destination", self.target)

        self.source_kind = QComboBox()
        self.source_kind.addItem("SINE LFO", "lfo")
        self.source_kind.addItem("ENVELOPE", "envelope")
        self.source_kind.addItem("STEPPED", "stepped")
        self.source_kind.addItem("BOUNDED RANDOM WALK", "random_walk")
        self.source_kind.addItem("PHRASE CURVE", "phrase_curve")
        self.source_kind.currentIndexChanged.connect(self._source_kind_changed)
        form.addRow("Source shape", self.source_kind)

        self.lfo_waveform = QComboBox()
        for value, label in (
            ("sine", "SINE"),
            ("triangle", "TRIANGLE"),
            ("square", "SQUARE"),
            ("saw", "SAW"),
        ):
            self.lfo_waveform.addItem(label, value)
        form.addRow("LFO waveform", self.lfo_waveform)

        self.source_values = QLineEdit("0.0, 1.0, 0.0")
        self.source_values.setPlaceholderText("Comma-separated values from 0 to 1")
        self.source_values.textChanged.connect(self._draft_source_preview_changed)
        form.addRow("Curve / step values", self.source_values)

        self.random_step_size = self._number(0.001, 1.0, 0.12, 3)
        self.random_initial = self._number(0.0, 1.0, 0.5, 3)
        form.addRow("Random-walk step size", self.random_step_size)
        form.addRow("Random-walk initial value", self.random_initial)

        self.scope = QComboBox()
        for value, label in (
            ("global", "GLOBAL"),
            ("role", "ROLE"),
            ("section", "SECTION"),
            ("event", "EVENT"),
        ):
            self.scope.addItem(label, value)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        form.addRow("Scope", self.scope)
        self.scope_id = QComboBox()
        self.scope_id.setEditable(True)
        self.scope_id.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.scope_id.lineEdit().setPlaceholderText(
            "Select a Score ID or type an exact custom ID"
        )
        form.addRow("Scope ID", self.scope_id)

        self.retrigger = QComboBox()
        for value, label in (
            ("free", "FREE RUNNING"),
            ("event", "RETRIGGER PER EVENT"),
            ("role", "RETRIGGER PER ROLE"),
            ("section", "RETRIGGER PER SECTION"),
        ):
            self.retrigger.addItem(label, value)
        form.addRow("Phase", self.retrigger)

        self.start_beat = self._number(0.0, 1_000_000.0, 0.0, 3)
        self.end_beat = self._number(0.001, 1_000_000.0, 16.0, 3)
        form.addRow("Start beat", self.start_beat)
        form.addRow("End beat", self.end_beat)
        self.period = self._number(0.0625, 256.0, 4.0, 3)
        form.addRow("Period / step · beats", self.period)
        self.amount = self._number(-20_000.0, 20_000.0, 1_200.0, 3)
        form.addRow("Modulation amount", self.amount)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setValue(2026)
        form.addRow("Source seed", self.seed)
        root.addLayout(form)

        self.preview = AutomationCurvePreview()
        self.preview.valuesChanged.connect(
            lambda values: self.source_values.setText(
                ", ".join(f"{float(value):.4f}" for value in values)
            )
        )
        root.addWidget(self.preview)

        action_row = QHBoxLayout()
        self.add_button = QPushButton("ADD CONTROL")
        self.remove_button = QPushButton("REMOVE")
        self.add_button.clicked.connect(self._add_control)
        self.remove_button.clicked.connect(self._remove_control)
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.remove_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.controls = QListWidget()
        self.controls.setMaximumHeight(118)
        self.controls.currentRowChanged.connect(self._select_control)
        root.addWidget(self.controls)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.apply_button = QPushButton("APPLY & RE-RENDER")
        self.apply_button.setObjectName("primaryAction")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.applyRequested.emit)
        footer.addWidget(self.apply_button)
        root.addLayout(footer)

        self.status = QLabel("Generate a project to edit its Score control performance.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        root.addWidget(self.status)
        self.remove_button.setEnabled(False)
        self._scope_changed()
        self._source_kind_changed()
        self._target_changed()

    @staticmethod
    def _number(minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setSingleStep(0.25 if decimals == 3 else 1.0)
        control.setValue(value)
        return control

    def _target_changed(self, *_args: Any) -> None:
        target = str(self.target.currentData())
        self.amount.setValue(_TARGET_AMOUNTS.get(target, 0.2))
        if hasattr(self, "scope"):
            fx_target = target.startswith(("stem.", "bus."))
            self.scope.setEnabled(not fx_target)
            if fx_target:
                self.scope.setCurrentIndex(self.scope.findData("global"))

    def _source_kind_changed(self, *_args: Any) -> None:
        kind = str(self.source_kind.currentData())
        self.lfo_waveform.setEnabled(kind == "lfo")
        self.source_values.setEnabled(
            kind in {"envelope", "stepped", "phrase_curve"}
        )
        self.random_step_size.setEnabled(kind == "random_walk")
        self.random_initial.setEnabled(kind == "random_walk")
        if kind not in {"envelope", "stepped", "phrase_curve"}:
            self.preview.set_values((), editable=False)
        else:
            self._draft_source_preview_changed()

    def _draft_source_preview_changed(self, *_args: Any) -> None:
        kind = str(self.source_kind.currentData())
        if kind not in {"envelope", "stepped", "phrase_curve"}:
            return
        try:
            values = self._source_values()
        except ValueError:
            self.preview.set_values((), editable=False)
            return
        self.preview.set_values(values, editable=True)

    @staticmethod
    def _fx_target_label(target_id: str) -> str:
        if target_id.startswith("stem."):
            _prefix, stem_name, action = target_id.split(".", 2)
            labels = {
                "insert_wet": "INSERT WET",
                "send.space": "SPACE SEND",
                "send.echo": "ECHO SEND",
            }
            action_label = labels.get(action, action.upper().replace("_", " "))
            return f"FX · {stem_name.upper()} · {action_label}"
        if target_id == "bus.space.wet":
            return "FX · SPACE RETURN WET"
        if target_id == "bus.echo.wet":
            return "FX · ECHO RETURN WET"
        return target_id

    def _populate_targets(self, score: Score | None) -> None:
        selected = self.target.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        for target_id, label in _TARGETS:
            self.target.addItem(label, target_id)
        self._target_ranges = dict(_TARGET_RANGES)
        if score is not None:
            stems = tuple(score.metadata.get("render_stems", ()))
            if not stems:
                stems = tuple(sorted({
                    event.voice_id for event in score.events
                    if event.voice_id != "sample_break"
                }))
            for target_id in automation_targets(stems):
                self.target.addItem(self._fx_target_label(target_id), target_id)
                self._target_ranges[target_id] = (0.0, 1.0)
        restored = self.target.findData(selected)
        self.target.setCurrentIndex(restored if restored >= 0 else 0)
        self.target.blockSignals(False)
        self._target_changed()

    def _source_values(self) -> list[float]:
        tokens = [part.strip() for part in self.source_values.text().split(",")]
        if len(tokens) < 2 or any(not token for token in tokens):
            raise ValueError("enter at least two comma-separated curve values")
        try:
            values = [float(token) for token in tokens]
        except ValueError as exc:
            raise ValueError("curve values must be numbers between 0 and 1") from exc
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("curve values must be finite and between 0 and 1")
        return values

    def _scope_changed(self, *_args: Any) -> None:
        scope = str(self.scope.currentData() or "global")
        is_global = scope == "global"
        self.scope_id.setEnabled(not is_global)
        if is_global:
            self.scope_id.clear()
            self.scope_id.setToolTip("Global controls apply to every matching Score event.")
            return
        self._refresh_scope_ids()

    def _refresh_scope_ids(self) -> None:
        """Suggest exact scope IDs from the loaded Score while retaining free-form entry."""
        scope = str(self.scope.currentData() or "global")
        if scope == "global":
            return
        if self._score is None:
            self.scope_id.clear()
            return
        previous = self.scope_id.currentText().strip()
        if scope == "role":
            identifiers = {event.voice_id for event in self._score.events}
        elif scope == "section":
            identifiers = {
                str(value)
                for event in self._score.events
                if (value := (
                    event.parameters.get("section_id")
                    or event.parameters.get("section_name")
                )) is not None and str(value).strip()
            }
        else:
            identifiers = {event.event_id for event in self._score.events}
        ordered = sorted(identifiers)
        # Keep very large Scores responsive; the editable field still accepts any exact ID.
        if scope == "event" and len(ordered) > 250:
            ordered = ordered[:250]
            self.scope_id.setToolTip(
                "Showing the first 250 event IDs. You can type any exact event ID."
            )
        else:
            self.scope_id.setToolTip(
                "Suggestions are drawn from the loaded Score. You can also type an exact ID."
            )
        self.scope_id.clear()
        self.scope_id.addItems(ordered)
        self.scope_id.setCurrentText(previous if previous else "")

    def set_score(self, score: Score | None) -> None:
        self._score = score
        self._populate_targets(score)
        self._refresh_scope_ids()
        self._sources = list(score.automation_sources) if score is not None else []
        self._modulations = list(score.modulations) if score is not None else []
        self.controls.clear()
        for source in self._sources:
            connections = [
                item for item in self._modulations if item.source_id == source.source_id
            ]
            if connections:
                destinations = ", ".join(item.destination_target_id for item in connections)
            else:
                destinations = "unconnected"
            self.controls.addItem(f"{source.source_id}  →  {destinations}")
        self.apply_button.setEnabled(score is not None)
        existing_indices = [
            int(source.source_id.rsplit("-", 1)[-1])
            for source in self._sources
            if source.source_id.startswith("m18-control-")
            and source.source_id.rsplit("-", 1)[-1].isdigit()
        ]
        self._counter = max([self._counter, *existing_indices], default=self._counter)
        self._select_control(self.controls.currentRow())
        self.status.setText(
            f"{len(self._sources)} source(s) · {len(self._modulations)} connection(s). "
            "Changes are staged until APPLY & RE-RENDER."
        )

    def updated_score(self, score: Score | None = None) -> Score:
        base = score or self._score
        if base is None:
            raise ValueError("generate a project before applying score automation")
        return replace(
            base,
            automation_sources=tuple(self._sources),
            modulations=tuple(self._modulations),
        )

    def _build_source(self, source_id: str) -> AutomationSource:
        kind = str(self.source_kind.currentData())
        period = float(self.period.value())
        parameters: dict[str, Any]
        if kind == "lfo":
            parameters = {
                "period_beats": period,
                "waveform": str(self.lfo_waveform.currentData()),
                "center": 0.5,
                "depth": 0.5,
                "sample_count": 128,
            }
        elif kind == "envelope":
            values = self._source_values()
            denominator = max(1, len(values) - 1)
            parameters = {
                "shape": [
                    [index / denominator, value]
                    for index, value in enumerate(values)
                ],
                "curve": "smooth",
            }
        elif kind == "stepped":
            parameters = {
                "values": self._source_values(),
                "step_beats": period,
            }
        elif kind == "random_walk":
            parameters = {
                "step_beats": period,
                "step_size": float(self.random_step_size.value()),
                "initial": float(self.random_initial.value()),
            }
        else:
            parameters = {
                "values": self._source_values(),
                "curve": "smooth",
            }
        return AutomationSource(
            source_id=source_id,
            kind=kind,
            start=Fraction(str(self.start_beat.value())),
            end=Fraction(str(self.end_beat.value())),
            parameters=parameters,
            seed=int(self.seed.value()),
            minimum=0.0,
            maximum=1.0,
            interpolation="linear",
        )

    def _add_control(self) -> None:
        scope = str(self.scope.currentData())
        scope_id = self.scope_id.currentText().strip() or None
        if scope != "global" and not scope_id:
            self.status.setText(f"Enter a {scope} ID before adding this control.")
            return
        if self.end_beat.value() <= self.start_beat.value():
            self.status.setText("End beat must be later than start beat.")
            return
        self._counter += 1
        source_id = f"m18-control-{self._counter:03d}"
        try:
            source = self._build_source(source_id)
            # Generate now so malformed source parameters fail before a render starts.
            lane = source.to_lane()
            target = str(self.target.currentData())
            low, high = self._target_ranges[target]
            amount = float(self.amount.value())
            polarity = "bipolar"
            modulation = AutomationModulation(
                source_id=source_id,
                destination_target_id=target,
                amount=amount,
                polarity=polarity,
                mode="add",
                retrigger=str(self.retrigger.currentData()),
                minimum=low,
                maximum=high,
                base_value=_TARGET_BASE_VALUES.get(target),
                scope=scope,
                scope_id=scope_id,
            )
        except Exception as exc:
            self.status.setText(f"Could not create control: {exc}")
            return
        self._sources.append(source)
        self._modulations.append(modulation)
        self.controls.addItem(f"{source_id}  →  {target}  ·  {scope.upper()}")
        self.controls.setCurrentRow(self.controls.count() - 1)
        editable_values: list[float] = []
        if source.kind == "envelope":
            editable_values = [
                float(point[1])
                for point in source.parameters.get(
                    "shape", [[0.0, 0.0], [0.15, 1.0], [1.0, 0.0]]
                )
            ]
        elif source.kind in {"phrase_curve", "stepped"}:
            editable_values = [
                float(value) for value in source.parameters.get("values", [0.0, 1.0])
            ]
        self.preview.set_values(
            editable_values if editable_values else [point.value for point in lane.points],
            editable=source.kind in {"envelope", "phrase_curve", "stepped"},
        )
        self.changed.emit()
        self.status.setText(
            f"Added {source.kind} → {target}. Control motion is bounded by {low:g}…{high:g}."
        )

    def _remove_control(self) -> None:
        row = self.controls.currentRow()
        if row < 0 or row >= len(self._sources):
            return
        source = self._sources.pop(row)
        self._modulations = [
            item for item in self._modulations if item.source_id != source.source_id
        ]
        self.controls.takeItem(row)
        self._select_control(self.controls.currentRow())
        self.changed.emit()

    def _select_control(self, row: int) -> None:
        self.remove_button.setEnabled(0 <= row < len(self._sources))
        if not 0 <= row < len(self._sources):
            self.preview.set_values(())
            return
        source = self._sources[row]
        try:
            lane = source.to_lane()
        except Exception:
            self.preview.set_values(())
            return
        editable_values: list[float] = []
        if source.kind == "envelope":
            editable_values = [
                float(point[1])
                for point in source.parameters.get(
                    "shape", [[0.0, 0.0], [0.15, 1.0], [1.0, 0.0]]
                )
            ]
        elif source.kind in {"phrase_curve", "stepped"}:
            editable_values = [
                float(value) for value in source.parameters.get("values", [0.0, 1.0])
            ]
        self.preview.set_values(
            editable_values if editable_values else [point.value for point in lane.points],
            editable=source.kind in {"envelope", "phrase_curve", "stepped"},
        )

