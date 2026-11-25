from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.core.engine import ReawarpEngine
from reawarp.core.manifest import audit_project_assets
from reawarp.core.project import ReawarpProject
from reawarp.export.project_archive import export_project_archive
from reawarp.export.wav import write_wav
from reawarp.fx_automation import normalise_fx_automation
from reawarp.fx_routing import default_fx_routing, normalise_fx_routing
from reawarp.score.model import Score
from reawarp.synthesis.sound_object import SoundObjectPatch
from reawarp.variations import VariationCandidateRecord


_FIXTURE = Path(__file__).parent / "fixtures" / "m25" / "legacy_contracts_v1.json"


def _project(tmp_path: Path, sample_path: Path | None = None, *, metadata=None) -> ReawarpProject:
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m25-portability",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        sample_paths={"kick": str(sample_path)} if sample_path is not None else {},
    )
    frames = config.frame_count
    score = Score(
        title="M25 portability fixture",
        metadata={
            "sample_rate": config.sample_rate,
            "duration_seconds": config.duration,
            "frame_count": frames,
            "render_stems": ["kick"],
            "seed_streams": {"kick_pattern": 211},
            "generator_families": {"kick": "archive-fixture"},
        },
    )
    audio = np.zeros((frames, 2), dtype=np.float32)
    audio[0] = (0.25, -0.25)
    return ReawarpProject(
        config=config,
        sample_rate=config.sample_rate,
        stems={"kick": audio},
        events=[],
        metadata=dict(metadata or {}),
        score=score,
    )


