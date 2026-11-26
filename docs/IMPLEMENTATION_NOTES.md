# Reawarp implementation notes

These notes describe enduring code and engineering contracts. Milestone scope and status live in [MILESTONES.md](MILESTONES.md).

## Architecture boundaries

1. **Composition planning** creates deterministic sections, motifs, role relationships, sample choices and symbolic Score events. It does not own device playback.
2. **The Score** is canonical for event-backed scheduling. Rational beat positions remain exact until RenderTimeline resolves them to frames.
3. **ScoreRenderer** schedules discrete events and calls production voice adapters. Noise texture and ambience remain specialist whole-field renders documented by Score markers.
4. **Dry stem ownership** remains with the generated project. Transforms, inserts, routing, variations and audition processors work on copies and never rewrite source assets.
5. **Production routing** uses per-stem serial inserts and two wet-only shared returns (SPACE/ECHO). Keep the graph explicit and bounded; do not silently introduce arbitrary feedback or plug-in routing.
6. **Playback** consumes completed buffers only. Audio callbacks must not synthesize, allocate large buffers, access disk, or call GUI code.
7. **Project persistence and delivery export are separate contracts.** Reawarp project archives retain configuration, Score/events, external-asset policy, routing and provenance for reopenability. The desktop delivery export is intentionally smaller: a normal folder with README.md, routed master.wav, aligned dry stems/ and combined/per-voice MIDI. It never copies source samples or creates a ZIP and is not a restorable project archive.

## Determinism

- Derive generators from stable named streams and explicit seeds. Do not use a project-wide global RNG for unrelated roles.
- Stem-only regeneration must preserve unrelated stems bit-identically where the contract promises invariance.
- Variation candidates derive seeds from frozen base identity, request and candidate index. Store the request and lineage needed to reproduce a candidate.
- Do not use Python's process-randomised `hash()` to derive musical decisions.
- Define the reproducibility boundary: same code/environment is stronger than cross-platform floating-point bit identity.

## Audio and signal contracts

- Use float32 working audio; validate finite mono/stereo data and consistent frame alignment.
- Preserve dry references and source arrays. Every destructive-looking transform returns a new buffer.
- Keep gain laws, wet/dry blends, pre/post insert/fader taps, pan, mute/solo gates, tail extension and master peak protection explicit.
- Do not normalise source stems or silently change a processor's output gain.
- Report peak, RMS, headroom, latency/alignment and tails where meaningful. Metrics are diagnostic, not artistic rankings.
- Match levels only on audition copies; production and exported buffers remain unchanged.

## Score, MIDI and schemas

- Keep Score time in rational beats until frame placement.
- Score schema, project/events schemas and all user-authored routing/control documents are versioned and validated.
- MIDI 1.0 is a compatibility projection. Fractional pitch and some exact event/provenance values remain Score-specific; escaped Reawarp metadata supports round trips through compatible importers.
- Unknown schema versions fail explicitly. Migrations are additive and in-memory unless a deliberate export/save is requested.

Current compatibility snapshot:

| Data | Version |
| --- | ---: |
| Project | 1 |
| Project manifest | 1 |
| Events | 1 |
| Score | 1 |
| FX routing | 3 (v1/v2 migrate) |
| FX automation | 1 |
| Sound Object | 1 |
| Variation candidate | 1 |

See the compatibility fixture at `tests/fixtures/m25/legacy_contracts_v1.json`.

## Delivery export contract

The desktop **EXPORT MASTER + STEMS + MIDI** action is a delivery operation, not a project archive operation.

