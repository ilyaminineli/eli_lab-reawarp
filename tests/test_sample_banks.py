import pytest

from reawarp.config import GenerationConfig


def _entry(path: str, asset_id: str) -> dict:
    return {
        "path": path,
        "asset_id": asset_id,
        "label": asset_id,
        "metadata": {"provider": "test"},
        "features": {"spectral_centroid_hz": 2000.0},
    }


def test_generation_config_serializes_role_sample_banks():
    config = GenerationConfig(
        sample_paths={"kick": "samples/kick.wav"},
        sample_metadata={"kick": {"provider": "test"}},
        sample_banks={"kick": (_entry("samples/kick.wav", "anchor"), _entry("samples/kick-bright.wav", "bright"))},
        drum_sample_automation="cycle",
        percussion_hybrid_architecture="feature_guided",
    )
    payload = config.to_dict()
    assert len(payload["sample_banks"]["kick"]) == 2
    assert payload["sample_banks"]["kick"][0]["asset_id"] == "anchor"
    assert payload["drum_sample_automation"] == "cycle"
    assert payload["percussion_hybrid_architecture"] == "feature_guided"


def test_generation_config_deduplicates_sample_bank_paths():
    config = GenerationConfig(sample_banks={"hat": (_entry("samples/hat.wav", "first"), _entry("samples/hat.wav", "duplicate"))})
    assert len(config.sample_banks["hat"]) == 1
    assert config.sample_banks["hat"][0]["asset_id"] == "first"


def test_generation_config_rejects_invalid_sample_bank_role_or_entry():
    with pytest.raises(ValueError):
        GenerationConfig(sample_banks={"break": (_entry("x.wav", "break"),)})
    with pytest.raises(ValueError):
        GenerationConfig(sample_banks={"kick": ({"metadata": {}},)})
