import numpy as np

from reawarp import GenerationConfig, ReawarpEngine


def _config():
    return GenerationConfig(
        duration=24.0,
        bpm=120.0,
        sample_rate=22_050,
        seed="m15-engine-integration",
        structure="free_jazz_episodic",
        complexity=0.36,
        include_melody=True,
        include_texture=True,
        include_ambience=True,
        rhythmic_syncopation=0.74,
        melodic_activity=0.68,
        arrangement_density=0.58,
    )


def test_engine_records_and_renders_one_shared_motif_and_section_role_plan():
    config = _config()
    engine = ReawarpEngine()
    first = engine.generate(config)
    second = engine.generate(config)

    motif_plan = first.metadata["motif_plan"]
    anchor = motif_plan["anchor"]
    motif_id = anchor["motif_id"]
    instances = motif_plan["instances"]
    assert motif_id.startswith("motif-")
    assert instances
    assert all(item["motif_id"] == motif_id for item in instances)
    assert any(item["operation"] == "call_response" for item in instances)

    role_plan = first.metadata["section_orchestration"]
    assert len(role_plan) == len(first.metadata["composition_plan"]["sections"])
    expected_roles = {
        "kick", "snare", "hat", "break", "melody", "texture", "ambience"
    }
    assert all(
        {item["role"] for item in section["roles"]} == expected_roles
        for section in role_plan
    )
    assert first.metadata["transition_gestures"]
    assert first.metadata["composition_axes"]["rhythmic_syncopation"] == 0.74

    melody_events = [
        event for event in first.events
        if event.get("lane") == "melody" and event.get("motif_id")
    ]
    assert melody_events
    assert all(event["motif_id"] == motif_id for event in melody_events)
    assert all(event.get("motif_transform") for event in melody_events)

    motif_accents = [
        event for event in first.events
        if event.get("motif_relation") in {"shadow", "response"}
    ]
    assert any(event["lane"] == "hat" for event in motif_accents)
    assert any(event["lane"] == "snare" for event in motif_accents)

    assert first.events == second.events
    assert first.metadata["motif_plan"] == second.metadata["motif_plan"]
    assert first.metadata["section_orchestration"] == second.metadata["section_orchestration"]
    assert first.metadata["transition_gestures"] == second.metadata["transition_gestures"]
    for name, audio in first.stems.items():
        assert audio.shape == (config.frame_count, 2)
        assert np.isfinite(audio).all()
        np.testing.assert_array_equal(audio, second.stems[name])


def test_melody_regeneration_does_not_change_cross_role_motif_stems():
    config = _config()
    engine = ReawarpEngine()
    base = engine.generate(config)
    variant = engine.generate_variant(config, "melody", 1, base_project=base)

    assert set(base.stems) == set(variant.stems)
    assert not np.array_equal(base.stems["melody"], variant.stems["melody"])
    for name in base.stems:
        if name != "melody":
            np.testing.assert_array_equal(base.stems[name], variant.stems[name])

    base_motif = base.metadata["motif_plan"]["anchor"]["motif_id"]
    variant_motif = variant.metadata["motif_plan"]["anchor"]["motif_id"]
    assert base_motif == variant_motif
