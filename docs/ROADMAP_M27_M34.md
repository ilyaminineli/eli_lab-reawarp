# Reawarp — M27–M34 development roadmap

**Agent-facing technical roadmap · 26 November 2026**  
**Status:** M27 is implemented; M28 and M29 remain in progress with human listening acceptance open; M30 implementation is complete with formal listening sign-off still open.  
**Current baseline:** M30 transition grammar, bounded Score-attached section memory, exact-beat transition actuation and typed EndingDirector. M31 — Sound-Object Workshop and Resampling Lineage — is the next planned priority. Implemented scope and open acceptance are recorded in [MILESTONES.md](MILESTONES.md).
## Roadmap intent — musical agency, perception and finished work (M27–M34)

**Roadmap assessment:** 26 November 2026  
**Basis:** the four companion guides in `docs/guides/`: the IDM Field Guide, Composition Atlas, Sound Design/Synthesis/Hybrid Sound Architecture, and Advanced Composition and Generative Systems.

**Source guides (read as the governing references):**

- [IDM Field Guide for Composers, Producers and Programmers](guides/IDM_Field_Guide_for_Composers_Producers_and_Programmers.md)
- [IDM Composition Atlas: Patterns, Phrases and Track Structures](guides/IDM_Composition_Atlas_Patterns_Phrases_and_Track_Structures.md)
- [IDM Sound Design, Synthesis and Hybrid Sound Architecture](guides/IDM_Sound_Design_Synthesis_and_Hybrid_Sound_Architecture.md)
- [IDM Advanced Composition and Generative Systems](guides/IDM_Advanced_Composition_and_Generation_Appendix.md)

Use these guides for the musical reasoning and terminology. Use the current code, tests and MILESTONES.md for implementation facts and compatibility; where the roadmap suggests an interface or path, treat it as a proposal to validate against the actual repository before creating new code.

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
**Status:** Implemented; UI integration and broader Score-native mutation execution remain follow-on work  
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
**Status:** In progress — core model, Phrase Workbench, contextual audition and matched-level A/B comparison are implemented; full musical acceptance and broader edge-case coverage remain open; sound-object transformations remain gated on M31  
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
- Compare source and candidate in the same context using matched-level A/B copies and a difference signal; keep comparison playback separate from production stems.
- Freeze a candidate into the Score with its parent identity, source events, seed streams, config delta, selection notes and generator version.
- Add explicit “continue evolving”, “freeze”, “branch from frozen phrase” and “restore base” actions. Frozen phrases must not silently change when another layer is regenerated.

### Acceptance criteria

- Phrase timing supports rational beat positions and non-integer bar lengths; frame resolution remains downstream.
- Each generated variation records which motif dimensions changed and which remained invariant.
- Frozen phrase content and unrelated score regions are bit-identical under unrelated regeneration.
- The same candidate request and frozen base reproduce the same candidate list.
- A user can compare source and candidate in the same phrase context—alone, after its predecessor and before its successor—with matched-level A/B and difference audition.
- Phrase/Score export and reopen preserve lineage, edits and freeze state.
- Tests include open phrases, omission, unusual phrase lengths, delayed returns and deliberate no-change repetition.

### Non-goals

- No fixed 4/8-bar phrase assumption.
- No automatic quality score that decides the winning phrase.
- No continuous regeneration of material already selected by the composer.

---

## M29 — Perceptual Orchestration, Figure/Ground and Attention Map

**Priority:** P1  
**Status:** In progress — Score-native attention descriptors, Attention Map workspace, evidence-led conflict diagnostics, human review provenance, non-destructive translation checks and a first render-facing Focus/Recede gesture path implemented; broader musical acceptance and remaining perceptual controls remain open  
**Depends on:** M27, M28; builds on M18, M20, M21, M22  
**Primary guide basis:** Advanced Appendix §§1, 7, 18; Field Guide §§5, 23; Sound Design Guide §1.

### Goal

Make orchestration decisions about what the listener notices, follows and remembers—not just which stems are enabled.

### Scope

