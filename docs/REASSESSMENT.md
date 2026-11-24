# Reawarp: architectural and musical reassessment

**Reviewed:** 25 November 2026  
**Baseline:** `main`, after the M17.5 Score-first generation cutover  
**Purpose:** Reconcile the four IDM guides with the shipped engine, identify the important gaps, and justify the next milestone sequence.

## Executive assessment

Reawarp has moved beyond a pattern generator. It now combines deterministic rhythmic construction, formal section planning, persistent motifs, role-aware orchestration, multiple synthesis families, a sample-bank workflow, frame-scheduled score rendering, typed automation, non-destructive stem processing, a searchable personal audio library, and project provenance.

The strongest architectural decision is the direction of the data flow:

`GenerationConfig → CompositionPlan → Score → Renderers → Dry Stems → FX → Export + Provenance`

M17.5 makes the Score the source of truth for event-backed generation. This is a meaningful foundation, not the end of the composition architecture. Some specialist whole-field texture and ambience passes still sit beside event renderers, the composition grammar still originates in a sixteenth-grid/constant-BPM planning vocabulary, and continuous musical behaviour is not yet a fully expressive, user-editable score-control language.

The next stage should deepen musical relationships and control, not add more pattern families indiscriminately. The guides repeatedly make the same argument: complexity is useful only when the listener can organise it; recurring identity creates expectation; deviation should be legible; independent lines need designed relationships; foreground, midground and background must have intentional hierarchy; sound design is the behaviour of a sound object; and the final judge is listening in context.

## 1. The philosophy translated into engineering principles

### 1.1 Identity before variation

The field guide and Composition Atlas emphasise a small material vocabulary, identity-bearing anchors and the distinction between variation and development. M15's persistent motif is a strong first implementation of this principle.

**Engineering implication:** every material family should have an identity and an explicit set of allowed transformations. A pattern or sound should not be replaced by an unrelated random candidate merely because a section has changed.

### 1.2 Complexity is allocated, not maximised

The guides distinguish density, entropy, perceptual complexity and attention. They also stress subtraction, negative space, stable anchors and one principal change at a time.

**Engineering implication:** composition controls should expose separate dimensions and role intent. A global complexity value may remain as a broad convenience, but it should not silently alter unrelated musical dimensions. A director should know what is foreground, midground and background, and reserve moments for each.

### 1.3 Independent lines need intentional relationships

The guides describe unison, reinforcement, doubling, interlock, call-and-response, independent counterpoint and antiphonal exchange. They also discuss voice-leading and pitch hierarchy beyond a single named scale.

**Engineering implication:** role independence alone is insufficient. The composition plan needs explicit relationships between roles, phrase-level interaction, and optional harmonic constraints. A collection of independent event streams is not yet a composed counterpoint.

### 1.4 Time has nested scales

The Atlas and appendix distinguish local event behaviour, motif/phrase cycles, section changes and whole-track form. Tempo, meter, pulse, phrase length and cycle length are related but not interchangeable.

**Engineering implication:** retain exact rational beat positions, but let phrase and cycle grammars use independent periods and meter-aware boundaries. The sixteenth grid should remain an available coordinate system, not the only conceptual model.

### 1.5 Sound design is controlled identity and behaviour

The sound-design manual treats the sound object as source, envelope, spectrum, modulation, spatial character and transformation. It recommends assigning a clear function to every layer of a hybrid sound and treating effects as instruments where musically useful.

**Engineering implication:** synth/sample hybrids should expose transient, body and tail roles; modulation should be an explicit, automatable relationship; sound identity and processing identity should be stored separately; and DSP modules should remain measurable and optional.

### 1.6 Measurement supports listening; it does not replace it

The guides recommend subtraction, invariance and context tests, matched-level comparison, isolated-role audition and full-track listening. A spectrum or metric cannot decide whether a passage is musically successful.

**Engineering implication:** every musical milestone needs a listening protocol and a set of candidate renders. CI can establish determinism, timing, schema and signal safety, but not musical quality or target-hardware performance.

## 2. Current architecture: strengths and remaining seams

