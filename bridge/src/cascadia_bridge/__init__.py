"""Bridge between Cascadia PLM's file vault and the AI Mechanical 3DCAD Design Agent."""

from .bridge import Binding, BridgeError, CheckinResult, CheckoutResult, checkin, checkout
from .client import CascadiaClient, CascadiaError, VaultFile, sha256_of

__all__ = [
    "Binding",
    "BridgeError",
    "CascadiaClient",
    "CascadiaError",
    "CheckinResult",
    "CheckoutResult",
    "VaultFile",
    "checkin",
    "checkout",
    "sha256_of",
]
