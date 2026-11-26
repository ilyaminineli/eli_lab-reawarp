"""SQLite-backed sample/stem library, similarity search, and variation genealogy."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from reawarp.library.features import SUPPORTED_AUDIO_SUFFIXES, analyze_audio_file


def default_database_path() -> Path:
    """Return the per-user Reawarp library location."""
    return Path.home() / ".reawarp" / "library.sqlite3"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset_id_for_path(path: Path) -> str:
    normalized = str(path.resolve()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _similarity_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Return a weighted distance over timbre, dynamics, duration, and rhythm."""

    def number(data: dict[str, Any], key: str, default: float = 0.0) -> float:
        value = data.get(key)
        return float(value) if value is not None else default

    components: list[tuple[float, float]] = []
    components.append(
        (
            abs(
                math.log2(
                    (number(left, "duration_seconds") + 0.02)
                    / (number(right, "duration_seconds") + 0.02)
                )
            )
            / 3.0,
            0.8,
        )
    )
    components.append(
        (
            abs(
                math.log2(
                    (number(left, "spectral_centroid_hz") + 20.0)
                    / (number(right, "spectral_centroid_hz") + 20.0)
                )
            )
            / 2.5,
            1.0,
        )
    )
    components.append(
        (
            abs(
                math.log(
                    (number(left, "spectral_flatness") + 0.003)
                    / (number(right, "spectral_flatness") + 0.003)
                )
            )
            / 4.0,
            0.8,
        )
    )
    components.append(
        (
            abs(
                number(left, "spectral_rolloff85_hz")
                - number(right, "spectral_rolloff85_hz")
            )
            / 8_000.0,
            0.7,
        )
    )
    components.append(
        (abs(number(left, "rms_dbfs") - number(right, "rms_dbfs")) / 36.0, 0.45)
    )
    components.append(
        (
            abs(
                number(left, "zero_crossing_rate") - number(right, "zero_crossing_rate")
            )
            / 0.25,
            0.5,
        )
    )
    components.append(
        (
            abs(
                math.log1p(number(left, "onset_density_per_second"))
                - math.log1p(number(right, "onset_density_per_second"))
            )
            / 2.5,
            1.0,
        )
    )
    left_tempo, right_tempo = left.get("tempo_bpm"), right.get("tempo_bpm")
    if left_tempo is None and right_tempo is None:
        tempo_distance = 0.0
    elif left_tempo is None or right_tempo is None:
        tempo_distance = 0.35
    else:
        tempo_distance = abs(float(left_tempo) - float(right_tempo)) / 90.0
    components.append((tempo_distance, 0.9))
    components.append(
        (
            abs(number(left, "onset_interval_cv") - number(right, "onset_interval_cv"))
            / 2.5,
            0.65,
        )
    )

    left_hist = left.get("rhythm_histogram") or [0.0] * 16
    right_hist = right.get("rhythm_histogram") or [0.0] * 16
    histogram_distance = (
        sum(
            abs(float(a) - float(b))
            for a, b in zip(left_hist, right_hist, strict=False)
        )
        / 2.0
    )
    components.append((histogram_distance, 1.0))

    weight_total = sum(weight for _, weight in components)
    return sum(distance * weight for distance, weight in components) / weight_total


