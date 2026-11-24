import numpy as np

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.samples.iro import load_drum_assets


def test_iro_samples_render_as_role_aligned_stems_with_provenance():
    assets = load_drum_assets()
    kick = next(item for item in assets if item.available and item.role == "kick")
    snare = next(item for item in assets if item.available and item.role == "snare")
    config = GenerationConfig(
        duration=5.0,
        bpm=120.0,
        sample_rate=22_050,
        seed="iro-test",
        include_texture=False,
        sample_paths={"kick": str(kick.path), "snare": str(snare.path)},
        sample_metadata={
            "kick": {
                "provider": "IRO", "pack": kick.pack,
                "family": kick.family, "articulation": kick.articulation,
                "relative_path": kick.relative_path, "sha256": kick.sha256,
            },
            "snare": {
                "provider": "IRO", "pack": snare.pack,
                "family": snare.family, "articulation": snare.articulation,
                "relative_path": snare.relative_path, "sha256": snare.sha256,
            },
        },
    )
    project = ReawarpEngine().generate(config)
    assert "sample_kick" in project.stems
    assert "sample_snare" in project.stems
    assert project.stems["sample_kick"].shape == (config.frame_count, 2)
    assert project.stems["sample_snare"].shape == (config.frame_count, 2)
    assert np.isfinite(project.stems["sample_kick"]).all()
    assert project.metadata["sample_sources"]["kick"]["source"]["family"] == kick.family
    trigger = next(item for item in project.events if item.get("lane") == "sample_kick")
    assert trigger["sample_metadata"]["provider"] == "IRO"
    assert trigger["sample_metadata"]["relative_path"] == kick.relative_path
