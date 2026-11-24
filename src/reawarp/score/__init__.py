"""Musical score, exact time, tuning, automation, and MIDI interchange."""

from reawarp.score.events import AutomationLane, AutomationPoint, MusicalEvent
from reawarp.score.automation import (
    AutomationControlBus, AutomationSamples, AutomationTarget,
    AutomationTargetRegistry, DEFAULT_AUTOMATION_TARGETS,
)
from reawarp.score.render import ScheduledScoreEvent, ScoreRenderResult, ScoreRenderer
from reawarp.score.timeline import RenderTimeline
from reawarp.score.model import Score
from reawarp.score.pitch import EqualTemperamentTuning, Pitch, TuningSystem
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
    "AutomationSamples",
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
    "RenderTimeline",
    "ScheduledScoreEvent",
    "Score",
    "ScoreRenderResult",
    "ScoreRenderer",
    "TempoMap",
    "TempoPoint",
    "TuningSystem",
    "as_fraction",
]
