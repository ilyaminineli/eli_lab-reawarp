# boundary_shard

A wavefolded carrier clipped at envelope boundaries, with short spectral splinters

Synthesis approach: wavefolding_and_harmonic_clipping

Equation: u=sum_j a_j*sin(j*phi); y=E*(2/pi)*asin(sin(gain*u+fold*c1))

Wavefolding, asymmetric drive and short boundary gates produce dense transient harmonics.

The six variations span different registers, durations, brightness and source-feature rows.
Every WAV is deterministic from its recorded seed and source features.

## Entities
- boundary_shard_01.wav — 1.317s; f0≈182.12 Hz; source row 130
- boundary_shard_02.wav — 1.458s; f0≈104.25 Hz; source row 147
- boundary_shard_03.wav — 1.547s; f0≈28.20 Hz; source row 164
- boundary_shard_04.wav — 1.744s; f0≈499.43 Hz; source row 181
- boundary_shard_05.wav — 1.732s; f0≈308.68 Hz; source row 198
- boundary_shard_06.wav — 1.692s; f0≈99.40 Hz; source row 215
