from __future__ import annotations

import hashlib
from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

from reawarp.composition.arrangement import (
    ArrangementPlan, arrangement_snapshot, arrangement_timeline,
    branch_arrangement, clip_score_for_render, create_arrangement,
    duplicate_clip, exchange_clip_layer, freeze_clip, move_clip, move_ending,
    move_transition, record_print, redo_arrangement_edit, reorder_clip,
    replace_clip_with_candidate, relink_transition, revert_to_generation,
    set_checklist_item, set_clip_muted, trim_clip, undo_arrangement_edit,
)
from reawarp.composition.endings import (
    EndingPlan, compile_ending_plans, ending_plans_from_score,
)
from reawarp.composition.phrases import (
    PhrasePlan, PhraseSpan, build_phrase_candidate_batch,
)
from reawarp.composition.transitions import (
    TransitionPhase, TransitionPlan, compile_transition_plans,
    transition_plans_from_score,
)
from reawarp.config import GenerationConfig
from reawarp.core.project import ReawarpProject
from reawarp.export.project_archive import export_project_archive
from reawarp.export.wav import write_wav
from reawarp.fx_automation import normalise_fx_automation
from reawarp.fx_routing import default_fx_routing
from reawarp.score import MusicalEvent, Score


def _score() -> Score:
    events = (
        MusicalEvent(
            "lead-a", "lead", Fraction(1), Fraction(2),
            kind="note", pitch=60, velocity=0.7, tags=("motif-A",),
        ),
        MusicalEvent(
            "bass-a", "bass", Fraction(0), Fraction(1),
            kind="note", pitch=36, velocity=0.8,
        ),
        MusicalEvent(
            "lead-b", "lead", Fraction(5), Fraction(2),
            kind="note", pitch=64, velocity=0.6,
        ),
    )
    score = Score(title="M33 arrangement fixture", events=events)
    plan = PhrasePlan(phrases=(
        PhraseSpan(
            "phrase-a", Fraction(0), Fraction(4), "presentation",
            roles=("lead", "bass"), motif_ids=(), event_ids=("lead-a", "bass-a"),
            parent_section_id="section-A",
        ),
        PhraseSpan(
            "phrase-b", Fraction(4), Fraction(8), "continuation",
            roles=("lead",), event_ids=("lead-b",), parent_section_id="section-B",
        ),
    ))
    return plan.attach_to_score(score)


def _with_cues(score: Score) -> Score:
    transition = TransitionPlan(
        transition_id="bridge-a-b",
        source_phrase_id="phrase-a",
        target_phrase_id="phrase-b",
        transition_type="additive",
        phases=(
            TransitionPhase("preparation", 2, 3, "Open the outgoing phrase"),
            TransitionPhase("change", 3, 4, "Commit the new state"),
            TransitionPhase("arrival", 4, 5, "Establish the target phrase"),
        ),
        changed_dimensions=("roles",),
        preserved_dimensions=("motif", "rhythm"),
        participating_roles=("lead", "texture"),
        source_state={"texture": False},
        target_state={"texture": True},
        seed_name="m33-test-transition",
        seed=19,
    )
    score = compile_transition_plans(score, (transition,))
    ending = EndingPlan(
        "ending-A", "dissolve", 8, 10, participating_roles=("texture",)
    )
    return compile_ending_plans(score, (ending,))


def _clips(score: Score):
    plan = ArrangementPlan.from_score(score)
    return {item.phrase_id: item for item in plan.clips}


def test_create_arrangement_roundtrips_exact_beats_and_contains_m30_cues():
    score = _with_cues(_score())
    arranged = create_arrangement(score)
    restored = Score.from_dict(arranged.to_dict())
    plan = ArrangementPlan.from_score(restored)

    assert [clip.phrase_id for clip in plan.clips] == ["phrase-a", "phrase-b"]
    assert [clip.start_beats for clip in plan.clips] == [Fraction(0), Fraction(4)]
    assert ArrangementPlan.from_score(arranged).revision == 0
    timeline = arrangement_timeline(restored)
    assert next(item for item in timeline if item["phrase_id"] == "phrase-a")["section_id"] == "section-A"
    assert {item["kind"] for item in timeline} == {"phrase", "transition", "ending"}
    assert any(item["item_id"] == "bridge-a-b" for item in timeline)
    assert any(item["item_id"] == "ending-A" for item in timeline)
    assert ending_plans_from_score(restored)[0].strategy == "dissolve"
    assert transition_plans_from_score(restored)[0].transition_id == "bridge-a-b"


