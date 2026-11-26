from __future__ import annotations

from reawarp import GenerationConfig
from reawarp.composition.brief import (
    CompositionBrief,
    MutationContract,
    bounded_explore_generation_config,
    quick_mutation_contracts,
)


def _config():
    return GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m27-deterministic-seed",
        include_melody=False,
        include_texture=False,
        include_ambience=False,
        sample_paths={"kick": "/tmp/kick.wav"},
        sample_metadata={"kick": {"asset_id": "kick-a"}},
        sample_banks={"kick": ({"path": "/tmp/kick.wav", "asset_id": "kick-a"},)},
    )


def test_bounded_exploration_changes_only_declared_fields_and_is_reproducible():
    config = _config()
    fields = ("arrangement_density", "rhythmic_syncopation", "break_density")
    brief = CompositionBrief(
        brief_id="bounded-study",
        mutation_contracts=quick_mutation_contracts(fields),
    )

    first = bounded_explore_generation_config(config, brief)
    second = bounded_explore_generation_config(config, brief)

    assert first.config == second.config
    assert first.field_changes == second.field_changes
    assert first.seed_lineage == second.seed_lineage
    assert set(first.field_changes) == set(fields)
    assert set(first.applied_contract_ids) == {
        item.contract_id for item in brief.mutation_contracts
    }
    assert first.config.seed == config.seed
    assert first.config.sample_rate == config.sample_rate
    assert first.config.sample_paths == config.sample_paths
    assert first.config.sample_metadata == config.sample_metadata
    assert first.config.sample_banks == config.sample_banks
    assert first.config.bpm == config.bpm
    assert first.config.duration == config.duration
    assert first.config.structure == config.structure
    assert first.config.composition_flow == config.composition_flow
    for field_name in fields:
        assert first.field_changes[field_name]["before"] == getattr(config, field_name)
        assert first.field_changes[field_name]["after"] == getattr(first.config, field_name)


def test_tempo_duration_and_form_are_mutable_only_with_explicit_policy():
    config = _config()
    contracts = quick_mutation_contracts(("bpm", "duration", "structure"))
    brief = CompositionBrief(
        brief_id="tempo-form-study",
        mutation_contracts=contracts,
    )
    try:
        bounded_explore_generation_config(config, brief)
    except ValueError as exc:
        assert "preserved by the CompositionBrief" in str(exc)
    else:
        raise AssertionError("tempo/form changes should require an explicit policy")

    from reawarp.composition.brief import TempoFormPolicy

    authorised = CompositionBrief(
        brief_id="tempo-form-authorised",
        mutation_contracts=contracts,
        tempo_form_policy=TempoFormPolicy(
            bpm_mode="explore",
            duration_mode="explore",
            form_mode="explore",
            bpm_bounds=(90.0, 100.0),
            duration_bounds=(10.0, 12.0),
        ),
    )
    result = bounded_explore_generation_config(config, authorised)
    assert 90.0 <= result.config.bpm <= 100.0
    assert 10.0 <= result.config.duration <= 12.0
    assert result.config.seed == config.seed


def test_mutation_outside_declared_permissions_is_not_applied():
    config = _config()
    brief = CompositionBrief(
        brief_id="one-field-only",
        mutation_contracts=quick_mutation_contracts(("arrangement_density",)),
    )
    result = bounded_explore_generation_config(config, brief)
    assert result.config.rhythmic_syncopation == config.rhythmic_syncopation
    assert result.config.tonal_brightness == config.tonal_brightness


def test_cross_contract_invariant_conflict_is_rejected_before_sampling():
    config = _config()
    contracts = (
        MutationContract(
            contract_id="protect-density",
            target_id="composition",
            scale="section",
            invariants=("arrangement_density",),
        ),
        *quick_mutation_contracts(("arrangement_density",)),
    )
    brief = CompositionBrief(
        brief_id="conflicting-contracts",
        mutation_contracts=contracts,
    )
    try:
        bounded_explore_generation_config(config, brief)
    except ValueError as exc:
        assert "declared invariant" in str(exc)
    else:
        raise AssertionError("a protected field was allowed to mutate")


def test_generation_config_adapter_rejects_unsupported_cadence_and_stop_condition():
    config = _config()
    contract = MutationContract(
        contract_id="per-phrase-density",
        target_id="composition",
        scale="section",
        mutable_fields=("arrangement_density",),
        cadence="per_phrase",
        decision_boundaries=("section_start",),
    )
    brief = CompositionBrief(brief_id="unsupported-cadence", mutation_contracts=(contract,))
    try:
        bounded_explore_generation_config(config, brief)
    except ValueError as exc:
        assert "unsupported GenerationConfig cadence" in str(exc)
    else:
        raise AssertionError("unsupported cadence should not silently run once per generation")
