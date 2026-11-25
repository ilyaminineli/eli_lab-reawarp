# Reawarp implementation notes

These notes describe enduring code and engineering contracts. Milestone scope and status live in [MILESTONES.md](MILESTONES.md).

## Architecture boundaries

1. **Composition planning** creates deterministic sections, motifs, role relationships, sample choices and symbolic Score events. It does not own device playback.
2. **The Score** is canonical for event-backed scheduling. Rational beat positions remain exact until RenderTimeline resolves them to frames.
3. **ScoreRenderer** schedules discrete events and calls production voice adapters. Noise texture and ambience remain specialist whole-field renders documented by Score markers.
4. **Dry stem ownership** remains with the generated project. Transforms, inserts, routing, variations and audition processors work on copies and never rewrite source assets.
5. **Production routing** uses per-stem serial inserts and two wet-only shared returns (SPACE/ECHO). Keep the graph explicit and bounded; do not silently introduce arbitrary feedback or plug-in routing.
6. **Playback** consumes completed buffers only. Audio callbacks must not synthesize, allocate large buffers, access disk, or call GUI code.
7. **Export** snapshots mutable UI state before background work and writes a portable project with configuration, Score/events, source assets, routing, automation, render provenance and integrity inventory.

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
|---|---:|
| Project | 1 |
| Project manifest | 1 |
| Events | 1 |
| Score | 1 |
| FX routing | 3 (v1/v2 migrate) |
| FX automation | 1 |
| Sound Object | 1 |
| Variation candidate | 1 |

See the compatibility fixture at `tests/fixtures/m25/legacy_contracts_v1.json`.

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
