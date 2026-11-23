# eli_lab-reawarp / 再変形

A deterministic mathematical audio laboratory for IDM percussion, synthetic breaks, eccentric melodic sequences, and stem generation.

Reawarp is an offline-first Python audio engine. Its first implementation focuses on a reproducible synthesis core rather than a DAW-style interface. It generates short loops using synthesized kick, snare, metallic hats, synthetic break fragments, geometric/FM melody, and evolving noise texture. Imported WAV samples can be layered onto generated event patterns.

## Current implementation

- Procedural kick synthesis with decaying pitch sweep, sub body, transient noise, and waveshaping.
- Procedural snare and metallic/noise hi-hat synthesis.
- Euclidean, modular-prime, and logistic-map rhythm material.
- Lissajous-derived melodic contours rendered with FM-style synthesis.
- Independent deterministic random streams per generator/stem.
- Stem-only regeneration while preserving unrelated stems bit-identically.
- Optional custom WAV samples for kick, snare, hat, and break lanes.
- Offline stereo rendering and synchronized individual WAV stems.
- JSON project metadata and event provenance.
- 16-bit and 24-bit PCM WAV export.

The core requires Python 3.10+ and NumPy. SoundFile is optional for reading additional sample formats; standard PCM WAV input is supported without it.

## Install

Create a virtual environment, then run:

    python -m pip install --upgrade pip
    python -m pip install -e ".[dev,audio]"

For a minimal installation:

    python -m pip install -e .

## Generate a loop

    reawarp --bpm 137 --duration 12 --seed 20261123 --complexity 0.68 --output output/demo

Or run without installing the console command:

    python -m reawarp.cli --bpm 137 --duration 12 --seed 20261123 --output output/demo

The output contains master.wav, a stems directory, project.json, and events.json.

## Python API

    from reawarp import GenerationConfig, ReawarpEngine

    engine = ReawarpEngine()
    project = engine.generate(
        GenerationConfig(
            bpm=137,
            duration=12.0,
            seed=20261123,
            complexity=0.68,
            sample_paths={"snare": "samples/my_snare.wav"},
        )
    )
    project.export("output/my_loop", bit_depth=24)

    # Regenerate only the kick; every unrelated stem remains identical.
    variation = engine.generate_variant(project.config, stem="kick", variation=2)
    variation.export("output/my_loop_kick_variation")

Supported custom sample roles: kick, snare, hat, and break. A custom sample is layered as its own stem and triggered by the corresponding generated lane. The original procedural lane remains available.

## Determinism

The root seed is split into named NumPy random streams using a stable hash. Regenerating one lane therefore does not change unrelated lanes. Repeated renders with the same application version, configuration, seed, and dependency environment produce identical floating-point stems.

## Audio model

- Internal format: NumPy float32, stereo.
- Default sample rate: 48 kHz.
- Duration: 5–20 seconds.
- BPM: 60–220.
- Timing: event positions are derived from a sixteenth-note grid with controlled variation.
- Export: 16-bit or 24-bit PCM WAV.

The first version is a loop/stem generator, not a real-time instrument or full DAW. Playback, interactive PySide6 controls, a visual geometry lab, MIDI export, stem library, and variation genealogy are future milestones.

## Development

    python -m pip install -e ".[dev]"
    pytest

The existing IDM field guide and advanced composition appendix in docs remain the musical/theoretical reference. The implementation architecture is summarized in docs/IMPLEMENTATION_NOTES.md.
