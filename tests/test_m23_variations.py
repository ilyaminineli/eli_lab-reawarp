import json
from dataclasses import replace

import numpy as np

from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject
from reawarp.library.store import SampleLibrary
from reawarp.variations import (
    VariationBatchService,
    VariationRequest,
    build_listening_set,
    matched_ab,
    project_fingerprint,
    variation_session_metadata,
)


def _base_project():
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed="m23-deterministic-fixture",
        complexity=0.22,
        include_texture=False,
        include_ambience=False,
    )
    return ReawarpEngine().generate(config)


def _session_project(base, batch):
    from reawarp.variations import clone_project

    origin = clone_project(base)
    fingerprint = project_fingerprint(origin)
    origin.metadata["m23_project_fingerprint"] = fingerprint
    candidates = {item.record.candidate_id: item for item in batch.candidates}
    for candidate in batch.candidates:
        candidate.record.notes = "The break relationship feels more coherent."
        candidate.record.selection_state = "kept"
        candidate.project.metadata["m23_candidate"] = candidate.record.to_dict()
        score = candidate.project.to_score()
        metadata = dict(score.metadata)
        metadata["m23_candidate"] = candidate.record.to_dict()
        candidate.project.score = replace(score, metadata=metadata)
    session = variation_session_metadata(
        origin, candidates,
        active_candidate_id=batch.candidates[0].record.candidate_id,
    )
    metadata = dict(origin.metadata)
    metadata["m23_project_fingerprint"] = fingerprint
    metadata["m23_variations"] = session
    return replace(
        origin,
        metadata=metadata,
        variation_candidates={
            "base": origin,
            **{candidate_id: item.project for candidate_id, item in candidates.items()},
        },
    )


def test_stem_batch_is_reproducible_and_preserves_unchanged_stems_bit_identically():
    base = _base_project()
    original_fingerprint = project_fingerprint(base)
    request = VariationRequest(mode="stems", targets=("melody",), count=2)
    service = VariationBatchService()
    first = service.generate_batch(base, request, batch_id="m23-fixed-batch")
    second = service.generate_batch(base, request, batch_id="m23-fixed-batch")

    assert first.batch_id == second.batch_id
    assert [x.record.variation_seed for x in first.candidates] == [
        x.record.variation_seed for x in second.candidates
    ]
    assert [x.record.candidate_id for x in first.candidates] == [
        x.record.candidate_id for x in second.candidates
    ]
    for left, right in zip(first.candidates, second.candidates, strict=True):
        for name, audio in left.project.stems.items():
            np.testing.assert_array_equal(audio, right.project.stems[name])
            if name != "melody":
                np.testing.assert_array_equal(audio, base.stems[name])
    assert project_fingerprint(base) == original_fingerprint
    assert all(not item.record.technical_flags for item in first.candidates)


def test_role_pair_variation_tracks_both_targets_and_parent_candidate():
    base = _base_project()
    batch = VariationBatchService().generate_batch(
        base,
        VariationRequest(mode="stems", targets=("kick", "snare"), count=1),
        parent_candidate_id="candidate-parent",
        batch_id="role-pair",
    )
    candidate = batch.candidates[0]
    assert candidate.record.targets == ("kick", "snare")
    assert candidate.record.parent_candidate_id == "candidate-parent"
    assert candidate.record.seed_lineage["recreation"]["request"]["targets"] == [
        "kick", "snare"
    ]
    for name in set(base.stems) - {"kick", "snare"}:
        np.testing.assert_array_equal(candidate.project.stems[name], base.stems[name])


