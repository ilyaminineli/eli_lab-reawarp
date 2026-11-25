"""Project archive/export service separated from the desktop window."""
from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from reawarp.core.manifest import refresh_project_manifest
from reawarp.core.project import ReawarpProject
from reawarp.export.wav import write_wav


def _check_cancelled(cancel_event: Any | None, operation: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError(f"{operation} cancelled")


def _audio_snapshot(value: Any, name: str) -> np.ndarray:
    audio = np.asarray(value, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or audio.shape[1] not in {1, 2}:
        raise ValueError(f"{name} must be mono or stereo (frames, channels)")
    if not np.isfinite(audio).all():
        raise ValueError(f"{name} must contain only finite samples")
    return np.ascontiguousarray(audio.copy())


def export_project_archive(
    project: ReawarpProject,
    directory: str | Path,
    *,
    master_audio: Any,
    fx_routing: Mapping[str, Any],
    fx_automation: Mapping[str, Any],
    returns: Mapping[str, Any] | None = None,
    mix_data: Mapping[str, Any] | None = None,
    bit_depth: int = 24,
    asset_policy: str = "copy",
    include_midi: bool = False,
    cancel_event: Any | None = None,
) -> Path:
    """Export a frozen project/mixer snapshot, WAV assets and integrity manifest.

    The caller must snapshot mutable UI state and audio before submitting this
    function to a worker. This service owns only the copied arrays and the new
    archive files; it never edits the source project or mixer buffers.
    """
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    if isinstance(bit_depth, bool) or not isinstance(bit_depth, int) or bit_depth not in {16, 24, 32}:
        raise ValueError("bit_depth must be 16, 24 or 32")
    destination = Path(directory).expanduser()
    master = _audio_snapshot(master_audio, "master_audio")
    if len(master) < project.frame_count:
        raise ValueError("master_audio cannot be shorter than the project stem duration")
    if not project.stems:
        raise ValueError("project must contain at least one source stem")
    channel_counts = set()
    for name, audio in project.stems.items():
        value = np.asarray(audio)
        if value.ndim not in {1, 2} or (value.ndim == 2 and value.shape[1] not in {1, 2}):
            raise ValueError(f"project stem {name!r} must be mono or stereo audio")
        channel_counts.add(1 if value.ndim == 1 else value.shape[1])
    if len(channel_counts) != 1:
        raise ValueError("project stems must use a consistent channel count")
    if master.shape[1] != next(iter(channel_counts)):
        raise ValueError("master channel count must match project stems")
    return_snapshots: dict[str, np.ndarray] = {}
    for bus, audio in (returns or {}).items():
        if bus not in {"space", "echo"}:
            raise ValueError(f"unsupported FX return name: {bus!r}")
        snapshot = _audio_snapshot(audio, f"{bus} return")
        if snapshot.shape[1] != next(iter(channel_counts)):
            raise ValueError(f"{bus} return channel count must match project stems")
        return_snapshots[bus] = snapshot

    try:
        mix_record = json.loads(json.dumps(
            dict(mix_data or {}), ensure_ascii=False, allow_nan=False
        ))
    except (TypeError, ValueError) as exc:
        raise ValueError("mix_data must be finite JSON-compatible data") from exc

    _check_cancelled(cancel_event, "project export")
    output = project.export(
        destination,
        bit_depth=bit_depth,
        include_stems=True,
        include_master=True,
        fx_routing=dict(fx_routing),
        fx_automation=dict(fx_automation),
        asset_policy=asset_policy,
        include_midi=include_midi,
        cancel_event=cancel_event,
    )
    _check_cancelled(cancel_event, "project export")
    write_wav(output / "master.wav", master, project.sample_rate, bit_depth)
    if return_snapshots:
        return_directory = output / "returns"
        return_directory.mkdir(parents=True, exist_ok=True)
    for bus, audio in return_snapshots.items():
        _check_cancelled(cancel_event, "project export")
        write_wav(output / "returns" / f"{bus}.wav", audio, project.sample_rate, bit_depth)
    _check_cancelled(cancel_event, "project export")
    temporary = output / "mix.json.tmp"
    temporary.write_text(
        json.dumps(mix_record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output / "mix.json")
    _check_cancelled(cancel_event, "project export")
    package_readme = """# Reawarp project package

This is a portable Reawarp project handoff. Open the extracted folder with Reawarp's
project loader or use `ReawarpProject.load(folder)`.

## Contents

- `master.wav`: the final routed master from the exported mixer snapshot.
- `stems/`: original aligned dry generation stems; these are not overwritten by FX.
- `returns/`: rendered SPACE/ECHO wet-only auxiliary returns when active.
- `score.json` and `events.json`: canonical Score and compatibility event records.
- `midi/score.mid`: combined Standard MIDI 1.0 export with one track per voice.
- `midi/voices/`: separate voice MIDI files for individual instrument/role import.
- `project.json`, `fx_routing.json`, `fx_automation.json`, and `mix.json`:
  generation, production, routing and automation settings.
- `assets/`: copied source samples by default, with hashes and asset identities.
- `manifest.json`: schema, environment, source-asset audit and SHA-256 file inventory.
- `candidates/` and `listening_report.json`: variation session data when present.

MIDI 1.0 uses integer semitone notes and finite tick resolution. Reawarp-specific text
meta events preserve exact pitch/event provenance when the file is read back by Reawarp;
other MIDI applications may ignore that metadata. The Reawarp Score remains authoritative.

For reference-only asset exports, external source files must remain available at their
recorded paths. Missing or changed sources are reported rather than substituted.
"""
    (output / "PACKAGE_README.md").write_text(package_readme, encoding="utf-8")
    refresh_project_manifest(output, cancel_event=cancel_event)
    return output


def export_project_package(
    project: ReawarpProject,
    archive_path: str | Path,
    *,
    master_audio: Any,
    fx_routing: Mapping[str, Any],
    fx_automation: Mapping[str, Any],
    returns: Mapping[str, Any] | None = None,
    mix_data: Mapping[str, Any] | None = None,
    bit_depth: int = 24,
    asset_policy: str = "copy",
    include_midi: bool = True,
    cancel_event: Any | None = None,
) -> Path:
    """Build a complete folder export and atomically package it as a ZIP handoff.

    ZIP creation is intentionally outside the generated project folder so that
    the manifest inventory remains stable and does not hash its own archive.
    """
    destination = Path(archive_path).expanduser()
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_archive = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with tempfile.TemporaryDirectory(prefix="reawarp-project-package-") as temporary:
            folder = export_project_archive(
                project,
                Path(temporary) / "Reawarp_Project",
                master_audio=master_audio,
                fx_routing=fx_routing,
                fx_automation=fx_automation,
                returns=returns,
                mix_data=mix_data,
                bit_depth=bit_depth,
                asset_policy=asset_policy,
                include_midi=include_midi,
                cancel_event=cancel_event,
            )
            _check_cancelled(cancel_event, "project package")
            with zipfile.ZipFile(
                temporary_archive, mode="w",
                compression=zipfile.ZIP_DEFLATED, compresslevel=6,
            ) as archive:
                for source in sorted(folder.rglob("*")):
                    _check_cancelled(cancel_event, "project package")
                    if not source.is_file():
                        continue
                    resolved = source.resolve()
                    if not resolved.is_relative_to(folder.resolve()):
                        raise ValueError(f"package member escapes export folder: {source}")
                    archive.write(source, source.relative_to(folder).as_posix())
        _check_cancelled(cancel_event, "project package")
        temporary_archive.replace(destination)
        return destination
    except Exception:
        try:
            temporary_archive.unlink(missing_ok=True)
        except OSError:
            pass
        raise