def test_move_preserves_event_identity_rational_time_and_records_reversible_history():
    score = create_arrangement(_score())
    clip = _clips(score)["phrase-b"]
    moved = move_clip(score, clip.clip_id, Fraction(17, 2))

    event = next(item for item in moved.events if item.event_id == "lead-b")
    assert event.onset_beats == Fraction(19, 2)
    assert event.event_id == "lead-b"
    assert ArrangementPlan.from_score(moved).clips[1].start_beats == Fraction(17, 2)
    assert next(
        item for item in ArrangementPlan.from_score(moved).clips
        if item.clip_id == clip.clip_id
    ).origin == "manual"
    record = moved.metadata["m33_arrangement"]
    assert record["edit_history"][-1]["actor"] == "composer"
    assert record["edit_history"][-1]["action"] == "move_clip"
    assert record["edit_history"][-1]["source_score_fingerprint"]
    assert record["edit_history"][-1]["result_score_fingerprint"]
    assert record["audit_log"][-1]["details"]["to"] == "17/2"

    undone = undo_arrangement_edit(moved)
    assert next(item for item in undone.events if item.event_id == "lead-b").onset_beats == 5
    redone = redo_arrangement_edit(undone)
    assert next(item for item in redone.events if item.event_id == "lead-b").onset_beats == Fraction(19, 2)


def test_duplicate_gives_new_event_and_phrase_ids_with_source_lineage():
    score = create_arrangement(_score())
    source = _clips(score)["phrase-a"]
    duplicated = duplicate_clip(score, source.clip_id, Fraction(8))
    plan = ArrangementPlan.from_score(duplicated)

    assert len(plan.clips) == 3
    copy = next(item for item in plan.clips if item.parent_clip_id == source.clip_id)
    assert copy.start_beats == Fraction(8)
    assert copy.end_beats == Fraction(12)
    assert set(copy.event_ids).isdisjoint(source.event_ids)
    assert set(copy.source_event_ids) == set(source.event_ids)
    assert copy.phrase_id != source.phrase_id
    assert copy.origin == "manual"
    assert all(
        next(event for event in duplicated.events if event.event_id == event_id).onset_beats >= 8
        for event_id in copy.event_ids
    )


def test_trim_crops_notes_to_exact_beats_and_rejects_a_frozen_clip():
    score = create_arrangement(_score())
    clip = _clips(score)["phrase-a"]
    trimmed = trim_clip(score, clip.clip_id, Fraction(3, 2), Fraction(5, 2))
    event = next(item for item in trimmed.events if item.event_id == "lead-a")
    assert (event.onset_beats, event.end_beats) == (Fraction(3, 2), Fraction(5, 2))
    assert "bass-a" not in {item.event_id for item in trimmed.events}
    trimmed_phrase = next(
        item for item in PhrasePlan.from_score(trimmed).phrases
        if item.phrase_id == "phrase-a"
    )
    assert trimmed_phrase.event_ids == ("lead-a",)

    frozen = freeze_clip(score, clip.clip_id)
    with pytest.raises(ValueError, match="frozen"):
        trim_clip(frozen, clip.clip_id, 1, 3)


def test_mute_unmute_and_layer_exchange_are_non_destructive_and_reversible():
    score = create_arrangement(_score())
    clip = _clips(score)["phrase-a"]
    muted = set_clip_muted(score, clip.clip_id, True)
    assert next(item for item in muted.events if item.event_id == "lead-a").velocity == 0
    assert muted.metadata["m33_arrangement"]["clips"][0]["original_velocities"]["lead-a"] == 0.7
    unmuted = set_clip_muted(muted, clip.clip_id, False)
    assert next(item for item in unmuted.events if item.event_id == "lead-a").velocity == 0.7

    exchanged = exchange_clip_layer(score, clip.clip_id, "lead", "texture")
    event = next(item for item in exchanged.events if item.event_id == "lead-a")
    assert event.voice_id == "texture"
    current_clip = next(
        item for item in ArrangementPlan.from_score(exchanged).clips
        if item.clip_id == clip.clip_id
    )
    assert current_clip.role_map == {"lead": "texture"}
    exchanged_phrase = next(
        item for item in PhrasePlan.from_score(exchanged).phrases
        if item.phrase_id == "phrase-a"
    )
    assert exchanged_phrase.roles == ("bass", "texture")
    assert next(item for item in score.events if item.event_id == "lead-a").voice_id == "lead"


def test_candidate_replacement_keeps_m28_lineage_and_can_be_frozen():
    score = _score()
    batch = build_phrase_candidate_batch(
        score, "phrase-a", count=1, root_seed=311,
        operations=("transposition",), batch_id="m33-candidate",
    )
    candidate = batch.candidates[0]
    arranged = create_arrangement(score)
    clip = _clips(arranged)["phrase-a"]
    replaced = replace_clip_with_candidate(arranged, clip.clip_id, candidate)
    selected = next(
        item for item in ArrangementPlan.from_score(replaced).clips
        if item.clip_id == clip.clip_id
    )

    assert selected.candidate_id == candidate.candidate_id
    assert selected.origin == "candidate"
    assert selected.source_event_ids == candidate.source_event_ids
    assert set(selected.event_ids).isdisjoint(candidate.target_event_ids)
    details = replaced.metadata["m33_arrangement"]["edit_history"][-1]["details"]
    assert details["generator_version"] == candidate.generator_version
    assert details["transformation"]["operation"] == candidate.operation
    assert details["base_score_fingerprint"] == candidate.base_score_fingerprint
    frozen = freeze_clip(replaced, clip.clip_id)
    assert next(
        item for item in ArrangementPlan.from_score(frozen).clips
        if item.clip_id == clip.clip_id
    ).frozen


