"""eli_lab-reawarp / 再変形 — mathematical IDM audio generation."""

from reawarp.config import GenerationConfig
from reawarp.core.engine import ReawarpEngine
from reawarp.core.project import ReawarpProject
from reawarp.score import (
    AutomationControlBus,
    AutomationLane,
    AutomationSamples,
    AutomationTarget,
    AutomationTargetRegistry,
    DEFAULT_AUTOMATION_TARGETS,
    AutomationPoint,
    EqualTemperamentTuning,
    MusicalEvent,
    Pitch,
    RenderTimeline,
    ScheduledScoreEvent,
    ScoreRenderResult,
    ScoreRenderer,
    Score,
    TempoMap,
    TempoPoint,
)

__all__ = [
    "AutomationControlBus",
    "AutomationLane",
    "AutomationSamples",
    "AutomationTarget",
    "AutomationTargetRegistry",
    "DEFAULT_AUTOMATION_TARGETS",
    "AutomationPoint",
    "EqualTemperamentTuning",
    "GenerationConfig",
    "MusicalEvent",
    "Pitch",
    "ReawarpEngine",
    "ReawarpProject",
    "RenderTimeline",
    "ScheduledScoreEvent",
    "Score",
    "ScoreRenderResult",
    "ScoreRenderer",
    "TempoMap",
    "TempoPoint",
]
__version__ = "0.8.0"