@dataclass(frozen=True, slots=True)
class LibraryAsset:
    asset_id: str
    path: str
    file_name: str
    sha256: str
    asset_type: str
    role: str | None
    tags: tuple[str, ...]
    duration_seconds: float
    source_sample_rate: int
    channels: int
    analysis_sample_rate: int
    features: dict[str, Any]
    metadata: dict[str, Any]
    indexed_at: str
    similarity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SampleLibrary:
    """Index audio assets in SQLite and search them by text or audio similarity."""

    def __init__(self, database: str | Path | None = None) -> None:
        selected = str(database if database is not None else default_database_path())
        if selected != ":memory:":
            expanded = Path(selected).expanduser()
            expanded.parent.mkdir(parents=True, exist_ok=True)
            selected = str(expanded)
        self.database = selected
        self._connection = sqlite3.connect(selected)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                role TEXT,
                tags_json TEXT NOT NULL,
                source_sample_rate INTEGER NOT NULL,
                channels INTEGER NOT NULL,
                analysis_sample_rate INTEGER NOT NULL,
                duration_seconds REAL NOT NULL,
                feature_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_assets_type_role
                ON assets(asset_type, role);
            CREATE INDEX IF NOT EXISTS idx_assets_hash
                ON assets(sha256);

            CREATE TABLE IF NOT EXISTS collections (
                collection_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS collection_assets (
                collection_id TEXT NOT NULL REFERENCES collections(collection_id)
                    ON DELETE CASCADE,
                asset_id TEXT NOT NULL REFERENCES assets(asset_id)
                    ON DELETE CASCADE,
                position INTEGER NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL,
                PRIMARY KEY(collection_id, asset_id)
            );
            CREATE INDEX IF NOT EXISTS idx_collection_assets_position
                ON collection_assets(collection_id, position);

            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                root_seed TEXT,
                variation_stem TEXT,
                variation_index INTEGER,
                parent_project_id TEXT,
                config_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_projects_family
                ON projects(family_id);

            CREATE TABLE IF NOT EXISTS project_candidates (
                candidate_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                batch_id TEXT NOT NULL,
                parent_candidate_id TEXT,
                selection_state TEXT NOT NULL,
                label TEXT NOT NULL,
                mode TEXT NOT NULL,
                targets_json TEXT NOT NULL,
                root_seed TEXT,
                variation_seed INTEGER NOT NULL,
                seed_lineage_json TEXT NOT NULL,
                changed_parameters_json TEXT NOT NULL,
                technical_flags_json TEXT NOT NULL,
                technical_metrics_json TEXT NOT NULL,
                notes TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_project_candidates_batch
                ON project_candidates(batch_id);
            CREATE INDEX IF NOT EXISTS idx_project_candidates_parent
                ON project_candidates(parent_candidate_id);

            CREATE TABLE IF NOT EXISTS sound_objects (
                patch_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_identity_id TEXT NOT NULL,
                processing_identity_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                patch_json TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sound_objects_name
                ON sound_objects(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_sound_objects_identity
                ON sound_objects(source_identity_id, processing_identity_id);

            CREATE TABLE IF NOT EXISTS sound_object_versions (
                version_id TEXT PRIMARY KEY,
                patch_id TEXT NOT NULL REFERENCES sound_objects(patch_id) ON DELETE CASCADE,
                revision INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                patch_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(patch_id, revision),
                UNIQUE(patch_id, content_sha256)
            );
            CREATE INDEX IF NOT EXISTS idx_sound_object_versions_patch
                ON sound_object_versions(patch_id, revision);

            CREATE TABLE IF NOT EXISTS sound_object_variants (
                variant_id TEXT PRIMARY KEY,
                patch_id TEXT NOT NULL REFERENCES sound_objects(patch_id)
                    ON DELETE CASCADE,
                asset_id TEXT NOT NULL REFERENCES assets(asset_id)
                    ON DELETE CASCADE,
                seed INTEGER NOT NULL,
                source_hashes_json TEXT NOT NULL,
                transformations_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(patch_id, asset_id, seed, transformations_json)
            );
            CREATE INDEX IF NOT EXISTS idx_sound_object_variants_patch
                ON sound_object_variants(patch_id);
            """)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SampleLibrary:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def _normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            sorted({str(tag).strip().casefold() for tag in tags if str(tag).strip()})
        )

    def index_file(
        self,
        path: str | Path,
        *,
        asset_type: str = "sample",
        role: str | None = None,
        tags: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> LibraryAsset:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError(f"unsupported audio format: {source.suffix}")
        stat = source.stat()
        digest = _sha256_file(source)
        asset_id = _asset_id_for_path(source)
        prior = self._connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()

        if prior is not None and prior["sha256"] == digest:
            source_rate = int(prior["source_sample_rate"])
            channels = int(prior["channels"])
            analysis_rate = int(prior["analysis_sample_rate"])
            features = json.loads(prior["feature_json"])
            duration = float(prior["duration_seconds"])
        else:
            source_info, descriptors = analyze_audio_file(source)
            source_rate = int(source_info["source_sample_rate"])
            channels = int(source_info["channels"])
            analysis_rate = int(source_info["analysis_sample_rate"])
            features = descriptors.to_dict()
            duration = float(descriptors.duration_seconds)

        normalized_tags = set(self._normalize_tags(tags))
        normalized_tags.add(asset_type.casefold())
        if role:
            normalized_tags.add(str(role).strip().casefold())
        normalized_tags.add(source.suffix.lower().lstrip("."))
        extra = dict(metadata or {})
        extra.update(
            {
                "file_size_bytes": int(stat.st_size),
                "modified_time_ns": int(stat.st_mtime_ns),
            }
        )
        indexed_at = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            """
            INSERT INTO assets (
                asset_id, path, file_name, sha256, asset_type, role, tags_json,
                source_sample_rate, channels, analysis_sample_rate, duration_seconds,
                feature_json, metadata_json, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                path=excluded.path,
                file_name=excluded.file_name,
                sha256=excluded.sha256,
                asset_type=excluded.asset_type,
                role=excluded.role,
                tags_json=excluded.tags_json,
                source_sample_rate=excluded.source_sample_rate,
                channels=excluded.channels,
                analysis_sample_rate=excluded.analysis_sample_rate,
                duration_seconds=excluded.duration_seconds,
                feature_json=excluded.feature_json,
                metadata_json=excluded.metadata_json,
                indexed_at=excluded.indexed_at
            """,
            (
                asset_id,
                str(source),
                source.name,
                digest,
                asset_type,
                role.strip().casefold() if role else None,
                _canonical_json(sorted(normalized_tags)),
                source_rate,
                channels,
                analysis_rate,
                duration,
                _canonical_json(features),
                _canonical_json(extra),
                indexed_at,
            ),
        )
        self._connection.commit()
        asset = self.get_asset(asset_id)
        assert asset is not None
        return asset

    def get_asset(self, asset_id: str) -> LibraryAsset | None:
        row = self._connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        return self._asset_from_row(row) if row is not None else None

    def _asset_from_row(
        self,
        row: sqlite3.Row,
        *,
        similarity: float | None = None,
    ) -> LibraryAsset:
        return LibraryAsset(
            asset_id=str(row["asset_id"]),
            path=str(row["path"]),
            file_name=str(row["file_name"]),
            sha256=str(row["sha256"]),
            asset_type=str(row["asset_type"]),
            role=str(row["role"]) if row["role"] is not None else None,
            tags=tuple(json.loads(row["tags_json"])),
            duration_seconds=float(row["duration_seconds"]),
            source_sample_rate=int(row["source_sample_rate"]),
            channels=int(row["channels"]),
            analysis_sample_rate=int(row["analysis_sample_rate"]),
            features=json.loads(row["feature_json"]),
            metadata=json.loads(row["metadata_json"]),
            indexed_at=str(row["indexed_at"]),
            similarity=similarity,
        )

    def index_project(self, directory: str | Path) -> dict[str, Any]:
        root = Path(directory).expanduser().resolve()
        project_file = root / "project.json" if root.is_dir() else root
        if project_file.name != "project.json" or not project_file.is_file():
            raise FileNotFoundError(f"project.json not found in: {directory}")
        record = json.loads(project_file.read_text(encoding="utf-8"))
        config = dict(record.get("config") or {})
        metadata = dict(record.get("metadata") or {})
        variation = metadata.get("variation")
        variation = variation if isinstance(variation, dict) else None
        candidate = metadata.get("m23_candidate")
        candidate = candidate if isinstance(candidate, dict) else None
        session = metadata.get("m23_variations")
        session = session if isinstance(session, dict) else None
        family_source = (
            (session or {}).get("base_project_fingerprint")
            or (candidate or {}).get("base_project_fingerprint")
            or metadata.get("m23_project_fingerprint")
        )
        family_id = (
            str(family_source)[:24]
            if family_source
            else hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()[
                :24
            ]
        )
        project_id = hashlib.sha256(
            (
                str(project_file.parent).casefold() + "\0" + _sha256_file(project_file)
            ).encode("utf-8")
        ).hexdigest()[:24]
        root_seed = str(config.get("seed")) if config.get("seed") is not None else None
        variation_stem = (
            str(variation.get("stem")) if variation and variation.get("stem") else None
        )
        variation_index = int(variation.get("index", 0)) if variation else None
        if candidate:
            targets = candidate.get("targets", [])
            variation_stem = (
                "+".join(str(item) for item in targets)
                if targets
                else str(candidate.get("mode", "full_project"))
            )
            variation_index = int(candidate.get("index", 0))
        parent = self._connection.execute(
            """
            SELECT project_id FROM projects
            WHERE family_id = ? AND variation_stem IS NULL AND project_id != ?
            ORDER BY indexed_at LIMIT 1
            """,
            (family_id, project_id),
        ).fetchone()
        parent_id = (
            str(parent["project_id"]) if parent is not None and variation else None
        )
        indexed_at = datetime.now(timezone.utc).isoformat()

        self._connection.execute(
            """
            INSERT INTO projects (
                project_id, family_id, path, root_seed, variation_stem,
                variation_index, parent_project_id, config_json, metadata_json, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                project_id=excluded.project_id,
                family_id=excluded.family_id,
                root_seed=excluded.root_seed,
                variation_stem=excluded.variation_stem,
                variation_index=excluded.variation_index,
                parent_project_id=excluded.parent_project_id,
                config_json=excluded.config_json,
                metadata_json=excluded.metadata_json,
                indexed_at=excluded.indexed_at
            """,
            (
                project_id,
                family_id,
                str(project_file.parent),
                root_seed,
                variation_stem,
                variation_index,
                parent_id,
                _canonical_json(config),
                _canonical_json(metadata),
                indexed_at,
            ),
        )
        if variation is None:
            self._connection.execute(
                """
                UPDATE projects SET parent_project_id = ?
                WHERE family_id = ? AND variation_stem IS NOT NULL
                """,
                (project_id, family_id),
            )
        if candidate:
            self._connection.execute(
                """
                INSERT INTO project_candidates (
                    candidate_id, project_id, batch_id, parent_candidate_id,
                    selection_state, label, mode, targets_json, root_seed,
                    variation_seed, seed_lineage_json, changed_parameters_json,
                    technical_flags_json, technical_metrics_json, notes, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    batch_id=excluded.batch_id,
                    parent_candidate_id=excluded.parent_candidate_id,
                    selection_state=excluded.selection_state,
                    label=excluded.label,
                    mode=excluded.mode,
                    targets_json=excluded.targets_json,
                    root_seed=excluded.root_seed,
                    variation_seed=excluded.variation_seed,
                    seed_lineage_json=excluded.seed_lineage_json,
                    changed_parameters_json=excluded.changed_parameters_json,
                    technical_flags_json=excluded.technical_flags_json,
                    technical_metrics_json=excluded.technical_metrics_json,
                    notes=excluded.notes,
                    indexed_at=excluded.indexed_at
                """,
                (
                    str(candidate.get("candidate_id", "")),
                    project_id,
                    str(candidate.get("batch_id", "")),
                    candidate.get("parent_candidate_id"),
                    str(candidate.get("selection_state", "unreviewed")),
                    str(candidate.get("label", "Candidate")),
                    str(candidate.get("mode", "stems")),
                    _canonical_json(candidate.get("targets", [])),
                    (
                        None
                        if candidate.get("root_seed") is None
                        else str(candidate.get("root_seed"))
                    ),
                    int(candidate.get("variation_seed", 1)),
                    _canonical_json(candidate.get("seed_lineage", {})),
                    _canonical_json(candidate.get("changed_parameters", {})),
                    _canonical_json(candidate.get("technical_flags", [])),
                    _canonical_json(candidate.get("technical_metrics", {})),
                    str(candidate.get("notes", "")),
                    indexed_at,
                ),
            )
        self._connection.commit()

        indexed_assets: list[str] = []
        stem_directory = project_file.parent / "stems"
        for stem_name in record.get("stems", []):
            stem_path = stem_directory / f"{stem_name}.wav"
            if stem_path.is_file():
                asset = self.index_file(
                    stem_path,
                    asset_type="stem",
                    role=str(stem_name),
                    tags=(
                        "project-stem",
                        f"seed-{root_seed}" if root_seed else "project",
                    ),
                    metadata={
                        "project_id": project_id,
                        "family_id": family_id,
                        "root_seed": root_seed,
                        "variation": variation,
                        "m23_candidate": candidate,
                        "sound_object_variants": metadata.get(
                            "sound_object_variants", []
                        ),
                    },
                )
                indexed_assets.append(asset.asset_id)

        master_path = project_file.parent / "master.wav"
        if master_path.is_file():
            master = self.index_file(
                master_path,
                asset_type="master",
                role="master",
                tags=("project-master",),
                metadata={"project_id": project_id, "family_id": family_id},
            )
            indexed_assets.append(master.asset_id)

        for source_role, source_record in (
            metadata.get("sample_sources") or {}
        ).items():
            source_path = Path(str(source_record.get("path", ""))).expanduser()
            if source_path.is_file():
                source_asset = self.index_file(
                    source_path,
                    asset_type="sample",
                    role=str(source_role),
                    tags=("project-source",),
                    metadata={
                        "source_sha256": source_record.get("sha256"),
                        "project_id": project_id,
                    },
                )
                indexed_assets.append(source_asset.asset_id)

        return {
            "project_id": project_id,
            "family_id": family_id,
            "parent_project_id": parent_id,
            "variation_stem": variation_stem,
            "variation_index": variation_index,
            "candidate_id": (candidate or {}).get("candidate_id"),
            "candidate_batch_id": (candidate or {}).get("batch_id"),
            "selection_state": (candidate or {}).get("selection_state"),
            "assets_indexed": len(indexed_assets),
            "asset_ids": indexed_assets,
        }

    def index_directory(self, directory: str | Path) -> dict[str, Any]:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        project_files = sorted(root.rglob("project.json"))
        project_roots = [path.parent.resolve() for path in project_files]
        projects_indexed = 0
        assets_indexed = 0
        errors: list[dict[str, str]] = []
        for project_file in project_files:
            try:
                result = self.index_project(project_file.parent)
                projects_indexed += 1
                assets_indexed += int(result["assets_indexed"])
            except Exception as exc:
                errors.append({"path": str(project_file.parent), "error": str(exc)})

        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES
            and not any(
                project_root == path.parent or project_root in path.parents
                for project_root in project_roots
            )
        )
        for path in files:
            try:
                self.index_file(path)
                assets_indexed += 1
            except Exception as exc:
                errors.append({"path": str(path), "error": str(exc)})
        return {
            "root": str(root),
            "projects_indexed": projects_indexed,
            "assets_indexed": assets_indexed,
            "errors": errors,
        }

    def search(
        self,
        *,
        query: str | None = None,
        asset_type: str | None = None,
        role: str | None = None,
        tags: Iterable[str] = (),
        similar_to: str | None = None,
        limit: int = 20,
    ) -> list[LibraryAsset]:
        if limit < 1:
            raise ValueError("limit must be positive")
        reference = None
        if similar_to:
            reference = self.get_asset(similar_to)
            if reference is None:
                row = self._connection.execute(
                    "SELECT * FROM assets WHERE path = ?",
                    (str(Path(similar_to).expanduser().resolve()),),
                ).fetchone()
                reference = self._asset_from_row(row) if row is not None else None
            if reference is None:
                raise KeyError(f"similarity reference not found: {similar_to}")

        needle = (query or "").strip().casefold()
        required_tags = set(self._normalize_tags(tags))
        rows = self._connection.execute("SELECT * FROM assets").fetchall()
        results: list[LibraryAsset] = []
        for row in rows:
            item = self._asset_from_row(row)
            if asset_type and item.asset_type != asset_type.casefold():
                continue
            if role and item.role != role.casefold():
                continue
            if required_tags and not required_tags.issubset(set(item.tags)):
                continue
            if needle:
                searchable = " ".join(
                    (
                        item.file_name,
                        item.path,
                        item.role or "",
                        " ".join(item.tags),
                        _canonical_json(item.metadata),
                    )
                ).casefold()
                if needle not in searchable:
                    continue
            if reference is not None:
                distance = _similarity_distance(reference.features, item.features)
                item = LibraryAsset(
                    **{
                        **item.to_dict(),
                        "similarity": float(1.0 / (1.0 + distance)),
                    }
                )
            results.append(item)

        if reference is not None:
            results.sort(
                key=lambda item: (-(item.similarity or 0.0), item.file_name.casefold())
            )
        else:
            results.sort(
                key=lambda item: (
                    item.asset_type,
                    item.role or "",
                    item.file_name.casefold(),
                )
            )
        return results[:limit]

    def create_collection(self, name: str, description: str = "") -> str:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("collection name cannot be empty")
        collection_id = hashlib.sha256(
            normalized_name.casefold().encode("utf-8")
        ).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            """
            INSERT INTO collections (collection_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                updated_at=excluded.updated_at
            """,
            (collection_id, normalized_name, str(description), now, now),
        )
        self._connection.commit()
        row = self._connection.execute(
            "SELECT collection_id FROM collections WHERE name = ?", (normalized_name,)
        ).fetchone()
        assert row is not None
        return str(row["collection_id"])

    def collections(self) -> list[dict[str, Any]]:
        rows = self._connection.execute("""
            SELECT c.collection_id, c.name, c.description, c.created_at,
                   c.updated_at, COUNT(ca.asset_id) AS asset_count
            FROM collections c
            LEFT JOIN collection_assets ca ON ca.collection_id = c.collection_id
            GROUP BY c.collection_id
            ORDER BY c.name COLLATE NOCASE
            """).fetchall()
        return [dict(row) for row in rows]

    def add_to_collection(self, name: str, asset_ids: Iterable[str]) -> int:
        collection = self._connection.execute(
            "SELECT collection_id FROM collections WHERE name = ?", (str(name),)
        ).fetchone()
        if collection is None:
            raise KeyError(f"collection not found: {name}")
        collection_id = str(collection["collection_id"])
        added = 0
        for asset_id in asset_ids:
            asset = self.get_asset(str(asset_id))
            if asset is None:
                raise KeyError(f"asset not found: {asset_id}")
            position_row = self._connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_position "
                "FROM collection_assets WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            position = int(position_row["next_position"])
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO collection_assets
                (collection_id, asset_id, position, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    collection_id,
                    str(asset_id),
                    position,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            added += int(cursor.rowcount > 0)
        self._connection.commit()
        return added

    def remove_from_collection(self, name: str, asset_ids: Iterable[str]) -> int:
        collection = self._connection.execute(
            "SELECT collection_id FROM collections WHERE name = ?", (str(name),)
        ).fetchone()
        if collection is None:
            raise KeyError(f"collection not found: {name}")
        removed = 0
        for asset_id in asset_ids:
            cursor = self._connection.execute(
                "DELETE FROM collection_assets WHERE collection_id = ? AND asset_id = ?",
                (str(collection["collection_id"]), str(asset_id)),
            )
            removed += int(cursor.rowcount > 0)
        self._connection.commit()
        return removed

    def collection_assets(self, name: str) -> list[LibraryAsset]:
        collection = self._connection.execute(
            "SELECT collection_id FROM collections WHERE name = ?", (str(name),)
        ).fetchone()
        if collection is None:
            raise KeyError(f"collection not found: {name}")
        rows = self._connection.execute(
            """
            SELECT a.* FROM assets a
            JOIN collection_assets ca ON ca.asset_id = a.asset_id
            WHERE ca.collection_id = ?
            ORDER BY ca.position, a.file_name
            """,
            (str(collection["collection_id"]),),
        ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def genealogy(self, family_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT p.project_id, p.family_id, p.path, p.root_seed,
                   p.variation_stem, p.variation_index, p.parent_project_id,
                   p.indexed_at, c.candidate_id, c.batch_id,
                   c.parent_candidate_id, c.selection_state, c.label,
                   c.mode, c.targets_json, c.variation_seed,
                   c.seed_lineage_json, c.changed_parameters_json,
                   c.technical_flags_json, c.technical_metrics_json, c.notes
            FROM projects p
            LEFT JOIN project_candidates c ON c.project_id = p.project_id
            WHERE p.family_id = ?
            ORDER BY CASE WHEN c.candidate_id IS NULL THEN 0 ELSE 1 END,
                     c.batch_id, c.variation_seed, p.path
            """,
            (str(family_id),),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field, source in (
                ("targets", "targets_json"),
                ("seed_lineage", "seed_lineage_json"),
                ("changed_parameters", "changed_parameters_json"),
                ("technical_flags", "technical_flags_json"),
                ("technical_metrics", "technical_metrics_json"),
            ):
                encoded = item.pop(source, None)
                if encoded is not None:
                    item[field] = json.loads(encoded)
            result.append(item)
        return result

    def project_family_id(self, directory: str | Path) -> str:
        root = Path(directory).expanduser().resolve()
        project_file = root / "project.json" if root.is_dir() else root
        record = json.loads(project_file.read_text(encoding="utf-8"))
        return hashlib.sha256(
            _canonical_json(record.get("config") or {}).encode("utf-8")
        ).hexdigest()[:24]

    def save_sound_object(self, patch: Any, *, tags: Iterable[str] = ()) -> str:
        """Persist one validated patch, retaining source and processing identities."""
        from reawarp.synthesis.sound_object import SoundObjectPatch

        value = (
            patch
            if isinstance(patch, SoundObjectPatch)
            else SoundObjectPatch.from_dict(patch)
        )
        for source in value.sources:
            if source.asset_id:
                asset = self.get_asset(source.asset_id)
                if asset is None:
                    raise KeyError(
                        f"sound-object source asset not found: {source.asset_id}"
                    )
                if asset.sha256.casefold() != str(source.asset_sha256).casefold():
                    raise ValueError(
                        f"sound-object source hash does not match indexed asset: {source.asset_id}"
                    )
        canonical = _canonical_json(value.to_dict())
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        normalized_tags = set(self._normalize_tags(tags))
        normalized_tags.update(
            {
                "sound-object",
                value.name.casefold(),
                value.patch_id.casefold(),
                value.source_identity_id.casefold(),
                value.processing_identity_id.casefold(),
            }
        )
        indexed_at = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            """
            INSERT INTO sound_objects (
                patch_id, name, source_identity_id, processing_identity_id,
                content_sha256, tags_json, patch_json, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patch_id) DO UPDATE SET
                name=excluded.name,
                source_identity_id=excluded.source_identity_id,
                processing_identity_id=excluded.processing_identity_id,
                content_sha256=excluded.content_sha256,
                tags_json=excluded.tags_json,
                patch_json=excluded.patch_json,
                indexed_at=excluded.indexed_at
            """,
            (
                value.patch_id,
                value.name,
                value.source_identity_id,
                value.processing_identity_id,
                digest,
                _canonical_json(sorted(normalized_tags)),
                canonical,
                indexed_at,
            ),
        )
        row = self._connection.execute(
            "SELECT version_id FROM sound_object_versions WHERE patch_id = ? AND content_sha256 = ?",
            (value.patch_id, digest),
        ).fetchone()
        if row is None:
            latest = self._connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM sound_object_versions WHERE patch_id = ?",
                (value.patch_id,),
            ).fetchone()
            revision = int(latest["revision"]) + 1
            version_id = f"{value.patch_id}@{revision:04d}-{digest[:12]}"
            self._connection.execute(
                """
                INSERT INTO sound_object_versions (
                    version_id, patch_id, revision, content_sha256, patch_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (version_id, value.patch_id, revision, digest, canonical, indexed_at),
            )
        self._connection.commit()
        return digest

    def list_sound_object_versions(self, patch_id: str) -> list[dict[str, Any]]:
        """Return immutable patch snapshots in ascending revision order."""
        from reawarp.synthesis.sound_object import SoundObjectPatch

        rows = self._connection.execute(
            "SELECT version_id, revision, content_sha256, patch_json, created_at "
            "FROM sound_object_versions WHERE patch_id = ? ORDER BY revision",
            (str(patch_id),),
        ).fetchall()
        return [
            {
                "version_id": str(row["version_id"]),
                "revision": int(row["revision"]),
                "content_sha256": str(row["content_sha256"]),
                "patch": SoundObjectPatch.from_dict(json.loads(row["patch_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def get_sound_object_version(self, version_id: str) -> dict[str, Any] | None:
        """Load one immutable patch snapshot by its stable version ID."""
        from reawarp.synthesis.sound_object import SoundObjectPatch

        row = self._connection.execute(
            "SELECT version_id, patch_id, revision, content_sha256, patch_json, created_at "
            "FROM sound_object_versions WHERE version_id = ?",
            (str(version_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "version_id": str(row["version_id"]),
            "patch_id": str(row["patch_id"]),
            "revision": int(row["revision"]),
            "content_sha256": str(row["content_sha256"]),
            "patch": SoundObjectPatch.from_dict(json.loads(row["patch_json"])),
            "created_at": str(row["created_at"]),
        }

    def get_sound_object(self, patch_id: str):
        """Load and validate one patch from the sound-object catalogue."""
        from reawarp.synthesis.sound_object import SoundObjectPatch

        row = self._connection.execute(
            "SELECT patch_json FROM sound_objects WHERE patch_id = ?",
            (str(patch_id),),
        ).fetchone()
        return (
            None
            if row is None
            else SoundObjectPatch.from_dict(json.loads(row["patch_json"]))
        )

    def search_sound_objects(
        self,
        *,
        query: str | None = None,
        tags: Iterable[str] = (),
        source_identity_id: str | None = None,
        processing_identity_id: str | None = None,
        limit: int = 20,
    ):
        """Search sound-object patches by name, identity and tags."""
        from reawarp.synthesis.sound_object import SoundObjectPatch

        if limit < 1:
            raise ValueError("limit must be positive")
        needle = (query or "").strip().casefold()
        required = set(self._normalize_tags(tags))
        rows = self._connection.execute(
            "SELECT patch_json, tags_json FROM sound_objects "
            "ORDER BY name COLLATE NOCASE, patch_id"
        ).fetchall()
        result = []
        for row in rows:
            patch = SoundObjectPatch.from_dict(json.loads(row["patch_json"]))
            row_tags = set(json.loads(row["tags_json"]))
            if required and not required.issubset(row_tags):
                continue
            if source_identity_id and patch.source_identity_id != source_identity_id:
                continue
            if (
                processing_identity_id
                and patch.processing_identity_id != processing_identity_id
            ):
                continue
            searchable = " ".join(
                (
                    patch.name,
                    patch.patch_id,
                    patch.source_identity_id,
                    patch.processing_identity_id,
                    " ".join(sorted(row_tags)),
                )
            ).casefold()
            if needle and needle not in searchable:
                continue
            result.append(patch)
            if len(result) >= limit:
                break
        return result

    def record_sound_object_variant(
        self,
        patch_id: str,
        asset_id: str,
        *,
        seed: int,
        source_hashes: Iterable[str] | None = None,
        transformations: Iterable[Any] = (),
    ) -> str:
        """Attach one rendered audio asset with deterministic lineage metadata."""
        from reawarp.synthesis.sound_object import TransformationRecord

        patch = self.get_sound_object(patch_id)
        if patch is None:
            raise KeyError(f"sound-object patch not found: {patch_id}")
        asset = self.get_asset(asset_id)
        if asset is None:
            raise KeyError(f"sound-object variant asset not found: {asset_id}")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("variant seed must be an integer")
        hashes = tuple(
            sorted(
                str(item).casefold()
                for item in (
                    source_hashes if source_hashes is not None else patch.source_hashes
                )
            )
        )
        if any(
            len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)
            for value in hashes
        ):
            raise ValueError("variant source_hashes must contain SHA-256 digests")
        records = []
        for item in transformations:
            record = (
                item
                if isinstance(item, TransformationRecord)
                else TransformationRecord.from_dict(item)
            )
            records.append(record.to_dict())
        transforms_json = _canonical_json(records)
        hashes_json = _canonical_json(list(hashes))
        variant_id = hashlib.sha256(
            f"{patch.patch_id}|{asset.asset_id}|{seed}|{transforms_json}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        created_at = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            """
            INSERT INTO sound_object_variants (
                variant_id, patch_id, asset_id, seed,
                source_hashes_json, transformations_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patch_id, asset_id, seed, transformations_json) DO UPDATE SET
                source_hashes_json=excluded.source_hashes_json,
                created_at=excluded.created_at
            """,
            (
                variant_id,
                patch.patch_id,
                asset.asset_id,
                int(seed),
                hashes_json,
                transforms_json,
                created_at,
            ),
        )
        self._connection.commit()
        return variant_id

    def sound_object_variants(self, patch_id: str) -> list[dict[str, Any]]:
        """List a patch's audio variants with indexed descriptors and lineage."""
        if self.get_sound_object(patch_id) is None:
            raise KeyError(f"sound-object patch not found: {patch_id}")
        rows = self._connection.execute(
            """
            SELECT v.variant_id, v.patch_id, v.asset_id, v.seed,
                   v.source_hashes_json, v.transformations_json, v.created_at,
                   a.path, a.sha256, a.feature_json
            FROM sound_object_variants v
            JOIN assets a ON a.asset_id = v.asset_id
            WHERE v.patch_id = ?
            ORDER BY v.created_at, v.variant_id
            """,
            (str(patch_id),),
        ).fetchall()
        return [
            {
                "variant_id": str(row["variant_id"]),
                "patch_id": str(row["patch_id"]),
                "asset_id": str(row["asset_id"]),
                "seed": int(row["seed"]),
                "source_hashes": json.loads(row["source_hashes_json"]),
                "transformations": json.loads(row["transformations_json"]),
                "created_at": str(row["created_at"]),
                "path": str(row["path"]),
                "asset_sha256": str(row["sha256"]),
                "features": json.loads(row["feature_json"]),
            }
            for row in rows
        ]
