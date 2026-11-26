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
