# quantization_residue

A phase-quantized waveform with bit depth and staircase size controlled by coordinates

Synthesis approach: nonlinear_quantization_error

Equation: Q(phi)=round(sin(phi)*N)/N; N=2^b; b=3+floor(5*coordinate); y=E*(Q(phi)-sin(phi))

The signal is the difference between a smooth phase carrier and its coordinate-controlled quantized version.

The six variations span different registers, durations, brightness and source-feature rows.
Every WAV is deterministic from its recorded seed and source features.

## Entities
- quantization_residue_01.wav — 1.068s; f0≈88.85 Hz; source row 99
- quantization_residue_02.wav — 1.271s; f0≈26.05 Hz; source row 116
- quantization_residue_03.wav — 1.611s; f0≈412.22 Hz; source row 133
- quantization_residue_04.wav — 1.744s; f0≈266.89 Hz; source row 150
- quantization_residue_05.wav — 1.822s; f0≈97.25 Hz; source row 167
- quantization_residue_06.wav — 2.011s; f0≈1072.65 Hz; source row 184
