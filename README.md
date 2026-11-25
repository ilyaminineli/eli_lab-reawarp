# eli_lab-reawarp / 再変形

**A deterministic mathematical audio laboratory for IDM composition, broken rhythms, hybrid synthesis and offline sound design.**

Reawarp turns musical constraints and generative systems into structured compositions, independently editable stems and portable project archives. It is an offline-first instrument and production laboratory, not a general-purpose DAW.

## What it does

- **Compose:** deterministic structures up to 180 seconds, section and phrase planning, persistent motifs, role relationships, asymmetry, transitions and negative space.
- **Generate sound:** subtractive and alternative melodic voices, dedicated percussion synthesis, sample-driven and hybrid drum architectures, ambience and transformed break material.
- **Transform breaks:** transient detection, slicing, rearrangement, stutter, dropout, reverse, gate, pitch/time operations, granular resynthesis and spectral freeze. Source recordings are not overwritten.
- **Manage samples:** local SQLite sample/stem library, descriptors, similarity search, collections, sample banks and project genealogy.
- **Work with a musical Score:** rational-beat events, tempo/meter maps, tuning-aware pitch, typed automation, Score-first event rendering and optional MIDI 1.0 interchange.
- **Produce non-destructively:** role-aware per-stem inserts, shared SPACE/ECHO returns, beat automation, routing meters, tail handling, matched-level audition and project-aware FX variations.
- **Review variations:** deterministic candidate batches, blind A/B, difference inspection, listening sets, review notes and candidate ancestry.
- **Export complete projects:** routed master, dry stems, returns, Score/events, MIDI, routing/automation, source assets and integrity manifest in a ZIP handoff.

## Architecture

`GenerationConfig → Composition / Role Plan → Score → Dry Stems → FX Routing + Automation → Project Archive`

The Score is canonical for event-backed generation: `ReawarpEngine.generate()` plans rational-beat events before rendering, and ScoreRenderer resolves them to sample frames. Whole-field texture and ambience remain specialist render passes represented by Score markers. Dry stems and original sample assets are not overwritten by downstream processing.

The mixer intentionally uses a bounded role-aware model: per-stem serial inserts and two shared wet-only returns (SPACE and ECHO). It is not an arbitrary routing graph or a live plug-in host.

## Install

Python 3.10 or newer is required. Create a virtual environment:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate
python -m pip install --upgrade pip
```

Minimal NumPy core:

```bash
python -m pip install -e .
```

Desktop, audio I/O and MIDI:

```bash
python -m pip install -e ".[audio,m4,midi]"
```

Development and tests:

```bash
python -m pip install -e ".[dev,audio,m4,midi]"
python -m pytest -q
```

Install optional capabilities only when needed:

```bash
python -m pip install -e ".[pyo]"       # Pyo offline FX rendering
python -m pip install -e ".[analysis]"  # librosa analysis adapters
python -m pip install -e ".[theory]"    # music21 symbolic theory
python -m pip install -e ".[soundfont]" # FluidSynth / SF2 synthesis
python -m pip install -e ".[pippi]"     # experimental pre-release integration
```

Pyo, FluidSynth and selected research integrations may require platform-specific native runtimes. `requirements.txt` is an expanded developer/research inventory; prefer the curated extras in `pyproject.toml`. See [Dependency ecosystem](docs/DEPENDENCY_ECOSYSTEM.md).

## Generate a composition

```bash
reawarp --duration 12 --bpm 137 --complexity 0.68 --seed 211 --output output/demo
```

A long-form 180-second study:

```bash
reawarp --duration 180 --structure autechre_like --flow mix \
  --pattern-family asymmetric_7 --pattern-relationship shadow \
  --pattern-follow-structure --synth-palette subtractive \
  --percussion-synthesis minimal --complexity 0.42 --seed 20261124 \
  --output output/three-minute-study