- Add an arrangement-level attention map with foreground, midground, background, anchor, counter-rhythm, motif, harmonic field, transition and absence roles.
- Persist semantic orchestration roles separately from depth and store optional onset-density, transient-strength, sustain, spatial-position, register and prominence descriptors. Score-derived estimates are symbolic proxies, not audio measurements.
- Validate hand-off identity against exact rational-beat boundaries; incomplete hand-offs remain explicitly visible.
- Allow role changes over phrase/section boundaries with explicit hand-offs and return identities.
- Track spectral zone, register, onset density, transient strength, sustain, spatial position and intended prominence as descriptors—not rigid mix rules.
- Add a masking/conflict inspector that reports possible competition in time, register, transient or stereo space and explains the evidence.
- Support intentional masking/merging as an explicit relationship, not every overlap as a warning.
- Introduce composition-level “focus” and “recede” operations through presence, register, articulation, density and space before resorting to volume. The first render-facing slice stores reversible role/span gestures in Score provenance and resolves them on render-time event copies: Recede uses deterministic thinning for non-anchor events and shortens note gates; Focus retains the event population and can extend eligible notes by at most 5%, only where the original note-off is already inside the gesture span. Optional semitone translation is supported, and stereo/pan placement moves narrower or wider. No master/fader gain is introduced.
- Apply the same role/span gestures to the fixed SPACE/ECHO send contributions. Focus attenuates each role’s existing send level; Recede raises it within the normalized send range. Both use eased phrase-edge ramps mapped through the Score tempo map, compose with existing routing and send automation, and leave direct stem gain, shared return chains and whole-field ambience/texture passes unchanged. Low-frequency foundation roles are excluded from send shaping.
- Add low-volume and mono checks as separate production views, not destructive master processing.
- Preserve kick/sub protection and existing M22 bounded routing contracts.
- Make MIDI export gesture-aware: emitted note population, register and gate duration follow the same deterministic M29 event gestures; pan is approximated with channel-wide MIDI CC 10. Roles sharing one MIDI channel (notably default GM percussion) therefore share pan state rather than receiving independent simultaneous positions. Store omitted source events and rendered/source mapping in Reawarp metadata so a Reawarp import restores canonical events and gesture provenance rather than freezing the performance mutation into the Score.

### Acceptance criteria

- An arrangement can show which roles are intended to be perceptually dominant at any phrase.
- A hand-off is atomic at a declared musical boundary; no partial intermediate scene is audible.
- Warnings identify affected roles, time range and descriptor basis, and can be reviewed as useful, masked or unresolved with project/plan provenance. Matching intentional-merge IDs suppress expected overlap warnings.
- “Foreground” can change without requiring master gain automation.
- Mono/low-volume checks operate on analysis/audition copies and never rewrite production audio.
- Focus/recede changes are explicit and reversible. The render path and MIDI note export apply the same event-level gesture to the exact rational-beat half-open span; kick/sub and tagged anchors are protected from Recede thinning, and the canonical Score is restored on Reawarp MIDI import. The fixed SPACE/ECHO send contributions also follow role/span gestures with eased rational-beat phrase edges, composing with existing static routing and Score automation while protecting low-frequency foundation roles. Direct/fader/master gain, shared return chains and whole-field texture/ambience passes are not modified by this gesture layer. Standard MIDI 1.0 receives a channel-wide pan approximation via CC 10; tracks sharing a MIDI channel also share pan state. Stereo-width shaping remains Reawarp metadata because standard MIDI 1.0 has no equivalent per-note width control. Complete musical listening acceptance remains open.
- Human review can mark a conflict as useful, masked, or unresolved.

### Non-goals

- No automatic EQ as the default answer to every conflict.
- No single numerical “clarity score”.
- No mandatory spectral slot for each instrument.

---

## M30 — Transition Grammar, Section Memory and Ending Director

