# Reawarp implementation notes

## Architecture

1. Mathematics produces normalized control data, event indices, pitch values, and trajectories. It does not render audio.
2. Generators translate mathematical data into musical events with roles, timing, velocity, and duration.
3. Synthesis turns events into audio buffers. It is independent of GUI code and imported sample libraries.
4. Core coordinates deterministic random streams, configuration, and project assembly.
5. Export writes synchronized stems and machine-readable provenance.
6. The GUI will be a client of the engine, not its owner.

## Deterministic stream policy

Never consume a single global RNG for the entire project. Derive one named NumPy generator from the root seed for each lane or generator. Stem-only regeneration must render the selected stream and preserve all unrelated buffers byte-for-byte.

## First implementation scope

- Synthesized kick, snare, hi-hat, and synthetic break.
- Lissajous / logistic-derived FM melody.
- Noise texture layer.
- Custom PCM WAV sample overlays.
- Stereo 24-bit PCM stem export and project/event JSON.
- CLI and Python library API.

## Next milestones

- Expand mathematics: prime-ratio pitch systems, cellular automata, Markov motif walker, geometric event mapping.
- Add break slicing, transient detection, reverse/retrigger, time stretch, spectral processing, and granular synthesis.
- Build PySide6 UI, pyqtgraph visualizations, audition transport, and per-stem regeneration controls.
- Add MIDI export, presets, batch rendering, and project version migration.
- Build searchable stem library, similarity features, collections, and project interchange.

## Audio engineering notes

- Render offline first; do not tie the render graph to an audio callback.
- Use 32-bit floating point internally and leave headroom before export.
- Keep individual stems time-aligned with identical frame counts.
- Apply peak attenuation per stem, not across all stems, so regenerating one layer cannot alter other stems.
- Store the generator algorithm version and complete configuration with each project.
