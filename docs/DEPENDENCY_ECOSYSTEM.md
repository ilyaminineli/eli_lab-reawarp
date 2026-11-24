# Reawarp dependency and research ecosystem

This document records the role and adoption decision for the libraries and tools discussed in the architecture and sound-design guides. `requirements.txt` is the full dependency inventory; `pyproject.toml` extras remain the supported install groups. The inventory is a capability map, not a requirement to install everything.

## Architectural rule

Reawarp's own event model, deterministic random streams, mathematical generators, and NumPy offline renderer remain authoritative. External libraries may provide an adapter or optional backend, but they must not become mandatory just to generate a loop or export stems.

Before bundling any dependency in a desktop release, re-check the current supported Python versions, Windows wheels, native runtime requirements, and license of the exact release being shipped.

## 1. Synthesis and sound design

| Project | Intended role | Adoption decision |
|---|---|---|
| NumPy + custom Reawarp DSP | Deterministic reference renderer and offline stem engine | Core; required |
| SciPy | Optional signal-processing utilities and future filter/analysis helpers | Optional `audio` extra; never required by the core |
| Pyo | Real-time oscillators, filters, delays, modulation, granular work, MIDI/OSC | Candidate optional real-time backend; do not replace NumPy |
| Pippi | Experimental buffer, wavetable, window, and granular sound design | Optional `research` extra; evaluate 2.x API stability before release use |
| pyFluidSynth | SF2 SoundFont playback and pitched source material | Optional `soundfont` extra; native FluidSynth runtime is required |
| ctcsound / Csound | Offline physical modelling, resonators, and complex modulation | External backend candidate; Python bindings must match the installed Csound API, especially across the 6/7 API boundary |
| SuperCollider / sc3nb | Interactive synthesis graphs and sonification | External experimental backend; keep independent of the core runtime |

The implementation remains NumPy-first. M9 adds a genuine subtractive voice path and a transient/body/tail percussion renderer that does not call the melodic FM engine. The `minimal` percussion mode is the default; `extended` adds resonant detail; `samples` retains the existing profile-based drum path. The M8 additive, inharmonic, modal, granular and scanned reference voices remain available as explicit lead architectures, while Pyo and Pippi remain optional future backends. FluidSynth is useful as a source instrument, not as the central renderer.

### M8 sound-design library decisions

| Library / technology | Intended M8 role | Adoption |
|---|---|---|
| NumPy FFT and oscillator bank | Reference additive, inharmonic, scanned and spectral utilities | Core; deterministic |
| SciPy | Higher-order filters, resampling, convolution helpers and future oversampled nonlinear DSP | Optional `audio` / `synthesis` extra |
| Pippi | Buffer manipulation, wavetable preparation, granular and windowing experiments | Optional `research` extra; isolate behind adapter and test on Windows |
| Csound / ctcsound | Modal, physical-model, resonator and complex modulation backends | Candidate external backend; requires matching native runtime |
| SuperCollider / sc3nb | Synthesis graph prototyping, feedback networks and spectral-delay research | External experimental backend |
| Pyo | Low-latency modulation, filters, granular playback and real-time preview | Optional future backend; not used by offline renderer |

The sound-design manual also suggests convolution, spectral delay, feedback systems, oversampling, multiband processing and sample-to-wavetable conversion. These should be implemented as small, independently tested DSP modules or optional adapters, not as heavyweight mandatory dependencies. The current `synthesis` extra exposes SciPy only; `research` is for experimental library evaluation, not required generation.

## 2. Audio I/O, playback, and analysis

| Library | Intended role | Adoption decision |
|---|---|---|
| SoundFile | Reading and writing audio formats through libsndfile | Optional `audio` extra; standard PCM WAV reading remains available without it |
| SoundDevice | NumPy-based playback, recording, and output-device selection | Optional `playback` extra; use for M4 audition transport |
| librosa | Spectral centroid/bandwidth/rolloff, contrast, flatness, chroma, onset strength, beat tracking, HPSS, and feature extraction | Optional `analysis` extra; keep version/platform compatibility separate from core installation |
| Essentia | Advanced MIR descriptors, similarity, fingerprinting, beat and melody analysis | Later candidate; the M3 review identified a Windows Python-binding limitation despite the C++ library's broader portability |
| aubio | Lightweight onset, pitch, tempo, and streaming analysis | Optional adapter candidate; review its GPL-3.0-or-later license before distribution |
| PyDub | Convenience conversion and high-level file manipulation | Low priority; keep sample slicing frame-accurate in Reawarp and use SoundFile or optional FFmpeg support for conversion |

SoundDevice and SoundFile are the preferred I/O pair. librosa can provide a second analysis implementation against which Reawarp's own transient and spectral measurements can be compared. None of these libraries should be imported at module load time by the minimal core.

## 3. MIDI, symbolic music, and tuning

| Library | Intended role | Adoption decision |
|---|---|---|
| Mido | MIDI messages, files, ports, tempo, and control events | Primary MIDI abstraction; optional `midi` extra |
| MIDIUtil | Convenient MIDI file writing | Not selected; Mido provides the broader import/export and port abstraction |
| music21 | Scales, intervals, chords, post-tonal analysis, notation, symbolic composition | Optional `theory` extra; keep out of real-time rendering |
| Xenharmlib | Just intonation, prime-limit tunings, regular temperaments, Bohlen–Pierce, microtonal scales | Important future tuning adapter; separate the tuning interface from any GPL-licensed implementation |
| MusPy | MIDI/MusicXML/ABC symbolic representations, dataset preparation, and model evaluation | Optional research/dataset tooling, not a runtime dependency |

