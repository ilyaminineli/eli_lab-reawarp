"""Beat-based FX automation editor for the Stem Mixer."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from reawarp.fx_automation import (
    FX_AUTOMATION_CURVES, automation_targets, load_fx_automation,
    normalise_fx_automation, save_fx_automation,
)


class FXAutomationEditor(QGroupBox):
    """Small point editor; lane positions are musical beats, not seconds."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("MUSICAL FX AUTOMATION", parent)
        self._stem_names: tuple[str, ...] = ()
        self._bpm = 120.0
        self._automation: dict[str, Any] = {"schema_version": 1, "lanes": {}}
        root = QVBoxLayout(self)
        intro = QLabel(
            "Draw deterministic insert, send, and return changes in beats. "
            "Unedited controls keep their static routing values."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)

        lane_row = QHBoxLayout()
        self.lane = QComboBox()
        self.lane.currentIndexChanged.connect(self._refresh_table)
        lane_row.addWidget(QLabel("Target"))
        lane_row.addWidget(self.lane, 1)
        self.tempo_label = QLabel("120 BPM")
        self.tempo_label.setObjectName("muted")
        lane_row.addWidget(self.tempo_label)
        root.addLayout(lane_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["BEAT", "VALUE", "CURVE TO NEXT"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(142)
        self.table.itemSelectionChanged.connect(self._select_point)
        root.addWidget(self.table)

        edit_form = QFormLayout()
        self.beat = QDoubleSpinBox()
        self.beat.setRange(0.0, 1_000_000.0)
        self.beat.setDecimals(3)
        self.beat.setSingleStep(1.0)
        self.value = QDoubleSpinBox()
        self.value.setRange(0.0, 1.0)
        self.value.setDecimals(3)
        self.value.setSingleStep(0.05)
        self.curve = QComboBox()
        for curve in FX_AUTOMATION_CURVES:
            self.curve.addItem(curve.upper(), curve)
        edit_form.addRow("Beat", self.beat)
        edit_form.addRow("Value", self.value)
        edit_form.addRow("Curve", self.curve)
        root.addLayout(edit_form)

        actions = QHBoxLayout()
        self.add_button = QPushButton("ADD POINT")
        self.update_button = QPushButton("UPDATE")
        self.remove_button = QPushButton("REMOVE")
        self.add_button.clicked.connect(self._add_point)
        self.update_button.clicked.connect(self._update_point)
        self.remove_button.clicked.connect(self._remove_point)
        actions.addWidget(self.add_button)
        actions.addWidget(self.update_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        root.addLayout(actions)

        files = QHBoxLayout()
        self.load_button = QPushButton("LOAD AUTOMATION…")
        self.save_button = QPushButton("SAVE AUTOMATION…")
        self.load_button.clicked.connect(self._load_file)
        self.save_button.clicked.connect(self._save_file)
        files.addWidget(self.load_button)
        files.addWidget(self.save_button)
        files.addStretch(1)
        root.addLayout(files)

        self.status = QLabel("No automation lanes. Static routing remains in control.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.update_button.setEnabled(False)
        self.remove_button.setEnabled(False)

    def set_project(self, stem_names: list[str] | tuple[str, ...], bpm: float) -> None:
        self._stem_names = tuple(stem_names)
        self._bpm = float(bpm)
        allowed = set(automation_targets(self._stem_names))
        kept_lanes = {
            target: points
            for target, points in self._automation.get("lanes", {}).items()
            if target in allowed
        }
        self._automation = normalise_fx_automation(
            {"schema_version": 1, "lanes": kept_lanes}, self._stem_names
        )
        self.lane.blockSignals(True)
        self.lane.clear()
        for target in automation_targets(self._stem_names):
            self.lane.addItem(target.replace(".", " / ").replace("_", " ").upper(), target)
        self.lane.blockSignals(False)
        self.tempo_label.setText(f"{self._bpm:g} BPM")
        self._refresh_table()
        self.status.setText(
            f"{len(self._stem_names)} stems · {len(self._automation['lanes'])} active automation lanes."
        )

    def set_automation(self, payload: dict[str, Any]) -> None:
        self._automation = normalise_fx_automation(payload, self._stem_names)
        self._refresh_table()
        self.changed.emit()
        self.status.setText(f"Loaded {len(self._automation['lanes'])} automation lane(s).")

    def automation(self) -> dict[str, Any]:
        return normalise_fx_automation(self._automation, self._stem_names)

    def _target(self) -> str | None:
        value = self.lane.currentData()
        return str(value) if value is not None else None

    def _refresh_table(self, *_args: Any) -> None:
        target = self._target()
        points = self._automation.get("lanes", {}).get(target, []) if target else []
        self.table.setRowCount(len(points))
        for row, point in enumerate(points):
            values = (
                f"{float(point['beat']):.3f}".rstrip("0").rstrip("."),
                f"{float(point['value']):.3f}".rstrip("0").rstrip("."),
                str(point["curve"]).upper(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, column, item)
        self.table.clearSelection()
        self._select_point()
        self.status.setText(
            "Static value is used outside this lane's points."
            if not points else f"{len(points)} points · beat positions follow the project tempo."
        )

    def _point_from_controls(self) -> dict[str, float | str]:
        return {
            "beat": float(self.beat.value()),
            "value": float(self.value.value()),
            "curve": str(self.curve.currentData()),
        }

    def _add_point(self) -> None:
        target = self._target()
        if target is None:
            return
        points = list(self._automation["lanes"].get(target, []))
        point = self._point_from_controls()
        if any(abs(float(item["beat"]) - point["beat"]) < 1e-6 for item in points):
            self.status.setText("A point already exists at that beat. Select it and use UPDATE.")
            return
        points.append(point)
        points.sort(key=lambda item: float(item["beat"]))
        self._automation["lanes"][target] = points
        self._refresh_table()
        self.changed.emit()

    def _update_point(self) -> None:
        target = self._target()
        row = self.table.currentRow()
        if target is None or row < 0:
            return
        points = list(self._automation["lanes"].get(target, []))
        if row >= len(points):
            return
        updated = self._point_from_controls()
        if any(
            index != row and abs(float(item["beat"]) - updated["beat"]) < 1e-6
            for index, item in enumerate(points)
        ):
            self.status.setText("Another point already uses that beat position.")
            return
        points[row] = updated
        points.sort(key=lambda item: float(item["beat"]))
        self._automation["lanes"][target] = points
        self._refresh_table()
        self.changed.emit()

    def _remove_point(self) -> None:
        target = self._target()
        row = self.table.currentRow()
        if target is None or row < 0:
            return
        points = list(self._automation["lanes"].get(target, []))
        if row >= len(points):
            return
        del points[row]
        if points:
            self._automation["lanes"][target] = points
        else:
            self._automation["lanes"].pop(target, None)
        self._refresh_table()
        self.changed.emit()

    def _select_point(self) -> None:
        target = self._target()
        row = self.table.currentRow()
        points = self._automation.get("lanes", {}).get(target, []) if target else []
        if row < 0 or row >= len(points):
            self.update_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            return
        point = points[row]
        self.beat.setValue(float(point["beat"]))
        self.value.setValue(float(point["value"]))
        index = self.curve.findData(point["curve"])
        if index >= 0:
            self.curve.setCurrentIndex(index)
        self.update_button.setEnabled(True)
        self.remove_button.setEnabled(True)

    def _load_file(self) -> None:
        if not self._stem_names:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load FX automation", str(Path.cwd()), "Automation (*.json)"
        )
        if not path:
            return
        try:
            self.set_automation(load_fx_automation(path, self._stem_names))
        except Exception as exc:
            QMessageBox.warning(self, "FX automation", str(exc))

    def _save_file(self) -> None:
        if not self._stem_names:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save FX automation", "reawarp_automation.json", "Automation (*.json)"
        )
        if not path:
            return
        try:
            saved = save_fx_automation(path, self.automation(), self._stem_names)
        except Exception as exc:
            QMessageBox.warning(self, "FX automation", str(exc))
            return
        self.status.setText(f"Saved {Path(saved).resolve()}")
