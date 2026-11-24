from reawarp.config import GenerationConfig
from reawarp.samples.iro import load_drum_assets


def test_iro_sample_config_preserves_index_metadata_without_claiming_audio_is_available():
    asset = next(item for item in load_drum_assets() if item.role == "kick")
    assert not asset.available
    config = GenerationConfig(
        duration=5.0,
        sample_paths={"kick": str(asset.path)},
        sample_metadata={
            "kick": {
                "provider": "IRO",
                "pack": asset.pack,
                "family": asset.family,
                "articulation": asset.articulation,
                "relative_path": asset.relative_path,
                "sha256": asset.sha256,
                "available": asset.available,
            }
        },
    )
    payload = config.to_dict()
    assert payload["sample_paths"]["kick"] == str(asset.path)
    assert payload["sample_metadata"]["kick"]["available"] is False
    assert payload["sample_metadata"]["kick"]["sha256"] == asset.sha256


def test_sample_metadata_requires_a_matching_sample_path():
    import pytest

    with pytest.raises(ValueError):
        GenerationConfig(sample_metadata={"kick": {"family": "sub_impact"}})
