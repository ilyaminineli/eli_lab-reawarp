"""Musical score, exact time, tuning, automation, and MIDI interchange."""

from reawarp.score.events import AutomationLane, AutomationPoint, MusicalEvent
from reawarp.score.automation import (
    AutomationControlBus, AutomationModulation, AutomationSamples, AutomationSource,
    AutomationTarget, AutomationTargetRegistry, DEFAULT_AUTOMATION_TARGETS,
)
from reawarp.score.render import (
    ScheduledScoreEvent, ScoreRenderResult, ScoreRenderer, build_score_control_bus,
)
from reawarp.score.timeline import RenderTimeline
from reawarp.score.model import Score
from reawarp.score.orchestration_intent import AttentionSpan,CycleSpec,MutationPolicy,OrchestrationPlan,PhraseSpan,RoleRelationship,build_orchestration_plan,inspect_attention_conflicts
from reawarp.score.planner import (
    melody_to_score_events,
    percussion_to_score_events,
    score_from_planner_events,
    score_to_legacy_grid_events,
)
from reawarp.score.pitch import (
    EqualTemperamentTuning, Pitch, PitchCandidate, PitchField, Sonority, TuningSystem,
    pitch_field_from_score, tuning_from_score,
)
from reawarp.score.harmony import (
    VoiceLeadingResult, VoiceLeadingWeights, assign_voice_leading,
)
from reawarp.score.voice_leading import (
    SonorityBoundary, SonoritySequencePlan, VoiceLeadingConstraints,
    VoiceLeadingPlanConfig, VoiceLeadingPreferences, VoiceLeadingTransition,
    VoiceRoleTarget, plan_sonority_sequence,
)
from reawarp.score.bass_role import BassRoleConfig, BassRolePlan, plan_bass_role
from reawarp.score.motif import (
    MotifResolutionPlan, MotifResolutionRecord, resolve_motif_plan_to_score,
)
from reawarp.score.sonority import (
    derive_spectral_sonority,
    displace_register,
    expand_contract_sonority,
    generate_sonority,
    invert_sonority,
    replace_sonority_voice,
    resolve_sonority_frequencies,
    rotate_sonority,
    transpose_sonority,
)
from reawarp.score.time import (
    Beat,
    MeterMap,
    MeterPoint,
    TempoMap,
    TempoPoint,
    as_fraction,
)

__all__ = [
    "AttentionSpan","CycleSpec","MutationPolicy","OrchestrationPlan","PhraseSpan","RoleRelationship","build_orchestration_plan","inspect_attention_conflicts",
    "AutomationControlBus",
    "AutomationLane",
    "AutomationModulation",
    "AutomationSamples",
    "AutomationSource",
    "AutomationTarget",
    "AutomationTargetRegistry",
    "DEFAULT_AUTOMATION_TARGETS",
    "AutomationPoint",
    "Beat",
    "EqualTemperamentTuning",
    "MeterMap",
    "MeterPoint",
    "MusicalEvent",
    "Pitch",
    "PitchCandidate",
    "PitchField",
    "pitch_field_from_score",
    "tuning_from_score",
    "Sonority",
    "RenderTimeline",
    "ScheduledScoreEvent",
    "Score",
    "ScoreRenderResult",
    "ScoreRenderer",
    "build_score_control_bus",
    "TempoMap",
    "TempoPoint",
    "TuningSystem",
    "VoiceLeadingResult",
    "VoiceLeadingWeights",
    "VoiceLeadingConstraints",
    "VoiceLeadingPreferences",
    "VoiceLeadingPlanConfig",
    "VoiceLeadingTransition",
    "VoiceRoleTarget",
    "SonorityBoundary",
    "SonoritySequencePlan",
    "BassRoleConfig",
    "BassRolePlan",
    "plan_bass_role",
    "MotifResolutionPlan",
    "MotifResolutionRecord",
    "resolve_motif_plan_to_score",
    "plan_sonority_sequence",
    "assign_voice_leading",
    "generate_sonority",
    "rotate_sonority",
    "transpose_sonority",
    "invert_sonority",
    "expand_contract_sonority",
    "displace_register",
    "derive_spectral_sonority",
    "replace_sonority_voice",
    "resolve_sonority_frequencies",
    "as_fraction",
    "melody_to_score_events",
    "percussion_to_score_events",
    "score_from_planner_events",
    "score_to_legacy_grid_events",
]
