"""Typed access to canonical on-disk research artifacts.

This module is the low-level storage boundary beneath :mod:`research_data.frame`.
It intentionally exposes named datasets rather than a generic path reader, so
callers cannot silently invent a second market-data access path.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from ..core import config

DAILY_BARS_ADJ = config.NORMALIZED_DIR / "daily_bars_adj.parquet"
DAILY_BARS_RAW = config.NORMALIZED_DIR / "daily_bars.parquet"
SCREEN_METRICS = config.NORMALIZED_DIR / "screen_metrics.parquet"
SCREEN_METRICS_ASOF = config.NORMALIZED_DIR / "screen_metrics_asof.parquet"
SYMBOL_METADATA = config.METADATA_DIR / "symbol_metadata.parquet"
OPENING_MANIFEST = config.METADATA_DIR / "opening_manifest.parquet"
OPENING_FEATURES = config.NORMALIZED_DIR / "opening_features.parquet"
CANDIDATE_PANEL = config.NORMALIZED_DIR / "candidate_panel.parquet"
CANDIDATE_LABELS = config.NORMALIZED_DIR / "candidate_labels.parquet"
OPENING_BEHAVIOUR = config.NORMALIZED_DIR / "opening_behaviour.parquet"
ENTRY_WINDOW_GRID = config.NORMALIZED_DIR / "entry_window_grid.parquet"
RENAME_MAP = config.METADATA_DIR / "rename_map.parquet"
CA_RECONCILIATION = config.METADATA_DIR / "ca_reconciliation.parquet"


def daily_bars(
    *, adjusted: bool = True, columns: list[str] | None = None
) -> pd.DataFrame:
    """Load canonical adjusted or raw daily bars."""
    path = DAILY_BARS_ADJ if adjusted else DAILY_BARS_RAW
    return pd.read_parquet(path, columns=columns)


def screen_metrics(
    *, asof_open: bool = True, columns: list[str] | None = None
) -> pd.DataFrame:
    """Load the lagged morning panel or its explicitly unlagged counterpart."""
    path = SCREEN_METRICS_ASOF if asof_open else SCREEN_METRICS
    return pd.read_parquet(path, columns=columns)


def symbol_metadata(*, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(SYMBOL_METADATA, columns=columns)


def opening_manifest(path: Path | str | None = None) -> pd.DataFrame:
    """Load the opening-fetch manifest, optionally from an explicit export."""
    return pd.read_parquet(Path(path) if path is not None else OPENING_MANIFEST)


def opening_features(path: Path | str | None = None) -> pd.DataFrame:
    """Load the canonical opening-feature panel or an explicit equivalent."""
    return pd.read_parquet(Path(path) if path is not None else OPENING_FEATURES)


def opening_ticks(files: Iterable[Path]) -> pd.DataFrame:
    """Load and concatenate explicitly selected opening-session partitions."""
    paths = list(files)
    if not paths:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


def candidate_panel() -> pd.DataFrame:
    return pd.read_parquet(CANDIDATE_PANEL)


def candidate_labels() -> pd.DataFrame:
    return pd.read_parquet(CANDIDATE_LABELS)


def behaviour_panel() -> pd.DataFrame:
    return pd.read_parquet(OPENING_BEHAVIOUR)


def entry_window_grid() -> pd.DataFrame:
    return pd.read_parquet(ENTRY_WINDOW_GRID)


def rename_map() -> pd.DataFrame:
    return pd.read_parquet(RENAME_MAP)


def corporate_action_reconciliation() -> pd.DataFrame:
    return pd.read_parquet(CA_RECONCILIATION)


__all__ = [
    "behaviour_panel",
    "candidate_labels",
    "candidate_panel",
    "corporate_action_reconciliation",
    "daily_bars",
    "entry_window_grid",
    "opening_features",
    "opening_manifest",
    "opening_ticks",
    "rename_map",
    "screen_metrics",
    "symbol_metadata",
]
