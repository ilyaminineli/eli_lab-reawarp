from __future__ import annotations

from dataclasses import replace

import pytest

from reawarp import GenerationConfig
from reawarp.composition.brief import (
    AnchorSpec,
    CompositionBrief,
    MaterialIdentity,
    PitchWorld,
    SourceAssetReference,
    SourceFamily,
    resolve_composition_brief,
    source_families_from_config,
)


def _config(path: str = "/tmp/kick-source.wav", digest: str = "a" * 64):
    return GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m27-brief",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        sample_paths={"kick": path},
        sample_metadata={"kick": {"asset_id": "kick-001", "sha256": digest}},
        sample_banks={
            "kick": ({
                "path": path,
                "asset_id": "kick-001",
                "sha256": digest,
                "metadata": {},
                "features": {},
            },)
        },
    )


def test_brief_schema_round_trips_material_anchor_pitch_world_and_source_identity():
    config = _config()
    families = source_families_from_config(config)
    source_id = families[0].assets[0].reference_id
    brief = CompositionBrief(
        brief_id="three-material-study",
        artistic_question="Can a stable pulse survive repeated interruption?",
        listening_mode="close listening",
        materials=(
            MaterialIdentity(
                "A", "Pulse", function="anchor", role="kick",
                source_asset_ids=(source_id,),
            ),
            MaterialIdentity("B", "Metal response", function="response"),
        ),
        anchor=AnchorSpec(
            kind="pulse", material_id="A", description="Keep the pulse recognisable."
        ),
        pitch_world=PitchWorld(scale="whole_tone", root=3),
        source_families=families,
    )

    restored = CompositionBrief.from_dict(brief.to_dict())

    assert restored.to_dict() == brief.to_dict()
    assert restored.fingerprint == brief.fingerprint
    assert restored.has_user_content is True
    resolved = resolve_composition_brief(restored, config)
    assert resolved.brief_fingerprint == brief.fingerprint
    assert resolved.source_families[0].assets[0].sha256 == "a" * 64


def test_unknown_schema_fields_and_unknown_material_references_are_rejected():
    brief = CompositionBrief(brief_id="strict-schema")
    malformed = brief.to_dict()
    malformed["future_field"] = "silently ignore me"
    with pytest.raises(ValueError, match="unknown CompositionBrief fields"):
        CompositionBrief.from_dict(malformed)

    with pytest.raises(ValueError, match="unknown material"):
        CompositionBrief(
            brief_id="bad-anchor",
            materials=(MaterialIdentity("A", "Pulse"),),
            anchor=AnchorSpec(kind="motif", material_id="missing"),
        )


def test_source_resolution_rejects_missing_or_changed_asset_without_substitution():
    original = _config()
    brief = CompositionBrief(
        brief_id="source-locked",
        source_families=source_families_from_config(original),
    )
    changed = _config(path="/tmp/replacement-kick.wav", digest="b" * 64)

    with pytest.raises(ValueError, match="missing or changed; no substitutions"):
        resolve_composition_brief(brief, changed)


def test_material_source_references_must_belong_to_declared_family():
    with pytest.raises(ValueError, match="unknown source IDs"):
        CompositionBrief(
            brief_id="invalid-material-source",
            materials=(
                MaterialIdentity("A", "Unresolved", source_asset_ids=("asset:missing",)),
            ),
        )


def test_legacy_brief_is_a_read_only_compatibility_view():
    brief = CompositionBrief.legacy()
    assert brief.authorship == "legacy"
    assert brief.structured is False
    assert brief.has_user_content is False



def test_default_pitch_world_does_not_overwrite_generation_config_but_explicit_default_can():
    from reawarp.composition.brief import PitchWorld, resolve_and_explore

    config = replace(
        _config(), melody_scale="whole_tone", melody_root=4
    )
    implicit = CompositionBrief(
        brief_id="pitch-inherited",
        artistic_question="The existing generator pitch world remains authoritative.",
    )
    inherited, _, _ = resolve_and_explore(implicit, config)
    assert inherited.melody_scale == "whole_tone"
    assert inherited.melody_root == 4

    explicit = CompositionBrief(
        brief_id="pitch-explicit-reset",
        artistic_question="Return to chromatic zero-root.",
        pitch_world=PitchWorld(scale="chromatic", root=0),
        pitch_world_explicit=True,
    )
    reset, _, _ = resolve_and_explore(explicit, config)
    assert reset.melody_scale == "chromatic"
    assert reset.melody_root == 0


def test_pitch_world_exports_through_public_composition_api():
    from reawarp.composition import CompositionBrief as PublicCompositionBrief
    from reawarp.composition import resolve_and_explore as public_resolve

    assert PublicCompositionBrief is CompositionBrief
    assert callable(public_resolve)
