from fractions import Fraction
import pytest
from reawarp.score import AttentionSpan,CycleSpec,MutationPolicy,OrchestrationPlan,PhraseSpan,RoleRelationship,Score,build_orchestration_plan,inspect_attention_conflicts

def make_plan():
 return build_orchestration_plan(phrases=(PhraseSpan("a",0,Fraction(13,2),"establishment"),PhraseSpan("b",Fraction(13,2),Fraction(41,3),"contrast")),cycles=(CycleSpec("kick","kick",Fraction(5,2),Fraction(1,3)),CycleSpec("texture","texture",Fraction(7,3),Fraction(2,5))),relationships=(RoleRelationship("r","lead","texture","call_response",response_gap_beats=Fraction(3,4)),),attention=(AttentionSpan("lead",0,6,"foreground",handoff_id="h"),AttentionSpan("texture",6,12,"foreground",handoff_id="h"),AttentionSpan("kick",12,14,"absence")),mutation_policies=(MutationPolicy("a",stable_anchors=("rhythm",),allow_motif=("register",)),),seed=42)

def test_asymmetric_phrase_and_fraction():
 p=make_plan();assert p.phrases[0].duration_beats==Fraction(13,2);assert p.phrases[1].start_beats==Fraction(13,2)

def test_independent_rational_cycles():
 a,b=make_plan().cycles
 assert a.onset_beats(until=8)==(Fraction(1,3),Fraction(17,6),Fraction(16,3),Fraction(47,6))
 assert a.length_beats!=b.length_beats and a.normalized_phase==Fraction(1,3)

def test_pair_relation():
 r=make_plan().relationships[0]
 assert r.target_onsets((0,2,4))==(Fraction(3,4),Fraction(11,4),Fraction(19,4))

def test_attention_handoff_and_absence():
 p=make_plan();assert p.foreground_at(2)==("lead",);assert p.foreground_at(8)==("texture",)
 assert p.attention_at("kick",13).reserved_silence

def test_occupancy_is_heuristic_warning():
 p=build_orchestration_plan(attention=(AttentionSpan("a",0,4,"foreground",register_low=40,register_high=70,spectral_band="mid"),AttentionSpan("b",2,5,"background",register_low=60,register_high=90,spectral_band="mid")))
 w=inspect_attention_conflicts(p);assert len(w)==1 and w[0]["heuristic_only"]

def test_score_json_roundtrip(tmp_path):
 p=make_plan();score=Score(orchestration_plan=p.to_dict());saved=score.save(tmp_path/"m20.json")
 restored=Score.load(saved);assert restored.orchestration_plan==p.to_dict();assert restored.duration_beats==14

def test_overlap_must_be_intentional():
 with pytest.raises(ValueError,match="overlap"):build_orchestration_plan(phrases=(PhraseSpan("a",0,5),PhraseSpan("b",4,8)))
 assert build_orchestration_plan(phrases=(PhraseSpan("a",0,5,overlap_group="x"),PhraseSpan("b",4,8,overlap_group="x"))).duration_beats==8

def test_mutation_default_is_one_principal_development():
 assert MutationPolicy("p").principal_developments==1


def test_cycles_report_exact_rational_alignment_points():
    plan = build_orchestration_plan(cycles=(
        CycleSpec("three", "hat", 3, 0),
        CycleSpec("two", "kick", 2, 0),
    ))
    assert plan.cycle_alignments("three", "two", end_beats=13) == (
        Fraction(0), Fraction(6), Fraction(12)
    )


def test_legacy_schema_v1_orchestration_plan_still_loads():
    legacy = make_plan().to_dict()
    legacy["schema_version"] = 1
    legacy.pop("transitions", None)
    restored = OrchestrationPlan.from_dict(legacy)
    assert restored.phrases == make_plan().phrases
    assert restored.transitions == ()


def test_event_onset_diagnostics_identify_role_collisions_only():
    from reawarp.score import MusicalEvent, inspect_event_onset_conflicts

    events = (
        MusicalEvent("kick-a", "kick", 0, Fraction(1, 4), kind="hit"),
        MusicalEvent("lead-a", "melody", 0, 1, kind="note", pitch=60),
        MusicalEvent("lead-b", "melody", 0, 1, kind="note", pitch=64),
    )
    warnings = inspect_event_onset_conflicts(events)
    assert len(warnings) == 1
    assert warnings[0]["roles"] == ["kick", "melody"]
    assert warnings[0]["heuristic_only"] is True


def test_score_generation_compiles_complete_m20_director_intent():
    from reawarp import GenerationConfig
    from reawarp.core.score_generation import build_score_generation_plan

    config = GenerationConfig(
        duration=24.0, bpm=120.0, seed="m20-director-bridge",
        structure="autechre_like", complexity=0.38,
        break_cycle_bars=2,
    )
    generated = build_score_generation_plan(config)
    plan = OrchestrationPlan.from_dict(generated.score.orchestration_plan)

    assert generated.score.metadata["perceptual_orchestration"] == plan.to_dict()
    assert len(plan.phrases) == len(generated.composition_plan.sections)
    assert len(plan.mutation_policies) == len(plan.phrases)
    assert len(plan.transitions) == len(generated.transition_plan)
    assert {cycle.role for cycle in plan.cycles} >= {"kick", "snare", "hat", "break", "melody"}
    assert len({cycle.length_beats for cycle in plan.cycles}) > 1
    assert plan.relationships
    assert plan.attention
    assert any(span.depth == "absence" for span in plan.attention)
    assert all(transition.source_phrase_id != transition.target_phrase_id
               for transition in plan.transitions)
    assert all(item["heuristic_only"] for item in
               generated.score.metadata["perceptual_attention_warnings"]
               + generated.score.metadata["perceptual_onset_warnings"])


def test_perceptual_director_bridge_is_deterministic_for_same_seed():
    from reawarp import GenerationConfig
    from reawarp.core.score_generation import build_score_generation_plan

    config = GenerationConfig(
        duration=24.0, bpm=120.0, seed="m20-listening-fixture",
        structure="uplift_drop_return", complexity=0.35,
    )
    first = build_score_generation_plan(config).score.orchestration_plan
    second = build_score_generation_plan(config).score.orchestration_plan
    assert first == second