```

Use the same seed and configuration to reproduce a composition within the documented application/environment contract. Generated output includes master audio, aligned stems, project/event metadata and canonical `score.json`.

## Desktop production workflow

Install the `m4` extra and launch:

```bash
reawarp-gui
# or
python -m reawarp.ui
```

The workspace groups composition, production and assets. The Stem Mixer renders role-aware inserts and shared returns in a cancellable background job; its processed channel/master previews and export use the same routing snapshot. Install Pyo to render actual effects:

```bash
python -m pip install -e ".[pyo]"
```

FX Lab can load an active project's dry channel, audition an editable chain, and assign it as that channel's insert in Stem Mixer. Stem Mixer can pre-render the complete routing and generate deterministic effect alternatives from project context and a variation seed; audition a candidate and apply its routing to the current project. When Pyo is unavailable, the app reports that the preview is dry rather than claiming an effect render succeeded.

Standalone FX commands:

```bash
reawarp-fx input.wav output_fx.wav --preset tape_echo --wet 0.70 --tail 2.0
reawarp-fx input.wav output_custom.wav --chain-json my_chain.json
reawarp-routing output/demo --output output/routed
```

## Score and MIDI

```python
from reawarp import GenerationConfig, ReawarpEngine

project = ReawarpEngine().generate(
    GenerationConfig(bpm=137, duration=12.0, seed=211, complexity=0.68)
)
score = project.to_score()
score.save("output/demo/score.json")
score.export_midi("output/demo.mid")  # requires the midi extra
```

MIDI import/export:

```bash
reawarp-midi-import input.mid --output imported-score.json
reawarp-midi-export imported-score.json --output exported.mid --ppq 960
```

MIDI 1.0 uses integer semitone notes and finite tick resolution. Reawarp preserves exact pitch/event context in its Score and escaped text metadata for Reawarp-to-Reawarp interchange. Other MIDI software may ignore that metadata.

## Complete project package

The desktop **EXPORT STEMS + MASTER…** action now writes a ZIP handoff. It includes:

- routed `master.wav`, original aligned dry `stems/` and rendered `returns/`;
- canonical `score.json`, compatibility `events.json`, combined `midi/score.mid` and separate `midi/voices/*.mid`;
- `project.json`, `fx_routing.json`, `fx_automation.json`, `mix.json` and package instructions;
- copied source samples under `assets/` by default, plus manifest and SHA-256 file inventory;
- variation candidates and listening report when they are part of the project session.

The extracted project folder can be reopened with Reawarp. MIDI 1.0 playback is a lossy pitch/timing projection; the Score remains authoritative. The Python packaging service is `reawarp.export.project_archive.export_project_package`.

New project exports embed referenced samples by default. The explicit `asset_policy="reference"` mode records external paths and hashes instead. Missing/changed assets are reported rather than silently substituted.

## Performance and validation

Run the target-Windows 30/180-second 48 kHz benchmark:

```powershell
python scripts/benchmark_m25.py --durations 30 180 --sample-rate 48000 --output output/m25-target-windows.json
```

For budget-gated acceptance, add agreed `--max-rss-gb` and `--max-wall-seconds` limits. CI runs the full regression suite on Linux/Python 3.10–3.12 and Windows/Python 3.11, plus CLI, routing, M24 and M25 smoke checks. A short smoke run is not a substitute for target-machine performance or human listening.

## Development

```bash
python -m pip install -e ".[dev,audio,m4,midi]"
python -m compileall -q src/reawarp
python -m pytest -q
```

Benchmark and matched-listening tools live in `scripts/`: generation (M14), sound objects (M21), independent DSP research modules (M24.1–M24.4) and project archive/reopen (M25).

## Documentation

- [Milestone history and current status](docs/MILESTONES.md) — the single milestone/roadmap source.
- [Implementation notes](docs/IMPLEMENTATION_NOTES.md) — architecture and engineering conventions.
- [Dependency ecosystem](docs/DEPENDENCY_ECOSYSTEM.md) — optional dependencies, platform constraints and licensing.
- [Sample banks and hybrid composition](docs/SAMPLE_BANKS_HYBRID_COMPOSITION.md) — role banks, switching and hybrid percussion.
- [IRO integration](docs/IRO_INTEGRATION.md) — shared manifests, source identity and missing-asset policy.
- [IDM field guide](docs/guides/IDM_Field_Guide_for_Composers_Producers_and_Programmers.md).
- [Composition atlas](docs/guides/IDM_Composition_Atlas_Patterns_Phrases_and_Track_Structures.md).
- [Sound-design architecture](docs/guides/IDM_Sound_Design_Synthesis_and_Hybrid_Sound_Architecture.md).
- [Advanced composition appendix](docs/guides/IDM_Advanced_Composition_and_Generation_Appendix.md).

The IRO manifests and indexes are present in this repository, but the IRO WAV payloads are currently absent under `samples/Iro`; those manifest entries are metadata-only until the audio files are supplied.
