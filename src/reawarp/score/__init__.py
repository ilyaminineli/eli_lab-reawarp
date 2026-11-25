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
from reawarp.score.planner import (
    melody_to_score_events,
    percussion_to_score_events,
    score_from_planner_events,
    score_to_legacy_grid_events,
)
from reawarp.score.pitch import (
    EqualTemperamentTuning, Pitch, PitchCandidate, PitchField, Sonority, TuningSystem,
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
    "as_fraction",
    "melody_to_score_events",
    "percussion_to_score_events",
    "score_from_planner_events",
    "score_to_legacy_grid_events",
]
