"""Allow running Cernis with ``python -m cernis``."""

import sys

from cernis.cli import main

if __name__ == "__main__":
    sys.exit(main())
