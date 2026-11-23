#!/usr/bin/env python3
# Reawarp M7 updater for a clean 0.6.0 checkout.
# Run from the repository root: python apply_m7_update.py [--dry-run]

from __future__ import annotations
import argparse
import datetime as dt
import shutil
from pathlib import Path

ROOT = Path.cwd()
BACKUP_ROOT = ROOT / ".reawarp_m7_backup"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source and old not in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected one exact source anchor, found {count}. "
            "No source files have been written."
        )
    return source.replace(old, new, 1)


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise RuntimeError(f"Required source file not found: {path}")
    return target.read_text(encoding="utf-8")


def prepare_changes() -> dict[str, str]:
    changes: dict[str, str] = {}

    p = "src/reawarp/config.py"
    s = read(p)
    s = replace_once(s, '    duration: float = 24.0\n',
        '    duration: float = 12.0\n    structure: str = "evolving"\n'
        '    composition_energy: float = 0.62\n    composition_variation: float = 0.45\n', p)
    s = replace_once(s,
        'if not 5.0 <= float(self.duration) <= 20.0:\n'
        '            raise ValueError("duration must be between 5 and 20 seconds")',
        'if not 5.0 <= float(self.duration) <= 45.0:\n'
        '            raise ValueError("duration must be between 5 and 45 seconds")', p)
    s = replace_once(s,
        '        if not 0.0 <= float(self.complexity) <= 1.0:\n',
        '        if self.structure not in {"evolving", "additive", "subtractive", "episodic", "drift"}:\n'
        '            raise ValueError("unknown composition structure")\n'
        '        if not 0.0 <= float(self.composition_energy) <= 1.0:\n'
        '            raise ValueError("composition_energy must be between 0 and 1")\n'
        '        if not 0.0 <= float(self.composition_variation) <= 1.0:\n'
        '            raise ValueError("composition_variation must be between 0 and 1")\n'
        '        if not 0.0 <= float(self.complexity) <= 1.0:\n', p)
    changes[p] = s

    p = "src/reawarp/core/engine.py"
    s = read(p)
    s = replace_once(s,
        'from reawarp.core.random_streams import RandomStreams, derive_seed\n',
        'from reawarp.core.random_streams import RandomStreams, derive_seed\n'
        'from reawarp.composition.director import build_composition_plan, section_for_time\n', p)
    s = replace_once(s, 'VERSION = "0.6.0"', 'VERSION = "0.7.0"', p)
    s = replace_once(s, '        seed_overrides = {}\n',
        '        # Formal decisions stay fixed during stem-only regeneration.\n'
        '        seed_overrides = {"section_ornaments": derive_seed(config.seed, "section_ornaments")}\n', p)
    s = replace_once(s,
        '        sample_streams = RandomStreams(config.seed)\n',
        '        sample_streams = RandomStreams(config.seed)\n'
        '        sample_section_ornaments = sample_streams.get("sample_section_ornaments")\n', p)
    s = replace_once(s,
        '        frame_count = config.frame_count\n        sample_rate = config.sample_rate\n',
        '        frame_count = config.frame_count\n'
        '        sample_rate = config.sample_rate\n'
        '        composition_plan = build_composition_plan(\n'
        '            duration_seconds=config.duration,\n'
        '            bpm=config.bpm,\n'
        '            seed=config.seed,\n'
        '            structure=config.structure,\n'
        '            energy=config.composition_energy,\n'
        '            variation=config.composition_variation,\n'
        '        )\n', p)
    s = replace_once(s,
        '        for event in percussion["kick"]:\n            profile = kick_profile\n',
        '        for event in percussion["kick"]:\n'
        '            section = section_for_time(composition_plan, event.time)\n'
        '            if not section.kick:\n                continue\n'
        '            profile = kick_profile\n', p)
    s = replace_once(s,
        '        for event in percussion["snare"]:\n            profile = snare_profile\n',
        '        for event in percussion["snare"]:\n'
        '            section = section_for_time(composition_plan, event.time)\n'
        '            if section.density < 0.14 and event.velocity < 0.70:\n                continue\n'
        '            profile = snare_profile\n', p)
    s = replace_once(s,
        '        for event in percussion["hat"]:\n            profile = hat_profile\n',
        '        for event in percussion["hat"]:\n'
        '            section = section_for_time(composition_plan, event.time)\n'
        '            if streams.get("section_ornaments").random() > section.percussion_density_scale:\n'
        '                continue\n'
        '            profile = hat_profile\n', p)
    s = replace_once(s,
        '        for event in percussion["break"]:\n            break_rng = streams.get("break_synthesis")\n',
        '        for event in percussion["break"]:\n'
        '            section = section_for_time(composition_plan, event.time)\n'
        '            if not section.kick and event.kind == "kick":\n                continue\n'
        '            if section.density < 0.16 and event.kind != "kick":\n                continue\n'
        '            break_rng = streams.get("break_synthesis")\n', p)
    s = replace_once(s,
        '            for event in melody_events:\n                signal = render_fm_note(\n                    event.frequency,\n',
        '            for event in melody_events:\n'
        '                section = section_for_time(composition_plan, event.time)\n'
        '                if not section.melody:\n                    continue\n'
        '                effective_frequency = event.frequency * (2.0 ** (section.motif_register_semitones / 12.0))\n'
        '                signal = render_fm_note(\n'
        '                    effective_frequency,\n', p)
    s = replace_once(s,
        '                    "synthesis_profile": melody_profile,\n                })\n',
        '                    "synthesis_profile": melody_profile,\n'
        '                    "effective_frequency_hz": effective_frequency,\n'
        '                    "section": section.name,\n'
        '                    "motif_mode": section.motif_mode,\n'
        '                })\n', p)
    s = replace_once(s,
        '            texture_stem[:, 0] += texture * 0.72\n'
        '            texture_stem[:, 1] += delayed * 0.72\n',
        '            texture_gain = np.zeros(frame_count, dtype=np.float32)\n'
        '            for section in composition_plan.sections:\n'
        '                start = int(round(section.start_seconds * sample_rate))\n'
        '                end = min(frame_count, int(round(section.end_seconds * sample_rate)))\n'
        '                if end > start and section.texture:\n'
        '                    texture_gain[start:end] = 0.45 + 0.55 * section.density\n'
        '            texture_stem[:, 0] += texture * texture_gain * 0.72\n'
        '            texture_stem[:, 1] += delayed * texture_gain * 0.72\n', p)
    s = replace_once(s,
        '            ambience_stem[:] = render_ambience(\n'
        '                frame_count,\n                sample_rate,\n'
        '                streams.get("ambience_synthesis"),\n'
        '                root_frequency=root_frequency,\n'
        '                amount=config.ambience_level,\n            )\n',
        '            ambience_stem[:] = render_ambience(\n'
        '                frame_count,\n                sample_rate,\n'
        '                streams.get("ambience_synthesis"),\n'
        '                root_frequency=root_frequency,\n'
        '                amount=config.ambience_level,\n            )\n'
        '            ambience_gain = np.zeros(frame_count, dtype=np.float32)\n'
        '            for section in composition_plan.sections:\n'
        '                start = int(round(section.start_seconds * sample_rate))\n'
        '                end = min(frame_count, int(round(section.end_seconds * sample_rate)))\n'
        '                if end > start and section.ambience:\n'
        '                    ambience_gain[start:end] = section.space\n'
        '            ambience_stem *= ambience_gain[:, None]\n', p)
    s = replace_once(s,
        '            triggers = sample_trigger_patterns[role]\n',
        '            triggers = sample_trigger_patterns[role]\n'
        '            if role in {"kick", "break"}:\n'
        '                triggers = [event for event in triggers if section_for_time(composition_plan, event.time).kick]\n'
        '            elif role == "snare":\n'
        '                triggers = [event for event in triggers if section_for_time(composition_plan, event.time).density >= 0.14 or event.velocity >= 0.70]\n'
        '            elif role == "hat":\n'
        '                triggers = [event for event in triggers if sample_section_ornaments.random() <= section_for_time(composition_plan, event.time).percussion_density_scale]\n', p)
    s = replace_once(s,
        '                for name in ("kick_pattern", "snare_pattern", "hat_pattern", "break_pattern", "break_processing")\n',
        '                for name in ("kick_pattern", "snare_pattern", "hat_pattern", "break_pattern", "break_processing", "sample_section_ornaments")\n', p)
    s = replace_once(s,
        '                    "break_processing",\n',
        '                    "break_processing", "section_ornaments",\n', p)
    s = replace_once(s,
        '            "break_rhythm": {\n',
        '            "composition_plan": composition_plan.to_dict(),\n'
        '            "break_rhythm": {\n', p)
    changes[p] = s

    p = "src/reawarp/cli.py"
    s = read(p)
    s = replace_once(s,
        '    parser.add_argument("--duration", type=float, default=12.0, help="duration in seconds (5–20)")\n',
        '    parser.add_argument("--duration", type=float, default=12.0, help="duration in seconds (5–45)")\n'
        '    parser.add_argument("--structure", choices=("evolving", "additive", "subtractive", "episodic", "drift"), default="evolving", help="formal composition structure")\n'
        '    parser.add_argument("--energy", type=float, default=0.62, help="composition energy target (0–1)")\n'
        '    parser.add_argument("--variation", type=float, default=0.45, help="section and phrase variation (0–1)")\n', p)
    s = replace_once(s,
        '        duration=args.duration,\n        sample_rate=args.sample_rate,\n',
        '        duration=args.duration,\n'
        '        structure=args.structure,\n'
        '        composition_energy=args.energy,\n'
        '        composition_variation=args.variation,\n'
        '        sample_rate=args.sample_rate,\n', p)
    changes[p] = s

    p = "src/reawarp/library/store.py"
    s = read(p)
    s = replace_once(s,
        '        normalized_tags = set(self._normalize_tags(tags))\n'
        '        normalized_tags.add(asset_type.casefold())\n'
        '        if role:\n',
        '        normalized_tags = set(self._normalize_tags(tags))\n'
        '        normalized_tags.add(asset_type.casefold())\n'
        '        if asset_type.casefold() == "sample":\n'
        '            tokens = set()\n'
        '            for part in (source.stem, *source.parent.parts):\n'
        '                tokens.update(token.casefold() for token in part.replace("-", "_").replace(".", "_").split("_") if token)\n'
        '            categories = {\n'
        '                "kick": {"kick", "bd", "bassdrum", "bass_drum"},\n'
        '                "snare": {"snare", "sd", "clap", "rim"},\n'
        '                "hat": {"hat", "hihat", "hi_hat", "cymbal", "shaker"},\n'
        '                "break": {"break", "breaks", "amen", "loop"},\n'
        '                "texture": {"texture", "noise", "drone", "ambience", "atmosphere", "fx"},\n'
        '                "melody": {"melody", "tonal", "synth", "chord", "key", "bell"},\n'
        '            }\n'
        '            for category, aliases in categories.items():\n'
        '                if tokens.intersection(aliases):\n'
        '                    normalized_tags.add(category)\n'
        '                    if category in {"kick", "snare", "hat", "break"}:\n'
        '                        normalized_tags.add("percussion")\n'
        '        if role:\n', p)
    retag = (
        '    def retag_existing_samples(self) -> int:\n'
        '        # Reapply filename/folder semantic tags to existing sample rows.\n'
        '        categories = {\n'
        '            "kick": {"kick", "bd", "bassdrum", "bass_drum"},\n'
        '            "snare": {"snare", "sd", "clap", "rim"},\n'
        '            "hat": {"hat", "hihat", "hi_hat", "cymbal", "shaker"},\n'
        '            "break": {"break", "breaks", "amen", "loop"},\n'
        '            "texture": {"texture", "noise", "drone", "ambience", "atmosphere", "fx"},\n'
        '            "melody": {"melody", "tonal", "synth", "chord", "key", "bell"},\n'
        '        }\n'
        '        rows = self._connection.execute(\n'
        '            "SELECT asset_id, path, tags_json FROM assets WHERE asset_type = \'sample\'"\n'
        '        ).fetchall()\n'
        '        for row in rows:\n'
        '            source = Path(str(row["path"]))\n'
        '            tokens = set()\n'
        '            for part in (source.stem, *source.parent.parts):\n'
        '                tokens.update(token.casefold() for token in part.replace("-", "_").replace(".", "_").split("_") if token)\n'
        '            tags = set(json.loads(row["tags_json"]))\n'
        '            for category, aliases in categories.items():\n'
        '                if tokens.intersection(aliases):\n'
        '                    tags.add(category)\n'
        '                    if category in {"kick", "snare", "hat", "break"}:\n'
        '                        tags.add("percussion")\n'
        '            self._connection.execute(\n'
        '                "UPDATE assets SET tags_json = ? WHERE asset_id = ?",\n'
        '                (_canonical_json(sorted(tags)), str(row["asset_id"])),\n'
        '            )\n'
        '        self._connection.commit()\n'
        '        return len(rows)\n\n'
    )
    s = replace_once(s,
        '    def index_directory(self, directory: str | Path) -> dict[str, Any]:\n',
        retag + '    def index_directory(self, directory: str | Path) -> dict[str, Any]:\n', p)
    changes[p] = s

    p = "src/reawarp/library/cli.py"
    s = read(p)
    s = replace_once(s,
        '    search = commands.add_parser("search", help="search by name, role, tags, or audio similarity")\n',
        '    commands.add_parser("retag", help="reapply semantic filename tags to indexed samples")\n'
        '    search = commands.add_parser("search", help="search by name, role, tags, or audio similarity")\n', p)
    s = replace_once(s,
        '        if args.command == "search":\n',
        '        if args.command == "retag":\n'
        '            count = library.retag_existing_samples()\n'
        '            print(f"Updated semantic tags for {count} indexed sample(s)")\n'
        '            return\n\n'
        '        if args.command == "search":\n', p)
    s = replace_once(s,
        '            results = library.search(\n'
        '                query=args.query,\n                asset_type=args.asset_type,\n'
        '                role=args.role,\n                tags=args.tag,\n'
        '                similar_to=args.similar_to,\n                limit=args.limit,\n'
        '            )\n',
        '            try:\n'
        '                results = library.search(\n'
        '                    query=args.query,\n                    asset_type=args.asset_type,\n'
        '                    role=args.role,\n                    tags=args.tag,\n'
        '                    similar_to=args.similar_to,\n                    limit=args.limit,\n'
        '                )\n'
        '            except (KeyError, ValueError) as exc:\n'
        '                parser.error(str(exc))\n'
        '                return\n', p)
    s = replace_once(s,
        '                added = library.add_to_collection(args.name, args.asset_ids)\n'
        '                print(f"Added {added} asset(s) to {args.name}")\n',
        '                try:\n'
        '                    added = library.add_to_collection(args.name, args.asset_ids)\n'
        '                except KeyError as exc:\n'
        '                    parser.error(\n'
        '                        f"{exc}. Use real asset IDs printed by reawarp-library search; "\n'
        '                        "example placeholders are not literal IDs."\n'
        '                    )\n'
        '                    return\n'
        '                print(f"Added {added} asset(s) to {args.name}")\n', p)
    changes[p] = s

    p = "src/reawarp/ui/main_window.py"
    s = read(p)
    s = replace_once(s,
        'from PySide6.QtCore import Qt, QTimer, Signal, QThreadPool\n'
        'from PySide6.QtWidgets import (\n'
        '    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,\n'
        '    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,\n'
        '    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,\n'
        '    QTabWidget, QToolButton, QVBoxLayout, QWidget,\n'
        ')\n',
        'from PySide6.QtCore import Qt, QTimer, Signal, QThreadPool, QEvent\n'
        'from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QPen\n'
        'from PySide6.QtWidgets import (\n'
        '    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,\n'
        '    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,\n'
        '    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,\n'
        '    QSystemTrayIcon, QTabWidget, QToolButton, QVBoxLayout, QWidget,\n'
        ')\n\n'
        'from reawarp.composition.director import STRUCTURES\n', p)
    s = replace_once(s,
        '        self.player.finished.connect(self._playback_finished)\n',
        '        self.player.finished.connect(self._playback_finished)\n'
        '        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()\n'
        '        self._tray_icon: QSystemTrayIcon | None = None\n'
        '        self._build_tray_icon()\n', p)
    s = replace_once(s,
        '        self.tabs.addTab(self._build_mixer_page(), "STEM MIXER")\n',
        '        self.tabs.addTab(self._build_mixer_page(), "STEM MIXER")\n'
        '        self.tabs.addTab(self._build_library_page(), "LIBRARY")\n', p)
    s = replace_once(s,
        '        panel_layout = QVBoxLayout(panel)\n\n'
        '        global_group = QGroupBox("GLOBAL PARAMETERS")\n',
        '        panel_layout = QVBoxLayout(panel)\n'
        '        control_tabs = QTabWidget()\n'
        '        composition_page, sound_page, break_controls_page = QWidget(), QWidget(), QWidget()\n'
        '        composition_layout = QVBoxLayout(composition_page)\n'
        '        sound_layout = QVBoxLayout(sound_page)\n'
        '        break_controls_layout = QVBoxLayout(break_controls_page)\n\n'
        '        global_group = QGroupBox("GLOBAL PARAMETERS")\n', p)
    s = replace_once(s, '        self.duration.setRange(5, 20)\n', '        self.duration.setRange(5, 45)\n', p)
    s = replace_once(s,
        '        form.addRow("Duration / sec", self.duration)\n',
        '        form.addRow("Duration / sec", self.duration)\n'
        '        self.structure = QComboBox()\n'
        '        self.structure.addItems(list(STRUCTURES))\n'
        '        self.structure.setCurrentText("evolving")\n'
        '        form.addRow("Formal structure", self.structure)\n'
        '        self.energy = QDoubleSpinBox()\n'
        '        self.energy.setRange(0.0, 1.0)\n'
        '        self.energy.setSingleStep(0.05)\n'
        '        self.energy.setValue(0.62)\n'
        '        form.addRow("Energy target", self.energy)\n'
        '        self.variation = QDoubleSpinBox()\n'
        '        self.variation.setRange(0.0, 1.0)\n'
        '        self.variation.setSingleStep(0.05)\n'
        '        self.variation.setValue(0.45)\n'
        '        form.addRow("Composition variation", self.variation)\n', p)
    s = replace_once(s, '        panel_layout.addWidget(global_group)\n', '        composition_layout.addWidget(global_group)\n', p)
    s = replace_once(s, '        panel_layout.addWidget(modules)\n', '        composition_layout.addWidget(modules)\n', p)
    s = replace_once(s, '        panel_layout.addWidget(profiles)\n', '        sound_layout.addWidget(profiles)\n', p)
    s = replace_once(s, '        panel_layout.addWidget(groove)\n', '        break_controls_layout.addWidget(groove)\n', p)
    s = replace_once(s,
        '        panel_layout.addWidget(source_group)\n\n'
        '        self.generate_button = QPushButton("GENERATE LOOP")\n',
        '        break_controls_layout.addWidget(source_group)\n'
        '        composition_layout.addStretch(1)\n'
        '        sound_layout.addStretch(1)\n'
        '        break_controls_layout.addStretch(1)\n'
        '        control_tabs.addTab(composition_page, "COMPOSITION")\n'
        '        control_tabs.addTab(sound_page, "SOUND")\n'
        '        control_tabs.addTab(break_controls_page, "BREAK")\n'
        '        panel_layout.addWidget(control_tabs, 1)\n\n'
        '        self.generate_button = QPushButton("GENERATE COMPOSITION")\n', p)
    s = replace_once(s,
        '        scroll = QScrollArea()\n'
        '        scroll.setWidgetResizable(True)\n'
        '        scroll.setWidget(panel)\n'
        '        layout.addWidget(scroll)\n',
        '        scroll = QScrollArea()\n'
        '        scroll.setWidgetResizable(True)\n'
        '        scroll.setWidget(panel)\n'
        '        scroll.setMinimumWidth(320)\n'
        '        scroll.setMaximumWidth(420)\n'
        '        layout.addWidget(scroll, 0)\n', p)
    s = replace_once(s,
        '            duration=self.duration.value(),\n            sample_rate=48_000,\n',
        '            duration=self.duration.value(),\n'
        '            structure=self.structure.currentText(),\n'
        '            composition_energy=self.energy.value(),\n'
        '            composition_variation=self.variation.value(),\n'
        '            sample_rate=48_000,\n', p)

    library_methods = r'''
    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        from reawarp.library.store import default_database_path

        header = QHBoxLayout()
        title = QLabel("LOCAL SAMPLE / STEM LIBRARY")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.library_index_button = QPushButton("INDEX FOLDER…")
        self.library_index_button.clicked.connect(self._index_library_folder)
        header.addWidget(self.library_index_button)
        layout.addLayout(header)

        self.library_database_label = QLabel(str(default_database_path()))
        self.library_database_label.setObjectName("muted")
        layout.addWidget(self.library_database_label)

        filters = QHBoxLayout()
        self.library_query = QLineEdit()
        self.library_query.setPlaceholderText("Filename, role, tag, or metadata")
        filters.addWidget(self.library_query, 1)
        self.library_type = QComboBox()
        self.library_type.addItems(["all", "sample", "stem", "master"])
        filters.addWidget(self.library_type)
        self.library_role = QComboBox()
        self.library_role.addItems(["all", "kick", "snare", "hat", "break", "melody", "noise_texture", "ambience"])
        filters.addWidget(self.library_role)
        search = QPushButton("SEARCH")
        search.clicked.connect(self._search_library)
        filters.addWidget(search)
        layout.addLayout(filters)

        self.library_results = QComboBox()
        self.library_results.currentIndexChanged.connect(self._inspect_library_asset)
        layout.addWidget(self.library_results)
        self.library_details = QLabel("Index a folder or exported project to browse audio assets.")
        self.library_details.setWordWrap(True)
        self.library_details.setObjectName("muted")
        layout.addWidget(self.library_details)
        self.library_preview = AudioPreview()
        self.library_preview.setMinimumHeight(220)
        layout.addWidget(self.library_preview, 1)

        actions = QHBoxLayout()
        for label, callback in (
            ("FIND SIMILAR", self._search_similar_library),
            ("CREATE COLLECTION…", self._create_library_collection),
            ("ADD TO COLLECTION…", self._add_to_library_collection),
            ("RETAG EXISTING", self._retag_library),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self._library_worker = None
        return page

    def _index_library_folder(self) -> None:
        from reawarp.library.store import SampleLibrary

        folder = QFileDialog.getExistingDirectory(self, "Index audio folder or projects", str(Path.cwd()))
        if not folder:
            return
        self.library_index_button.setEnabled(False)
        self.library_details.setText("Indexing audio assets and calculating descriptors…")

        def operation():
            with SampleLibrary() as library:
                return library.index_directory(folder)

        worker = RenderWorker(operation)
        self._library_worker = worker

        def finished(result: object) -> None:
            self._library_worker = None
            self.library_index_button.setEnabled(True)
            self.library_details.setText(
                f"Indexed {result.get('assets_indexed', 0)} assets; "
                f"{result.get('projects_indexed', 0)} projects; "
                f"{len(result.get('errors', []))} errors."
            )
            self._search_library()

        def failed(message: str) -> None:
            self._library_worker = None
            self.library_index_button.setEnabled(True)
            self._show_error(message)

        worker.signals.finished.connect(finished)
        worker.signals.error.connect(failed)
        QThreadPool.globalInstance().start(worker)

    def _search_library(self) -> None:
        from reawarp.library.store import SampleLibrary

        try:
            with SampleLibrary() as library:
                results = library.search(
                    query=self.library_query.text() or None,
                    asset_type=None if self.library_type.currentText() == "all" else self.library_type.currentText(),
                    role=None if self.library_role.currentText() == "all" else self.library_role.currentText(),
                    limit=100,
                )
        except Exception as exc:
            self._show_error(f"Library search failed: {exc}")
            return

        self.library_results.blockSignals(True)
        self.library_results.clear()
        for asset in results:
            self.library_results.addItem(
                f"{asset.file_name} · {asset.asset_type} · {asset.role or 'unassigned'} · {asset.duration_seconds:.2f}s · {asset.asset_id[:8]}",
                asset.asset_id,
            )
        self.library_results.blockSignals(False)
        if results:
            self.library_results.setCurrentIndex(0)
        else:
            self.library_preview.set_audio(None)
        self.library_details.setText(f"{len(results)} result(s)")

    def _inspect_library_asset(self, *_args: Any) -> None:
        from reawarp.library.store import SampleLibrary

        asset_id = self.library_results.currentData()
        if not asset_id:
            self.library_preview.set_audio(None)
            return
        try:
            with SampleLibrary() as library:
                asset = library.get_asset(asset_id)
            if asset is None:
                self.library_details.setText("Asset record not found.")
                return
            features = asset.features
            self.library_details.setText(
                f"{asset.file_name} · {asset.asset_type}/{asset.role or 'unassigned'} · "
                f"{asset.duration_seconds:.2f}s · centroid {features.get('spectral_centroid_hz', 0.0):.0f} Hz · "
                f"onsets {features.get('onset_density_per_second', 0.0):.2f}/s\\n{asset.path}"
            )
            self.library_preview.set_audio(read_sample(asset.path, asset.analysis_sample_rate), asset.analysis_sample_rate)
        except Exception as exc:
            self.library_details.setText(f"Preview failed: {exc}")

    def _search_similar_library(self) -> None:
        from reawarp.library.store import SampleLibrary

        asset_id = self.library_results.currentData()
        if not asset_id:
            return
        try:
            with SampleLibrary() as library:
                results = library.search(similar_to=asset_id, limit=30)
        except Exception as exc:
            self._show_error(f"Similarity search failed: {exc}")
            return
        self.library_results.blockSignals(True)
        self.library_results.clear()
        for asset in results:
            self.library_results.addItem(f"{asset.file_name} · similarity {asset.similarity:.3f}", asset.asset_id)
        self.library_results.blockSignals(False)
        if results:
            self.library_results.setCurrentIndex(0)

    def _create_library_collection(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        from reawarp.library.store import SampleLibrary

        name, accepted = QInputDialog.getText(self, "New collection", "Collection name:")
        if not accepted or not name.strip():
            return
        with SampleLibrary() as library:
            library.create_collection(name.strip())
        self.library_details.setText(f"Created collection: {name.strip()}")

    def _add_to_library_collection(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        from reawarp.library.store import SampleLibrary

        asset_id = self.library_results.currentData()
        if not asset_id:
            return
        with SampleLibrary() as library:
            names = [row["name"] for row in library.collections()]
        if not names:
            self._show_error("Create a collection first.")
            return
        name, accepted = QInputDialog.getItem(self, "Add to collection", "Collection:", names, 0, False)
        if not accepted:
            return
        with SampleLibrary() as library:
            library.add_to_collection(name, [asset_id])
        self.library_details.setText(f"Added selected asset to {name}")

    def _retag_library(self) -> None:
        from reawarp.library.store import SampleLibrary

        with SampleLibrary() as library:
            count = library.retag_existing_samples()
        self.library_details.setText(f"Updated semantic tags for {count} sample(s)")

    def _build_tray_icon(self) -> None:
        icon_path = Path(__file__).resolve().parents[3] / "resources" / "reawarp.ico"
        icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
        if icon.isNull():
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#8fb8ed"), 3))
            painter.setBrush(QColor("#171b22"))
            painter.drawRoundedRect(5, 5, 54, 54, 10, 10)
            painter.setPen(QPen(QColor("#f0f4fa"), 3))
            painter.drawLine(18, 18, 18, 46)
            painter.drawLine(18, 18, 43, 18)
            painter.drawLine(43, 18, 43, 46)
            painter.drawLine(18, 32, 43, 32)
            painter.end()
            icon = QIcon(pixmap)
        self.setWindowIcon(icon)
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if not self._tray_available:
            return
        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip("Reawarp — 再変形")
        menu = QMenu(self)
        show_action = QAction("Show Reawarp", self)
        show_action.triggered.connect(self._restore_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_application)
        menu.addAction(quit_action)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._tray_activated)
        self._tray_icon.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_application(self) -> None:
        self.player.stop()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        QApplication.instance().quit()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and self._tray_available:
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        if self._tray_available and self._tray_icon is not None:
            event.ignore()
            self.hide()
            return
        self.player.stop()
        super().closeEvent(event)

'''
    s = replace_once(s,
        '    def _build_transport_bar(self) -> QWidget:\n',
        library_methods + '    def _build_transport_bar(self) -> QWidget:\n', p)
    s = replace_once(s,
        '        self.header_state.setText("RENDERING…" if busy else "OFFLINE RENDER ENGINE")\n',
        '        self.header_state.setText("RENDERING…" if busy else "OFFLINE COMPOSITION ENGINE")\n', p)
    changes[p] = s

    p = "src/reawarp/ui/__main__.py"
    s = read(p)
    s = replace_once(s,
        '    window = MainWindow()\n    window.show()\n',
        '    window = MainWindow()\n'
        '    app.setQuitOnLastWindowClosed(not window._tray_available)\n'
        '    app.setWindowIcon(window.windowIcon())\n'
        '    window.show()\n', p)
    changes[p] = s

    p = "pyproject.toml"
    changes[p] = replace_once(read(p), 'version = "0.6.0"', 'version = "0.7.0"', p)
    p = "src/reawarp/__init__.py"
    changes[p] = replace_once(read(p), '__version__ = "0.6.0"', '__version__ = "0.7.0"', p)
    p = "src/reawarp/core/project.py"
    changes[p] = replace_once(read(p), '"application_version": "0.6.0"', '"application_version": "0.7.0"', p)

    p = "tests/test_engine.py"
    s = read(p)
    s = replace_once(s,
        '    assert variant.metadata["variation"] == {"stem": "kick", "index": 2}\n',
        '    assert variant.metadata["variation"] == {"stem": "kick", "index": 2}\n'
        '    assert variant.metadata["composition_plan"] == original.metadata["composition_plan"]\n', p)
    s += r'''

def test_composition_plan_and_45_second_render_are_reproducible():
    config = GenerationConfig(
        duration=45.0, bpm=137, sample_rate=22_050, seed="long-form-seed",
        structure="episodic", composition_energy=0.72, composition_variation=0.8,
    )
    first = ReawarpEngine().generate(config)
    second = ReawarpEngine().generate(config)
    assert first.frame_count == 45 * 22_050
    assert first.metadata["composition_plan"] == second.metadata["composition_plan"]
    assert first.metadata["composition_plan"]["sections"][-1]["end_seconds"] == pytest.approx(45.0)
    for name in first.stems:
        assert np.array_equal(first.stems[name], second.stems[name])


def test_duration_upper_bound_is_45_seconds():
    assert GenerationConfig(duration=45.0).frame_count == 45 * 48_000
    with pytest.raises(ValueError):
        GenerationConfig(duration=45.1)
'''
    changes[p] = s

    p = "tests/test_library.py"
    s = read(p)
    s += r'''

def test_semantic_sample_tags_and_retag_existing_records(tmp_path):
    sample_rate = 22_050
    folder = tmp_path / "percussion"
    folder.mkdir()
    path = write_wav(
        folder / "amen_break_loop.wav",
        _pulse_audio(sample_rate, 2.0, 0.5),
        sample_rate,
        16,
    )
    with SampleLibrary(":memory:") as library:
        asset = library.index_file(path)
        assert {"break", "percussion"}.issubset(set(asset.tags))
        library._connection.execute(
            "UPDATE assets SET tags_json = ? WHERE asset_id = ?",
            ('["sample","wav"]', asset.asset_id),
        )
        library._connection.commit()
        assert library.search(tags=("percussion",)) == []
        assert library.retag_existing_samples() == 1
        refreshed = library.get_asset(asset.asset_id)
        assert refreshed is not None
        assert {"break", "percussion"}.issubset(set(refreshed.tags))
'''
    changes[p] = s

    p = "tests/test_ui.py"
    s = read(p)
    s = replace_once(s,
        '    assert config.duration == 12\n',
        '    assert config.duration == 12\n'
        '    assert config.structure == "evolving"\n'
        '    assert config.composition_energy == pytest.approx(0.62)\n'
        '    assert config.composition_variation == pytest.approx(0.45)\n'
        '    window.duration.setValue(45.0)\n'
        '    assert window._read_config().duration == pytest.approx(45.0)\n', p)
    s = replace_once(s,
        '    assert window.tabs.count() == 3\n'
        '    assert [window.tabs.tabText(i) for i in range(3)] == [\n'
        '        "GENERATOR", "BREAK LAB", "STEM MIXER"\n'
        '    ]\n',
        '    assert window.tabs.count() == 4\n'
        '    assert [window.tabs.tabText(i) for i in range(4)] == [\n'
        '        "GENERATOR", "BREAK LAB", "STEM MIXER", "LIBRARY"\n'
        '    ]\n'
        '    assert window.windowIcon().isNull() is False\n', p)
    changes[p] = s

    p = "README.md"
    s = read(p)
    s = replace_once(s, '- Duration: 5–20 seconds.\n', '- Duration: 5–45 seconds.\n', p)
    s = replace_once(s,
        '- Independent random streams per generator and synthesis/profile lane.\n',
        '- Independent random streams per generator and synthesis/profile lane.\n'
        '- A section-level composition director with five formal structures and exact 5–45 second renders.\n'
        '- Separate composition energy, variation, and local complexity controls; stem regeneration freezes the section plan.\n', p)
    s = replace_once(s,
        'The main workspaces are Generator, Break Lab, and Stem Mixer.',
        'The main workspaces are Generator, Break Lab, Stem Mixer, and Library.', p)
    s = replace_once(s,
        '    reawarp-library search --tag percussion --tag idm\n',
        '    reawarp-library search --tag percussion --tag idm\n'
        '    reawarp-library retag\n', p)
    s += r'''

## Composition Director (M7)

The first M7 increment adds five formal structures: `evolving`, `additive`, `subtractive`, `episodic`, and `drift`. It records a deterministic section plan in `project.json` and lets that plan guide role activation, density, melody register, texture, and ambience.

    reawarp --duration 45 --structure evolving --energy 0.62 --variation 0.45 --seed 211 --output output/long-evolving
    reawarp --duration 32 --structure episodic --energy 0.72 --variation 0.80 --seed 518 --output output/episodic

Composition-level variation changes section durations and bounded macro/register decisions; break phrase variation remains independent. See `docs/M7.md` for implementation boundaries and follow-on M7.1–M7.4 work.
'''
    changes[p] = s

    p = "docs/M6.md"
    s = read(p)
    s += r'''

### Retag existing sample records

For databases indexed before semantic sample tags were introduced, run:

    reawarp-library retag

This re-applies conservative filename/folder-derived categories such as percussion, kick, snare, hat, break, texture, and melody. These are heuristics; explicit tagging remains preferable for ambiguous material.
'''
    changes[p] = s
    changes["docs/M7.md"] = "# M7 — Composition Director, Long-Form Generation, and Desktop Workflow\n\nStatus: first composition-aware rendering increment.\n\n## 1. Why M7 follows M6\n\nThe Field Guide describes IDM as a relationship between stable reference points and controlled change, not simply maximum rhythmic density. The Advanced Composition Appendix formalises a hierarchy:\n\n1. Event.\n2. Pattern.\n3. Phrase.\n4. Section.\n5. Composition.\n\nM7 adds a section director above the existing event generators. It decides the formal situation and macro targets; specialised generators continue to create local events and sound buffers.\n\n## 2. Formal trajectories\n\n| Structure | Formal behaviour |\n|---|---|\n| `evolving` | Intro, foundation, expansion, mutation, reassembly, outro |\n| `additive` | Accumulation toward a peak, then release |\n| `subtractive` | Full opening gradually exposes and dissolves material |\n| `episodic` | Contrasting scenes, suspension, and return |\n| `drift` | Related states with gradual, bounded changes |\n\nSection durations vary deterministically within bounded limits. Boundaries are contiguous, and the final section ends at the exact requested duration.\n\n## 3. Section plan\n\nEach section records exact time boundaries, energy, density, brightness, instability, spatial openness, role activation, motif treatment, register guidance, and a phrase-length hint. The plan is stored in `project.json` metadata as `composition_plan`.\n\n## 4. Renderer behaviour\n\n- Kick anchors are removed in intro, suspension, and outro-like sections.\n- Supporting snare and hat activity is thinned in sparse sections.\n- Melody event contours are retained, while selected sections may omit the line or shift its register.\n- Noise texture follows section activation and density.\n- Ambience follows the section's spatial openness.\n- Imported break triggers are suppressed in selected sparse states.\n- The section plan uses its own deterministic random stream, so changing a stem does not change unrelated arrangement decisions.\n\nThis first increment uses role activation and density gates. It is not yet a full motif planner or counterpoint system.\n\n## 5. Duration and variation\n\nGenerationConfig, CLI, and GUI accept 5–45 seconds. Fixed-time rendering still produces exactly `round(duration * sample_rate)` frames. This does not yet provide a bar-count duration mode.\n\nComposition-level variation changes section weights and bounded macro/register perturbations. It is not a global probability for extra hits. Break-specific phrase variation remains a separate lower-level control.\n\nEnergy, density, brightness, instability, and space are separate values. Energy does not map to master gain.\n\n## 6. Desktop changes\n\nThe desktop app exposes formal structure, energy, variation, and 45-second duration controls; groups Generator controls into Composition, Sound, and Break pages; adds a local Library workspace; and provides a Reawarp window/tray icon with Show and Quit actions. The tray behaviour is conditional on the operating system exposing a tray host.\n\n## 7. M6 sample tag repair\n\nNew standalone samples receive conservative semantic categories from filename and folder tokens. Existing databases can run `reawarp-library retag` to add those categories to already-indexed samples. These tags are heuristics, not a replacement for explicit user tagging.\n\n## 8. Comparison with the IDM guides\n\n| Principle | Current state |\n|---|---|\n| Independent deterministic random streams | Implemented for generator lanes; section decisions use a separate named stream |\n| Stable pulse and controlled deviations | Partial: existing sixteenth-grid grammars plus section suppression |\n| Event/pattern/phrase/section hierarchy | Partial: event generators and section plans exist; phrase generation is not yet a general object model |\n| Long-form pacing | First increment: five formal structures |\n| Energy distinct from loudness | Macro values are separate; energy is not master gain |\n| Motif continuity through transformations | Partial: existing geometric melody, register changes, and motif state labels |\n| Counterpoint and independent cycle relationships | Not yet a general planner |\n| Candidate generation, scoring, audition, and freeze | Not yet implemented |\n| Score automation rendered over time | Not yet connected to the offline renderer |\n| Full formal closure / motif dissolution | Partial: role reduction exists, but no complete motif decay planner |\n\n## 9. Follow-on work\n\n1. **M7.1 — Motif objects:** identity across rhythm, contour, duration, articulation, register, timbre, and space; transformation operators.\n2. **M7.2 — Phrase candidates:** hard constraints, continuity/novelty/groove scoring, audition, and freeze.\n3. **M7.3 — Automation and clocks:** connect score lanes to phrase/section macro curves while preserving separate beat, sample, wall, and UI clocks.\n4. **M7.4 — Composition editor:** section map, macro curves, motif inspector, candidate comparison, and library integration.\n\nM7 is a principled start, not a claim that every composition concept in the Appendix is complete.\n"
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the Reawarp M7 update.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not (ROOT / "pyproject.toml").is_file():
        parser.error("Run from the root of the eli_lab-reawarp repository.")
    version_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'version = "0.7.0"' in version_text and (ROOT / "src/reawarp/composition/director.py").exists():
        print("M7 appears to be already installed; no changes made.")
        return 0
    if 'version = "0.6.0"' not in version_text:
        parser.error("This updater targets the Reawarp 0.6.0 source tree.")

    changes = prepare_changes()
    new_files = {
        "src/reawarp/composition/__init__.py": '"""Composition-level planning and formal state."""\n\nfrom reawarp.composition.director import (\n    CompositionPlan,\n    SectionPlan,\n    build_composition_plan,\n    section_for_time,\n)\n\n__all__ = [\n    "CompositionPlan",\n    "SectionPlan",\n    "build_composition_plan",\n    "section_for_time",\n]\n',
        "src/reawarp/composition/director.py": '"""Deterministic section and phrase planning for composition-level generation."""\n\nfrom __future__ import annotations\n\nimport hashlib\nfrom dataclasses import asdict, dataclass\nfrom typing import Any\n\nimport numpy as np\n\n\n@dataclass(frozen=True, slots=True)\nclass SectionPlan:\n    index: int\n    name: str\n    start_seconds: float\n    end_seconds: float\n    energy: float\n    density: float\n    brightness: float\n    instability: float\n    space: float\n    kick: bool\n    melody: bool\n    texture: bool\n    ambience: bool\n    motif_mode: str\n    motif_register_semitones: int\n    percussion_density_scale: float\n    phrase_bars: int\n\n    @property\n    def duration_seconds(self) -> float:\n        return self.end_seconds - self.start_seconds\n\n    def to_dict(self) -> dict[str, Any]:\n        return asdict(self)\n\n\n@dataclass(frozen=True, slots=True)\nclass CompositionPlan:\n    duration_seconds: float\n    bpm: float\n    seed: int | str\n    structure: str\n    sections: tuple[SectionPlan, ...]\n\n    def to_dict(self) -> dict[str, Any]:\n        return {\n            "duration_seconds": self.duration_seconds,\n            "bpm": self.bpm,\n            "seed": self.seed,\n            "structure": self.structure,\n            "sections": [section.to_dict() for section in self.sections],\n        }\n\n\n# name, relative duration weight, target energy, motif treatment\nSTRUCTURES: dict[str, tuple[tuple[str, float, float, str], ...]] = {\n    "evolving": (\n        ("INTRO", 0.13, 0.20, "fragment"),\n        ("FOUNDATION", 0.24, 0.43, "present"),\n        ("EXPANSION", 0.25, 0.69, "develop"),\n        ("MUTATION", 0.18, 0.82, "fragment"),\n        ("REASSEMBLY", 0.14, 0.56, "return"),\n        ("OUTRO", 0.06, 0.12, "dissolve"),\n    ),\n    "additive": (\n        ("INTRO", 0.16, 0.18, "fragment"),\n        ("FOUNDATION", 0.22, 0.38, "present"),\n        ("EXPANSION", 0.30, 0.62, "develop"),\n        ("PEAK", 0.22, 0.84, "develop"),\n        ("OUTRO", 0.10, 0.14, "dissolve"),\n    ),\n    "subtractive": (\n        ("FULL", 0.22, 0.78, "present"),\n        ("UNRAVEL", 0.28, 0.58, "fragment"),\n        ("EXPOSE", 0.22, 0.34, "fragment"),\n        ("RESIDUAL", 0.18, 0.18, "dissolve"),\n        ("OUTRO", 0.10, 0.08, "dissolve"),\n    ),\n    "episodic": (\n        ("SCENE_A", 0.22, 0.44, "present"),\n        ("SUSPENSION", 0.14, 0.16, "fragment"),\n        ("SCENE_B", 0.26, 0.72, "develop"),\n        ("CONTRAST", 0.18, 0.35, "fragment"),\n        ("REASSEMBLY", 0.20, 0.57, "return"),\n    ),\n    "drift": (\n        ("ORIGIN", 0.20, 0.30, "present"),\n        ("DRIFT_A", 0.20, 0.50, "develop"),\n        ("DRIFT_B", 0.20, 0.66, "develop"),\n        ("DRIFT_C", 0.20, 0.42, "fragment"),\n        ("RETURN", 0.20, 0.52, "return"),\n    ),\n}\n\n\ndef _normalised_weights(template, rng: np.random.Generator, variation: float) -> np.ndarray:\n    weights = np.asarray([item[1] for item in template], dtype=np.float64)\n    if variation > 0.0 and len(weights) > 2:\n        noise = rng.normal(0.0, 0.18 * variation, size=len(weights))\n        noise -= np.mean(noise)\n        weights *= np.exp(np.clip(noise, -0.35, 0.35))\n    weights = np.maximum(weights, 0.07)\n    return weights / np.sum(weights)\n\n\ndef build_composition_plan(\n    *,\n    duration_seconds: float,\n    bpm: float,\n    seed: int | str,\n    structure: str = "evolving",\n    energy: float = 0.62,\n    variation: float = 0.45,\n) -> CompositionPlan:\n    """Create a seeded formal plan covering the exact requested duration."""\n    if duration_seconds <= 0.0 or bpm <= 0.0:\n        raise ValueError("duration_seconds and bpm must be positive")\n    if structure not in STRUCTURES:\n        raise ValueError(f"unknown structure: {structure}")\n    if not 0.0 <= energy <= 1.0 or not 0.0 <= variation <= 1.0:\n        raise ValueError("energy and variation must be between zero and one")\n\n    seed_word = int.from_bytes(\n        hashlib.blake2b(str(seed).encode("utf-8"), digest_size=4).digest(),\n        "little",\n    )\n    rng = np.random.default_rng(np.random.SeedSequence([seed_word, 0x52454157]))\n    template = STRUCTURES[structure]\n    weights = _normalised_weights(template, rng, variation)\n    bar_seconds = 240.0 / float(bpm)\n    boundaries = np.concatenate(([0.0], np.cumsum(weights) * duration_seconds))\n    boundaries[-1] = float(duration_seconds)\n    sections: list[SectionPlan] = []\n\n    for index, ((name, _weight, target_energy, motif_mode), start, end) in enumerate(\n        zip(template, boundaries[:-1], boundaries[1:], strict=True)\n    ):\n        section_energy = float(np.clip(\n            0.68 * target_energy + 0.32 * energy\n            + rng.normal(0.0, 0.035 * variation),\n            0.0, 1.0,\n        ))\n        density = float(np.clip(\n            0.08 + 0.68 * section_energy\n            + rng.normal(0.0, 0.035 * variation),\n            0.04, 0.78,\n        ))\n        brightness = float(np.clip(\n            0.16 + 0.69 * section_energy\n            + rng.normal(0.0, 0.08 * variation),\n            0.08, 0.92,\n        ))\n        instability = float(np.clip(\n            0.08 + 0.56 * section_energy\n            + rng.uniform(-0.12, 0.12) * variation,\n            0.0, 0.78,\n        ))\n        space = float(np.clip(\n            1.0 - 0.76 * density + rng.uniform(-0.08, 0.08) * variation,\n            0.12, 1.0,\n        ))\n\n        upper_name = name.upper()\n        is_outro = "OUTRO" in upper_name or "RESIDUAL" in upper_name\n        is_suspension = "SUSPENSION" in upper_name or "EXPOSE" in upper_name\n        is_intro = upper_name == "INTRO"\n        kick = not (is_outro or is_suspension or is_intro)\n        melody = not is_outro and motif_mode != "dissolve"\n        texture = not is_outro\n        ambience = True\n        if is_suspension:\n            kick = False\n            melody = motif_mode == "present"\n\n        phrase_bars = max(1, int(round(float(end - start) / bar_seconds)))\n        register_shift = 0\n        if variation > 0.05 and motif_mode in ("develop", "fragment"):\n            register_shift = int(rng.choice((-12, -7, 0, 5, 12)))\n\n        # Retain anchors but allocate less probability to supporting ornaments\n        # as the section becomes denser.\n        support_scale = float(np.clip(0.98 - 0.43 * density, 0.52, 0.96))\n        if section_energy > 0.78 and density > 0.62:\n            texture = bool(rng.random() < 0.35)\n\n        sections.append(SectionPlan(\n            index=index,\n            name=name,\n            start_seconds=float(start),\n            end_seconds=float(end),\n            energy=section_energy,\n            density=density,\n            brightness=brightness,\n            instability=instability,\n            space=space,\n            kick=kick,\n            melody=melody,\n            texture=texture,\n            ambience=ambience,\n            motif_mode=motif_mode,\n            motif_register_semitones=register_shift,\n            percussion_density_scale=support_scale,\n            phrase_bars=phrase_bars,\n        ))\n\n    return CompositionPlan(\n        duration_seconds=float(duration_seconds),\n        bpm=float(bpm),\n        seed=seed,\n        structure=structure,\n        sections=tuple(sections),\n    )\n\n\ndef section_for_time(plan: CompositionPlan, time_seconds: float) -> SectionPlan:\n    """Return the containing section, clamping at the start and end."""\n    if not plan.sections:\n        raise ValueError("composition plan has no sections")\n    value = float(time_seconds)\n    for section in plan.sections:\n        if section.start_seconds <= value < section.end_seconds:\n            return section\n    return plan.sections[0] if value < 0.0 else plan.sections[-1]\n',
        "docs/M7.md": "# M7 — Composition Director, Long-Form Generation, and Desktop Workflow\n\nStatus: first composition-aware rendering increment.\n\n## 1. Why M7 follows M6\n\nThe Field Guide describes IDM as a relationship between stable reference points and controlled change, not simply maximum rhythmic density. The Advanced Composition Appendix formalises a hierarchy:\n\n1. Event.\n2. Pattern.\n3. Phrase.\n4. Section.\n5. Composition.\n\nM7 adds a section director above the existing event generators. It decides the formal situation and macro targets; specialised generators continue to create local events and sound buffers.\n\n## 2. Formal trajectories\n\n| Structure | Formal behaviour |\n|---|---|\n| `evolving` | Intro, foundation, expansion, mutation, reassembly, outro |\n| `additive` | Accumulation toward a peak, then release |\n| `subtractive` | Full opening gradually exposes and dissolves material |\n| `episodic` | Contrasting scenes, suspension, and return |\n| `drift` | Related states with gradual, bounded changes |\n\nSection durations vary deterministically within bounded limits. Boundaries are contiguous, and the final section ends at the exact requested duration.\n\n## 3. Section plan\n\nEach section records exact time boundaries, energy, density, brightness, instability, spatial openness, role activation, motif treatment, register guidance, and a phrase-length hint. The plan is stored in `project.json` metadata as `composition_plan`.\n\n## 4. Renderer behaviour\n\n- Kick anchors are removed in intro, suspension, and outro-like sections.\n- Supporting snare and hat activity is thinned in sparse sections.\n- Melody event contours are retained, while selected sections may omit the line or shift its register.\n- Noise texture follows section activation and density.\n- Ambience follows the section's spatial openness.\n- Imported break triggers are suppressed in selected sparse states.\n- The section plan uses its own deterministic random stream, so changing a stem does not change unrelated arrangement decisions.\n\nThis first increment uses role activation and density gates. It is not yet a full motif planner or counterpoint system.\n\n## 5. Duration and variation\n\nGenerationConfig, CLI, and GUI accept 5–45 seconds. Fixed-time rendering still produces exactly `round(duration * sample_rate)` frames. This does not yet provide a bar-count duration mode.\n\nComposition-level variation changes section weights and bounded macro/register perturbations. It is not a global probability for extra hits. Break-specific phrase variation remains a separate lower-level control.\n\nEnergy, density, brightness, instability, and space are separate values. Energy does not map to master gain.\n\n## 6. Desktop changes\n\nThe desktop app exposes formal structure, energy, variation, and 45-second duration controls; groups Generator controls into Composition, Sound, and Break pages; adds a local Library workspace; and provides a Reawarp window/tray icon with Show and Quit actions. The tray behaviour is conditional on the operating system exposing a tray host.\n\n## 7. M6 sample tag repair\n\nNew standalone samples receive conservative semantic categories from filename and folder tokens. Existing databases can run `reawarp-library retag` to add those categories to already-indexed samples. These tags are heuristics, not a replacement for explicit user tagging.\n\n## 8. Comparison with the IDM guides\n\n| Principle | Current state |\n|---|---|\n| Independent deterministic random streams | Implemented for generator lanes; section decisions use a separate named stream |\n| Stable pulse and controlled deviations | Partial: existing sixteenth-grid grammars plus section suppression |\n| Event/pattern/phrase/section hierarchy | Partial: event generators and section plans exist; phrase generation is not yet a general object model |\n| Long-form pacing | First increment: five formal structures |\n| Energy distinct from loudness | Macro values are separate; energy is not master gain |\n| Motif continuity through transformations | Partial: existing geometric melody, register changes, and motif state labels |\n| Counterpoint and independent cycle relationships | Not yet a general planner |\n| Candidate generation, scoring, audition, and freeze | Not yet implemented |\n| Score automation rendered over time | Not yet connected to the offline renderer |\n| Full formal closure / motif dissolution | Partial: role reduction exists, but no complete motif decay planner |\n\n## 9. Follow-on work\n\n1. **M7.1 — Motif objects:** identity across rhythm, contour, duration, articulation, register, timbre, and space; transformation operators.\n2. **M7.2 — Phrase candidates:** hard constraints, continuity/novelty/groove scoring, audition, and freeze.\n3. **M7.3 — Automation and clocks:** connect score lanes to phrase/section macro curves while preserving separate beat, sample, wall, and UI clocks.\n4. **M7.4 — Composition editor:** section map, macro curves, motif inspector, candidate comparison, and library integration.\n\nM7 is a principled start, not a claim that every composition concept in the Appendix is complete.\n",
    }
    for name, content in new_files.items():
        target = ROOT / name
        if target.exists() and target.read_text(encoding="utf-8") != content:
            raise RuntimeError(
                f"Refusing to overwrite a different existing file: {name}. "
                "Move it aside or compare it manually first."
            )
    if args.dry_run:
        print(f"Dry run passed: {len(changes)} existing files and {len(new_files)} new files.")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_ROOT / stamp
    backup.mkdir(parents=True, exist_ok=False)
    for name in changes:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    for name, content in changes.items():
        (ROOT / name).write_text(content, encoding="utf-8", newline="\n")
    for name, content in new_files.items():
        target = ROOT / name
        if target.exists():
            continue  # The bundle itself may already have overlaid this exact file.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    print("M7 update applied.")
    print(f"Original files backed up to: {backup}")
    print('Install: python -m pip install -e ".[dev,audio,m4,midi]"')
    print("Test:    python -m pytest -q")
    print("Render:  reawarp --duration 45 --structure episodic --energy 0.72 --variation 0.8 --seed 211 --sample-rate 22050 --output output/m7-smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
