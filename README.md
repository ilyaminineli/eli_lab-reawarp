# eli_lab-reawarp / 再変形

A deterministic mathematical audio laboratory for IDM percussion, synthetic breaks, eccentric melodic sequences, and stem generation.

Reawarp is an offline-first Python audio engine. Its synthesis core is independent of the desktop layer and optional third-party analysis or playback backends. It renders short loops, synchronized stems, and machine-readable event provenance.

## Current implementation

### Synthesis and composition
- Thirteen named kick profiles, six snare profiles, and six hi-hat profiles, with mix-friendly weighted automatic choices.
- Five profiled additive/FM melody voices with evolving partials, soft detuning, envelopes, low-pass shaping, and release tails.
- A separate harmonic ambience stem with filtered noise, slow stereo movement, and restrained early reflections.
- A structured 16-step break grammar (broken funk, half-time, straight, sparse) with density, phrase-cycle, and bounded variation controls.
- Imported break recordings are transient-sliced and triggered on the groove grid; complete clips are no longer stacked at every trigger.
- Euclidean, modular-prime, Fibonacci-accent, and logistic-map rhythm material in the other percussion lanes.
- Lissajous-derived melodic contours with profiled synthesis.
- Independent random streams per generator and synthesis/profile lane.
- Stem-only regeneration while preserving unrelated stems bit-identically.

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

The core requires Python 3.10+ and NumPy. SoundFile and SciPy are optional in the audio extra; desktop and playback dependencies are grouped in the m4 extra; analysis, MIDI, symbolic theory, and SoundFont integrations remain separately installable.

## Install

Create a virtual environment, then run:

    python -m pip install --upgrade pip
    python -m pip install -e ".[dev,audio,m4,midi]"

For the minimal core:

    python -m pip install -e .

Optional analysis and music integrations:

    python -m pip install -e ".[analysis]"   # librosa analysis adapters
    python -m pip install -e ".[midi]"       # Mido MIDI import/export
    python -m pip install -e ".[theory]"     # music21 symbolic music theory
    python -m pip install -e ".[soundfont]"  # FluidSynth / SF2 source synthesis

Install extras only when the corresponding feature is needed. A full M4/M5 development environment can also include analysis and symbolic-theory tools:

    python -m pip install -e ".[dev,audio,m4,analysis,midi,theory,soundfont]"

If upgrading an environment that previously had PySide6 6.12.0, remove the two optional 6.12-only Qt extension wheels left behind by the downgrade before running pip check:

    python -m pip uninstall -y PySide6-Pdf PySide6-WebEngine
    python -m pip check

Csound, SuperCollider, and FluidSynth also require their native runtimes when those adapters are used.

## Generate a loop

    reawarp --bpm 137 --duration 12 --seed 20261123 --complexity 0.68 --output output/demo --midi-output output/demo.mid

Shape the break grammar and sound palette:

    reawarp --break-style broken_funk --break-density 0.50 --break-variation 0.25 --break-cycle-bars 2
    reawarp --melody-profile soft_keys --ambience-level 0.16

Use a fixed or automatically selected percussion profile:

    reawarp --kick-profile deep_sub --snare-profile acoustic --hat-profile dark

Process an imported break sample without modifying the original file:

    reawarp --break-sample samples/Breaks/my_break.wav --break-transforms slice_rearrange,stutter,dropout,reverse,gate --break-slice-count 16 --output output/processed

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
- Duration: 5–20 seconds.
- BPM: 60–220.
- Timing: event positions are derived from a sixteenth-note grid with controlled variation.
- Export: 16-bit or 24-bit PCM WAV.

The M4 PySide6 desktop instrument provides generation controls, break analysis, waveform/spectrogram preview, SoundDevice audition, stem mixing, and per-generator regeneration. The M5.1 sound pass adds controlled break grammar, transient-sliced break playback, profiled melody voices, and a dedicated ambience stem. It remains an offline loop/stem instrument, not a live event sequencer or full DAW. The next milestone is the searchable stem/sample library and variation genealogy.

## Desktop application (M4)

Install the UI and playback dependencies with `python -m pip install -e ".[m4]"` (or use the complete development command above). Launch with:

    reawarp-gui

or:

    python -m reawarp.ui

The main workspaces are Generator, Break Lab, and Stem Mixer. The Generator now exposes break style, density, phrase variation, cycle length, melody voice, and ambience controls. Rendering runs in a background worker; the audio callback only copies pre-rendered samples. Mixer faders affect audition and the exported master, while individual stem files remain unchanged. See [M4 design and implementation](docs/M4.md) and [M5.1 sound/rhythm refinement](docs/M5.1.md).

## Development

    python -m pip install -e ".[dev]"
    pytest
    reawarp --duration 5 --sample-rate 22050 --seed 211 --output /tmp/reawarp-smoke

The IDM Field Guide, Advanced Composition Appendix, [M3 implementation note](docs/M3.md), [M4 desktop specification](docs/M4.md), [M5 score/MIDI specification](docs/M5.md), [M5.1 sound/rhythm refinement](docs/M5.1.md), and [dependency ecosystem review](docs/DEPENDENCY_ECOSYSTEM.md) provide the musical and technical reference.
