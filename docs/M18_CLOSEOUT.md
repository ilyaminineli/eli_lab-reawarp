# M18 close-out and acceptance record

**Implementation status:** Complete for the deterministic offline Score-control contract on `main`'s current architecture.  
**Experimental sign-off:** Target-Windows performance profiling and Pyo-enabled matched-level listening remain open cross-cutting evidence items (M14/M22); they are not represented as passed by CI.

## Final implementation review

The implementation now includes:

- Typed target contracts, strict units/ranges/interpolation validation, and backward-compatible Score JSON.
- Global, section, role and event lanes with deterministic absolute/relative precedence.
- Reusable deterministic LFO, envelope, stepped, random-walk and phrase-curve sources, including selectable LFO shapes and editable point lists.
- Source-to-destination modulation with polarity, add/multiply, bounded outputs, base values, retrigger and scope.
- Shared beat/frame clock control evaluation, tempo-ramp support, destination update clocks, smoothing/hysteresis and active-state masks.
- ScoreRenderer consumption for event/role probability, velocity, role activity, density thinning, syncopation placement, articulation and sample contribution.
- Production voice consumption for cutoff/resonance/gain, onset pitch, note ADSR, continuous vibrato, wavetable position, additive partial balance and granular size/position/density where supported by that instrument family.
- ScoreRenderer spatial pan/width processing.
- Fixed FX router integration through the typed control bus using the existing explicit M13 identifiers: per-stem insert wet, per-stem SPACE/ECHO sends, and SPACE/ECHO return wet. The M13 schema-v1 adapter remains backward compatible.
- Score Control editor with templates, score-aware scope suggestions, editable curve preview, undo/reset and offline Apply & Re-render.

## Important architectural boundary

The generic registry identifiers `fx.insert.wet`, `fx.send.space`, `fx.send.echo`, `fx.return.space.wet` and `fx.return.echo.wet` are descriptive catalogue targets; the production fixed router consumes its established explicit identifiers (`stem.<name>.insert_wet`, `stem.<name>.send.space`, `stem.<name>.send.echo`, `bus.space.wet`, `bus.echo.wet`). This deliberately avoids guessing a destination when multiple stems or buses exist. The Score Control editor exposes the concrete stem-aware targets from the loaded Score.

Planner-facing density/syncopation/articulation controls operate as deterministic Score render-performance transformations at event/phrase boundaries. They do not rewrite the canonical symbolic Score or rerun the upstream stochastic planner. A future interactive planner-regeneration contract would need explicit regeneration provenance and is not silently implied here.

## Automated acceptance

Existing focused M18 tests cover:

- old Score JSON compatibility and M18 round-trip;
- deterministic sources and modulation, including phase/retrigger and tempo ramps;
- scope isolation, active-state masks, smoothing/hysteresis and bounded probability;
- event density, syncopation, articulation, voice expression across five palettes;
- wavetable, additive partial and granular destinations;
- shared control-bus compatibility with downstream FX targets.

Cross-platform CI evidence recorded by the project at the time of this close-out: 129 tests passed per job on Linux Python 3.10–3.12 and Windows Python 3.11. This record is inherited project evidence; no new CI run or local audio audition is claimed by this documentation-only close-out.

## Remaining cross-cutting experiments

1. On the target Windows/RTX 4060 machine, benchmark 30 s and 180 s at 48 kHz with and without automation, recording Python/NumPy/SciPy versions, CPU, memory, render time, real-time factor and peak memory.
2. Render matched-seed variants: dry baseline, slow macro, event-relative envelope, coupled modulation, stem-aware insert/send/return automation.
3. Audition the full mix and isolated roles at matched perceived loudness; note transient integrity, brightness, pitch stability, stereo mono-compatibility, foreground masking and negative space.
4. Verify optional Pyo FX integration on the target setup.

These are explicitly **experimentally unverified**, not software implementation blockers.

## Decision

M18 is closed as an implementation milestone. Its offline deterministic control model, production voice and fixed routing consumers, and authoring surface are integrated. Hardware profiling and critical listening remain tracked under M14/M22.