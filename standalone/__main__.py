"""Allow ``python -m standalone`` as a fallback to the ``sonoff-collector`` command."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