**Priority:** P1  
**Status:** Implemented; human listening sign-off open — typed three-phase TransitionPlan, exact-beat actuation resolver, bounded serializable SectionMemory, and fingerprinted EndingPlan/EndingDirector with silent Score markers  
**Depends on:** M28, M29; builds on M7, M15, M20  
**Primary guide basis:** Field Guide §§8–9; Composition Atlas §§13–14; Advanced Appendix §§5–6, 12, 17, 20.

### Goal

Make transitions and endings first-class compositional events. Long-form work needs purposeful state changes, not simply a succession of section presets or a fade-out added at the end.

### Scope

- Create typed transition objects: additive, subtractive, filtered/registral, rhythmic displacement, metric reinterpretation, fragmentation, overlap, silence, false return and motif-as-bridge. The first implementation models these as immutable, versioned plans with source/target phrase identity, source/target state, changed/preserved dimensions, participating roles, optional motif bridge and named seed lineage.
- Give each transition exact rational-beat preparation, change and consequence/arrival phases. Compile the three phase starts and completion into non-audio canonical Score marker events; the change phase is one atomic scene-commit marker carrying the complete target state. Do not create a parallel scheduler or apply implicit audio mutations yet.
- Add a bounded, immutable `SectionMemory` service over recent section snapshots. Each `SectionState` keeps exact rational-beat bounds, M20/M28 phrase references, motif and role identity, versioned motif-transformation history, compact normalized energy/density trajectory summaries, unresolved expectations and explicit return opportunities with permitted transformations.
- Keep memory capacity explicit (default 12, hard maximum 64). Append is deterministic and idempotent; only the newest section may be revised, with unchanged beat bounds and a higher revision; overflow evicts the oldest state. No global mutable cache or parallel scheduler is introduced.
- Expose queries for previous section, last motif/role use, motif recurrence, transformation history, unresolved expectations and unconsumed return opportunities. A later motif use closes an earlier return opportunity; an explicit expectation ID resolves its matching open expectation.
- Attach the versioned memory snapshot and fingerprint to canonical Score metadata without changing audio events. Validate phrase references against an attached M28 PhrasePlan or M20 OrchestrationPlan; store compact trajectory summaries rather than raw time-series.
- Add delayed return, transformed reprise, interrupted cadence, residue, dissolve and hard-stop ending strategies through the typed EndingPlan/EndingDirector contract. Motif returns must reference an open SectionMemory opportunity; interrupted cadences must name an unresolved expectation.
- Allow an ending to preserve a residual A/B/C identity without introducing new section-level randomness.
- Make tempo-map changes an explicit composition choice with rational beat location, clear conversion semantics and user review; keep fixed BPM as the default.
- Scene changes affecting several roles must be atomic at a Score boundary.

### Acceptance criteria

- Transition plans specify source state, target state, changed dimensions, preserved identity, participating roles, seed lineage and exact preparation/change/arrival regions.
- Every transition has deterministic timing and can be inspected/reproduced. Compiled Score markers preserve the phase boundaries; one marker carries the whole target scene at the atomic change beat.
- Existing M20 phrase spans and M28 phrase plans are valid references; compilation is idempotent and leaves unrelated Score events unchanged.
- Section memory round-trips through a versioned Score metadata record with a verified fingerprint, preserves unrelated events, and validates M20/M28 phrase references. Capacity/eviction, deterministic revision, last-use/recurrence, transformation lineage, expectation resolution and motif-return closure are tested.
- Ending plans are present in fingerprinted Score metadata with deterministic silent start/completion markers; they do not depend on an arbitrary audio fade alone. Return strategies validate motif/source lineage against open SectionMemory opportunities, and interrupted cadences validate unresolved expectation IDs.
- A frozen or selected section cannot be modified by an unrelated later section mutation.
- Tests cover asymmetrical phrases, no-transition repetition, abrupt rupture, silence, false return, all six ending strategies, return permissions, unresolved expectations, exact-beat transition actuation and multiple ending types.
- Tempo-map behaviour is tested for beat-to-second and beat-to-frame conversion; no implied continuously varying tempo is assumed.

### Implementation boundary

