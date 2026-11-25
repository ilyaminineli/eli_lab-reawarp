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
