"""Optional, independently scoped DSP research modules."""
from reawarp.dsp.convolution import (
    ConvolutionResult,
    ImpulseResponse,
    convolve_partitioned,
    design_resonant_ir,
    spectral_imprint,
)

__all__ = [
    "ConvolutionResult",
    "ImpulseResponse",
    "convolve_partitioned",
    "design_resonant_ir",
    "spectral_imprint",
]