Transition actuation is a pure exact-beat resolver that exposes the source scene until the declared change beat and the complete target scene at/after that beat. Ending markers carry explicit directives only. Neither service mutates rendered audio or runs as a parallel playback scheduler; a later arrangement/render action must consume a directive explicitly and retain reversible provenance.

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

---

# Agent implementation handoff

This section translates the milestone intentions into concrete development boundaries. Names below are suggested starting points, not permission to duplicate an existing service. Before creating a module, inspect the current source tree and search for an existing model or API that already owns the behaviour.

## Repository-wide working protocol

### Required reading before each milestone

1. Read MILESTONES.md for the implemented baseline, current schema versions and known open acceptance work.
2. Read IMPLEMENTATION_NOTES.md for determinism, Score timing, audio ownership, thread boundaries and dependency constraints.
3. Read the four source guides named in this roadmap and the exact sections listed under the milestone being implemented.
4. Inspect current modules and their tests before proposing new abstractions. Existing implementation is authoritative over a roadmap sketch.
5. Identify which persisted data changes, which renderer owns the output, and what is allowed to mutate before coding.

### Required design note for each milestone

Before implementation, add a short design note to the milestone PR description or a focused document covering:

- the musical problem being solved and a concrete listening scenario;
- existing modules/services to reuse;
- new public models and their ownership;
- data/schema changes and migration behaviour;
- deterministic seed inputs and invariants;
- worker/cancellation/cache lifecycle;
- expected files and UI workflow;
- objective automated tests;
- separate human listening acceptance.

Do not start by extending the main window with more unrelated state. Prefer a Qt-independent model/service first, then a thin UI adapter.

### Shared data and execution contracts

- **Intent is not configuration.** CompositionBrief describes why/how material should behave; GenerationConfig contains validated renderer/planner inputs. Keep them separate and define an explicit compile/resolve boundary.
- **Plan is not Score.** Phrase/section planning may carry semantic functions and mutation permissions; Score remains canonical for event-backed scheduled content.
- **Source is not print.** Original samples and dry stems are immutable. A resample or processed object is a new asset/version with lineage.
- **A freeze is a snapshot, not a flag over mutable content.** Store the exact parent revision, Score region/event identity, configuration delta, generator version and seed lineage needed to reconstruct it.
- **Musical time stays rational.** Keep beat positions as rational values until RenderTimeline resolves them to frames. Do not infer bar number from a rounded time in seconds.
- **Randomness stays hierarchical.** Derive independent stable named streams for event, pattern, phrase, section and object processes. Never use Python's salted hash function for persistent identities or seed derivation.
- **UI never owns rendering logic.** Expensive planning, analysis, synthesis, DSP, disk reads/writes and archive work run outside the GUI thread through immutable snapshots and cancellable workers.
- **Audio callback is not a work queue.** It must not allocate large buffers, log synchronously, access files, parse schemas or block on a general lock.
- **Diagnostics are not taste.** Technical warnings report evidence, units, ranges and uncertainty. No milestone may silently create a numerical artistic ranking.
- **Manual work is provenance.** Distinguish generated, automatically transformed, manually edited, frozen and printed material in project history.
- **Unknown schemas fail explicitly.** Add migration fixtures; do not silently coerce missing or future fields into a different musical result.

### Expected change-set discipline

- One milestone per PR unless two milestones are inseparable and their shared design is documented.
- Avoid simultaneous edits to ui/main_window.py by several agents. Agree a single integration owner or work through separate UI modules/pages.
- Add unit tests for models/services, property-style tests for invariants over many seeds, round-trip tests for persistence and offscreen UI tests for workflows.
- Keep optional native dependencies lazy-loaded and optional. Add dependency/license/runtime notes before adopting them.
- Add a human-listening checklist with test projects and reproducible seeds, but never report it as passed without listening evidence.
- Update the status in MILESTONES.md only after evidence meets that status definition. Keep detailed scope and implementation decisions in this roadmap or focused ADRs.
- Do not claim the whole milestone is complete merely because the main happy-path test passes.

---

## Suggested implementation boundaries by milestone

The following paths are recommended service boundaries. Confirm current package structure before adding each file.

