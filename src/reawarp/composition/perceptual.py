"""Bridge M15 section/motif decisions into the M20 perceptual Score plan."""
from __future__ import annotations

import hashlib
from fractions import Fraction
from typing import Any, Sequence

from reawarp.score.orchestration_intent import (
    AttentionSpan,
    CycleSpec,
    MutationPolicy,
    OrchestrationPlan,
    PhraseSpan,
    RoleRelationship,
    TransitionSpan,
    build_orchestration_plan,
)


def _beat_from_seconds(seconds: float, bpm: float) -> Fraction:
    return (Fraction(str(seconds)) * Fraction(str(bpm)) / 60).limit_denominator(1_000_000)


def _phase(seed: int | str, role: str) -> Fraction:
    payload = f"reawarp:m20-cycle-phase:v1:{seed}:{role}".encode("utf-8")
    value = int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "little")
    return Fraction(value % 8, 8)


def _phrase_function(function: str) -> str:
    return {
        "introduction": "proposition",
        "establishment": "establishment",
        "continuation": "development",
        "development": "development",
        "uplift": "development",
        "arrival": "establishment",
        "drop": "suspension",
        "silence": "suspension",
        "contrast": "contrast",
        "return": "return",
        "false_return": "contrast",
        "transition": "transition",
        "residue": "residue",
        "outro": "coda",
    }.get(function, "development")


def _transition_gesture(gesture: str) -> str:
    return {
        "rhythmic_collapse": "collapse",
        "silence_gate": "silence",
        "fragment_reassembly": "return",
        "echo_handoff": "residue",
    }.get(gesture, gesture)


