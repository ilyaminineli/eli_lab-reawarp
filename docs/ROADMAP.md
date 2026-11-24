# Reawarp roadmap — consolidated status and next milestones

**Updated:** 2026-11-24  
**Current implementation baseline:** M15 motif/orchestration implementation and cross-platform regression coverage landed on `main`; subjective listening validation remains pending; M14 target-machine profiling/listening also remains pending  
**Roadmap policy:** milestone documents describe implementation status and acceptance criteria. Proposed features must be labelled planned; they must not be presented as implemented.

## Product direction

Reawarp is an offline-first, deterministic IDM composition and sound-design laboratory. It is not intended to become a general-purpose DAW. Its distinctive value is the combination of mathematically derived rhythmic material, formal composition planning, independent stem regeneration, hybrid synthesis, break transformation, a personal sound library, and non-destructive offline mixing.

The canonical target workflow is:

`Configuration → Form/Role Plan → Score → Dry Stem Render → FX Routing/Automation → Export + Provenance`

The current application has strong components at most of these stages, but score-driven rendering is not yet complete. That is the main architectural bridge to build after reliability and profiling.

## Implemented baseline

| Area | Status | Notes |
|---|---|---|
| Deterministic event generation | Implemented | Named independent random streams and per-stem regeneration |
| Formal section planning | Implemented | Multiple structure grammars, deterministic flow operations and section-level controls |
| Pattern relationships | Implemented | Interlock, shadow, call-response and counter-accent families |
| Percussion and break generation | Implemented | Procedural lanes, imported break slicing and transforms |
| Melodic synthesis | Implemented | Distinct subtractive and alternative synthesis paths |
| Ambience/texture stems | Implemented | Separate generated roles |
| Project stems and provenance | Implemented | Dry stems, events and generation metadata |
| Score and MIDI interchange | Partially implemented | Rich score schema and conversion/export exist; score is not yet the renderer's authoritative input |
| Local sample/stem library | Implemented | SQLite indexing, descriptors, search, collections and genealogy |
| FX Lab and editable serial chains | Implemented | Optional Pyo offline backend and portable JSON |
| Role-aware inserts and shared returns | Implemented | Two fixed buses, dry-by-default routing |
| Beat-based FX automation | Implemented | Static-BPM lanes for insert wet, sends and return wet |
| GUI / CLI workflow | Implemented | Grouped Compose / Produce / Assets navigation, shared project context and transport, responsive splitters, and a project-aware Stem Mixer empty state; controller extraction remains planned |
| Regression testing | Implemented | M14 suite covers deterministic streams, transform edge cases, score/MIDI and project round trips, FX contracts, stem isolation and offscreen UI navigation; M15 motif/orchestration fixtures are being added |
| Target-machine DSP listening validation | Pending | Requires Pyo-enabled Windows render and critical audition |
| Performance benchmark baseline | Partially implemented | Reproducible benchmark harness and phase timings are present; target-Windows 30/180-second results are pending |

## Current focus — M14: Reliability and Performance Baseline

**Status:** Portable implementation and CI acceptance passed on `main` (commit `3ea19f7`). The milestone remains open for 48 kHz target-Windows 30/180-second profiling and Pyo-enabled critical listening.

**Goal:** Make changes to the generator safe, measurable and repeatable before expanding the composition and DSP surface.

### Delivered on `main`

- Expanded the pytest suite to 59 tests, including short/silent/stereo transform cases, seeded full-chain transforms, score JSON and MIDI round trips, exported-project reopen validation, and GUI navigation transitions.
- Added `GenerationConfig.from_dict`, PCM `read_wav` with preserved channel layout, and `ReawarpProject.load` with schema, configuration, timing, stem alignment, finiteness and score-metadata validation.
- Added a native Windows Python 3.11 CI job. Linux Python 3.10, 3.11 and 3.12 plus Windows Python 3.11 all pass the regression suite; CLI/benchmark/desktop smoke checks also pass.
- Retained the named-stream, exact-duration, dry-buffer immutability, FX routing and signal-diagnostic checks already in the suite.

### Remaining sign-off