### M27 implementation map — intent and mutation contracts

**Likely modules**
- src/reawarp/composition/brief.py — immutable CompositionBrief model, validation, serialization and defaults for legacy projects.
- src/reawarp/composition/mutation.py — MutationContract, invariant checks, allowed-field application and mutation audit.
- src/reawarp/composition/brief_compiler.py — deterministic resolution from brief + GenerationConfig + available assets into a validated composition request.
- src/reawarp/ui/pages/composition_intent.py (or a Generator subpanel) — concise controls for the brief; no renderer code in the widget.
- tests/test_composition_brief.py, tests/test_mutation_contracts.py — schema, compile, invariant and property tests.

**Suggested public concepts**
- CompositionBrief: schema_version, artistic_question, listening_mode, anchor, materials, contrast_targets, pitch_world, ending_intent, source_asset_ids, notes.
- MaterialIdentity: stable ID, role, source identity, perceptual signature/descriptor references and optional motif reference.
- MutationContract: stable target ID, allowed fields, preserved fields, lower/upper bounds, scale, cadence, allowed boundaries, mutation policy, stop condition.
- ResolvedCompositionIntent: immutable result showing selected materials, explicit invariants, mutable dimensions and unresolved source references.

**Design decisions to settle**
- Whether a brief stores literal sample paths or logical asset IDs. Prefer IDs plus hashes; resolve paths through existing sample/project asset services.
- Whether contracts target semantic role IDs, Score voice IDs or sound-object IDs. Avoid mixing these identity domains.
- How global constraints intersect local contracts. Explicit conflicts should fail validation or require a visible resolution; never silently override one contract with another.
- Whether legacy projects have an empty/legacy brief or an inferred read-only preview. Do not persist inferred intent as if the user authored it.

**Minimum tests**
- Stable serialization and schema version rejection.
- Same brief/config/seed yields same resolved intent.
- Changing one named local RNG stream leaves unrelated streams and structure unchanged.
- A field outside may_change is rejected; a field inside must_preserve remains exact.
- Missing asset IDs/hashes are reported without substitute sample selection.
- Legacy projects load without an implicit brief write-back.

### M28 implementation map — phrase grammar and frozen candidates

**Likely modules**
- src/reawarp/composition/phrases.py — phrase functions, rational spans, open/closed/fragmentary state and boundary descriptors.
- src/reawarp/composition/motifs.py — motif identity, dimensional feature references and named transformation operations.
- src/reawarp/composition/phrase_candidates.py — deterministic offline candidate batch service from a frozen Score region.
- Existing variations services remain responsible for candidate genealogy and human selection where their current contracts fit; extend them rather than building a second candidate database.
- src/reawarp/ui/pages/phrase_workbench.py — audition, compare, freeze, branch and restore actions.
- Tests: test_phrase_grammar.py, test_motif_lineage.py, test_phrase_candidate_determinism.py, test_phrase_freeze_invariance.py.

**Suggested public concepts**
- PhraseSpan: stable phrase ID, rational start/end, function, boundary type, motif IDs, participating roles and section parent.
- MotifIdentity: feature domains that make a motif recognisable (rhythmic, pitch/contour, timbral, registral, sample/source, spatial or gesture).
- MotifTransformation: operation, changed domains, preserved domains, amount, source motif/version and derived seed.
- PhraseCandidate: frozen-base fingerprint, phrase span, candidate Score/events, transformation chain, seed map and technical flags.
- FreezeRecord: exact source revision, target region, selected candidate ID, frozen content fingerprint, selection note and timestamp.

**Design decisions to settle**
- How semantic phrase objects map onto Score event IDs and automation lanes; no duplicate event scheduler.
- How overlapping phrases and independently phased cycles are represented.
- How motif similarity is described for comparison; use transparent descriptors, not a hidden quality score.
- Which transformations operate on symbolic Score, which operate on sound objects/audio, and how those different domains are linked.
- Whether branch/freeze persistence belongs in project metadata, candidate records or a new versioned arrangement/phrase document.

