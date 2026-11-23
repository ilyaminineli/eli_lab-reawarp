# eli_lab-reawarp / 再変形

A deterministic mathematical audio laboratory for IDM percussion, synthetic breaks, eccentric melodic sequences, and stem generation.

Reawarp is an offline-first Python audio engine. Its synthesis core is independent of the desktop layer and optional third-party analysis or playback backends. It renders short loops, synchronized stems, and machine-readable event provenance.

## Current implementation

### Synthesis and composition
- Thirteen named kick profiles, six snare profiles, and six hi-hat profiles.
- Each percussion profile defines its own pitch/body oscillator, noise spectrum, envelope, and saturation characteristics.
- Deterministic per-hit automatic profile selection or a fixed profile selected from the CLI/API.
- Euclidean, modular-prime, Fibonacci-accent, and logistic-map rhythm material.
- Lissajous-derived melodic contours with FM synthesis.
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

The core requires Python 3.10+ and NumPy. SoundFile and SciPy are optional in the `audio` extra; native playback, analysis, and MIDI packages are separate extras.

## Install

Create a virtual environment, then run:

    python -m pip install --upgrade pip
    python -m pip install -e ".[dev,audio]"

For the minimal core:

    python -m pip install -e .

Optional integrations:

    python -m pip install -e ".[playback]"  # SoundDevice audition/recording
    python -m pip install -e ".[analysis]"  # librosa analysis adapters
    python -m pip install -e ".[midi]"      # Mido MIDI import/export
    python -m pip install -e ".[theory]"   # music21 symbolic music theory

Install extras only when the corresponding feature is needed. Csound, SuperCollider, and FluidSynth also require their native runtimes.

## Generate a loop

    reawarp --bpm 137 --duration 12 --seed 20261123 --complexity 0.68 --output output/demo

Use a fixed or automatically selected percussion profile:

    reawarp --kick-profile deep_sub --snare-profile industrial --hat-profile metallic

Process an imported break sample without modifying the original file:

    reawarp --break-sample samples/Breaks/my_break.wav --break-transforms slice_rearrange,stutter,dropout,reverse,gate --break-slice-count 16 --output output/processed

Pitch/time/granular operations accept their own controls:

    reawarp --break-sample samples/Breaks/my_break.wav --break-transforms pitch_shift,time_stretch,granular --break-pitch-semitones 5 --break-time-stretch 1.25 --break-grain-size-ms 75 --break-grain-density 1.6 --output output/warped

The output contains `master.wav`, a `stems/` directory, `project.json`, and `events.json`.

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

    # Regenerate only the kick; every unrelated stem remains identical.
    variation = engine.generate_variant(project.config, stem="kick", variation=2)
    variation.export("output/my_loop_kick_variation")

Supported custom sample roles: kick, snare, hat, and break. Break transformations are applied only to the imported break sample and run in memory. The original source file is read-only from Reawarp's perspective.

## Determinism

The root seed is split into named NumPy random streams using a stable hash. Pattern, synthesis, profile-selection, and break-processing streams are independent. Regenerating one lane therefore does not change unrelated generated lanes. Repeated renders with the same application version, configuration, seed, and dependency environment produce identical floating-point stems.

## Audio model

- Internal format: NumPy float32, stereo.
- Default sample rate: 48 kHz.
- Duration: 5–20 seconds.
- BPM: 60–220.
- Timing: event positions are derived from a sixteenth-note grid with controlled variation.
- Export: 16-bit or 24-bit PCM WAV.

The application remains an offline loop/stem generator, not a real-time instrument or full DAW. Playback, interactive PySide6 controls, MIDI export, searchable stem library, and variation genealogy are follow-on milestones.

## Development

    python -m pip install -e ".[dev]"
    pytest
    reawarp --duration 5 --sample-rate 22050 --seed 211 --output /tmp/reawarp-smoke

The IDM Field Guide, Advanced Composition Appendix, and M3 implementation note in `docs/` provide the musical and technical reference.