def test_reorder_compacts_sequence_and_undo_restores_original_order():
    score = create_arrangement(_score())
    clips = _clips(score)
    reordered = reorder_clip(score, clips["phrase-b"].clip_id, 0)
    ordered = ArrangementPlan.from_score(reordered).clips
    assert [item.phrase_id for item in ordered] == ["phrase-b", "phrase-a"]
    assert [item.start_beats for item in ordered] == [Fraction(0), Fraction(4)]
    assert reordered.metadata["m33_arrangement"]["edit_history"][-1]["action"] == "reorder_clip"
    restored = undo_arrangement_edit(reordered)
    assert [item.start_beats for item in ArrangementPlan.from_score(restored).clips] == [
        Fraction(0), Fraction(4)
    ]


def test_branch_and_revert_to_generation_are_reversible():
    score = create_arrangement(_score())
    initial = ArrangementPlan.from_score(score)
    first = initial.clips[0]
    moved = move_clip(score, first.clip_id, 1)
    branch = branch_arrangement(moved)
    branched = ArrangementPlan.from_score(branch)
    assert branched.arrangement_id != ArrangementPlan.from_score(moved).arrangement_id
    assert branched.parent_arrangement_id == ArrangementPlan.from_score(moved).arrangement_id
    assert all(not item.frozen for item in branched.clips)
    
    undone_branch = undo_arrangement_edit(branch)
    assert ArrangementPlan.from_score(undone_branch).arrangement_id == (
        ArrangementPlan.from_score(moved).arrangement_id
    )
    assert [item.start_beats for item in ArrangementPlan.from_score(undone_branch).clips] == [
        item.start_beats for item in ArrangementPlan.from_score(moved).clips
    ]

    reverted = revert_to_generation(moved)
    assert ArrangementPlan.from_score(reverted).revision == (
        ArrangementPlan.from_score(moved).revision + 1
    )
    assert [item.start_beats for item in ArrangementPlan.from_score(reverted).clips] == [
        Fraction(0), Fraction(4)
    ]
    
    undone_revert = undo_arrangement_edit(reverted)
    assert [item.start_beats for item in ArrangementPlan.from_score(undone_revert).clips] == [
        item.start_beats for item in ArrangementPlan.from_score(moved).clips
    ]
    assert {item.event_id for item in undone_revert.events} == {
        item.event_id for item in moved.events
    }


def test_m30_transition_and_ending_cues_remain_editable_in_arrangement():
    score = create_arrangement(_with_cues(_score()))
    moved_transition = move_transition(score, "bridge-a-b", Fraction(3))
    transition = transition_plans_from_score(moved_transition)[0]
    assert transition.start_beats == Fraction(3)
    assert transition.change_beat == Fraction(4)
    moved_ending = move_ending(moved_transition, "ending-A", Fraction(9))
    ending = ending_plans_from_score(moved_ending)[0]
    assert ending.start_beats == Fraction(9)
    assert ending.end_beats == Fraction(11)


def test_candidate_replacement_rejects_a_stale_source_after_trim():
    score = _score()
    candidate = build_phrase_candidate_batch(
        score, "phrase-a", count=1, root_seed=312,
        operations=("transposition",), batch_id="m33-stale-candidate",
    ).candidates[0]
    arranged = create_arrangement(score)
    clip = _clips(arranged)["phrase-a"]
    trimmed = trim_clip(arranged, clip.clip_id, Fraction(3, 2), Fraction(5, 2))
    with pytest.raises(ValueError, match="source events"):
        replace_clip_with_candidate(trimmed, clip.clip_id, candidate)


def test_reordered_m30_transition_can_be_relinked_and_ending_stays_at_track_end():
    score = create_arrangement(_with_cues(_score()))
    clips = _clips(score)
    reordered = reorder_clip(score, clips["phrase-b"].clip_id, 0)
    ending = ending_plans_from_score(reordered)[0]
    assert ending.start_beats == Fraction(8)
    assert ending.end_beats == Fraction(10)

    relinked = relink_transition(
        reordered, "bridge-a-b", "phrase-b", "phrase-a"
    )
    transition = transition_plans_from_score(relinked)[0]
    assert transition.source_phrase_id == "phrase-b"
    assert transition.target_phrase_id == "phrase-a"
    assert transition.start_beats == Fraction(3)
    assert transition.change_beat == Fraction(4)
    assert ArrangementPlan.from_score(relinked).revision == (
        ArrangementPlan.from_score(reordered).revision + 1
    )