**Minimum tests**
- Irregular rational spans, zero/negative length rejection, open and interrupted phrases.
- Variation candidate reproducibility and candidate lineage.
- Frozen region byte/semantic identity after unrelated regeneration.
- Transform provenance correctly lists changed and preserved identity dimensions.
- Candidate context render uses the same predecessor/successor buffers and frame alignment.
- Score/MIDI projection preserves what is representable and documents MIDI limitations.

### M29 implementation map — attention and perceptual orchestration

**Likely modules**
- src/reawarp/composition/attention.py — arrangement attention map and role prominence model.
- src/reawarp/analysis/masking.py — evidence-based temporal/spectral/registral/transient conflict diagnostics.
- src/reawarp/composition/hand_offs.py — role hand-off and shared identity transitions, only if not already represented by M20 role relationships.
- src/reawarp/ui/pages/attention_editor.py — timeline/phrase-level role prominence and warnings.
- Tests: test_attention_map.py, test_masking_diagnostics.py, test_atomic_role_handoffs.py.

**Suggested public concepts**
- AttentionAssignment: role ID, phrase/section span, foreground/midground/background/anchor/etc. state, intended prominence, register/spectral zone and spatial intent.
- AttentionMap: assignments plus explicit gaps/absence and hand-off links.
- ConflictEvidence: roles, time range, measured descriptor overlap, analysis settings, severity and confidence.
- IntentionalOverlap: reference to evidence marked as desired merge/masking with user reason.

**Design decisions to settle**
- Reuse M20 role relationships and M18 control targets. Do not invent a parallel role enum that drifts from Score.
- Keep perceived prominence separate from loudness/gain; it can be expressed via density, articulation, register, spectral motion, source behaviour or spatial placement.
- Analysis windows and thresholds must be visible and configurable; diagnostics must expose uncertainty.
- Decide which warnings are static pre-render estimates and which require rendered-audio analysis.

**Minimum tests**
- Attention assignments are deterministic and align to valid rational phrase boundaries.
- Atomic hand-off does not generate a mixed intermediate scene.
- Mono and low-volume analysis use audition copies only.
- Masking diagnostic returns its descriptor evidence and analysis parameters.
- User-dismissed intentional overlap survives project reopen without suppressing unrelated warnings.

### M30 implementation map — transition and ending grammar

**Likely modules**
- src/reawarp/composition/transitions.py — transition type, preparation/change/arrival plan and boundary constraints.
- src/reawarp/composition/endings.py — explicit exit state and ending strategies.
- src/reawarp/composition/section_memory.py — compact history of recent motif/role/energy/density/expectation states for the director.
- Reuse CompositionPlan, M20 phrase spans and Score markers rather than creating a second macro-form model.
- Tests: test_transition_plans.py, test_section_memory.py, test_ending_director.py.

**Suggested public concepts**
- TransitionPlan: source and target state, rational start/end, type, prepare/change/arrival regions, changed and preserved dimensions, participating roles, motif bridge and seed lineage.
- SectionMemory: bounded recent-state record; motif last-use and transformation history; unresolved return/contrast affordances.
- EndingPlan: exit type, last permitted mutation boundary, residual identity, tail/silence policy and explicit completion condition.

**Design decisions to settle**
- Transition objects should compile to canonical Score events/markers and existing automation, not run a parallel playback timeline.
- Section memory must be bounded and serializable; it is planning context, not hidden mutable global state.
- Define whether an ending extends duration or is constrained to requested duration. The chosen policy must be explicit in project/brief state.
- Tempo maps must distinguish step changes from continuous ramps and keep beat-to-second conversion mathematically defined.

**Minimum tests**
- Transition plans preserve declared dimensions, validate phrase identity and use permitted transition types.
- Scene updates are represented by one atomic target-state marker at the declared beat/frame boundary; renderer execution remains a later slice.
- Ending director cannot schedule a new section-level mutation after the exit state is committed.
- Tests include repetition without change, hard rupture, silence, false return, residue and deliberate early termination.
- Tempo conversion round-trips beat/time/frame values within defined sample tolerance.

