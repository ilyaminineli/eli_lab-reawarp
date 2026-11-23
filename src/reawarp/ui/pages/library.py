"""Local sample and stem library workspace."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from reawarp.samples.io import read_sample
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
        search_button = QPushButton("SEARCH")
        search_button.clicked.connect(self._search)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.results = QComboBox()
        self.results.currentIndexChanged.connect(self._preview_selected)
        layout.addWidget(self.results)
        self.details = QLabel(
            "Index an audio folder to search samples, generated stems, and project masters."
        )
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.preview = AudioPreview()
        layout.addWidget(self.preview, 1)

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

    def _search(self) -> None:
        from reawarp.library.store import SampleLibrary

        asset_type = self.asset_type.currentText()
        role = self.role.currentText()
        try:
            with SampleLibrary() as library:
                assets = library.search(
                    query=self.query.text().strip() or None,
                    asset_type=None if asset_type == "all" else asset_type,
                    role=None if role == "all" else role,
                    limit=100,
                )
            self.results.blockSignals(True)
            self.results.clear()
            for asset in assets:
                self.results.addItem(
                    f"{asset.file_name} · {asset.asset_type} · {asset.duration_seconds:.2f}s",
                    asset.asset_id,
                )
            self.results.blockSignals(False)
            self.details.setText(f"{len(assets)} matching asset(s)")
            if assets:
                self.results.setCurrentIndex(0)
            else:
                self.preview.set_audio(None)
        except Exception as exc:
            self.results.blockSignals(False)
            self.details.setText(f"Library search failed: {exc}")

    def _preview_selected(self, *_args: Any) -> None:
        from reawarp.library.store import SampleLibrary

        asset_id = self.results.currentData()
        if not asset_id:
            return
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
