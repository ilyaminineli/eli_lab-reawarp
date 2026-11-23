# Reawarp implementation notes

## Architecture

1. Mathematics produces normalized control data, event indices, pitch values, and trajectories. It does not render audio.
2. Generators translate mathematical data into musical events with roles, timing, velocity, and duration.
3. Synthesis turns events into audio buffers. The renderer is independent of GUI code and imported sample libraries.
4. Break transformations operate on copied NumPy buffers and never write back to source samples.
5. Core coordinates deterministic random streams, configuration, and project assembly.
6. Export writes synchronized stems and machine-readable provenance.
7. The GUI and optional integrations are clients of the engine, not owners of its state.

## Deterministic stream policy

Never consume a single global RNG for the entire project. Derive one named NumPy generator from the root seed for each lane, profile selector, and transformation chain. Stem-only regeneration must render the selected stream and preserve all unrelated buffers byte-for-byte.

## Implemented foundation

- Synthesized kick, snare, hi-hat, and synthetic break.
- Thirteen kick, six snare, and six hi-hat sound profiles with independently configured oscillator/noise and envelope parameters.
- Lissajous / logistic-derived FM melody.
- Custom PCM WAV sample overlays.
- Deterministic transforms with transient detection, auto-slicing, rearrangement, stutter, dropout, reverse, gate, pitch shift, phase-vocoder time stretch, granular resynthesis, and spectral freeze.
- Stereo 24-bit PCM stem export, CLI, Python library API, project/event JSON.
- Unit tests for synthesis profiles, determinism, transforms, sample integrity, and export.

## Dependency boundaries

The core is NumPy-only. SoundFile and SciPy remain optional audio helpers. SoundDevice, librosa, Mido, and music21 are separately installable extras. Pyo, Pippi, FluidSynth, Csound, SuperCollider, Essentia, aubio, Xenharmlib, and dataset toolkits are adapters or research candidates; none is required to install or use the core engine.

Optional libraries must not replace Reawarp's event model, deterministic random-stream policy, or NumPy reference renderer. Review platform support, native-runtime requirements, and redistribution licenses before bundling any dependency into a desktop build.

## Next milestones

- M3: implemented break-transformation and advanced percussion-profile foundation; see docs/M3.md.
- M4: implemented PySide6 Generator, Break Lab, and Stem Mixer workspaces; SoundDevice audition, waveform/spectrogram visualization, background rendering, faders/pan/mute/solo, and stem regeneration. See docs/M4.md.
- M5: Mido MIDI import/export and microtonal pitch infrastructure.
- M6: searchable stem library, similarity features, collections, and project interchange.
- M7: advanced mathematical composition, optional external synthesis backends, and experimental data-driven generators.

## Audio engineering notes

- Render offline first; do not tie the render graph to an audio callback.
- Use 32-bit floating point internally and leave headroom before export.
- Keep individual stems time-aligned with identical frame counts.
- Apply peak attenuation per stem, not across all stems, so regenerating one layer cannot alter other lanes.
- Store the generator algorithm version and complete configuration with each project.

See [DEPENDENCY_ECOSYSTEM.md](DEPENDENCY_ECOSYSTEM.md) for the role, adoption status, platform notes, and licensing considerations for the libraries and datasets from the architecture review.
