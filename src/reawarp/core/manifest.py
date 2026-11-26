"""Integrity manifest, source-asset packaging and portability diagnostics for projects."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

MANIFEST_FORMAT = "eli_lab_reawarp_project_manifest"
MANIFEST_SCHEMA_VERSION = 1


def _check_cancelled(cancel_event: Any | None, operation: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError(f"{operation} cancelled")


def sha256_file(path: str | Path, *, cancel_event: Any | None = None) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            _check_cancelled(cancel_event, "manifest hashing")
            digest.update(block)
    return digest.hexdigest()


def _application_version() -> str:
    try:
        return importlib.metadata.version("eli-lab-reawarp")
    except importlib.metadata.PackageNotFoundError:
        return "0.12.0"


def _resolve_source_path(value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _safe_filename(path: Path) -> str:
    name = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in path.name
    ).strip("._")
    return (name or "source_asset")[:96]


def prepare_project_assets(
    config_data: dict[str, Any],
    project_directory: str | Path,
    *,
    asset_policy: str = "copy",
    cancel_event: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Copy configured source assets and rewrite references without mutating config_data.

    asset_policy='copy' makes project-relative, self-contained references. 'reference'
    preserves absolute external paths and records them as dependencies. Missing files
    remain explicit missing references; they are never substituted from a library.
    """
    if asset_policy not in {"copy", "reference"}:
        raise ValueError("asset_policy must be 'copy' or 'reference'")
    root = Path(project_directory).expanduser().resolve()
    rewritten = json.loads(json.dumps(config_data, ensure_ascii=False))
    references: list[tuple[str, str]] = []

    sample_paths = rewritten.get("sample_paths", {})
    if isinstance(sample_paths, dict):
        references.extend(
            (f"sample_paths.{role}", str(path)) for role, path in sample_paths.items()
        )
    sample_banks = rewritten.get("sample_banks", {})
    if isinstance(sample_banks, dict):
        for role, entries in sample_banks.items():
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                if isinstance(entry, dict) and entry.get("path"):
                    references.append(
                        (f"sample_banks.{role}.{index}", str(entry["path"]))
                    )

    assets_by_source: dict[str, dict[str, Any]] = {}
    rewritten_paths: dict[str, str] = {}
    for reference_id, configured_path in references:
        _check_cancelled(cancel_event, "asset packaging")
        source = _resolve_source_path(configured_path)
        source_key = str(source)
        asset = assets_by_source.get(source_key)
        if asset is None:
            base = {
                "configured_path": configured_path,
                "source_path": source_key,
                "file_name": source.name,
                "references": [],
                "project_path": None,
                "sha256": None,
                "size_bytes": None,
            }
            if not source.is_file():
                missing_id = hashlib.sha256(
                    ("missing:" + source_key).encode("utf-8")
                ).hexdigest()
                asset = {
                    **base,
                    "asset_id": "missing-path:" + missing_id,
                    "status": "missing",
                }
                rewritten_path = source_key
            else:
                digest = sha256_file(source, cancel_event=cancel_event)
                base.update(
                    {
                        "asset_id": "sha256:" + digest,
                        "sha256": digest,
                        "size_bytes": int(source.stat().st_size),
                    }
                )
                if asset_policy == "copy":
                    destination = (
                        root / "assets" / f"{digest[:16]}-{_safe_filename(source)}"
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if (
                        not destination.is_file()
                        or sha256_file(destination, cancel_event=cancel_event) != digest
                    ):
                        temporary = destination.with_suffix(destination.suffix + ".tmp")
                        try:
                            with (
                                source.open("rb") as source_handle,
                                temporary.open("wb") as destination_handle,
                            ):
                                for block in iter(
                                    lambda: source_handle.read(1024 * 1024), b""
                                ):
                                    _check_cancelled(cancel_event, "asset packaging")
                                    destination_handle.write(block)
                            shutil.copystat(source, temporary)
                            temporary.replace(destination)
                        finally:
                            if temporary.exists():
                                temporary.unlink()
                    if sha256_file(destination, cancel_event=cancel_event) != digest:
                        raise IOError(
                            f"copied asset hash verification failed: {source}"
                        )
                    relative = Path(os.path.relpath(destination, root)).as_posix()
                    asset = {**base, "project_path": relative, "status": "embedded"}
                    rewritten_path = relative
                else:
                    asset = {**base, "status": "external_reference"}
                    rewritten_path = source_key
            assets_by_source[source_key] = asset
        else:
            rewritten_path = (
                str(asset["project_path"])
                if asset["status"] == "embedded"
                else source_key
            )
        asset["references"].append(reference_id)
        rewritten_paths[reference_id] = rewritten_path

    for role, path in (
        list(sample_paths.items()) if isinstance(sample_paths, dict) else []
    ):
        reference_id = f"sample_paths.{role}"
        if reference_id in rewritten_paths:
            rewritten["sample_paths"][role] = rewritten_paths[reference_id]
    if isinstance(sample_banks, dict):
        for role, entries in sample_banks.items():
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                reference_id = f"sample_banks.{role}.{index}"
                if isinstance(entry, dict) and reference_id in rewritten_paths:
                    entry["path"] = rewritten_paths[reference_id]

    assets = sorted(assets_by_source.values(), key=lambda item: item["asset_id"])
    return assets, rewritten


def resolve_project_asset_paths(
    config_data: dict[str, Any], project_directory: str | Path
) -> dict[str, Any]:
    """Resolve relative packaged sample references against the project folder."""
    root = Path(project_directory).expanduser().resolve()
    config = json.loads(json.dumps(config_data, ensure_ascii=False))

    def resolve(value: Any) -> str:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            resolved = (root / path).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(
                    "project-relative asset path escapes the project directory"
                )
            return str(resolved)
        return str(path.resolve())

    sample_paths = config.get("sample_paths", {})
    if isinstance(sample_paths, dict):
        config["sample_paths"] = {
            role: resolve(path) for role, path in sample_paths.items()
        }
    sample_banks = config.get("sample_banks", {})
    if isinstance(sample_banks, dict):
        for entries in sample_banks.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("path"):
                    entry["path"] = resolve(entry["path"])
    return config


def audit_project_assets(
    project_directory: str | Path,
    source_assets: list[dict[str, Any]] | None = None,
    *,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    """Report missing, modified and available source assets by stable ID and path."""
    root = Path(project_directory).expanduser().resolve()
    if source_assets is None:
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            return {
                "manifest_available": False,
                "ok": True,
                "assets": [],
                "missing": [],
                "changed": [],
            }
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_assets = manifest.get("source_assets", [])
    if not isinstance(source_assets, list):
        raise ValueError("manifest source_assets must be a list")
    results: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for index, asset in enumerate(source_assets):
        if not isinstance(asset, Mapping):
            raise ValueError(f"manifest source_assets[{index}] must be an object")
        record = dict(asset)
        status = str(record.get("status", "unknown"))
        project_path = record.get("project_path")
        source_path = record.get("source_path")
        if status == "missing":
            result_status = "missing"
            actual_path = str(source_path or record.get("configured_path", ""))
        elif status == "embedded":
            relative = Path(str(project_path))
            actual = (root / relative).resolve()
            if not actual.is_relative_to(root):
                result_status = "invalid_path"
                actual_path = str(actual)
            else:
                actual_path = str(actual)
                if not actual.is_file():
                    result_status = "missing"
                elif (
                    record.get("sha256")
                    and sha256_file(actual, cancel_event=cancel_event)
                    != record["sha256"]
                ):
                    result_status = "changed"
                else:
                    result_status = "ok"
        elif status == "external_reference":
            actual = Path(str(source_path)).expanduser()
            actual_path = str(actual)
            if not actual.is_file():
                result_status = "missing"
            elif (
                record.get("sha256")
                and sha256_file(actual, cancel_event=cancel_event) != record["sha256"]
            ):
                result_status = "changed"
            else:
                result_status = "external_available"
        else:
            result_status = "unknown"
            actual_path = str(source_path or project_path or "")
        item = {
            "asset_id": record.get("asset_id"),
            "status": result_status,
            "path": actual_path,
            "sha256": record.get("sha256"),
            "references": record.get("references", []),
        }
        results.append(item)
        if result_status in {"missing", "invalid_path"}:
            missing.append(item)
        elif result_status == "changed":
            changed.append(item)
    return {
        "manifest_available": True,
        "ok": not missing and not changed,
        "assets": results,
        "missing": missing,
        "changed": changed,
    }


def audit_project_file_inventory(
    project_directory: str | Path,
    file_inventory: list[dict[str, Any]] | None = None,
    *,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    """Verify archived artifact hashes and report missing or modified files."""
    root = Path(project_directory).expanduser().resolve()
    if file_inventory is None:
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            return {
                "ok": True,
                "manifest_available": False,
                "missing": [],
                "changed": [],
            }
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_inventory = manifest.get("file_inventory", [])
    if not isinstance(file_inventory, list):
        raise ValueError("manifest file_inventory must be a list")
    missing: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for index, entry in enumerate(file_inventory):
        _check_cancelled(cancel_event, "project integrity audit")
        if not isinstance(entry, Mapping):
            raise ValueError(f"manifest file_inventory[{index}] must be an object")
        relative = Path(str(entry.get("path", "")))
        actual = (root / relative).resolve()
        item = {"path": str(relative), "sha256": entry.get("sha256")}
        if not actual.is_relative_to(root) or not actual.is_file():
            missing.append({**item, "status": "missing_or_unsafe"})
        elif (
            entry.get("sha256")
            and sha256_file(actual, cancel_event=cancel_event) != entry["sha256"]
        ):
            changed.append({**item, "status": "changed"})
    return {
        "manifest_available": True,
        "ok": not missing and not changed,
        "missing": missing,
        "changed": changed,
    }


def _environment_record() -> dict[str, Any]:
    try:
        import scipy

        scipy_version: str | None = str(scipy.__version__)
    except ImportError:
        scipy_version = None
    physical_memory: int | None = None
    if platform.system() == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                physical_memory = int(status.ullTotalPhys)
        except (AttributeError, OSError):
            physical_memory = None
    else:
        try:
            physical_memory = int(
                os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            )
        except (AttributeError, OSError, ValueError):
            physical_memory = None
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "numpy": str(np.__version__),
        "scipy": scipy_version,
        "physical_memory_bytes": physical_memory,
    }


def _file_inventory(
    root: Path, *, cancel_event: Any | None = None
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        _check_cancelled(cancel_event, "manifest inventory")
        if not path.is_file() or path.name in {"manifest.json", "manifest.json.tmp"}:
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(
                f"project file symlink escapes the project directory: {path}"
            )
        relative = path.relative_to(root).as_posix()
        stat = resolved.stat()
        entries.append(
            {
                "path": relative,
                "size_bytes": int(stat.st_size),
                "sha256": sha256_file(resolved, cancel_event=cancel_event),
            }
        )
    return entries


def write_project_manifest(
    project_directory: str | Path,
    *,
    source_assets: list[dict[str, Any]] | None = None,
    cancel_event: Any | None = None,
) -> Path:
    """Write or refresh the archive manifest after all export artifacts are final."""
    _check_cancelled(cancel_event, "manifest write")
    root = Path(project_directory).expanduser().resolve()
    project_path = root / "project.json"
    if not project_path.is_file():
        raise FileNotFoundError(f"project.json is required to write a manifest: {root}")
    project_record = json.loads(project_path.read_text(encoding="utf-8"))
    old_manifest_path = root / "manifest.json"
    prior: dict[str, Any] = {}
    if old_manifest_path.is_file():
        try:
            prior = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
    assets = source_assets
    if assets is None:
        assets = prior.get("source_assets", [])
    score_path = root / str(project_record.get("score_file", "score.json"))
    score_record: dict[str, Any] = {}
    if score_path.is_file():
        try:
            score_record = json.loads(score_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            score_record = {}
    metadata = project_record.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    render_provenance = project_record.get("render_provenance", {})
    if not isinstance(render_provenance, dict):
        render_provenance = {}
    variation_session = metadata.get("m23_variations", {})
    candidate_ancestry = []
    if isinstance(variation_session, dict):
        for record in variation_session.get("candidate_records", []):
            if isinstance(record, dict):
                candidate_ancestry.append(
                    {
                        key: record.get(key)
                        for key in (
                            "candidate_id",
                            "parent_candidate_id",
                            "variation_seed",
                            "mode",
                            "selection_state",
                            "targets",
                        )
                    }
                )
    fx_files = {
        "routing": "fx_routing.json" if (root / "fx_routing.json").is_file() else None,
        "automation": (
            "fx_automation.json" if (root / "fx_automation.json").is_file() else None
        ),
        "mix": "mix.json" if (root / "mix.json").is_file() else None,
    }
    listening_session = metadata.get("m32_listening_session", {})
    if not isinstance(listening_session, dict):
        listening_session = {}
    critical_listening = {
        "json_file": (
            "critical_listening_report.json"
            if (root / "critical_listening_report.json").is_file()
            else None
        ),
        "markdown_file": (
            "critical_listening_report.md"
            if (root / "critical_listening_report.md").is_file()
            else None
        ),
        "session_id": listening_session.get("session_id"),
        "project_fingerprint": listening_session.get("project_fingerprint"),
        "project_revision": listening_session.get("project_revision"),
        "candidate_ids": listening_session.get("candidate_ids", []),
        "analysis_enabled": listening_session.get("analysis_enabled"),
        "audition_transform_count": len(
            listening_session.get("audition_transforms", [])
        ),
    }
    report = {
        "format": MANIFEST_FORMAT,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "application": {
            "id": str(project_record.get("application", "eli_lab-reawarp")),
            "version": str(
                project_record.get("application_version", _application_version())
            ),
            "renderer_version": str(project_record.get("renderer_version", "unknown")),
        },
        "schemas": {
            "project": int(project_record.get("schema_version", 1)),
            "events": 1,
            "score": int(
                project_record.get(
                    "score_schema_version", score_record.get("schema_version", 1)
                )
            ),
            "fx_routing": 3 if fx_files["routing"] else None,
            "fx_automation": 1 if fx_files["automation"] else None,
            "sound_object": 1,
            "candidate_record": 1,
        },
        "project": {
            "sample_rate": int(project_record.get("sample_rate", 0)),
            "frame_count": int(project_record.get("frame_count", 0)),
            "duration_seconds": float(project_record.get("duration_seconds", 0.0)),
            "stems": list(project_record.get("stems", [])),
            "event_count": (
                len(
                    json.loads((root / "events.json").read_text(encoding="utf-8")).get(
                        "events", []
                    )
                )
                if (root / "events.json").is_file()
                else None
            ),
        },
        "config": {
            "sha256": hashlib.sha256(
                json.dumps(
                    project_record.get("config", {}),
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "root_seed": project_record.get("config", {}).get("seed"),
            "algorithm_version": metadata.get("algorithm_version"),
            "renderer_version": project_record.get("renderer_version"),
        },
        "score": {
            "title": score_record.get("title"),
            "tuning": score_record.get("tuning"),
            "generator_families": score_record.get("metadata", {}).get(
                "generator_families", {}
            ),
            "seed_streams": score_record.get("metadata", {}).get("seed_streams", {}),
            "render_provenance": score_record.get("metadata", {}).get(
                "render_provenance", render_provenance
            ),
        },
        "source_selection": {
            "sample_sources": metadata.get("sample_sources", {}),
            "sample_switch_summary": metadata.get("sample_switch_summary", {}),
            "score_sample_schedule": score_record.get("metadata", {}).get(
                "sample_schedule", {}
            ),
        },
        "source_assets": list(assets or []),
        "candidate_ancestry": candidate_ancestry,
        "critical_listening": critical_listening,
        "fx_files": fx_files,
        "render_environment": _environment_record(),
        "reproducibility": {
            "classification": "exact_archive; same_environment_rerender; cross_environment_best_effort",
            "exact_archive": "SHA-256 hashes identify the archived WAVs and project files exactly.",
            "same_environment": "Regeneration uses the recorded seed, application/renderer, Python and numerical-library versions; exact waveform parity is still verified by comparing output hashes.",
            "cross_environment": "best_effort",
            "seed_and_algorithm_provenance_recorded": True,
            "bit_identical_cross_platform_promised": False,
            "notes": [
                "Archived audio is the exact reference; regeneration is a separate operation.",
                "Same-environment rerendering is expected to be deterministic for the declared input set but must be verified against archived hashes.",
                "Cross-platform bit identity is not guaranteed.",
            ],
        },
        "file_inventory": _file_inventory(root, cancel_event=cancel_event),
    }
    temporary = root / "manifest.json.tmp"
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(root / "manifest.json")
    return root / "manifest.json"


def refresh_project_manifest(
    project_directory: str | Path, *, cancel_event: Any | None = None
) -> Path:
    """Re-hash an export after a host application has added its final mix files."""
    return write_project_manifest(project_directory, cancel_event=cancel_event)
