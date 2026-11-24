"""Deterministic offline rendering of the universal musical score."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Mapping

import numpy as np

from reawarp.score.automation import (
    AutomationControlBus,
    AutomationTargetRegistry,
    DEFAULT_AUTOMATION_TARGETS,
)
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.timeline import RenderTimeline

SCORE_RENDERER_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ScheduledScoreEvent:
    """A score event resolved onto the renderer's absolute frame clock."""

    event: MusicalEvent
    start_frame: int
    end_frame: int
    bar_number: int
    beat_in_bar: Fraction

    @property
    def duration_frames(self) -> int:
        return max(0, self.end_frame - self.start_frame)

    @property
    def event_id(self) -> str:
        return self.event.event_id


@dataclass(slots=True)
class ScoreRenderResult:
    """Dry, per-voice score render plus the resolved schedule and control bus."""

    stems: dict[str, np.ndarray]
    schedule: tuple[ScheduledScoreEvent, ...]
    controls: AutomationControlBus
    timeline: RenderTimeline
    sample_rate: int
    frame_count: int
    score: Score | None = None

    def render_master(self) -> np.ndarray:
        if not self.stems:
            return np.zeros((self.frame_count, 2), dtype=np.float32)
        master = np.zeros((self.frame_count, 2), dtype=np.float32)
        for audio in self.stems.values():
            master += audio
        return master


ScoreVoiceRenderer = Callable[
    [ScheduledScoreEvent, int, AutomationControlBus],
    np.ndarray,
]


