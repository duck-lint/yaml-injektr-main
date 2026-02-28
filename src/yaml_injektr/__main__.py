"""Module entrypoint for ``python -m yaml_injektr``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
