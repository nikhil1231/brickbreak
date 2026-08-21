"""Parquet storage + normalization to a compact schema.

Layout:
  data/raw/         one parquet per API call, exactly as Breeze returned it
  data/normalized/  the compact schema below, partitioned by interval
  data/metadata/    call log, scrip master, validation summaries

Normalized schema:
  security_id (str)  ISEC stock_code used in the request
  symbol      (str)  NSE ticker symbol
  timestamp   (datetime64[ns], IST wall-clock, tz-naive)
  open/high/low/close (float64)
  volume      (int64)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...core import config

NORMALIZED_COLUMNS = [
    "security_id", "symbol", "timestamp", "open", "high", "low", "close", "volume",
]

# Breeze has used several spellings across endpoints/versions; map them all.
_TS_CANDIDATES = ("datetime", "date", "Datetime", "DateTime", "timestamp")
_NUM_ALIASES = {
    "open": ("open", "Open"),
    "high": ("high", "High"),
    "low": ("low", "Low"),
    "close": ("close", "Close"),
    "volume": ("volume", "Volume", "vol"),
}


def raw_path(call_id: str, interval: str, stock_code: str) -> Path:
    return config.RAW_DIR / f"{interval}__{stock_code}__{call_id}.parquet"


def save_raw(rows: list[dict], call_id: str, interval: str, stock_code: str) -> Path | None:
    if not rows:
        return None
    config.ensure_dirs()
    df = pd.DataFrame(rows).astype(str)  # keep verbatim; typing happens in normalize
    path = raw_path(call_id, interval, stock_code)
    df.to_parquet(path, index=False)
    return path


def _pick(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    return None


def normalize(rows: list[dict], security_id: str, symbol: str) -> pd.DataFrame:
    """Coerce a raw Breeze payload into NORMALIZED_COLUMNS.

    Timestamps are parsed as IST wall-clock and left tz-naive: Breeze labels
    them with a 'Z' suffix but the values are IST, so attaching UTC would
    silently shift every bar by 5h30m.
    """
    if not rows:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)
    df = pd.DataFrame(rows)

    ts_col = _pick(df, _TS_CANDIDATES)
    # Build on df's index so scalar columns broadcast instead of staying empty.
    out = pd.DataFrame(index=df.index)
    out["security_id"] = security_id
    out["symbol"] = symbol
    if ts_col is None:
        out["timestamp"] = pd.NaT
    else:
        ts = df[ts_col].astype(str).str.replace("Z$", "", regex=True)
        out["timestamp"] = pd.to_datetime(ts, errors="coerce", format="mixed").dt.tz_localize(None)

    for target, aliases in _NUM_ALIASES.items():
        col = _pick(df, aliases)
        out[target] = pd.to_numeric(df[col], errors="coerce") if col else pd.NA

    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(-1).astype("int64")
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
    return out[NORMALIZED_COLUMNS]


def save_normalized(df: pd.DataFrame, interval: str, name: str) -> Path | None:
    if df.empty:
        return None
    d = config.NORMALIZED_DIR / f"interval={interval}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def bytes_per_row(path: Path, n_rows: int) -> float | None:
    if not path or not path.exists() or n_rows <= 0:
        return None
    return round(path.stat().st_size / n_rows, 3)
