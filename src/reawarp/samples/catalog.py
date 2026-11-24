"""Discoverable sample material bundled with the Reawarp repository.

This is a lightweight file catalogue for the Generator. The SQLite SampleLibrary
remains the richer searchable/indexed library; this module only discovers the
audio already shipped in samples/ so those sources can participate in generation
without a manual file-browser round trip.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SAMPLE_SUFFIXES = {".wav", ".flac", ".aif", ".aiff", ".ogg"}
SAMPLE_ROOT = Path(__file__).resolve().parents[3] / "samples"

_ROLE_TOKENS = {
    "kick": ("kick", "bass_drum", "bassdrum", "_bd", "bd_"),
    "snare": ("snare", "clap", "rim"),
    "hat": ("hihat", "hi_hat", "hat", "cymbal", "ride", "crash"),
}

_PREFERRED_NAMES = {
    "kick": ("kick.wav",),
    "snare": ("dwb_snare_07.wav", "ah_clap_&_snare_hit_04.wav"),
    "hat": ("evn_04_hihat_02.wav", "13_cymbal1_606.wav"),
}


@dataclass(frozen=True, slots=True)
class BundledSample:
    path: Path
    role: str
    label: str
    relative_path: str

    def __str__(self) -> str:
        return self.label


def classify_sample_role(path: str | Path) -> str | None:
    """Infer a coarse percussion role from a filename and its sample subfolder."""
    source = Path(path)
    parts = [part.casefold() for part in source.parts]
    if any(part == "breaks" or part.startswith("breaks") for part in parts):
        return "break"
    stem = source.stem.casefold().replace("-", "_").replace(" ", "_")
    name = f"{stem}_{source.suffix.casefold()}"
    for role, tokens in _ROLE_TOKENS.items():
        if any(token in name for token in tokens):
            return role
    return None


def discover_bundled_samples(
    root: str | Path | None = None,
    *,
    role: str | None = None,
) -> list[BundledSample]:
    """Return bundled audio sources, optionally restricted to one drum role."""
    sample_root = Path(root).expanduser().resolve() if root is not None else SAMPLE_ROOT
    if not sample_root.is_dir():
        return []
    records: list[BundledSample] = []
    for path in sorted(sample_root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_SAMPLE_SUFFIXES:
            continue
        detected_role = classify_sample_role(path)
        if detected_role is None or detected_role == "break":
            continue
        if role is not None and detected_role != role:
            continue
        relative = path.relative_to(sample_root).as_posix()
        records.append(BundledSample(
            path=path,
            role=detected_role,
            label=f"{path.name}  ·  {path.parent.name}",
            relative_path=relative,
        ))
    return records


def default_sample_for_role(
    role: str,
    root: str | Path | None = None,
) -> BundledSample | None:
    """Choose a conservative bundled default while allowing user replacement."""
    choices = discover_bundled_samples(root, role=role)
    if not choices:
        return None
    preferred = [name.casefold() for name in _PREFERRED_NAMES.get(role, ())]
    by_name = {item.path.name.casefold(): item for item in choices}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return choices[0]


def sample_library_counts(root: str | Path | None = None) -> dict[str, int]:
    """Return discovered sample counts by supported drum role."""
    return {
        role: len(discover_bundled_samples(root, role=role))
        for role in ("kick", "snare", "hat")
    }
