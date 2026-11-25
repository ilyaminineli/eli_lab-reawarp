"""Compact editor for per-stem inserts and shared send buses."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from reawarp.fx import FX_PRESETS, normalise_fx_stages
from reawarp.fx_routing import (
    FX_BUSES, FX_DELAY_DIVISIONS, SEND_TAP_POINTS, default_fx_routing,
    role_aware_fx_routing, load_fx_routing, normalise_fx_routing, save_fx_routing,
)


class FXRoutingEditor(QGroupBox):
    changed = Signal()
    auditionRequested = Signal(str, str)
    mixerStateRequested = Signal(dict)
    preRenderRequested = Signal()
    variationsRequested = Signal(int, int)
    variationAuditionRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("AUTOMATIC ROLE FX · INSERTS + SHARED RETURNS", parent)
        self.setToolTip("Effects are assigned by musical role and processed on each source path before the master.")
        self._stem_names: tuple[str, ...] = ()
        self._routing: dict[str, Any] = role_aware_fx_routing()
        self.send_taps: dict[str, QComboBox] = {}
        self._loading = False
        root = QVBoxLayout(self)
        intro = QLabel(
            "Effects are part of each sound's role path, not a post-master effect. "
            "Assignments happen automatically from the generated stem role: "
            "kick/sub stays dry; percussion, melody and textures receive restrained "
            "inserts and shared SPACE/ECHO contributions. Edit only exceptions; "
            "RESET DRY is available for comparison. Source stems remain immutable."
        )
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
        self.insert.addItem("CUSTOM FX LAB CHAIN", "__custom__")
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
            tap = QComboBox()
            for value in SEND_TAP_POINTS:
                tap.addItem(value.replace("_", " ").upper(), value)
            tap.setCurrentIndex(tap.findData("post_insert_post_fader"))
            tap.currentIndexChanged.connect(self._store_selected)
            self.send_taps[bus] = tap
            bus_form.addRow(bus.upper(), slider)
            bus_form.addRow(f"{bus.upper()} TAP", tap)
        root.addWidget(bus_group)
        return_group = QGroupBox("BUS RETURNS")
        return_form = QFormLayout(return_group)
        self.bus_wet: dict[str, QSlider] = {}
        self.bus_tail: dict[str, QDoubleSpinBox] = {}
        self.bus_chain: dict[str, QComboBox] = {}
        self.bus_sync: dict[str, QComboBox] = {}
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
            if bus == "echo":
                sync = QComboBox()
                for division in FX_DELAY_DIVISIONS:
                    sync.addItem("STATIC" if division == "off" else division.replace("_", " ").upper(), division)
                self.bus_sync[bus] = sync
                row.addRow("Delay division", sync)
                sync.currentIndexChanged.connect(self._store_buses)
            return_form.addRow(form)
            chain.currentIndexChanged.connect(self._store_buses)
            wet.valueChanged.connect(self._store_buses)
            tail.valueChanged.connect(self._store_buses)
        root.addWidget(return_group)
        actions = QHBoxLayout()
        self.auto_button = QPushButton("AUTO ROLE ROUTING")
        self.dry_button = QPushButton("RESET DRY")
        self.auto_button.clicked.connect(self._apply_auto_routing)
        self.dry_button.clicked.connect(self._apply_dry_routing)
        actions.addWidget(self.auto_button)
        actions.addWidget(self.dry_button)
        self.load_button = QPushButton("LOAD ROUTING…")
        self.save_button = QPushButton("SAVE ROUTING…")
        self.load_button.clicked.connect(self._load_file)
        self.save_button.clicked.connect(self._save_file)
        actions.addWidget(self.load_button)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        root.addLayout(actions)

        prerender_row = QHBoxLayout()
        self.prerender_button = QPushButton("PRE-RENDER CHANNEL FX")
        self.prerender_button.setToolTip(
            "Render the current insert/send/return snapshot for every channel in the background."
        )
        self.prerender_button.clicked.connect(self.preRenderRequested.emit)
        prerender_row.addWidget(self.prerender_button)
        self.variation_count = QSpinBox()
        self.variation_count.setRange(2, 8)
        self.variation_count.setValue(4)
        self.variation_seed = QSpinBox()
        self.variation_seed.setRange(0, 2_147_483_647)
        self.variation_seed.setValue(211)
        prerender_row.addWidget(QLabel("FX VARIANTS"))
        prerender_row.addWidget(self.variation_count)
        prerender_row.addWidget(QLabel("SEED"))
        prerender_row.addWidget(self.variation_seed)
        self.generate_variations_button = QPushButton("GENERATE + PRE-RENDER")
        self.generate_variations_button.clicked.connect(
            lambda: self.variationsRequested.emit(
                self.variation_count.value(), self.variation_seed.value()
            )
        )
        prerender_row.addWidget(self.generate_variations_button)
        self.variation_choice = QComboBox()
        self.variation_choice.setMinimumWidth(150)
        self.variation_choice.addItem("NO VARIATIONS", None)
        prerender_row.addWidget(self.variation_choice, 1)
        self.play_variation_button = QPushButton("PLAY VARIANT")
        self.play_variation_button.setEnabled(False)
        self.play_variation_button.clicked.connect(
            lambda: self.variationAuditionRequested.emit(
                str(self.variation_choice.currentData())
            ) if self.variation_choice.currentData() else None
        )
        self.variation_choice.currentIndexChanged.connect(
            lambda: self.play_variation_button.setEnabled(
                self.variation_choice.currentData() is not None
            )
        )
        prerender_row.addWidget(self.play_variation_button)
        root.addLayout(prerender_row)

        self.status = QLabel("No project loaded.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.meter_report = QLabel("ROUTING METERS · waiting for render")
        self.meter_report.setObjectName("muted")
        self.meter_report.setWordWrap(True)
        root.addWidget(self.meter_report)

        audition_row = QHBoxLayout()
        self.audition_stage = QComboBox()
        for label, stage in (
            ("DIRECT", "direct"), ("INSERT", "insert"),
            ("SPACE SEND", "send.space"), ("ECHO SEND", "send.echo"),
            ("SPACE RETURN", "return.space"), ("ECHO RETURN", "return.echo"),
            ("MASTER", "master"),
        ):
            self.audition_stage.addItem(label, stage)
        self.audition_button = QPushButton("AUDITION SELECTED")
        self.audition_button.clicked.connect(self._request_audition)
        self.match_level_checkbox = QCheckBox("MATCH LEVEL")
        self.match_level_checkbox.setChecked(True)
        self.match_level_checkbox.setToolTip(
            "Create a peak-safe -18 dBFS RMS audition copy. Exported masters are not changed."
        )
        audition_row.addWidget(self.audition_stage, 1)
        audition_row.addWidget(self.match_level_checkbox)
        audition_row.addWidget(self.audition_button)
        root.addLayout(audition_row)

    def set_stems(self, names: list[str] | tuple[str, ...], sample_rate: int, bpm: float = 120.0) -> None:
        self._stem_names = tuple(names)
        self._sample_rate = int(sample_rate)
        self._bpm = float(bpm)
        current = self.stem.currentData()
        self._loading = True
        self._routing = role_aware_fx_routing(self._stem_names)
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
        self._loading = False
        self.status.setText(
            f"{len(names)} stems · effects assigned automatically by role · "
            "no per-stem effect tagging required · kick/sub protected"
        )
        self.changed.emit()

    def _load_selected(self, *_args: Any) -> None:
        name = self.stem.currentData()
        if name not in self._routing["stems"]:
            return
        record = self._routing["stems"][name]
        insert = record["insert"]
        preset = (
            insert.get("preset") if insert["kind"] == "preset"
            else "__custom__" if insert["kind"] == "stages" else "bypass"
        )
        self.insert.blockSignals(True)
        self.insert.setCurrentIndex(max(0, self.insert.findData(preset)))
        self.insert.blockSignals(False)
        self.insert_wet.blockSignals(True)
        self.insert_wet.setValue(round(float(insert.get("wet", 0.0)) * 100))
        self.insert_wet.blockSignals(False)
        for bus, slider in self.sends.items():
            slider.blockSignals(True)
            slider.setValue(round(float(record["sends"][bus]) * 100))
            slider.blockSignals(False)
            tap = self.send_taps[bus]
            tap.blockSignals(True)
            tap.setCurrentIndex(tap.findData(record.get("send_taps", {}).get(
                bus, "post_insert_post_fader"
            )))
            tap.blockSignals(False)

    def _store_selected(self, *_args: Any) -> None:
        name = self.stem.currentData()
        if self._loading or name not in self._routing["stems"]:
            return
        choice = self.insert.currentData()
        prior = self._routing["stems"][name]
        if choice == "bypass":
            insert = {"kind": "bypass"}
        elif choice == "__custom__":
            if prior["insert"].get("kind") != "stages":
                return
            insert = {
                **prior["insert"],
                "stages": [dict(stage) for stage in prior["insert"]["stages"]],
                "wet": self.insert_wet.value() / 100,
            }
        else:
            insert = {
                "kind": "preset", "preset": choice,
                "wet": self.insert_wet.value() / 100, "tail_seconds": 1.5,
            }
        self._routing["stems"][name] = {
            **prior,
            "insert": insert,
            "sends": {bus: slider.value() / 100 for bus, slider in self.sends.items()},
            "send_taps": {bus: tap.currentData() for bus, tap in self.send_taps.items()},
        }
        self._routing["routing_mode"] = "manual"
        self.changed.emit()

    def _load_buses_into_widgets(self) -> None:
        for bus, record in self._routing["buses"].items():
            self.bus_chain[bus].setCurrentIndex(max(0, self.bus_chain[bus].findData(record["chain"])))
            self.bus_wet[bus].setValue(round(record["wet"] * 100))
            self.bus_tail[bus].setValue(record["tail_seconds"])
            if bus in self.bus_sync:
                sync = self.bus_sync[bus]
                sync.blockSignals(True)
                sync.setCurrentIndex(max(0, sync.findData(record.get("delay_sync", "off"))))
                sync.blockSignals(False)
                has_delay = any(
                    stage.get("type") == "delay" for stage in FX_PRESETS[record["chain"]]
                )
                sync.setEnabled(has_delay)

    def _store_buses(self, *_args: Any) -> None:
        if self._loading or not hasattr(self, "bus_chain"):
            return
        echo_preset = str(self.bus_chain["echo"].currentData())
        echo_has_delay = any(
            stage.get("type") == "delay" for stage in FX_PRESETS[echo_preset]
        )
        if not echo_has_delay and self.bus_sync["echo"].currentData() != "off":
            self.bus_sync["echo"].blockSignals(True)
            self.bus_sync["echo"].setCurrentIndex(self.bus_sync["echo"].findData("off"))
            self.bus_sync["echo"].blockSignals(False)
        self.bus_sync["echo"].setEnabled(echo_has_delay)
        self._routing["routing_mode"] = "manual"
        self._routing["buses"] = {
            bus: {
                "chain": self.bus_chain[bus].currentData(),
                "wet": self.bus_wet[bus].value() / 100,
                "tail_seconds": self.bus_tail[bus].value(),
                "delay_sync": self.bus_sync[bus].currentData() if bus in self.bus_sync else "off",
            }
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
        self._loading = True
        self._routing = routing
        self._load_selected()
        self._load_buses_into_widgets()
        self._loading = False
        self.mixerStateRequested.emit({
            name: {
                "gain_db": float(record.get("gain_db", 0.0)),
                "pan": float(record.get("pan", 0.0)),
                "mute": bool(record.get("mute", False)),
                "solo": bool(record.get("solo", False)),
            }
            for name, record in self._routing["stems"].items()
        })
        self.status.setText(f"Loaded routing: {Path(path).name}")
        self.changed.emit()

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

    def set_routing(self, payload: dict[str, Any]) -> None:
        self._loading = True
        self._routing = normalise_fx_routing(payload, self._stem_names, self._sample_rate)
        self._load_selected()
        self._load_buses_into_widgets()
        self._loading = False
        self.changed.emit()

    def _apply_auto_routing(self) -> None:
        self.set_routing(role_aware_fx_routing(self._stem_names))

    def _apply_dry_routing(self) -> None:
        self.set_routing(default_fx_routing(self._stem_names))

    def set_mixer_state(self, states: dict[str, dict[str, Any]]) -> None:
        """Synchronise portable v2 fader state without changing effect routing mode."""
        if not self._stem_names:
            return
        for name, values in states.items():
            if name not in self._routing["stems"]:
                continue
            record = self._routing["stems"][name]
            record["gain_db"] = float(values.get("gain_db", record.get("gain_db", 0.0)))
            record["pan"] = float(values.get("pan", record.get("pan", 0.0)))
            record["mute"] = bool(values.get("mute", record.get("mute", False)))
            record["solo"] = bool(values.get("solo", record.get("solo", False)))


    def match_audition_level(self) -> bool:
        return bool(self.match_level_checkbox.isChecked())

    def _request_audition(self) -> None:
        stem = str(self.stem.currentData() or "")
        stage = str(self.audition_stage.currentData() or "direct")
        if stage == "master":
            stem = "master"
        self.auditionRequested.emit(stage, stem)

    def set_meter_report(self, meters: dict[str, Any] | None) -> None:
        if not meters:
            self.meter_report.setText("ROUTING METERS · not rendered yet")
            return
        def summarize(record: dict[str, Any]) -> str:
            return (
                f"peak {float(record.get('peak_dbfs', -240.0)):.1f} dBFS · "
                f"RMS {float(record.get('rms_dbfs', -240.0)):.1f} dBFS · "
                f"crest {float(record.get('crest_factor_db', 0.0)):.1f} dB · "
                f"headroom {float(record.get('headroom_db', 0.0)):.1f} dB"
            )
        rows = []
        for boundary in ("direct", "insert", "returns"):
            records = meters.get(boundary, {})
            if not records:
                continue
            values = " | ".join(
                f"{name}: {summarize(record)}" for name, record in records.items()
            )
            rows.append(f"{boundary.upper()} · {values}")
        sends = meters.get("sends", {})
        send_records = [
            (stem, bus, record)
            for stem, buses in sends.items()
            for bus, record in buses.items()
        ]
        if send_records:
            rows.append(
                "SEND CONTRIBUTIONS · " + " | ".join(
                    f"{stem}/{bus}: peak {record['peak_dbfs']:.1f} dBFS · "
                    f"RMS {record['rms_dbfs']:.1f} dBFS"
                    for stem, bus, record in send_records
                )
            )
        master = meters.get("master")
        if master:
            rows.append(f"MASTER · {summarize(master)}")
        self.meter_report.setText("\n".join(rows) if rows else "ROUTING METERS · silence")

    def set_custom_insert(
        self,
        stem_name: str,
        stages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        wet: float = 0.75,
        tail_seconds: float = 1.5,
    ) -> None:
        """Install the current FX Lab chain as a portable custom stem insert."""
        if stem_name not in self._routing.get("stems", {}):
            raise ValueError(f"unknown project stem: {stem_name}")
        chain = normalise_fx_stages(stages, sample_rate=self._sample_rate)
        if not 0.0 <= float(wet) <= 1.0:
            raise ValueError("custom insert wet must be between 0 and 1")
        if not 0.0 <= float(tail_seconds) <= 12.0:
            raise ValueError("custom insert tail must be between 0 and 12 seconds")
        self._routing["stems"][stem_name]["insert"] = {
            "kind": "stages",
            "stages": [dict(stage) for stage in chain],
            "wet": float(wet),
            "tail_seconds": float(tail_seconds),
        }
        self._routing["routing_mode"] = "manual"
        self._loading = True
        self.stem.setCurrentIndex(max(0, self.stem.findData(stem_name)))
        self._load_selected()
        self._loading = False
        self.changed.emit()

    def set_variation_choices(
        self, choices: list[tuple[str, str]] | tuple[tuple[str, str], ...]
    ) -> None:
        self.variation_choice.blockSignals(True)
        self.variation_choice.clear()
        self.variation_choice.addItem("NO VARIATIONS", None)
        for candidate_id, label in choices:
            self.variation_choice.addItem(str(label), str(candidate_id))
        self.variation_choice.blockSignals(False)
        self.play_variation_button.setEnabled(False)


    def routing(self) -> dict[str, Any]:
        return normalise_fx_routing(self._routing, self._stem_names, self._sample_rate) if self._stem_names else default_fx_routing()