def test_export_embeds_source_asset_hash_and_reopens_with_resolved_relative_path(tmp_path):
    source = tmp_path / "kick-source.wav"
    write_wav(source, np.asarray([0.2, -0.2, 0.1, -0.1], dtype=np.float32), 22_050, 16)
    original_hash = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    project = _project(tmp_path, source)
    original_config = project.config.to_dict()

    output = project.export(
        tmp_path / "portable",
        fx_routing=default_fx_routing(("kick",)),
        fx_automation={"schema_version": 1, "lanes": {}},
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assets = manifest["source_assets"]
    assert len(assets) == 1
    asset = assets[0]
    assert asset["status"] == "embedded"
    assert asset["sha256"] == original_hash
    assert asset["asset_id"] == "sha256:" + original_hash
    assert (output / asset["project_path"]).is_file()
    assert project.config.to_dict() == original_config
    assert source.is_file()
    assert __import__("hashlib").sha256(source.read_bytes()).hexdigest() == original_hash

    reopened = ReawarpProject.load(output)
    resolved = Path(reopened.config.sample_paths["kick"])
    assert resolved == (output / asset["project_path"]).resolve()
    assert resolved.is_file()
    assert reopened.metadata["project_asset_validation"]["ok"] is True
    assert reopened.metadata["project_file_validation"]["ok"] is True
    assert reopened.metadata["project_fx_routing"]["schema_version"] == 3
    assert reopened.metadata["project_fx_automation"]["schema_version"] == 1
    assert manifest["schemas"]["project"] == 1
    assert manifest["schemas"]["score"] == 1
    inventory_paths = {item["path"] for item in manifest["file_inventory"]}
    assert {"project.json", "score.json", "events.json", "master.wav", "stems/kick.wav"} <= inventory_paths
    assert manifest["render_environment"]["numpy"] == np.__version__
    assert manifest["reproducibility"]["cross_environment"] == "best_effort"


def test_missing_source_is_explicit_and_never_replaced_by_another_sample(tmp_path):
    missing = (tmp_path / "gone" / "original-kick.wav").resolve()
    project = _project(tmp_path, missing)
    output = project.export(tmp_path / "missing-source")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    asset = manifest["source_assets"][0]

    assert asset["status"] == "missing"
    assert asset["asset_id"].startswith("missing-path:")
    assert asset["project_path"] is None
    assert asset["source_path"] == str(missing)

    reopened = ReawarpProject.load(output)
    assert reopened.config.sample_paths["kick"] == str(missing)
    audit = reopened.metadata["project_asset_validation"]
    assert audit["ok"] is False
    assert audit["missing"][0]["asset_id"] == asset["asset_id"]
    assert audit["missing"][0]["path"] == str(missing)


def test_changed_embedded_asset_is_reported_by_hash(tmp_path):
    source = tmp_path / "snare.wav"
    write_wav(source, np.asarray([0.1, 0.2, -0.1], dtype=np.float32), 22_050, 16)
    output = _project(tmp_path, source).export(tmp_path / "changed")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    embedded = output / manifest["source_assets"][0]["project_path"]
    embedded.write_bytes(embedded.read_bytes() + b"tamper")

    audit = audit_project_assets(output)
    assert audit["ok"] is False
    assert audit["changed"][0]["asset_id"] == manifest["source_assets"][0]["asset_id"]
    reopened = ReawarpProject.load(output)
    assert reopened.metadata["project_asset_validation"]["changed"]


def test_reference_asset_policy_records_external_dependency_without_copying(tmp_path):
    source = tmp_path / "external.wav"
    write_wav(source, np.zeros(32, dtype=np.float32), 22_050, 16)
    output = _project(tmp_path, source).export(tmp_path / "reference", asset_policy="reference")
    record = json.loads((output / "manifest.json").read_text(encoding="utf-8"))["source_assets"][0]
    assert record["status"] == "external_reference"
    assert record["project_path"] is None
    assert record["source_path"] == str(source.resolve())
    assert not (output / "assets").exists()
    assert audit_project_assets(output)["ok"] is True


def test_old_project_v1_without_manifest_still_loads_without_rewriting_source(tmp_path):
    source = tmp_path / "source.wav"
    write_wav(source, np.zeros(32, dtype=np.float32), 22_050, 16)
    output = _project(tmp_path, source).export(tmp_path / "legacy", asset_policy="reference")
    (output / "manifest.json").unlink()
    record_before = (output / "project.json").read_bytes()

    reopened = ReawarpProject.load(output)

    assert reopened.config.sample_paths["kick"] == str(source.resolve())
    assert reopened.metadata["project_asset_validation"]["source"] == "legacy_config_audit"
    assert reopened.metadata["project_asset_validation"]["missing"] == []
    assert (output / "project.json").read_bytes() == record_before


def test_manifest_records_candidate_ancestry_and_portable_fx_sidecars(tmp_path):
    metadata = {
        "m23_variations": {
            "candidate_records": [{
                "candidate_id": "candidate-b",
                "parent_candidate_id": "candidate-a",
                "variation_seed": 511,
                "mode": "automation",
                "selection_state": "unreviewed",
                "targets": ["melody"],
            }]
        }
    }
    project = _project(tmp_path, metadata=metadata)
    output = project.export(
        tmp_path / "ancestry",
        fx_routing=default_fx_routing(("kick",)),
        fx_automation={"schema_version": 1, "lanes": {}},
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    ancestry = manifest["candidate_ancestry"]
    assert ancestry[0]["candidate_id"] == "candidate-b"
    assert ancestry[0]["parent_candidate_id"] == "candidate-a"
    assert manifest["fx_files"] == {
        "routing": "fx_routing.json",
        "automation": "fx_automation.json",
        "mix": None,
    }


def test_archived_schema_fixtures_load_or_migrate_with_explicit_current_versions():
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["project_v1"]["schema_version"] == 1
    assert fixture["events_v1"]["schema_version"] == 1

    score = Score.from_dict(fixture["score_v1"])
    assert score.schema_version == 1
    assert score.to_dict()["metadata"]["fixture"] == "m14-archive"

    for key in ("fx_routing_v1", "fx_routing_v2"):
        migrated = normalise_fx_routing(fixture[key], ("kick",), 22_050)
        assert migrated["schema_version"] == 3
        assert migrated["routing_mode"] == "manual"
        assert migrated["stems"]["kick"]["sends"]["space"] > 0.0

    automation = normalise_fx_automation(fixture["fx_automation_v1"], ("kick",))
    assert automation["schema_version"] == 1
    assert "stem.kick.send.space" in automation["lanes"]

    sound_object = SoundObjectPatch.from_dict(fixture["sound_object_v1"])
    assert sound_object.schema_version == 1
    assert sound_object.patch_id == "archive-v1"

    candidate = VariationCandidateRecord.from_dict(fixture["candidate_v1"])
    assert candidate.schema_version == 1
    assert candidate.to_dict()["schema_version"] == 1


def test_unknown_project_manifest_schema_reports_an_actionable_upgrade_error(tmp_path):
    output = _project(tmp_path).export(tmp_path / "unsupported-manifest")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        ReawarpProject.load(output)
    except ValueError as exc:
        assert "explicit migration is required" in str(exc)
    else:
        raise AssertionError("unknown manifest schema unexpectedly loaded")


def test_background_archive_service_writes_mixer_snapshot_returns_and_manifest(tmp_path):
    source = tmp_path / "kick.wav"
    write_wav(source, np.asarray([0.2, -0.1, 0.05], dtype=np.float32), 22_050, 16)
    project = _project(tmp_path, source)
    routing = default_fx_routing(("kick",))
    automation = {"schema_version": 1, "lanes": {}}
    master = np.zeros((project.frame_count + 32, 2), dtype=np.float32)
    master[0] = (0.4, -0.4)
    returns = {"space": np.zeros((project.frame_count + 32, 2), dtype=np.float32)}
    output = export_project_archive(
        project,
        tmp_path / "service-export",
        master_audio=master,
        fx_routing=routing,
        fx_automation=automation,
        returns=returns,
        mix_data={"schema_version": 1, "test": "m25"},
    )
    assert (output / "fx_routing.json").is_file()
    assert (output / "fx_automation.json").is_file()
    assert (output / "returns" / "space.wav").is_file()
    assert json.loads((output / "mix.json").read_text(encoding="utf-8"))["test"] == "m25"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["file_inventory"]} >= {
        "fx_routing.json", "fx_automation.json", "mix.json",
        "returns/space.wav", "master.wav",
    }
    assert audit_project_assets(output)["ok"] is True


def test_background_archive_service_rejects_invalid_return_and_nonfinite_master(tmp_path):
    project = _project(tmp_path)
    route = default_fx_routing(("kick",))
    automation = {"schema_version": 1, "lanes": {}}
    master = np.zeros((project.frame_count, 2), dtype=np.float32)
    try:
        export_project_archive(
            project, tmp_path / "bad-return", master_audio=master,
            fx_routing=route, fx_automation=automation,
            returns={"unknown": np.zeros((8, 2), dtype=np.float32)},
        )
    except ValueError as exc:
        assert "unsupported FX return" in str(exc)
    else:
        raise AssertionError("unsupported return was exported")

    master[0, 0] = np.nan
    try:
        export_project_archive(
            project, tmp_path / "bad-master", master_audio=master,
            fx_routing=route, fx_automation=automation,
        )
    except ValueError as exc:
        assert "finite" in str(exc)
    else:
        raise AssertionError("non-finite master was exported")


def test_generation_records_separate_sample_voice_and_event_timing():
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed=211,
        complexity=0.25,
        include_melody=False,
        include_texture=False,
        include_ambience=False,
    )
    project = ReawarpEngine().generate(config)
    performance = project.metadata["performance"]
    required = {
        "planning_seconds", "event_generation_seconds", "sample_preparation_seconds",
        "voice_renderer_setup_seconds", "control_bus_seconds",
        "event_scheduling_seconds", "voice_callback_seconds",
        "sample_trigger_callback_seconds", "event_accumulation_seconds",
        "field_render_seconds", "headroom_seconds", "total_engine_seconds",
    }
    detail = project.metadata["performance_detail"]
    assert {"callback_seconds_by_voice", "callback_counts_by_voice"} <= set(detail)
    assert required <= set(performance)
    assert performance["scheduled_event_count"] >= performance["rendered_event_count"] > 0
    assert sum(detail["callback_counts_by_voice"].values()) == performance["rendered_event_count"]
    assert performance["voice_callback_seconds"] >= performance["sample_trigger_callback_seconds"]
    assert performance["total_engine_seconds"] > 0.0
    assert project.metadata["performance"] == performance


