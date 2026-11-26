# M27 — Artistic Intent and Mutation Contracts

**Status:** Generator / GenerationConfig workflow implemented  
**Scope:** Versioned brief, source identity resolution, bounded configuration exploration and project provenance  
**Current limitation:** permitted GenerationConfig fields are sampled once per generation; they are not yet scheduled as repeated event-, pattern-, phrase- or section-local changes

## Intent is separate from configuration

A `CompositionBrief` expresses what the piece is about and what must remain recognisable. `GenerationConfig` remains the validated set of actual renderer/planner inputs. M27 does not replace the canonical Score or introduce another event scheduler.

The brief records:

- Artistic question and listening mode.
- Named A/B/C materials, optional roles and source-family identities.
- Anchor type, target and stability.
- Pitch world (scale, root and tuning identity). It is applied to melody scale/root only when explicitly authored or non-default; otherwise the current Generator pitch settings remain authoritative.
- Contrast targets and intended ending behaviour.
- Per-target mutation contracts and a separate tempo/form policy.

The Generator's **M27 / Artistic Intent + Mutation Contracts** editor is part of the Generator control panel. It authors the brief, but contains no renderer or project state. The **Apply Brief to Current Project** button adds the brief and its resolved-source record to the current project's metadata without rerendering audio.

## Source identity and resolution

The resolver snapshots available `GenerationConfig.sample_paths` and `sample_banks` into role-labelled source families. References retain asset ID and SHA-256 when present; custom unindexed sources fall back to role and exact path identity.

Before generation, each brief source is checked against the current configuration. A missing family, changed role, changed asset ID/hash or mismatched path is an error. Reawarp does not silently replace a named source with another member of the same sample role.

Project export continues to use the existing manifest policy (`copy` or `reference`). On reopen, the project manifest audits embedded/external source files, while M27 provenance validates the saved brief fingerprint, resolved-intent schema, source snapshot record and root generation seed.

## Mutation permissions

A `MutationContract` names a target, one of the existing event/pattern/phrase/section intent scales, an explicit list of mutable GenerationConfig fields, preserved fields, optional numeric bounds or categorical allowed values, cadence, decision boundaries and stop/freeze conditions.

The executable adapter is intentionally conservative:

- A field not listed in a contract cannot change.
- A field may appear in only one active contract. A field declared invariant anywhere in the brief cannot be mutated by another contract.
- Source/clock invariants are always protected: `seed`, `sample_rate`, `sample_paths`, `sample_metadata` and `sample_banks`.
- BPM, duration and formal trajectory/flow remain fixed unless `TempoFormPolicy` explicitly sets the matching mode to `explore`. Their chosen ranges are bounded by GenerationConfig's legal domains.
- Numeric and categorical options are validated again when a mutation is applied. Unsupported fields, enum values, break transforms, bounds, cadence or stop conditions fail before generation.
- Every changed field gets its own stable random stream derived from root seed, brief ID, contract ID, scale and field name. Changing one contract/field does not advance another field's random stream.
- Mutations are opt-in. A brief with mutation permissions but with bounded exploration disabled does not randomise the current generator values.

**Current execution limit:** although contracts retain event/pattern/phrase/section scale and decision-boundary intent, the current adapter translates them to a single bounded GenerationConfig selection before planning. It does not yet make repeated per-event or per-phrase decisions inside the composition. Those future behaviours require explicit Score/phrase mutation services and their own tests.

## Generation and project records

Use the public API:

```python
from reawarp import GenerationConfig, ReawarpEngine
from reawarp.composition import (
    CompositionBrief,
    quick_mutation_contracts,
)

brief = CompositionBrief(
    brief_id="machine-pulse-study",
    artistic_question="Can the anchor pulse survive unstable surroundings?",
    listening_mode="close listening",
    mutation_contracts=quick_mutation_contracts(
        ("arrangement_density", "tonal_brightness")
    ),
)

project = ReawarpEngine().generate(
    GenerationConfig(seed=211, duration=12.0),
    composition_brief=brief,
    bounded_exploration=True,
)
project.export("output/machine-pulse-study")
```

Generated projects carry these metadata records:

| Key | Purpose |
|---|---|
| `m27_composition_brief` | Complete versioned, user-authored brief |
| `m27_resolved_intent` | Brief fingerprint, generation seed, resolved source-family snapshot, preserved fields and warnings |
| `m27_bounded_exploration` | Applied contract IDs, before/after field values, independent seed lineage and preserved fields; null when not enabled |
| `m27_bounded_exploration_enabled` | Explicit user opt-in state |

When reopening an M27 project, Reawarp validates the brief, resolved-intent schema and fingerprint, generation seed, changed fields, contract ownership, final GenerationConfig values and deterministic seed lineage. Old projects without M27 metadata remain legacy-unstructured; merely loading one does not create or save an inferred brief.

## Automated verification

- `tests/test_composition_brief.py` — schema, material/source references, strict resolution and pitch-world semantics.
- `tests/test_mutation_contracts.py` — deterministic independent field streams, permission enforcement, invariant conflicts, explicit tempo/form policy and unsupported cadence.
- `tests/test_m27_integration.py` — engine integration, project export/reopen, tamper detection, legacy loading and Generator editor round-trip.
- CI's desktop smoke checks that the M27 editor is part of the actual Generator workflow.

A passing test suite establishes reproducibility and permission boundaries; it does not judge whether the brief makes a better composition. Artistic authorship and listening acceptance remain human decisions.
