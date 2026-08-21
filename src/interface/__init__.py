"""`interface` — Research backend, web application, and CLI (PLAN.md §6, §7).

Exports:
- `backend`: Primary web application and REST API server
- `cli`: CLI command handlers for catalogue, hypotheses, ledger, explore, compare, serve
"""
from __future__ import annotations

from . import backend, cli
from .backend import serve_backend

__all__ = [
    "backend",
    "cli",
    "serve_backend",
]
