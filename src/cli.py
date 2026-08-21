"""Stable command-line entry point for brickbreak."""
from __future__ import annotations

from .interface.cli.main import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
