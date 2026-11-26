# Reawarp roadmap re-audit — 26 November 2026

**Audited branch:** `main`  
**Baseline commit:** `60a50e9adb25617f2669ad29fa61feba9910e273` (`Implement M24.6 bounded feedback delay network`)  
**Scope:** milestone ledger, M27–M34 roadmap, repository tree, relevant implementation modules/tests, README and latest CI record.

This is a static repository audit plus review of the latest CI result. It is not a target-Windows benchmark, a Pyo listening session or a claim of human musical acceptance. Source and tests on `main` take precedence over older status prose.

## Executive result

- **M24.7 stays gated.** Reawarp already has per-stem serial chains with stage/chain dry-wet blending and two shared wet-only auxiliary returns. Independent per-stem parallel chains are not supported, but no real composition or failed baseline demonstrates that they are needed. See [M24.7 gate](M24_7_PARALLEL_BRANCHES.md).
- **M27 is less complete than its old status implied.** A versioned `CompositionBrief` / mutation-contract model exists, but current repository search found no non-model consumer, no Generator Intent UI, no project-level persistence/resolution/execution path and no dedicated M27 test module. Its correct status is **Partial**.
- **M28–M33 contain useful delivered vertical slices**, but M28/M29 remain in progress and M31/M32/M33 retain explicitly scoped follow-ons and human acceptance.
- **M14/M25 and M24.5/M24.6 still need target-machine profiling.** The 5-second CI smoke is not the requested 30/180-second 48 kHz test.
- **Pyo/mix listening and musical acceptance remain human gates.** A green CI run cannot evaluate timbre, identity, masking, pacing or emotional coherence.

## M24.7 — decision and evidence

The current FX stack is intentionally bounded:

| Existing capability | Current boundary |
|---|---|
| Per-stem inserts | One ordered chain per stem; up to 12 stages; per-stage and chain-level dry/wet blend |
| Auxiliary effects | Two shared wet-only returns, SPACE and ECHO, each with its own shared chain |
| Sends | Four tap choices around insert/fader; send and return wet automation |
| Dynamics control | M24.5 one-way source-detector to target-gain sidechain |
| Timing | Built-in chains report zero latency and are start-aligned; tails are bounded/reported |

The missing capability is a set of independently processed parallel chains for one stem, each with its own chain and recombination control. The shared returns do not supply that: all stems feeding a return share its chain. Still, adding that capability would introduce branch alignment, phase, gain-law, tail-ownership, persistence and UI decisions. There is no submitted real example showing that the current topology blocks a musical result. No code, project schema or UI change is warranted until a source-backed case and matched-level comparison pass the gate.

## Remaining milestone register

### A. Software integration or scoped feature work remains

| Milestone | What is actually present | Remaining work / correct interpretation |
|---|---|---|
| **M27 — Artistic Intent** | `src/reawarp/composition/brief.py` contains versioned brief, material/source and mutation-contract models and validators. | The audited tree has no source consumer of those models, no Intent panel, no project integration/resolution/execution adapter and no dedicated M27 test file. Implement the end-to-end path before treating M27 as delivered. |
| **M28 — Phrase grammar** | Rational phrase plans, motif-family records, deterministic candidate generation, freeze/branch/restore, Phrase Workbench, contextual audition and matched-level A/B/difference playback have code and tests. | Broad edge-case and real-composition acceptance remain open. M31 core is now delivered; sound-object-aware phrase transformations and deeper motif-to-object lineage are follow-on integrations rather than a blocked dependency. |
| **M29 — Attention / figure-ground** | Score-native attention descriptors, Attention Map editing, conflict evidence/review, translation checks, reversible Focus/Recede event gestures, send shaping and gesture-aware MIDI export are present. | It is a first render-facing slice, not a full audio-measured perception system. Score descriptor estimates remain symbolic; whole-field texture/ambience and direct stem/master gain are intentionally untouched. Broader perceptual controls and listening acceptance remain open. |
| **M31 — Sound-object workshop** | Dedicated editor, aligned layer auditions, immutable patch revisions, non-destructive WAV print and ResampleRecord lineage are implemented. | Coherent-family generation, direct phrase/stem/FX-stage printing and full-arrangement matched-level A/B remain follow-ons; object-layer balance and mono/role reuse need listening. |
| **M32 — Critical listening** | Disposable contextual auditions, role subtraction, invariance probes, undo/redo review, technical diagnostics and JSON/Markdown report export are implemented. | Full-FX candidate A/B transport, deeper role-aware spectral occupancy, more precise onset/phase diagnostics and extended invariance mutations remain follow-ons. Human notes must remain human-authored. |
| **M33 — Arrangement / print-to-track** | Score-native phrase editing, cue relinking, bounded undo/redo, finishing checklist, dry phrase print with SHA-256/source lineage and export copy are implemented. | Current phrase print is intentionally dry; it does not include insert FX, SPACE/ECHO or mastering. Human acceptance must decide whether that print is sufficient for the downstream workflow. This is not a general DAW/clip editor. |

