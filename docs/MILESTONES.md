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
| **M26 — Connected project FX and complete handoff** | Implemented on `main`; corrected regression suite pending CI | FX Lab loads active project channels and can assign custom serial chains as per-stem inserts. Stem Mixer can pre-render channel inserts/SPACE/ECHO returns, generate deterministic role-aware FX alternatives from project context/seed, audition them from a temporary disk cache and apply a chosen route. Desktop Export creates a ZIP handoff containing routed master, original dry stems, returns, Score/events, routing/automation/mix data, copied source assets, manifest and combined/per-voice MIDI. |

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

The following documents are reference material, not duplicate milestone plans:

- [Implementation notes](IMPLEMENTATION_NOTES.md) — architecture and engineering conventions.
- [Dependency ecosystem](DEPENDENCY_ECOSYSTEM.md) — dependencies, platform constraints and licences.
- [Sample banks and hybrid composition](SAMPLE_BANKS_HYBRID_COMPOSITION.md) — source selection and hybrid percussion.
- [IRO integration](IRO_INTEGRATION.md) — shared manifests, source identity and missing-asset policy.
- [IDM field guide](guides/IDM_Field_Guide_for_Composers_Producers_and_Programmers.md).
- [Composition atlas](guides/IDM_Composition_Atlas_Patterns_Phrases_and_Track_Structures.md).
- [Sound-design architecture](guides/IDM_Sound_Design_Synthesis_and_Hybrid_Sound_Architecture.md).
- [Advanced composition appendix](guides/IDM_Advanced_Composition_and_Generation_Appendix.md).

The per-milestone Markdown files and dated assessment snapshots have been consolidated into this document. Their previous versions remain available in Git history.

---

# Next roadmap — musical agency, perception and finished work (M27–M34)

**Roadmap assessment:** 26 November 2026  
**Basis:** the four companion guides in `docs/guides/`: the IDM Field Guide, Composition Atlas, Sound Design/Synthesis/Hybrid Sound Architecture, and Advanced Composition and Generative Systems.

This roadmap deliberately does not treat “more algorithms”, “more parameters”, or “more complexity” as progress by themselves. It follows the guides' central distinction between producing events and composing relationships: the system should establish recognisable material, develop it at several time-scales, preserve intentional invariants, orchestrate it for listener attention, and help a human composer audition, subtract, freeze, arrange and finish.

## Guide-derived design principles

These principles are the acceptance lens for every milestone below.

1. **Identity before accumulation.** Start with an artistic question and a restricted vocabulary. Prefer a small number of identity-bearing materials over a default stack of unrelated layers. The Composition Atlas's A/B/C model (anchor, counter-idea, destabilising/transition idea) should become an optional composition scaffold, not a mandatory template.
2. **Pulse and reference are compositional resources.** Complexity is not the goal. The system must be able to maintain a stable anchor while the surface mutates, or maintain a stable surface while the anchor moves. Absence of an anchor is valid when intentional and perceptible.
3. **Change is hierarchical.** Event, pattern, phrase, section and whole-track decisions must have separate responsibilities, state and random streams. Local probability must not silently rewrite global form.
4. **Mutations need permissions and memory.** Every layer needs an identity, may-change fields, must-preserve fields, bounds, rate, decision boundary and a stop condition. Repetition is allowed to remain repetition; changes should be purposeful and often limited to one principal dimension.
5. **A phrase is perceptual, not a fixed bar count.** Phrase boundaries may be regular, asymmetric, open, interrupted or defined by a sound gesture, arrival or silence. Section functions must describe a musical job, not merely a preset label.
6. **Sound objects have identity and context.** Source, excitation, resonance, spectrum, envelope, motion, space and musical role should be inspectable. Source identity must remain distinguishable from processing identity; transient/body/tail design and resampling are compositional operations.
7. **Orchestration is about attention.** Foreground, midground, background, pulse, counter-rhythm, motif, harmonic field, texture and absence should have intentional spectral, registral, temporal and spatial relationships. Masking can be a deliberate effect, not just a defect to EQ away.
8. **Evaluation is listening-led.** Continuity, identity, contrast, legibility, motif development, orchestration, pacing, surprise, emotional coherence and technical integrity are useful prompts—not a numerical quality ranking. Subtraction, invariance and context tests must be built into the workflow.
9. **Finish the work.** Generation is not the finish line. A system should support candidate selection, manual revision, freeze/print/resample, transitions, endings, mix checks and durable provenance.