1. Run the 30-second and 180-second benchmark cases at 48 kHz on the target Windows machine; record the processor, memory, Python, NumPy, SciPy versions, render time, real-time factor and peak memory.
2. Profile any measured hotspots and optimise only where the evidence supports it, preserving deterministic output and the current signal contracts.
3. Run the optional Pyo-enabled integration and critical listening checks on the target audio setup, including low-volume and mono compatibility.

### Explicitly out of scope

No new synthesis palette, arbitrary routing graph, convolution engine or GPU port in M14. The first navigation/layout redesign is included; a broader controller/service extraction remains a follow-on task.

## M15: Composition Director 2.0 — motifs, roles and transitions

**Status:** Implementation landed on `main`; 66 regression tests pass on Linux Python 3.10–3.12 and Windows Python 3.11. Subjective listening validation remains pending.

**Goal:** Make long-form arrangements feel composed rather than like a sequence of section-level parameter states.

### Delivered in this increment

- Stable motif identity extracted from a named source phrase; section instances share the identity and carry explicit transformation history.
- Deterministic repetition, displacement, fragmentation, augmentation/diminution, inversion, retrograde, rhythmic shadow, call/response, return and dissolve transformations.
- Motif-driven melody events on the shared sixteenth-note clock. The same phrase rhythm can create restrained hi-hat shadows and snare responses.
- Seven-role section orchestration plans for kick, snare, hats, break, melody, texture and ambience, each with activity, density, syncopation, register, brightness, space and motif relation.
- Bar-aligned transition windows derived from the phrase grammar. Transition envelopes implement pickups/fills, subtraction, rhythmic collapse, hard cuts/silence gates, reverse-swell/riser intentions, call/response reassembly and echo handoffs.
- Independent Generator controls for density, syncopation, instability, melodic activity, register, tonal brightness and spatial intent.
- Project metadata records the motif, every section instance, role plans, transition gestures and the axis values used.

### Acceptance criteria

- Fixed seeds reproduce motif identity, section transformations, cross-role accents and role/transition plans.
- Return sections recall the source motif; development/contrast sections change selected dimensions while retaining identity.
- Each section has a distinguishable orchestration purpose independent of a single energy scalar.
- Transition gestures remain inside their source phrase/bar window; all rendered buffers retain exact duration and aligned stems.
- Regenerating melody does not mutate the other role stems; named random streams remain isolated.
- Tests cover transformation rules, role-plan determinism, transition boundaries, cross-role motif use and full-engine integration.

### Listening protocol

Compare the same seed in a full render and in isolated kick/snare/hat/melody/texture/ambience stems. Listen for the anchor phrase in establishment and return sections, controlled transformation in development, a recognisable call/response in contrast, deliberate subtraction through drop/void sections, and enough negative space around transitions. Numeric tests establish timing and repeatability, not subjective musical quality.

## M16: Score-driven render core

**Status:** Partially implemented on main. A score-native offline renderer, shared beat/frame timeline, typed automation control bus and score provenance are landed. Full migration of the existing M8–M15 Generator planners and production synthesis loops remains open.

**Goal:** Make the universal score the canonical symbolic event representation consumed by the audio renderer.

### Delivered in this increment

- RenderTimeline maps rational beats to seconds and sample frames through step and linear tempo maps, and maps frames back to musical time.
- Meter-map bar/beat queries are available on the render timeline; meter changes remain independent from tempo and pattern cycles.
- ScoreRenderer consumes Score.events, schedules note/hit/grain/trigger events onto sample frames, and renders aligned dry per-voice stereo stems.
- Production/custom voice callbacks receive a ScheduledScoreEvent and shared AutomationControlBus; the score core owns frame placement, velocity, mono panning and finite-buffer validation.
- AutomationTargetRegistry defines synthesis, FX and MIDI control domains, units, value types, ranges and interpolation. Beat-, second- and frame-based lanes are evaluated against the same absolute frame clock.
- Project-derived scores retain score-renderer version, source generator version, root seed, sample rate, frame count, duration, named seed streams and generator-family provenance.
- Existing project and score schema version 1 remain readable; MIDI 1.0 precision and metadata limitations are documented in docs/M16.md.

### Remaining integration work

