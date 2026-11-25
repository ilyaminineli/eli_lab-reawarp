"""Deterministic variation batches and critical-listening helpers."""
from __future__ import annotations
import copy, hashlib, json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence
import numpy as np
from reawarp.core.project import ReawarpProject
from reawarp.core.random_streams import derive_seed
from reawarp.fx_routing import match_audition_level, measure_signal
from reawarp.score.model import Score

_STATES = {"unreviewed", "kept", "discarded", "promoted", "branched"}
_SCORE_PATCH_FIELDS = {"automation", "automation_sources", "modulations"}

def clone_project(project: ReawarpProject, *, readonly: bool = False) -> ReawarpProject:
    stems = {}
    for name, audio in project.stems.items():
        value = np.asarray(audio, dtype=np.float32).copy()
        if readonly:
            value.setflags(write=False)
        stems[name] = value
    return ReawarpProject(
        config=project.config, sample_rate=project.sample_rate, stems=stems,
        events=copy.deepcopy(project.events), metadata=copy.deepcopy(project.metadata),
        score=project.score,
    )

def project_fingerprint(project: ReawarpProject) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(project.config.to_dict(), sort_keys=True, default=str).encode())
    digest.update(str((project.sample_rate, project.frame_count)).encode())
    for name in sorted(project.stems):
        audio = np.ascontiguousarray(project.stems[name], dtype=np.float32)
        digest.update(name.encode())
        digest.update(str(audio.shape).encode())
        digest.update(memoryview(audio).cast("B"))
    score = project.to_score().to_dict()
    metadata = dict(score.get("metadata", {}))
    metadata.pop("performance", None)
    metadata.pop("render_provenance", None)
    score["metadata"] = metadata
    digest.update(json.dumps(score, sort_keys=True, ensure_ascii=False, default=str).encode())
    return digest.hexdigest()

@dataclass(frozen=True, slots=True)
class VariationRequest:
    mode: str = "stems"
    targets: tuple[str, ...] = ()
    count: int = 4
    config_overrides: dict[str, Any] = field(default_factory=dict)
    score_patch: dict[str, Any] = field(default_factory=dict)
    label: str = "Variation batch"

    def __post_init__(self):
        if self.mode not in {"stems", "full_project", "config", "sample_bank", "automation", "sound_object"}:
            raise ValueError("unsupported variation mode")
        targets = tuple(dict.fromkeys(str(x).strip() for x in self.targets if str(x).strip()))
        if isinstance(self.count, bool) or not 1 <= int(self.count) <= 16:
            raise ValueError("variation batch count must be between 1 and 16")
        if not isinstance(self.config_overrides, dict) or not isinstance(self.score_patch, dict):
            raise ValueError("variation overrides and Score patch must be objects")
        unknown = set(self.score_patch) - _SCORE_PATCH_FIELDS
        if unknown:
            raise ValueError("unsupported Score patch fields: " + ", ".join(sorted(unknown)))
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "count", int(self.count))
        object.__setattr__(self, "config_overrides", copy.deepcopy(self.config_overrides))
        object.__setattr__(self, "score_patch", copy.deepcopy(self.score_patch))
        object.__setattr__(self, "label", str(self.label).strip() or "Variation batch")

    def to_dict(self):
        return {"mode": self.mode, "targets": list(self.targets), "count": self.count,
                "config_overrides": copy.deepcopy(self.config_overrides),
                "score_patch": copy.deepcopy(self.score_patch), "label": self.label}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]):
        return cls(
            mode=str(value.get("mode", "stems")), targets=tuple(value.get("targets", ())),
            count=int(value.get("count", 4)),
            config_overrides=dict(value.get("config_overrides", {})),
            score_patch=dict(value.get("score_patch", {})), label=str(value.get("label", "Variation batch")),
        )