## Priority order

| Priority | Milestones | Why this order |
|---|---|---|
| P0 — Core composition agency | M27, M28 | Explicit identity/invariants and meaningful phrase development are foundations for all later features. |
| P1 — Perceptual arrangement | M29, M30 | Role relationships, attention and transitions should act on the new phrase-level representation. |
| P2 — Sound-object workflow | M31 | Connects the composition engine to the existing M21 sound-object architecture without opening an unbounded DSP graph. |
| P3 — Critical listening and finish | M32, M33 | Turns generated material into context-tested, selected, printable and finished work. |
| P4 — Conditional research | M34 | New analysis-driven and advanced processing methods proceed only when a real composition problem remains unsolved. |

---

## M27 — Artistic Intent, Material Vocabulary and Mutation Contracts

**Priority:** P0  
**Status:** Planned  
**Depends on:** M15, M18, M20, M21, M23  
**Primary guide basis:** Field Guide §§9, 12, 14, 17; Composition Atlas §§1–3; Advanced Appendix §§10.2, 13, 16–17.

### Goal

Give each composition an explicit, inspectable identity before generation. Replace the idea that a randomised parameter set is itself an artistic direction with an optional *composition brief* that establishes the world, materials, anchor and permitted behaviours.

### Scope

- Introduce a versioned `CompositionBrief` independent of low-level `GenerationConfig`.
- Brief fields: artistic question/central tension; listening mode; material vocabulary; A/B/C identities; anchor type and stability; pitch/tuning field; source families; target contrasts; intended ending behaviour.
- Add per-role mutation contracts: role identity, mutable fields, invariants, allowed ranges, mutation cadence, valid decision boundaries, and stop/freeze conditions.
- Support contracts at event, pattern, phrase and section scales. Use the existing independent seed-stream principle; identify streams by stable role/scale/object identifiers.
- Add a “bounded exploration” mode: randomise only fields explicitly marked mutable. Preserve BPM and duration by default, but allow an explicit brief-level tempo/form policy when requested.
- Preserve sample/source IDs and hashes. A brief may select from available sources but must not invent missing assets or silently substitute them.
- Surface a compact Intent panel in Generator; keep detailed implementation values inspectable in an advanced view.

### Acceptance criteria

- A saved brief round-trips through a versioned schema and is embedded in project provenance.
- Identical brief, generator version and seed reproduce the same brief-derived plan.
- Changing the ornament stream does not change the anchor, section order or unrelated role streams.
- Mutations outside declared permissions are rejected or explicitly reported.
- BPM, duration, source identity and other declared invariants remain unchanged.
- Legacy projects without a brief load as an explicitly unstructured/legacy brief; no silent synthetic brief is written back.

### Non-goals

- No “AI writes a perfect brief” claim.
- No replacement of `GenerationConfig`, Score or project archive.
- No requirement that every piece use an anchor or three-material structure.

---

## M28 — Phrase Grammar, Motif Families and Candidate Freeze

**Priority:** P0  
**Status:** Planned  
**Depends on:** M27; builds on M15, M19, M20, M23  
**Primary guide basis:** Composition Atlas §§7, 10, 12–14; Advanced Appendix §§2, 10.1, 10.5, 12, 17, 20.

### Goal

Move the centre of generation from isolated patterns and fixed bar-based sections toward related phrase candidates with perceptible function, controlled transformation and identity-preserving returns.

### Scope