1. Convert the existing percussion, motif and melody planners to emit MusicalEvent records directly instead of legacy seconds-based event classes.
2. Adapt production instrument, sample-trigger and break-slice renderers to consume ScheduledScoreEvent from the canonical score.
3. Replace remaining constant-4/4 section and bar timing in the legacy Generator with MeterMap queries where musical form is expressed in bars.
4. Route the existing M13 FX automation representation into the typed score control bus.
5. Complete target-Windows performance profiling and critical listening after the production renderer adapters land.

### Acceptance criteria

- Score event positions correspond to actual render frames through step and ramp tempo maps.
- Meter changes produce correct bar/beat queries.
- Repeated rendering of the same score is deterministic within the documented environment contract.
- Synthesis and FX callbacks can evaluate typed control lanes on the same absolute frame clock.
- Existing project exports remain readable and new exports contain renderer and generation provenance.
- The legacy Generator no longer maintains a parallel seconds-based event timeline; this final criterion remains open.

See M16.md for implementation details and the score-render API.
## M17: Canonical score-native composition pipeline

**Status:** Implemented on `main`. M17.1–M17.4 adapters are now the production path used by `ReawarpEngine.generate()`. M17.5 plans a canonical rational-beat Score before rendering, schedules all event-backed voices through ScoreRenderer, and derives legacy project event dictionaries from Score.events. Texture and ambience remain specialised whole-field renderers represented by symbolic Score markers.

**Goal:** Make the universal score the only event-scheduling authority while preserving the existing M8–M15 musical grammar, instrument catalogue, sample bank logic and non-destructive production workflow.

### Scope

- Direct score emission from percussion, melody, motif and cross-role accent planners.
- Rational-beat orchestration shaping and meter-aware phrase/section boundaries.
- Production adapters for subtractive/FM/modal/other voices and role-specific percussion synthesis.
- Sample-bank trigger, hybrid transient/body and frame-domain break-slice adapters.
- Conversion of the M13 insert/send/return automation model to the typed score control bus.
- Compatibility projections for existing project events, legacy automation JSON and project schema.

### Implementation slices

1. **M17.1 — Planner emission:** percussion and melody planner adapters emit MusicalEvent from sixteenth-grid positions; stable motif/style/role metadata and named stream seeds are retained. A compatibility projection exists for legacy consumers. Melody notes carry separate gate and scheduled release spans.
2. **M17.2 — Production voices:** `synthesis/score_voices.py` supplies deterministic per-event callbacks for subtractive, FM/hybrid and extended melody palettes, profile-based kick/snare/hat, and synthetic break voices. Callbacks use event-derived random streams and the shared control bus for pitch-at-onset, cutoff/resonance and gain automation. Each result is fitted to the exact scheduled frame span.
3. **M17.3 — Samples and breaks:** `synthesis/score_samples.py` turns drum hits into first-class sample trigger events, preserves sample/IRO metadata and indexed features, and resolves deterministic anchor/section/cycle/return variant choices from score metadata. Hybrid transient/body and layered sample sources are mixed as separate same-onset score events. Imported break assets are transformed, transient-sliced and trimmed to the next trigger or current bar boundary in absolute scheduled frames, with 2 ms edge fades. `render_score(score, config=config)` composes these callbacks with M17.2 synthesis voices.
4. **M17.4 — FX automation:** `fx_automation.py` converts M13 schema-v1 target IDs and per-point `hold`/`linear`/`smooth` curves to typed beat-addressed `AutomationLane` records. Per-point segment interpolation is preserved in `AutomationPoint.interpolation_to_next`; score smoothstep evaluates as the same smoothstep rather than being flattened into cubic. `ReawarpEngine.render_score(..., fx_automation=legacy_json)` attaches those lanes to the score and validates them with a stem-aware FX target registry. `render_fx_routing(..., controls=rendered.controls)` consumes the exact same AutomationControlBus for insert wet, sends and shared-return wet; legacy `automation=...` JSON rendering remains supported and mutually exclusive with `controls`. `score_to_fx_automation()` exports the typed lanes back to the unchanged M13 schema-v1 structure. The score beat-to-frame mapping also honours tempo-map ramps.
5. **M17.5 — Canonical generation cutover (implemented):** `ReawarpEngine.plan_score()` exposes deterministic symbolic planning without rendering. `generate()` now builds that Score first, renders event voices through ScoreRenderer, and only then projects `ReawarpProject.events` as compatibility/export records. `ScoreRenderResult.score` returns the actual prepared Score, including sample triggers and provenance. `ReawarpProject.to_score()` returns this canonical object; the former renderer remains available as `generate_legacy()` for controlled comparisons. The whole-field noise texture and ambience passes remain specialised, with marker events in the Score recording their existence and render intent.