### B. Implemented software with external or human acceptance still open

| Milestone group | Open acceptance |
|---|---|
| **M14 and M25** | Run the existing 48 kHz generation/export/reopen benchmark at 30 and 180 seconds on the target Windows machine; capture hardware, Python/NumPy/SciPy versions, wall time, real-time factor and peak memory. Agree explicit resource budgets before sign-off. |
| **M15, M18–M23 and M28–M33** | Human listening on representative compositions. Evaluate identity, contrast, motif/phrase development, figure/ground, transitions/endings, sound-object balance, contextual subtraction and arrangement/print usefulness. |
| **M22 and M26** | Install the optional Pyo extra on the target Windows environment and audition the actual insert/send/return/master path, export render, matched-level comparisons, mono and low-volume translation. CI currently installs no Pyo runtime. |
| **M24.1–M24.4** | NumPy reference processors and regression coverage exist; matched-level listening and target-machine profiling remain open. They are not default production inserts. |
| **M24.5 and M24.6** | Core offline implementations and CI smoke coverage exist. Real-material matched-level listening and target-Windows 30/180-second profiling remain open. |
| **M30** | Transition/ending model and deterministic Score marker behaviour are implemented; formal listening sign-off remains open. |

### C. Conditional research only

| Item | Decision |
|---|---|
| **M24.7 — Parallel branches** | Do not implement without a real source-backed use case showing that serial stage/chain blends plus shared SPACE/ECHO cannot express the desired result. |
| **M34 — Audio-conditioned composition / further DSP** | Remains deferred until a real reference source, a precise composition problem, a static baseline, an objective test and a human listening benefit are demonstrated. The synthetic order-reversal fixture proves only that global descriptors lose temporal order. |

## Verification state

The latest main-branch workflow at audit time was [CI run 45868070414](https://github.com/ilyaminineli/eli_lab-reawarp/actions/runs/45868070414), on baseline commit `60a50e9`. All four jobs passed: Windows regression and Linux Python 3.10, 3.11 and 3.12. It includes the M24.6 smoke and the 5-second M25 archive/reopen smoke. This proves the automated regression baseline only; it does not close the external/human acceptance rows above.

The GitHub open-issues endpoint returned no open issues during this audit. The remaining work is therefore recorded in the milestone documents rather than in an existing issue backlog.

## Recommended implementation order from this audit

1. **M27 end-to-end integration** — the clearest software-completeness gap and a prerequisite for reliable brief-led mutation policy.
2. **M28 sound-object-aware phrase transformation integration** — M31 core is now available; add only the transformation and lineage bridge needed by a real phrase workflow.
3. **M29 remaining perceptual controls** — preserve the current event-gesture and Score/MIDI round-trip contracts; add only a concrete missing focus/recede action.
4. **M32 full-FX candidate comparison / diagnostics** — integrate the existing routed render snapshot rather than creating a second renderer.
5. **M31/M33 delivery follow-ons** — coherent sound families and FX-aware prints only after a demonstrated listening/production need.
6. **M24.7 and M34** remain research gates, not queued implementation tasks.

Human listening and target-machine validation should proceed alongside these software priorities; they cannot be closed by code changes alone.