- Add explicit phrase objects with irregular beat spans, open/closed/fragmentary state, function, motif references, internal cycles and boundary events.
- Add phrase functions: presentation, continuation, departure, response, suspension, arrival, interruption, reprise and exit. Permit project-specific extension.
- Build motif families across pitch, rhythm, timbre, envelope, register, sample, spatial and silence dimensions.
- Make transformation operations explicit and provenance-aware: transposition, inversion, retrograde, augmentation, diminution, fragmentation, extension, truncation, displacement, re-orchestration, resampling and timbral translation.
- Implement a variation ladder from subtle to disruptive; enforce “one principal change” as a selectable development policy, not an absolute rule.
- Generate multiple phrase candidates offline from a frozen base; audition them in isolation and in preceding/following context.
- Freeze a candidate into the Score with its parent identity, source events, seed streams, config delta, selection notes and generator version.
- Add explicit “continue evolving”, “freeze”, “branch from frozen phrase” and “restore base” actions. Frozen phrases must not silently change when another layer is regenerated.

### Acceptance criteria

- Phrase timing supports rational beat positions and non-integer bar lengths; frame resolution remains downstream.
- Each generated variation records which motif dimensions changed and which remained invariant.
- Frozen phrase content and unrelated score regions are bit-identical under unrelated regeneration.
- The same candidate request and frozen base reproduce the same candidate list.
- A user can compare a candidate alone, after its predecessor and before its successor.
- Phrase/Score export and reopen preserve lineage, edits and freeze state.
- Tests include open phrases, omission, unusual phrase lengths, delayed returns and deliberate no-change repetition.

### Non-goals

- No fixed 4/8-bar phrase assumption.
- No automatic quality score that decides the winning phrase.
- No continuous regeneration of material already selected by the composer.

---

## M29 — Perceptual Orchestration, Figure/Ground and Attention Map

**Priority:** P1  
**Status:** Planned  
**Depends on:** M27, M28; builds on M18, M20, M21, M22  
**Primary guide basis:** Advanced Appendix §§1, 7, 18; Field Guide §§5, 23; Sound Design Guide §1.

### Goal

Make orchestration decisions about what the listener notices, follows and remembers—not just which stems are enabled.

### Scope

- Add an arrangement-level attention map with foreground, midground, background, anchor, counter-rhythm, motif, harmonic field, transition and absence roles.
- Allow role changes over phrase/section boundaries with explicit hand-offs and return identities.
- Track spectral zone, register, onset density, transient strength, sustain, spatial position and intended prominence as descriptors—not rigid mix rules.
- Add a masking/conflict inspector that reports possible competition in time, register, transient or stereo space and explains the evidence.
- Support intentional masking/merging as an explicit relationship, not every overlap as a warning.
- Introduce composition-level “focus” and “recede” operations that can be expressed through presence, register, articulation, density and space before resorting to volume.
- Add low-volume and mono checks as separate production views, not destructive master processing.
- Preserve kick/sub protection and existing M22 bounded routing contracts.

### Acceptance criteria

- An arrangement can show which roles are intended to be perceptually dominant at any phrase.
- A hand-off is atomic at a declared musical boundary; no partial intermediate scene is audible.
- Warnings identify affected roles, time range and descriptor basis, and can be dismissed as intentional with provenance.
- “Foreground” can change without requiring master gain automation.
- Mono/low-volume checks operate on analysis/audition copies and never rewrite production audio.
- Human review can mark a conflict as useful, masked, or unresolved.

### Non-goals

- No automatic EQ as the default answer to every conflict.
- No single numerical “clarity score”.
- No mandatory spectral slot for each instrument.

---

## M30 — Transition Grammar, Section Memory and Ending Director

**Priority:** P1  
**Status:** Planned  
**Depends on:** M28, M29; builds on M7, M15, M20  
**Primary guide basis:** Field Guide §§8–9; Composition Atlas §§13–14; Advanced Appendix §§5–6, 12, 17, 20.

### Goal

Make transitions and endings first-class compositional events. Long-form work needs purposeful state changes, not simply a succession of section presets or a fade-out added at the end.