| Area | Current state | Assessment |
|---|---|---|
| Deterministic generation | Named seed streams, repeatable planning, stem regeneration | Strong foundation; keep stream names and variation contracts versioned |
| Formal composition | Structure presets, section plans, phrase directives, transition gestures | Useful macro-form; time and grammar remain tightly tied to current grid assumptions |
| Motif system | Persistent motif identity, transformations, cross-role shadows/responses | Strong first generation; still needs richer independent lines and phrase relationship modelling |
| Orchestration | Seven role plans with activity/density/syncopation/register/brightness/space | Role attributes exist; explicit foreground hierarchy, masking and pairwise relationships are the next step |
| Score | Rational-beat Score, tempo/meter maps, event provenance, automation lanes | Canonical event representation for event-backed voices; specialized whole-field passes still exist |
| Rendering | ScoreRenderer, frame timeline, typed control bus, synthesis/sample/break adapters | Strong event path; continuous field layers and score-level render graph can be brought closer to the same model |
| Musical automation | Score bus supports typed synthesis controls and FX adapters | API foundation exists; user-facing composition-level parameter automation and modulation design remain incomplete |
| Harmony/tuning | Tuning fields, pitch collections, frequency-aware note events, MIDI adapter | Data hooks exist; harmonic context, chord/sonority planning and voice-leading are not yet composition-first |
| Synthesis | Subtractive, FM, additive, modal/inharmonic, granular/physical options and hybrid percussion | Broad palette; deeper sound-object modulation, spectral families and coherent hybrid instruments remain |
| Samples/library | SQLite library, descriptors, similarity, collections, genealogy and sample banks | Strong source management; better audition, variant curation and score-linked sample identity are useful next steps |
| FX/routing | Editable chains, fixed SPACE/ECHO buses, wet automation, non-destructive export | Good deliberately small v1; metering, gain staging, tail and latency semantics need a focused pass |
| Desktop workflow | Compose/Produce/Assets UI, preview, mixer, library and worker-based generation | Functional; main window remains a large orchestration boundary and FX refresh can block the interface |
| Project durability | Config, stems, events, score and metadata export/reopen | Schema v1 works; an explicit complete project manifest and portable dependency/source policy should be defined before breaking changes |
| Validation | 107 tests across Linux Python 3.10–3.12 and Windows Python 3.11 at M17.5 baseline | Strong CI contract; hardware profiling and subjective listening remain open |

### 2.1 Important corrections to older documentation

The current baseline supersedes older statements that the default `generate()` path still renders legacy seconds-based events. It is now Score-first, with `generate_legacy()` retained for comparisons. M17.5 and the current consolidated roadmap are authoritative for this boundary.

M14 is not fully signed off by CI. Its portable tests and benchmark harness are implemented, but target-Windows 30/180-second 48 kHz profiling and Pyo-enabled critical listening are still required.

The score model supports tempo and meter maps, but this does not mean every high-level planner is already free of constant-BPM and sixteenth-grid assumptions. Those assumptions should be removed incrementally where actual musical time requires it, not by forcing all material into a generic abstraction.

## 3. Highest-value gaps

### Gap A — Musical automation is not yet a composition instrument

The typed control bus can evaluate synthesis and FX targets on the same frame clock. The next capability is to let the composition planner intentionally write parameter trajectories: filter motion, pitch/register, decay, modulation depth, grain density, probability, stereo position, send depth and section macros. Those curves should be musically meaningful, editable and attached to score/role identity.

### Gap B — Harmony and counterpoint are underdeveloped relative to rhythm

M15 made motif and role orchestration much stronger, but the current composition still leans on rhythmic identity and contour-based pitch generation. The guides call for optional harmonic fields, voice-leading, pedal tones, controlled dissonance, independent bass lines and role relationships that can evolve. This should be a first-class optional composition layer—not a mandatory functional-harmony engine.

### Gap C — Orchestration needs a perceptual model

The role plan has independent musical axes, but foreground/midground/background, spectral/register budgets, onset overlap and masking relationships are not yet explicit enough. A useful system would allocate attention and leave negative space, without pretending that a simple metric can predict artistic success.

### Gap D — Long-form grammar should work across nested time scales

The current phrase and pattern families provide useful material. A next step is a hierarchy from event gestures to motifs, phrase functions, sections and whole-track narrative, with asymmetry and independent cycle lengths designed into that hierarchy.

### Gap E — Sound objects need richer motion and hybrid structure

The synthesis catalog is broad, but the guides describe a deeper vocabulary: coupled modulators, transient/body/tail separation, modal/resonator families, evolving spectra, resampling as a development operation, and effects that become instruments. Add these as modular sound-object capabilities rather than one giant new palette.

### Gap F — Critical iteration and routing transparency need product-level support

The user should be able to generate comparable candidates, audition one role or pair of roles, compare dry/processed/return/master paths at matched levels, and retain the selected version. The fixed two-bus mixer should first acquire clear gain/tail/metering semantics; arbitrary graphs are not yet justified.

## 4. Recommended architecture direction

The target data flow should be:

`GenerationConfig → Material/Constraint Vocabulary → CompositionPlan → Score + Control Lanes → Render Graph → Immutable Dry Stems → FX Graph/Automation → Master + Complete Project Manifest`

Responsibilities:

