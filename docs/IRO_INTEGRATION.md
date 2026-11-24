# IRO ↔ Reawarp integration

**Status:** integration contract and first runtime adapters in progress.

IRO is a shared creative system across:

- `eli_lab-math-cover-generator`: release equations, feature fields, entity families, generated drum kits, sound-lab material and release-driven sound FX.
- `sonicpi_eli_lab`: performance grammar, sample maps, named project scenes, a shared master beat clock, feature-reactive state and role-specific live voices.
- `eli_lab-reawarp`: deterministic offline composition, sample-driven stems, break transformation, hybrid synthesis, FX routing and project provenance.

These repositories are related, but they are not interchangeable. Reawarp should consume the IRO assets and their metadata without treating a Sonic Pi live patch as a renderer specification or flattening the release into a generic drum-kit folder.

## Source identity

The current IRO release represented in `samples/Iro` is:

- Release title: `るもらをぬてふ`
- Release code: `24-73-41-25-23-57-54`
- Release seed: `211`

The IRO Track 01 project `けれあけ` has its own track seed `312`, tempo `113 BPM`, 392-beat main score and an 8-beat residue coda. These identities must remain separate in project metadata: release provenance is not a track seed.

## Current checkout limitation

The current Reawarp Git tree contains the IRO manifests, indexes and documentation, but **no `.wav` files anywhere under `samples/Iro`**. Therefore the IRO adapter currently exposes manifest/index entries as metadata-only records (`available=false`); it does not generate substitute audio or fall back to source paths. The drum index contains 96 generated kit entries, the eight entity manifests contain 48 entity variants, the sound-lab manifest lists 32 one-shots/four loops/four stems, and the sound-FX manifest lists 18 event variants/four loops. Their generated/source WAV payloads still need to be committed or supplied before Reawarp can audition or render them.

The Generator filters unavailable records out of its selectable sample controls. The Library can still search the metadata, display sonic identity/equations and report missing files. SHA-256 values in the index remain expected hashes; a hash cannot be verified until its file exists.

## Asset hierarchy already shipped in Reawarp

- `samples/Iro/entities/<family>/`: eight mathematical families—boundary_shard, coordinate_slip, interference_knot, phase_fracture, quantization_residue, ratio_orbit, recurrence_ghost, spectral_bloom.
- `samples/Iro/experimental-drum-kit-211/`: 96 instrument/articulation WAVs plus source indexes, drum manifest, drum map, MIDI note mapping and mutated kit alternatives.
- `samples/Iro/sound-lab-211/`: 32 one-shots, four loops, four stems and MIDI/MusicXML material.
- `samples/Iro/sound-fx-211/`: nine release-driven event families (with variants), four beat-aligned loops and an asset index.

The files are grouped by their generation identity and sonic family. Preserve that structure; do not rename all samples to generic role filenames.

## Manifest and integrity contract

The first Reawarp adapter reads the drum, sound-lab, sound-FX and entity manifests. Each asset retains:

- pack and relative path;
- role and mathematical/sonic family;
- articulation or variant;
- SHA-256 when the manifest supplies it;
- sample rate, duration and channel metadata when available;
- source feature index and seed when present;
- equations, synthesis approach and sonic identity as descriptive provenance.

Manifest paths must remain inside their pack root. Source audio is read-only. Hash mismatches and missing files must be visible; an asset must not be silently replaced by a similarly named WAV.

## Role mapping for composition

Suggested first-pass role mapping (kept distinct from source family):

| IRO source role/family | Reawarp use |
|---|---|
| kick, sub_kick | kick / low-frequency anchor |
| snare | snare / principal backbeat |
| closed_hat, open_hat | hat / subdivision and high-frequency surface |
| rim_click, phase_click, residue_snap | click / ghost / transition punctuation |
| metallic_ping, glitch_tom, hybrid_percussion | percussion / accent / counter-gesture |
| granular_shaker | high-frequency texture / granular percussion |
| eight entity families | math entity / motif fragments / transition events |
| sound-lab one-shots | one-shot / melodic and percussive gestures |
| sound-lab loops | rendered loop / source phrase |
| sound-lab stems | rendered stem / phrase layer or harmonic bed |
| sound-FX event families | event texture / transition / impact / residue |
| sound-FX loops | structural event loop / build / collision / aftershock |

Role assignment is an interpretation layer. The original IRO role and family must still be stored in event and project metadata.

## Composition philosophy carried from the IDM guides

The guide set treats composition as relationships over time, across event, pattern, phrase/section and whole-track scales. It emphasises local surprise inside global intelligibility, a small vocabulary of identity-bearing materials, one principal change at a time, and purposeful contrast/negative space.

The IRO Track 01 arrangement offers a concrete named arc:

`Signal → Construction → Orbit → Collision → Overload → Aftershock → Unravel → False Return → Residue`

Its Sonic Pi implementation uses a shared integer master beat clock and independent role voices. Reawarp should express the same principle offline: one shared project/form state, with independent deterministic event streams and separate stem renderers. Do not force all voices into one pattern or erase fractional source timing when importing future polyrhythm data.

## Phrase grammar direction

Reawarp's phrase director maps formal sections to recognisable functions:

- introduction / establishment;
- continuation / development;
- uplift / arrival;
- drop / silence;
- contrast;
- return / false return;
- residue / outro.

The function controls activity and orchestration roles, not master loudness alone. A drop can reduce kick/snare while leaving a quiet residue or ambience. An uplift can increase event activity, register, brightness or interlock without merely raising every track. A return should recall identity-bearing material while changing a limited number of dimensions.

## Non-goals

- Do not make Reawarp dependent on a live Sonic Pi session.
- Do not execute equation strings from IRO JSON.
- Do not duplicate assets just to satisfy a new interface.
- Do not treat a generated IRO manifest as a license record.
- Do not equate greater event density with greater musical quality.
