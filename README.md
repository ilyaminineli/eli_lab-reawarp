# eli_lab-reawarp / 再変形

A deterministic mathematical audio laboratory for IDM percussion, synthetic breaks, eccentric melodic sequences, and stem generation.

Reawarp is an offline-first Python audio engine. Its synthesis core is independent of the desktop layer and optional third-party analysis or playback backends. It renders compositions up to three minutes, synchronized stems, and machine-readable event provenance.

## Current implementation

### Synthesis and composition (M9)
- Long-form composition planning up to 180 seconds with classical-arc, transformed-sonata, free-jazz, episodic, minimal-variation, and Autechre-inspired process-form presets.
- Structure flow controls: preserve a preset, cross-mix its movements with another formal grammar, or mutate the order of inner movements deterministically.
- A pattern grammar library with asymmetric, interlocking, ghost-break, omission, rotating-cycle, ratchet, cross-accent, and broken-regularity families, selected per form and section.
- Pattern relationship controls for unison, interlock, shadow/phase offset, call-and-response, and counter-accent; motif transformation utilities include retrograde, inversion, augmentation, diminution, fragmentation, reordering, and displacement. Formal-section pattern auto-switching is opt-in in the desktop UI or via `--pattern-follow-structure`, preserving legacy break phrases by default.
- Role-driven lead synthesis defaults to a genuinely subtractive voice (harmonic source, moving low-pass filter, restrained resonance and envelope); additive, FM, modal, inharmonic, granular and scanned/pulsar voices remain selectable alternatives.
- Drum synthesis is independent of the melody renderer: minimal dry transient/body/tail kick, snare and hat voices are the default; extended resonant voices and the legacy profiled sample-style renderer remain selectable.
- Legacy profile catalogues remain available when `percussion_synthesis=samples` is selected.
- Subtractive lead voices use independent oscillator/filter/envelope code paths rather than routing every named palette through FM.
- A separate harmonic ambience stem with filtered noise, slow stereo movement, and restrained early reflections.
- A structured 16-step break grammar (broken funk, half-time, straight, sparse) with density, phrase-cycle, and bounded variation controls.
- Imported break recordings are transient-sliced and triggered on the groove grid; complete clips are no longer stacked at every trigger.
- Euclidean, modular-prime, Fibonacci-accent, and logistic-map rhythm material in the other percussion lanes.
- Lissajous-derived melodic contours with profiled synthesis.
- Independent random streams per generator and synthesis/profile lane.
- Stem-only regeneration while preserving unrelated stems bit-identically.
- A local SQLite sample/stem library with timbral and rhythmic descriptors, similarity ranking, named collections, and variation genealogy.

### Offline sound design (M10–M13)
- A separate FX Lab loads external mono/stereo audio without changing the source file.
- Optional Pyo offline processing with high/low/band-pass filters, saturation, delay, frequency shift, and Freeverb stages.
- Four starting chains: restrained space, tape echo, metallic machine, and digital fracture.
- M11 adds a serial-chain editor: add/remove stages, reorder processing, edit each stage’s parameters and mix, and save/load portable versioned JSON chains.
- M12 adds per-stem inserts and shared SPACE/ECHO sends/returns in the Stem Mixer, with a separate offline routing render and non-destructive export.
- M13 adds beat-based deterministic automation for insert wet, per-stem sends, and shared return wet, plus tempo-synchronised delay divisions on the ECHO bus.
- Global wet/dry blend, explicit tail allowance, dry/processed waveform and spectrogram comparison, audition, and 24-bit WAV export.
- The `reawarp-fx` command renders starter presets or user-authored chain JSON; Pyo is not required by the base generator.

### Editable processing, role-aware routing, and musical automation (M11–M13)

M11's serial chain editor supports add/remove/reorder operations, bounded stage parameters, per-stage wet/dry, global wet/tail, and portable versioned JSON.

M12 brings those chains into the generated-project Stem Mixer. Each stem can have its own insert and post-insert sends to the two shared returns, SPACE and ECHO. The design is intentionally small and dry by default. Original stem exports remain untouched; insert tails can feed shared sends and returns can extend the routed master.

M13 adds deterministic beat-addressed automation for insert wet, stem sends, and bus return wet, along with tempo-synchronised delay divisions. Automation JSON is portable and independent from routing JSON. Pyo remains optional and is needed only when an active insert or send is rendered.

