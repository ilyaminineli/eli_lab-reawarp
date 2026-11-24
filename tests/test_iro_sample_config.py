from pathlib import Path

import pytest

from reawarp.config import GenerationConfig
from reawarp.samples.iro import load_drum_assets


def test_iro_sample_configuration_retains_provenance():
    asset = next(item for item in load_drum_assets() if item.role == "kick")
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed=211,
        sample_paths={"kick": str(asset.path)},
        sample_metadata={
            "kick": {
                "provider": "IRO",
                "pack": asset.pack,
                "relative_path": asset.relative_path,
                "family": asset.family,
                "articulation": asset.articulation,
                "sha256": asset.sha256,
                "release_seed": 211,
            }
        },
    )
    data = config.to_dict()
    assert data["sample_paths"]["kick"] == str(asset.path)
    assert data["sample_metadata"]["kick"]["family"] == asset.family
    assert data["sample_metadata"]["kick"]["release_seed"] == 211


def test_sample_metadata_requires_a_matching_sample_path():
    with pytest.raises(ValueError):
        GenerationConfig(sample_metadata={"kick": {"family": "sub_impact"}})
