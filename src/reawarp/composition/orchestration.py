"""Section-level role intent and phrase-boundary transition planning."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from typing import Any, Sequence

import numpy as np

from reawarp.composition.director import section_for_time

ROLE_NAMES = ("kick", "snare", "hat", "break", "melody", "texture", "ambience")

# Musical function is a composition decision, not a linear proxy for energy.
_FUNCTION_ACTIVITY: dict[str, dict[str, float]] = {
    "introduction": {
        "kick": 0.18,
        "snare": 0.04,
        "hat": 0.24,
        "break": 0.08,
        "melody": 0.48,
        "texture": 0.22,
        "ambience": 0.72,
    },
    "establishment": {
        "kick": 0.78,
        "snare": 0.52,
        "hat": 0.38,
        "break": 0.24,
        "melody": 0.74,
        "texture": 0.24,
        "ambience": 0.42,
    },
    "continuation": {
        "kick": 0.66,
        "snare": 0.56,
        "hat": 0.52,
        "break": 0.46,
        "melody": 0.68,
        "texture": 0.34,
        "ambience": 0.40,
    },
    "development": {
        "kick": 0.72,
        "snare": 0.68,
        "hat": 0.72,
        "break": 0.58,
        "melody": 0.82,
        "texture": 0.50,
        "ambience": 0.34,
    },
    "uplift": {
        "kick": 0.86,
        "snare": 0.76,
        "hat": 0.94,
        "break": 0.72,
        "melody": 0.90,
        "texture": 0.44,
        "ambience": 0.36,
    },
    "arrival": {
        "kick": 1.00,
        "snare": 0.92,
        "hat": 0.96,
        "break": 0.82,
        "melody": 0.88,
        "texture": 0.25,
        "ambience": 0.42,
    },
    "drop": {
        "kick": 0.08,
        "snare": 0.12,
        "hat": 0.24,
        "break": 0.08,
        "melody": 0.34,
        "texture": 0.16,
        "ambience": 0.76,
    },
    "silence": {
        "kick": 0.0,
        "snare": 0.0,
        "hat": 0.015,
        "break": 0.0,
        "melody": 0.015,
        "texture": 0.0,
        "ambience": 0.90,
    },
    "contrast": {
        "kick": 0.36,
        "snare": 0.76,
        "hat": 0.48,
        "break": 0.32,
        "melody": 0.72,
        "texture": 0.46,
        "ambience": 0.64,
    },
    "return": {
        "kick": 0.78,
        "snare": 0.52,
        "hat": 0.38,
        "break": 0.30,
        "melody": 0.78,
        "texture": 0.22,
        "ambience": 0.46,
    },
    "false_return": {
        "kick": 0.48,
        "snare": 0.34,
        "hat": 0.28,
        "break": 0.18,
        "melody": 0.60,
        "texture": 0.18,
        "ambience": 0.66,
    },
    "transition": {
        "kick": 0.46,
        "snare": 0.56,
        "hat": 0.64,
        "break": 0.50,
        "melody": 0.58,
        "texture": 0.42,
        "ambience": 0.66,
    },
    "residue": {
        "kick": 0.06,
        "snare": 0.12,
        "hat": 0.22,
        "break": 0.06,
        "melody": 0.30,
        "texture": 0.12,
        "ambience": 0.82,
    },
    "outro": {
        "kick": 0.015,
        "snare": 0.02,
        "hat": 0.10,
        "break": 0.02,
        "melody": 0.20,
        "texture": 0.10,
        "ambience": 0.78,
    },
}


@dataclass(frozen=True, slots=True)
class RoleIntent:
    role: str
    active: bool
    activity: float
    density: float
    syncopation: float
    register_semitones: int
    brightness: float
    space_intent: float
    motif_relation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SectionOrchestrationPlan:
    section_index: int
    section_name: str
    function: str
    start_bar: int
    end_bar: int
    motif_id: str | None
    motif_transform: str | None
    roles: tuple[RoleIntent, ...]

    def role(self, name: str) -> RoleIntent:
        for intent in self.roles:
            if intent.role == name:
                return intent
        raise KeyError(f"unknown orchestration role: {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_index": self.section_index,
            "section_name": self.section_name,
            "function": self.function,
            "start_bar": self.start_bar,
            "end_bar": self.end_bar,
            "motif_id": self.motif_id,
            "motif_transform": self.motif_transform,
            "roles": [intent.to_dict() for intent in self.roles],
        }


@dataclass(frozen=True, slots=True)
class TransitionGesture:
    source_section: int
    target_section: int
    source_name: str
    target_name: str
    gesture: str
    start_bar: int
    boundary_bar: int
    start_seconds: float
    end_seconds: float
    intensity: float
    affected_roles: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["affected_roles"] = list(self.affected_roles)
        return data


def _stable_role_value(
    seed: int | str,
    role: str,
    section_index: int,
    step: int,
    kind: str,
    purpose: str,
) -> float:
    payload = f"{seed}:{role}:{section_index}:{step}:{kind}:{purpose}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "little") / float(2**64)


def shape_role_events(
    role: str,
    events: Sequence[Any],
    composition_plan: Any,
    orchestration_plan: Sequence[SectionOrchestrationPlan],
    *,
    step_seconds: float,
    seed: int | str,
) -> list[Any]:
    """Apply section density and syncopation without consuming generator RNG streams.

    Metric anchors and motif-carried cross-role events are protected. Other hits
    are deterministically thinned by the role's density intent, then selected
    even sixteenth-note positions may move one cell forward according to the
    role's syncopation intent. A shift never crosses a bar boundary.
    """
    if role not in {"kick", "snare", "hat", "break"}:
        raise KeyError(f"role {role!r} does not accept percussion events")
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    plans = {item.section_index: item for item in orchestration_plan}
    result = []
    for event in events:
        section = section_for_time(composition_plan, float(event.time))
        plan = plans.get(int(section.index))
        if plan is None:
            raise ValueError(f"no orchestration plan for section {section.index}")
        intent = plan.role(role)
        step = int(event.step)
        position = step % 16
        kind = str(event.kind or "")
        motif_relation = getattr(event, "motif_relation", None)
        motif_carried = motif_relation in {"shadow", "response"}
        anchor = (
            (role == "kick" and position in {0, 8})
            or (role == "snare" and position in {4, 12})
            or (
                role == "break"
                and (
                    (kind == "kick" and position == 0)
                    or (kind == "snare" and position in {4, 12})
                )
            )
        )
        if not anchor and not motif_carried:
            keep_probability = 0.15 + 0.85 * float(intent.density)
            keep_value = _stable_role_value(
                seed, role, section.index, step, kind, "density"
            )
            if keep_value >= keep_probability:
                continue

        adjusted = event
        if (
            role in {"snare", "hat", "break"}
            and not motif_carried
            and position % 2 == 0
            and not (role == "snare" and position in {4, 12})
        ):
            shift_probability = 0.50 * float(intent.syncopation)
            shift_value = _stable_role_value(
                seed, role, section.index, step, kind, "syncopation"
            )
            shifted_step = step + 1
            if shift_value < shift_probability and shifted_step // 16 == step // 16:
                adjusted = replace(
                    event, step=shifted_step, time=shifted_step * step_seconds
                )
        result.append(adjusted)

    return sorted(result, key=lambda item: (item.step, item.kind or ""))


def build_section_orchestration_plan(
    composition_plan: Any,
    phrase_directives: Sequence[Any],
    config: Any,
    motif_plan: Any = None,
) -> tuple[SectionOrchestrationPlan, ...]:
    """Allocate role activity and musical intent independently for each section."""
    directives = {int(item.index): item for item in phrase_directives}
    motifs = {
        int(item.section_index): item for item in getattr(motif_plan, "instances", ())
    }
    result = []
    for section in composition_plan.sections:
        directive = directives[int(section.index)]
        function = str(directive.function)
        base = _FUNCTION_ACTIVITY.get(function, _FUNCTION_ACTIVITY["continuation"])
        motif = motifs.get(int(section.index))
        roles = []
        for role in ROLE_NAMES:
            initial = float(base[role])
            if role in {"kick", "snare"}:
                activity = initial * (0.45 + 0.55 * float(config.arrangement_density))
            elif role == "hat":
                activity = initial * (0.35 + 0.65 * float(config.rhythmic_syncopation))
            elif role == "break":
                activity = initial * (
                    0.50
                    + 0.30 * float(config.arrangement_density)
                    + 0.20 * float(config.rhythmic_syncopation)
                )
            elif role == "melody":
                activity = initial * float(config.melodic_activity)
            elif role == "texture":
                activity = initial * (
                    0.35 + 0.65 * float(config.arrangement_instability)
                )
            else:
                activity = initial * (0.35 + 0.65 * float(config.spatial_intent))

            register = int(config.melody_register_semitones)
            if role == "melody" and function != "return":
                register += int(section.motif_register_semitones)
            brightness = float(
                np.clip(
                    0.68 * float(config.tonal_brightness)
                    + 0.32 * float(section.brightness),
                    0.0,
                    1.0,
                )
            )
            space = float(
                np.clip(
                    0.58 * float(config.spatial_intent) + 0.42 * float(section.space),
                    0.0,
                    1.0,
                )
            )
            role_density = float(
                np.clip(
                    float(config.arrangement_density) * (0.45 + 0.55 * initial),
                    0.0,
                    1.0,
                )
            )
            syncopation = float(
                np.clip(
                    float(config.rhythmic_syncopation)
                    * (0.60 + 0.40 * float(section.instability)),
                    0.0,
                    1.0,
                )
            )

            if role == "kick":
                relation = (
                    "anchor"
                    if function in {"establishment", "return", "arrival"}
                    else "pulse"
                )
            elif role == "snare":
                relation = "response" if function == "contrast" else "backbeat"
            elif role == "hat":
                relation = (
                    "shadow"
                    if function in {"development", "contrast", "uplift"}
                    else "ornament"
                )
            elif role == "break":
                relation = (
                    "fragment"
                    if motif and motif.operation in {"fragmentation", "dissolve"}
                    else "phrase"
                )
            elif role == "melody":
                relation = "carrier"
            elif role == "texture":
                relation = (
                    "counter_motion"
                    if function in {"development", "contrast"}
                    else "bed"
                )
            else:
                relation = (
                    "handoff"
                    if function in {"residue", "outro", "transition"}
                    else "space"
                )

            if role == "melody" and not config.include_melody:
                activity = 0.0
            elif role == "texture" and not config.include_texture:
                activity = 0.0
            elif role == "ambience" and not config.include_ambience:
                activity = 0.0
            activity = float(np.clip(activity, 0.0, 1.0))
            roles.append(
                RoleIntent(
                    role=role,
                    active=activity > 0.015,
                    activity=activity,
                    density=role_density,
                    syncopation=syncopation,
                    register_semitones=register if role == "melody" else 0,
                    brightness=brightness,
                    space_intent=space,
                    motif_relation=relation,
                )
            )
        result.append(
            SectionOrchestrationPlan(
                section_index=int(section.index),
                section_name=str(section.name),
                function=function,
                start_bar=int(section.start_bar),
                end_bar=int(section.end_bar),
                motif_id=motif.motif_id if motif else None,
                motif_transform=motif.operation if motif else None,
                roles=tuple(roles),
            )
        )
    return tuple(result)


def build_transition_plan(
    composition_plan: Any,
    phrase_directives: Sequence[Any],
) -> tuple[TransitionGesture, ...]:
    """Convert phrase grammar gestures into bounded section-end windows."""
    directives = {int(item.index): item for item in phrase_directives}
    bar_seconds = 240.0 / float(composition_plan.bpm)
    plans = []
    for index, section in enumerate(composition_plan.sections[:-1]):
        following = composition_plan.sections[index + 1]
        directive = directives[int(section.index)]
        gesture = str(directive.transition_out)
        if gesture in {"", "none"}:
            continue
        start_bar = max(int(section.start_bar), int(section.end_bar) - 1)
        start_seconds = max(
            float(section.start_seconds), float(section.end_seconds) - bar_seconds
        )
        end_seconds = min(
            float(composition_plan.duration_seconds), float(section.end_seconds)
        )
        if end_seconds <= start_seconds:
            continue
        affected = {
            "pickup": ("kick", "snare", "hat", "break"),
            "fill": ("kick", "snare", "hat", "break"),
            "riser": ("texture", "ambience", "melody"),
            "subtraction": ("kick", "snare", "hat", "break", "melody"),
            "hard_cut": ("kick", "snare", "hat", "break", "melody", "texture"),
            "reverse_swell": ("texture", "ambience"),
            "register_shift": ("melody",),
            "echo_handoff": ("ambience", "texture"),
            "rhythmic_collapse": ("kick", "snare", "hat", "break"),
            "silence_gate": ("kick", "snare", "hat", "break", "melody"),
            "fragment_reassembly": ("melody", "hat", "snare"),
            "false_cadence": ("kick", "snare", "melody"),
        }.get(gesture, ROLE_NAMES)
        plans.append(
            TransitionGesture(
                source_section=int(section.index),
                target_section=int(following.index),
                source_name=str(section.name),
                target_name=str(following.name),
                gesture=gesture,
                start_bar=start_bar,
                boundary_bar=int(section.end_bar),
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                intensity=float(np.clip(directive.variation_budget, 0.0, 1.0)),
                affected_roles=tuple(affected),
            )
        )
    return tuple(plans)


def _transition_multiplier(
    role: str, gesture: str, phase: np.ndarray, intensity: float
) -> np.ndarray:
    p = np.clip(np.asarray(phase, dtype=np.float64), 0.0, 1.0)
    strength = float(np.clip(intensity, 0.0, 1.0))
    ones = np.ones_like(p)
    if gesture in {"pickup", "fill"}:
        amount = strength * p
        factors = {
            "kick": 1.0 + 0.12 * amount,
            "snare": 1.0 + 0.38 * amount,
            "hat": 1.0 + 0.42 * amount,
            "break": 1.0 + 0.20 * amount,
        }
        return np.clip(factors.get(role, ones), 0.0, 1.35)
    if gesture in {"riser", "reverse_swell"}:
        if role in {"texture", "ambience"}:
            return 0.62 + 0.55 * strength * p
        if role == "melody":
            return 0.94 + 0.08 * strength * p
    if gesture == "subtraction":
        amount = strength * p
        factors = {
            "kick": 1.0 - 0.80 * amount,
            "snare": 1.0 - 0.76 * amount,
            "hat": 1.0 - 0.52 * amount,
            "break": 1.0 - 0.82 * amount,
            "melody": 1.0 - 0.24 * amount,
        }
        return np.clip(factors.get(role, ones), 0.0, 1.0)
    if gesture == "rhythmic_collapse":
        amount = strength * p
        factor = 1.0 - (0.44 if role == "hat" else 0.74) * amount
        return np.full_like(p, factor)
    if gesture in {"hard_cut", "silence_gate"} and role in {
        "kick",
        "snare",
        "hat",
        "break",
        "melody",
        "texture",
    }:
        fade_start = 0.82 if gesture == "hard_cut" else 0.64
        fade = np.clip((p - fade_start) / (1.0 - fade_start), 0.0, 1.0)
        return 1.0 - fade
    if gesture == "echo_handoff":
        if role == "ambience":
            return 1.0 + 0.30 * strength * p
        if role == "texture":
            return 1.0 + 0.12 * strength * p
    if gesture == "fragment_reassembly":
        if role == "melody":
            return 0.84 + 0.20 * strength * p
        if role == "hat":
            return 1.0 + 0.14 * strength * p
    if gesture == "false_cadence":
        if role == "melody":
            return 1.0 - 0.18 * strength * p
        if role in {"kick", "snare"}:
            return 1.0 - 0.58 * strength * p
    return ones


def role_intent_at_time(
    role: str,
    time_seconds: float,
    composition_plan: Any,
    orchestration_plan: Sequence[SectionOrchestrationPlan],
) -> RoleIntent:
    if role not in ROLE_NAMES:
        raise KeyError(f"unknown composition role: {role}")
    section = section_for_time(composition_plan, time_seconds)
    plan = next(
        (item for item in orchestration_plan if item.section_index == section.index),
        None,
    )
    if plan is None:
        raise ValueError(f"no orchestration plan for section {section.index}")
    return plan.role(role)


def role_activity_at_time(
    role: str,
    time_seconds: float,
    composition_plan: Any,
    orchestration_plan: Sequence[SectionOrchestrationPlan],
    transitions: Sequence[TransitionGesture],
) -> float:
    intent = role_intent_at_time(
        role, time_seconds, composition_plan, orchestration_plan
    )
    multiplier = 1.0
    for transition in transitions:
        if (
            role in transition.affected_roles
            and transition.start_seconds <= time_seconds < transition.end_seconds
        ):
            duration = max(1e-9, transition.end_seconds - transition.start_seconds)
            phase = (time_seconds - transition.start_seconds) / duration
            multiplier *= float(
                _transition_multiplier(
                    role, transition.gesture, np.asarray([phase]), transition.intensity
                )[0]
            )
    return float(np.clip(intent.activity * multiplier, 0.0, 1.35))


def render_role_envelope(
    role: str,
    frame_count: int,
    sample_rate: int,
    composition_plan: Any,
    orchestration_plan: Sequence[SectionOrchestrationPlan],
    transitions: Sequence[TransitionGesture],
) -> np.ndarray:
    """Render section intents with continuous, bar-aligned transition shaping."""
    if role not in ROLE_NAMES:
        raise KeyError(f"unknown composition role: {role}")
    if frame_count < 0 or sample_rate <= 0:
        raise ValueError("frame_count must be non-negative and sample_rate positive")
    by_index = {item.section_index: item for item in orchestration_plan}
    envelope = np.zeros(frame_count, dtype=np.float32)
    for section in composition_plan.sections:
        start = max(0, int(round(section.start_seconds * sample_rate)))
        end = min(frame_count, int(round(section.end_seconds * sample_rate)))
        if end > start:
            envelope[start:end] = by_index[int(section.index)].role(role).activity
    for transition in transitions:
        if role not in transition.affected_roles:
            continue
        start = max(0, int(round(transition.start_seconds * sample_rate)))
        end = min(frame_count, int(round(transition.end_seconds * sample_rate)))
        if end <= start:
            continue
        phase = np.linspace(0.0, 1.0, end - start, endpoint=False, dtype=np.float64)
        envelope[start:end] *= _transition_multiplier(
            role, transition.gesture, phase, transition.intensity
        ).astype(np.float32)
    return np.clip(envelope, 0.0, 1.35).astype(np.float32, copy=False)
