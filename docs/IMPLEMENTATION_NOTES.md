# Reawarp implementation notes

## Architecture

1. Mathematics produces normalized control data, event indices, pitch values, and trajectories. It does not render audio.
2. Generators translate mathematical data into musical events with roles, timing, velocity, and duration.
3. The offline NumPy engine synthesizes aligned float32 stem buffers from the event/configuration model.
4. Break transformations operate on copied buffers and never write back to source samples.
5. Named random streams make generation and stem-only regeneration reproducible.
6. Export writes synchronized stems and machine-readable project/event/score provenance.
7. The GUI and optional processing integrations are clients of the engine, not owners of its state.

## Deterministic stream policy

Never consume a single global RNG for the entire project. Derive one named NumPy generator from the root seed for each lane, profile selector, and transformation chain. Stem-only regeneration must render the selected stream and preserve all unrelated buffers byte-for-byte.

## Current implementation

- Independent mathematical rhythm and melody generators with formal section planning up to 180 seconds.
- Role-driven lead synthesis, separate generated percussion, and a dedicated ambience stem.
- Sample overlays and a frame-accurate break analysis/transformation pipeline.
- Universal score and event model, rational time, tempo/meter maps, tuning interface, and optional Mido MIDI 1.0 import/export.
- Local SQLite sample/stem library with audio descriptors, search, similarity ranking, named collections, and variation genealogy.
- PySide6 workspaces for Generator, Break Lab, Stem Mixer, Library, and FX Lab.
- Optional Pyo offline effect processing behind an isolated adapter. The base generator and NumPy reference renderer do not import Pyo.
- Portable 16-bit/24-bit PCM WAV output, project JSON, event JSON, and score JSON.

## Dependency boundaries

The core requirement is NumPy. SoundFile, SciPy, PySide6, pyqtgraph, SoundDevice, librosa, Mido, music21, FluidSynth bindings, and Pyo are used only through their documented optional features or extras. Pippi remains a separately pinned pre-release research option; it is not required for the Windows desktop. Pedalboard stays inactive pending a distribution/licensing decision.

Optional libraries must not replace Reawarp's event model, deterministic random-stream policy, or NumPy reference renderer. Review Python/platform wheels, native-runtime requirements, and redistribution licenses before bundling any dependency into a desktop release.

## Validation policy

The repository currently uses compile, CLI, library, and desktop-import smoke checks in GitHub Actions. There is no active unit-test suite in the repository; do not recreate a test suite as part of routine cleanup or milestones without an explicit request.

## Milestone status

- **M3–M5:** break transformation, desktop instrument, universal score model, tuning interface, and MIDI interchange.
- **M6:** searchable sample/stem library, descriptors, collections, and variation genealogy.
- **M7–M8:** formal composition planning, section-aware patterns, motif transformations, long-form structure presets, and selectable synthesis architectures.
- **M9:** restrained subtractive synthesis, dedicated generated drum voices, sparser defaults, monochrome UI, and dependency inventory.
- **M10:** optional Pyo offline FX backend, four starter chains, FX Lab workspace, dry/processed comparison, and `reawarp-fx` CLI.
- **M11 — in progress:** editable ordered effect chains, stage-level parameter controls, and portable chain JSON.

The next architectural extension after M11 is role-aware per-stem effect routing. Keep it separate from the current master-level mixer and validate that effect rendering never mutates or regenerates unrelated stems.

## Audio engineering notes

- Render offline first; do not tie the render graph to an audio callback.
- Use 32-bit floating point internally and leave headroom before export.
- Keep individual stems time-aligned with identical frame counts.
- Apply attenuation locally and avoid changing unrelated lanes during stem regeneration.
- Preserve a dry reference and level-match bypass comparisons when processing.
- Store the generator algorithm version and complete configuration with each project.

See [DEPENDENCY_ECOSYSTEM.md](DEPENDENCY_ECOSYSTEM.md) for dependency roles, adoption status, platform notes, and licensing considerations.
