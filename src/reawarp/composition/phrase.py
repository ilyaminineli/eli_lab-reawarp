"""Phrase-level musical functions for recognisable long-form composition.

A phrase directive describes compositional behaviour, not a new synthesis
engine. Directives can be consumed by percussion, motifs, sample selection,
ambience, automation and transitions while all voices remain on the shared
project beat clock.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PHRASE_FUNCTIONS = (
    "introduction",
    "establishment",
    "continuation",
    "development",
    "uplift",
    "arrival",
    "drop",
    "silence",
    "contrast",
    "return",
    "false_return",
    "transition",
    "residue",
    "outro",
)

TRANSITION_GESTURES = (
    "none",
    "pickup",
    "fill",
    "riser",
    "subtraction",
    "hard_cut",
    "reverse_swell",
    "register_shift",
    "echo_handoff",
    "rhythmic_collapse",
    "silence_gate",
    "fragment_reassembly",
    "false_cadence",
)


@dataclass(frozen=True, slots=True)
class PhraseDirective:
    index: int
    function: str
    start_bar: int
    end_bar: int
    anchor_strength: float
    motif_mode: str
    rhythm_mode: str
    density_scale: float
    event_activity: float
    kick_activity: float
    snare_activity: float
    high_activity: float
    melody_activity: float
    texture_activity: float
    ambience_activity: float
    space_intent: float
    silence_ratio: float
    transition_in: str
    transition_out: str
    variation_budget: float
    memory_tag: str

    @property
    def bars(self) -> int:
        return self.end_bar - self.start_bar

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _function(name: str, motif_mode: str) -> str:
    token = name.upper()
    if "INTRO" in token or token in {"SIGNAL", "SEED_OBJECT", "ORIGIN"}:
        return "introduction"
    if any(
        word in token
        for word in ("FOUNDATION", "ESTABLISH", "FRAME", "EXPOSITION", "SUBJECT_A")
    ):
        return "establishment"
    if any(
        word in token
        for word in ("UPLIFT", "SURGE_IN", "PRE_COLLISION", "PICKUP", "RAMP")
    ):
        return "uplift"
    if any(
        word in token for word in ("PEAK", "COLLISION", "OVERLOAD", "CLIMAX", "ARRIVAL")
    ):
        return "arrival"
    if any(
        word in token
        for word in ("DROP", "VOID", "NULL", "SILENCE", "OPEN_SPACE", "SUSPENSION")
    ):
        return (
            "silence"
            if any(word in token for word in ("VOID", "NULL", "SILENCE"))
            else "drop"
        )
    if any(word in token for word in ("CONTRAST", "COUNTER")):
        return "contrast"
    if any(word in token for word in ("FALSE_RETURN", "FALSE_REPRISE")):
        return "false_return"
    if (
        any(word in token for word in ("RETURN", "REPRISE", "RECAP", "REASSEMBLY"))
        or motif_mode == "return"
    ):
        return "return"
    if any(
        word in token
        for word in ("RESIDUE", "AFTERIMAGE", "AFTERSHOCK", "UNRAVEL", "DISSOLVE")
    ):
        return "residue"
    if "OUTRO" in token or "CODA" in token or "RELEASE" in token:
        return "outro"
    if any(word in token for word in ("TRANSITION", "BRIDGE", "TURN")):
        return "transition"
    if motif_mode in {"develop", "fragment", "rhythmic", "inversion"}:
        return "development"
    return "continuation"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def build_phrase_directives(sections) -> tuple[PhraseDirective, ...]:
    """Map formal sections to deterministic, role-aware phrase directives."""
    result: list[PhraseDirective] = []
    for index, section in enumerate(sections):
        function = _function(section.name, section.motif_mode)
        previous = sections[index - 1] if index else None
        following = sections[index + 1] if index + 1 < len(sections) else None

        transition_in = "none"
        if previous is None:
            transition_in = "none"
        elif function in {"arrival", "uplift"}:
            transition_in = "pickup" if function == "uplift" else "fill"
        elif function in {"drop", "silence"}:
            transition_in = "subtraction" if function == "drop" else "hard_cut"
        elif function in {"return", "false_return"}:
            transition_in = (
                "fragment_reassembly" if function == "return" else "false_cadence"
            )
        elif function == "contrast":
            transition_in = "register_shift"
        elif function == "residue":
            transition_in = "echo_handoff"

        transition_out = "none"
        if following is not None:
            next_function = _function(following.name, following.motif_mode)
            if next_function == "uplift":
                transition_out = "riser"
            elif next_function == "arrival":
                transition_out = "fill"
            elif next_function in {"drop", "silence"}:
                transition_out = "rhythmic_collapse"
            elif next_function in {"return", "false_return"}:
                transition_out = "fragment_reassembly"
            elif next_function in {"residue", "outro"}:
                transition_out = "echo_handoff"

        energy = _clamp(section.energy)
        density = _clamp(section.density)
        instability = _clamp(section.instability / 0.90)
        space = _clamp(section.space)
        silence_ratio = {
            "introduction": 0.18,
            "drop": 0.22,
            "silence": 0.72,
            "residue": 0.35,
            "outro": 0.46,
        }.get(function, 0.0)
        if function == "arrival":
            silence_ratio = 0.0

        kick_activity = _clamp((0.82 * density + 0.18 * energy) * (1.0 - silence_ratio))
        if function in {"introduction", "drop", "silence", "residue", "outro"}:
            kick_activity *= {
                "introduction": 0.28,
                "drop": 0.0,
                "silence": 0.0,
                "residue": 0.12,
                "outro": 0.0,
            }[function]
        snare_activity = _clamp(
            (0.55 * density + 0.45 * energy) * (1.0 - silence_ratio)
        )
        if function in {"introduction", "drop", "silence", "residue", "outro"}:
            snare_activity *= {
                "introduction": 0.20,
                "drop": 0.10,
                "silence": 0.0,
                "residue": 0.10,
                "outro": 0.0,
            }[function]
        high_activity = _clamp(
            (0.42 * density + 0.58 * instability) * (1.0 - silence_ratio)
        )
        if function == "drop":
            high_activity = max(high_activity, 0.22 * instability)
        melody_activity = _clamp(
            (0.55 * energy + 0.45 * (1.0 - density)) * (1.0 - silence_ratio)
        )
        texture_activity = _clamp(
            (0.55 * energy + 0.45 * instability) * (1.0 - silence_ratio)
        )
        if function == "drop":
            melody_activity = max(melody_activity, 0.12)
            texture_activity *= 0.18
        ambience_activity = _clamp(0.30 + 0.70 * space)
        if function in {"silence", "outro"}:
            ambience_activity = _clamp(space * 0.75)
        if function == "arrival":
            high_activity = _clamp(high_activity * 0.85)
            texture_activity = _clamp(texture_activity * 0.70)
        if function == "uplift":
            event_activity = _clamp(energy * 1.12)
            high_activity = _clamp(high_activity * 1.16)
            melody_activity = _clamp(melody_activity * 1.08)
        if function == "return":
            melody_activity = max(melody_activity, 0.55)
        if function == "false_return":
            melody_activity = max(melody_activity, 0.35)
            kick_activity *= 0.55

        anchor = {
            "introduction": 0.25,
            "establishment": 0.95,
            "continuation": 0.70,
            "development": 0.58,
            "uplift": 0.62,
            "arrival": 0.98,
            "drop": 0.30,
            "silence": 0.08,
            "contrast": 0.24,
            "return": 0.92,
            "false_return": 0.46,
            "transition": 0.38,
            "residue": 0.18,
            "outro": 0.12,
        }[function]

        rhythm_mode = {
            "introduction": "fragment",
            "establishment": "anchor",
            "continuation": "retain",
            "development": "mutate_one_axis",
            "uplift": "increase_activity",
            "arrival": "full_interlock",
            "drop": "subtract_roles",
            "silence": "void",
            "contrast": "counter_rhythm",
            "return": "recognisable_reprise",
            "false_return": "incomplete_reprise",
            "transition": "handoff",
            "residue": "ghosts_only",
            "outro": "dissolve",
        }[function]

        event_activity = _clamp(energy * (1.0 - silence_ratio))
        if function == "uplift":
            event_activity = _clamp(event_activity * 1.12)
        elif function == "drop":
            event_activity = max(0.08, event_activity * 0.24)
        elif function == "silence":
            event_activity = 0.0
        result.append(
            PhraseDirective(
                index=index,
                function=function,
                start_bar=int(section.start_bar),
                end_bar=int(section.end_bar),
                anchor_strength=anchor,
                motif_mode=section.motif_mode,
                rhythm_mode=rhythm_mode,
                density_scale=_clamp(section.density * (1.0 - silence_ratio)),
                event_activity=event_activity,
                kick_activity=kick_activity,
                snare_activity=snare_activity,
                high_activity=high_activity,
                melody_activity=melody_activity,
                texture_activity=texture_activity,
                ambience_activity=ambience_activity,
                space_intent=space,
                silence_ratio=silence_ratio,
                transition_in=transition_in,
                transition_out=transition_out,
                variation_budget=_clamp(0.15 + instability * 0.70),
                memory_tag=f"{section.name.lower()}:{section.motif_mode}",
            )
        )
    return tuple(result)