### Integrated composition and source engine

Reawarp uses the audio already shipped in `samples/` as a selectable percussion library. The IRO repositories provide a related mathematical-sound and performance vocabulary; their manifests are kept separate from the actual bundled audio paths. See [IRO integration](docs/IRO_INTEGRATION.md).

The Generator now builds one shared kick/snare/hat score for both synthesis and samples. Section-aware drum grammars change the parts through the track, while preserving anchors and role relationships. Sample-only, synthesis-only, automatic and hybrid source modes render into the same role stems. Hybrid architectures can combine a short sample transient with a synthesized body/tail, or use a controlled parallel blend.

The phrase director remains responsible for the larger arc—introduction, establishment, development, uplift, arrival, drop, silence, contrast, return and residue—while the drum arranger and source engine translate those functions into actual patterns, timbres and source contributions.

See [M15 — Integrated composition-to-production workflow](docs/M15.md) for the shared drum-score, hybrid source and Generator architecture.

### Break transformation (M3)
- Transient detection from positive short-time energy flux.
- Automatic frame-accurate slicing with configurable slice limits.
- Slice/phrase rearrangement, stutter, and probabilistic dropout.
- Reverse and periodic gating with short edge fades.
- Pitch shifting and phase-vocoder time stretching.
- Jittered granular resynthesis and spectral freezing.
- Ordered transform chains applied in memory to imported break samples; source files are never overwritten.
- Transform and source provenance recorded in `project.json` and `events.json`.

### Audio and export
- Optional WAV sample overlays for kick, snare, hi-hat, and break lanes.
- Offline stereo rendering using float32 buffers.
- Synchronized individual stems and master WAV.
- 16-bit and 24-bit PCM WAV export.
- JSON project metadata and event provenance.

The core requires Python 3.10+ and NumPy. `requirements.txt` is an expanded environment inventory: every uncommented line is installed, including experimental integrations that may need native runtimes or platform-specific setup. `pyproject.toml` extras remain the curated install groups for supported features.

## Install

Create a virtual environment, then run:

    python -m pip install --upgrade pip
    python -m pip install -e ".[audio,m4,midi]"

For the minimal core:

    python -m pip install -e .

Optional analysis and music integrations:

    python -m pip install -e ".[analysis]"   # librosa analysis adapters
    python -m pip install -e ".[midi]"       # Mido MIDI import/export
    python -m pip install -e ".[theory]"     # music21 symbolic music theory
    python -m pip install -e ".[soundfont]"  # FluidSynth / SF2 source synthesis
    python -m pip install -e ".[pyo]"       # Pyo offline FX Lab backend
    python -m pip install -e ".[pippi]"     # experimental Pippi beta (platform caveat)

Install extras only when the corresponding feature is needed. A full M4/M5 development environment can also include analysis and symbolic-theory tools:

    python -m pip install -e ".[audio,m4,analysis,midi,theory,soundfont,synthesis]"

If upgrading an environment that previously had PySide6 6.12.0, remove the two optional 6.12-only Qt extension wheels left behind by the downgrade before running pip check:

    python -m pip uninstall -y PySide6-Pdf PySide6-WebEngine
    python -m pip check

Csound, SuperCollider, and FluidSynth also require their native runtimes when those adapters are used.

## Generate a composition (M8)

The composition duration can be up to three minutes. Example:

    reawarp --duration 180 --structure autechre_like --flow mix --pattern-family asymmetric_7 --pattern-relationship shadow --pattern-follow-structure --synth-palette subtractive --percussion-synthesis minimal --complexity 0.42 --seed 20261124 --output output/three-minute-study

Useful structure presets include `classical_arc`, `sonata_mutation`, `free_jazz`, `free_jazz_episodic`, `autechre_like`, `minimal_variation`, and `hybrid`. The `preset` flow preserves the chosen movement sequence, `mix` imports middle movements from a deterministic alternate structure, and `mutate` reorders the inner movements while retaining the opening and ending.

