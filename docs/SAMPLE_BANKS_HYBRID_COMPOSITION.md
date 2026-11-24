# Sample banks, drum-part automation and hybrid synthesis

## Purpose

Reawarp's composition plan, drum grammars, synthesis profiles and sample library now share a role-level source contract. The selected sound in each Generator selector is the **anchor** for that role. Other eligible assets from the bundled sample folder and the indexed Library can become phrase-aware alternatives.

No sample file is copied, renamed or modified. The project stores the asset path, content hash, descriptors, role and source metadata so the resulting arrangement is reproducible.

## How the role bank is assembled

The Generator builds separate kick, snare and hat banks in this order:

1. The currently selected Generator sample is first and becomes the opening/return anchor.
2. Other bundled samples discovered under `samples/` for the same role are added.
3. When **Include indexed Library assets** is enabled, indexed audio with an explicit role or a recognizable filename/folder role is added with its measured feature descriptors.

Paths are deduplicated. The current UI bounds each role bank to 65 entries. The SQLite Library is read as an index; the source audio remains in its original location.

Feature-guided selection uses the indexed spectral centroid, RMS level, spectral flatness, onset density and crest factor when available. Assets without indexed features can still participate, with neutral descriptor defaults. A feature index is useful but not required for playback.

## Drum sample automation

The Generator's **Switch sample parts through the track** control enables bank selection. The schedule can be:

- **Fixed:** use the selected anchor for the entire track.
- **Section:** choose a part when a new formal section begins.
- **Cycle:** choose a part at the start of each configured drum cycle.
- **Automatic:** preserve the anchor through introduction and establishment, change material in development/uplift/arrival/contrast/transition functions, use a related alternative for a false return, and recall the anchor for a true return.

The choices are deterministic from the project seed, role, section and cycle. Sample changes do not consume the hit-level pattern or synthesis random streams. Each change is recorded with its bar, section, phrase function, previous/next asset and label.

The same drum event stream drives synthesis and sample playback. Changing a sound source does not create a parallel rhythm or a second set of hits.

## Hybrid source modes and architectures

The source mode selects the overall balance:

- **Automatic:** phrase-aware sample contribution, reduced in introductions/drops/residue and increased for developments/uplifts/arrivals.
- **Synthesis only:** no sample playback or sample switching.
- **Hybrid:** a stable user-selected sample/synthesis blend.
- **Sample only:** sample hits without a parallel synthesized voice.

The hybrid architecture then defines how the two sources relate:

| Architecture | Sample role | Synth role |
|---|---|---|
| Transient sample + synth body | Uses a short, faded onset from the selected sample | Supplies the pitched/body component |
| Parallel full layers | Plays the full sample | Plays the full synthesized voice at complementary gain |
| Feature-guided hybrid | Uses a sample transient window shaped by its crest factor | Adjusts synthesized voice, pitch and velocity using the selected asset's spectral brightness and onset density |

The sample contribution and transient window remain user-adjustable. Feature-guided synthesis falls back to neutral descriptors when an asset has not been indexed.

## UI workflow

The Generator is presented as one scrollable sequence rather than isolated FORM / VOICES / RHYTHM tabs. A persistent top action bar keeps **GENERATE TRACK** visible while the user scrolls through the settings.

The action bar describes the connected path:

`FORM → DRUM PARTS → SAMPLE LIBRARY → SYNTHESIS → RENDER`

After rendering, the summary reports bank sizes, sample changes, section/timbre maps and the selected source architecture. Sample changes are also preserved in `metadata.sample_switch_summary`, `metadata.sample_sources` and per-hit event records.

## Current scope

The first connected role banks are kick, snare and hat. Break Lab remains the separate path for long-form break material and transformations. The feature-guided architecture currently uses spectral centroid, flatness, onset density and crest factor for the percussion roles; future instruments can reuse the same role-bank contract.
