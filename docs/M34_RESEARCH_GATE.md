# M34 — Audio-Conditioned Composition and Advanced DSP Research Gate

**Review date:** 26 November 2026  
**Decision:** Research reviewed; no production implementation approved  
**Scope:** Baseline, repository capability audit and acceptance contract only

## Executive decision

M34 remains a conditional research gate. The audit found one plausible missing capability—**time-varying audio features that can condition phrase-level composition macros**—but no supplied real-composition example demonstrating that this is currently blocking the composing workflow. The synthetic baseline below proves an information gap in the current whole-file summary API; it does not prove that an audio-conditioned generator produces better music.

Therefore this review does **not** approve a feature implementation, new DSP routing, a new dependency, or a production UI. The next justified action is to run the same experiment against a real break/stem/reference supplied for a concrete musical task, compare against a static-macro baseline, and record human listening outcomes. M34 should remain deferred until that comparison demonstrates a benefit.

## Repository capability audit

| Existing capability | What it already does | What it does not establish |
|---|---|---|
| **reawarp.transforms.analysis** | Dependency-light transient detection and automatic frame slicing for imported break material | No stable, time-indexed feature envelope or phrase-level macro control |
| **reawarp.library.features** | Whole-file peak/RMS/crest, centroid/rolloff/flatness, transient count/density, onset interval summary, rhythm histogram and optional HPSS/onset descriptors | AudioFeatures returns aggregate values, not a window-by-window timeline, confidence or beat-aligned control curve |
| **M27 CompositionBrief** | Source identity, anchors, mutation contracts, scope-aware bounded config exploration and deterministic seeds | No signal-derived parameter source; macro values are explicit composition intent or bounded mutations |
| **M28/M32** | Phrase identity, deterministic alternatives, contextual audition, technical diagnostics and human evaluation provenance | No audio-analysis-to-Score mutation path |
| **M29/M30/M33** | Semantic attention/gesture controls, transition/ending grammar and deliberate phrase arrangement | No imported-reference-following control lane; these are authored from Score/form intent |
| **M22 FX routing** | Per-stem serial inserts and fixed SPACE/ECHO auxiliary returns; dry stems remain authoritative | No general cross-stem detector/sidechain semantics or arbitrary routing graph |
| **M24.1–M24.4** | Separate NumPy reference implementations and CI coverage for convolution, spectral delay, cross-synthesis and nonlinear processing | These are research/reference processors, not automatic production inserts; listening and target profiling remain open |
| **M24.5** | Planned sidechain/envelope routing | No explicit detector, envelope, smoothing, hysteresis and cross-stem control model |
| **M24.6** | Planned bounded feedback networks | No fixed-topology feedback network contract with stability, reset, finite-tail and headroom tests |
| **M24.7** | Research gate for parallel branches | No demonstrated use case that existing inserts and SPACE/ECHO cannot express |

The repository already has substantial analysis and editing capability. The actual gap is temporal orchestration of reference features, not a lack of basic audio analysis. This distinction avoids duplicating transient detection, library indexing, M27 mutation contracts or M32 diagnostics.

## Candidate ranking

1. **Audio-conditioned phrase macros — most plausible, not yet approved.** A reference break/stem may have a meaningful progression in density, energy or spectral character. Whole-file averages erase its order. A future adapter could expose a few explicit normalized controls (initially density, brightness and activity) while keeping musical decisions on phrase boundaries.
2. **M24.5 sidechain/envelope routing — defer.** The current fixed routing has no cross-stem detector. Before adding it, a concrete musical example must show that a manually authored Score/FX automation lane or existing send/insert setup cannot express the desired ducking or reciprocal movement.
3. **M24.6 bounded feedback — defer.** Existing delay and spectral-delay effects already expose bounded repeat/feedback parameters. A new network is justified only by a sound or evolving interaction that a single bounded chain cannot produce. Stability, reset and finite-tail contracts would be prerequisites.
4. **M24.7 parallel branches — do not implement by default.** The existing serial insert and shared wet-return model is intentionally bounded. Parallel processing is not an objective in itself; a failing serial/return baseline is required.
5. **Search/evolutionary optimisation — defer.** M27 bounded exploration, M28 phrase candidates and M32 human evaluation already establish a safer generate–audition–select pattern. Further search is not justified without a declared constraint that those contracts cannot express.

## Baseline example: same material, opposite order

The reproducible synthetic pair is defined in tests/fixtures/m34/audio_conditioning_order_pair.json and constructed in tests/test_m34_research_gate.py.

