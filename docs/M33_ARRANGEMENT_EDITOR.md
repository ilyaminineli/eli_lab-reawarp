# M33 — Arrangement Editor, Manual Composition and Print-to-Track

**Status:** Core implementation delivered; human listening acceptance remains open  
**Date:** 26 November 2026  
**Canonical model:** `Score` plus the versioned `m33_arrangement` record in Score metadata

## Intent and boundary

M33 makes selected phrase material into a manually authored piece without turning Reawarp into a general-purpose DAW. The Score remains the only source of event timing and identity. The arrangement document stores where each phrase is placed, which event IDs it owns, where those events originated, whether the phrase is frozen or muted, and which M28 candidate supplied the selected material.

All musical positions are exact rational beats. Move and trim operations update the canonical Score events and the M28 PhrasePlan together. No independent floating-point clip clock or destructive source-sample editor is introduced.

## Arrangement model

`src/reawarp/composition/arrangement.py` owns the service layer:

- `ArrangementClip` stores a stable clip ID, current phrase ID, source phrase ID, rational source/destination spans, current and original event IDs, candidate/parent lineage, freeze/mute state, role exchange map, origin and revision.
- `ArrangementPlan` validates the arrangement schema, its content fingerprint, the Score revision fingerprint, phrase identity, exact phrase boundaries and all referenced event IDs.
- `m33_arrangement` metadata retains the original pre-arrangement Score snapshot, ordered phrase references, human finishing checklist, print records, a bounded undo/redo journal and a durable edit audit log.

The `origin` field distinguishes generator-originated, candidate-originated and manually edited material. Candidate identity is retained when a selected candidate is subsequently moved or duplicated; the edit journal separately records the manual operation. Each edit records actor, action, revision, operation details and before/after Score and arrangement snapshots. The undo stack retains the latest 50 reversible edits to bound archive growth; the audit log retains the latest 200 edit/undo/redo records.

## Editing operations

The Arrangement Editor workspace is available under **Compose → Arrangement**.

- **Create from phrases** builds one arrangement clip for each existing M28 PhraseSpan. It requires a non-empty, valid PhrasePlan and does not change the original Score.
- **Move** changes a phrase's exact start beat and shifts its events and phrase boundaries without changing event IDs or durations.
- **Duplicate** creates a new phrase ID and new event IDs. It retains the original source-event IDs and parent clip ID, so the copy is editable without stealing identity from the source.
- **Trim** crops intersecting events to exact phrase boundaries and removes events outside the selected range. Zero-duration events inside the half-open trim interval are retained. Frozen clips cannot be trimmed.
- **Reorder** compacts the phrase sequence from its current start beat and retains the ending's offset relative to the complete phrase sequence. The operation is committed as one undoable edit.
- **Mute / unmute** sets note/hit velocities to zero on the Score, saves their prior velocities, and restores those exact values on unmute. Events are not deleted.
- **Exchange layer** reassigns selected phrase events from one Score voice to another, updates phrase role participation and records the role map. A frozen clip cannot exchange layers.
- **Replace with candidate** installs the selected M28 candidate events with fresh arrangement event IDs and preserves the candidate ID, operation, seed and original source-event lineage. It never silently imports a different phrase's candidate.
- **Freeze selection** protects content from trim, layer exchange and candidate replacement while allowing arrangement placement to change.
- **Branch arrangement** creates a new arrangement identity with a parent reference and unfreezes the branch for further edits.
- **Revert to generation** restores the stored pre-arrangement Score and rebuilds the initial phrase clips. It is itself undoable.
- **Undo / redo** restore Score and arrangement snapshots through the canonical Score renderer when audio content changes.

M28 phrase definition editing, deletion and M28's separate freeze/restore controls are locked while an M33 arrangement is active. This prevents a second workspace from changing phrase membership beneath an arrangement. Revert to generation returns to the M28 phrase workflow.

## Transitions and endings

M30 transition and ending plans remain Score-native cue objects on the M33 timeline. A cue can be moved in exact beats. A transition can also be relinked to a new outgoing/incoming phrase pair after a reorder; relinking preserves the three phase durations and anchors preparation to the new source phrase end. It is rejected when the existing durations cannot fit the source and target spans. Moving a phrase automatically carries a linked cue where the M30 phrase-boundary constraints remain valid; otherwise the cue remains explicit and can be repositioned or relinked by the composer.

M30 markers remain silent Score markers, not audio events. Ending movement preserves the ending strategy and duration.

## Print-to-track

**Print to new WAV** renders only the selected phrase's Score events through the offline Score renderer and writes a separate 24-bit PCM WAV object. The print operation crops to the exact phrase's rendered time interval, leaving the project's master and existing dry stems untouched. The print record includes:

- clip, phrase, candidate and event identities;
- original source-event IDs and current Score event IDs;
- output path/name, sample rate, frame count and duration;
- SHA-256 of the actual WAV bytes;
- renderer identity and arrangement revision.

Print lineage is attached only after the WAV header and supplied frame/sample-rate values are checked against the file. If the arrangement changes or the project is switched while a print is running, the file is retained at the selected path but is not falsely attached to the new project.

This print path is a **dry Score print**. It does not claim to include per-stem inserts, shared SPACE/ECHO returns, or final mastering. Those remain part of the existing mixer/delivery workflow.

## Finishing checklist

The editor stores human checkmarks for form review, ending review, subtraction, identity/invariance, contextual audition, low-volume translation, mono, peak/headroom, missing sources and export integrity. These are human-entered sign-off prompts, not automated artistic scores and not claims that the checks passed merely because the software rendered successfully.

## Save, reopen and export

The arrangement is serialized inside `score.json` as Score metadata, so the regular project loader reopens the same rational-beat phrase timing, event references, M28 candidate/source lineage and M30 cue plans.

When M33 state exists, `ReawarpProject.export()` additionally writes:

- `arrangement_snapshot.json` — schema, arrangement, timeline, checklist, edit/undo history, audit log and print export status;
- `arrangement_prints/` — verified copies of printed WAVs whose source hash still matches the print record.

The regular project package continues to include the canonical Score, events, combined/per-voice MIDI, dry stems, routed master, M32 critical-listening report and manifest. The manifest inventories the M33 snapshot and copied print files. Missing or changed source WAVs are reported instead of silently substituted.

## Tests and acceptance

Automated coverage lives in:

- `tests/test_m33_arrangement.py` — exact-beat operations, event identity, candidate replacement, undo/redo, M30 cue editing/relinking, print verification, export/reopen.
- `tests/test_m33_arrangement_ui.py` — workspace signal wiring, selection, candidate filtering and checklist interaction.

**Still open:** full human listening sign-off on real compositions; detailed target-Windows listening/performance acceptance; and confirmation that dry phrase prints fit the intended production use. M33 deliberately does not add a full audio clip/fade/crossfade editor, live arrangement engine, destructive sample editing or automatic artistic quality score.