### Acceptance criteria

- Fixed seeds produce identical planned score events and repeatable stems; render-performance measurements remain observational metadata.
- No event time is routed through a seconds-based intermediate before frame placement.
- Specialist voice callbacks use the event schedule, return exact-length finite buffers and do not share mutable RNG state.
- Sample variant switching, motif cross-role relationships, hybrid percussion and break-slice trimming preserve existing musical semantics; sample source decisions and provenance are retained as score metadata.
- Existing exported projects and automation files remain readable.
- All event-backed production lanes render through ScoreRenderer; texture/ambience whole-field renderers may remain specialised until they have event-level semantics.
- Listening and target-machine performance sign-offs remain separate from automated test acceptance.

See [M16 — Score-driven render core](M16.md) for the timing/render foundation and detailed M17 migration contract.

## M18: Mixer and routing quality

**Goal:** Make current two-bus routing more transparent and reliable before generalising it.

### Scope

- Clear pre/post insert and pre/post fader send semantics.
- Direct/insert/send/return/master audition and level meters.
- Peak, RMS and headroom diagnostics at each routing boundary.
- Better cache invalidation and asynchronous/off-thread render coordination.
- Explicit tail and alignment rules for inserts and shared returns.
- Snapshot/compare for routing and automation settings.
- Preserve existing portable JSON through versioned migration.

### Acceptance criteria

- Routing changes refresh only affected processing where safe.
- Gain/pan/mute/solo behaviour is consistent between preview and export.
- Dry stems remain unchanged; exports contain complete return tails.
- Mono compatibility and headroom are checked.
- All UI controls have documented and testable effect on render or audition.

## M19: Advanced DSP research modules

**Goal:** Add selected advanced processing only after the core and routing are stable.

Potential independent modules:
- convolution reverb and impulse-response library;
- spectral delay and frequency-dependent feedback;
- cross-synthesis and ring/frequency modulation;
- oversampled nonlinear processing;
- sidechain envelope extraction and cross-stem detector routing;
- optional user-defined bus graphs and parallel branches.

Each module must define CPU/memory budget, latency/tail behaviour, optional dependency policy, portability, headroom strategy and regression fixtures. Do not bundle all modules into one milestone.

## M20: Iteration and creative workflow

**Goal:** Reduce friction when exploring and selecting variations.

Potential scope:
- multi-variation stem browser with seed/parameter comparison;
- project snapshots and matched-level A/B audition;
- waveform/spectrogram comparison for dry, processed, send, return and master;
- contextual sample-library audition and replace/keep workflow;
- export profiles and project portability checks;
- extracted UI controllers/services and more modular page construction.

## Cross-cutting engineering requirements

Every milestone should satisfy these requirements:

1. **Determinism:** new random sources use named/versioned streams; unrelated lanes remain independent.
2. **Non-destructive audio:** dry sources are retained; processing writes separate results.
3. **Portable data:** user-authored settings use validated, versioned schemas.
4. **Optional dependencies:** experimental/native backends remain optional and lazy-loaded.
5. **Signal safety:** all outputs are finite, bounded as specified, and report peak/tail behaviour.
6. **Testability:** musical rules and signal contracts have automated tests; subjective sound requires a listening protocol.
7. **Documentation accuracy:** mark features as implemented, partial, planned or experimentally unverified.
8. **Performance evidence:** profile before optimisation and report measured results on the target platform.

## Milestone status policy

- **Implemented:** code exists and has automated coverage for its key behaviour.
- **Partially implemented:** core workflow exists, but key advertised semantics or integration remain incomplete.
- **Experimentally unverified:** code exists but depends on target-machine execution/listening not represented in CI.
- **Planned:** specification only; no claim of implementation.

Use this vocabulary in future milestone documents and the README. Historical M1–M13 specifications should be retained as the development record; this consolidated roadmap is the current forward plan.
