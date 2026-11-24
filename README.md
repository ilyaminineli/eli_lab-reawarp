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

### Offline sound design (M10)
- A separate FX Lab loads external mono/stereo audio without changing the source file.
- Optional Pyo offline processing with ordered high/low/band-pass filtering, saturation, delay, frequency shift, and Freeverb stages.
- Four role-oriented chains: restrained space, tape echo, metallic machine, and digital fracture.
- Global wet/dry blend, explicit tail allowance, dry/processed waveform and spectrogram comparison, audition, and 24-bit WAV export.
- The same processing engine is available through the `reawarp-fx` command; Pyo is not required by the base generator.

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

Choose a lead synthesis architecture with `--synth-palette`: `subtractive` (default), `hybrid`, `fm`, `additive`, `modal`, `inharmonic`, `granular`, or `physical`. `subtractive` is a separate renderer, not another FM preset. Choose drum construction separately with `--percussion-synthesis minimal|extended|samples`; `minimal` (default) uses sparse, dry transient/body/tail kick/snare/hat voices, while `samples` selects the legacy profiled drum renderers. The M10 FX Lab adds a separate non-destructive Pyo processing path; the core generator and NumPy reference renderer remain independent. Convolution, spectral delay, feedback-delay networks, cross-synthesis, oversampling and per-stem inserts remain later DSP modules.

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

The FX LAB workspace loads a mono/stereo audio file, lets you select a processing chain and wet/dry balance, renders a separate result, and allows dry/processed audition and export. The original is untouched. CLI usage:

    reawarp-fx input.wav output_fx.wav --preset tape_echo --wet 0.70 --tail 2.0
    reawarp-fx --list-presets

Available chains: `restrained_space`, `tape_echo`, `metallic_machine`, and `digital_fracture`. Pyo uses its offline server; it does not open the audio device to process the file. See [M10 FX Lab](docs/M10.md).

Pitch/time/granular operations accept their own controls:

    reawarp --break-sample samples/Breaks/my_break.wav --break-transforms pitch_shift,time_stretch,granular --break-pitch-semitones 5 --break-time-stretch 1.25 --break-grain-size-ms 75 --break-grain-density 1.6 --output output/warped

The output contains master.wav, a stems/ directory, project.json, events.json, and the synthesizer-independent score.json.

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
- Duration: 5–45 seconds.
- BPM: 60–220.
- Timing: event positions are derived from a sixteenth-note grid with controlled variation.
- Export: 16-bit or 24-bit PCM WAV.

The M4 PySide6 desktop instrument provides generation controls, break analysis, waveform/spectrogram preview, SoundDevice audition, stem mixing, and per-generator regeneration. The M9 interface uses the AVTranslator-inspired near-black monochrome theme; closing its window now performs a full application shutdown. The M5.1 sound pass adds controlled break grammar, transient-sliced break playback, profiled melody voices, and a dedicated ambience stem. M6 adds the searchable local sample/stem library, similarity descriptors, collections, and project-variation genealogy. Reawarp remains an offline mathematical sound laboratory, not a live event sequencer or full DAW.

## Desktop application (M4)

Install the UI and playback dependencies with `python -m pip install -e ".[m4]"` (or use the complete development command above). Launch with:

    reawarp-gui

or:

    python -m reawarp.ui

The main workspaces are Generator, Break Lab, Stem Mixer, FX Lab, and Library. The Generator now exposes break style, density, phrase variation, cycle length, melody voice, and ambience controls. Rendering runs in a background worker; the audio callback only copies pre-rendered samples. Mixer faders affect audition and the exported master, while individual stem files remain unchanged. See [M4 design and implementation](docs/M4.md) and [M5.1 sound/rhythm refinement](docs/M5.1.md). The M6 library is currently exposed through the Python API and `reawarp-library` CLI.

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

The repository currently uses compile and command-line smoke checks; no unit-test suite is included.

The four documents under `docs/guides/` remain the musical reference for all milestones. The [M10 FX Lab specification](docs/M10.md), IDM Field Guide, Advanced Composition Appendix, [M3 implementation note](docs/M3.md), [M4 desktop specification](docs/M4.md), [M5 score/MIDI specification](docs/M5.md), [M5.1 sound/rhythm refinement](docs/M5.1.md), [M6 library specification](docs/M6.md), and [dependency ecosystem review](docs/DEPENDENCY_ECOSYSTEM.md) provide the musical and technical reference.

## M7 — Composition Workbench (0.7.0)

M7 adds a deterministic formal section director above the existing mathematical event generators. Available structures are evolving, additive, subtractive, episodic, and drift. Section transitions are quantised to 4/4 bars where the requested duration permits; the final audio buffer still ends at the exact requested duration.

Use the same formal controls in the command line or the desktop Generator:

    reawarp --duration 45 --structure episodic --energy 0.72 --variation 0.8 --seed 211 --sample-rate 22050 --output output/m7-episodic

Composition energy is not master gain. Structural variation changes section allocation and bounded macro targets; it is not a global probability of extra hits. The local break grammar retains its separate phrase-variation control.

The Generator is divided into Form, Voices, and Rhythm sub-pages. Main workspaces are Generator, Break Lab, Stem Mixer, FX Lab, and Library. The Library indexes, searches, and auditions local material. Mixer controls can regenerate procedural layers and imported sample overlays against a frozen project, preserving unrelated stems. The shared ELI LAB icon is packaged for the application window and system tray.

See docs/M7.0.md, docs/M7.1.md, docs/M7.2.md, and docs/M7.3.md for implemented behaviour and remaining limitations.