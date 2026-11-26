"""Deterministic offline rendering of the universal musical score."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, replace
from fractions import Fraction
from time import perf_counter
from typing import Any, Callable, Mapping

import numpy as np

from reawarp.score.automation import (
    AutomationControlBus,
    AutomationTargetRegistry,
    DEFAULT_AUTOMATION_TARGETS,
)
from reawarp.score.attention import apply_attention_gesture_to_event
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.timeline import RenderTimeline

SCORE_RENDERER_VERSION = "1.1.0"


def build_score_control_bus(
    score: Score,
    sample_rate: int,
    *,
    automation_registry: AutomationTargetRegistry | None = None,
    allow_custom_automation_targets: bool = True,
) -> AutomationControlBus:
    """Build the canonical Score control bus for render voices or downstream FX routing."""
    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
        raise ValueError("sample_rate must be a positive integer")
    rate = int(sample_rate)
    timeline = RenderTimeline(rate, score.tempo_map, score.meter_map)
    source_sample_rate = int(score.metadata.get("sample_rate", rate) or rate)
    if source_sample_rate <= 0:
        raise ValueError("score metadata sample_rate must be positive")

    role_origins: dict[str, int] = {}
    section_origins: dict[str, int] = {}
    event_rows: list[tuple[MusicalEvent, int, str | None]] = []
    for event in score.events:
        onset_frame = timeline.beat_to_frame(event.onset_beats)
        section_value = event.parameters.get(
            "section_id", event.parameters.get("section_name")
        )
        section_id = None if section_value is None else str(section_value)
        role_origins[event.voice_id] = min(
            onset_frame, role_origins.get(event.voice_id, onset_frame)
        )
        if section_id is not None:
            section_origins[section_id] = min(
                onset_frame, section_origins.get(section_id, onset_frame)
            )
        event_rows.append((event, onset_frame, section_id))
    event_contexts = {
        event.event_id: {
            "role_id": event.voice_id,
            "section_id": section_id,
            "event_onset_frame": onset_frame,
            "role_onset_frame": role_origins[event.voice_id],
            "section_onset_frame": (
                section_origins[section_id] if section_id is not None else onset_frame
            ),
        }
        for event, onset_frame, section_id in event_rows
    }
    return AutomationControlBus(
        score.automation,
        timeline,
        source_sample_rate=source_sample_rate,
        registry=automation_registry or DEFAULT_AUTOMATION_TARGETS,
        allow_custom_targets=allow_custom_automation_targets,
        sources=score.automation_sources,
        modulations=score.modulations,
        event_contexts=event_contexts,
    )


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
    performance: dict[str, Any] = field(default_factory=dict)

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


def _stable_event_probability_seed(event: MusicalEvent) -> int:
    """Use the parent hit's identity for generated sample/break trigger events."""
    if event.seed is not None:
        return int(event.seed)
    event_id = event.event_id
    for prefix in ("sample-trigger-", "sample-break-"):
        if event_id.startswith(prefix):
            event_id = event_id[len(prefix) :]
            break
    digest = hashlib.blake2b(event_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little", signed=False)


def _stable_control_value(event: MusicalEvent, domain: str) -> float:
    """Return a domain-separated, event-stable value in [0, 1)."""
    digest = hashlib.blake2b(
        f"{event.event_id}:{domain}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "little", signed=False) / float(1 << 64)


def _apply_score_performance_controls(
    event: MusicalEvent,
    start_frame: int,
    frame_count: int,
    controls: AutomationControlBus,
    timeline: RenderTimeline,
) -> MusicalEvent | None:
    """Resolve composition controls once per event without mutating the source Score.

    Density is stable event thinning; syncopation advances eligible percussion by one
    sixteenth without crossing a bar; articulation changes note gate length. The
    transformed event is a render-performance view and repeated renders stay idempotent.
    """
    event_id = event.event_id
    event_gain = event
    if "role.density" in controls.target_ids:
        density, active = controls.value_and_active_for_context(
            "role.density", start_frame, event_id=event_id, default_value=1.0
        )
        if active and _stable_control_value(event, "m18-density") >= float(
            np.clip(density, 0.0, 1.0)
        ):
            return None

    if "role.syncopation" in controls.target_ids and event.voice_id in {
        "snare",
        "hat",
        "break",
    }:
        syncopation, active = controls.value_and_active_for_context(
            "role.syncopation", start_frame, event_id=event_id, default_value=0.0
        )
        step_value = event.parameters.get("step")
        if step_value is None:
            raw_step = event.onset_beats * 4
            step_value = int(raw_step) if raw_step.denominator == 1 else None
        try:
            step = int(step_value) if step_value is not None else None
        except (TypeError, ValueError):
            step = None
        motif_relation = str(event.parameters.get("motif_relation") or "")
        eligible = (
            step is not None
            and step % 2 == 0
            and not (event.voice_id == "snare" and step % 16 in {4, 12})
            and motif_relation not in {"shadow", "response"}
        )
        if (
            active
            and eligible
            and _stable_control_value(event, "m18-syncopation")
            < 0.5 * float(np.clip(syncopation, 0.0, 1.0))
        ):
            shifted_onset = event.onset_beats + Fraction(1, 4)
            if (
                timeline.bar_and_beat(shifted_onset)[0]
                == timeline.bar_and_beat(event.onset_beats)[0]
            ):
                shifted_start, shifted_end = timeline.beat_span_to_frames(
                    shifted_onset, event.duration_beats
                )
                if shifted_start < frame_count and shifted_end <= frame_count:
                    parameters = dict(event.parameters)
                    parameters["step"] = step + 1
                    parameters["m18_syncopation_shift_beats"] = "1/4"
                    event_gain = replace(
                        event, onset_beats=shifted_onset, parameters=parameters
                    )

    if "role.articulation" in controls.target_ids and event_gain.kind == "note":
        articulation, active = controls.value_and_active_for_context(
            "role.articulation",
            start_frame,
            event_id=event_id,
            default_value=0.0,
        )
        if active:
            index = int(np.clip(round(articulation), 0, 4))
            gate_ratios = (1.0, 0.55, 0.78, 1.0, 1.15)
            articulation_names = (
                event_gain.articulation,
                "staccato",
                "detached",
                "tenuto",
                "legato",
            )
            base_gate = Fraction(
                str(
                    event_gain.parameters.get(
                        "gate_duration_beats", event_gain.duration_beats
                    )
                )
            )
            gate = max(
                Fraction(1, 64),
                min(
                    event_gain.duration_beats,
                    base_gate * Fraction(str(gate_ratios[index])),
                ),
            )
            parameters = dict(event_gain.parameters)
            parameters["gate_duration_beats"] = str(gate)
            parameters["m18_articulation_index"] = index
            event_gain = replace(
                event_gain,
                articulation=articulation_names[index],
                parameters=parameters,
            )
    return event_gain


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
        cancel_event: Any | None = None,
    ) -> ScoreRenderResult:
        if not isinstance(score, Score):
            raise TypeError("score must be a reawarp Score")
        if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
            raise ValueError("sample_rate must be a positive integer")
        sample_rate = int(sample_rate)
        renderer_started = perf_counter()
        control_started = perf_counter()
        controls = build_score_control_bus(
            score,
            sample_rate,
            automation_registry=automation_registry,
            allow_custom_automation_targets=allow_custom_automation_targets,
        )
        control_bus_seconds = perf_counter() - control_started
        timeline = controls.timeline
        source_sample_rate = int(
            score.metadata.get("sample_rate", sample_rate) or sample_rate
        )

        if frame_count is None:
            inferred = 0
            source_duration = score.metadata.get("duration_seconds")
            source_frames = int(score.metadata.get("frame_count", 0) or 0)
            if source_duration is not None:
                if (
                    not math.isfinite(float(source_duration))
                    or float(source_duration) < 0.0
                ):
                    raise ValueError(
                        "score duration_seconds metadata must be finite and non-negative"
                    )
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
            for source in score.automation_sources:
                automation_end = max(automation_end, timeline.beat_to_frame(source.end))
            frame_count = max(inferred, event_end, automation_end, 1)
        if isinstance(frame_count, bool) or int(frame_count) <= 0:
            raise ValueError("frame_count must be a positive integer")
        frame_count = int(frame_count)

        scheduling_started = perf_counter()
        schedule: list[ScheduledScoreEvent] = []
        for source_event in score.events:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("score render cancelled")
            source_start = timeline.beat_to_frame(source_event.onset_beats)
            if source_start >= frame_count:
                continue
            event = _apply_score_performance_controls(
                source_event, source_start, frame_count, controls, timeline
            )
            if event is None:
                continue
            event = apply_attention_gesture_to_event(
                event, score.metadata.get("m29_attention_gestures", ())
            )
            if event is None:
                continue
            start, end = timeline.beat_span_to_frames(
                event.onset_beats, event.duration_beats
            )
            if start >= frame_count:
                continue
            end = min(frame_count, max(start + 1, end))
            bar_number, beat_in_bar = timeline.bar_and_beat(event.onset_beats)
            schedule.append(
                ScheduledScoreEvent(
                    event=event,
                    start_frame=start,
                    end_frame=end,
                    bar_number=bar_number,
                    beat_in_bar=beat_in_bar,
                )
            )

        scheduling_seconds = perf_counter() - scheduling_started
        renderers = dict(voice_renderers or {})
        stems: dict[str, np.ndarray] = {}
        voice_callback_seconds = 0.0
        sample_trigger_callback_seconds = 0.0
        event_accumulation_seconds = 0.0
        callback_seconds_by_voice: dict[str, float] = {}
        callback_counts_by_voice: dict[str, int] = {}
        callback_seconds_by_kind: dict[str, float] = {}
        callback_counts_by_kind: dict[str, int] = {}
        rendered_event_count = 0
        rendered_sample_trigger_count = 0
        for scheduled in schedule:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("score render cancelled")
            event = scheduled.event
            if event.kind in {"control", "marker"} or event.velocity <= 0.0:
                continue
            event_gain = float(event.velocity)
            if "event.velocity_scale" in controls.target_ids:
                event_gain *= controls.value_for_context(
                    "event.velocity_scale",
                    scheduled.start_frame,
                    event_id=event.event_id,
                    default_value=1.0,
                )
            if "role.activity" in controls.target_ids:
                event_gain *= controls.value_for_context(
                    "role.activity",
                    scheduled.start_frame,
                    event_id=event.event_id,
                    default_value=1.0,
                )
            if "event.probability" in controls.target_ids:
                probability = float(
                    np.clip(
                        controls.value_for_context(
                            "event.probability",
                            scheduled.start_frame,
                            event_id=event.event_id,
                            default_value=1.0,
                        ),
                        0.0,
                        1.0,
                    )
                )
                threshold = int(probability * (1 << 64))
                if _stable_event_probability_seed(event) >= threshold:
                    continue
            if event_gain <= 0.0:
                continue
            renderer = renderers.get(event.voice_id, renderers.get(event.kind))
            if renderer is None:
                renderer = _default_voice_renderer
            callback_started = perf_counter()
            rendered = np.asarray(
                renderer(scheduled, sample_rate, controls), dtype=np.float32
            )
            callback_elapsed = perf_counter() - callback_started
            voice_id = str(event.voice_id)
            event_kind = str(event.kind)
            voice_callback_seconds += callback_elapsed
            callback_seconds_by_voice[voice_id] = (
                callback_seconds_by_voice.get(voice_id, 0.0) + callback_elapsed
            )
            callback_counts_by_voice[voice_id] = (
                callback_counts_by_voice.get(voice_id, 0) + 1
            )
            callback_seconds_by_kind[event_kind] = (
                callback_seconds_by_kind.get(event_kind, 0.0) + callback_elapsed
            )
            callback_counts_by_kind[event_kind] = (
                callback_counts_by_kind.get(event_kind, 0) + 1
            )
            rendered_event_count += 1
            if event_kind == "trigger":
                sample_trigger_callback_seconds += callback_elapsed
                rendered_sample_trigger_count += 1
            accumulation_started = perf_counter()
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
                raise ValueError(
                    f"voice renderer for {event.voice_id!r} returned non-finite audio"
                )
            if rendered.ndim == 1:
                pan = float(event.parameters.get("pan", 0.0))
                if "spatial.pan" in controls.target_ids:
                    pan = controls.value_for_context(
                        "spatial.pan",
                        scheduled.start_frame,
                        event_id=event.event_id,
                        default_value=pan,
                    )
                pan = pan * float(event.parameters.get("m29_pan_factor", 1.0)) + float(
                    event.parameters.get("m29_pan_offset", 0.0)
                )
                if not math.isfinite(pan):
                    raise ValueError(
                        f"event {event.event_id!r} has a non-finite pan value"
                    )
                pan = float(np.clip(pan, -1.0, 1.0))
                angle = (pan + 1.0) * (math.pi / 4.0)
                rendered_stereo = np.column_stack(
                    (
                        rendered * math.cos(angle),
                        rendered * math.sin(angle),
                    )
                ).astype(np.float32, copy=False)
            else:
                rendered_stereo = rendered.copy()
                gesture_width = float(
                    event.parameters.get("m29_spatial_width_factor", 1.0)
                )
                if "spatial.width" in controls.target_ids or gesture_width != 1.0:
                    width = (
                        controls.value_for_context(
                            "spatial.width",
                            scheduled.start_frame,
                            event_id=event.event_id,
                            default_value=1.0,
                        )
                        if "spatial.width" in controls.target_ids
                        else 1.0
                    )
                    width = float(np.clip(width * gesture_width, 0.0, 2.0))
                    mid = 0.5 * (rendered_stereo[:, 0] + rendered_stereo[:, 1])
                    side = 0.5 * (rendered_stereo[:, 0] - rendered_stereo[:, 1]) * width
                    rendered_stereo = np.column_stack((mid + side, mid - side)).astype(
                        np.float32, copy=False
                    )

            target = stems.setdefault(
                event.voice_id, np.zeros((frame_count, 2), dtype=np.float32)
            )
            start = scheduled.start_frame
            target[start : scheduled.end_frame] += rendered_stereo * event_gain
            event_accumulation_seconds += perf_counter() - accumulation_started

        performance = {
            "control_bus_seconds": control_bus_seconds,
            "event_scheduling_seconds": scheduling_seconds,
            "voice_callback_seconds": voice_callback_seconds,
            "sample_trigger_callback_seconds": sample_trigger_callback_seconds,
            "event_accumulation_seconds": event_accumulation_seconds,
            "scheduled_event_count": len(schedule),
            "rendered_event_count": rendered_event_count,
            "rendered_sample_trigger_count": rendered_sample_trigger_count,
            "callback_seconds_by_voice": callback_seconds_by_voice,
            "callback_counts_by_voice": callback_counts_by_voice,
            "callback_seconds_by_kind": callback_seconds_by_kind,
            "callback_counts_by_kind": callback_counts_by_kind,
            "score_renderer_wall_seconds": perf_counter() - renderer_started,
        }
        return ScoreRenderResult(
            stems=stems,
            schedule=tuple(schedule),
            controls=controls,
            timeline=timeline,
            sample_rate=sample_rate,
            frame_count=frame_count,
            score=score,
            performance=performance,
        )
