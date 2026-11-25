"""Serializable score container for events, timing, tuning, and automation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reawarp.score.events import AutomationLane, MusicalEvent
from reawarp.score.automation import AutomationModulation, AutomationSource
from reawarp.score.time import MeterMap, TempoMap, as_fraction


@dataclass(frozen=True, slots=True)
class Score:
    title: str = "Untitled Reawarp Score"
    ppq: int = 960
    tempo_map: TempoMap = field(default_factory=TempoMap)
    meter_map: MeterMap = field(default_factory=MeterMap)
    events: tuple[MusicalEvent, ...] = ()
    automation: tuple[AutomationLane, ...] = ()
    automation_sources: tuple[AutomationSource, ...] = ()
    modulations: tuple[AutomationModulation, ...] = ()
    harmonic_context: dict[str, Any] | None = None
    sonorities: tuple[dict[str, Any], ...] = ()
    tuning_id: str = "12tet"
    tuning_reference_pitch: float = 69.0
    tuning_reference_frequency_hz: float = 440.0
    tuning_divisions_per_period: int = 12
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    sonority_plan: dict[str, Any] | None = None
    bass_plan: dict[str, Any] | None = None
    orchestration_plan: dict[str, Any] | None = None
    tuning_period_ratio: float = 2.0

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("score title cannot be empty")
        if not 24 <= int(self.ppq) <= 32_767:
            raise ValueError("ppq must be between 24 and 32767")
        if self.schema_version != 1:
            raise ValueError(f"unsupported score schema version: {self.schema_version}")
        if not self.tuning_id.strip():
            raise ValueError("tuning_id cannot be empty")
        if not math.isfinite(float(self.tuning_reference_pitch)):
            raise ValueError("tuning reference pitch must be finite")
        if not math.isfinite(float(self.tuning_reference_frequency_hz)) or self.tuning_reference_frequency_hz <= 0:
            raise ValueError("tuning reference frequency must be positive")
        if isinstance(self.tuning_divisions_per_period, bool) or not isinstance(self.tuning_divisions_per_period, int) or self.tuning_divisions_per_period < 1:
            raise ValueError("tuning divisions per period must be positive")
        try:
            tuning_period_ratio = float(self.tuning_period_ratio)
        except (TypeError, ValueError) as exc:
            raise ValueError("tuning period ratio must be finite and greater than one") from exc
        if not math.isfinite(tuning_period_ratio) or tuning_period_ratio <= 1.0:
            raise ValueError("tuning period ratio must be finite and greater than one")
        object.__setattr__(self, "tuning_period_ratio", tuning_period_ratio)
        events = tuple(self.events)
        ids = [event.event_id for event in events]
        if len(ids) != len(set(ids)):
            raise ValueError("event_id values must be unique within a score")
        object.__setattr__(self, "ppq", int(self.ppq))
        object.__setattr__(self, "events", tuple(sorted(
            events, key=lambda item: (item.onset_beats, item.voice_id, item.event_id)
        )))
        automation = tuple(self.automation)
        lane_keys = [(lane.target_id, lane.scope, lane.scope_id) for lane in automation]
        if len(lane_keys) != len(set(lane_keys)):
            raise ValueError("automation target/scope combinations must be unique")
        sources = tuple(self.automation_sources)
        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("automation source IDs must be unique")
        harmonic_context = self.harmonic_context
        if harmonic_context is not None:
            if not isinstance(harmonic_context, dict):
                raise ValueError("harmonic_context must be an object or None")
            harmonic_context = json.loads(json.dumps(
                harmonic_context, ensure_ascii=False, allow_nan=False
            ))
            from reawarp.score.pitch import PitchField

            mode = str(harmonic_context.get("mode", "chromatic"))
            if mode not in PitchField.MODES:
                raise ValueError(f"unsupported harmonic context mode: {mode}")
            for key in ("pitch_collection", "allowed_intervals"):
                values = harmonic_context.get(key, [])
                if not isinstance(values, list) or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
                    raise ValueError(f"harmonic_context {key} must be a list of finite numbers")
            for key in ("stability_weights", "tension_weights"):
                values = harmonic_context.get(key, {})
                if not isinstance(values, dict) or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values.values()):
                    raise ValueError(f"harmonic_context {key} must map labels to finite numbers")
            try:
                PitchField.from_score_context(harmonic_context)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"invalid harmonic_context: {exc}") from exc
        raw_sonorities = tuple(self.sonorities)
        if any(not isinstance(item, dict) for item in raw_sonorities):
            raise ValueError("each sonority must be an object")
        sonorities = tuple(json.loads(json.dumps(item, ensure_ascii=False, allow_nan=False)) for item in raw_sonorities)
        sonority_plan = self.sonority_plan
        if sonority_plan is not None:
            if not isinstance(sonority_plan, dict):
                raise ValueError("sonority_plan must be an object or None")
            sonority_plan = json.loads(json.dumps(
                sonority_plan, ensure_ascii=False, allow_nan=False
            ))
            if sonority_plan.get("format") != "eli_lab_reawarp_sonority_sequence_plan":
                raise ValueError("unsupported sonority_plan format")
            if int(sonority_plan.get("schema_version", 1)) != 1:
                raise ValueError("unsupported sonority_plan schema version")
            planned_boundaries = sonority_plan.get("boundaries", [])
            if not isinstance(planned_boundaries, list) or any(
                not isinstance(item, dict) for item in planned_boundaries
            ):
                raise ValueError("sonority_plan boundaries must be a list of objects")
            planned_ids = [str(item.get("sonority_id", "")) for item in planned_boundaries]
            score_ids = [str(item.get("sonority_id", "")) for item in sonorities]
            if planned_ids and planned_ids != score_ids:
                raise ValueError("sonority_plan boundary IDs must match Score.sonorities order")
        orchestration_plan = self.orchestration_plan
        if orchestration_plan is not None:
            from reawarp.score.orchestration import OrchestrationPlan
            if not isinstance(orchestration_plan, dict):
                raise ValueError("orchestration_plan must be an object or None")
            try:
                payload = json.loads(json.dumps(orchestration_plan, ensure_ascii=False, allow_nan=False))
                orchestration_plan = OrchestrationPlan.from_dict(payload).to_dict()
            except (TypeError, ValueError, KeyError, OverflowError) as exc:
                raise ValueError(f"invalid orchestration_plan: {exc}") from exc
        orchestration_plan = self.orchestration_plan
        if orchestration_plan is not None:
            from reawarp.score.orchestration_intent import OrchestrationPlan
            if not isinstance(orchestration_plan, dict):
                raise ValueError("orchestration_plan must be an object or None")
            try:
                payload = json.loads(json.dumps(orchestration_plan, ensure_ascii=False, allow_nan=False))
                orchestration_plan = OrchestrationPlan.from_dict(payload).to_dict()
            except (TypeError, ValueError, KeyError, OverflowError) as exc:
                raise ValueError(f"invalid orchestration_plan: {exc}") from exc
        bass_plan = self.bass_plan
        if bass_plan is not None:
            if not isinstance(bass_plan, dict):
                raise ValueError("bass_plan must be an object or None")
            bass_plan = json.loads(json.dumps(
                bass_plan, ensure_ascii=False, allow_nan=False
            ))
            if bass_plan.get("format") != "eli_lab_reawarp_bass_role_plan":
                raise ValueError("unsupported bass_plan format")
            if int(bass_plan.get("schema_version", 1)) != 1:
                raise ValueError("unsupported bass_plan schema version")
            bass_config = bass_plan.get("config")
            bass_boundaries = bass_plan.get("boundaries")
            if not isinstance(bass_config, dict) or not isinstance(
                bass_boundaries, list
            ) or any(not isinstance(item, dict) for item in bass_boundaries):
                raise ValueError("bass_plan requires a config object and boundary objects")
            boundary_ids = [
                str(item.get("sonority_id", "")) for item in bass_boundaries
            ]
            if (
                not boundary_ids
                or any(not item for item in boundary_ids)
                or len(boundary_ids) != len(set(boundary_ids))
            ):
                raise ValueError("bass_plan boundary IDs must be unique and non-empty")
            bass_ids = bass_plan.get("event_ids", [])
            if (
                not isinstance(bass_ids, list)
                or any(not isinstance(value, str) or not value for value in bass_ids)
                or len(bass_ids) != len(set(bass_ids))
            ):
                raise ValueError("bass_plan event_ids must be unique non-empty strings")
            score_event_ids = {event.event_id for event in events}
            missing_bass_ids = set(bass_ids) - score_event_ids
            if missing_bass_ids:
                raise ValueError(
                    "bass_plan references missing Score event(s): "
                    + ", ".join(sorted(missing_bass_ids))
                )
            expected_voice = str(bass_config.get("voice_id", "bass"))
            bass_events = [event for event in events if event.event_id in set(bass_ids)]
            if any(event.voice_id != expected_voice or event.kind != "note"
                   for event in bass_events):
                raise ValueError("bass_plan event IDs must reference its note voice")
            kick_ids = bass_plan.get("kick_event_ids", [])
            if (
                not isinstance(kick_ids, list)
                or any(not isinstance(value, str) or not value for value in kick_ids)
                or len(kick_ids) != len(set(kick_ids))
            ):
                raise ValueError("bass_plan kick_event_ids must be unique non-empty strings")
            event_by_id = {event.event_id: event for event in events}
            for kick_id in kick_ids:
                kick = event_by_id.get(kick_id)
                if kick is None or kick.kind != "hit":
                    raise ValueError("bass_plan kick provenance must reference Score hit events")
                if not (
                    kick.voice_id.casefold() == "kick"
                    or str(kick.parameters.get("source_kind", "")).casefold() == "kick"
                    or "kick" in {tag.casefold() for tag in kick.tags}
                ):
                    raise ValueError("bass_plan kick provenance references a non-kick event")
        sonority_ids = [str(item.get("sonority_id", "")) for item in sonorities]
        if any(not value for value in sonority_ids) or len(sonority_ids) != len(set(sonority_ids)):
            raise ValueError("sonorities require unique non-empty sonority_id values")
        for item in sonorities:
            from reawarp.score.time import as_fraction
            start = as_fraction(item.get("onset_beats", 0))
            duration = as_fraction(item.get("duration_beats", 1))
            if start < 0 or duration <= 0:
                raise ValueError("sonority onset must be non-negative and duration positive")
            pitches = item.get("pitches", [])
            if not isinstance(pitches, list) or not pitches or any(
                not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in pitches
            ):
                raise ValueError("sonority pitches must be a non-empty list of finite pitch coordinates")
            bass_pitch = item.get("bass_pitch")
            if bass_pitch is not None and (
                not isinstance(bass_pitch, (int, float))
                or not math.isfinite(float(bass_pitch))
            ):
                raise ValueError("sonority bass_pitch must be finite or None")
            tension = item.get("tension", 0.0)
            if not isinstance(tension, (int, float)) or not math.isfinite(float(tension)):
                raise ValueError("sonority tension must be finite")
            transform = item.get("transform", "original")
            if not isinstance(transform, str) or not transform.strip():
                raise ValueError("sonority transform must be a non-empty string")
            source_id = item.get("source_sonority_id")
            if source_id is not None and (
                not isinstance(source_id, str) or not source_id.strip()
            ):
                raise ValueError("sonority source_sonority_id must be a non-empty string")
            parameters = item.get("transform_parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("sonority transform_parameters must be an object")
            as_fraction(item.get("onset_beats", 0))
            as_fraction(item.get("duration_beats", 1))
        modulations = tuple(self.modulations)
        modulation_keys = [
            (
                item.source_id, item.destination_target_id, item.retrigger,
                item.scope, item.scope_id,
            )
            for item in modulations
        ]
        if len(modulation_keys) != len(set(modulation_keys)):
            raise ValueError("automation modulation relationships must be unique")
        unknown_sources = {item.source_id for item in modulations} - set(source_ids)
        if unknown_sources:
            raise ValueError(
                "automation modulation references unknown source(s): "
                + ", ".join(sorted(unknown_sources))
            )
        object.__setattr__(self, "automation", automation)
        object.__setattr__(self, "automation_sources", sources)
        object.__setattr__(self, "modulations", modulations)
        object.__setattr__(self, "harmonic_context", harmonic_context)
        object.__setattr__(self, "sonorities", sonorities)
        object.__setattr__(self, "sonority_plan", sonority_plan)
        object.__setattr__(self, "bass_plan", bass_plan)
        object.__setattr__(self, "orchestration_plan", orchestration_plan)
        object.__setattr__(self, "metadata", json.loads(json.dumps(
            self.metadata, ensure_ascii=False, allow_nan=False
        )))

    @property
    def duration_beats(self):
        event_end = max((event.end_beats for event in self.events), default=0)
        automation_end = max(
            (
                lane.points[-1].at if lane.time_basis == "beats"
                else 0
                for lane in self.automation
            ),
            default=0,
        )
        source_end = max((source.end for source in self.automation_sources), default=0)
        sonority_end = max(
            (
                as_fraction(item.get("onset_beats", 0))
                + as_fraction(item.get("duration_beats", 1))
                for item in self.sonorities
            ),
            default=0,
        )
        orchestration_end = Fraction(0)
        if self.orchestration_plan is not None:
            from reawarp.score.orchestration import OrchestrationPlan
            orchestration_end = OrchestrationPlan.from_dict(self.orchestration_plan).duration_beats
        return max(event_end, automation_end, source_end, sonority_end, orchestration_end)

    def beat_to_seconds(self, beat) -> float:
        return self.tempo_map.beat_to_seconds(beat)

    def seconds_to_beat(self, seconds: float):
        return self.tempo_map.seconds_to_beat(seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "eli_lab_reawarp_score",
            "schema_version": self.schema_version,
            "title": self.title,
            "ppq": self.ppq,
            "tempo_map": self.tempo_map.to_dict(),
            "meter_map": self.meter_map.to_dict(),
            "tuning": {
                "id": self.tuning_id,
                "reference_pitch": self.tuning_reference_pitch,
                "reference_frequency_hz": self.tuning_reference_frequency_hz,
                "divisions_per_period": self.tuning_divisions_per_period,
                "period_ratio": self.tuning_period_ratio,
            },
            "events": [event.to_dict() for event in self.events],
            "automation": [lane.to_dict() for lane in self.automation],
            "automation_sources": [source.to_dict() for source in self.automation_sources],
            "modulations": [item.to_dict() for item in self.modulations],
            "harmonic_context": self.harmonic_context,
            "sonorities": list(self.sonorities),
            "sonority_plan": self.sonority_plan,
            "bass_plan": self.bass_plan,
            "orchestration_plan": self.orchestration_plan,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Score":
        if data.get("format") not in (None, "eli_lab_reawarp_score"):
            raise ValueError("file is not a Reawarp score")
        tuning = data.get("tuning", {})
        return cls(
            title=str(data.get("title", "Untitled Reawarp Score")),
            ppq=int(data.get("ppq", 960)),
            tempo_map=TempoMap.from_dict(data.get("tempo_map", [
                {"at_beats": "0", "bpm": 120.0, "interpolation_to_next": "step"}
            ])),
            meter_map=MeterMap.from_dict(data.get("meter_map", [
                {"at_beats": "0", "numerator": 4, "denominator": 4}
            ])),
            events=tuple(MusicalEvent.from_dict(item) for item in data.get("events", [])),
            automation=tuple(
                AutomationLane.from_dict(item) for item in data.get("automation", [])
            ),
            automation_sources=tuple(
                AutomationSource.from_dict(item)
                for item in data.get("automation_sources", [])
            ),
            modulations=tuple(
                AutomationModulation.from_dict(item)
                for item in data.get("modulations", [])
            ),
            harmonic_context=data.get("harmonic_context"),
            sonorities=tuple(data.get("sonorities", ())),
            sonority_plan=data.get("sonority_plan"),
            bass_plan=data.get("bass_plan"),
            orchestration_plan=data.get("orchestration_plan"),
            tuning_id=str(tuning.get("id", "12tet")),
            tuning_reference_pitch=float(tuning.get("reference_pitch", 69.0)),
            tuning_reference_frequency_hz=float(
                tuning.get("reference_frequency_hz", 440.0)
            ),
            tuning_divisions_per_period=int(tuning.get("divisions_per_period", 12)),
            tuning_period_ratio=float(tuning.get("period_ratio", 2.0)),
            metadata=dict(data.get("metadata", {})),
            schema_version=int(data.get("schema_version", 1)),
        )

    def save(self, path: str | Path) -> Path:
        output = Path(path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(output)
        return output

    @classmethod
    def load(cls, path: str | Path) -> "Score":
        source = Path(path).expanduser()
        data = json.loads(source.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_project(cls, project, *, title: str | None = None) -> "Score":
        from reawarp.score.conversion import project_to_score

        return project_to_score(project, title=title)

    def export_midi(
            self,
            path: str | Path,
            *,
            ticks_per_beat: int | None = None,
            tempo_ramp_resolution: str = "1/4",
    ) -> Path:
        from reawarp.score.midi import score_to_midi

        return score_to_midi(
            self,
            path,
            ticks_per_beat=ticks_per_beat,
            tempo_ramp_resolution=tempo_ramp_resolution,
        )

    @classmethod
    def from_midi(cls, path: str | Path) -> "Score":
        from reawarp.score.midi import score_from_midi

        return score_from_midi(path)
