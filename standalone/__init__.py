"""Stand-alone, local-only collector for Sonoff/eWeLink LAN devices.

Reuses the Home-Assistant-free transport core that ships inside
``custom_components/sonoff/core`` (see :mod:`standalone._core`). The eWeLink
cloud is contacted only during interactive ``login``; the ``run`` service is
purely local.
"""

__version__ = "0.1.0"
