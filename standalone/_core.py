"""Import shim for the Home-Assistant-free SonoffLAN transport core.

``custom_components/sonoff/core`` is a PEP-420 namespace package (it has no
``__init__.py``), and ``custom_components/sonoff/core/ewelink`` is a regular
package whose modules import only stdlib + ``aiohttp`` / ``cryptography`` /
``zeroconf``. By putting the ``core`` directory on ``sys.path`` and importing
``ewelink`` as a *top-level* package, we get ``XRegistry`` and friends WITHOUT
executing ``custom_components/sonoff/__init__.py`` (which is HA-coupled).

The only Home Assistant imports reachable from the core are lazy
``from ..devices import ...`` calls inside two ``XRegistry`` methods; the
standalone registry overrides both so they never run (see
:mod:`standalone.registry`).
"""

import os
import sys

_CORE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "custom_components", "sonoff", "core"
    )
)

if not os.path.isdir(os.path.join(_CORE_DIR, "ewelink")):
    raise ImportError(
        f"SonoffLAN transport core not found at {_CORE_DIR!r}. "
        "Run sonoff-collector from a checkout of the SonoffLAN repository."
    )

if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

# ruff: noqa: E402  (imports must follow the sys.path tweak above)
from ewelink import XRegistry
from ewelink.base import SIGNAL_CONNECTED, SIGNAL_UPDATE, XDevice
from ewelink.cloud import REGIONS, AuthError

__all__ = [
    "XRegistry",
    "SIGNAL_CONNECTED",
    "SIGNAL_UPDATE",
    "XDevice",
    "REGIONS",
    "AuthError",
]
