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
