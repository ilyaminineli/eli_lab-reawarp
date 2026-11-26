# M24.7 — Optional Parallel Processing Branches

**Decision:** Research gate retained — no parallel-branch feature approved  
**Audit date:** 26 November 2026  
**Audited baseline:** `main` at `60a50e9adb25617f2669ad29fa61feba9910e273`  
**Scope:** Reawarp's current offline FX chain and mixer; no schema or runtime change

## Gate decision

Do not implement M24.7 yet. The current mixer cannot express every imaginable parallel topology, but the repository contains no concrete composition in which that limitation prevents a useful result. Adding a generic branch model now would expand persisted routing, rendering, UI, latency, phase, tail and cache contracts without evidence that the added complexity solves a musical problem.

This is a deliberate hold, not a claim that parallel branches are already fully supported.

## What the current system can express

1. **Per-stem serial inserts.** Each stem has one ordered insert chain. The chain supports up to 12 validated stages, with a bounded dry/wet `mix` per stage and a chain-level wet blend. The insert is rendered offline and the dry stem remains intact.
2. **Two parallel auxiliary returns.** Every stem can send to the shared `SPACE` and `ECHO` returns. Each return has its own shared chain and wet amount. Returns are wet-only; the dry signal stays on the direct path.
3. **Four send tap positions.** A send can take pre-insert/pre-fader, pre-insert/post-fader, post-insert/pre-fader or post-insert/post-fader material. Send levels and return wet levels can be automated.
4. **One-way sidechain control.** M24.5 can derive a bounded gain envelope from one source stem and apply it to a different target stem before the target insert.
5. **Bounded timing assumptions.** The built-in routing path reports zero processing latency and start-aligns the built-in chains. Insert and return tails are tracked separately.

Relevant implementation: `src/reawarp/fx.py` (stage and chain dry/wet mix), `src/reawarp/fx_routing.py` (`FX_BUSES`, per-stem inserts, send taps, shared return render and tail report), and `src/reawarp/sidechain.py`.

## What is not expressible today

- Two or more independently configured insert chains on the **same stem**, processed from the same tap and blended back together as separate per-stem branches.
- A branch-specific chain and gain/automation lane for each such branch. The current two returns are global shared buses: stems feeding one bus share that bus's chain and return controls.
- An arbitrary branch-combine graph, branch-to-branch routing, or branch-specific latency compensation. Those are outside the current M22 contract.

The absence of those structures is not, by itself, a reason to add them. The current stage-level and chain-level blends already cover ordinary dry/wet parallelism; the two shared returns cover common shared-space and echo paths.

## Evidence required to reopen

Before implementation, one real use case must provide all of the following:

- The source project or reproducible source stems, the role being processed and the exact musical passage.
- The intended branches (input tap, distinct processing chains, branch gain/automation, and where their outputs recombine).
- A baseline attempt using the current serial insert, stage dry/wet mix and SPACE/ECHO returns, with a precise explanation of what cannot be achieved.
- A matched-loudness comparison showing the desired parallel result contributes something audible and musically useful, not merely a different parameter configuration.
- A statement of the required channel layout, expected latency/tail behaviour, and acceptable CPU/memory budget.

Without this evidence M24.7 remains deferred. No default branch count, branch schema, UI or processing graph is being proposed as if already accepted.

## Minimum engineering contract if the gate passes

A future design must define, test and expose before it is wired into projects:

- **Topology:** bounded branch count and explicit source tap; no unrestricted graph, cycles or implicit feedback.
- **Alignment:** declared latency for every branch, deterministic compensation, and a documented policy for phase-sensitive recombination.
- **Gain law:** explicit linear/equal-power or other justified blend law, with defined dry retention and peak/headroom reporting.
- **Tail ownership:** per-branch tail cap, output-length rule, and deterministic summing of branch tails.
- **Channels:** mono/stereo handling and deterministic channel mapping.
- **Lifecycle:** reset, cancellation, panic/stop, stale-render rejection and bounded temporary memory.
- **Persistence:** versioned routing schema with migrations that preserve all existing v1–v4 projects exactly.
- **UI and audition:** source/branch controls, per-branch meters, matched-level branch solo/A-B and an unmistakable bypass path.
- **Validation:** impulse alignment/latency tests, phase tests, gain-law tests, tail/headroom tests, schema round trips, source immutability, deterministic rerenders and target-Windows 30/180-second benchmarks.
- **Acceptance:** a human matched-level listening review on the real use case before adding the feature to default routing.

## Related coverage

Current baseline is covered by `tests/test_fx_contracts.py`, `tests/test_m22_routing.py`, `tests/test_m24_5_sidechain.py` and the M24.6 standalone processor tests. These tests establish existing contracts; they do not prove that an additional parallel branch feature is needed.
