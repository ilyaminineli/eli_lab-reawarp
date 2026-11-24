"""Local sample and stem library workspace."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget, QInputDialog,
)

from reawarp.samples.io import read_sample
from reawarp.samples.iro import IROAsset, load_iro_assets, verify_iro_assets
from reawarp.ui.visualization import AudioPreview
from reawarp.ui.workers import RenderWorker


class LibraryPage(QWidget):
    """Browse, index, search, and audition local Reawarp audio material."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from reawarp.library.store import default_database_path

        self._worker: RenderWorker | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("LOCAL MATERIAL / STEM LIBRARY")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.database_label = QLabel(str(default_database_path()))
        self.database_label.setObjectName("muted")
        layout.addWidget(self.database_label)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Choose a sample or project folder to index")
        folder_row.addWidget(self.folder, 1)
        browse = QPushButton("BROWSE…")
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse)
        self.index_button = QPushButton("INDEX")
        self.index_button.clicked.connect(self._index_folder)
        folder_row.addWidget(self.index_button)
        layout.addLayout(folder_row)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Find by filename, path, metadata, or tags")
        search_row.addWidget(self.query, 1)
        self.asset_type = QComboBox()
        self.asset_type.addItems(["all", "sample", "stem", "master"])
        search_row.addWidget(self.asset_type)
        self.role = QComboBox()
        self.role.addItems([
            "all", "kick", "snare", "hat", "break", "melody", "ambience", "noise_texture"
        ])
        search_row.addWidget(self.role)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("required tags, comma separated")
        search_row.addWidget(self.tags)
        search_button = QPushButton("SEARCH")
        search_button.clicked.connect(self._search)
        search_row.addWidget(search_button)
        self.similar_button = QPushButton("SIMILAR")
        self.similar_button.setToolTip("Find assets with similar timbral and rhythmic descriptors.")
        self.similar_button.clicked.connect(self._search_similar)
        search_row.addWidget(self.similar_button)
        layout.addLayout(search_row)

        iro_row = QHBoxLayout()
        self.iro_source = QComboBox()
        self.iro_source.addItems([
            "ALL IRO", "DRUM KIT", "MATH ENTITIES", "SOUND LAB", "SOUND FX"
        ])
        iro_row.addWidget(QLabel("IRO CATALOG"))
        iro_row.addWidget(self.iro_source, 1)
        self.iro_search = QLineEdit()
        self.iro_search.setPlaceholderText("family, articulation or asset name")
        iro_row.addWidget(self.iro_search, 2)
        self.iro_load_button = QPushButton("BROWSE IRO")
        self.iro_load_button.clicked.connect(self._search_iro)
        iro_row.addWidget(self.iro_load_button)
        self.iro_verify_button = QPushButton("VERIFY HASHES")
        self.iro_verify_button.clicked.connect(self._verify_iro)
        iro_row.addWidget(self.iro_verify_button)
        layout.addLayout(iro_row)

        collection_row = QHBoxLayout()
        self.collections = QComboBox()
        self.collections.setMinimumWidth(180)
        collection_row.addWidget(self.collections, 1)
        create_collection = QPushButton("NEW COLLECTION")
        create_collection.clicked.connect(self._create_collection)
        collection_row.addWidget(create_collection)
        add_collection = QPushButton("ADD SELECTED")
        add_collection.clicked.connect(self._add_to_collection)
        collection_row.addWidget(add_collection)
        show_collection = QPushButton("SHOW")
        show_collection.clicked.connect(self._show_collection)
        collection_row.addWidget(show_collection)
        layout.addLayout(collection_row)

        self.results = QComboBox()
        self.results.currentIndexChanged.connect(self._preview_selected)
        layout.addWidget(self.results)
        self._iro_assets: dict[str, IROAsset] = {}
        self._result_source = "library"
        self.details = QLabel(
            "Index an audio folder to search samples, generated stems, and project masters."
        )
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.preview = AudioPreview()
        layout.addWidget(self.preview, 1)
        self._refresh_collections()

    def _search_iro(self) -> None:
        scope = self.iro_source.currentText()
        catalog = load_iro_assets()
        packs = {
            "DRUM KIT": {"experimental-drum-kit-211"},
            "MATH ENTITIES": {"entities"},
            "SOUND LAB": {"sound-lab-211"},
            "SOUND FX": {"sound-fx-211"},
        }
        if scope in packs:
            catalog = [item for item in catalog if item.pack in packs[scope]]
        query = self.iro_search.text().strip().lower()
        if query:
            catalog = [
                item for item in catalog
                if query in " ".join((
                    item.relative_path, item.role, item.family, item.articulation, item.pack
                )).lower()
            ]
        self._iro_assets = {item.asset_id: item for item in catalog}
        self._result_source = "iro"
        self.results.blockSignals(True)
        self.results.clear()
        for item in catalog:
            duration = f"{item.duration_seconds:.2f}s" if item.duration_seconds is not None else "duration n/a"
            availability = "PLAYABLE" if item.available else "INDEX ONLY · WAV MISSING"
            self.results.addItem(
                f"{item.family} · {item.articulation or item.role} · {duration} · {availability}",
                item.asset_id,
            )
        self.results.blockSignals(False)
        self.details.setText(
            f"{len(catalog)} IRO manifest entries · "
            f"{sum(item.available for item in catalog)} WAVs available · "
            f"{sum(not item.available for item in catalog)} WAVs missing · "
            "source pack metadata retained · originals are read-only"
        )
        if catalog:
            self.results.setCurrentIndex(0)
        else:
            self.preview.set_audio(None)

    def _verify_iro(self) -> None:
        try:
            report = verify_iro_assets()
            self.details.setText(
                f"IRO integrity · {report['verified']} verified · "
                f"{len(report['unverified'])} without supplied hash · "
                f"{len(report['missing'])} missing · {len(report['mismatched'])} mismatch"
            )
        except Exception as exc:
            self.details.setText(f"IRO integrity check failed: {exc}")

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose material folder", self.folder.text() or str(Path.cwd())
        )
        if folder:
            self.folder.setText(folder)

    @staticmethod
    def _index(folder: str) -> dict[str, Any]:
        from reawarp.library.store import SampleLibrary

        with SampleLibrary() as library:
            return library.index_directory(folder)

    def _index_folder(self) -> None:
        folder = self.folder.text().strip()
        if not folder:
            self.details.setText("Choose a folder before indexing.")
            return
        if self._worker is not None:
            return
        self.index_button.setEnabled(False)
        worker = RenderWorker(lambda: self._index(folder))
        self._worker = worker
        worker.signals.finished.connect(self._index_finished)
        worker.signals.error.connect(self._index_failed)
        QThreadPool.globalInstance().start(worker)
        self.details.setText("Indexing audio assets in the local library…")

    def _index_finished(self, result: object) -> None:
        self._worker = None
        self.index_button.setEnabled(True)
        if not isinstance(result, dict):
            self.details.setText("Indexing returned an unexpected result.")
            return
        self.details.setText(
            f"Indexed {result.get('assets_indexed', 0)} assets across "
            f"{result.get('projects_indexed', 0)} projects; "
            f"{len(result.get('errors', []))} file error(s)."
        )
        self._search()

    def _index_failed(self, message: str) -> None:
        self._worker = None
        self.index_button.setEnabled(True)
        self.details.setText(f"Library indexing failed: {message}")

    def _populate_results(self, assets: list[Any], label: str) -> None:
        self.results.blockSignals(True)
        self.results.clear()
        for asset in assets:
            similarity = (
                f" · sim {asset.similarity:.3f}"
                if getattr(asset, "similarity", None) is not None else ""
            )
            self.results.addItem(
                f"{asset.file_name} · {asset.asset_type} · "
                f"{asset.duration_seconds:.2f}s{similarity}",
                asset.asset_id,
            )
        self.results.blockSignals(False)
        self.details.setText(f"{len(assets)} {label}")
        if assets:
            self.results.setCurrentIndex(0)
        else:
            self.preview.set_audio(None)

    def _search(self, similar_to: str | None = None) -> None:
        self._result_source = "library"
        self._iro_assets = {}
        from reawarp.library.store import SampleLibrary

        asset_type = self.asset_type.currentText()
        role = self.role.currentText()
        tags = tuple(
            value.strip() for value in self.tags.text().split(",") if value.strip()
        )
        try:
            with SampleLibrary() as library:
                assets = library.search(
                    query=self.query.text().strip() or None,
                    asset_type=None if asset_type == "all" else asset_type,
                    role=None if role == "all" else role,
                    tags=tags,
                    similar_to=similar_to,
                    limit=100,
                )
            self._populate_results(
                assets, "similar asset(s)" if similar_to else "matching asset(s)"
            )
        except Exception as exc:
            self.details.setText(f"Library search failed: {exc}")

    def _search_similar(self) -> None:
        asset_id = self.results.currentData()
        if not asset_id:
            self.details.setText("Select an indexed asset before searching for similar material.")
            return
        self._search(similar_to=str(asset_id))

    def _refresh_collections(self) -> None:
        from reawarp.library.store import SampleLibrary

        try:
            with SampleLibrary() as library:
                collections = library.collections()
            selected = self.collections.currentText() if hasattr(self, "collections") else ""
            self.collections.blockSignals(True)
            self.collections.clear()
            for collection in collections:
                self.collections.addItem(
                    f"{collection['name']} · {collection['asset_count']}",
                    collection["name"],
                )
            if selected:
                index = self.collections.findData(selected)
                if index >= 0:
                    self.collections.setCurrentIndex(index)
            self.collections.blockSignals(False)
        except Exception as exc:
            self.details.setText(f"Could not load collections: {exc}")

    def _create_collection(self) -> None:
        from reawarp.library.store import SampleLibrary

        name, accepted = QInputDialog.getText(self, "New collection", "Collection name:")
        if not accepted or not name.strip():
            return
        try:
            with SampleLibrary() as library:
                library.create_collection(name.strip())
            self._refresh_collections()
            index = self.collections.findData(name.strip())
            if index >= 0:
                self.collections.setCurrentIndex(index)
            self.details.setText(f"Created collection: {name.strip()}")
        except Exception as exc:
            self.details.setText(f"Could not create collection: {exc}")

    def _add_to_collection(self) -> None:
        from reawarp.library.store import SampleLibrary

        asset_id = self.results.currentData()
        collection = self.collections.currentData()
        if not asset_id or not collection:
            self.details.setText("Select an asset and a collection first.")
            return
        try:
            with SampleLibrary() as library:
                added = library.add_to_collection(str(collection), [str(asset_id)])
            self.details.setText(
                f"Added selected asset to {collection}." if added
                else f"Selected asset is already in {collection}."
            )
            self._refresh_collections()
        except Exception as exc:
            self.details.setText(f"Could not update collection: {exc}")

    def _show_collection(self) -> None:
        from reawarp.library.store import SampleLibrary

        collection = self.collections.currentData()
        if not collection:
            self.details.setText("Create or select a collection first.")
            return
        try:
            with SampleLibrary() as library:
                assets = library.collection_assets(str(collection))
            self._populate_results(assets, f"asset(s) in {collection}")
        except Exception as exc:
            self.details.setText(f"Could not open collection: {exc}")

    def _preview_selected(self, *_args: Any) -> None:
        asset_id = self.results.currentData()
        if not asset_id:
            return
        if self._result_source == "iro":
            asset = self._iro_assets.get(str(asset_id))
            if asset is None:
                return
            meta = asset.metadata or {}
            if not asset.available:
                self.details.setText(
                    f"IRO manifest entry is present, but its WAV is absent: {asset.relative_path}"
                )
                self.preview.set_audio(None)
                return
            self.details.setText(
                f"IRO · {asset.pack} · {asset.relative_path}\\n"
                f"Role {asset.role} · family {asset.family} · articulation {asset.articulation or '—'}\\n"
                f"Release seed {meta.get('seed', asset.seed) or 'n/a'} · "
                f"source feature {asset.source_feature_index if asset.source_feature_index is not None else 'n/a'}"
            )
            try:
                self.preview.set_audio(read_sample(asset.path, 48_000), 48_000)
            except Exception as exc:
                self.details.setText(f"IRO preview failed: {exc}")
            return

        from reawarp.library.store import SampleLibrary
        try:
            with SampleLibrary() as library:
                asset = library.get_asset(str(asset_id))
            if asset is None:
                return
            self.details.setText(
                f"{asset.file_name} · {asset.asset_type} · {asset.role or 'unassigned'} · "
                f"{asset.duration_seconds:.2f}s · "
                f"{asset.features.get('spectral_centroid_hz', 0.0):.0f} Hz centroid"
            )
            self.preview.set_audio(
                read_sample(asset.path, asset.analysis_sample_rate),
                asset.analysis_sample_rate,
            )
        except Exception as exc:
            self.details.setText(f"Preview failed: {exc}")
