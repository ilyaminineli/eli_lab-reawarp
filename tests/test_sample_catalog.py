from pathlib import Path

from reawarp.samples.catalog import (
    classify_sample_role,
    default_sample_for_role,
    discover_bundled_samples,
    sample_library_counts,
)


def test_bundled_sample_catalog_discovers_each_drum_role():
    counts = sample_library_counts()
    assert counts["kick"] >= 1
    assert counts["snare"] >= 1
    assert counts["hat"] >= 1

    for role in ("kick", "snare", "hat"):
        items = discover_bundled_samples(role=role)
        assert items
        assert all(item.role == role and item.path.is_file() for item in items)
        preferred = default_sample_for_role(role)
        assert preferred is not None
        assert preferred in items


def test_catalog_classifies_breaks_separately_from_drum_voices():
    assert classify_sample_role(Path("samples/Breaks/org_2/example.wav")) == "break"
    assert classify_sample_role(Path("samples/kick.wav")) == "kick"
    assert classify_sample_role(Path("samples/dwb_snare_07.wav")) == "snare"
    assert classify_sample_role(Path("samples/evn_04_hihat_02.wav")) == "hat"


def test_custom_catalog_root_is_supported(tmp_path: Path):
    (tmp_path / "kick").mkdir()
    sample = tmp_path / "kick" / "custom_kick.wav"
    sample.write_bytes(b"fixture")
    items = discover_bundled_samples(tmp_path, role="kick")
    assert len(items) == 1
    assert items[0].path == sample.resolve()
