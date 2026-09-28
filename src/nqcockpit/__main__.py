"""Executable entrypoint for python -m nqcockpit."""

from __future__ import annotations

import sys

from nqcockpit.cli import main

if __name__ == "__main__":
    sys.exit(main())
