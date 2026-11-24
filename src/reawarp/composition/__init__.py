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
)

__all__ = [
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
    "build_motif_role_accents",
    "build_section_orchestration_plan",
    "build_transition_plan",
    "render_motif_events",
    "render_role_envelope",
    "role_activity_at_time",
    "role_intent_at_time",
    "section_for_time",
    "transform_motif",
]
