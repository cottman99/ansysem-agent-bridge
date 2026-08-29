"""Public package surface for AnsysEM Agent Bridge."""

from .models import CapabilityDescriptor, CapabilityState, Installation, TargetIdentity

__all__ = [
    "CapabilityDescriptor",
    "CapabilityState",
    "Installation",
    "TargetIdentity",
]

__version__ = "0.2.0a5"