Choose a lead synthesis architecture with `--synth-palette`: `subtractive` (default), `hybrid`, `fm`, `additive`, `modal`, `inharmonic`, `granular`, or `physical`. `subtractive` is a separate renderer, not another FM preset. Choose drum construction separately with `--percussion-synthesis minimal|extended|samples`; `minimal` (default) uses sparse, dry transient/body/tail kick/snare/hat voices, while `samples` selects the legacy profiled drum renderers. The M10 FX Lab adds a separate non-destructive Pyo processing path; the core generator and NumPy reference renderer remain independent. Convolution, spectral delay, feedback-delay networks, cross-synthesis and oversampling remain later DSP modules; role-aware inserts and shared returns are implemented in M12.

## Generate a loop

    reawarp --bpm 137 --duration 12 --seed 20261123 --complexity 0.68 --output output/demo --midi-output output/demo.mid

Shape the break grammar and sound palette:

    reawarp --break-style broken_funk --break-density 0.50 --break-variation 0.25 --break-cycle-bars 2
    reawarp --melody-profile soft_keys --ambience-level 0.16

Use a fixed or automatically selected percussion profile:

    reawarp --kick-profile deep_sub --snare-profile acoustic --hat-profile dark

Process an imported break sample without modifying the original file:

    reawarp --break-sample samples/Breaks/my_break.wav --break-transforms slice_rearrange,stutter,dropout,reverse,gate --break-slice-count 16 --output output/processed

### Offline FX Lab (M10)

Install its optional backend and launch the desktop app:

    python -m pip install -e ".[pyo]"
    reawarp-gui

The FX LAB workspace loads a mono/stereo audio file, lets you build an ordered processing chain, and renders a separate result for dry/processed audition and export. The source is untouched. Start from a preset or edit its stages; each stage has its own mix and bounded controls. Save your chain as JSON to reuse it in the GUI or CLI:

    reawarp-fx input.wav output_fx.wav --preset tape_echo --wet 0.70 --tail 2.0
    reawarp-fx input.wav output_custom.wav --chain-json my_chain.json
    reawarp-fx --list-presets
    reawarp-fx --list-stages
    reawarp-fx --validate-chain-json my_chain.json

Available starting chains: `restrained_space`, `tape_echo`, `metallic_machine`, and `digital_fracture`. Pyo uses its offline server; it does not open the audio device to process the file. See [M10 FX Lab](docs/M10.md) and [M11 Editable FX Chains](docs/M11.md).

Pitch/time/granular operations accept their own controls:

    reawarp --break-sample samples/Breaks/my_break.wav --break-transforms pitch_shift,time_stretch,granular --break-pitch-semitones 5 --break-time-stretch 1.25 --break-grain-size-ms 75 --break-grain-density 1.6 --output output/warped

The output contains master.wav, a stems/ directory, project.json, events.json, and the synthesizer-independent score.json.

## Role-aware per-stem FX routing (M12)

After exporting a generated project, create a starter routing document:

    reawarp-routing output/my-composition --output output/routed

Validate or render a routing file without overwriting the source project:

    reawarp-routing output/my-composition --routing my-routing.json --automation my-automation.json --validate
    reawarp-routing output/my-composition --routing my-routing.json --automation my-automation.json --output output/routed

Generate four starter listening variants from the same dry stems:

    reawarp-routing output/my-composition --audition-matrix --output output/role-auditions

The audition matrix exports percussion, melody, ambience, and combined-role renders plus an RMS/peak report. The report is a signal-level aid, not a substitute for listening. The Stem Mixer exposes per-stem inserts, shared SPACE/ECHO sends, beat-based automation, and tempo-synchronised ECHO divisions. The routed export contains dry source stems, processed return WAVs, the routed master, fx_routing.json, fx_automation.json, and render metadata. See [M12 role-aware FX routing](docs/M12.md) and [M13 musical FX automation](docs/M13.md).

## Python API

    from reawarp import GenerationConfig, ReawarpEngine

    engine = ReawarpEngine()
    project = engine.generate(
        GenerationConfig(
            bpm=137,
            duration=12.0,
            seed=20261123,
            complexity=0.68,
            kick_profile="deep_sub",
            sample_paths={"break": "samples/Breaks/my_break.wav"},
            break_transforms=("slice_rearrange", "granular", "reverse"),
        )
    )
    project.export("output/my_loop", bit_depth=24)

    # Build the universal score from the render and export standard MIDI 1.0.
    score = project.to_score(title="My IDM sketch")
    score.save("output/my_loop/score.json")
    score.export_midi("output/my_loop.mid")

    # Regenerate only the kick; every unrelated stem remains identical.
    variation = engine.generate_variant(project.config, stem="kick", variation=2)
    variation.export("output/my_loop_kick_variation")

