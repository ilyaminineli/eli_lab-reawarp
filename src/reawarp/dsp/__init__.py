"""Optional, independently scoped DSP research modules."""
from reawarp.dsp.convolution import (
    ConvolutionResult, ImpulseResponse, convolve_partitioned, design_resonant_ir,
    spectral_imprint,
)
from reawarp.dsp.spectral_delay import SpectralDelayResult, spectral_delay
from reawarp.dsp.feedback_network import (
    FeedbackDelayNetwork, FeedbackNetworkCancelledError, FeedbackNetworkResult,
    feedback_delay_network,
)
from reawarp.dsp.cross_synthesis import (
    CrossSynthesisResult, frequency_shift, ring_modulate, spectral_envelope_transfer,
    vocoder,
)
from reawarp.dsp.nonlinear import NonlinearResult, oversampled_waveshaper

__all__ = [
    "ConvolutionResult", "ImpulseResponse", "convolve_partitioned",
    "design_resonant_ir", "spectral_imprint", "SpectralDelayResult",
    "spectral_delay", "FeedbackDelayNetwork", "FeedbackNetworkCancelledError",
    "FeedbackNetworkResult", "feedback_delay_network", "CrossSynthesisResult",
    "frequency_shift", "ring_modulate",
    "spectral_envelope_transfer", "vocoder", "NonlinearResult", "oversampled_waveshaper",
]