- The export service receives an immutable project snapshot and the completed routed master buffer.
- FX pre-render is automatically completed before delivery begins. If it fails, the retained dry fallback may still be exported, but README.md must say that the master is dry fallback.
- The delivery folder contains only README.md, master.wav, stems/*.wav, midi/score.mid and midi/voices/*.mid (the MIDI directory is omitted only when MIDI is explicitly disabled).
- master.wav is the final routed mix, including current mixer settings and successful insert/return processing.
- stems/*.wav are the original aligned dry generation stems. They are not overwritten by inserts or shared returns.
- Do not include source samples, sample banks, project.json, score.json, events.json, FX JSON, returns, manifests, candidate caches, or a ZIP.
- The folder is not a restorable Reawarp project. Original project/source assets remain managed separately.
- Write into a sibling temporary directory and rename into a new destination only after every file is complete. Never overwrite a non-empty existing destination; cancellation must leave no partial delivery folder.
- The package README is part of the deliverable and must report title, tempo, duration, sample rate, bit depth, channels, seed, structure, FX render state, stem semantics and MIDI 1.0 limitations.

The complete project archive APIs remain distinct and may continue to support project portability where that is explicitly requested.

## Optional dependencies

NumPy is the core requirement. PySide6/pyqtgraph and SoundDevice are used by the desktop; Mido supports MIDI; SoundFile/SciPy/librosa and music21 are optional adapters; Pyo is only required for actual offline FX Lab/Mixer rendering. Native/runtime constraints and licence notes belong in [DEPENDENCY_ECOSYSTEM.md](DEPENDENCY_ECOSYSTEM.md).

Keep optional/native libraries lazy-loaded and out of the normal generation import path. Review Python wheel support, external runtimes, redistribution and licence before bundling any new dependency.

## Validation

The maintained pytest suite covers deterministic streams, planning, Score timing/rendering/automation, transforms, samples, routing, signal diagnostics, project manifests, archive round trips, candidate lineage and offscreen UI navigation. GitHub Actions runs Linux Python 3.10–3.12 and Windows Python 3.11, with CLI and short benchmark smoke checks.

CI establishes software/data contracts. It does not establish target-machine performance, Pyo sound quality, low-volume/mono compatibility or artistic acceptance. Track those sign-offs in [MILESTONES.md](MILESTONES.md).

## Code organisation guidance

- Keep renderers/services independent of Qt.
- Keep GUI widgets thin; pass immutable snapshots to cancellable workers.
- Do not refactor the entire main window in one pass. Extract stable services at a time with regression coverage.
- Reuse the same completed routing snapshot for preview, stage audition and export.
- Cache by project revision plus all routing, automation, mixer and tempo inputs. Discard stale worker results.
- Keep long-lived project sources separate from temporary effect-variation render caches.

# Reawarp dependency and research ecosystem

This document records the role and adoption decision for the libraries and tools discussed in the architecture and sound-design guides. `requirements.txt` is the full dependency inventory; `pyproject.toml` extras remain the supported install groups. The inventory is a capability map, not a requirement to install everything.

## Architectural rule

Reawarp's own event model, deterministic random streams, mathematical generators, and NumPy offline renderer remain authoritative. External libraries may provide an adapter or optional backend, but they must not become mandatory just to generate a loop or export stems.

Before bundling any dependency in a desktop release, re-check the current supported Python versions, Windows wheels, native runtime requirements, and license of the exact release being shipped.

## 1. Synthesis and sound design

| Project | Intended role | Adoption decision |
| --- | --- | --- |
| NumPy + custom Reawarp DSP | Deterministic reference renderer and offline stem engine | Core; required |
| SciPy | Optional signal-processing utilities and future filter/analysis helpers | Optional `audio` extra; never required by the core |
| Pyo | Offline DSP chains for the M10–M11 FX Lab; filters, distortion, delay, reverb | Implemented as an optional `pyo` extra; lazy-loaded and isolated from NumPy generation |
| Pippi | Experimental buffer, wavetable, window, and granular sound design | Isolated optional `pippi` beta extra; Windows native build caveat |
| pyFluidSynth | SF2 SoundFont playback and pitched source material | Optional `soundfont` extra; native FluidSynth runtime is required |
| ctcsound / Csound | Offline physical modelling, resonators, and complex modulation | External backend candidate; Python bindings must match the installed Csound API, especially across the 6/7 API boundary |
| SuperCollider / sc3nb | Interactive synthesis graphs and sonification | External experimental backend; keep independent of the core runtime |

The implementation remains NumPy-first. M9 adds a genuine subtractive voice path and a transient/body/tail percussion renderer that does not call the melodic FM engine. The `minimal` percussion mode is the default; `extended` adds resonant detail; `samples` retains the existing profile-based drum path. The M8 additive, inharmonic, modal, granular, and scanned voices remain selectable lead architectures. M10 adds Pyo as an optional offline FX backend; Pippi remains a pre-release research dependency. FluidSynth is useful as a source instrument, not as the central renderer.

### M8 sound-design library decisions

| Library / technology | Intended M8 role | Adoption |
| --- | --- | --- |
| NumPy FFT and oscillator bank | Reference additive, inharmonic, scanned and spectral utilities | Core; deterministic |
| SciPy | Higher-order filters, resampling, convolution helpers and future oversampled nonlinear DSP | Optional `audio` / `synthesis` extra |
| Pippi | Buffer manipulation, wavetable preparation, granular and windowing experiments | Separate `pippi` pre-release extra; evaluate native build on Windows before use |
| Csound / ctcsound | Modal, physical-model, resonator and complex modulation backends | Candidate external backend; requires matching native runtime |
| SuperCollider / sc3nb | Synthesis graph prototyping, feedback networks and spectral-delay research | External experimental backend |
| Pyo | Offline effect processing and future live modulation/preview | Implemented for the M10 FX Lab through Pyo offline server mode; not used by the base renderer |

The sound-design manual also suggests convolution, spectral delay, feedback systems, oversampling, multiband processing and sample-to-wavetable conversion. These should be implemented as small, independently tested DSP modules or optional adapters, not as heavyweight mandatory dependencies. The `synthesis` extra exposes SciPy only; `pyo` is a separate optional extra for the FX Lab; `research` installs librosa only; and `pippi` is isolated in its own pre-release extra.

## 2. Audio I/O, playback, and analysis

| Library | Intended role | Adoption decision |
| --- | --- | --- |
| SoundFile | Reading and writing audio formats through libsndfile | Optional `audio` extra; standard PCM WAV reading remains available without it |
| SoundDevice | NumPy-based playback, recording, and output-device selection | Optional `playback` extra; use for M4 audition transport |
| librosa | Spectral centroid/bandwidth/rolloff, contrast, flatness, chroma, onset strength, beat tracking, HPSS, and feature extraction | Optional `analysis` extra; keep version/platform compatibility separate from core installation |
| Essentia | Advanced MIR descriptors, similarity, fingerprinting, beat and melody analysis | Later candidate; the M3 review identified a Windows Python-binding limitation despite the C++ library's broader portability |
| aubio | Lightweight onset, pitch, tempo, and streaming analysis | Optional adapter candidate; review its GPL-3.0-or-later license before distribution |
| PyDub | Convenience conversion and high-level file manipulation | Low priority; keep sample slicing frame-accurate in Reawarp and use SoundFile or optional FFmpeg support for conversion |

SoundDevice and SoundFile are the preferred I/O pair. librosa can provide a second analysis implementation against which Reawarp's own transient and spectral measurements can be compared. None of these libraries should be imported at module load time by the minimal core.

## 3. MIDI, symbolic music, and tuning

| Library | Intended role | Adoption decision |
| --- | --- | --- |
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
| --- | --- | --- |
| athenaCL | Parameter objects, stochastic composition, cellular automata, and modular multi-paradigm generator architecture | Study its concepts; do not make the application or its historical CLI a dependency |
| HSMusic | Large MIDI corpus, metadata, and symbolic-sequence experiments | Research dataset only; investigate the rights and provenance of individual source files before reuse or redistribution |
| GiantMIDI-Piano | Classical piano MIDI transcriptions for testing note/melody extraction and symbolic analysis | Benchmark dataset, not a representative IDM corpus; retain CC BY 4.0 attribution and its accompanying disclaimer |

The M3 research notes recorded HSMusic as a collection of approximately 130,943 MIDI files and GiantMIDI-Piano as approximately 10,855 transcriptions. Those counts describe the reviewed repositories at that time and should be rechecked before a dataset workflow is built around them.

## 5. Optional installation groups

The installable extras in `pyproject.toml` are deliberately limited to adapters with a clear Python package boundary. The root `requirements.txt` lists implemented packages plus commented planned packages from this document and the curated audio ecosystem; commented lines are inventory entries, not packages installed by `pip install -r requirements.txt`.

| Extra | Packages | Role |
| --- | --- | --- |
| `audio` | SoundFile, SciPy | File I/O and optional signal-processing helpers |
| `playback` | SoundDevice | Playback/recording for M4 |
| `analysis` | librosa | Offline feature and onset analysis |
| `midi` | Mido | MIDI import/export |
| `theory` | music21 | Symbolic music-theory analysis |
| `soundfont` | pyFluidSynth | Optional SF2 source synthesis |
| `ui` | PySide6, pyqtgraph 0.14.x | Desktop interface and visual analysis |
| `m4` | PySide6, pyqtgraph 0.14.x, SoundDevice | Combined desktop and playback installation |
| `synthesis` | SciPy | Optional higher-level filters and resampling |
| `pyo` | Pyo, SoundFile | Optional M10 offline FX Lab backend |
| `pippi` | Pippi 2.0.0b16 beta | Experimental buffer/wavetable research; Windows source-build caveat |
| `research` | librosa | Offline analysis research |
| `dev` | pytest, Ruff | Development and code-quality tools; no unit-test suite is currently checked in |

Pippi, ctcsound, SuperCollider, Essentia, aubio, Xenharmlib, MusPy, and dataset repositories are not added as unconditional dependencies. Pyo is optional, and the remaining candidates have native software, platform, experimental, or licensing constraints that require a dedicated release review.

## 6. Licensing and release hygiene

The M3 research review identified licensing considerations for Pyo (LGPL-3.0-or-later), aubio (GPL-3.0-or-later), and Xenharmlib (GPL-3.0-or-later). These are not automatically incompatible with every use, but their distribution implications need deliberate review. The licenses of datasets and individual MIDI files must be checked separately; a repository-level license does not necessarily clear every embedded recording or transcription for redistribution.

No external project should be copied into Reawarp merely because it is useful. Prefer documented adapters, optional installation groups, source attribution, and reproducible version pins for release builds.

## 7. Implemented feature boundary

The authoritative implementation history, current feature status, compatibility contracts and planned DSP sequence are maintained in [MILESTONES.md](MILESTONES.md). Do not use a dependency list or this ecosystem review as a second product roadmap.

The architectural rule remains: add small, explicit adapters around Reawarp's mathematical event model and NumPy reference renderer. Optional libraries must not become mandatory merely because they appear in the research inventory.

### M10 dependency decisions

Pyo is used only by the FX Lab and `reawarp-fx`. The adapter uses Pyo offline server mode with `SfPlayer`, filters, `Disto`, `Delay`, `Freeverb`, and `FreqShift`; it does not open an audio device for processing. Install with `python -m pip install -e ".[pyo]"`. The ordinary generator imports no Pyo modules.

Pippi is pinned to `pippi>=2.0.0b16,<2.1.0` in a separate `pippi` extra. This is an explicit pre-release pin, not part of the default install or the normal research extra. Its published 2.0.0b16 wheel targets Linux/CPython 3.14; Windows users may need to build from the source archive and prepare the native toolchain first.

Pedalboard remains commented in `requirements.txt` because its upstream distribution is GPL-3.0. Reawarp's MIT project should not activate it casually without a distribution and licensing decision.

# M24.5 — Sidechain and Envelope Routing

**Status:** Core implementation delivered; human listening and target-machine acceptance remain open  
**Routing schema:** v4 (v1–v3 migrate in memory)  
**Processing model:** Offline, deterministic, one-way detector-to-target gain control

## Musical use case

Let the actual transients of a kick, snare or break stem briefly make space in a sustained texture, ambience or melodic layer. The source may contain irregular timing and changing transient amplitude after break edits, regeneration or arrangement changes. A hand-authored automation curve can approximate a known passage, but it does not follow the actual rendered detector signal when those details change.

M24.5 therefore adds a narrowly scoped detector-to-gain relationship. It is not an arbitrary routing graph, a live compressor plug-in, or a new composition-generation control source.

## Route model

Each route declares:

- `route_id`, `source_stem` and a different `target_stem`.
- A linked-channel `peak` or `rms` detector.
- `threshold_db` in [-96, 0] dBFS and `ratio` in [1, 20].
- `max_reduction_db` in [0, 24] dB.
- `attack_ms` in [0.1, 500] ms and `release_ms` in [1, 5000] ms.
- `hysteresis_db` in [0, 24] dB.
- `control_rate_hz` in [50, 2000] Hz, never above the render sample rate.

The detector calculates a requested reduction from the signal level above threshold:

`reduction = min(max_reduction, max(0, detector_dB - threshold_dB) × (1 - 1 / ratio))`

The route smooths rising and falling reduction with separate attack/release time constants. Hysteresis uses a lower exit threshold to prevent threshold chatter. The control-rate points are interpolated to a sample-aligned gain envelope.

## Signal and safety contract

1. The detector reads the source's immutable dry stem **pre-insert and pre-fader**. Its linked-channel peak or RMS level is independent of fader gain and pan.
2. A source muted or excluded by solo does not trigger a sidechain. A muted/solo-excluded target is still handled by the normal mixer path.
3. The resulting gain envelope is applied to the target **before its insert and sends**, so both its direct path and downstream send taps follow the duck.
4. Source buffers, imported samples and stored dry stems are never modified.
5. Multiple routes targeting one stem combine by the strongest requested reduction (minimum linear gain), not by multiplying unrelated gain envelopes into unexpectedly deep attenuation.
6. Routes are bounded to 32 per routing document, each with a unique ID and distinct source/target. Invalid stems, values, sample-rate relationships and unknown fields fail validation.
7. Processing runs in the offline FX render pass. No detector, file access or DSP has been added to the audio callback. Cancellation is checked during envelope generation.
8. Schema v1, v2 and v3 routing documents remain loadable and are normalised to v4 with an empty `sidechains` list when no routes were authored.

## Example

Add this object to an FX routing document's top-level `sidechains` array:

```json
{
  "route_id": "kick_to_texture",
  "source_stem": "kick",
  "target_stem": "noise_texture",
  "detector_mode": "peak",
  "threshold_db": -24.0,
  "ratio": 12.0,
  "max_reduction_db": 9.0,
  "attack_ms": 2.0,
  "release_ms": 120.0,
  "hysteresis_db": 1.5,
  "control_rate_hz": 1000.0
}
```

The FX Routing editor exposes route selection, source/target, detector mode, threshold, ratio, reduction ceiling, attack, release and hysteresis. Use **ADD / UPDATE ROUTE** to save the selected relationship and **REMOVE ROUTE** to delete it. The route is included in the normal routing JSON save/load path and in render metadata.

## Automated acceptance coverage

`tests/test_m24_5_sidechain.py` verifies:

- Route identity, bounds, source/target separation and invalid-reference rejection.
- v3-to-v4 migration and preservation of authored sidechain settings.
- Deterministic peak detection, bounded gain reduction, attack/release behaviour and source immutability.
- RMS detector operation and silent-source no-trigger behaviour.
- Application before the target insert/send path, plus mute/solo gating.
- FX Routing editor add/remove interactions.

The renderer also records the route configuration, per-route maximum/mean reduction, active fraction, detector peak and the actual control rate in metadata.

## Acceptance still open

Automated tests prove routing semantics and deterministic signal behaviour, not artistic benefit. Listen to real kick/break-to-texture examples at matched loudness, including mono and low-volume playback. Confirm the chosen threshold, attack/release and maximum reduction are musically appropriate, and run the target-Windows 30/180-second performance benchmark before treating M24.5 as fully signed off.

# IRO ↔ Reawarp integration

**Status:** integration contract and first runtime adapters in progress.

IRO is a shared creative system across:

- `eli_lab-math-cover-generator`: release equations, feature fields, entity families, generated drum kits, sound-lab material and release-driven sound FX.
- `sonicpi_eli_lab`: performance grammar, sample maps, named project scenes, a shared master beat clock, feature-reactive state and role-specific live voices.
- `eli_lab-reawarp`: deterministic offline composition, sample-driven stems, break transformation, hybrid synthesis, FX routing and project provenance.

These repositories are related, but they are not interchangeable. Reawarp should consume the IRO assets and their metadata without treating a Sonic Pi live patch as a renderer specification or flattening the release into a generic drum-kit folder.

## Source identity

The current IRO release represented in `samples/Iro` is:

- Release title: `るもらをぬてふ`
- Release code: `24-73-41-25-23-57-54`
- Release seed: `211`

The IRO Track 01 project `けれあけ` has its own track seed `312`, tempo `113 BPM`, 392-beat main score and an 8-beat residue coda. These identities must remain separate in project metadata: release provenance is not a track seed.

## Reawarp's actual bundled sample library

The playable drum source library is the repository's `samples/` tree, not the `samples/Iro/` reference manifests. The Generator discovers local kick, snare/clap and hat/cymbal audio, lets the user choose one source per role, and supports custom replacements. The source engine combines these files with the existing Reawarp synthesis profiles using a shared percussion event score.

IRO remains relevant as a cross-repository design vocabulary: release identity, mathematical source families, articulation names, feature-driven sound design and Sonic Pi performance grammar can inform later source classification and synthesis models. They do not need to be copied into a second sample folder to participate in Reawarp.

## Current checkout limitation

The current Reawarp Git tree contains the IRO manifests, indexes and documentation, but **no `.wav` files anywhere under `samples/Iro`**. Therefore the IRO adapter currently exposes manifest/index entries as metadata-only records (`available=false`); it does not generate substitute audio or fall back to source paths. The drum index contains 96 generated kit entries, the eight entity manifests contain 48 entity variants, the sound-lab manifest lists 32 one-shots/four loops/four stems, and the sound-FX manifest lists 18 event variants/four loops. Their generated/source WAV payloads still need to be committed or supplied before Reawarp can audition or render them.

The Generator filters unavailable records out of its selectable sample controls. The Library can still search the metadata, display sonic identity/equations and report missing files. SHA-256 values in the index remain expected hashes; a hash cannot be verified until its file exists.

## Asset hierarchy already shipped in Reawarp

- `samples/Iro/entities/<family>/`: eight mathematical families—boundary_shard, coordinate_slip, interference_knot, phase_fracture, quantization_residue, ratio_orbit, recurrence_ghost, spectral_bloom.
- `samples/Iro/experimental-drum-kit-211/`: a 96-row generated instrument/articulation index plus immutable source indexes, drum manifest, drum map, MIDI note mapping and mutated-kit manifest.
- `samples/Iro/sound-lab-211/`: a manifest listing 32 one-shots, four loops, four stems and MIDI/MusicXML material.
- `samples/Iro/sound-fx-211/`: 18 release-driven event variants across mathematical families, four beat-aligned loops and an asset index.

The files are grouped by their generation identity and sonic family. Preserve that structure; do not rename all samples to generic role filenames.

## Manifest and integrity contract

The first Reawarp adapter reads the drum, sound-lab, sound-FX and entity manifests. Each asset retains:

- pack and relative path;
- role and mathematical/sonic family;
- articulation or variant;
- SHA-256 when the manifest supplies it;
- sample rate, duration and channel metadata when available;
- source feature index and seed when present;
- equations, synthesis approach and sonic identity as descriptive provenance.

Manifest paths must remain inside their pack root. Source audio is read-only. Hash mismatches and missing files must be visible; an asset must not be silently replaced by a similarly named WAV.

## Role mapping for composition

Suggested first-pass role mapping (kept distinct from source family):

| IRO source role/family | Reawarp use |
| --- | --- |
| kick, sub_kick | kick / low-frequency anchor |
| snare | snare / principal backbeat |
| closed_hat, open_hat | hat / subdivision and high-frequency surface |
| rim_click, phase_click, residue_snap | click / ghost / transition punctuation |
| metallic_ping, glitch_tom, hybrid_percussion | percussion / accent / counter-gesture |
| granular_shaker | high-frequency texture / granular percussion |
| eight entity families | math entity / motif fragments / transition events |
| sound-lab one-shots | one-shot / melodic and percussive gestures |
| sound-lab loops | rendered loop / source phrase |
| sound-lab stems | rendered stem / phrase layer or harmonic bed |
| sound-FX event families | event texture / transition / impact / residue |
| sound-FX loops | structural event loop / build / collision / aftershock |

Role assignment is an interpretation layer. The original IRO role and family must still be stored in event and project metadata.

## Composition philosophy carried from the IDM guides

The guide set treats composition as relationships over time, across event, pattern, phrase/section and whole-track scales. It emphasises local surprise inside global intelligibility, a small vocabulary of identity-bearing materials, one principal change at a time, and purposeful contrast/negative space.

The IRO Track 01 arrangement offers a concrete named arc:

`Signal → Construction → Orbit → Collision → Overload → Aftershock → Unravel → False Return → Residue`

Its Sonic Pi implementation uses a shared integer master beat clock and independent role voices. Reawarp should express the same principle offline: one shared project/form state, with independent deterministic event streams and separate stem renderers. Do not force all voices into one pattern or erase fractional source timing when importing future polyrhythm data.

## Phrase grammar direction

Reawarp's phrase director maps formal sections to recognisable functions:

- introduction / establishment;
- continuation / development;
- uplift / arrival;
- drop / silence;
- contrast;
- return / false return;
- residue / outro.

The function controls activity and orchestration roles, not master loudness alone. A drop can reduce kick/snare while leaving a quiet residue or ambience. An uplift can increase event activity, register, brightness or interlock without merely raising every track. A return should recall identity-bearing material while changing a limited number of dimensions.

## Non-goals

- Do not make Reawarp dependent on a live Sonic Pi session.
- Do not execute equation strings from IRO JSON.
- Do not duplicate assets just to satisfy a new interface.
- Do not treat a generated IRO manifest as a license record.
- Do not equate greater event density with greater musical quality.

# M24.6 — Bounded Feedback Delay Network

**Status:** Core NumPy implementation delivered; human listening and target-machine acceptance remain open  
**Processor:** Fixed four-line orthogonal feedback-delay network (FDN)  
**Integration:** Standalone offline DSP module; no automatic M22 insert or general routing graph

## Musical use case

Build a short resonant, interwoven tail from machine pulses, metallic transients, clipped percussion or inharmonic sound objects. The tail should evolve through several unequal delay paths rather than repeat as one obvious echo or split into static frequency bands.

M24.2 already provides frequency-region spectral delay with independent band delays. M24.6 addresses a different question: what happens when four time-domain delay paths repeatedly exchange energy through a fixed orthogonal mixing matrix? This creates cross-coupled, evolving echoes while retaining a small, understandable system.

## Fixed topology and stability

The processor contains exactly four delay lines with a normalized 4×4 Hadamard feedback matrix:

`M = (1/2) [[1,1,1,1], [1,-1,1,-1], [1,1,-1,-1], [1,-1,-1,1]]`

`M` is orthogonal, so its induced 2-norm is 1. The feedback operator is `gM`, where `0 ≤ g ≤ 0.98`. Its norm is therefore at most 0.98, strictly below unity, with a minimum stability margin of 0.02. No arbitrary matrix, dynamic topology, feedback graph or hidden gain compensation is accepted.

Four unequal delay times are authored in milliseconds and resolved to distinct integer sample delays. The initial implementation bounds each time to 5–2000 ms and uses a fixed mono/stereo injection and decoding transform.

## Controls

- `delay_times_ms`: exactly four distinct delays.
- `feedback_gain`: [0, 0.98]; the contraction factor for every network traversal.
- `input_gain`: [0, 1]; excitation level sent into the delay network.
- `dry`, `wet`: [0, 1] linear mix amounts.
- `max_tail_seconds`: [0, 30] hard duration cap.
- `tail_threshold_db`: [40, 120] conservative decay estimate.
- `output_ceiling`: [0.1, 1] static whole-render peak guard.

The tail estimator uses the longest delay and the number of feedback traversals required to fall below the requested decay threshold. The result is always clipped to the hard maximum duration. A truncated tail is reported; it is never silently described as fully decayed.

The processor records the topology ID, sample delay values, feedback norm bound, stability margin, tail estimate/cap, pre-guard peak, final guard gain, output peak, working-memory estimate and render time.

## Signal, state and safety contract

1. **Fixed topology:** exactly four delay lines and one normalized orthogonal feedback matrix. No user-defined graph or recursive stage chain is allowed.
2. **Stable feedback:** feedback gain cannot reach unity. Since the matrix norm is 1, the loop operator norm is bounded by the scalar gain.
3. **Finite output:** a conservative decay estimate is capped by `max_tail_seconds`; output frame count is input length plus the selected tail.
4. **Headroom:** the one-shot offline render applies a deterministic static peak guard to the entire render and reports the amount of attenuation. It does not claim to be a transparent look-ahead limiter.
5. **Reset:** each one-shot call starts with zero delay memory. The streaming `FeedbackDelayNetwork.reset()` clears all four lines and returns the instance to a ready state.
6. **Panic/stop:** `panic()` clears the state immediately and refuses further processing until `start()` or `reset()`.
7. **Cancellation:** offline streaming checks cancellation at block boundaries, clears state and raises `FeedbackNetworkCancelledError`.
8. **Bounded memory:** only the recent delay history is retained in the ring buffers; memory does not grow with the input duration. The output array is necessarily proportional to rendered duration.
9. **Non-destructive:** source arrays are read-only inputs; the processor never modifies them.
10. **Offline only:** no work is added to the audio callback or real-time playback path. The processor is opt-in and is not added to role-aware defaults.

## API

`reawarp.dsp.feedback_delay_network(audio, sample_rate, ...)` returns a `FeedbackNetworkResult` with audio and diagnostics.

`FeedbackDelayNetwork` also exposes stateful `process()`, bounded `flush()`, `reset()`, `panic()` and `start()` methods for block-oriented offline use. The stateful block interface returns raw streaming output; the one-shot helper is the path that applies the complete-render peak guard.

## Reproducible evaluation

- `tests/test_m24_6_feedback_network.py` covers orthogonality/stability, bounded tails, peak guard, source immutability, deterministic rerenders, mono/stereo shape, streaming block invariance, reset/panic, cancellation and invalid settings.
- `scripts/benchmark_m24_6_feedback_network.py` reports platform, NumPy/Python, wall time, real-time factor, traced allocation and processor diagnostics.
- `scripts/render_m24_6_listening_example.py` writes dry, level-matched and unmatched WAVs plus listening questions.

Run the benchmark and listening render:

```powershell
python scripts/benchmark_m24_6_feedback_network.py --duration 5 --sample-rate 48000 --output output/m24-6-benchmark.json
python scripts/render_m24_6_listening_example.py --output output/m24-6-listening
```

## Acceptance still open

Automated tests establish deterministic operation and the stated mathematical bounds, not whether the resulting tail is musically desirable. Listen to the matched-level set in stereo, mono and at low monitoring level. Confirm whether the cross-coupled tail contributes something distinct from M24.2 on real material, and run the 30/180-second 48 kHz benchmark on the target Windows machine before treating M24.6 as fully signed off.

No M24.6 processor is automatically inserted into existing projects. Existing FX routing and project schemas remain unchanged.

# M24.7 — Optional Parallel Processing Branches

**Decision:** Research gate retained — no parallel-branch feature approved  
**Audit date:** 26 November 2026  
**Audited baseline:** `main` at `60a50e9adb25617f2669ad29fa61feba9910e273`  
**Scope:** Reawarp's current offline FX chain and mixer; no schema or runtime change

## Gate decision

Do not implement M24.7 yet. The current mixer cannot express every imaginable parallel topology, but the repository contains no concrete composition in which that limitation prevents a useful result. Adding a generic branch model now would expand persisted routing, rendering, UI, latency, phase, tail and cache contracts without evidence that the added complexity solves a musical problem.

This is a deliberate hold, not a claim that parallel branches are already fully supported.

## What the current system can express

1. **Per-stem serial inserts.** Each stem has one ordered insert chain. The chain supports up to 12 validated stages, with a bounded dry/wet `mix` per stage and a chain-level wet blend. The insert is rendered offline and the dry stem remains intact.
2. **Two parallel auxiliary returns.** Every stem can send to the shared `SPACE` and `ECHO` returns. Each return has its own shared chain and wet amount. Returns are wet-only; the dry signal stays on the direct path.
3. **Four send tap positions.** A send can take pre-insert/pre-fader, pre-insert/post-fader, post-insert/pre-fader or post-insert/post-fader material. Send levels and return wet levels can be automated.
4. **One-way sidechain control.** M24.5 can derive a bounded gain envelope from one source stem and apply it to a different target stem before the target insert.
5. **Bounded timing assumptions.** The built-in routing path reports zero processing latency and start-aligns the built-in chains. Insert and return tails are tracked separately.

Relevant implementation: `src/reawarp/fx.py` (stage and chain dry/wet mix), `src/reawarp/fx_routing.py` (`FX_BUSES`, per-stem inserts, send taps, shared return render and tail report), and `src/reawarp/sidechain.py`.

## What is not expressible today

- Two or more independently configured insert chains on the **same stem**, processed from the same tap and blended back together as separate per-stem branches.
- A branch-specific chain and gain/automation lane for each such branch. The current two returns are global shared buses: stems feeding one bus share that bus's chain and return controls.
- An arbitrary branch-combine graph, branch-to-branch routing, or branch-specific latency compensation. Those are outside the current M22 contract.

The absence of those structures is not, by itself, a reason to add them. The current stage-level and chain-level blends already cover ordinary dry/wet parallelism; the two shared returns cover common shared-space and echo paths.

## Evidence required to reopen

Before implementation, one real use case must provide all of the following:

- The source project or reproducible source stems, the role being processed and the exact musical passage.
- The intended branches (input tap, distinct processing chains, branch gain/automation, and where their outputs recombine).
- A baseline attempt using the current serial insert, stage dry/wet mix and SPACE/ECHO returns, with a precise explanation of what cannot be achieved.
- A matched-loudness comparison showing the desired parallel result contributes something audible and musically useful, not merely a different parameter configuration.
- A statement of the required channel layout, expected latency/tail behaviour, and acceptable CPU/memory budget.

Without this evidence M24.7 remains deferred. No default branch count, branch schema, UI or processing graph is being proposed as if already accepted.

## Minimum engineering contract if the gate passes

A future design must define, test and expose before it is wired into projects:

- **Topology:** bounded branch count and explicit source tap; no unrestricted graph, cycles or implicit feedback.
- **Alignment:** declared latency for every branch, deterministic compensation, and a documented policy for phase-sensitive recombination.
- **Gain law:** explicit linear/equal-power or other justified blend law, with defined dry retention and peak/headroom reporting.
- **Tail ownership:** per-branch tail cap, output-length rule, and deterministic summing of branch tails.
- **Channels:** mono/stereo handling and deterministic channel mapping.
- **Lifecycle:** reset, cancellation, panic/stop, stale-render rejection and bounded temporary memory.
- **Persistence:** versioned routing schema with migrations that preserve all existing v1–v4 projects exactly.
- **UI and audition:** source/branch controls, per-branch meters, matched-level branch solo/A-B and an unmistakable bypass path.
- **Validation:** impulse alignment/latency tests, phase tests, gain-law tests, tail/headroom tests, schema round trips, source immutability, deterministic rerenders and target-Windows 30/180-second benchmarks.
- **Acceptance:** a human matched-level listening review on the real use case before adding the feature to default routing.

## Related coverage

Current baseline is covered by `tests/test_fx_contracts.py`, `tests/test_m22_routing.py`, `tests/test_m24_5_sidechain.py` and the M24.6 standalone processor tests. These tests establish existing contracts; they do not prove that an additional parallel branch feature is needed.

# M27 — Artistic Intent and Mutation Contracts

**Status:** Generator / GenerationConfig workflow implemented  
**Scope:** Versioned brief, source identity resolution, bounded configuration exploration and project provenance  
**Current limitation:** permitted GenerationConfig fields are sampled once per generation; they are not yet scheduled as repeated event-, pattern-, phrase- or section-local changes

## Intent is separate from configuration

A `CompositionBrief` expresses what the piece is about and what must remain recognisable. `GenerationConfig` remains the validated set of actual renderer/planner inputs. M27 does not replace the canonical Score or introduce another event scheduler.

The brief records:

- Artistic question and listening mode.
- Named A/B/C materials, optional roles and source-family identities.
- Anchor type, target and stability.
- Pitch world (scale, root and tuning identity). It is applied to melody scale/root only when explicitly authored or non-default; otherwise the current Generator pitch settings remain authoritative.
- Contrast targets and intended ending behaviour.
- Per-target mutation contracts and a separate tempo/form policy.

The Generator's **M27 / Artistic Intent + Mutation Contracts** editor is part of the Generator control panel. It authors the brief, but contains no renderer or project state. The **Apply Brief to Current Project** button adds the brief and its resolved-source record to the current project's metadata without rerendering audio.

## Source identity and resolution

The resolver snapshots available `GenerationConfig.sample_paths` and `sample_banks` into role-labelled source families. References retain asset ID and SHA-256 when present; custom unindexed sources fall back to role and exact path identity.

Before generation, each brief source is checked against the current configuration. A missing family, changed role, changed asset ID/hash or mismatched path is an error. Reawarp does not silently replace a named source with another member of the same sample role.

Project export continues to use the existing manifest policy (`copy` or `reference`). On reopen, the project manifest audits embedded/external source files, while M27 provenance validates the saved brief fingerprint, resolved-intent schema, source snapshot record and root generation seed.

## Mutation permissions

A `MutationContract` names a target, one of the existing event/pattern/phrase/section intent scales, an explicit list of mutable GenerationConfig fields, preserved fields, optional numeric bounds or categorical allowed values, cadence, decision boundaries and stop/freeze conditions.

The executable adapter is intentionally conservative:

- A field not listed in a contract cannot change.
- A field may appear in only one active contract. A field declared invariant anywhere in the brief cannot be mutated by another contract.
- Source/clock invariants are always protected: `seed`, `sample_rate`, `sample_paths`, `sample_metadata` and `sample_banks`.
- BPM, duration and formal trajectory/flow remain fixed unless `TempoFormPolicy` explicitly sets the matching mode to `explore`. Their chosen ranges are bounded by GenerationConfig's legal domains.
- Numeric and categorical options are validated again when a mutation is applied. Unsupported fields, enum values, break transforms, bounds, cadence or stop conditions fail before generation.
- Every changed field gets its own stable random stream derived from root seed, brief ID, contract ID, scale and field name. Changing one contract/field does not advance another field's random stream.
- Mutations are opt-in. A brief with mutation permissions but with bounded exploration disabled does not randomise the current generator values.

**Current execution limit:** although contracts retain event/pattern/phrase/section scale and decision-boundary intent, the current adapter translates them to a single bounded GenerationConfig selection before planning. It does not yet make repeated per-event or per-phrase decisions inside the composition. Those future behaviours require explicit Score/phrase mutation services and their own tests.

## Generation and project records

Use the public API:

```python
from reawarp import GenerationConfig, ReawarpEngine
from reawarp.composition import (
    CompositionBrief,
    quick_mutation_contracts,
)

brief = CompositionBrief(
    brief_id="machine-pulse-study",
    artistic_question="Can the anchor pulse survive unstable surroundings?",
    listening_mode="close listening",
    mutation_contracts=quick_mutation_contracts(
        ("arrangement_density", "tonal_brightness")
    ),
)

project = ReawarpEngine().generate(
    GenerationConfig(seed=211, duration=12.0),
    composition_brief=brief,
    bounded_exploration=True,
)
project.export("output/machine-pulse-study")
```

Generated projects carry these metadata records:

| Key | Purpose |
| --- | --- |
| `m27_composition_brief` | Complete versioned, user-authored brief |
| `m27_resolved_intent` | Brief fingerprint, generation seed, resolved source-family snapshot, preserved fields and warnings |
| `m27_bounded_exploration` | Applied contract IDs, before/after field values, independent seed lineage and preserved fields; null when not enabled |
| `m27_bounded_exploration_enabled` | Explicit user opt-in state |

When reopening an M27 project, Reawarp validates the brief, resolved-intent schema and fingerprint, generation seed, changed fields, contract ownership, final GenerationConfig values and deterministic seed lineage. Old projects without M27 metadata remain legacy-unstructured; merely loading one does not create or save an inferred brief.

## Automated verification

- `tests/test_composition_brief.py` — schema, material/source references, strict resolution and pitch-world semantics.
- `tests/test_mutation_contracts.py` — deterministic independent field streams, permission enforcement, invariant conflicts, explicit tempo/form policy and unsupported cadence.
- `tests/test_m27_integration.py` — engine integration, project export/reopen, tamper detection, legacy loading and Generator editor round-trip.
- CI's desktop smoke checks that the M27 editor is part of the actual Generator workflow.

A passing test suite establishes reproducibility and permission boundaries; it does not judge whether the brief makes a better composition. Artistic authorship and listening acceptance remain human decisions.

# M30 — Ending Director and transition actuation

**Implementation note · 26 November 2026**

## Musical problem

A transition is more than a preset swap, and an ending is more than a global fade. A composer needs an explicit, inspectable final action that can recall a motif, transform a reprise, leave an expectation unresolved, preserve a residual identity, dissolve selected material, or stop at a declared beat.

## Existing services reused

- TransitionPlan remains the typed three-phase transition contract and compiles to non-audio Score markers.
- SectionMemory remains the bounded, immutable recent-section window. The EndingDirector queries its open return opportunities and unresolved expectations instead of keeping another cache.
- Score remains the canonical timeline. Ending plans live in versioned Score metadata, and marker events are silent.

## Public models

- EndingPlan records exact rational start/end beats, strategy, motif/source-section or expectation identity, permitted transformations, retained material IDs, participating roles, named seed lineage and rationale.
- EndingDirector.propose() requires an explicit strategy. A delayed return or transformed reprise must resolve to a still-open SectionMemory return opportunity; an interrupted cadence must name a still-unresolved expectation. No hidden strategy selection or random seed is introduced.
- compile_ending_plans() attaches a fingerprinted plan list and deterministic start/completion markers. Recompilation replaces only markers owned by the same ending ID.
- transition_actuation_at() resolves the current preparation/change/arrival phase at an exact Score beat. The target scene is exposed at the single change boundary, with one atomic commit indication.

## Mutation and render boundary

These features are descriptive composition directives. They do not delete, rewrite, thin, fade or resample audio events. Marker events use kind=marker and remain silent in ScoreRenderer. A later arrangement/render action must explicitly consume a directive and create a reversible, provenance-bearing edit or render copy.

## Validation

Automated coverage checks all six ending strategies, exact rational timing, return-opportunity permissions, unresolved-expectation ownership, marker silence, Score round-trip and fingerprint integrity, idempotent replacement, unrelated-event preservation, and transition phase/commit resolution.

Human listening sign-off remains open: the strategies need to be evaluated in short asymmetric examples, including no-change repetition, transformed return, interrupted cadence, sparse residue, gradual dissolve and exact hard stop.

# M31 — Sound-Object Workshop and Resampling Lineage

**Implementation note · 26 November 2026**

## Architecture

M31 is a thin authoring and print layer around the existing M21 SoundObjectPatch, HybridVoiceRenderer, sound_object_editor_model and SampleLibrary services. Qt does not duplicate the patch model or DSP renderer.

## Delivered core

- A dedicated Sound Objects workspace imports a linked audio source as a body-layer object, selects saved patches, edits identity and frame-addressed layer fields, and saves immutable patch revisions.
- Transient/body/tail/texture/voice layers can be auditioned individually or as one aligned object through the M21 renderer. Rendering runs in a cancellable background worker; audio output is optional for editing and waveform inspection.
- SoundObjectVersion snapshots are content-addressed and revisioned in SQLite. Re-saving identical patch content is idempotent.
- RoleAssignment derives a distinct processing identity for each (object version, target role) pair.
- Printing writes a new WAV asset, optionally resamples it, indexes it in SampleLibrary, and stores ResampleRecord provenance: source object version, source asset IDs and SHA-256 values, transformation chain, renderer version, settings, seed, sample rates, rendered-audio hash, output-file hash and role assignment.
- Source paths are protected against accidental overwrite. Missing assets and hash mismatches are reported rather than silently replaced.

## Render and lineage boundary

The workshop invokes the existing M21 HybridVoiceRenderer. A print is a new sample-library asset and never edits project stems or source files. The renderer version tag identifies the algorithm family; the output hash remains the authoritative identity of the actual print across differing runtime environments.

## Validation and remaining acceptance

Automated checks cover version history and idempotence, layer-solo alignment, original-file protection, source-hash and print lineage, sample-rate conversion, role-specific processing IDs, and headless UI editing.

Human listening acceptance remains open for transient/body/tail balance, mono translation, object reuse across multiple roles and A/B comparison in a full arrangement. Optional coherent-family generation and direct printing of selected phrase/stem/FX stages remain follow-on integrations.

# M32 — Critical Listening Workbench and Contextual Evaluation

**Implementation note · 26 November 2026**

## Architecture

M32 extends the existing M23 Variation Browser and M28 Phrase Workbench contracts. It adds no new renderer, no production-mix mutation path, no automatic artistic ranking and no "best candidate" recommendation.

## Delivered services

- AuditionTransform records the operation, source project fingerprint, candidate ID, parameters, before/after audio hashes, sample rate and review decision.
- ListeningEditHistory keeps disposable snapshots with undo/redo and explicit keep-for-review decisions.
- Contextual audition covers full track; opening/middle/ending; solo phrase; predecessor→candidate; candidate→successor; full parent section; reduced density; altered register; and invariance removal probes.
- Percentage subtraction and register changes happen on copies. Register changes are rendered from a temporary Score copy; original Score and production stems are not rewritten.
- Invariance probes identify anchor and removed roles, state the human identity question, and record a human outcome (survives / does not survive / ambiguous / not reviewed) without scoring.
- Analysis describes peak, RMS, crest/headroom, clipping, silence floor/ratio, active end/tail silence, mono fold loss, channel correlation, spectral occupancy, several playback-level measurements and transient overlap between stems. Every warning carries severity and numerical evidence; thresholds/window sizes are serialized.
- Analysis is optional. The disabled path returns no metrics or warnings and does not influence rendering or generation.
- Session metadata records project fingerprint/revision, candidate IDs, exact audition transform metadata, playback-level gain and hashes, subtraction/invariance decisions and human-authored notes.
- Project export emits critical_listening_report.json and a portable critical_listening_report.md; manifest.json records session identity, fingerprint, candidate references, analysis state and report filenames.

## Mutation boundary

The project, Score and dry stems are copied or treated as read-only while building an audition. A keep decision records a listening choice only. Restore moves the audition history back or returns to the unmodified master. Neither action applies a change to production. The project fingerprint remains the anchor for provenance.

## Automated coverage

Tests cover percentage subtraction, non-destructive buffers, undo/redo and keep decisions, exact rational-beat contextual crops, altered-register Score-copy rendering, invariance semantics, measurement evidence/severity, analysis disabled mode, candidate/session provenance, JSON/Markdown export and manifest linkage.

## Human acceptance still open

Listening sign-off is intentionally human-led: evaluate identity survival, transient/body/tail balance, spectral masking, mono and low-level translation, phrase continuity, section pacing and emotional coherence on actual compositions. Threshold warnings are prompts for inspection, not declarations of artistic failure.

## Explicit follow-on scope

- Contextual audition of M23 candidate A/B with the full FX chain and matched-level output in the same transport.
- Multi-select invariance mutations that alter/re-orchestrate anchors as well as remove other material.
- A/B level ladders with selectable calibrated reference excerpts and an integrated blind/unblind sequence.
- Optional spectral occupancy by semantic role group and more precise onset/phase diagnostics.

# M33 — Arrangement Editor, Manual Composition and Print-to-Track

**Status:** Core implementation delivered; human listening acceptance remains open  
**Date:** 26 November 2026  
**Canonical model:** `Score` plus the versioned `m33_arrangement` record in Score metadata

## Intent and boundary

M33 makes selected phrase material into a manually authored piece without turning Reawarp into a general-purpose DAW. The Score remains the only source of event timing and identity. The arrangement document stores where each phrase is placed, which event IDs it owns, where those events originated, whether the phrase is frozen or muted, and which M28 candidate supplied the selected material.

All musical positions are exact rational beats. Move and trim operations update the canonical Score events and the M28 PhrasePlan together. No independent floating-point clip clock or destructive source-sample editor is introduced.

## Arrangement model

`src/reawarp/composition/arrangement.py` owns the service layer:

- `ArrangementClip` stores a stable clip ID, current phrase ID, source phrase ID, rational source/destination spans, current and original event IDs, candidate/parent lineage, freeze/mute state, role exchange map, origin and revision.
- `ArrangementPlan` validates the arrangement schema, its content fingerprint, the Score revision fingerprint, phrase identity, exact phrase boundaries and all referenced event IDs.
- `m33_arrangement` metadata retains the original pre-arrangement Score snapshot, ordered phrase references, human finishing checklist, print records, a bounded undo/redo journal and a durable edit audit log.

The `origin` field distinguishes generator-originated, candidate-originated and manually edited material. Candidate identity is retained when a selected candidate is subsequently moved or duplicated; the edit journal separately records the manual operation. Each edit records actor, action, revision, operation details and before/after Score and arrangement snapshots. The undo stack retains the latest 50 reversible edits to bound archive growth; the audit log retains the latest 200 edit/undo/redo records.

## Editing operations

The Arrangement Editor workspace is available under **Compose → Arrangement**.

- **Create from phrases** builds one arrangement clip for each existing M28 PhraseSpan. It requires a non-empty, valid PhrasePlan and does not change the original Score.
- **Move** changes a phrase's exact start beat and shifts its events and phrase boundaries without changing event IDs or durations.
- **Duplicate** creates a new phrase ID and new event IDs. It retains the original source-event IDs and parent clip ID, so the copy is editable without stealing identity from the source.
- **Trim** crops intersecting events to exact phrase boundaries and removes events outside the selected range. Zero-duration events inside the half-open trim interval are retained. Frozen clips cannot be trimmed.
- **Reorder** compacts the phrase sequence from its current start beat and retains the ending's offset relative to the complete phrase sequence. The operation is committed as one undoable edit.
- **Mute / unmute** sets note/hit velocities to zero on the Score, saves their prior velocities, and restores those exact values on unmute. Events are not deleted.
- **Exchange layer** reassigns selected phrase events from one Score voice to another, updates phrase role participation and records the role map. A frozen clip cannot exchange layers.
- **Replace with candidate** installs the selected M28 candidate events with fresh arrangement event IDs and preserves the candidate ID, operation, seed and original source-event lineage. It never silently imports a different phrase's candidate.
- **Freeze selection** protects content from trim, layer exchange and candidate replacement while allowing arrangement placement to change.
- **Branch arrangement** creates a new arrangement identity with a parent reference and unfreezes the branch for further edits.
- **Revert to generation** restores the stored pre-arrangement Score and rebuilds the initial phrase clips. It is itself undoable.
- **Undo / redo** restore Score and arrangement snapshots through the canonical Score renderer when audio content changes.

M28 phrase definition editing, deletion and M28's separate freeze/restore controls are locked while an M33 arrangement is active. This prevents a second workspace from changing phrase membership beneath an arrangement. Revert to generation returns to the M28 phrase workflow.

## Transitions and endings

M30 transition and ending plans remain Score-native cue objects on the M33 timeline. A cue can be moved in exact beats. A transition can also be relinked to a new outgoing/incoming phrase pair after a reorder; relinking preserves the three phase durations and anchors preparation to the new source phrase end. It is rejected when the existing durations cannot fit the source and target spans. Moving a phrase automatically carries a linked cue where the M30 phrase-boundary constraints remain valid; otherwise the cue remains explicit and can be repositioned or relinked by the composer.

M30 markers remain silent Score markers, not audio events. Ending movement preserves the ending strategy and duration.

## Print-to-track

**Print to new WAV** renders only the selected phrase's Score events through the offline Score renderer and writes a separate 24-bit PCM WAV object. The print operation crops to the exact phrase's rendered time interval, leaving the project's master and existing dry stems untouched. The print record includes:

- clip, phrase, candidate and event identities;
- original source-event IDs and current Score event IDs;
- output path/name, sample rate, frame count and duration;
- SHA-256 of the actual WAV bytes;
- renderer identity and arrangement revision.

Print lineage is attached only after the WAV header and supplied frame/sample-rate values are checked against the file. If the arrangement changes or the project is switched while a print is running, the file is retained at the selected path but is not falsely attached to the new project.

This print path is a **dry Score print**. It does not claim to include per-stem inserts, shared SPACE/ECHO returns, or final mastering. Those remain part of the existing mixer/delivery workflow.

## Finishing checklist

The editor stores human checkmarks for form review, ending review, subtraction, identity/invariance, contextual audition, low-volume translation, mono, peak/headroom, missing sources and export integrity. These are human-entered sign-off prompts, not automated artistic scores and not claims that the checks passed merely because the software rendered successfully.

## Save, reopen and export

The arrangement is serialized inside `score.json` as Score metadata, so the regular project loader reopens the same rational-beat phrase timing, event references, M28 candidate/source lineage and M30 cue plans.

When M33 state exists, `ReawarpProject.export()` additionally writes:

- `arrangement_snapshot.json` — schema, arrangement, timeline, checklist, edit/undo history, audit log and print export status;
- `arrangement_prints/` — verified copies of printed WAVs whose source hash still matches the print record.

The regular project package continues to include the canonical Score, events, combined/per-voice MIDI, dry stems, routed master, M32 critical-listening report and manifest. The manifest inventories the M33 snapshot and copied print files. Missing or changed source WAVs are reported instead of silently substituted.

## Tests and acceptance

Automated coverage lives in:

- `tests/test_m33_arrangement.py` — exact-beat operations, event identity, candidate replacement, undo/redo, M30 cue editing/relinking, print verification, export/reopen.
- `tests/test_m33_arrangement_ui.py` — workspace signal wiring, selection, candidate filtering and checklist interaction.

**Still open:** full human listening sign-off on real compositions; detailed target-Windows listening/performance acceptance; and confirmation that dry phrase prints fit the intended production use. M33 deliberately does not add a full audio clip/fade/crossfade editor, live arrangement engine, destructive sample editing or automatic artistic quality score.

# M34 — Audio-Conditioned Composition and Advanced DSP Research Gate

**Review date:** 26 November 2026  
**Decision:** Research reviewed; no production implementation approved  
**Scope:** Baseline, repository capability audit and acceptance contract only

## Executive decision

M34 remains a conditional research gate. The audit found one plausible missing capability—**time-varying audio features that can condition phrase-level composition macros**—but no supplied real-composition example demonstrating that this is currently blocking the composing workflow. The synthetic baseline below proves an information gap in the current whole-file summary API; it does not prove that an audio-conditioned generator produces better music.

Therefore this review does **not** approve M34 audio-conditioned composition, a new dependency or a generated-Score mutation path. A separate, narrower M24.5 sidechain use case was subsequently taken forward as offline detector-to-target gain routing (see M24_5_SIDECHAIN.md); that does not resolve or implement the M34 temporal-composition research question. M34 should remain deferred until a real break/stem/reference experiment demonstrates a benefit over a static-macro baseline and human listening confirms it.

## Repository capability audit

| Existing capability | What it already does | What it does not establish |
| --- | --- | --- |
| **reawarp.transforms.analysis** | Dependency-light transient detection and automatic frame slicing for imported break material | No stable, time-indexed feature envelope or phrase-level macro control |
| **reawarp.library.features** | Whole-file peak/RMS/crest, centroid/rolloff/flatness, transient count/density, onset interval summary, rhythm histogram and optional HPSS/onset descriptors | AudioFeatures returns aggregate values, not a window-by-window timeline, confidence or beat-aligned control curve |
| **M27 CompositionBrief** | Source identity, anchors, mutation contracts, scope-aware bounded config exploration and deterministic seeds | No signal-derived parameter source; macro values are explicit composition intent or bounded mutations |
| **M28/M32** | Phrase identity, deterministic alternatives, contextual audition, technical diagnostics and human evaluation provenance | No audio-analysis-to-Score mutation path |
| **M29/M30/M33** | Semantic attention/gesture controls, transition/ending grammar and deliberate phrase arrangement | No imported-reference-following control lane; these are authored from Score/form intent |
| **M22/M24.5 FX routing** | Per-stem serial inserts, fixed SPACE/ECHO returns and optional one-way sidechain gain routes; dry stems remain authoritative | No arbitrary routing graph, post-insert detector network or feedback routing |
| **M24.1–M24.4** | Separate NumPy reference implementations and CI coverage for convolution, spectral delay, cross-synthesis and nonlinear processing | These are research/reference processors, not automatic production inserts; listening and target profiling remain open |
| **M24.5** | Implemented as a bounded offline source-envelope to target-gain route | Peak/RMS detection, threshold/ratio, capped reduction, attack/release, hysteresis and mute/solo gating; human listening and target performance remain open |
| **M24.6** | Implemented as a standalone fixed-topology four-line FDN | Orthogonal Hadamard coupling, feedback operator norm bound, conservative decay estimate, hard tail cap, reset/panic/cancel and static peak guard; human listening and target profiling remain open |
| **M24.7** | Research gate for parallel branches | No demonstrated use case that existing inserts and SPACE/ECHO cannot express |

The repository already has substantial analysis and editing capability. The actual gap is temporal orchestration of reference features, not a lack of basic audio analysis. This distinction avoids duplicating transient detection, library indexing, M27 mutation contracts or M32 diagnostics.

## Candidate ranking

1. **Audio-conditioned phrase macros — most plausible, not yet approved.** A reference break/stem may have a meaningful progression in density, energy or spectral character. Whole-file averages erase its order. A future adapter could expose a few explicit normalized controls (initially density, brightness and activity) while keeping musical decisions on phrase boundaries.
2. **M24.5 sidechain/envelope routing — subsequently implemented as a narrow, separate milestone.** The chosen use case is transient-responsive ducking of a sustained texture by the actual kick/snare/break stem, especially when transient timing or amplitude changes after edits or regeneration. The detector follows the rendered source buffer rather than a manually drawn approximation; the implementation is deliberately one-way and offline. Its listening benefit remains unverified.
3. **M24.6 bounded feedback — implemented as a separate standalone processor.** The selected use case is an evolving resonant tail from machine-like pulses and metallic transients: four unequal time-domain delay paths exchange energy through one fixed orthogonal matrix, unlike M24.2's frequency-band repeat paths. The implementation has a contractive feedback operator, reset/panic semantics, bounded decay and headroom reporting. Its artistic benefit over M24.2 still needs matched-level listening.
4. **M24.7 parallel branches — do not implement by default.** The existing serial insert and shared wet-return model is intentionally bounded. Parallel processing is not an objective in itself; a failing serial/return baseline is required.
5. **Search/evolutionary optimisation — defer.** M27 bounded exploration, M28 phrase candidates and M32 human evaluation already establish a safer generate–audition–select pattern. Further search is not justified without a declared constraint that those contracts cannot express.

## Baseline example: same material, opposite order

The reproducible synthetic pair is defined in tests/fixtures/m34/audio_conditioning_order_pair.json and constructed in tests/test_m34_research_gate.py.

At 22,050 Hz it creates two equal-length, guarded materials:

- **sparse_dark:** four short 110 Hz pulses in the segment;
- **dense_bright:** sixteen short 3,800 Hz pulses in the segment.

Sequence A is sparse/dark followed by dense/bright. Sequence B contains the **same samples** in the opposite order. The guard regions and analysis-hop alignment avoid boundary windows changing the material inventory.

The existing library extractor returns whole-file values. Peak, RMS, crest, centroid, rolloff and flatness therefore match for the two orderings within a tight numeric tolerance, even though their temporal trajectories are opposite. The baseline regression test verifies that limitation. It is not an audio-conditioning feature test and it does not claim musical preference.

**What this baseline establishes:** whole-file summaries cannot answer the question “when does this source become denser/brighter?”  
**What it does not establish:** that a composition should follow the source, which macro should change, or that following it is musically beneficial.

## Proposed acceptance contract if a real use case is demonstrated

A future M34 design should begin with one named source, one musical problem and no more than three mapped macros. The following are objective prerequisites, not features delivered by this research review.

### Analysis contract

- Preserve source sample rate, channel count, duration and SHA-256. Record analysis version, window/hop, resampling method and all detector settings.
- Produce time-indexed RMS/energy, onset activity and spectral brightness/flux descriptors. Chroma or low-frequency bands are added only when the chosen source/task needs them.
- Normalize against a declared robust source range; report confidence and explicitly mark silent, clipped, corrupt or out-of-distribution windows as unreliable.
- Smooth at control rate and use enter/exit hysteresis. Never map raw frame-to-frame values directly to musical parameters.
- Align feature windows to rational Score beats and commit changes only at declared phrase/section boundaries. No audio callback performs analysis, file access or Score mutation.

### Composition and identity contract

- The mapping is explicit, bounded and small: proposed first controls are arrangement density, tonal brightness and melodic/percussive activity, each in [0, 1].
- Preserve CompositionBrief anchors, frozen source identities, selected motif/event IDs, root/scale, tempo and declared form unless the user explicitly authorizes a particular mutation.
- Manual override has priority and persists as authored Score intent; the analysis curve must not silently overwrite it.
- Same source hash + analysis settings + mapping + Score revision + seed must reproduce the same feature curve and mutation proposal. Record confidence, mapped values, phrase commits, override decisions and source lineage.
- Low-confidence or silent windows hold the last accepted value or the explicit baseline macro; they never trigger an uncontrolled reset or random value.

### Objective acceptance tests

1. **Order sensitivity:** the two fixture sequences in this review must produce different time-indexed macro curves even though their global summaries match.
2. **Known segment response:** detected sparse/dark and dense/bright regions must map to the declared expected direction; test tolerance is measured against exact synthetic segment boundaries.
3. **Boundary discipline:** the control curve may update only at the selected rational phrase/section boundaries, never at arbitrary analysis-frame positions.
4. **Hysteresis/smoothing:** a synthetic feature sequence alternating around a threshold must not chatter; step and slew limits are asserted numerically.
5. **Confidence/silence:** silent, corrupted and low-confidence windows must not produce a spurious macro excursion.
6. **Identity invariants:** deterministic reruns preserve protected anchor event IDs, motif identity, tempo/form and the original source bytes; intentional changes have an explicit mutation contract and provenance.
7. **Manual override:** a user-authored value wins over the analysis proposal and survives save/reopen.
8. **Reset/undo:** returning to the source baseline restores the exact original Score/config fingerprint and removes only the conditioned proposal.
9. **Resource budget:** benchmark analysis plus planning at 48 kHz for 30 s and 180 s, reporting CPU wall time, peak RSS and temporary buffers. Numeric budgets must be declared from a named target machine before claiming acceptance.
10. **Musical comparison:** render the conditioned proposal and static-macro baseline with the same source, Score invariants, seed and mix. A human must report an audible compositional benefit in context; feature correlation alone is not acceptance.

## Evidence still required to open implementation

- A real break/stem/reference and a precise musical problem it should help solve.
- A baseline composition made with current Reawarp tools and the exact limitation encountered.
- A matched static-macro versus conditioned render, reviewed in context and at matched loudness.
- Target-machine 30/180-second resource measurements and declared budgets.
- Explicit human decision on which anchors and structural invariants must remain fixed.

Until that evidence exists, M34 remains a research note and regression baseline. M24.5 and M24.6 are delivered separately with their own routing/processor contracts and tests; M24.7 parallel processing remains a research gate. This M34 review itself did not add an audio-feature composition lane or mutate generated Scores.

# Sample banks, drum-part automation and hybrid synthesis

## Purpose

Reawarp's composition plan, drum grammars, synthesis profiles and sample library now share a role-level source contract. The selected sound in each Generator selector is the **anchor** for that role. Other eligible assets from the bundled sample folder and the indexed Library can become phrase-aware alternatives.

No sample file is copied, renamed or modified. The project stores the asset path, content hash, descriptors, role and source metadata so the resulting arrangement is reproducible.

## How the role bank is assembled

The Generator builds separate kick, snare and hat banks in this order:

1. The currently selected Generator sample is first and becomes the opening/return anchor.
2. Other bundled samples discovered under `samples/` for the same role are added.
3. When **Include indexed Library assets** is enabled, indexed audio with an explicit role or a recognizable filename/folder role is added with its measured feature descriptors.

Paths are deduplicated. The current UI bounds each role bank to 65 entries. The SQLite Library is read as an index; the source audio remains in its original location.

Feature-guided selection uses the indexed spectral centroid, RMS level, spectral flatness, onset density and crest factor when available. Assets without indexed features can still participate, with neutral descriptor defaults. A feature index is useful but not required for playback.

## Drum sample automation

The Generator's **Switch sample parts through the track** control enables bank selection. The schedule can be:

- **Fixed:** use the selected anchor for the entire track.
- **Section:** choose a part when a new formal section begins.
- **Cycle:** choose a part at the start of each configured drum cycle.
- **Automatic:** preserve the anchor through introduction and establishment, change material in development/uplift/arrival/contrast/transition functions, use a related alternative for a false return, and recall the anchor for a true return.

The choices are deterministic from the project seed, role, section and cycle. Sample changes do not consume the hit-level pattern or synthesis random streams. Each change is recorded with its bar, section, phrase function, previous/next asset and label.

The same drum event stream drives synthesis and sample playback. Changing a sound source does not create a parallel rhythm or a second set of hits.

## Hybrid source modes and architectures

The source mode selects the overall balance:

- **Automatic:** phrase-aware sample contribution, reduced in introductions/drops/residue and increased for developments/uplifts/arrivals.
- **Synthesis only:** no sample playback or sample switching.
- **Hybrid:** a stable user-selected sample/synthesis blend.
- **Sample only:** sample hits without a parallel synthesized voice.

The hybrid architecture then defines how the two sources relate:

| Architecture | Sample role | Synth role |
| --- | --- | --- |
| Transient sample + synth body | Uses a short, faded onset from the selected sample | Supplies the pitched/body component |
| Parallel full layers | Plays the full sample | Plays the full synthesized voice at complementary gain |
| Feature-guided hybrid | Uses a sample transient window shaped by its crest factor | Adjusts synthesized voice, pitch and velocity using the selected asset's spectral brightness and onset density |

The sample contribution and transient window remain user-adjustable. Feature-guided synthesis falls back to neutral descriptors when an asset has not been indexed.

## UI workflow

The Generator is presented as one scrollable sequence rather than isolated FORM / VOICES / RHYTHM tabs. A persistent top action bar keeps **GENERATE TRACK** visible while the user scrolls through the settings.

The action bar describes the connected path:

`FORM → DRUM PARTS → SAMPLE LIBRARY → SYNTHESIS → RENDER`

After rendering, the summary reports bank sizes, sample changes, section/timbre maps and the selected source architecture. Sample changes are also preserved in `metadata.sample_switch_summary`, `metadata.sample_sources` and per-hit event records.

## Current scope

The first connected role banks are kick, snare and hat. Break Lab remains the separate path for long-form break material and transformations. The feature-guided architecture currently uses spectral centroid, flatness, onset density and crest factor for the percussion roles; future instruments can reuse the same role-bank contract.