@dataclass(slots=True)
class VariationCandidateRecord:
    candidate_id: str
    batch_id: str
    index: int
    label: str
    mode: str
    targets: tuple[str, ...]
    base_project_fingerprint: str
    parent_candidate_id: str | None
    root_seed: int | str
    variation_seed: int
    seed_lineage: dict[str, Any]
    changed_parameters: dict[str, Any]
    selection_state: str = "unreviewed"
    notes: str = ""
    technical_flags: list[str] = field(default_factory=list)
    technical_metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.candidate_id or not self.batch_id or self.index < 1 or self.variation_seed < 1:
            raise ValueError("candidate identity, index and seed must be valid")
        if self.selection_state not in _STATES:
            raise ValueError("invalid candidate selection state")
        self.targets = tuple(self.targets)
        self.seed_lineage = copy.deepcopy(dict(self.seed_lineage))
        self.changed_parameters = copy.deepcopy(dict(self.changed_parameters))
        self.technical_flags = [str(x) for x in self.technical_flags]
        self.technical_metrics = copy.deepcopy(dict(self.technical_metrics))
        self.notes = str(self.notes)

    def to_dict(self):
        result = asdict(self)
        result["targets"] = list(self.targets)
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]):
        return cls(
            candidate_id=str(value["candidate_id"]), batch_id=str(value["batch_id"]),
            index=int(value["index"]), label=str(value.get("label", "Candidate")),
            mode=str(value.get("mode", "stems")), targets=tuple(value.get("targets", ())),
            base_project_fingerprint=str(value["base_project_fingerprint"]),
            parent_candidate_id=value.get("parent_candidate_id"), root_seed=value.get("root_seed", 0),
            variation_seed=int(value.get("variation_seed", 1)),
            seed_lineage=dict(value.get("seed_lineage", {})),
            changed_parameters=dict(value.get("changed_parameters", {})),
            selection_state=str(value.get("selection_state", "unreviewed")),
            notes=str(value.get("notes", "")), technical_flags=list(value.get("technical_flags", [])),
            technical_metrics=dict(value.get("technical_metrics", {})),
        )

@dataclass(slots=True)
class VariationCandidate:
    record: VariationCandidateRecord
    project: ReawarpProject

@dataclass(slots=True)
class VariationBatch:
    batch_id: str
    base_project_fingerprint: str
    request: VariationRequest
    candidates: list[VariationCandidate]

    def to_dict(self):
        return {"batch_id": self.batch_id, "base_project_fingerprint": self.base_project_fingerprint,
                "request": self.request.to_dict(),
                "candidates": [x.record.to_dict() for x in self.candidates]}

def _signal_summary(audio, sample_rate):
    return measure_signal(np.asarray(audio, dtype=np.float32), sample_rate=sample_rate)

def _candidate_seed(root_seed, batch_id, index):
    return 1_000_000_000 + int(derive_seed(root_seed, f"m23:{batch_id}:candidate:{index}") % 1_000_000_000)

def _attach_candidate(project, record):
    metadata = copy.deepcopy(project.metadata)
    metadata["m23_candidate"] = record.to_dict()
    metadata["variation"] = {"stem": "+".join(record.targets) if record.targets else None, "index": record.index}
    project.metadata = metadata
    score = project.to_score()
    score_metadata = dict(score.metadata)
    score_metadata["m23_candidate"] = record.to_dict()
    project.score = replace(score, metadata=score_metadata)

def _event_voice_stem(voice_id):
    return {"hat": "hats", "break": "synthetic_break"}.get(voice_id, voice_id)

