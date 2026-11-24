"""eli_lab-reawarp / 再変形 — mathematical IDM audio generation."""

from reawarp.config import GenerationConfig
from reawarp.core.engine import ReawarpEngine
from reawarp.core.project import ReawarpProject
from reawarp.fx_automation import (
    attach_fx_automation_to_score,
    fx_automation_registry,
    fx_automation_to_score_lanes,
    score_lanes_to_fx_automation,
    score_to_fx_automation,
)
from reawarp.synthesis.score_voices import build_production_voice_renderers
from reawarp.score import (
    AutomationControlBus,
    AutomationLane,
    AutomationSamples,
    AutomationTarget,
    AutomationTargetRegistry,
    DEFAULT_AUTOMATION_TARGETS,
    AutomationPoint,
    EqualTemperamentTuning,
    MeterMap,
    MeterPoint,
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
    "MeterMap",
    "MeterPoint",
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
    "attach_fx_automation_to_score",
    "build_production_voice_renderers",
    "fx_automation_registry",
    "fx_automation_to_score_lanes",
    "score_lanes_to_fx_automation",
    "score_to_fx_automation",
]
__version__ = "0.8.0"