### Scope

- Create typed transition objects: additive, subtractive, filtered/registral, rhythmic displacement, metric reinterpretation, fragmentation, overlap, silence, false return and motif-as-bridge.
- Give each transition a preparation, change and consequence/arrival phase.
- Track section memory: recent materials, last use, transformation history, energy/density trajectory, unresolved expectation and return opportunities.
- Add delayed return, transformed reprise, interrupted cadence, residue, dissolve and hard-stop ending strategies.
- Allow an ending to preserve a residual A/B/C identity without introducing new section-level randomness.
- Make tempo-map changes an explicit composition choice with rational beat location, clear conversion semantics and user review; keep fixed BPM as the default.
- Scene changes affecting several roles must be atomic at a Score boundary.

### Acceptance criteria

- Transition plans specify source state, target state, changed dimensions, preserved identity and boundary.
- Every transition has deterministic timing and can be inspected/reproduced.
- Ending plans are present in the Score and do not depend on an arbitrary audio fade alone.
- A frozen or selected section cannot be modified by an unrelated later section mutation.
- Tests cover asymmetrical phrases, no-transition repetition, abrupt rupture, silence, false return and multiple ending types.
- Tempo-map behaviour is tested for beat-to-second and beat-to-frame conversion; no implied continuously varying tempo is assumed.

### Non-goals

- No mandatory narrative arc or classical cadence.
- No requirement to automate tempo.
- No automatic “drop” or climax in every piece.

---

## M31 — Sound-Object Workshop and Resampling Lineage

**Priority:** P2  
**Status:** Planned  
**Depends on:** M27–M29; builds on M21, M22, M25, M26  
**Primary guide basis:** Sound Design Guide §§1–6 and closing note; Field Guide §7; Advanced Appendix §§7–9, 17.

### Goal

Make the existing sound-object and hybrid-instrument architecture directly usable as a compositional workshop: create a recognisable sound family, transform it in deliberate stages, and reuse printed results without losing source/processing provenance.

### Scope

- Build a graphical sound-object editor over the existing M21 editor-facing model; do not duplicate renderer or patch logic in Qt.
- Expose source, excitation, resonance, spectrum, envelope, motion, space and context/role as organised parameter groups.
- Support transients, bodies and tails as independently auditioned layers that can also be heard as one object.
- Add source-to-object and object-to-role workflow: one sound object can appear in several roles, but each assignment retains a separate processing identity.
- Add a non-destructive resampling/print operation for a selected sound, phrase, stem or FX stage; generated audio becomes a new versioned source object.
- Preserve original samples and dry stems; store parent source IDs/hashes, transform chain, render settings, seed, and output hash.
- Add A/B auditions for source, intermediate stages and final object with matched-level copies.
- Introduce optional coherent-family generation: related kick/snare/hat/metallic/percussive objects share a material language without becoming identical.
- Keep complex M24 processors opt-in and use bounded M22 routing; no arbitrary processing graph is implied.

### Acceptance criteria

- A user can create/edit/save a sound object, audition each layer, assign it to a role, and reopen it with all relationships intact.
- Every printed/resampled source has immutable lineage to its source(s), processing graph and render parameters.
- Source audio is never overwritten; missing source assets are reported.
- Same source, patch version, seed and renderer version reproduce the same print within the documented environment contract.
- An object can be evaluated solo and in arrangement context.
- UI remains a thin client of the sound-object service and remains usable without optional native backends where possible.

### Non-goals

- No mandatory external plug-in host.
- No unbounded modular routing editor.
- No rewriting the M21 renderer merely to fit a new UI.

---

## M32 — Critical Listening Workbench and Contextual Evaluation

**Priority:** P3  
**Status:** Planned  
**Depends on:** M28–M31; builds on M22, M23, M25  
**Primary guide basis:** Advanced Appendix §§15, 18; Field Guide §§9, 23–24, 26; Composition Atlas §§18 onward.

### Goal