class VariationBatchService:
    """Generate deterministic candidate projects against an immutable source."""

    def __init__(self, engine=None):
        if engine is None:
            from reawarp.core.engine import ReawarpEngine
            engine = ReawarpEngine()
        self.engine = engine

    @staticmethod
    def _check_cancel(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("variation batch cancelled")

    def generate_batch(
        self, base_project, request, *, parent_candidate_id=None, batch_id=None,
        cancel_event=None, sound_object_renderer: Callable[..., ReawarpProject] | None = None,
    ):
        spec = request if isinstance(request, VariationRequest) else VariationRequest.from_dict(request)
        frozen = clone_project(base_project, readonly=True)
        base_fp = project_fingerprint(frozen)
        request_json = json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        batch_id = batch_id or hashlib.sha256(
            f"{base_fp}:{request_json}:{parent_candidate_id or ''}".encode()
        ).hexdigest()[:16]
        candidates = []
        for index in range(1, spec.count + 1):
            self._check_cancel(cancel_event)
            seed = _candidate_seed(frozen.config.seed, batch_id, index)
            project = self._render_candidate(
                frozen, spec, index, seed, cancel_event=cancel_event,
                sound_object_renderer=sound_object_renderer,
            )
            self._check_cancel(cancel_event)
            flags = []
            changed_stems = set(spec.targets) if spec.mode in {"stems", "automation"} else set()
            if spec.mode == "automation" and not spec.targets:
                changed_stems = set(frozen.stems)
            if spec.mode == "sound_object":
                changed_stems = {
                    str(item.get("stem"))
                    for item in candidate.metadata.get("sound_object_variants", [])
                    if isinstance(item, dict) and item.get("stem")
                }
            for name, source in frozen.stems.items():
                output = project.stems.get(name)
                if output is None:
                    flags.append(f"missing_stem:{name}")
                elif output.shape != source.shape:
                    flags.append(f"frame_or_channel_mismatch:{name}")
                elif not np.isfinite(output).all():
                    flags.append(f"non_finite_audio:{name}")
                elif name not in changed_stems and spec.mode in {"stems", "sound_object", "automation"} and not np.array_equal(output, source):
                    flags.append(f"unexpected_change_in_unchanged_stem:{name}")
            if project.sample_rate != frozen.sample_rate:
                flags.append("sample_rate_mismatch")
            sound_object_variants = project.metadata.get("sound_object_variants", [])
            for variant in sound_object_variants:
                if not isinstance(variant, dict):
                    continue
                for warning in variant.get("diagnostics", {}).get("warnings", []):
                    if isinstance(warning, dict):
                        flags.append(
                            f"sound_object:{variant.get('patch_id', 'unknown')}:"
                            f"{warning.get('kind', 'renderer_warning')}"
                        )
            lineage = {
                "root_seed": frozen.config.seed,
                "render_root_seed": project.config.seed,
                "seed_streams": copy.deepcopy(project.metadata.get("seed_streams", {})),
                "sample_trigger_seed_streams": copy.deepcopy(project.metadata.get("sample_trigger_seed_streams", {})),
                "variation_seed": seed,
                "recreation": {"mode": spec.mode, "targets": list(spec.targets), "request": spec.to_dict()},
            }
            metrics = {name: _signal_summary(project.stems[name], project.sample_rate)
                       for name in spec.targets if name in project.stems}
            candidate_id = hashlib.sha256(f"{batch_id}:{index}:{seed}".encode()).hexdigest()[:20]
            record = VariationCandidateRecord(
                candidate_id=candidate_id, batch_id=batch_id, index=index,
                label=f"Candidate {index:02d}", mode=spec.mode, targets=spec.targets,
                base_project_fingerprint=base_fp, parent_candidate_id=parent_candidate_id,
                root_seed=frozen.config.seed, variation_seed=seed, seed_lineage=lineage,
                changed_parameters={
                    "config_overrides": spec.config_overrides,
                    "score_patch": spec.score_patch,
                    "targets": list(spec.targets),
                    "sound_object_variants": copy.deepcopy(
                        project.metadata.get("sound_object_variants", [])
                    ),
                },
                technical_flags=flags, technical_metrics=metrics,
            )
            _attach_candidate(project, record)
            candidates.append(VariationCandidate(record, project))
        if project_fingerprint(frozen) != base_fp:
            raise RuntimeError("frozen source project changed during variation generation")
        return VariationBatch(batch_id, base_fp, spec, candidates)

    def _render_candidate(self, base, request, index, variation_seed, *, cancel_event, sound_object_renderer):
        self._check_cancel(cancel_event)
        if request.mode == "stems":
            if not request.targets:
                raise ValueError("stem variation requires at least one target")
            current = clone_project(base)
            for stem in request.targets:
                self._check_cancel(cancel_event)
                if stem not in base.stems:
                    raise ValueError(f"variation target is not a project stem: {stem}")
                current = self.engine.generate_variant(
                    base.config, stem, variation_seed, base_project=current
                )
            return current
        if request.mode in {"full_project", "config", "sample_bank"}:
            from reawarp.config import GenerationConfig
            values = base.config.to_dict()
            values.update(copy.deepcopy(request.config_overrides))
            values["seed"] = request.config_overrides.get("seed", variation_seed)
            return self.engine.generate(GenerationConfig.from_dict(values))
        if request.mode == "automation":
            score_data = base.to_score().to_dict()
            if request.score_patch:
                score_data.update(copy.deepcopy(request.score_patch))
            else:
                # Mutate authored controls around their local centre while
                # retaining timing, source identity, bounds and interpolation.
                rng = np.random.default_rng(variation_seed)
                lanes = score_data.get("automation", [])
                sources = score_data.get("automation_sources", [])
                modulations = score_data.get("modulations", [])
                if not (lanes or sources or modulations):
                    raise ValueError(
                        "automation variation requires Score lanes, sources/modulations or an explicit Score patch"
                    )
                for lane in lanes:
                    points = lane.get("points", [])
                    if not points:
                        continue
                    values = [float(point["value"]) for point in points]
                    centre = float(np.mean(values))
                    scale = float(rng.uniform(0.82, 1.18))
                    for point in points:
                        value = centre + (float(point["value"]) - centre) * scale
                        if lane.get("minimum") is not None:
                            value = max(float(lane["minimum"]), value)
                        if lane.get("maximum") is not None:
                            value = min(float(lane["maximum"]), value)
                        point["value"] = value
                for source in sources:
                    parameters = source.setdefault("parameters", {})
                    source_scale = float(rng.uniform(0.82, 1.18))
                    if source.get("kind") in {"phrase_curve", "stepped"}:
                        values = parameters.get("values")
                        if isinstance(values, list) and values:
                            centre = float(np.mean([float(value) for value in values]))
                            parameters["values"] = [
                                centre + (float(value) - centre) * source_scale
                                for value in values
                            ]
                    elif source.get("kind") == "envelope":
                        shape = parameters.get("shape")
                        if isinstance(shape, list):
                            points = []
                            for point in shape:
                                if isinstance(point, (list, tuple)) and len(point) == 2:
                                    points.append([
                                        point[0],
                                        float(point[1]) * source_scale,
                                    ])
                                else:
                                    points.append(point)
                            parameters["shape"] = points
                    elif source.get("kind") == "lfo":
                        if "depth" in parameters:
                            parameters["depth"] = float(parameters["depth"]) * source_scale
                        if "phase_cycles" in parameters:
                            parameters["phase_cycles"] = float(parameters["phase_cycles"]) + float(
                                rng.uniform(-0.08, 0.08)
                            )
                    elif source.get("kind") == "random_walk":
                        if "step_size" in parameters:
                            parameters["step_size"] = float(parameters["step_size"]) * source_scale
                for modulation in modulations:
                    modulation["amount"] = float(modulation.get("amount", 0.25)) * float(
                        rng.uniform(0.82, 1.18)
                    )
            score = Score.from_dict(score_data)
            rendered = self.engine.render_score(score, config=base.config)
            canonical = rendered.score or score
            targets = {self.engine._event_lane_for_stem(x) for x in request.targets}
            if not targets:
                targets = {e.voice_id for e in canonical.events if e.kind not in {"control", "marker"}}
            stems = {n: np.asarray(a, dtype=np.float32).copy() for n, a in base.stems.items()}
            for voice in targets:
                name = _event_voice_stem(voice)
                if name not in stems:
                    continue
                audio = rendered.stems.get(voice)
                stems[name] = np.zeros_like(stems[name]) if audio is None else np.asarray(audio, dtype=np.float32).copy()
            from reawarp.core.score_generation import score_to_legacy_project_events
            score_metadata = dict(canonical.metadata)
            score_metadata["render_stems"] = list(stems)
            canonical = replace(canonical, metadata=score_metadata)
            metadata = copy.deepcopy(base.metadata)
            metadata["m23_automation_variation_seed"] = variation_seed
            return ReawarpProject(
                config=base.config, sample_rate=base.sample_rate, stems=stems,
                events=score_to_legacy_project_events(canonical), metadata=metadata, score=canonical,
            )
        if request.mode == "sound_object":
            if sound_object_renderer is None:
                raise ValueError("sound-object variation requires a sound_object_renderer adapter")
            result = sound_object_renderer(base, index, variation_seed, request, cancel_event)
            if not isinstance(result, ReawarpProject):
                raise TypeError("sound-object renderer must return a ReawarpProject")
            return result
        raise ValueError(f"unsupported variation mode: {request.mode}")

def matched_ab(reference, candidate, *, sample_rate, target_rms_dbfs=-18.0, peak_ceiling=0.95):
    """Return matched-level A/B copies and a difference buffer; never mutate inputs."""
    left, right = np.asarray(reference, dtype=np.float32), np.asarray(candidate, dtype=np.float32)
    if left.ndim not in {1, 2} or right.ndim not in {1, 2}:
        raise ValueError("A/B audio must be mono or multichannel")
    if left.ndim == 1: left = left[:, None]
    if right.ndim == 1: right = right[:, None]
    channels = max(left.shape[1], right.shape[1])
    if channels not in {1, 2}: raise ValueError("A/B audio must be mono or stereo")
    if left.shape[1] == 1 and channels == 2: left = np.repeat(left, 2, axis=1)
    if right.shape[1] == 1 and channels == 2: right = np.repeat(right, 2, axis=1)
    frames = max(len(left), len(right))
    left = np.pad(left, ((0, frames-len(left)), (0, 0)))
    right = np.pad(right, ((0, frames-len(right)), (0, 0)))
    matched_left, left_report = match_audition_level(
        left, target_rms_dbfs=target_rms_dbfs, peak_ceiling=peak_ceiling
    )
    matched_right, right_report = match_audition_level(
        right, target_rms_dbfs=target_rms_dbfs, peak_ceiling=peak_ceiling
    )
    difference = np.ascontiguousarray(matched_right - matched_left, dtype=np.float32)
    return {
        "reference": matched_left, "candidate": matched_right, "difference": difference,
        "reference_match": left_report, "candidate_match": right_report,
        "difference_meter": measure_signal(difference, sample_rate=sample_rate),
        "sample_rate": int(sample_rate), "level_match_target_dbfs": float(target_rms_dbfs),
    }

def project_audio(project, *, stem=None):
    if stem is None or stem == "master": return project.render_master()
    try: return np.asarray(project.stems[stem], dtype=np.float32)
    except KeyError as exc: raise KeyError(f"project has no stem {stem!r}") from exc

def build_listening_set(project, preset="full_mix", *, targets=()):
    """Create contextual listening sets; never rank or grade artistic quality."""
    stems = project.stems
    if preset == "full_mix": return {"FULL MIX": project.render_master()}
    if preset == "isolated_roles": return {n.upper(): np.asarray(a).copy() for n, a in stems.items()}
    if preset == "role_pairs":
        pairs = (
            ("KICK + SNARE", ("kick", "snare")), ("HATS + BREAK", ("hats", "synthetic_break")),
            ("MELODY + TEXTURE", ("melody", "noise_texture")), ("MELODY + AMBIENCE", ("melody", "ambience")),
        )
        result = {}
        for label, names in pairs:
            buffers = [stems[n] for n in names if n in stems]
            if buffers:
                mix = np.zeros_like(buffers[0], dtype=np.float32)
                for audio in buffers: mix += audio
                result[label] = mix
        return result
    if preset in {"opening", "middle", "ending"}:
        spans = {"opening": (0, 1/3), "middle": (1/3, 2/3), "ending": (2/3, 1)}
        start, end = spans[preset]
        master = project.render_master()
        return {preset.upper(): master[int(round(len(master)*start)):int(round(len(master)*end))].copy()}
    if preset == "transitions":
        master, bpm = project.render_master(), float(project.config.bpm)
        result = {}
        for i, gesture in enumerate(project.metadata.get("transition_gestures", [])):
            centre = int(round(float(gesture.get("boundary_bar", 0))*4*60/bpm*project.sample_rate))
            radius = int(2*project.sample_rate)
            lo, hi = max(0, centre-radius), min(len(master), centre+radius)
            if hi > lo: result[f"TRANSITION {i+1:02d}"] = master[lo:hi].copy()
        return result or {"FULL MIX": master}
    if preset == "subtraction":
        selected = tuple(targets) or tuple(n for n in ("kick", "melody", "noise_texture") if n in stems)
        result = {}
        master = project.render_master()
        for name in selected:
            if name in stems:
                residual = master.copy()
                residual[:len(stems[name])] -= stems[name]
                result[f"WITHOUT {name.upper()}"] = residual
        return result or {"FULL MIX": master}
    raise ValueError(f"unknown listening-set preset: {preset}")

def variation_session_metadata(base_project, candidates: Mapping[str, VariationCandidate], *, active_candidate_id=None):
    return {
        "schema_version": 1,
        "base_project_fingerprint": project_fingerprint(base_project),
        "active_candidate_id": active_candidate_id,
        "candidate_records": [c.record.to_dict() for _, c in sorted(candidates.items(), key=lambda x: x[1].record.index)],
        "listening_policy": "human_selection_only_no_artistic_auto_score",
    }