At 22,050 Hz it creates two equal-length, guarded materials:

- **sparse_dark:** four short 110 Hz pulses in the segment;
- **dense_bright:** sixteen short 3,800 Hz pulses in the segment.

Sequence A is sparse/dark followed by dense/bright. Sequence B contains the **same samples** in the opposite order. The guard regions and analysis-hop alignment avoid boundary windows changing the material inventory.

The existing library extractor returns whole-file values. Peak, RMS, crest, centroid, rolloff and flatness therefore match for the two orderings within a tight numeric tolerance, even though their temporal trajectories are opposite. The baseline regression test verifies that limitation. It is not an audio-conditioning feature test and it does not claim musical preference.

**What this baseline establishes:** whole-file summaries cannot answer the question “when does this source become denser/brighter?”  
**What it does not establish:** that a composition should follow the source, which macro should change, or that following it is musically beneficial.

## Proposed acceptance contract if a real use case is demonstrated

A future M34 design should begin with one named source, one musical problem and no more than three mapped macros. The following are objective prerequisites, not features delivered by this research review.

### Analysis contract

- Preserve source sample rate, channel count, duration and SHA-256. Record analysis version, window/hop, resampling method and all detector settings.
- Produce time-indexed RMS/energy, onset activity and spectral brightness/flux descriptors. Chroma or low-frequency bands are added only when the chosen source/task needs them.
- Normalize against a declared robust source range; report confidence and explicitly mark silent, clipped, corrupt or out-of-distribution windows as unreliable.
- Smooth at control rate and use enter/exit hysteresis. Never map raw frame-to-frame values directly to musical parameters.
- Align feature windows to rational Score beats and commit changes only at declared phrase/section boundaries. No audio callback performs analysis, file access or Score mutation.

### Composition and identity contract

- The mapping is explicit, bounded and small: proposed first controls are arrangement density, tonal brightness and melodic/percussive activity, each in [0, 1].
- Preserve CompositionBrief anchors, frozen source identities, selected motif/event IDs, root/scale, tempo and declared form unless the user explicitly authorizes a particular mutation.
- Manual override has priority and persists as authored Score intent; the analysis curve must not silently overwrite it.
- Same source hash + analysis settings + mapping + Score revision + seed must reproduce the same feature curve and mutation proposal. Record confidence, mapped values, phrase commits, override decisions and source lineage.
- Low-confidence or silent windows hold the last accepted value or the explicit baseline macro; they never trigger an uncontrolled reset or random value.

### Objective acceptance tests

1. **Order sensitivity:** the two fixture sequences in this review must produce different time-indexed macro curves even though their global summaries match.
2. **Known segment response:** detected sparse/dark and dense/bright regions must map to the declared expected direction; test tolerance is measured against exact synthetic segment boundaries.
3. **Boundary discipline:** the control curve may update only at the selected rational phrase/section boundaries, never at arbitrary analysis-frame positions.
4. **Hysteresis/smoothing:** a synthetic feature sequence alternating around a threshold must not chatter; step and slew limits are asserted numerically.
5. **Confidence/silence:** silent, corrupted and low-confidence windows must not produce a spurious macro excursion.
6. **Identity invariants:** deterministic reruns preserve protected anchor event IDs, motif identity, tempo/form and the original source bytes; intentional changes have an explicit mutation contract and provenance.
7. **Manual override:** a user-authored value wins over the analysis proposal and survives save/reopen.
8. **Reset/undo:** returning to the source baseline restores the exact original Score/config fingerprint and removes only the conditioned proposal.
9. **Resource budget:** benchmark analysis plus planning at 48 kHz for 30 s and 180 s, reporting CPU wall time, peak RSS and temporary buffers. Numeric budgets must be declared from a named target machine before claiming acceptance.
10. **Musical comparison:** render the conditioned proposal and static-macro baseline with the same source, Score invariants, seed and mix. A human must report an audible compositional benefit in context; feature correlation alone is not acceptance.

## Evidence still required to open implementation

- A real break/stem/reference and a precise musical problem it should help solve.
- A baseline composition made with current Reawarp tools and the exact limitation encountered.
- A matched static-macro versus conditioned render, reviewed in context and at matched loudness.
- Target-machine 30/180-second resource measurements and declared budgets.
- Explicit human decision on which anchors and structural invariants must remain fixed.

Until that evidence exists, M34 remains a research note and regression baseline. M24.5–M24.7 retain their separate planned/research statuses. No production processor, GUI, routing schema or generated-score mutation has been added by this review.