- **GenerationConfig:** artistic constraints and high-level user intent; avoid conflating unrelated musical axes.
- **Material vocabulary:** motif, rhythm cell, bass cell, sound object, source sample, tuning and transformation permissions.
- **CompositionPlan:** form, phrase functions, role relationships, attention hierarchy, harmonic context and transition intentions.
- **Score:** all discrete musical events plus continuous control trajectories in rational musical time.
- **Render graph:** deterministic event and field renderers which consume Score and produce immutable dry buffers.
- **FX graph:** non-destructive insert/send/return processing with explicit latency, tail, gain and bypass behaviour.
- **Project manifest:** source references, stable IDs, seeds, algorithm versions, schemas, all settings, score, audio and processing provenance.

Do not build a general-purpose DAW, real-time plugin host or arbitrary node graph as the default product direction. Keep Reawarp an offline-first composition and sound-design laboratory.

## 5. Validation doctrine

Each milestone should include four independent forms of evidence:

1. **Musical-rule tests:** identity preservation, transformation constraints, phrase/cycle boundaries, role relationships and deterministic planning.
2. **Signal tests:** frame alignment, finite output, peak/headroom, mono compatibility, channel handling, latency and tail contracts.
3. **Workflow tests:** generation, variation, save/reload, audition state, export and schema migrations.
4. **Listening protocol:** matched-level comparison of full mix, roles, role pairs, transitions, first/middle/final sections, dry/routed, and subtraction variants.

Target-machine profiling is a separate sign-off. Do not claim it from CI or from a short smoke benchmark.

## 6. What should not be next

- Do not add dozens more Euclidean, chaotic or random pattern generators before making the existing materials interact more musically.
- Do not make tonal harmony mandatory; support harmonic, modal, intervallic, spectral and ambiguous pitch languages.
- Do not add arbitrary routing graphs before metering, gain staging, tail and latency semantics are dependable.
- Do not port to GPU before profiling establishes a real bottleneck.
- Do not add heavyweight analysis or machine-learning libraries to the mandatory core.
- Do not equate a successful score render or spectrum plot with a successful composition.
- Do not make the desktop application a full DAW.

## 7. Proposed sequence

The detailed milestones are in the companion files:

1. **M18 — Musical automation and control performance:** make the existing score control bus a true composition instrument; add typed targets, control generators, modulation relationships and automation-aware UI.
2. **M19 — Harmonic context and voice-leading:** optional harmonic fields, tuning-aware pitch constraints, bass roles, sonority planning and voice-leading.
3. **M20 — Perceptual orchestration and multi-scale phrase grammar:** attention hierarchy, spectral/register allocation, layer relationships, asymmetric phrases and long-form pacing.
4. **M21 — Sound-object and hybrid instrument architecture:** reusable source/envelope/spectrum/modulation/space models, transient/body/tail roles, resampling workflows and advanced hybrid voices.
5. **M22 — Mixer and routing quality:** meters, gain staging, pre/post semantics, return audition, latency/tail behaviour, asynchronous rendering and portable snapshots.
6. **M23 — Variation browser and critical-listening workflow:** candidate generation, matched-level A/B, project snapshots, per-role comparisons and guided listening reports.
7. **M24 — Advanced DSP research modules:** separately scoped convolution, spectral delay, feedback networks, cross-synthesis, oversampling and sidechain tools.
8. **M25 — Performance, portability and project durability:** target-machine profiling, project manifest/schema migrations, offline rendering efficiency, memory budgets and reproducible release validation.

M14 target-machine and Pyo listening sign-off remains a cross-cutting gate and should be completed alongside M18/M22, not hidden inside an unrelated later milestone.

## 8. Source map reviewed

### Philosophy
- `docs/guides/IDM_Field_Guide_for_Composers_Producers_and_Programmers.md`
- `docs/guides/IDM_Composition_Atlas_Patterns_Phrases_and_Track_Structures.md`
- `docs/guides/IDM_Advanced_Composition_and_Generation_Appendix.md`
- `docs/guides/IDM_Sound_Design_Synthesis_and_Hybrid_Sound_Architecture.md`

### Product and engineering
- `README.md`, `docs/ROADMAP.md`, `docs/M14.md`–`docs/M17.md), `docs/M16.md`
- `src/reawarp/core/engine.py`, `core/score_generation.py`, `core/project.py`, `config.py`
- `src/reawarp/composition/`, `src/reawarp/score/`, `src/reawarp/synthesis/`
- `src/reawarp/fx_automation.py`, `fx_routing.py`, `library/`, `ui/main_window.py`
- Existing regression suite, benchmark script and CI workflow.

---

**Bottom line:** Reawarp's next leap should make its existing complexity feel composed. Build musical control, harmonic and contrapuntal relationships, attention-aware orchestration, expressive sound objects, transparent mixing and critical iteration—then expand DSP where real compositions call for it.
