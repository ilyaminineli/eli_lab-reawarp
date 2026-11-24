from pathlib import Path

import pytest

from reawarp.samples.iro import (
    load_drum_assets,
    load_entity_assets,
    load_iro_assets,
    load_sound_fx_assets,
    load_sound_lab_assets,
    verify_iro_assets,
    _safe_path,
)


def test_iro_catalog_preserves_release_pack_family_and_availability():
    drums = load_drum_assets()
    entities = load_entity_assets()
    sound_fx = load_sound_fx_assets()
    sound_lab = load_sound_lab_assets()

    assert drums
    assert entities
    assert sound_fx
    assert sound_lab
    assert {item.pack for item in drums} == {"experimental-drum-kit-211"}
    assert {item.pack for item in entities} == {"entities"}
    assert {item.role for item in sound_fx} <= {"event_texture", "event_loop"}
    assert {item.role for item in sound_lab} <= {"one_shot", "rendered_loop", "rendered_stem"}
    assert all(item.available == item.path.is_file() for item in drums + entities + sound_fx + sound_lab)
    assert any(item.available for item in drums)
    assert any(not item.available for item in drums)


def test_iro_catalog_keeps_mathematical_family_and_articulation():
    assets = load_drum_assets()
    assert any(item.family == "sub_impact" for item in assets)
    assert any(item.articulation for item in assets)
    family_names = {item.family for item in load_entity_assets()}
    assert {
        "boundary_shard", "coordinate_slip", "interference_knot", "phase_fracture",
        "quantization_residue", "ratio_orbit", "recurrence_ghost", "spectral_bloom",
    } <= family_names


def test_iro_manifest_paths_cannot_escape_pack_root(tmp_path: Path):
    root = tmp_path / "pack"
    root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        _safe_path(root, "../outside.wav")


def test_iro_integrity_report_is_non_destructive_and_explicit_about_missing_assets():
    assets = load_iro_assets()
    report = verify_iro_assets(assets)
    assert report["total"] == len(assets)
    assert report["available"] + len(report["missing"]) == report["total"]
    assert report["ok"] is True
    assert report["verified"] > 0
