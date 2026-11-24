# Reawarp roadmap — consolidated status and next milestones

**Updated:** 2026-11-24  
**Current implementation baseline:** M13 merged on `main`  
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
| GUI / CLI workflow | Implemented | PySide6 UI, commands and render worker; main window orchestration is due for modularisation |
| Comprehensive regression testing | Not complete | Current docs describe compile/smoke validation; real unit/integration coverage is required |
| Target-machine DSP listening validation | Pending | Requires Pyo-enabled Windows render and critical audition |
| Performance benchmark baseline | Not complete | Must be measured before optimisation claims |

## Current focus — M14: Reliability and Performance Baseline

**Goal:** Make changes to the generator safe, measurable and repeatable before expanding the composition and DSP surface.

### Scope

1. Reintroduce a focused `tests/` suite.
2. Protect deterministic stream derivation and lane independence.
3. Validate event timing, composition boundaries and exact render duration.
4. Validate signal invariants: finite samples, expected shape, peak limits, no accidental source mutation and aligned dry stems.
5. Test break transform edge cases, silence, short clips, stereo input, and boundary fades.
6. Test FX stage/routing/automation schemas, tails and dry-source immutability without requiring Pyo.
7. Add benchmark cases for 5 s, 30 s and 180 s at 48 kHz; measure per-stage render time and peak memory.
8. Add supported Windows/Python CI coverage, with optional Pyo integration tests separated from core CI.
9. Extract a small signal diagnostics module used by tests and audition reports.

### Acceptance criteria

- Same version, environment, config and seed reproduce the expected events and audio within declared tolerances.
- Regenerating one stem preserves unrelated stems and event lanes.
- Every rendered buffer has the expected shape, sample rate, finite values and documented peak/headroom behaviour.
- FX routing and automation never mutate dry input buffers.
- Core installation and smoke tests do not import or require optional Pyo.
- Benchmarks report a baseline with hardware/software metadata and no unsupported optimisation claims.
- CI exercises unit tests, CLI smoke tests, JSON round trips and offscreen UI construction.

### Explicitly out of scope

No new synthesis palette, arbitrary routing graph, convolution engine, GPU port or broad UI redesign in M14.

## M15: Composition Director 2.0 — motifs, roles and transitions

**Goal:** Make long-form arrangements feel composed rather than like a sequence of section-level parameter states.

### Scope

- A stable motif model: identity, source phrase, role, register, rhythmic/pitch contour and transformation history.
- Shared motif transformations across roles: repetition, displacement, fragmentation, augmentation/diminution, inversion/retrograde where musically applicable, rhythmic shadow and call-response.
- A per-section role plan for kick, snare, hats, break, melody, texture and ambience.
- Role entrances/exits, density/activity, register, brightness and spatial intention.
- Transition gestures: fills, subtraction, silence, pickups, reverse swells, rhythmic collapse, register shifts, echo handoffs and motif previews.
- Phrase-aware repetition: retain anchors while changing selected details.
- Clear controls that separate density, syncopation, instability, melodic activity, register, brightness and space.

### Acceptance criteria

- Fixed seeds produce recognisable motif identity across multiple sections.
- Each section has a distinguishable orchestration purpose, not just a higher or lower energy scalar.
- Transition gestures fit within bar/phrase boundaries and do not create accidental truncation or timing drift.
- Tests cover motif transformation and role-plan determinism.
- Listening fixtures demonstrate contrast, continuity and intentional negative space.

## M16: Score-driven render core

**Goal:** Make the universal score the canonical symbolic representation consumed by the audio renderer.

### Scope

- Generation planners emit score events and automation lanes.
- Renderers consume score events rather than maintaining a parallel private event timeline.
- Tempo-map and meter-map aware beat-to-frame conversion.
- Rational beat positions remain exact until frame conversion.
- Typed control lanes share a single timebase across synthesis and FX.
- Project export stores canonical score, renderer version and provenance.
- MIDI import/export round trips have documented representational limits.

### Acceptance criteria

- Score events correspond to actual rendered note/hit/trigger positions.
- Step and ramp tempo maps render at the expected musical positions.
- Meter changes produce correct bar/beat queries and phrase boundaries.
- Rendering the same score twice is deterministic within the documented environment contract.
- Existing project exports remain readable through a migration or compatibility strategy.

## M17: Synthesis modulation and musical automation

**Goal:** Make automation affect the sound-generation process itself, not only post-processing wet/send levels.

### Scope

- Automate filter cutoff/resonance, oscillator or FM parameters, envelope times, pitch/register, modulation depth and selected spatial controls.
- Automate role density, activity and rhythmic mutation at section/phrase boundaries.
- Reuse the score's beat/bar/section timeline and typed target validation.
- Support hold, linear and smooth curves first; add more curve types only when needed.
- Provide preview of automation shape and a clear source/static value fallback.
- Preserve deterministic evaluation and avoid random modulation unless explicitly seeded and saved.

### Acceptance criteria

- Every lane has a declared target, units, valid range and interpolation definition.
- Identical score/config/seed/automation yields repeatable output.
- Automation does not cause clicks, unbounded feedback, NaNs or silent parameter clamping.
- A/B renders demonstrate the target control changed without unexpectedly changing unrelated roles.

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
