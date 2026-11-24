from reawarp.samples.iro import load_drum_assets


def test_iro_catalog_keeps_source_lineage_but_does_not_offer_missing_generated_wavs():
    drum_assets = load_drum_assets()
    assert len(drum_assets) == 96
    assert all(not item.available for item in drum_assets)
    assert all(item.sha256 for item in drum_assets)
    assert any(item.source_feature_index is not None for item in drum_assets)
    assert any(item.family == "sub_impact" for item in drum_assets)
    assert any(item.articulation for item in drum_assets)
    assert all((item.metadata or {}).get("source_asset_path") for item in drum_assets)
    assert all((item.metadata or {}).get("source_asset_sha256") for item in drum_assets)