Supported custom sample roles: kick, snare, hat, and break. Break transformations are applied only to the imported break sample and run in memory. The original source file is read-only from Reawarp's perspective.

## Musical score and MIDI (M5)

Every rendered project can be converted to a synthesizer-independent score:

    from reawarp import Score

    score = project.to_score(title="Break study")
    score.save("output/score.json")
    score.export_midi("output/score.mid")

The score model includes:
- Rational beat positions and durations using fractions.Fraction.
- Piecewise step/linear tempo maps with beat/second conversion.
- Independent meter maps and bar/beat queries.
- Universal note, hit, grain, trigger, control, and marker events.
- Automation lanes with step, linear, cubic, and exponential interpolation.
- Exact frequency in Hz, fractional pitch coordinates, and a pluggable tuning-system interface.
- Event provenance, stable IDs, source references, tags, and seed information.

MIDI import/export is provided by the optional Mido adapter:

    reawarp-midi-import input.mid --output imported-score.json
    reawarp-midi-export imported-score.json --output exported.mid --ppq 960

The main reawarp command can also export MIDI for a freshly generated render with --midi-output.

MIDI 1.0 note numbers are integer semitones. Reawarp rounds fractional pitches to the nearest MIDI note for ordinary playback, while embedding exact pitch, frequency, event identity, and Reawarp metadata in text meta events for a Reawarp-to-Reawarp round trip. Linear tempo ramps are sampled into discrete MIDI tempo events. The score model remains the authoritative representation.

The score system does not yet make the existing offline renderer follow arbitrary tempo maps, time-signature changes, or automation. It establishes the data model and interchange layer; score-driven rendering and editing are future work.

## Determinism

The root seed is split into named NumPy random streams using a stable hash. Pattern, synthesis, profile-selection, and break-processing streams are independent. Regenerating one lane therefore does not change unrelated generated lanes. Repeated renders with the same application version, configuration, seed, and dependency environment produce identical floating-point stems.

## Audio model

- Internal format: NumPy float32, stereo.
- Default sample rate: 48 kHz.
- Duration: 5–180 seconds (up to three minutes).
- BPM: 60–220.
- Timing: event positions are derived from a sixteenth-note grid with controlled variation.
- Export: 16-bit or 24-bit PCM WAV.

The M4 PySide6 desktop instrument provides generation controls, break analysis, waveform/spectrogram preview, SoundDevice audition, stem mixing, and per-generator regeneration. The M9 interface uses the AVTranslator-inspired near-black monochrome theme; closing its window now performs a full application shutdown. The M5.1 sound pass adds controlled break grammar, transient-sliced break playback, profiled melody voices, and a dedicated ambience stem. M6 adds the searchable local sample/stem library, similarity descriptors, collections, and project-variation genealogy. Reawarp remains an offline mathematical sound laboratory, not a live event sequencer or full DAW.

## Desktop application (M4)

Install the UI and playback dependencies with `python -m pip install -e ".[m4]"` (or use the complete development command above). Launch with:

    reawarp-gui

or:

    python -m reawarp.ui

The main workspaces are Generator, Break Lab, Stem Mixer, FX Lab, and Library. The Generator exposes break style, density, phrase variation, cycle length, melody voice, and ambience controls. Rendering runs in a background worker; the audio callback only copies pre-rendered samples. Mixer faders affect audition and the exported master, while individual stem files remain unchanged. The Library provides local indexing, search, similarity, collections, and audition, with matching `reawarp-library` CLI commands. See [M4 design and implementation](docs/M4.md) and [M5.1 sound/rhythm refinement](docs/M5.1.md).

## Local sample and stem library (M6)

Create or update the default local library database:

    reawarp-library index samples/
    reawarp-library index output/

Index one exported project directly (including its stems, master, and referenced source samples):

    reawarp-library index output/my_idm_project/

Search by role, text, or tags:

    reawarp-library search --role kick
    reawarp-library search --query granular --type sample
    reawarp-library search --tag percussion --tag idm

Find sounds similar to an indexed asset (the command prints asset IDs for reuse):

    reawarp-library search --similar-to ASSET_ID --limit 12