Make the guide's subtraction, invariance and context tests executable as repeatable listening sessions. Objective analysis should help explain what is happening, never rank a piece as good or bad.

### Scope

- Extend M23's candidate comparison into composition-level listening sessions.
- Add contextual audition sets: solo phrase; predecessor→candidate; candidate→successor; full section; full track; reduced-density and altered-register versions.
- Add guided subtraction passes by role group and by selected percentage; support restore/keep decisions and maintain a reversible edit history.
- Add invariance sessions: identify the anchor/motif/tuning/sound family, temporarily remove or transform other material, then record whether identity survives.
- Add technical diagnostics: peak/RMS/headroom, tail and silence, clipping, phase/mono compatibility, transient overlap, spectral occupancy, and loudness at more than one playback level where practical.
- Show analysis window/parameter choices; do not imply a spectrogram or one metric is “the truth”.
- Add a human-authored listening report with identity, continuity, contrast, legibility, motif development, orchestration, pacing, surprise, emotional coherence and technical integrity prompts.
- Keep blind/matched-level audition and avoid automatic “best candidate” selection.

### Acceptance criteria

- All audition transforms operate on disposable copies; the exported production mix is unchanged unless the user explicitly applies an edit.
- A listening session records the exact project revision, candidate IDs, audition transformations, levels and user notes.
- Every technical warning includes evidence and severity; it does not claim artistic failure.
- Analysis can be disabled and does not change rendered audio or deterministic generation.
- Listening report exports with the project archive and is readable without Reawarp.
- Automated tests verify measurement correctness, transform non-destructiveness and session provenance; listening quality remains human sign-off.

### Non-goals

- No machine-generated artistic score.
- No “AI mastering” replacing listening.
- No opaque black-box ranking or recommendation.

---

## M33 — Arrangement Editor, Manual Composition and Print-to-Track

**Priority:** P3  
**Status:** Planned  
**Depends on:** M28–M32; builds on M4, M5, M23, M25, M26  
**Primary guide basis:** Field Guide §9, especially print/edit/recompose and subtraction; Advanced Appendix §§17–18; Composition Atlas §§1, 12–18.

### Goal

Close the distance between an interesting generator result and a finished, deliberately arranged track. Reawarp remains an offline-first composition instrument, not a full DAW, but needs clear manual editing and finalisation gates.

### Scope

- Provide a structured arrangement view over Score phrases/sections and frozen candidate material.
- Permit non-destructive move, duplicate, trim, reorder, mute, layer exchange and replacement at phrase/section level.
- Provide explicit “print to new object/stem”, “freeze selection”, “branch arrangement” and “revert to generation” actions.
- Permit Score-aware edits while preserving rational time, phrase relationships, motif lineage and event provenance.
- Make transitions and endings editable in the same arrangement model.
- Add a finishing checklist: form/ending review, subtraction, identity/invariance, context, low-volume, mono, peak/headroom, missing sources and export integrity.
- Export an arrangement snapshot with Score, frozen choices, source lineage, MIDI, processed/dry stems and listening report.
- Keep manual edits distinguishable from generated material and support reversible edit history.

### Acceptance criteria

- A user can create a complete track from candidate phrases without regenerating selected material.
- All edits are reversible and recorded with actor/action/source revision.
- Frozen material stays unchanged when upstream generator parameters are edited.
- Arrangement reopens with the same ordering, timing, sources, transitions and ending.
- A finished export includes the final arrangement state and full provenance.
- The workflow can finish a piece without requiring arbitrary DAW-style clip editing.

### Non-goals

- No attempt to clone Ableton/Logic/Reaper.
- No real-time live arrangement engine.
- No destructive editing of original samples or generation bases.

---

## M34 — Audio-Conditioned Composition and Advanced DSP Research Gate

**Priority:** P4 / conditional research  
**Status:** Research gate; no implementation commitment  
**Depends on:** M27–M33; builds on M18, M21, M24, M25  
**Primary guide basis:** Field Guide §21; Sound Design Guide §§4–6; Advanced Appendix §§8–11, 15, 17.

