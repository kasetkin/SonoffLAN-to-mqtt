"""Single import boundary to the vendored SonoffLAN transport core.

The Home-Assistant-free ``ewelink`` package (``XRegistry`` plus the cloud/local
transports) is vendored into this package at ``standalone/ewelink/`` — see
``standalone/ewelink/VENDORED.md``. This module re-exports only the symbols the
rest of ``standalone`` actually uses, so there's one place that knows where the
core lives.
"""

from .ewelink import XRegistry
from .ewelink.cloud import REGIONS, AuthError

__all__ = ["XRegistry", "REGIONS", "AuthError"]