### M31 implementation map — sound-object workshop and resampling lineage

**Likely modules**
- Extend the existing sound_object service/model and its persistence adapter; do not fork a second sound-object renderer.
- src/reawarp/ui/pages/sound_object_editor.py — graphical editor over the current editor-facing model.
- src/reawarp/synthesis/resampling.py (or existing samples/resample service) — non-destructive print/resample operations.
- Tests: test_sound_object_editor_model.py, test_sound_object_lineage.py, test_resampling_non_destructive.py.

**Suggested public concepts**
- SoundObjectVersion: stable object ID/version, source ID/hash, excitation, resonance, spectrum, envelope, motion, space and context role.
- SoundObjectLayer: transient/body/tail identity, frame region, gain/envelope and renderer source.
- ResampleRecord: input object/phrase/stage, exact source revision, render graph/settings, seed, sample rate, output hash and parent lineage.
- RoleAssignment: sound object version plus target role and role-specific processing identity.

**Design decisions to settle**
- Which parameter groups are editable at once and which controls need constrained ranges/units.
- How patches and rendered audio variants map to the existing SQLite lineage schema.
- Whether a printed FX stage creates a sound object version or an imported sample-library asset; make the choice explicit and reversible.
- How missing original sources are shown when a print remains available.
- Keep M24 research processors opt-in and avoid arbitrary processing-graph scope.

**Minimum tests**
- Patch save/load round trip and schema validation.
- Transient/body/tail solo and combined audition alignment.
- New prints never modify input buffers/files.
- Source hashes, transform settings and output hashes remain traceable.
- Same patch/source/seed/renderer version produces the documented deterministic result.
- Editor works without optional backends unless the user requests that backend.

### M32 implementation map — critical listening workbench

**Likely modules**
- src/reawarp/analysis/listening_sessions.py — session model, snapshots, tests and human-authored notes.
- src/reawarp/analysis/delivery_checks.py — technical reports with evidence and thresholds.
- src/reawarp/ui/pages/listening_workbench.py — contextual audition and review UI.
- Reuse M23 blind A/B, matched-level audition and candidate genealogy.
- Tests: test_listening_session_roundtrip.py, test_delivery_checks.py, test_audition_transform_non_destructive.py.

**Suggested public concepts**
- ListeningSession: project revision, candidate/phrase IDs, ordered audition contexts, levels, transformations and notes.
- AuditionContext: solo, predecessor→candidate, candidate→successor, full section, full track, reduced density, alternate register.
- TechnicalFinding: metric, value, unit, threshold, time/role range, evidence and severity.
- ListeningReview: identity, continuity, contrast, legibility, motif development, orchestration, pacing, surprise, emotional coherence and technical integrity prompts.

**Design decisions to settle**
- Keep objective checks as separate technical findings; never collapse them into an artistic rank.
- Decide how matched loudness is computed and store the match report; do not alter source/master buffers.
- Keep the exact analysis window, weighting, sample rate and channel handling with each finding.
- Define which transformations are temporary audition-only and which become an explicit applied edit.
- Decide whether listening reports embed waveforms or reference project/candidate IDs; favour compact portable notes.

**Minimum tests**
- Meter/diagnostic functions tested against known signals and documented tolerances.
- Every audition transform is applied to a copy and source arrays remain unchanged.
- Session round-trip preserves exact project revision, contexts, order, level match reports and notes.
- Mono/downmix tests check phase cancellation and do not rewrite stereo production.
- Reports export and reopen even if Reawarp UI is unavailable.

### M33 implementation map — arrangement and print-to-track

**Likely modules**
- src/reawarp/arrangement/model.py — ordered arrangement of phrase/section references, frozen blocks, transitions and endings.
- src/reawarp/arrangement/operations.py — non-destructive move/duplicate/trim/reorder/mute/replace and edit history.
- src/reawarp/ui/pages/arrangement_editor.py — Score-aware arrangement workspace.
- src/reawarp/export/delivery.py only if the existing folder delivery service needs an extension; do not conflate delivery output with a restorable project archive.
- Tests: test_arrangement_operations.py, test_arrangement_roundtrip.py, test_manual_edit_provenance.py.

