"""M18 score-control editor for deterministic musical automation."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

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
    ("event.velocity_scale", "Event velocity scale"),
    ("event.probability", "Event probability"),
    ("role.activity", "Role activity"),
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
    "event.velocity_scale": (0.0, 2.0),
    "event.probability": (0.0, 1.0),
    "role.activity": (0.0, 1.0),
    "sample.mix": (0.0, 1.0),
    "spatial.pan": (-1.0, 1.0),
    "spatial.width": (0.0, 2.0),
}


class AutomationCurvePreview(QWidget):
    """Small dependency-free preview of the currently selected generated curve."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(104)
        self.setMaximumHeight(136)
        self._values: tuple[float, ...] = ()

    def set_values(self, values: list[float] | tuple[float, ...]) -> None:
        self._values = tuple(float(value) for value in values)
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
        low = min(self._values)
        high = max(self._values)
        span = max(1e-9, high - low)
        path = QPainterPath()
        for index, value in enumerate(self._values):
            x = bounds.left() + bounds.width() * index / (len(self._values) - 1)
            y = bounds.bottom() - bounds.height() * (value - low) / span
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor("#9b9cf6"), 2.0))
        painter.drawPath(path)
        painter.setPen(QColor("#818894"))
        painter.drawText(bounds.adjusted(3, 2, -3, -2), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, f"{high:.3g}")
        painter.drawText(bounds.adjusted(3, 2, -3, -2), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, f"{low:.3g}")
        painter.end()


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
        form.addRow("Source shape", self.source_kind)

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
        self.amount.setValue(_TARGET_AMOUNTS.get(target, 0.25))

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
                "waveform": "sine",
                "center": 0.5,
                "depth": 0.5,
                "sample_count": 128,
            }
        elif kind == "envelope":
            parameters = {
                "shape": [[0.0, 0.0], [0.15, 1.0], [1.0, 0.0]],
                "curve": "smooth",
            }
        elif kind == "stepped":
            parameters = {
                "values": [0.0, 1.0, 0.45, 0.8],
                "step_beats": period,
            }
        elif kind == "random_walk":
            parameters = {
                "step_beats": period,
                "step_size": 0.12,
                "initial": 0.5,
            }
        else:
            parameters = {
                "values": [0.0, 0.75, 0.3, 1.0],
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
            low, high = _TARGET_RANGES[target]
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
        self.preview.set_values([point.value for point in lane.points])
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
        self.preview.set_values([point.value for point in lane.points])