def test_legacy_project_without_manifest_reports_a_missing_external_source(tmp_path):
    source = tmp_path / "legacy-kick.wav"
    write_wav(source, np.zeros(32, dtype=np.float32), 22_050, 16)
    output = _project(tmp_path, source).export(
        tmp_path / "legacy-missing", asset_policy="reference"
    )
    (output / "manifest.json").unlink()
    project_record_before = (output / "project.json").read_bytes()
    source.unlink()

    reopened = ReawarpProject.load(output)

    audit = reopened.metadata["project_asset_validation"]
    assert audit["source"] == "legacy_config_audit"
    assert audit["manifest_available"] is False
    assert audit["ok"] is False
    assert audit["missing"][0]["path"] == str(source.resolve())
    assert audit["missing"][0]["asset_id"].startswith("missing-path:")
    assert (output / "project.json").read_bytes() == project_record_before


def test_generation_and_archive_export_observe_cooperative_cancellation(tmp_path):
    cancelled = threading.Event()
    cancelled.set()
    config = GenerationConfig(
        duration=5.0, sample_rate=22_050, seed=211,
        include_melody=False, include_texture=False, include_ambience=False,
    )
    try:
        ReawarpEngine().generate(config, cancel_event=cancelled)
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("cancelled generation unexpectedly completed")

    project = _project(tmp_path)
    try:
        project.export(tmp_path / "cancelled-project", cancel_event=cancelled)
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("cancelled project export unexpectedly completed")

    try:
        export_project_archive(
            project, tmp_path / "cancelled-archive",
            master_audio=np.zeros((project.frame_count, 2), dtype=np.float32),
            fx_routing=default_fx_routing(("kick",)),
            fx_automation={"schema_version": 1, "lanes": {}},
            cancel_event=cancelled,
        )
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("cancelled archive service unexpectedly completed")
