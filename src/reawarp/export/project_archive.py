"""Project archive/export service separated from the desktop window."""

from __future__ import annotations

import json
import tempfile
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
    if (
        isinstance(bit_depth, bool)
        or not isinstance(bit_depth, int)
        or bit_depth not in {16, 24, 32}
    ):
        raise ValueError("bit_depth must be 16, 24 or 32")
    destination = Path(directory).expanduser()
    master = _audio_snapshot(master_audio, "master_audio")
    if len(master) < project.frame_count:
        raise ValueError(
            "master_audio cannot be shorter than the project stem duration"
        )
    if not project.stems:
        raise ValueError("project must contain at least one source stem")
    channel_counts = set()
    for name, audio in project.stems.items():
        value = np.asarray(audio)
        if value.ndim not in {1, 2} or (
            value.ndim == 2 and value.shape[1] not in {1, 2}
        ):
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
        mix_record = json.loads(
            json.dumps(dict(mix_data or {}), ensure_ascii=False, allow_nan=False)
        )
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
        write_wav(
            output / "returns" / f"{bus}.wav", audio, project.sample_rate, bit_depth
        )
    _check_cancelled(cancel_event, "project export")
    temporary = output / "mix.json.tmp"
    temporary.write_text(
        json.dumps(mix_record, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output / "mix.json")
    _check_cancelled(cancel_event, "project export")
    midi_contents = (
        "- `midi/score.mid`: combined Standard MIDI 1.0 export with one track per voice.\n"
        "- `midi/voices/`: separate voice MIDI files for individual instrument/role import.\n"
        if include_midi
        else "- MIDI export was not requested for this folder.\n"
    )
    package_readme = """# Reawarp project package

This is a portable Reawarp project handoff. Open the extracted folder with Reawarp's
project loader or use `ReawarpProject.load(folder)`.

## Contents

- `master.wav`: the final routed master from the exported mixer snapshot.
- `stems/`: original aligned dry generation stems; these are not overwritten by FX.
- `returns/`: rendered SPACE/ECHO wet-only auxiliary returns when active.
- `score.json` and `events.json`: canonical Score and compatibility event records.
- `project.json`, `fx_routing.json`, `fx_automation.json`, and `mix.json`:
  generation, production, routing and automation settings.
- `assets/`: copied source samples by default, with hashes and asset identities.
- `manifest.json`: schema, environment, source-asset audit and SHA-256 file inventory.
- `candidates/` and `listening_report.json`: variation session data when present.
- `critical_listening_report.json` and `critical_listening_report.md`: M32 audition provenance, technical evidence and human-authored listening notes when present.
- `arrangement_snapshot.json` and `arrangement_prints/`: M33 phrase/cue order, finishing checklist, reversible edit history and verified printed WAV objects when present.

MIDI 1.0 uses integer semitone notes and finite tick resolution. When MIDI is included,
Reawarp-specific escaped text metadata preserves exact pitch/event provenance for
Reawarp-to-Reawarp import. Other MIDI applications may ignore that metadata. The
Reawarp Score remains authoritative.

For reference-only asset exports, external source files must remain available at their
recorded paths. Missing or changed sources are reported rather than substituted.
"""
    package_readme = package_readme.replace(
        "- `project.json`,", midi_contents + "- `project.json`,"
    )
    (output / "PACKAGE_README.md").write_text(package_readme, encoding="utf-8")
    refresh_project_manifest(output, cancel_event=cancel_event)
    return output


def export_project_package(
    project: ReawarpProject,
    directory: str | Path,
    *,
    master_audio: Any,
    bit_depth: int = 24,
    include_midi: bool = True,
    fx_render_status: str = "not_configured",
    cancel_event: Any | None = None,
) -> Path:
    """Export a delivery folder containing README, routed master, dry stems and MIDI.

    This is deliberately not a restorable Reawarp project archive. Source sample
    files, project JSON, manifests, FX configuration, returns and ZIP packaging
    are intentionally excluded. The master contains the current routed mix;
    stem files are the original aligned generation stems, kept non-destructive.
    """
    if not isinstance(project, ReawarpProject):
        raise TypeError("project must be a ReawarpProject")
    if (
        isinstance(bit_depth, bool)
        or not isinstance(bit_depth, int)
        or bit_depth not in {16, 24, 32}
    ):
        raise ValueError("bit_depth must be 16, 24 or 32")
    if fx_render_status not in {"rendered", "dry_fallback", "not_configured"}:
        raise ValueError("invalid FX render status")
    destination = Path(directory).expanduser()
    if not destination.name or destination.name in {".", ".."}:
        raise ValueError("delivery directory must have a valid final folder name")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"delivery folder already exists: {destination}")
    master = _audio_snapshot(master_audio, "master_audio")
    if len(master) < project.frame_count:
        raise ValueError(
            "master_audio cannot be shorter than the project stem duration"
        )
    if not project.stems:
        raise ValueError("project must contain at least one source stem")

    stem_snapshots: dict[str, np.ndarray] = {}
    channel_counts: set[int] = set()
    safe_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    for name, audio in project.stems.items():
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or any(character not in safe_characters for character in name)
        ):
            raise ValueError(f"invalid project stem name: {name!r}")
        snapshot = _audio_snapshot(audio, f"stem {name}")
        if len(snapshot) != project.frame_count:
            raise ValueError(f"stem {name!r} must align to the project frame count")
        channel_counts.add(int(snapshot.shape[1]))
        stem_snapshots[name] = snapshot
    if len(channel_counts) != 1:
        raise ValueError("project stems must use a consistent channel count")
    if master.shape[1] != next(iter(channel_counts)):
        raise ValueError("master channel count must match project stems")

    score = project.to_score()
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}.tmp-", dir=str(parent)
    ) as temporary:
        staging = Path(temporary) / destination.name
        staging.mkdir(parents=True)
        _check_cancelled(cancel_event, "delivery export")
        write_wav(staging / "master.wav", master, project.sample_rate, bit_depth)

        stems_directory = staging / "stems"
        stems_directory.mkdir()
        for name, audio in stem_snapshots.items():
            _check_cancelled(cancel_event, "delivery export")
            write_wav(
                stems_directory / f"{name}.wav", audio, project.sample_rate, bit_depth
            )

        if include_midi:
            import hashlib
            import re
            from dataclasses import replace

            midi_root = staging / "midi"
            voice_root = midi_root / "voices"
            voice_root.mkdir(parents=True)
            _check_cancelled(cancel_event, "delivery MIDI export")
            combined_midi = midi_root / "score.mid"
            score.export_midi(combined_midi)
            voice_ids = sorted(
                {
                    event.voice_id
                    for event in score.events
                    if event.kind not in {"control", "marker"}
                }
            )
            for voice_id in voice_ids:
                _check_cancelled(cancel_event, "delivery MIDI export")
                events = tuple(
                    event for event in score.events if event.voice_id == voice_id
                )
                voice_score = replace(
                    score,
                    title=f"{score.title} — {voice_id}",
                    events=events,
                    automation=(),
                    automation_sources=(),
                    modulations=(),
                )
                slug = (
                    re.sub(r"[^A-Za-z0-9_-]+", "_", str(voice_id)).strip("_") or "voice"
                )
                digest = hashlib.sha256(str(voice_id).encode("utf-8")).hexdigest()[:8]
                voice_path = voice_root / f"{slug[:48]}-{digest}.mid"
                voice_score.export_midi(voice_path)

        _check_cancelled(cancel_event, "delivery export")
        title = str(getattr(score, "title", "") or "Untitled Reawarp composition")
        config = project.config
        if fx_render_status == "rendered":
            fx_description = "The master includes the completed routed FX render and current mixer settings."
        elif fx_render_status == "dry_fallback":
            fx_description = "FX rendering failed; the master is a dry-fallback mix. No effects are claimed as rendered."
        else:
            fx_description = "No project FX routing was configured; the master reflects the available mix."
        midi_description = (
            "- midi/score.mid: combined Standard MIDI 1.0 file.\n"
            "- midi/voices/: separate MIDI file for each event-backed voice.\n"
            if include_midi
            else "MIDI export was not requested.\n"
        )
        package_readme = f"""# {title}

A Reawarp audio delivery folder.

## Contents

- master.wav — final master mix at {project.sample_rate:,} Hz, {bit_depth}-bit.
- stems/ — aligned dry generation stems, one WAV per source role.
{midi_description}
## Render information

- Tempo: {config.bpm:g} BPM
- Duration: {project.duration:.3f} seconds
- Sample rate: {project.sample_rate:,} Hz
- Channels: {master.shape[1]}
- Bit depth: {bit_depth}-bit PCM
- Generation seed: {config.seed}
- Structure: {config.structure}
- Pattern family: {config.pattern_family}

## Audio semantics

The master is the final routed mix, including the mixer levels and any successfully
rendered inserts and shared returns. {fx_description}

The files in stems/ are the original aligned dry generation stems. They are
intentionally not rewritten by the mixer or FX routing, so they remain suitable
for independent processing and remixing. The individual dry stems do not include
their insert effects or the shared SPACE/ECHO returns.

## MIDI notes

MIDI 1.0 is an interchange format with integer semitone notes and finite tick
resolution. Reawarp-specific escaped text metadata may be ignored by other MIDI
applications. The MIDI files are provided for musical interchange; WAV files
remain the audio deliverables.

## Source material and project files

This delivery contains no copied source samples, sample banks, project database,
Score JSON, routing JSON, manifests, intermediate returns or ZIP archive.
It is a finished audio/MIDI handoff, not a self-contained, restorable Reawarp
project. Reopening the original Reawarp project or regenerating it may require
the source samples at their original locations.
"""
        (staging / "README.md").write_text(package_readme, encoding="utf-8")
        _check_cancelled(cancel_event, "delivery export")
        staging.replace(destination)

    return destination
