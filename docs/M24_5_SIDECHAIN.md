# M24.5 — Sidechain and Envelope Routing

**Status:** Core implementation delivered; human listening and target-machine acceptance remain open  
**Routing schema:** v4 (v1–v3 migrate in memory)  
**Processing model:** Offline, deterministic, one-way detector-to-target gain control

## Musical use case

Let the actual transients of a kick, snare or break stem briefly make space in a sustained texture, ambience or melodic layer. The source may contain irregular timing and changing transient amplitude after break edits, regeneration or arrangement changes. A hand-authored automation curve can approximate a known passage, but it does not follow the actual rendered detector signal when those details change.

M24.5 therefore adds a narrowly scoped detector-to-gain relationship. It is not an arbitrary routing graph, a live compressor plug-in, or a new composition-generation control source.

## Route model

Each route declares:

- `route_id`, `source_stem` and a different `target_stem`.
- A linked-channel `peak` or `rms` detector.
- `threshold_db` in [-96, 0] dBFS and `ratio` in [1, 20].
- `max_reduction_db` in [0, 24] dB.
- `attack_ms` in [0.1, 500] ms and `release_ms` in [1, 5000] ms.
- `hysteresis_db` in [0, 24] dB.
- `control_rate_hz` in [50, 2000] Hz, never above the render sample rate.

The detector calculates a requested reduction from the signal level above threshold:

`reduction = min(max_reduction, max(0, detector_dB - threshold_dB) × (1 - 1 / ratio))`

The route smooths rising and falling reduction with separate attack/release time constants. Hysteresis uses a lower exit threshold to prevent threshold chatter. The control-rate points are interpolated to a sample-aligned gain envelope.

## Signal and safety contract

1. The detector reads the source's immutable dry stem **pre-insert and pre-fader**. Its linked-channel peak or RMS level is independent of fader gain and pan.
2. A source muted or excluded by solo does not trigger a sidechain. A muted/solo-excluded target is still handled by the normal mixer path.
3. The resulting gain envelope is applied to the target **before its insert and sends**, so both its direct path and downstream send taps follow the duck.
4. Source buffers, imported samples and stored dry stems are never modified.
5. Multiple routes targeting one stem combine by the strongest requested reduction (minimum linear gain), not by multiplying unrelated gain envelopes into unexpectedly deep attenuation.
6. Routes are bounded to 32 per routing document, each with a unique ID and distinct source/target. Invalid stems, values, sample-rate relationships and unknown fields fail validation.
7. Processing runs in the offline FX render pass. No detector, file access or DSP has been added to the audio callback. Cancellation is checked during envelope generation.
8. Schema v1, v2 and v3 routing documents remain loadable and are normalised to v4 with an empty `sidechains` list when no routes were authored.

## Example

Add this object to an FX routing document's top-level `sidechains` array:

```json
{
  "route_id": "kick_to_texture",
  "source_stem": "kick",
  "target_stem": "noise_texture",
  "detector_mode": "peak",
  "threshold_db": -24.0,
  "ratio": 12.0,
  "max_reduction_db": 9.0,
  "attack_ms": 2.0,
  "release_ms": 120.0,
  "hysteresis_db": 1.5,
  "control_rate_hz": 1000.0
}
```

The FX Routing editor exposes route selection, source/target, detector mode, threshold, ratio, reduction ceiling, attack, release and hysteresis. Use **ADD / UPDATE ROUTE** to save the selected relationship and **REMOVE ROUTE** to delete it. The route is included in the normal routing JSON save/load path and in render metadata.

## Automated acceptance coverage

`tests/test_m24_5_sidechain.py` verifies:

- Route identity, bounds, source/target separation and invalid-reference rejection.
- v3-to-v4 migration and preservation of authored sidechain settings.
- Deterministic peak detection, bounded gain reduction, attack/release behaviour and source immutability.
- RMS detector operation and silent-source no-trigger behaviour.
- Application before the target insert/send path, plus mute/solo gating.
- FX Routing editor add/remove interactions.

The renderer also records the route configuration, per-route maximum/mean reduction, active fraction, detector peak and the actual control rate in metadata.

## Acceptance still open

Automated tests prove routing semantics and deterministic signal behaviour, not artistic benefit. Listen to real kick/break-to-texture examples at matched loudness, including mono and low-volume playback. Confirm the chosen threshold, attack/release and maximum reduction are musically appropriate, and run the target-Windows 30/180-second performance benchmark before treating M24.5 as fully signed off.