def build_perceptual_orchestration_plan(
    composition_plan: Any,
    phrase_directives: Sequence[Any],
    section_orchestration: Sequence[Any],
    transition_plan: Sequence[Any],
    *,
    config: Any,
    motif_plan: Any = None,
) -> OrchestrationPlan:
    """Compile M15's actual director decisions into M20's inspectable Score plan.

    Section boundaries are mapped to quarter-note beats using the active tempo.
    Cycle phases are deterministic and role-domain separated. No playback
    scheduling or additional randomness is introduced here.
    """
    bpm = float(composition_plan.bpm)
    directives = {int(item.index): item for item in phrase_directives}
    role_plans = {int(item.section_index): item for item in section_orchestration}
    motif_instances = {
        int(item.section_index): item
        for item in getattr(motif_plan, "instances", ())
    }
    sections = tuple(composition_plan.sections)

    phrases: list[PhraseSpan] = []
    phrase_by_section: dict[int, PhraseSpan] = {}
    for section in sections:
        directive = directives[int(section.index)]
        start = _beat_from_seconds(float(section.start_seconds), bpm)
        end = _beat_from_seconds(float(section.end_seconds), bpm)
        phrase = PhraseSpan(
            phrase_id=f"phrase-{int(section.index):03d}",
            start_beats=start,
            end_beats=end,
            function=_phrase_function(str(directive.function)),
            section_id=f"section-{int(section.index):03d}",
            tags=(str(section.name), str(directive.rhythm_mode)),
        )
        phrases.append(phrase)
        phrase_by_section[int(section.index)] = phrase

    # These are the cycles actually implied by the existing generator controls:
    # bar pulse, two-bar backbeat, the selected seven-pulse family when present,
    # imported-break cycle length, and persistent melody motif length.
    cycle_lengths: dict[str, Fraction] = {
        "kick": Fraction(4),
        "snare": Fraction(8),
    }
    family = str(composition_plan.pattern_family)
    if family.endswith("_7") or "asymmetric_7" in family:
        cycle_lengths["hat"] = Fraction(7)
    else:
        cycle_lengths["hat"] = Fraction(4)
    cycle_bars = max(1, int(getattr(config, "break_cycle_bars", 1)))
    cycle_lengths["break"] = Fraction(cycle_bars * 4)
    if motif_plan is not None:
        motif_bars = max(1, int(motif_plan.anchor.phrase_bars))
        cycle_lengths["melody"] = Fraction(motif_bars * 4)

    cycles = []
    for role, length in cycle_lengths.items():
        cycles.append(CycleSpec(
            cycle_id=f"{role}-cycle",
            role=role,
            length_beats=length,
            phase_beats=_phase(composition_plan.seed, role),
            start_beats=Fraction(0),
            end_beats=_beat_from_seconds(composition_plan.duration_seconds, bpm),
            anchor_id=(
                motif_plan.anchor.motif_id
                if role == "melody" and motif_plan is not None else None
            ),
        ))

    transitions: list[TransitionSpan] = []
    transition_by_source: dict[int, Any] = {}
    for item in transition_plan:
        transition_by_source[int(item.source_section)] = item
        source_id = f"phrase-{int(item.source_section):03d}"
        target_id = f"phrase-{int(item.target_section):03d}"
        transitions.append(TransitionSpan(
            transition_id=f"transition-{int(item.source_section):03d}-{int(item.target_section):03d}",
            source_phrase_id=source_id,
            target_phrase_id=target_id,
            start_beats=_beat_from_seconds(float(item.start_seconds), bpm),
            end_beats=_beat_from_seconds(float(item.end_seconds), bpm),
            gesture=_transition_gesture(str(item.gesture)),
            intensity=float(item.intensity),
            affected_roles=tuple(item.affected_roles),
            transition_intent=f"{item.source_name}->{item.target_name}",
        ))

    relationships: list[RoleRelationship] = []
    for section in sections:
        section_index = int(section.index)
        phrase = phrase_by_section[section_index]
        role_plan = role_plans[section_index]
        start, end = phrase.start_beats, phrase.end_beats
        transition = transition_by_source.get(section_index)
        transition_name = (
            None if transition is None else str(transition.gesture)
        )
        pair = {
            "unison": ("kick", "snare", "unison", Fraction(0)),
            "interlock": ("kick", "snare", "interlock", Fraction(1, 2)),
            "shadow": ("kick", "hat", "complement", Fraction(1, 4)),
            "call_response": ("melody", "snare", "call_response", Fraction(3, 4)),
            "counter_accent": ("kick", "hat", "counterpoint", Fraction(1, 2)),
        }.get(str(composition_plan.pattern_relationship))
        if pair is not None:
            source_role, target_role, kind, offset = pair
            relationships.append(RoleRelationship(
                relationship_id=f"pattern-{section_index:03d}",
                source_role=source_role,
                target_role=target_role,
                kind=kind,
                start_beats=start,
                end_beats=end,
                offset_beats=offset if kind in {"interlock", "complement", "counterpoint"} else 0,
                response_gap_beats=offset if kind == "call_response" else 0,
                transition_intent=transition_name,
            ))

        intents = {item.role: item for item in role_plan.roles}
        if intents.get("hat") is not None and intents["hat"].motif_relation == "shadow":
            relationships.append(RoleRelationship(
                relationship_id=f"motif-shadow-{section_index:03d}",
                source_role="melody",
                target_role="hat",
                kind="complement",
                start_beats=start,
                end_beats=end,
                offset_beats=Fraction(1, 4),
                transition_intent=transition_name,
            ))
        if intents.get("snare") is not None and intents["snare"].motif_relation == "response":
            relationships.append(RoleRelationship(
                relationship_id=f"motif-response-{section_index:03d}",
                source_role="melody",
                target_role="snare",
                kind="call_response",
                start_beats=start,
                end_beats=end,
                response_gap_beats=Fraction(3, 4),
                transition_intent=transition_name,
            ))
        if intents.get("texture") is not None and intents["texture"].motif_relation == "counter_motion":
            relationships.append(RoleRelationship(
                relationship_id=f"texture-counterpoint-{section_index:03d}",
                source_role="melody",
                target_role="texture",
                kind="counterpoint",
                start_beats=start,
                end_beats=end,
                offset_beats=Fraction(1, 3),
                transition_intent=transition_name,
            ))

    # Rank only categorical attention depth, never a quality score. Activity is
    # used as the director's declared prominence input; ties resolve by ROLE_NAMES order.
    role_order = ("melody", "break", "kick", "snare", "hat", "texture", "ambience")
    foreground_by_section: dict[int, str | None] = {}
    depth_by_section: dict[int, dict[str, str]] = {}
    for section in sections:
        plan = role_plans[int(section.index)]
        roles = {item.role: item for item in plan.roles}
        active = [
            role for role in role_order
            if role in roles and roles[role].active and roles[role].activity > 0.015
        ]
        active.sort(key=lambda role: (-roles[role].activity, role_order.index(role)))
        foreground = active[0] if active else None
        foreground_by_section[int(section.index)] = foreground
        depths: dict[str, str] = {}
        for role in role_order:
            if role not in active:
                depths[role] = "absence"
            elif role == foreground:
                depths[role] = "foreground"
            elif len(active) > 1 and active.index(role) == 1 and roles[role].activity >= roles[foreground].activity * 0.55:
                depths[role] = "midground"
            else:
                depths[role] = "background"
        depth_by_section[int(section.index)] = depths

    handoffs: dict[tuple[int, str], str] = {}
    for previous, current in zip(sections, sections[1:]):
        left = foreground_by_section[int(previous.index)]
        right = foreground_by_section[int(current.index)]
        if left and right and left != right:
            handoff_id = f"handoff-{int(previous.index):03d}-{int(current.index):03d}"
            handoffs[(int(previous.index), left)] = handoff_id
            handoffs[(int(current.index), right)] = handoff_id

    attention: list[AttentionSpan] = []
    pitch_center = (
        float(motif_plan.anchor.pitch_center) if motif_plan is not None else 60.0
    )
    for section in sections:
        section_index = int(section.index)
        role_plan = role_plans[section_index]
        role_intents = {item.role: item for item in role_plan.roles}
        phrase = phrase_by_section[section_index]
        for role in role_order:
            intent = role_intents.get(role)
            depth = depth_by_section[section_index][role]
            register_low = register_high = None
            spectral_band = {
                "kick": "sub-low", "snare": "upper-mid", "hat": "high",
                "break": "broadband", "melody": "mid", "texture": "broadband",
                "ambience": "broadband",
            }[role]
            if role == "melody" and intent is not None:
                centre = pitch_center + float(intent.register_semitones)
                register_low, register_high = centre - 12.0, centre + 12.0
            semantic_role = {
                "kick": "anchor",
                "snare": "counter_rhythm",
                "hat": "counter_rhythm",
                "break": "counter_rhythm",
                "melody": "motif",
                "texture": "texture",
                "ambience": "harmonic_field",
            }[role]
            attention.append(AttentionSpan(
                role=role,
                start_beats=phrase.start_beats,
                end_beats=phrase.end_beats,
                depth=depth,
                handoff_id=handoffs.get((section_index, role)),
                register_low=register_low,
                register_high=register_high,
                spectral_band=spectral_band,
                reserved_silence=depth == "absence",
                attention_role=semantic_role,
                prominence=(
                    0.0 if depth == "absence"
                    else float(intent.activity) if intent is not None else None
                ),
            ))

    mutations: list[MutationPolicy] = []
    for section in sections:
        section_index = int(section.index)
        phrase = phrase_by_section[section_index]
        directive = directives[section_index]
        instance = motif_instances.get(section_index)
        motif_id = instance.motif_id if instance is not None else None
        preserved_motif = tuple(instance.preserved_dimensions) if instance else ()
        changed_motif = tuple(instance.changed_dimensions) if instance else ()
        anchors = ["section-downbeat"]
        if motif_id:
            anchors.append(motif_id)
        mutations.append(MutationPolicy(
            phrase_id=phrase.phrase_id,
            stable_anchors=tuple(anchors),
            preserve_pattern=("primary-pulse",) if directive.anchor_strength >= 0.5 else (),
            preserve_motif=preserved_motif,
            preserve_sound=("source_identity",),
            allow_pattern=(
                ("density", "syncopation")
                if directive.function in {"development", "contrast", "uplift"} else ()
            ),
            allow_motif=changed_motif,
            allow_sound=(),
            principal_developments=1,
        ))

    return build_orchestration_plan(
        phrases=phrases,
        cycles=cycles,
        relationships=relationships,
        attention=attention,
        mutation_policies=mutations,
        transitions=transitions,
        seed=int(hashlib.blake2b(str(composition_plan.seed).encode("utf-8"), digest_size=4).hexdigest(), 16),
        title=f"{composition_plan.structure} perceptual orchestration",
    )
