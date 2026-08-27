"""Bridge between Cascadia PLM's file vault and the AI Mechanical 3DCAD Design Agent."""

from .bridge import Binding, BridgeError, CheckinResult, CheckoutResult, checkin, checkout
from .client import CascadiaClient, CascadiaError, VaultFile, sha256_of
from .fcstd_scan import FileVerdict, ScanReport, scan
from .preflight import ContractDiff, FreeCADCheck, diff_surface, tool_surface, verify_freecad

__all__ = [
    "Binding",
    "BridgeError",
    "CascadiaClient",
    "CascadiaError",
    "CheckinResult",
    "CheckoutResult",
    "ContractDiff",
    "FileVerdict",
    "FreeCADCheck",
    "ScanReport",
    "VaultFile",
    "checkin",
    "checkout",
    "diff_surface",
    "scan",
    "sha256_of",
    "tool_surface",
    "verify_freecad",
]
