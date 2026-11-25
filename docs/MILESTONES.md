# Reawarp — milestone history and implementation status

**Canonical milestone record · 26 November 2026**  
This is the single maintained source for milestone scope, current implementation status, compatibility decisions and outstanding acceptance work. Code and tests are authoritative if documentation differs from behaviour.

## Product direction

Reawarp is an offline-first, deterministic mathematical composition and sound-design laboratory for IDM, broken rhythms, hybrid instruments and evolving arrangements. It is not a general-purpose DAW or a live plug-in host.

The project path is:

`GenerationConfig → Composition / Role Plan → Canonical Score → Dry Stem Render → FX Routing + Automation → Project Archive + Provenance`

Event-backed voices are planned into a rational-beat Score and scheduled by ScoreRenderer. Noise texture and ambience remain specialist whole-field passes represented symbolically in the Score. Dry stems and source assets remain the immutable source material for downstream production.

## Current status

| Area | Status | Remaining qualification |
|---|---|---|
| Deterministic composition and source roles | Implemented | Musical judgement remains a listening task |
| Score-first event rendering | Implemented | Whole-field texture and ambience remain specialist passes |
| Score automation, harmony and orchestration | Implemented | Subjective listening remains separate |
| Sound objects and hybrid instruments | Implemented | Full graphical patch-authoring UI is not claimed |
| Role-aware mixer and fixed returns | Implemented | Target-Windows Pyo listening remains open |
| Variation browser and candidate genealogy | Implemented | Candidate selection remains human-authored |
| M24.1–M24.4 DSP research | NumPy reference APIs and CI coverage | Not default production inserts; listening and target profiling remain open |
| M25 portability and project durability | Implementation complete; prior short CI acceptance passed | Target-Windows long benchmark and declared resource budgets remain open |
| M26 production FX variations and complete package export | Implemented on `main`; corrected regression cases are being revalidated | Latest CI result is pending; Pyo and human listening remain separate gates |
| M24.5–M24.7 | Planned / research gate | No implementation claim |

