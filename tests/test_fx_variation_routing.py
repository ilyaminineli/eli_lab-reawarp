from __future__ import annotations

import pytest

from reawarp.fx_routing import (
    build_fx_variation_routings,
    role_aware_fx_routing,
)


def test_fx_variation_routings_are_seeded_by_project_context_and_role():
    stems = ("kick", "snare", "hats", "melody", "noise_texture", "ambience")
    base = role_aware_fx_routing(stems)
    context = {
        "seed": 211,
        "bpm": 137,
        "duration": 45,
        "complexity": 0.62,
        "structure": "episodic",
        "synth_palette": "subtractive",
    }
    first = build_fx_variation_routings(
        stems, 48_000, base, project_context=context,
        variation_seed=19, count=4, bpm=137,
    )
    repeated = build_fx_variation_routings(
        stems, 48_000, base, project_context=context,
        variation_seed=19, count=4, bpm=137,
    )
    changed_context = build_fx_variation_routings(
        stems, 48_000, base,
        project_context={**context, "complexity": 0.78},
        variation_seed=19, count=4, bpm=137,
    )

    assert [item["candidate_id"] for item in first] == [
        "fx_01_space_depth", "fx_02_metallic_motion",
        "fx_03_digital_fracture", "fx_04_rhythmic_echo",
    ]
    assert [item["routing"] for item in first] == [
        item["routing"] for item in repeated
    ]
    assert [item["seed"] for item in first] != [
        item["seed"] for item in changed_context
    ]
    assert first[0]["routing"] != first[1]["routing"]
    assert first[1]["routing"] != first[2]["routing"]
    assert first[2]["routing"] != first[3]["routing"]

    for candidate in first:
        route = candidate["routing"]
        assert route["schema_version"] == 3
        assert route["stems"]["kick"]["insert"]["kind"] == "bypass"
        assert route["stems"]["kick"]["sends"] == {"space": 0.0, "echo": 0.0}
        assert set(route["buses"]) == {"space", "echo"}


def test_fx_variation_batch_validates_count_and_seed():
    with pytest.raises(ValueError, match="count"):
        build_fx_variation_routings(("kick",), 48_000, count=0)
    with pytest.raises(ValueError, match="variation_seed"):
        build_fx_variation_routings(("kick",), 48_000, variation_seed="random")