def _stable_event_seed(event: MusicalEvent) -> int:
    if event.seed is not None:
        return int(event.seed)
    digest = hashlib.blake2b(event.event_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little", signed=False)


def _default_voice_renderer(
    scheduled: ScheduledScoreEvent,
    sample_rate: int,
    controls: AutomationControlBus,
) -> np.ndarray:
    """Small deterministic reference voice; applications can inject richer voices."""
    del controls
    event = scheduled.event
    count = max(1, scheduled.duration_frames)
    time = np.arange(count, dtype=np.float64) / float(sample_rate)
    parameters = event.parameters

    if event.kind == "note":
        frequency = event.frequency_hz
        if frequency is None and event.pitch is not None:
            frequency = 440.0 * (2.0 ** ((float(event.pitch) - 69.0) / 12.0))
        if frequency is None or not math.isfinite(float(frequency)) or frequency <= 0:
            raise ValueError(f"note {event.event_id!r} has no usable frequency")
        phase = time * float(frequency)
        waveform = str(parameters.get("waveform", "sine")).casefold()
        if waveform == "triangle":
            signal = 2.0 * np.abs(2.0 * (phase - np.floor(phase + 0.5))) - 1.0
        elif waveform == "saw":
            signal = 2.0 * (phase - np.floor(phase + 0.5))
        elif waveform == "square":
            signal = np.where(np.sin(2.0 * np.pi * phase) >= 0.0, 1.0, -1.0)
        else:
            signal = np.sin(2.0 * np.pi * phase)
        attack = min(count, max(1, int(round(sample_rate * 0.006))))
        release = min(count, max(1, int(round(sample_rate * 0.025))))
        envelope = np.ones(count, dtype=np.float64)
        envelope[:attack] *= np.linspace(0.0, 1.0, attack, endpoint=True)
        envelope[-release:] *= np.linspace(1.0, 0.0, release, endpoint=True)
        return (0.22 * signal * envelope).astype(np.float32)

    rng = np.random.default_rng(_stable_event_seed(event))
    frequency = float(parameters.get("frequency_hz", 110.0))
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise ValueError(f"event {event.event_id!r} has an invalid reference frequency")
    tone = np.sin(2.0 * np.pi * frequency * time)
    noise = rng.standard_normal(count)
    decay_seconds = max(0.008, float(parameters.get("decay_seconds", 0.075)))
    envelope = np.exp(-time / decay_seconds)
    noise_mix = float(np.clip(parameters.get("noise_mix", 0.32), 0.0, 1.0))
    signal = ((1.0 - noise_mix) * tone + noise_mix * noise) * envelope * 0.24
    return np.asarray(signal, dtype=np.float32)


class ScoreRenderer:
    """Render Score.events; event placement and controls share one timeline.

    A custom voice renderer receives a ScheduledScoreEvent and the same
    AutomationControlBus used by downstream synthesis and FX callbacks. It
    returns mono or stereo float audio; event velocity, mono panning, frame
    placement and finite-sample validation are handled by this class.
    """

    VERSION = SCORE_RENDERER_VERSION

    def render(
        self,
        score: Score,
        sample_rate: int,
        *,
        frame_count: int | None = None,
        voice_renderers: Mapping[str, ScoreVoiceRenderer] | None = None,
        automation_registry: AutomationTargetRegistry | None = None,
        allow_custom_automation_targets: bool = True,
    ) -> ScoreRenderResult:
        if not isinstance(score, Score):
            raise TypeError("score must be a reawarp Score")
        if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
            raise ValueError("sample_rate must be a positive integer")
        sample_rate = int(sample_rate)
        timeline = RenderTimeline(sample_rate, score.tempo_map, score.meter_map)
        source_sample_rate = int(score.metadata.get("sample_rate", sample_rate) or sample_rate)
        if source_sample_rate <= 0:
            raise ValueError("score metadata sample_rate must be positive")
        controls = AutomationControlBus(
            score.automation,
            timeline,
            source_sample_rate=source_sample_rate,
            registry=automation_registry or DEFAULT_AUTOMATION_TARGETS,
            allow_custom_targets=allow_custom_automation_targets,
        )

        if frame_count is None:
            inferred = 0
            source_duration = score.metadata.get("duration_seconds")
            source_frames = int(score.metadata.get("frame_count", 0) or 0)
            if source_duration is not None:
                if not math.isfinite(float(source_duration)) or float(source_duration) < 0.0:
                    raise ValueError("score duration_seconds metadata must be finite and non-negative")
                inferred = timeline.seconds_to_frame(float(source_duration))
            elif source_frames > 0:
                inferred = timeline.seconds_to_frame(
                    source_frames / float(source_sample_rate)
                )
            event_end = max(
                (timeline.beat_to_frame(event.end_beats) for event in score.events),
                default=0,
            )
            automation_end = 0
            for lane in score.automation:
                last = lane.points[-1].at
                if lane.time_basis == "beats":
                    end = timeline.beat_to_frame(last)
                elif lane.time_basis == "seconds":
                    end = timeline.seconds_to_frame(float(last))
                else:
                    end = timeline.seconds_to_frame(float(last) / source_sample_rate)
                automation_end = max(automation_end, end)
            frame_count = max(inferred, event_end, automation_end, 1)
        if isinstance(frame_count, bool) or int(frame_count) <= 0:
            raise ValueError("frame_count must be a positive integer")
        frame_count = int(frame_count)

        schedule: list[ScheduledScoreEvent] = []
        for event in score.events:
            start, end = timeline.beat_span_to_frames(
                event.onset_beats, event.duration_beats
            )
            if start >= frame_count:
                continue
            end = min(frame_count, max(start + 1, end))
            bar_number, beat_in_bar = timeline.bar_and_beat(event.onset_beats)
            schedule.append(ScheduledScoreEvent(
                event=event,
                start_frame=start,
                end_frame=end,
                bar_number=bar_number,
                beat_in_bar=beat_in_bar,
            ))

        renderers = dict(voice_renderers or {})
        stems: dict[str, np.ndarray] = {}
        for scheduled in schedule:
            event = scheduled.event
            if event.kind in {"control", "marker"} or event.velocity <= 0.0:
                continue
            renderer = renderers.get(event.voice_id, renderers.get(event.kind))
            if renderer is None:
                renderer = _default_voice_renderer
            rendered = np.asarray(renderer(scheduled, sample_rate, controls), dtype=np.float32)
            if rendered.ndim == 2 and rendered.shape[1] == 1:
                rendered = rendered[:, 0]
            if rendered.ndim not in (1, 2) or (
                rendered.ndim == 2 and rendered.shape[1] != 2
            ):
                raise ValueError(
                    f"voice renderer for {event.voice_id!r} must return mono or stereo audio"
                )
            if len(rendered) != scheduled.duration_frames:
                raise ValueError(
                    f"voice renderer for {event.voice_id!r} must return exactly "
                    f"{scheduled.duration_frames} frames; received {len(rendered)}"
                )
            if not np.isfinite(rendered).all():
                raise ValueError(f"voice renderer for {event.voice_id!r} returned non-finite audio")
            if rendered.ndim == 1:
                pan = float(event.parameters.get("pan", 0.0))
                if not math.isfinite(pan):
                    raise ValueError(f"event {event.event_id!r} has a non-finite pan value")
                pan = float(np.clip(pan, -1.0, 1.0))
                angle = (pan + 1.0) * (math.pi / 4.0)
                rendered_stereo = np.column_stack((
                    rendered * math.cos(angle),
                    rendered * math.sin(angle),
                )).astype(np.float32, copy=False)
            else:
                rendered_stereo = rendered

            target = stems.setdefault(
                event.voice_id, np.zeros((frame_count, 2), dtype=np.float32)
            )
            start = scheduled.start_frame
            target[start:scheduled.end_frame] += (
                rendered_stereo * float(event.velocity)
            )

        return ScoreRenderResult(
            stems=stems,
            schedule=tuple(schedule),
            controls=controls,
            timeline=timeline,
            sample_rate=sample_rate,
            frame_count=frame_count,
            score=score,
        )