**Previous M25 validation baseline:** [CI run 45701978735](https://github.com/ilyaminineli/eli_lab-reawarp/actions/runs/45701978735) passed Linux Python 3.10–3.12 and Windows. The 5-second 48 kHz export/reopen smoke passed in all four jobs and Windows reported 307 passing tests. This is a short portability/integrity check, not a 30/180-second target-machine performance sign-off. M26 adds further regression coverage; see the latest [Actions runs](https://github.com/ilyaminineli/eli_lab-reawarp/actions).

## Milestone ledger

Status terms:
- **Implemented** — behaviour is present and has automated coverage.
- **Implemented; sign-off open** — software is present, but optional-backend, target-hardware or human listening evidence is outstanding.
- **Planned** — direction/specification only.

### Foundation: material, Score and composition (M3–M9)

| Milestone | Status | Delivered scope |
|---|---|---|
| **M3 — Break transformation and percussion** | Implemented | Transient detection, slice-based break transforms, stutter, dropout, reverse, gate, pitch/time operations, granular resynthesis and spectral freeze. Processing uses copies; original sample assets are not overwritten. |
| **M4 — Desktop instrument** | Implemented | Optional PySide6 Generator, Break Lab and Stem Mixer workspaces; waveform/spectrogram views; SoundDevice transport; background rendering. |
| **M5 — Universal Score and MIDI** | Implemented | Synthesizer-independent events, rational beat positions, tempo/meter maps, automation lanes, tuning references, Score JSON and optional Mido MIDI 1.0 import/export. |
| **M5.1 — Break integrity and sound palette** | Implemented | Four structured break grammars, transient-sliced imported breaks, coherent melodic timbre profiles, restrained automatic percussion and separate harmonic ambience. |
| **M6 — Searchable sample/stem library** | Implemented | Local SQLite index, hashes, role/tags, audio descriptors, similarity search, collections and project genealogy. Audio remains in its original location. |
| **M7 — Composition director and workbench** | Implemented | Formal section trajectories; section-aware material; frozen-base, stem-only regeneration; Generator/Library desktop workflows. |
| **M8 — Long-form composition** | Implemented | Structure presets and flow operations up to 180 seconds, pattern relationships, motif transformations and selectable synthesis architectures. |
| **M9 — Restrained synthesis foundation** | Implemented | Separate subtractive lead renderer, sparse transient/body/tail percussion, role-separated ambience and refined dependency/UI foundations. |

### Processing and production (M10–M13)

| Milestone | Status | Delivered scope |
|---|---|---|
| **M10 — Offline FX Lab** | Implemented | Optional lazy-loaded Pyo offline DSP: filters, saturation, delay, reverb and frequency shift; starter chains; dry/processed audition; `reawarp-fx` CLI. |
| **M11 — Editable FX chains** | Implemented | User-authored ordered serial chains, bounded stage controls/mixes, portable JSON save/load and CLI validation. |
| **M12 — Role-aware FX routing** | Implemented; refined by M22 | Per-stem inserts and fixed shared SPACE/ECHO returns. Dry stems remain intact; returns are wet-only; routed exports can extend with effect tails. |
| **M13 — Musical FX automation** | Implemented | Beat-based insert wet, per-stem send and return wet automation; hold/linear/smooth curves; tempo-synchronised delay divisions. Schema v1 remains supported. |

The production routing model is intentionally bounded: each role has a serial insert path and can feed two shared auxiliary returns. It is not an arbitrary routing graph, a feedback network or a live plug-in host.

### Reliability and Score-first rendering (M14–M17)

| Milestone | Status | Delivered scope |
|---|---|---|
| **M14 — Reliability and performance baseline** | Implemented baseline; sign-off open | Signal diagnostics, deterministic regression suite, project export/reopen checks, benchmark harness and phase timings, Windows CI and grouped project-centred UI navigation. Target-Windows 30/180-second profiling and Pyo listening remain open. |
| **M15 — Composition Director 2.0** | Implemented; listening sign-off open | Persistent motif identity and transformations, seven-role orchestration, phrase-boundary transitions, independent density/syncopation/instability/register/brightness/spatial controls. |
| **M16 — Score-driven render core** | Implemented; completed by M17.5 | Shared beat/frame timeline, ScoreRenderer, typed AutomationControlBus, production voice callback contract and render provenance. |
| **M17 — Canonical Score-first pipeline** | Implemented | M17.1 planner event emission; M17.2 production voice adapters; M17.3 sample triggers, hybrid layers and frame-domain break slices; M17.4 legacy FX automation adapter; M17.5 canonical Score planning before rendering. Project event dictionaries are compatibility projections. |

**Timing boundary:** Score supports richer tempo/meter timing than every high-level planner currently consumes. Texture and ambience remain whole-field passes rather than being forced into per-event semantics.

### Control, harmony and orchestration (M18–M20)

| Milestone | Status | Delivered scope |
|---|---|---|
| **M18 — Musical automation and control performance** | Implemented; listening sign-off open | Typed targets with units/ranges; global/section/role/event scopes; deterministic LFO, envelope, stepped, random-walk and phrase-curve sources; modulation; render-time role/event shaping; supported ADSR/vibrato/spectral/spatial controls; fixed-router integration; Score Control editor. |
| **M19 — Harmonic context and voice-leading** | Implemented; listening sign-off open | Optional pitch fields, tuning-aware sonorities and transforms, deterministic sequence-level voice-leading with inspectable cost terms, six independent bass grammars and loss-aware MIDI 1.0 interchange. No mandatory functional-harmony model is imposed. |
| **M20 — Perceptual orchestration and phrase grammar** | Implemented; listening sign-off open | Score-persisted asymmetric phrase spans, independently phased cycles, role-pair grammars, foreground/midground/background/absence, hand-offs, mutation permissions and heuristic conflict warnings. Compiles from M15 director decisions. |

M18's render-time density, syncopation and articulation do not silently rewrite the canonical symbolic Score or re-run the upstream stochastic planner. A future planner-regeneration interface would require explicit provenance semantics.

### Sound objects, mixing, variation and durability (M21–M26)

| Milestone | Status | Delivered scope |
|---|---|---|
| **M21 — Sound-object and hybrid instrument architecture** | Implemented; sign-off open | Versioned sound-object patches with separate source/processing identity, frame-exact transient/body/tail layers, hybrid renderer, modal/additive voices, typed Score controls, non-destructive resampling and SQLite patch/variant lineage. An editor-facing model exists; a full graphical patch editor is not claimed. |
| **M22 — Mixer and routing quality** | Implemented; Pyo listening open | Role-aware defaults, routing schema v3 with v1/v2 migration, four send taps, fader/pan/mute/solo semantics, wet-only returns, meters, tail/headroom reporting, stage audition, matched-level copies and cancellable background routing/cache. |
| **M23 — Variation browser and critical listening** | Implemented; listening remains human-led | Deterministic candidate batches, frozen bases, blind matched A/B, difference waveform/spectrogram, listening sets, notes, keep/discard/promote/branch/restore, nested project persistence and SQLite ancestry. |
| **M24 — Advanced DSP research** | M24.1–M24.4 reference implementations; M24.5–M24.7 planned | Independent NumPy reference APIs. None is automatically inserted into the M22 production role map. |
| **M25 — Performance, portability and project durability** | Implemented; long target benchmark open | Manifest v1, source-asset copy/reference policy, file inventory and SHA-256 audit, compatibility fixtures, background archive service, detailed Score/voice timings and cooperative cancellation. |
| **M26 — Connected project FX and delivery export** | Implemented; Windows/Pyo and human listening sign-off remain separate | FX Lab loads active project channels and can assign custom serial chains as per-stem inserts. Stem Mixer pre-renders channel inserts/SPACE/ECHO returns, generates deterministic role-aware FX alternatives and reuses the completed routing snapshot for audition and master render. Desktop Delivery Export automatically completes FX rendering, then writes a normal folder containing README.md, routed master.wav, original aligned dry stems/ and combined/per-voice MIDI. It does not copy source samples, create a ZIP, or claim to be a restorable Reawarp project archive. |

#### M24 module ledger

| Module | Status | Scope |
|---|---|---|
| **M24.1 — Convolution and designed IR instruments** | NumPy reference + regression/CI coverage implemented; audition/profile open | Partitioned overlap-add FIR, designed modal IR, hashed portable archive, tail/headroom reports and audition generator. |
| **M24.2 — Spectral delay** | NumPy reference + regression/CI coverage implemented; audition/profile open | Frequency-region delay, bounded repeat feedback, attack-aware repeats and capped tails. |
| **M24.3 — Cross-synthesis and frequency transformation** | NumPy reference + regression/CI coverage implemented; audition/profile open | Ring modulation, fixed-Hz frequency shift, spectral-envelope transfer and band vocoder. |
| **M24.4 — Oversampled nonlinear processing** | NumPy reference + regression/CI coverage implemented; audition/profile open | Five transfer curves and 1x/2x/4x/8x Kaiser-sinc oversampling. Aliasing is reduced, not eliminated. |
| **M24.5 — Sidechain and envelope routing** | Planned | Explicit detector, envelope, smoothing, hysteresis and cross-stem control semantics. |
| **M24.6 — Feedback networks** | Planned | Bounded fixed-topology feedback delay/resonator structures with stability, decay and headroom tests. |
| **M24.7 — Optional parallel processing branches** | Research gate only | Only if a demonstrated use case cannot be expressed by serial inserts and shared returns. |

M26's project-aware FX variations change routing/effect settings, not source events or the composition seed. Generated alternatives remain deterministic for the same project context and variation seed. Current role protection keeps kick/sub paths dry. Actual Pyo sound and musical acceptance still require listening; a render/cache smoke cannot judge the artistic result.

## Current architecture contracts

### Determinism and audio ownership

- Derive random streams from stable names and explicit seeds; do not use Python's process-randomised `hash()` for musical decisions.
- Stem regeneration must preserve unrelated sources; imported samples, dry stems and frozen variation bases are read-only.
- Render offline. The audio callback plays completed buffers and does not run synthesis, disk, GUI or FX processing.
- Use float32 internal buffers; frame alignment, tail extension, peak/headroom and channel layout are explicit.
- Diagnostics are evidence for listening, not artistic quality scores.

### Score and control

- Rational beat positions remain exact until frame resolution.
- Score is canonical for event-backed production; compatibility event dictionaries are not a second scheduler.
- MIDI 1.0 is an interchange layer with semitone/tick limitations. Reawarp Score retains exact pitch/event context in its own metadata.
- Automation target units, ranges, scopes, interpolation and destination identity are explicit.
- Whole-field texture/ambience remain specialist passes until they have valid event-level semantics.

### Effects and playback

- Pyo is optional and lazy-loaded. The FX Lab can audition a standalone file or an active project's dry stem; a custom chain can be assigned to that stem in Stem Mixer.
- Stem Mixer pre-render uses a cancellable background worker and reuses the rendered result for channel/master preview and export. If Pyo is unavailable, it reports the failure and retains dry source material rather than claiming a processed result.
- M22 routing v3 keeps fixed per-stem inserts and wet-only SPACE/ECHO returns. There are no arbitrary graphs, feedback loops or live plug-ins.
- M24 processors remain separate reference modules until an explicit production-routing design and sign-off exist.

### Project portability and schemas

Project archives include application/render provenance, generation configuration, Score, events, source dependencies and a SHA-256 file inventory.

- Asset policy `copy` embeds referenced samples under `assets/` by default. `reference` retains external paths and hashes; those sources must remain accessible.
- Missing or changed assets are reported; Reawarp does not silently substitute another sample.
- Existing project v1 exports without a manifest remain loadable. Unknown manifest versions require explicit migration.
- Hash identity of an archived artifact is distinct from a regenerated render; cross-platform bit-identical output is not promised.

| Data | Schema | Compatibility |
|---|---:|---|
| Project export | 1 | Existing v1 projects remain readable |
| Project manifest | 1 | Validated; unsupported versions fail explicitly |
| Events | 1 | Existing v1 event data supported |
| Score | 1 | Existing v1 Score data supported |
| FX routing | 3 | v1/v2 migrate in memory |
| FX automation | 1 | M13 schema remains supported |
| Sound Object | 1 | Strict version/range validation |
| Variation candidate | 1 | Legacy records default to v1 |

The M25 compatibility fixture is `tests/fixtures/m25/legacy_contracts_v1.json`.

## Validation and remaining acceptance work

CI currently targets Ubuntu/Python 3.10–3.12 and Windows/Python 3.11. It runs the pytest suite, package compilation, CLI/library smoke checks, IRO catalog checks, role-aware routing contracts, M24.1–M24.4 short reference smokes and M25 5-second 48 kHz archive/reopen smoke.

**Still required:**

1. Confirm the current M26 regression run passes on all four CI jobs.
2. Run 30-second and 180-second 48 kHz generation/export/reopen on the target Windows machine; record hardware, Python/NumPy/SciPy versions, render time, real-time factor and peak memory. Choose explicit budgets before declaring a budget-gated sign-off:
   ```powershell
   python scripts/benchmark_m25.py --durations 30 180 --sample-rate 48000 --output output/m25-target-windows.json
   ```
   Add agreed `--max-rss-gb` and `--max-wall-seconds` limits for explicit pass/fail budget checks.
3. Install `.[pyo]` and audition role inserts, sends, returns and the complete mix on the target Windows setup. Check matched-level, low-volume and mono playback.
4. Perform human listening across M18–M24 composition/sound-object/DSP features. CI does not certify musical identity, masking, negative space or taste.
5. Keep M24.5 sidechain, M24.6 feedback networks and M24.7 parallel paths as separate design decisions, not automatic follow-ons.

## Engineering principles for future work

- Profile before optimising; avoid speculative GPU/native rewrites and unbounded caches.
- Keep native backends optional and lazy-loaded; review wheels, runtime and redistribution licences.
- Separate source identity from processing identity.
- Prefer explicit schemas and small service boundaries over moving all UI state at once.
- Do not silently normalise sources, substitute missing files or coerce unknown schemas.
- Use objective metrics to inform listening, never as an artistic ranking.

## Documentation that remains separate

The following documents are maintained separately from this delivered-milestone ledger:

- [Implementation notes](IMPLEMENTATION_NOTES.md) — architecture and engineering conventions.
- [M27–M34 development roadmap](ROADMAP_M27_M34.md) — detailed forward milestone specifications and implementation handoff for agents.
- [Dependency ecosystem](DEPENDENCY_ECOSYSTEM.md) — dependencies, platform constraints and licences.
- [Sample banks and hybrid composition](SAMPLE_BANKS_HYBRID_COMPOSITION.md) — source selection and hybrid percussion.
- [IRO integration](IRO_INTEGRATION.md) — shared manifests, source identity and missing-asset policy.
- [IDM field guide](guides/IDM_Field_Guide_for_Composers_Producers_and_Programmers.md).
- [Composition atlas](guides/IDM_Composition_Atlas_Patterns_Phrases_and_Track_Structures.md).
- [Sound-design architecture](guides/IDM_Sound_Design_Synthesis_and_Hybrid_Sound_Architecture.md).
- [Advanced composition appendix](guides/IDM_Advanced_Composition_and_Generation_Appendix.md).

The completed milestone history remains consolidated in this document. Future M27–M34 specifications are maintained in the dedicated roadmap so agents can work from a focused implementation brief.

---