### Goal

Evaluate whether audio analysis and the remaining advanced DSP ideas solve a demonstrated musical need after the composition and listening workflows are usable.

### Candidate directions

- **Audio-conditioned composition:** analyse an imported break, stem or reference audio at multiple windows; extract onset, RMS, centroid, flux, chroma/low-frequency descriptors; smooth and normalise; map to a small number of explicit musical macros with confidence, hysteresis, phrase-boundary updates and manual overrides.
- **Sidechain/envelope routing (existing M24.5 research topic):** explicit detector, envelope, smoothing, hysteresis and cross-stem control semantics.
- **Bounded feedback systems (existing M24.6 topic):** fixed-topology networks with gain stability, decay, reset, tail and headroom contracts.
- **Parallel processing branches (existing M24.7 research topic):** only if a documented use case cannot be represented by existing serial inserts and SPACE/ECHO returns.
- **Search/constraint/evolutionary approaches:** generate alternatives against declared hard constraints and musical objectives, then expose them for audition; numerical scores remain advisory.

### Gate questions

1. Which concrete musical problem is not already solved by M27–M33?
2. Can the method preserve composition identity and explicit invariants?
3. Is the analysis relationship audible, stable and understandable rather than a parameter-wiggle effect?
4. Can the behaviour be deterministic, bounded, resettable and provenance-aware?
5. What is the CPU/memory cost at 48 kHz for 30/180-second projects?
6. Is there a listening example showing benefit over the simpler existing approach?

### Acceptance criteria

- No M34 implementation begins without a short design note, baseline example and objective acceptance test.
- Audio-conditioned controls use confidence thresholds, smoothing, hysteresis, phrase-boundary commits and manual override.
- Any feedback or parallel processor has bounded gain, finite tails, headroom and hard-stop tests.
- The simplest implementation that answers the musical problem is preferred.
- M24.5–M24.7 status remains accurately marked until each separate design and listening gate passes.

---

## Cross-milestone architecture contracts

- **Canonical authority:** CompositionBrief expresses intent; the composition/phrase plan expresses structure; Score expresses event-backed musical content; dry stems express source audio; FX routing expresses processing; archive expresses the portable project. No layer silently supersedes another.
- **Time:** rational beats remain authoritative until frame rendering. Irregular phrases are not converted to fixed bar counts for convenience.
- **Determinism:** use named, independent random streams per scale, role, phrase and object. Persist generator version, configuration deltas, source hashes, lineage and manual/frozen decisions.
- **Mutability:** dry source, imported asset, frozen phrase and frozen candidate are immutable inputs. Mutations create new versions.
- **Perception:** diagnostics expose evidence and uncertainty. They do not make artistic judgements or force EQ/volume corrections.
- **Realtime boundary:** no new composition, DSP, file, UI or blocking work enters the audio callback. Prepare buffers off-thread and apply scene changes atomically at musical boundaries.
- **Optional dependencies:** new native DSP backends remain lazy-loaded, optional and license-reviewed. Prefer the NumPy reference and small auditable algorithms until profiling justifies another backend.
- **Scope discipline:** the next roadmap does not call for arbitrary FX graphs, GPU rewrites, a general-purpose DAW, an automatic mastering system, or maximum-parameter randomisation as a substitute for composition.

## Recommended implementation sequence

1. M27 — make artistic intent and mutation permissions explicit.
2. M28 — create, compare and freeze identity-bearing phrases.
3. M29 — orchestrate by listener attention and figure/ground.
4. M30 — build purposeful transition and ending behaviour.
5. M31 — make existing sound-object capability practical to use and resample.
6. M32 — add contextual listening and evaluation.
7. M33 — allow the composer to finish and archive a coherent arrangement.
8. M34 — only then decide whether audio-conditioned composition and further DSP warrant implementation.

A short, successful composition made from three related materials with one meaningful transformation and a deliberate ending is a better acceptance demonstration than a maximally dense render using every generator option.
