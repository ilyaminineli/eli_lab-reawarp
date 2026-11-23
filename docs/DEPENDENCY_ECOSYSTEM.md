# Reawarp dependency and research ecosystem

This document records the role and adoption decision for every library and dataset discussed during the M3 architecture review. The list is a capability map, not a requirement to install everything.

## Architectural rule

Reawarp's own event model, deterministic random streams, mathematical generators, and NumPy offline renderer remain authoritative. External libraries may provide an adapter or optional backend, but they must not become mandatory just to generate a loop or export stems.

Before bundling any dependency in a desktop release, re-check the current supported Python versions, Windows wheels, native runtime requirements, and license of the exact release being shipped.

## 1. Synthesis and sound design

| Project | Intended role | Adoption decision |
|---|---|---|
| NumPy + custom Reawarp DSP | Deterministic reference renderer and offline stem engine | Core; required |
| SciPy | Optional signal-processing utilities and future filter/analysis helpers | Optional `audio` extra; never required by the core |
| Pyo | Real-time oscillators, filters, delays, modulation, granular work, MIDI/OSC | Candidate optional real-time backend; do not replace NumPy |
| Pippi | Experimental buffer, wavetable, window, and granular sound design | Research adapter; 2.x development line was considered experimental in the M3 notes |
| pyFluidSynth | SF2 SoundFont playback and pitched source material | Optional `soundfont` extra; native FluidSynth runtime is required |
| ctcsound / Csound | Offline physical modelling, resonators, and complex modulation | External backend candidate; Python bindings must match the installed Csound API, especially across the 6/7 API boundary |
| SuperCollider / sc3nb | Interactive synthesis graphs and sonification | External experimental backend; keep independent of the core runtime |

The first implementation should stay NumPy-first. Pyo is the most direct future path for real-time audition and synthesis; Pippi is the experimental sound-design path. FluidSynth is useful as a source instrument, not as the central renderer.

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

The installable extras in `pyproject.toml` are deliberately limited to adapters with a clear Python package boundary:

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
| `dev` | pytest, Ruff | Tests and development checks |

Pyo, Pippi, ctcsound, SuperCollider, Essentia, aubio, Xenharmlib, MusPy, and dataset repositories are not added as unconditional dependencies. Some require native software, have platform restrictions, are experimental, or have licensing implications that need a dedicated release review.

## 6. Licensing and release hygiene

The M3 research review identified licensing considerations for Pyo (LGPL-3.0-or-later), aubio (GPL-3.0-or-later), and Xenharmlib (GPL-3.0-or-later). These are not automatically incompatible with every use, but their distribution implications need deliberate review. The licenses of datasets and individual MIDI files must be checked separately; a repository-level license does not necessarily clear every embedded recording or transcription for redistribution.

No external project should be copied into Reawarp merely because it is useful. Prefer documented adapters, optional installation groups, source attribution, and reproducible version pins for release builds.

## 7. Implementation sequence

- **M3 — complete:** dependency-free break analysis/transformation and profile-based percussion synthesis.
- **M4 — implemented:** PySide6 Generator, Break Lab, and Stem Mixer workspaces, SoundDevice audition, waveform/spectrogram views, asynchronous rendering, and stem controls.
- **M5 — implemented:** universal score/event model, rational beat time, tempo/meter maps, automation lanes, tuning interface, project score conversion, and Mido MIDI 1.0 import/export.
- **M6 — next:** searchable sample/stem catalogue, metadata indexing, similarity features, collections, variation genealogy, and MusPy-based research utilities.
- **M7 — later:** optional Pyo/Pippi/Csound/SuperCollider backends, advanced mathematical composition, and curated dataset experiments.

The project should grow through small, testable adapters. Its identity remains in its mathematics, event model, and deterministic renderer.
