"""Reusable stem mixer row widget."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QToolButton, QWidget


class StemRow(QFrame):
    selected = Signal(str)
    regenerate = Signal(str)
    changed = Signal()

    def __init__(self, name: str, can_regenerate: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.can_regenerate = can_regenerate
        self.setObjectName("stemRow")
        self.setStyleSheet(
            "QFrame#stemRow { background: #171e27; border: 1px solid #293442; border-radius: 6px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(8)

        name_button = QPushButton(name.replace("_", " ").upper())
        name_button.setMinimumWidth(145)
        name_button.clicked.connect(lambda: self.selected.emit(self.name))
        layout.addWidget(name_button)

        layout.addWidget(QLabel("GAIN"))
        self.gain = QSlider(Qt.Orientation.Horizontal)
        self.gain.setRange(0, 400)
        self.gain.setValue(100)
        self.gain.setFixedWidth(100)
        self.gain.valueChanged.connect(self.changed.emit)
        layout.addWidget(self.gain)
        self.gain_label = QLabel("1.00")
        self.gain_label.setFixedWidth(38)
        self.gain.valueChanged.connect(lambda value: self.gain_label.setText(f"{value / 100:.2f}"))
        layout.addWidget(self.gain_label)

        layout.addWidget(QLabel("PAN"))
        self.pan = QSlider(Qt.Orientation.Horizontal)
        self.pan.setRange(-100, 100)
        self.pan.setValue(0)
        self.pan.setFixedWidth(80)
        self.pan.valueChanged.connect(self.changed.emit)
        layout.addWidget(self.pan)
        self.pan_label = QLabel("C")
        self.pan_label.setFixedWidth(30)
        self.pan.valueChanged.connect(
            lambda value: self.pan_label.setText(
                "C" if value == 0 else f"{abs(value)}{'L' if value < 0 else 'R'}"
            )
        )
        layout.addWidget(self.pan_label)

        self.mute = QToolButton()
        self.mute.setText("M")
        self.mute.setCheckable(True)
        self.mute.setToolTip("Mute in mixer audition and master export")
        self.mute.toggled.connect(self.changed.emit)
        layout.addWidget(self.mute)

        self.solo = QToolButton()
        self.solo.setText("S")
        self.solo.setCheckable(True)
        self.solo.setToolTip("Solo this stem; multiple solo stems are allowed")
        self.solo.toggled.connect(self.changed.emit)
        layout.addWidget(self.solo)

        self.regen = QPushButton("REGENERATE")
        self.regen.setEnabled(can_regenerate)
        if not can_regenerate:
            self.regen.setToolTip("This source layer cannot be regenerated procedurally.")
        self.regen.clicked.connect(lambda: self.regenerate.emit(self.name))
        layout.addWidget(self.regen)
        layout.addStretch(1)

    def state(self) -> dict[str, Any]:
        return {
            "gain": self.gain.value(),
            "pan": self.pan.value(),
            "mute": self.mute.isChecked(),
            "solo": self.solo.isChecked(),
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.gain.setValue(int(state.get("gain", 100)))
        self.pan.setValue(int(state.get("pan", 0)))
        self.mute.setChecked(bool(state.get("mute", False)))
        self.solo.setChecked(bool(state.get("solo", False)))
