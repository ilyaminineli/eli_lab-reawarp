"""Compact editor for per-stem inserts and shared send buses."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from reawarp.fx import FX_PRESETS
from reawarp.fx_routing import FX_BUSES, default_fx_routing, load_fx_routing, normalise_fx_routing, save_fx_routing


class FXRoutingEditor(QGroupBox):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("ROLE-AWARE FX ROUTING", parent)
        self.setToolTip("Per-stem inserts and shared post-insert send/return buses.")
        self._stem_names: tuple[str, ...] = ()
        self._routing: dict[str, Any] = default_fx_routing()
        root = QVBoxLayout(self)
        intro = QLabel("INSERT processes one stem. SPACE / ECHO sends share a return across selected roles. Dry source stems remain untouched.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)
        top = QHBoxLayout()
        self.stem = QComboBox()
        self.stem.currentIndexChanged.connect(self._load_selected)
        top.addWidget(QLabel("Stem"))
        top.addWidget(self.stem, 1)
        self.insert = QComboBox()
        self.insert.addItem("BYPASS", "bypass")
        for key in FX_PRESETS:
            self.insert.addItem(key.replace("_", " ").upper(), key)
        top.addWidget(QLabel("Insert"))
        top.addWidget(self.insert, 1)
        root.addLayout(top)
        self.insert.currentIndexChanged.connect(self._store_selected)
        self.insert_wet = QSlider(Qt.Orientation.Horizontal)
        self.insert_wet.setRange(0, 100)
        self.insert_wet.setValue(100)
        root.addWidget(QLabel("INSERT WET"))
        root.addWidget(self.insert_wet)
        self.insert_wet.valueChanged.connect(self._store_selected)
        bus_group = QGroupBox("SHARED SEND LEVELS")
        bus_form = QFormLayout(bus_group)
        self.sends: dict[str, QSlider] = {}
        for bus in FX_BUSES:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.valueChanged.connect(self._store_selected)
            self.sends[bus] = slider
            bus_form.addRow(bus.upper(), slider)
        root.addWidget(bus_group)
        return_group = QGroupBox("BUS RETURNS")
        return_form = QFormLayout(return_group)
        self.bus_wet: dict[str, QSlider] = {}
        self.bus_tail: dict[str, QDoubleSpinBox] = {}
        self.bus_chain: dict[str, QComboBox] = {}
        for bus, default in (("space", "restrained_space"), ("echo", "tape_echo")):
            chain = QComboBox()
            for name in FX_PRESETS:
                chain.addItem(name.replace("_", " ").upper(), name)
            chain.setCurrentIndex(max(0, chain.findData(default)))
            wet = QSlider(Qt.Orientation.Horizontal)
            wet.setRange(0, 100)
            wet.setValue(0 if bus == "echo" else 18)
            tail = QDoubleSpinBox()
            tail.setRange(0.0, 12.0)
            tail.setSingleStep(0.5)
            tail.setSuffix(" s")
            tail.setValue(2.0 if bus == "space" else 1.5)
            self.bus_chain[bus], self.bus_wet[bus], self.bus_tail[bus] = chain, wet, tail
            form = QGroupBox(bus.upper())
            row = QFormLayout(form)
            row.addRow("Processor", chain)
            row.addRow("Return level", wet)
            row.addRow("Tail", tail)
            return_form.addRow(form)
            chain.currentIndexChanged.connect(self._store_buses)
            wet.valueChanged.connect(self._store_buses)
            tail.valueChanged.connect(self._store_buses)
        root.addWidget(return_group)
        actions = QHBoxLayout()
        self.load_button = QPushButton("LOAD ROUTING…")
        self.save_button = QPushButton("SAVE ROUTING…")
        self.load_button.clicked.connect(self._load_file)
        self.save_button.clicked.connect(self._save_file)
        actions.addWidget(self.load_button)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        root.addLayout(actions)
        self.status = QLabel("No project loaded.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def set_stems(self, names: list[str] | tuple[str, ...], sample_rate: int) -> None:
        self._stem_names = tuple(names)
        self._sample_rate = int(sample_rate)
        current = self.stem.currentData()
        self._routing = default_fx_routing(self._stem_names)
        self.stem.blockSignals(True)
        self.stem.clear()
        self.stem.addItems([])
        for name in self._stem_names:
            self.stem.addItem(name.replace("_", " ").upper(), name)
        self.stem.blockSignals(False)
        index = self.stem.findData(current)
        self.stem.setCurrentIndex(index if index >= 0 else 0)
        self._load_selected()
        self._load_buses_into_widgets()
        self.status.setText(f"{len(names)} stems · dry by default · insert and sends are opt-in.")

    def _load_selected(self, *_args: Any) -> None:
        name = self.stem.currentData()
        if name not in self._routing["stems"]:
            return
        record = self._routing["stems"][name]
        insert = record["insert"]
        preset = insert.get("preset") if insert["kind"] == "preset" else None
        self.insert.blockSignals(True)
        self.insert.setCurrentIndex(max(0, self.insert.findData(preset or "bypass")))
        self.insert.blockSignals(False)
        self.insert_wet.blockSignals(True)
        self.insert_wet.setValue(round(float(insert.get("wet", 0.0)) * 100))
        self.insert_wet.blockSignals(False)
        for bus, slider in self.sends.items():
            slider.blockSignals(True)
            slider.setValue(round(float(record["sends"][bus]) * 100))
            slider.blockSignals(False)

    def _store_selected(self, *_args: Any) -> None:
        name = self.stem.currentData()
        if name not in self._routing["stems"]:
            return
        choice = self.insert.currentData()
        insert = ({"kind": "bypass"} if choice == "bypass" else
                  {"kind": "preset", "preset": choice, "wet": self.insert_wet.value() / 100, "tail_seconds": 1.5})
        self._routing["stems"][name] = {
            "insert": insert,
            "sends": {bus: slider.value() / 100 for bus, slider in self.sends.items()},
        }
        self.changed.emit()

    def _load_buses_into_widgets(self) -> None:
        for bus, record in self._routing["buses"].items():
            self.bus_chain[bus].setCurrentIndex(max(0, self.bus_chain[bus].findData(record["chain"])))
            self.bus_wet[bus].setValue(round(record["wet"] * 100))
            self.bus_tail[bus].setValue(record["tail_seconds"])

    def _store_buses(self, *_args: Any) -> None:
        if not hasattr(self, "bus_chain"):
            return
        self._routing["buses"] = {
            bus: {"chain": self.bus_chain[bus].currentData(),
                  "wet": self.bus_wet[bus].value() / 100,
                  "tail_seconds": self.bus_tail[bus].value()}
            for bus in FX_BUSES
        }
        self.changed.emit()

    def _load_file(self) -> None:
        if not self._stem_names:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load FX routing", str(Path.cwd()), "Routing (*.json)")
        if not path:
            return
        try:
            routing = load_fx_routing(path, self._stem_names, self._sample_rate)
        except Exception as exc:
            QMessageBox.warning(self, "FX routing", str(exc))
            return
        self._routing = routing
        self._load_selected()
        self._load_buses_into_widgets()
        self.status.setText(f"Loaded routing: {Path(path).name}")

    def _save_file(self) -> None:
        if not self._stem_names:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save FX routing", "reawarp_routing.json", "Routing (*.json)")
        if not path:
            return
        try:
            save_fx_routing(path, self._routing, self._stem_names, self._sample_rate)
        except Exception as exc:
            QMessageBox.warning(self, "FX routing", str(exc))
            return
        self.status.setText(f"Saved {Path(path).resolve()}")

    def routing(self) -> dict[str, Any]:
        return normalise_fx_routing(self._routing, self._stem_names, self._sample_rate) if self._stem_names else default_fx_routing()
