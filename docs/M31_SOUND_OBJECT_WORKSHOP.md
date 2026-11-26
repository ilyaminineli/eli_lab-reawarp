# M31 — Sound-Object Workshop and Resampling Lineage

**Implementation note · 26 November 2026**

## Architecture

M31 is a thin authoring and print layer around the existing M21 SoundObjectPatch, HybridVoiceRenderer, sound_object_editor_model and SampleLibrary services. Qt does not duplicate the patch model or DSP renderer.

## Delivered core

- A dedicated Sound Objects workspace imports a linked audio source as a body-layer object, selects saved patches, edits identity and frame-addressed layer fields, and saves immutable patch revisions.
- Transient/body/tail/texture/voice layers can be auditioned individually or as one aligned object through the M21 renderer. Rendering runs in a cancellable background worker; audio output is optional for editing and waveform inspection.
- SoundObjectVersion snapshots are content-addressed and revisioned in SQLite. Re-saving identical patch content is idempotent.
- RoleAssignment derives a distinct processing identity for each (object version, target role) pair.
- Printing writes a new WAV asset, optionally resamples it, indexes it in SampleLibrary, and stores ResampleRecord provenance: source object version, source asset IDs and SHA-256 values, transformation chain, renderer version, settings, seed, sample rates, rendered-audio hash, output-file hash and role assignment.
- Source paths are protected against accidental overwrite. Missing assets and hash mismatches are reported rather than silently replaced.

## Render and lineage boundary

The workshop invokes the existing M21 HybridVoiceRenderer. A print is a new sample-library asset and never edits project stems or source files. The renderer version tag identifies the algorithm family; the output hash remains the authoritative identity of the actual print across differing runtime environments.

## Validation and remaining acceptance

Automated checks cover version history and idempotence, layer-solo alignment, original-file protection, source-hash and print lineage, sample-rate conversion, role-specific processing IDs, and headless UI editing.

Human listening acceptance remains open for transient/body/tail balance, mono translation, object reuse across multiple roles and A/B comparison in a full arrangement. Optional coherent-family generation and direct printing of selected phrase/stem/FX stages remain follow-on integrations.
