"""Composition-level formal, motif and orchestration planning."""

from reawarp.composition.director import (
    STRUCTURES,
    CompositionPlan,
    SectionPlan,
    build_composition_plan,
    section_for_time,
)
from reawarp.composition.motifs import (
    Motif,
    MotifInstance,
    MotifNote,
    MotifPlan,
    build_motif_plan,
    build_motif_role_accents,
    render_motif_events,
    transform_motif,
)
from reawarp.composition.phrases import (
    PhraseBoundary, PhraseSpan, PhrasePlan, MotifIdentity, MotifFamily,
    MotifTransformation, PhraseCandidate, PhraseCandidateBatch,
    build_phrase_candidate_batch, freeze_phrase_candidate,
    restore_phrase_base, branch_phrase_candidate, continue_evolving,
    phrase_context_events,
)
from reawarp.composition.perceptual import build_perceptual_orchestration_plan
from reawarp.composition.transitions import (
    TransitionPhase, TransitionPlan, compile_transition_plans,
    transition_marker_events, transition_plans_from_score,
    TransitionActuation, transition_actuation_at,
)
from reawarp.composition.endings import (
    ENDING_STRATEGIES, EndingDirector, EndingPlan, compile_ending_plans,
    ending_marker_events, ending_plans_from_score,
)
from reawarp.composition.section_memory import (
    DEFAULT_SECTION_MEMORY_CAPACITY, EXPECTATION_KINDS,
    MAX_SECTION_MEMORY_CAPACITY, MemoryExpectation, ReturnOpportunity,
    SectionMemory, SectionState, TrajectorySummary,
    attach_section_memory, section_memory_from_score,
)
from reawarp.composition.orchestration import (
    ROLE_NAMES,
    RoleIntent,
    SectionOrchestrationPlan,
    TransitionGesture,
    build_section_orchestration_plan,
    build_transition_plan,
    render_role_envelope,
    role_activity_at_time,
    role_intent_at_time,
    shape_role_events,
)

__all__ = [
    "BRIEF_SCHEMA_VERSION", "CompositionBrief", "MutationContract",
    "MaterialIdentity", "SourceAssetReference", "SourceFamily", "AnchorSpec",
    "PitchWorld", "ContrastTarget", "EndingIntent", "TempoFormPolicy",
    "ResolvedCompositionIntent", "BoundedExplorationResult",
    "source_families_from_config", "resolve_composition_brief",
    "quick_mutation_contracts", "bounded_explore_generation_config",
    "resolve_and_explore",
    "PhraseBoundary",
    "PhraseSpan",
    "PhrasePlan",
    "MotifIdentity",
    "MotifFamily",
    "MotifTransformation",
    "PhraseCandidate",
    "PhraseCandidateBatch",
    "build_phrase_candidate_batch",
    "freeze_phrase_candidate",
    "restore_phrase_base",
    "branch_phrase_candidate",
    "continue_evolving",
    "phrase_context_events",
    "TransitionPhase",
    "TransitionPlan",
    "compile_transition_plans",
    "transition_marker_events",
    "transition_plans_from_score",
    "DEFAULT_SECTION_MEMORY_CAPACITY",
    "EXPECTATION_KINDS",
    "MAX_SECTION_MEMORY_CAPACITY",
    "MemoryExpectation",
    "ReturnOpportunity",
    "SectionMemory",
    "SectionState",
    "TrajectorySummary",
    "attach_section_memory",
    "section_memory_from_score",
    "STRUCTURES",
    "CompositionPlan",
    "SectionPlan",
    "Motif",
    "MotifInstance",
    "MotifNote",
    "MotifPlan",
    "ROLE_NAMES",
    "RoleIntent",
    "SectionOrchestrationPlan",
    "TransitionGesture",
    "build_composition_plan",
    "build_motif_plan",
    "build_perceptual_orchestration_plan",
    "build_motif_role_accents",
    "build_section_orchestration_plan",
    "build_transition_plan",
    "render_motif_events",
    "render_role_envelope",
    "role_activity_at_time",
    "role_intent_at_time",
    "shape_role_events",
    "section_for_time",
    "transform_motif",
    "ENDING_STRATEGIES", "EndingDirector", "EndingPlan", "compile_ending_plans",
    "ending_marker_events", "ending_plans_from_score",
    "TransitionActuation", "transition_actuation_at",]


# M27 exports are lazy to avoid a cycle: config imports submodules from this
# package while brief.py itself references GenerationConfig.
_M27_EXPORTS = {
    "BRIEF_SCHEMA_VERSION",
    "CompositionBrief",
    "MutationContract",
    "MaterialIdentity",
    "SourceAssetReference",
    "SourceFamily",
    "AnchorSpec",
    "PitchWorld",
    "ContrastTarget",
    "EndingIntent",
    "TempoFormPolicy",
    "ResolvedCompositionIntent",
    "BoundedExplorationResult",
    "source_families_from_config",
    "resolve_composition_brief",
    "quick_mutation_contracts",
    "bounded_explore_generation_config",
    "resolve_and_explore",
}


def __getattr__(name: str):
    if name not in _M27_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(".brief", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | _M27_EXPORTS)
