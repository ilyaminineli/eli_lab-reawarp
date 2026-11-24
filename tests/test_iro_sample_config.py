import pytest

from reawarp.config import GenerationConfig
from reawarp.samples.iro import load_drum_assets


def test_iro_sample_config_rejects_unavailable_asset_and_keeps_metadata_contract():
    asset = next(item for item in load_drum_assets() if item.role == "kick")
    assert not asset.available
    # A future checkout containing the generated WAV payload can pass the same
    # path + metadata contract, but this manifest-only snapshot cannot render it.
    with pytest.raises(ValueError):
        GenerationConfig(
            duration=5.0,
            sample_paths={"kick": str(asset.path)},
            sample_metadata={
                "kick": {
                    "provider": "IRO",
                    "pack": asset.pack,
                    "family": asset.family,
                    "articulation": asset.articulation,
                }
            },
        )


def test_sample_metadata_requires_a_matching_sample_path():
    with pytest.raises(ValueError):
        GenerationConfig(sample_metadata={"kick": {"family": "sub_impact"}})
