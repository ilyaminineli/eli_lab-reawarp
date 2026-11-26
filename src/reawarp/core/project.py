"""In-memory generation result and synchronized stem export."""

from __future__ import annotations

import json
import math
import platform
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reawarp.score.model import Score

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.core.manifest import (
    audit_project_assets, audit_project_file_inventory, prepare_project_assets,
    resolve_project_asset_paths, write_project_manifest,
)
from reawarp.export.wav import write_wav


def _check_cancelled(cancel_event: Any | None, operation: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError(f"{operation} cancelled")


@dataclass(slots=True)
class ReawarpProject:
    config: GenerationConfig
    sample_rate: int
    stems: dict[str, np.ndarray]
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    score: Score | None = None
    variation_candidates: dict[str, ReawarpProject] = field(default_factory=dict, repr=False, compare=False)

    @property
    def frame_count(self) -> int:
        return next(iter(self.stems.values())).shape[0] if self.stems else self.config.frame_count

    @property
    def duration(self) -> float:
        return self.frame_count / float(self.sample_rate)

    @property
    def composition_brief(self):
        """Return the saved M27 brief, or a read-only legacy view without write-back."""
        from reawarp.composition.brief import CompositionBrief

        saved = self.metadata.get("m27_composition_brief")
        return CompositionBrief.from_dict(saved) if isinstance(saved, dict) else CompositionBrief.legacy()

    def to_score(self, *, title: str | None = None):
        """Return the canonical score, or adapt a legacy project when absent."""
        if self.score is not None:
            return self.score if title is None else replace(self.score, title=title)
        from reawarp.score.conversion import project_to_score

        return project_to_score(self, title=title)

    def render_master(self) -> np.ndarray:
        if not self.stems:
            return np.zeros((self.config.frame_count, 2), dtype=np.float32)
        master = np.zeros_like(next(iter(self.stems.values())), dtype=np.float32)
        for stem in self.stems.values():
            master += stem
        peak = float(np.max(np.abs(master))) if master.size else 0.0
        ceiling = 10.0 ** (-1.0 / 20.0)
        if peak > ceiling:
            master *= ceiling / peak
        return np.clip(master, -1.0, 1.0).astype(np.float32, copy=False)

    def export(
            self,
            directory: str | Path,
            *,
            bit_depth: int = 24,
            include_stems: bool = True,
            include_master: bool = True,
            fx_routing: dict[str, Any] | None = None,
            fx_automation: dict[str, Any] | None = None,
            asset_policy: str = "copy",
            include_midi: bool = False,
            cancel_event: Any | None = None,
            _include_variations: bool = True,
    ) -> Path:
        output = Path(directory).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        _check_cancelled(cancel_event, "project export")
        asset_records, portable_config = prepare_project_assets(
            self.config.to_dict(), output, asset_policy=asset_policy,
            cancel_event=cancel_event,
        )
        if include_stems:
            stem_directory = output / "stems"
            stem_directory.mkdir(parents=True, exist_ok=True)
            for name, audio in self.stems.items():
                _check_cancelled(cancel_event, "project export")
                write_wav(stem_directory / f"{name}.wav", audio, self.sample_rate, bit_depth)
        _check_cancelled(cancel_event, "project export")
        if include_master:
            write_wav(output / "master.wav", self.render_master(), self.sample_rate, bit_depth)

        project_record = {
            "schema_version": 1,
            "application": "eli_lab-reawarp",
            "application_version": "0.12.0",
            "renderer_version": str(self.metadata.get(
                "renderer_version",
                f"legacy-generator/{self.metadata.get('algorithm_version', 'unknown')}",
            )),
            "score_file": "score.json",
            "score_schema_version": 1,
            "python_version": platform.python_version(),
            "sample_rate": self.sample_rate,
            "duration_seconds": self.duration,
            "frame_count": self.frame_count,
            "config": portable_config,
            "metadata": self.metadata,
            "stems": list(self.stems),
            "render_provenance": {
                "renderer_version": str(self.metadata.get(
                    "renderer_version",
                    f"legacy-generator/{self.metadata.get('algorithm_version', 'unknown')}",
                )),
                "root_seed": self.config.seed,
                "sample_rate": self.sample_rate,
                "frame_count": self.frame_count,
                "duration_seconds": self.duration,
            },
            "export": {
                "bit_depth": bit_depth, "master": include_master, "stems": include_stems,
                "asset_policy": asset_policy, "midi": bool(include_midi),
            },
        }
        if fx_routing is None:
            saved_routing = self.metadata.get("project_fx_routing")
            fx_routing = saved_routing if isinstance(saved_routing, dict) else None
        if fx_automation is None:
            saved_automation = self.metadata.get("project_fx_automation")
            fx_automation = saved_automation if isinstance(saved_automation, dict) else None
        if fx_routing is not None:
            from reawarp.fx_routing import normalise_fx_routing

            normalized_routing = normalise_fx_routing(
                fx_routing, tuple(self.stems), self.sample_rate
            )
            (output / "fx_routing.json").write_text(
                json.dumps(normalized_routing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            project_record["fx_routing_file"] = "fx_routing.json"
        if fx_automation is not None:
            from reawarp.fx_automation import normalise_fx_automation

            normalized_automation = normalise_fx_automation(
                fx_automation, tuple(self.stems)
            )
            (output / "fx_automation.json").write_text(
                json.dumps(normalized_automation, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            project_record["fx_automation_file"] = "fx_automation.json"
        if _include_variations and self.variation_candidates:
            candidate_ids = []
            for candidate_id, candidate in sorted(self.variation_candidates.items()):
                _check_cancelled(cancel_event, "project export")
                safe_id = str(candidate_id)
                if (
                    not safe_id or safe_id in {".", ".."}
                    or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in safe_id)
                ):
                    raise ValueError(f"invalid variation candidate ID: {candidate_id!r}")
                candidate.export(
                    output / "candidates" / safe_id,
                    bit_depth=bit_depth,
                    include_stems=True,
                    include_master=True,
                    asset_policy=asset_policy,
                    cancel_event=cancel_event,
                    _include_variations=False,
                )
                candidate_ids.append(safe_id)
            project_record["variation_candidates"] = candidate_ids
        (output / "project.json").write_text(
            json.dumps(project_record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (output / "events.json").write_text(
            json.dumps({"schema_version": 1, "events": self.events}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        session = self.metadata.get("m23_variations")
        if isinstance(session, dict):
            report = {
                "schema_version": 1,
                "policy": "human_selection_only_no_artistic_auto_score",
                "base_project_fingerprint": session.get("base_project_fingerprint"),
                "active_candidate_id": session.get("active_candidate_id"),
                "candidates": [
                    {
                        "candidate_id": item.get("candidate_id"),
                        "label": item.get("label"),
                        "selection_state": item.get("selection_state"),
                        "parent_candidate_id": item.get("parent_candidate_id"),
                        "mode": item.get("mode"),
                        "targets": item.get("targets", []),
                        "variation_seed": item.get("variation_seed"),
                        "technical_flags": item.get("technical_flags", []),
                        "technical_metrics": item.get("technical_metrics", {}),
                        "notes": item.get("notes", ""),
                    }
                    for item in session.get("candidate_records", [])
                    if isinstance(item, dict)
                ],
            }
            (output / "listening_report.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        m32_session = self.metadata.get("m32_listening_session")
        if isinstance(m32_session, dict):
            from reawarp.listening import (
                listening_report_markdown, validate_listening_session,
            )

            validated_session = validate_listening_session(m32_session)
            (output / "critical_listening_report.json").write_text(
                json.dumps(validated_session, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            (output / "critical_listening_report.md").write_text(
                listening_report_markdown(validated_session),
                encoding="utf-8",
            )
        _check_cancelled(cancel_event, "project export")
        score = self.to_score()
        arrangement_record = score.metadata.get("m33_arrangement")
        if isinstance(arrangement_record, dict):
            from reawarp.composition.arrangement import (
                arrangement_snapshot, copy_print_assets,
            )

            snapshot = arrangement_snapshot(score)
            snapshot["print_exports"] = copy_print_assets(
                arrangement_record, output / "arrangement_prints"
            )
            (output / "arrangement_snapshot.json").write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        score.save(output / "score.json")
        if include_midi:
            _check_cancelled(cancel_event, "project MIDI export")
            midi_root = output / "midi"
            voice_root = midi_root / "voices"
            voice_root.mkdir(parents=True, exist_ok=True)
            score.export_midi(midi_root / "score.mid")
            import hashlib
            import re

            exported_voice_files = []
            voices = sorted({
                event.voice_id for event in score.events
                if event.kind not in {"control", "marker"}
            })
            for voice_id in voices:
                _check_cancelled(cancel_event, "project MIDI export")
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
                slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(voice_id)).strip("_") or "voice"
                digest = hashlib.sha256(str(voice_id).encode("utf-8")).hexdigest()[:8]
                voice_path = voice_root / f"{slug[:48]}-{digest}.mid"
                voice_score.export_midi(voice_path)
                exported_voice_files.append(voice_path.relative_to(output).as_posix())
            project_record["midi"] = {
                "combined_score": "midi/score.mid",
                "voice_files": exported_voice_files,
                "format": "Standard MIDI 1.0",
                "notes": (
                    "Fractional pitches are rounded for MIDI playback; exact Reawarp pitch, "
                    "event identity and orchestration metadata are retained in Reawarp text events."
                ),
            }
            (output / "project.json").write_text(
                json.dumps(project_record, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        write_project_manifest(
            output, source_assets=asset_records, cancel_event=cancel_event
        )
        return output

    @classmethod
    def load(
        cls, directory: str | Path, *, cancel_event: Any | None = None
    ) -> "ReawarpProject":
        """Reopen and validate a complete exported project folder."""
        from reawarp.export.wav import read_wav
        from reawarp.score.model import Score

        _check_cancelled(cancel_event, "project load")
        root = Path(directory).expanduser().resolve()
        record = json.loads((root / "project.json").read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            raise ValueError("unsupported or invalid Reawarp project schema")
        if record.get("application") != "eli_lab-reawarp":
            raise ValueError("directory is not a Reawarp project")
        export_options = record.get("export", {})
        if not isinstance(export_options, dict) or not export_options.get("stems", True):
            raise ValueError("project export does not contain source stems")

        config_data = record.get("config")
        asset_validation = None
        file_validation = None
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("format") != "eli_lab_reawarp_project_manifest"
                or manifest.get("schema_version") != 1
            ):
                raise ValueError("unsupported project manifest schema; an explicit migration is required")
            asset_validation = audit_project_assets(
                root, manifest.get("source_assets", []), cancel_event=cancel_event
            )
            file_validation = audit_project_file_inventory(
                root, manifest.get("file_inventory", []), cancel_event=cancel_event
            )
            config_data = resolve_project_asset_paths(config_data, root)
        config = GenerationConfig.from_dict(config_data)
        if asset_validation is None:
            legacy_assets, _legacy_config = prepare_project_assets(
                config_data, root, asset_policy="reference", cancel_event=cancel_event
            )
            if legacy_assets:
                asset_validation = audit_project_assets(
                    root, legacy_assets, cancel_event=cancel_event
                )
                asset_validation["source"] = "legacy_config_audit"
                asset_validation["manifest_available"] = False
        sample_rate = int(record.get("sample_rate", 0))
        frame_count = int(record.get("frame_count", 0))
        if sample_rate <= 0 or frame_count <= 0:
            raise ValueError("project sample rate and frame count must be positive")
        if config.sample_rate != sample_rate or config.frame_count != frame_count:
            raise ValueError("project timing does not match its generation configuration")
        duration = float(record.get("duration_seconds", -1.0))
        expected_duration = frame_count / float(sample_rate)
        if not math.isfinite(duration) or not math.isclose(
                duration, expected_duration, rel_tol=0.0, abs_tol=1.0 / sample_rate
        ):
            raise ValueError("project duration does not match its frame count")

        stem_names = record.get("stems")
        if not isinstance(stem_names, list) or not stem_names:
            raise ValueError("project does not list any source stems")
        if len(stem_names) != len(set(stem_names)):
            raise ValueError("project stem names must be unique")

        stems: dict[str, np.ndarray] = {}
        safe_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for name in stem_names:
            _check_cancelled(cancel_event, "project load")
            if (
                not isinstance(name, str)
                or not name
                or name in {".", ".."}
                or any(character not in safe_characters for character in name)
            ):
                raise ValueError(f"invalid project stem name: {name!r}")
            audio, stem_rate = read_wav(root / "stems" / f"{name}.wav")
            if stem_rate != sample_rate:
                raise ValueError(f"stem {name!r} uses a different sample rate")
            if len(audio) != frame_count:
                raise ValueError(f"stem {name!r} is not aligned to the project frame count")
            if not np.isfinite(audio).all():
                raise ValueError(f"stem {name!r} contains non-finite samples")
            stems[name] = audio

        event_record = json.loads((root / "events.json").read_text(encoding="utf-8"))
        if not isinstance(event_record, dict) or event_record.get("schema_version") != 1:
            raise ValueError("unsupported or invalid project event schema")
        events = event_record.get("events")
        if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
            raise ValueError("project events must be a list of JSON objects")

        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("project metadata must be a JSON object")
        brief_record = metadata.get("m27_composition_brief")
        if brief_record is not None:
            from reawarp.composition.brief import CompositionBrief

            brief = CompositionBrief.from_dict(brief_record)
            resolved_intent = metadata.get("m27_resolved_intent")
            if not isinstance(resolved_intent, dict):
                raise ValueError("project M27 brief is missing its resolved-intent provenance")
            if resolved_intent.get("schema_version") != 1:
                raise ValueError("unsupported project M27 resolved-intent schema")
            if resolved_intent.get("brief_fingerprint") != brief.fingerprint:
                raise ValueError("project M27 brief fingerprint does not match its provenance")
            if resolved_intent.get("brief_id") != brief.brief_id:
                raise ValueError("project M27 brief ID does not match its provenance")
            if resolved_intent.get("generation_seed") != config.seed:
                raise ValueError("project M27 generation seed does not match its configuration")
            if not isinstance(resolved_intent.get("source_families"), list):
                raise ValueError("project M27 resolved source-family provenance is invalid")

            exploration = metadata.get("m27_bounded_exploration")
            exploration_enabled = metadata.get(
                "m27_bounded_exploration_enabled", exploration is not None
            )
            if not isinstance(exploration_enabled, bool):
                raise ValueError("project M27 exploration-enabled flag must be boolean")
            if exploration_enabled != (exploration is not None):
                raise ValueError("project M27 exploration flag and audit record disagree")
            if exploration is not None:
                if not isinstance(exploration, dict) or exploration.get("schema_version") != 1:
                    raise ValueError("project M27 bounded-exploration provenance is invalid")
                changes = exploration.get("field_changes")
                seeds = exploration.get("seed_lineage")
                preserved = exploration.get("preserved_fields")
                applied = exploration.get("applied_contract_ids")
                if (
                    not isinstance(changes, dict) or not changes
                    or not isinstance(seeds, dict)
                    or not isinstance(preserved, list)
                    or not isinstance(applied, list)
                ):
                    raise ValueError("project M27 exploration audit fields are malformed")
                contracts = {item.contract_id: item for item in brief.mutation_contracts}
                field_contracts: dict[str, Any] = {}
                for contract in brief.mutation_contracts:
                    for field_name in contract.mutable_fields:
                        if field_name in field_contracts:
                            raise ValueError(
                                f"project M27 field {field_name!r} is permitted by multiple contracts"
                            )
                        field_contracts[field_name] = contract
                if not set(changes) <= set(field_contracts):
                    raise ValueError("project M27 exploration changed a field outside its contracts")
                expected_seeds: dict[str, int] = {}
                changed_contract_ids: set[str] = set()
                config_values = config.to_dict()
                from reawarp.core.random_streams import derive_seed

                for field_name, change in changes.items():
                    if not isinstance(change, dict) or not {"before", "after", "contract_id"} <= set(change):
                        raise ValueError(f"project M27 change record for {field_name!r} is malformed")
                    contract = field_contracts[field_name]
                    if change["contract_id"] != contract.contract_id:
                        raise ValueError(f"project M27 change for {field_name!r} names the wrong contract")
                    changed_contract_ids.add(contract.contract_id)
                    seed_name = (
                        f"composition-brief:v{brief.schema_version}:"
                        f"{brief.brief_id}:{contract.contract_id}:{contract.scale}:{field_name}"
                    )
                    expected_seeds[seed_name] = derive_seed(config.seed, seed_name)
                    current_value = config_values.get(field_name)
                    if json.dumps(current_value, sort_keys=True) != json.dumps(
                        change["after"], sort_keys=True
                    ):
                        raise ValueError(
                            f"project M27 final config does not match the recorded {field_name!r} mutation"
                        )
                if set(seeds) != set(expected_seeds):
                    raise ValueError("project M27 seed lineage does not match changed fields")
                for seed_name, expected_seed in expected_seeds.items():
                    if seeds.get(seed_name) != expected_seed:
                        raise ValueError(f"project M27 seed lineage is invalid for {seed_name!r}")
                if set(applied) != changed_contract_ids or not set(applied) <= set(contracts):
                    raise ValueError("project M27 applied contract IDs do not match changed fields")
                if not set(preserved) >= {
                    "seed", "sample_rate", "sample_paths", "sample_metadata", "sample_banks"
                } or set(preserved) & set(changes):
                    raise ValueError("project M27 preserved-field audit violates source/clock invariants")
        score_name = str(record.get("score_file", "score.json"))
        score_path = (root / score_name).resolve()
        if not score_path.is_relative_to(root) or not score_path.is_file():
            raise ValueError(f"project Score file is missing or unsafe: {score_name}")
        score = Score.load(score_path)
        if int(record.get("score_schema_version", score.schema_version)) != score.schema_version:
            raise ValueError("project score_schema_version does not match the archived Score")
        if int(score.metadata.get("sample_rate", 0)) != sample_rate:
            raise ValueError("project score sample rate does not match the audio stems")
        if list(score.metadata.get("render_stems", [])) != list(stem_names):
            raise ValueError("project score stem list does not match project.json")

        routing_name = record.get("fx_routing_file")
        if routing_name is None and (root / "fx_routing.json").is_file():
            routing_name = "fx_routing.json"
        if routing_name is not None:
            from reawarp.fx_routing import load_fx_routing

            routing_path = (root / str(routing_name)).resolve()
            if not routing_path.is_relative_to(root.resolve()) or not routing_path.is_file():
                raise ValueError(f"project FX routing file is missing or unsafe: {routing_name}")
            metadata["project_fx_routing"] = load_fx_routing(
                routing_path, tuple(stem_names), sample_rate
            )
        automation_name = record.get("fx_automation_file")
        if automation_name is None and (root / "fx_automation.json").is_file():
            automation_name = "fx_automation.json"
        if automation_name is not None:
            from reawarp.fx_automation import load_fx_automation

            automation_path = (root / str(automation_name)).resolve()
            if not automation_path.is_relative_to(root.resolve()) or not automation_path.is_file():
                raise ValueError(f"project FX automation file is missing or unsafe: {automation_name}")
            metadata["project_fx_automation"] = load_fx_automation(
                automation_path, tuple(stem_names)
            )

        project = cls(
            config=config,
            sample_rate=sample_rate,
            stems=stems,
            events=events,
            metadata=metadata,
            score=score,
        )
        asset_records_present = bool(
            asset_validation and asset_validation.get("assets")
        )
        asset_findings = bool(
            asset_validation and (
                asset_validation.get("missing") or asset_validation.get("changed")
            )
        )
        file_findings = bool(
            file_validation and (
                file_validation.get("missing") or file_validation.get("changed")
            )
        )
        if asset_validation is not None and (asset_records_present or asset_findings):
            project.metadata["project_asset_validation"] = asset_validation
        if file_validation is not None and (asset_records_present or file_findings):
            project.metadata["project_file_validation"] = file_validation
        candidate_ids = record.get("variation_candidates", [])
        if not isinstance(candidate_ids, list):
            raise ValueError("variation_candidates must be a list")
        for candidate_id in candidate_ids:
            _check_cancelled(cancel_event, "project load")
            safe_id = str(candidate_id)
            if (
                not safe_id or safe_id in {".", ".."}
                or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in safe_id)
            ):
                raise ValueError(f"invalid variation candidate ID: {candidate_id!r}")
            candidate_directory = root / "candidates" / safe_id
            if not candidate_directory.is_dir():
                raise ValueError(f"variation candidate export is missing: {safe_id}")
            project.variation_candidates[safe_id] = cls.load(
                candidate_directory, cancel_event=cancel_event
            )
        return project