Create a collection and add selected assets:

    reawarp-library collections create "Metallic Breaks" --description "Bright, inharmonic and percussive sources"
    reawarp-library collections add "Metallic Breaks" ASSET_ID_1 ASSET_ID_2
    reawarp-library collections show "Metallic Breaks"

Inspect generated variants from a project family using the `family_id` returned by project indexing:

    reawarp-library genealogy FAMILY_ID

The default SQLite database is stored at `~/.reawarp/library.sqlite3`; pass `--db path/to/library.sqlite3` before the subcommand to use another database. WAV indexing works with the core install. FLAC/AIFF/OGG support uses the optional `soundfile` package from the `audio` extra. Descriptors are calculated locally and source files are never modified.

## Development

    python -m pip install -e ".[dev]"
    python -m compileall -q src/reawarp
    reawarp --duration 5 --sample-rate 22050 --seed 211 --output /tmp/reawarp-smoke
    python -m pytest -q
    python scripts/benchmark_generation.py --durations 5 30 180 --palettes subtractive fm --output benchmark-m14.json

The repository now includes an initial M14 pytest regression suite for deterministic random streams, composition planning, signal diagnostics, stem regeneration, and dry FX/automation contracts. CI also runs a short benchmark fixture and an offscreen check of the grouped workspace shell. Additional transform-boundary, score round-trip, project portability, Windows and Pyo-enabled tests remain outstanding.

The four documents under `docs/guides/` remain the musical reference for all milestones. The [M10 FX Lab specification](docs/M10.md), IDM Field Guide, Advanced Composition Appendix, [M3 implementation note](docs/M3.md), [M4 desktop specification](docs/M4.md), [M5 score/MIDI specification](docs/M5.md), [M5.1 sound/rhythm refinement](docs/M5.1.md), [M6 library specification](docs/M6.md), and [dependency ecosystem review](docs/DEPENDENCY_ECOSYSTEM.md) provide the musical and technical reference.

## M7 — Composition Workbench (0.7.0)

M7 adds a deterministic formal section director above the existing mathematical event generators. Available structures are evolving, additive, subtractive, episodic, and drift. Section transitions are quantised to 4/4 bars where the requested duration permits; the final audio buffer still ends at the exact requested duration.

Use the same formal controls in the command line or the desktop Generator:

    reawarp --duration 45 --structure episodic --energy 0.72 --variation 0.8 --seed 211 --sample-rate 22050 --output output/m7-episodic

Composition energy is not master gain. Structural variation changes section allocation and bounded macro targets; it is not a global probability of extra hits. The local break grammar retains its separate phrase-variation control.

The Generator is divided into Form, Voices, and Rhythm sub-pages. Workspaces are grouped into Compose (Generator, Break Lab), Produce (Stem Mixer, FX Lab), and Assets (Library). A persistent project-context header and shared audition transport keep the in-memory composition connected across production workspaces; the Stem Mixer presents an explicit empty state until a project exists. The Library indexes, searches, and auditions local material. Mixer controls can regenerate procedural layers and imported sample overlays against a frozen project, preserving unrelated stems. The packaged application icon lives at `src/reawarp/resources/icons/Icon.ico`; closing the main window exits the application rather than hiding it in the tray.

See docs/M7.0.md, docs/M7.1.md, docs/M7.2.md, and docs/M7.3.md for implemented behaviour and remaining limitations.

- [IRO integration contract](docs/IRO_INTEGRATION.md) — shared sample identity, provenance and the phrase grammar bridge to the IRO project.
## Current roadmap

The current implementation baseline is **M13 with M14 in progress**. M14 has added initial regression coverage, signal diagnostics, render-phase timings, a benchmark harness and a grouped project-centred workspace shell. Its target-machine profiling and expanded validation are still pending. The next milestones deepen composition direction, score-driven rendering, synthesis automation, mixer quality and selected advanced DSP modules.

- [Technical and Musical Assessment](docs/TECHNICAL_AND_MUSICAL_ASSESSMENT.md) — source-level review, strengths, weaknesses, optimisation priorities and listening protocol.
- [Consolidated Roadmap](docs/ROADMAP.md) — implementation status and M14–M20 forward plan.
- [M14 Reliability and Performance Baseline](docs/M14.md) — current implementation, validation and remaining acceptance work.
- [Historical milestones](docs/) — M10–M13 and earlier specifications retained as the development record.