def test_finishing_checklist_is_human_entered_and_print_record_is_hash_verified(tmp_path):
    score = create_arrangement(_score())
    clip = _clips(score)["phrase-a"]
    checked = set_checklist_item(score, "mono", True)
    checklist = ArrangementPlan.from_score(checked).checklist
    assert checklist["mono"] is True
    assert checklist["low_volume"] is False
    assert not all(checklist.values())
    assert arrangement_snapshot(checked)["all_finishing_checks_complete"] is False

    printed = tmp_path / "phrase-print.wav"
    write_wav(printed, np.zeros((48_000, 2), dtype=np.float32), 48_000)
    digest = hashlib.sha256(printed.read_bytes()).hexdigest()
    with_lineage = record_print(
        checked, clip.clip_id, path=printed, sha256=digest,
        sample_rate=48_000, frame_count=48_000,
    )
    record = with_lineage.metadata["m33_arrangement"]
    assert record["prints"][0]["sha256"] == digest
    assert record["prints"][0]["source_event_ids"] == list(clip.source_event_ids)
    with pytest.raises(ValueError, match="hash"):
        record_print(
            with_lineage, clip.clip_id, path=printed, sha256="0" * 64,
            sample_rate=48_000, frame_count=48_000,
        )


def test_clip_print_score_contains_only_selected_events_and_preserves_original():
    score = create_arrangement(_score())
    clip = _clips(score)["phrase-a"]
    printed_score = clip_score_for_render(score, clip.clip_id)
    assert {item.event_id for item in printed_score.events} == {"lead-a", "bass-a"}
    assert printed_score.metadata.get("m33_arrangement") is None
    assert {item.event_id for item in score.events} == {"lead-a", "bass-a", "lead-b"}


def test_project_export_roundtrip_includes_arrangement_snapshot_and_print_asset(tmp_path):
    config = GenerationConfig(
        duration=5, sample_rate=22_050, seed=33,
        include_melody=False, include_texture=False, include_ambience=False,
    )
    frame_count = config.frame_count
    score = create_arrangement(_score())
    score = replace(score, metadata={
        **score.metadata,
        "sample_rate": config.sample_rate,
        "duration_seconds": config.duration,
        "frame_count": frame_count,
        "render_stems": ["lead", "bass"],
    })
    # Recreate the arrangement fingerprint after adding the project render metadata.
    from reawarp.composition.arrangement import refresh_arrangement_fingerprint
    score = refresh_arrangement_fingerprint(score)
    project = ReawarpProject(
        config=config, sample_rate=config.sample_rate,
        stems={
            "lead": np.zeros((frame_count, 2), dtype=np.float32),
            "bass": np.zeros((frame_count, 2), dtype=np.float32),
        },
        score=score,
    )
    print_file = tmp_path / "print-source.wav"
    write_wav(
        print_file, np.zeros((frame_count, 2), dtype=np.float32), config.sample_rate
    )
    clip = _clips(score)["phrase-a"]
    digest = hashlib.sha256(print_file.read_bytes()).hexdigest()
    project.score = record_print(
        score, clip.clip_id, path=print_file, sha256=digest,
        sample_rate=config.sample_rate, frame_count=frame_count,
    )
    output = project.export(tmp_path / "M33_Project")
    assert (output / "arrangement_snapshot.json").is_file()
    assert (output / "arrangement_prints" / print_file.name).read_bytes() == print_file.read_bytes()
    assert (output / "score.json").is_file()
    assert (output / "manifest.json").is_file()

    restored = ReawarpProject.load(output)
    assert ArrangementPlan.from_score(restored.to_score()).arrangement_id == (
        ArrangementPlan.from_score(project.to_score()).arrangement_id
    )
    assert restored.to_score().metadata["m33_arrangement"]["prints"][0]["sha256"] == digest

    archive = export_project_archive(
        project, tmp_path / "M33_Archive",
        master_audio=project.render_master(),
        fx_routing=default_fx_routing(tuple(project.stems)),
        fx_automation=normalise_fx_automation(
            {"schema_version": 1, "lanes": {}}, tuple(project.stems)
        ),
        include_midi=True, asset_policy="reference",
    )
    assert (archive / "PACKAGE_README.md").is_file()
    package_readme = (archive / "PACKAGE_README.md").read_text(encoding="utf-8")
    assert "arrangement_snapshot.json" in package_readme
    assert "arrangement_prints/" in package_readme
    assert (archive / "arrangement_snapshot.json").is_file()
    assert (archive / "arrangement_prints" / print_file.name).is_file()