def test_automation_batch_varies_m18_sources_and_modulations_without_changing_other_stems():
    from fractions import Fraction
    from reawarp.score.automation import AutomationModulation, AutomationSource

    base = _base_project()
    score = base.to_score()
    source = AutomationSource(
        source_id="m23-control-lfo", kind="lfo",
        start=Fraction(0), end=Fraction(16),
        parameters={"period_beats": 4.0, "depth": 0.22, "waveform": "triangle"},
        seed=71, minimum=0.0, maximum=1.0,
    )
    modulation = AutomationModulation(
        source_id="m23-control-lfo", destination_target_id="synth.cutoff",
        amount=0.28, polarity="unipolar", mode="add",
    )
    from dataclasses import replace
    score = replace(score, automation_sources=(source,), modulations=(modulation,))
    controlled = replace(base, score=score)
    batch = VariationBatchService().generate_batch(
        controlled,
        VariationRequest(mode="automation", targets=("melody",), count=1),
        batch_id="m23-source-only-automation",
    )
    candidate = batch.candidates[0].project
    assert candidate.to_score().automation_sources[0].parameters["depth"] != 0.22 or (
        candidate.to_score().automation_sources[0].parameters["phase_cycles"] != 0.0
    )
    assert candidate.to_score().modulations[0].amount != 0.28
    for name in set(base.stems) - {"melody"}:
        np.testing.assert_array_equal(candidate.stems[name], base.stems[name])


def test_matched_ab_is_peak_safe_and_never_mutates_source_buffers():
    reference = np.linspace(-0.12, 0.12, 4096, dtype=np.float32)
    candidate = reference * np.float32(0.5)
    before_reference, before_candidate = reference.copy(), candidate.copy()
    result = matched_ab(reference, candidate, sample_rate=22_050)

    np.testing.assert_array_equal(reference, before_reference)
    np.testing.assert_array_equal(candidate, before_candidate)
    assert result["reference"].shape == result["candidate"].shape
    assert np.max(np.abs(result["reference"])) <= 0.95 + 1e-6
    assert np.max(np.abs(result["candidate"])) <= 0.95 + 1e-6
    assert result["difference"].shape == result["reference"].shape
    assert result["reference_match"]["linear_gain"] != result["candidate_match"]["linear_gain"]


def test_listening_sets_cover_pairs_sections_transitions_and_subtraction():
    base = _base_project()
    assert "FULL MIX" in build_listening_set(base, "full_mix")
    assert build_listening_set(base, "isolated_roles")
    assert build_listening_set(base, "role_pairs")
    assert "OPENING" in build_listening_set(base, "opening")
    assert "MIDDLE" in build_listening_set(base, "middle")
    assert "ENDING" in build_listening_set(base, "ending")
    assert build_listening_set(base, "subtraction")
    assert build_listening_set(base, "transitions")


def test_candidate_notes_selection_and_ancestry_survive_project_reload_and_library_index(tmp_path):
    base = _base_project()
    batch = VariationBatchService().generate_batch(
        base, VariationRequest(mode="stems", targets=("melody",), count=1),
        batch_id="m23-persist",
    )
    exported = _session_project(base, batch).export(tmp_path / "variation-session")
    assert (exported / "listening_report.json").is_file()

    report = json.loads((exported / "listening_report.json").read_text(encoding="utf-8"))
    record = report["candidates"][0]
    assert record["selection_state"] == "kept"
    assert record["notes"].startswith("The break relationship")

    reopened = ReawarpProject.load(exported)
    assert set(reopened.variation_candidates) == {
        "base", batch.candidates[0].record.candidate_id
    }
    restored = reopened.variation_candidates[batch.candidates[0].record.candidate_id]
    assert restored.metadata["m23_candidate"]["notes"] == record["notes"]
    assert restored.metadata["m23_candidate"]["selection_state"] == "kept"

    with SampleLibrary(tmp_path / "library.sqlite3") as library:
        indexed = library.index_directory(exported)
        family_id = str(reopened.metadata["m23_variations"]["base_project_fingerprint"])[:24]
        genealogy = library.genealogy(family_id)
        candidate_rows = [item for item in genealogy if item.get("candidate_id")]
        assert any(item["candidate_id"] == record["candidate_id"] for item in candidate_rows)
        assert any(item["selection_state"] == "kept" for item in candidate_rows)
        assert indexed["projects_indexed"] >= 3