**Suggested public concepts**
- ArrangementDocument: schema version, project/Score revision, ordered section references and explicit final duration policy.
- ArrangementBlock: stable block ID, phrase/candidate/source reference, rational start/end, role participation and freeze state.
- ArrangementEdit: operation, before/after references, authoring mode (generated/manual), source revision and undo identity.
- PrintRecord: selected arrangement region, printed source, output hash and lineage.

**Design decisions to settle**
- Establish whether arrangement blocks reference Score subranges, frozen Score snapshots or separately stored phrase documents. A block must not ambiguously own two sources of truth.
- Determine whether trim changes event duration, crops render audio, or both; store explicit semantics.
- Define how overlaps, crossfades and tails are represented without introducing an arbitrary timeline engine.
- Keep edits reversible and separate manual operations from generation changes.
- Define the handoff between the editing arrangement and the existing export pipeline.

**Minimum tests**
- Reorder/duplicate/trim maintain rational timing and source lineage.
- Frozen blocks remain unchanged after upstream config/seed edits.
- Undo/redo reproduces previous arrangement identity.
- Export/reopen retains final section order, transitions, ending and MIDI projection.
- A full piece can be finished using phrase/section operations without a general-purpose clip editor.

### M34 implementation map — research gates

**Likely modules**
- Audio analysis adapters remain optional and isolated, e.g. src/reawarp/analysis/audio_features.py.
- Sidechain/envelope control, if approved, should first be represented as a typed detector/control source in existing M18 automation contracts.
- Feedback research, if approved, should live in a standalone bounded DSP module with NumPy reference tests before any FX Lab integration.
- Parallel branches should not be created until a design note demonstrates why serial inserts + SPACE/ECHO cannot express the use case.
- Tests: feature alignment/confidence, hysteresis, deterministic mapping, control-boundary commit, feedback stability and tail/headroom.

**Audio-conditioned control contract**
- Feature windows, hop size, weighting, smoothing, normalisation and confidence must be explicit.
- A low-confidence analysis frame must not trigger a large structural decision.
- Map to a small set of musical controls, not every low-level parameter.
- Apply control changes at a phrase/section boundary unless the parameter is explicitly continuous.
- Store input identity/hash, feature configuration, confidence trace, mapping version, manual overrides and seed.
- Provide disable/bypass and deterministic replay.

**Advanced DSP safety contract**
- Each feedback processor needs finite parameter bounds, a documented gain/stability condition, decay/tail cap, reset, panic/stop and headroom tests.
- A parallel branch must define latency alignment, phase behaviour, wet/dry gain law, tail ownership and channel layout.
- Optional native libraries remain lazy-loaded and require a licence/platform review.
- No new processor becomes a default production insert without separate listening and performance sign-off.

---

## Cross-agent handoff checklist

Before marking any milestone implemented, an agent should be able to answer “yes” to every applicable item:

- [ ] The feature solves a named musical problem from the guide, not only a technical novelty.
- [ ] The data model has one clear owner and a versioned persistence boundary where needed.
- [ ] Existing Score, timing, sample, role, automation and export contracts are reused rather than duplicated.
- [ ] Invariants and mutation permissions are testable and enforced.
- [ ] Seeds and lineage are sufficient to reproduce the result within the documented environment contract.
- [ ] Dry source audio, imported assets and frozen material are not mutated.
- [ ] Cancellation, stale results, worker lifetime and output cleanup are handled.
- [ ] Unit, regression, round-trip and multi-seed invariant tests have been added.
- [ ] UI is a thin client and no expensive work entered the audio callback.
- [ ] CLI/documentation examples only use implemented and validated options.
- [ ] Objective diagnostics report evidence and do not claim artistic ranking.
- [ ] Human listening evidence is separately recorded where the milestone requires it.
- [ ] The README, implementation notes and milestone status agree with actual behaviour.

