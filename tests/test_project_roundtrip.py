import numpy as np

from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject
from reawarp.score import Score


def test_exported_project_reopens_with_aligned_stems_events_and_score(tmp_path):
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m14-project-reopen",
        complexity=0.28,
        include_texture=False,
    )
    project = ReawarpEngine().generate(config)
    export_dir = project.export(tmp_path / "project", bit_depth=24)
    reopened = ReawarpProject.load(export_dir)

    assert reopened.config.to_dict() == project.config.to_dict()
    assert reopened.sample_rate == project.sample_rate
    assert reopened.frame_count == project.frame_count
    assert reopened.events == project.events
    assert reopened.metadata == project.metadata
    assert set(reopened.stems) == set(project.stems)
    for name, source in project.stems.items():
        restored = reopened.stems[name]
        assert restored.shape == source.shape
        assert np.isfinite(restored).all()
        np.testing.assert_allclose(restored, source, rtol=0.0, atol=2.0 / 8_388_607.0)

    restored_score = Score.load(export_dir / "score.json")
    assert restored_score.to_dict() == project.to_score().to_dict()


def test_project_loader_rejects_partial_exports(tmp_path):
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m14-incomplete-project",
        complexity=0.2,
        include_melody=False,
        include_texture=False,
        include_ambience=False,
    )
    project = ReawarpEngine().generate(config)
    export_dir = project.export(tmp_path / "without-stems", include_stems=False)
    try:
        ReawarpProject.load(export_dir)
    except ValueError as exc:
        assert "source stems" in str(exc)
    else:
        raise AssertionError("partial export unexpectedly loaded")
