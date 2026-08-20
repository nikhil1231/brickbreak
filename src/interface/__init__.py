"""`interface` — Interactive research dashboard and CLI (PLAN.md §6, §7).

Exports:
- `app`: Web dashboard application and REST API server
- `cli`: CLI command handlers for catalogue, hypotheses, ledger, explore, compare, serve
"""
from __future__ import annotations

from . import app, cli
from .app import serve_dashboard

__all__ = [
    "app",
    "cli",
    "serve_dashboard",
]