### Shared event model

Before adding MIDI, all generators should emit one universal event representation. Its common fields should cover:

- Lane and instrument identity.
- Absolute time and duration.
- MIDI note where applicable, plus exact frequency in Hz.
- Velocity, pan, and modulation/control values.
- Tuning reference and pitch-system identity.
- Generator family, seed stream, and provenance.

The exact-frequency field is important: a MIDI note number alone cannot represent arbitrary just-intonation or microtonal pitch. Mido should serialize the interoperable subset; the richer Reawarp event remains the source of truth.

### Proposed symbolic pipeline

Mathematical generators → universal musical events → optional music21 theory analysis → optional Xenharmlib tuning adapter → Mido MIDI serialization → Reawarp synthesis and stem rendering.

MIDIUtil is unnecessary if Mido is used as the shared MIDI layer.

## 4. Algorithmic composition and reference projects

| Project | What to study | Adoption decision |
|---|---|---|
| athenaCL | Parameter objects, stochastic composition, cellular automata, and modular multi-paradigm generator architecture | Study its concepts; do not make the application or its historical CLI a dependency |
| HSMusic | Large MIDI corpus, metadata, and symbolic-sequence experiments | Research dataset only; investigate the rights and provenance of individual source files before reuse or redistribution |
| GiantMIDI-Piano | Classical piano MIDI transcriptions for testing note/melody extraction and symbolic analysis | Benchmark dataset, not a representative IDM corpus; retain CC BY 4.0 attribution and its accompanying disclaimer |

The M3 research notes recorded HSMusic as a collection of approximately 130,943 MIDI files and GiantMIDI-Piano as approximately 10,855 transcriptions. Those counts describe the reviewed repositories at that time and should be rechecked before a dataset workflow is built around them.

## 5. Optional installation groups

The installable extras in `pyproject.toml` are deliberately limited to adapters with a clear Python package boundary. The root `requirements.txt` lists implemented packages plus commented planned packages from this document and the curated audio ecosystem; commented lines are inventory entries, not packages installed by `pip install -r requirements.txt`.

| Extra | Packages | Role |
|---|---|---|
| `audio` | SoundFile, SciPy | File I/O and optional signal-processing helpers |
| `playback` | SoundDevice | Playback/recording for M4 |
| `analysis` | librosa | Offline feature and onset analysis |
| `midi` | Mido | MIDI import/export |
| `theory` | music21 | Symbolic music-theory analysis |
| `soundfont` | pyFluidSynth | Optional SF2 source synthesis |
| `ui` | PySide6, pyqtgraph 0.14.x | Desktop interface and visual analysis |
| `m4` | PySide6, pyqtgraph 0.14.x, SoundDevice | Combined desktop and playback installation |
| `synthesis` | SciPy, Pedalboard | Optional higher-level filters, resampling and effects research |\n| `research` | Pippi, librosa | Experimental buffer synthesis and feature research |\n| `dev` | pytest, Ruff | Development checks; the repository may temporarily omit a local test suite during milestone transitions |

Pyo, Pippi, ctcsound, SuperCollider, Essentia, aubio, Xenharmlib, MusPy, and dataset repositories are not added as unconditional dependencies. Some require native software, have platform restrictions, are experimental, or have licensing implications that need a dedicated release review.

## 6. Licensing and release hygiene

The M3 research review identified licensing considerations for Pyo (LGPL-3.0-or-later), aubio (GPL-3.0-or-later), and Xenharmlib (GPL-3.0-or-later). These are not automatically incompatible with every use, but their distribution implications need deliberate review. The licenses of datasets and individual MIDI files must be checked separately; a repository-level license does not necessarily clear every embedded recording or transcription for redistribution.

No external project should be copied into Reawarp merely because it is useful. Prefer documented adapters, optional installation groups, source attribution, and reproducible version pins for release builds.

## 7. Implementation sequence

- **M3 — complete:** dependency-free break analysis/transformation and profile-based percussion synthesis.
- **M4 — implemented:** PySide6 Generator, Break Lab, and Stem Mixer workspaces, SoundDevice audition, waveform/spectrogram views, asynchronous rendering, and stem controls.
- **M5 — implemented:** universal score/event model, rational beat time, tempo/meter maps, automation lanes, tuning interface, project score conversion, and Mido MIDI 1.0 import/export.
- **M6 — next:** searchable sample/stem catalogue, metadata indexing, similarity features, collections, variation genealogy, and MusPy-based research utilities.
- **M7 — implemented:** 45-second composition workbench, section-aware motifs, layer regeneration, workspaces and searchable library.
- **M8 — current:** up-to-three-minute formal presets and flow modes, pattern relationship/motif transformation utilities, and selectable native synthesis palettes.
- **M9 — candidates:** dedicated modules for oversampled waveshaping, spectral delay, convolution/cross-synthesis, feedback-delay-network reverb and sample-to-wavetable instruments; add optional Csound/Pyo/Pippi adapters only behind isolated interfaces.

The project should grow through small, testable adapters. Its identity remains in its mathematics, event model, and deterministic renderer.
