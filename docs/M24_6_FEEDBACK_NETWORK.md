# M24.6 — Bounded Feedback Delay Network

**Status:** Core NumPy implementation delivered; human listening and target-machine acceptance remain open  
**Processor:** Fixed four-line orthogonal feedback-delay network (FDN)  
**Integration:** Standalone offline DSP module; no automatic M22 insert or general routing graph

## Musical use case

Build a short resonant, interwoven tail from machine pulses, metallic transients, clipped percussion or inharmonic sound objects. The tail should evolve through several unequal delay paths rather than repeat as one obvious echo or split into static frequency bands.

M24.2 already provides frequency-region spectral delay with independent band delays. M24.6 addresses a different question: what happens when four time-domain delay paths repeatedly exchange energy through a fixed orthogonal mixing matrix? This creates cross-coupled, evolving echoes while retaining a small, understandable system.

## Fixed topology and stability

The processor contains exactly four delay lines with a normalized 4×4 Hadamard feedback matrix:

`M = (1/2) [[1,1,1,1], [1,-1,1,-1], [1,1,-1,-1], [1,-1,-1,1]]`

`M` is orthogonal, so its induced 2-norm is 1. The feedback operator is `gM`, where `0 ≤ g ≤ 0.98`. Its norm is therefore at most 0.98, strictly below unity, with a minimum stability margin of 0.02. No arbitrary matrix, dynamic topology, feedback graph or hidden gain compensation is accepted.

Four unequal delay times are authored in milliseconds and resolved to distinct integer sample delays. The initial implementation bounds each time to 5–2000 ms and uses a fixed mono/stereo injection and decoding transform.

## Controls

- `delay_times_ms`: exactly four distinct delays.
- `feedback_gain`: [0, 0.98]; the contraction factor for every network traversal.
- `input_gain`: [0, 1]; excitation level sent into the delay network.
- `dry`, `wet`: [0, 1] linear mix amounts.
- `max_tail_seconds`: [0, 30] hard duration cap.
- `tail_threshold_db`: [40, 120] conservative decay estimate.
- `output_ceiling`: [0.1, 1] static whole-render peak guard.

The tail estimator uses the longest delay and the number of feedback traversals required to fall below the requested decay threshold. The result is always clipped to the hard maximum duration. A truncated tail is reported; it is never silently described as fully decayed.

The processor records the topology ID, sample delay values, feedback norm bound, stability margin, tail estimate/cap, pre-guard peak, final guard gain, output peak, working-memory estimate and render time.

## Signal, state and safety contract

1. **Fixed topology:** exactly four delay lines and one normalized orthogonal feedback matrix. No user-defined graph or recursive stage chain is allowed.
2. **Stable feedback:** feedback gain cannot reach unity. Since the matrix norm is 1, the loop operator norm is bounded by the scalar gain.
3. **Finite output:** a conservative decay estimate is capped by `max_tail_seconds`; output frame count is input length plus the selected tail.
4. **Headroom:** the one-shot offline render applies a deterministic static peak guard to the entire render and reports the amount of attenuation. It does not claim to be a transparent look-ahead limiter.
5. **Reset:** each one-shot call starts with zero delay memory. The streaming `FeedbackDelayNetwork.reset()` clears all four lines and returns the instance to a ready state.
6. **Panic/stop:** `panic()` clears the state immediately and refuses further processing until `start()` or `reset()`.
7. **Cancellation:** offline streaming checks cancellation at block boundaries, clears state and raises `FeedbackNetworkCancelledError`.
8. **Bounded memory:** only the recent delay history is retained in the ring buffers; memory does not grow with the input duration. The output array is necessarily proportional to rendered duration.
9. **Non-destructive:** source arrays are read-only inputs; the processor never modifies them.
10. **Offline only:** no work is added to the audio callback or real-time playback path. The processor is opt-in and is not added to role-aware defaults.

## API

`reawarp.dsp.feedback_delay_network(audio, sample_rate, ...)` returns a `FeedbackNetworkResult` with audio and diagnostics.

`FeedbackDelayNetwork` also exposes stateful `process()`, bounded `flush()`, `reset()`, `panic()` and `start()` methods for block-oriented offline use. The stateful block interface returns raw streaming output; the one-shot helper is the path that applies the complete-render peak guard.

## Reproducible evaluation

- `tests/test_m24_6_feedback_network.py` covers orthogonality/stability, bounded tails, peak guard, source immutability, deterministic rerenders, mono/stereo shape, streaming block invariance, reset/panic, cancellation and invalid settings.
- `scripts/benchmark_m24_6_feedback_network.py` reports platform, NumPy/Python, wall time, real-time factor, traced allocation and processor diagnostics.
- `scripts/render_m24_6_listening_example.py` writes dry, level-matched and unmatched WAVs plus listening questions.

Run the benchmark and listening render:

```powershell
python scripts/benchmark_m24_6_feedback_network.py --duration 5 --sample-rate 48000 --output output/m24-6-benchmark.json
python scripts/render_m24_6_listening_example.py --output output/m24-6-listening
```

## Acceptance still open

Automated tests establish deterministic operation and the stated mathematical bounds, not whether the resulting tail is musically desirable. Listen to the matched-level set in stereo, mono and at low monitoring level. Confirm whether the cross-coupled tail contributes something distinct from M24.2 on real material, and run the 30/180-second 48 kHz benchmark on the target Windows machine before treating M24.6 as fully signed off.

No M24.6 processor is automatically inserted into existing projects. Existing FX routing and project schemas remain unchanged.
