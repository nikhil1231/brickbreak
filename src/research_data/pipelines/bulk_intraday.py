"""Resumable Breeze ingestion for fixed intraday event windows.

This is a generic storage boundary: callers provide symbol/session pairs and
the pipeline fetches the fixed 15:15--15:17 one-minute window, preserving
successes, empty responses and errors in a manifest. Hypothesis selection
lives in the family module, not here.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from ...core import config
from ..sources import security_master
from ..sources.breeze import BreezeClient, fmt_ts
from . import renames, storage

DATA_DIR = config.NORMALIZED_DIR / "bulk_1515"
MANIFEST = config.METADATA_DIR / "bulk_1515_manifest.parquet"
DESIGN = config.METADATA_DIR / "h047_design.parquet"
NIFTY_DAILY = config.NORMALIZED_DIR / "bulk_1515_nifty_daily.parquet"
WINDOW_START = (15, 15, 0)
WINDOW_END = (15, 17, 0)


def load_manifest() -> pd.DataFrame:
    if MANIFEST.exists():
        return pd.read_parquet(MANIFEST)
    return pd.DataFrame(columns=[
        "symbol", "date", "request_code", "n_rows", "status",
        "duration_s", "error", "fetched_at",
    ])


def save_manifest(frame: pd.DataFrame) -> None:
    config.ensure_dirs()
    frame.to_parquet(MANIFEST, index=False)


def load_bars() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("part-*.parquet"))
    if not files:
        return pd.DataFrame(columns=storage.NORMALIZED_COLUMNS)
    out = pd.concat((pd.read_parquet(path) for path in files), ignore_index=True)
    return out.drop_duplicates(["symbol", "timestamp"], keep="last")


def save_design(frame: pd.DataFrame) -> None:
    config.ensure_dirs()
    frame.to_parquet(DESIGN, index=False)


def load_design() -> pd.DataFrame:
    if not DESIGN.exists():
        return pd.DataFrame()
    return pd.read_parquet(DESIGN)


def load_nifty_daily() -> pd.DataFrame:
    if not NIFTY_DAILY.exists():
        return pd.DataFrame(columns=storage.NORMALIZED_COLUMNS)
    return pd.read_parquet(NIFTY_DAILY)


def resolve_requests(pairs: pd.DataFrame,
                     master: pd.DataFrame | None = None,
                     rename_map: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Attach current Breeze codes without changing the experiment's symbol key."""
    want = pairs[["symbol", "date"]].drop_duplicates().copy()
    want["symbol"] = want["symbol"].astype(str).str.upper()
    want["date"] = pd.to_datetime(want["date"])

    man = load_manifest()
    if not man.empty:
        settled = man[man["status"].isin(["ok", "empty"])]
        want = want.merge(settled[["symbol", "date"]].drop_duplicates().assign(_done=True),
                          on=["symbol", "date"], how="left")
        want = want[want["_done"].isna()].drop(columns="_done")

    sm = security_master.load() if master is None else master
    if rename_map is None:
        try:
            rename_map = renames.load_map()
        except RuntimeError:
            rename_map = pd.DataFrame()
    cmap = renames.canonical_map(rename_map)

    codes: list[str | None] = []
    resolution_symbols: list[str] = []
    for symbol in want["symbol"]:
        if symbol == "__NIFTY__":
            codes.append("NIFTY")
            resolution_symbols.append(symbol)
            continue
        candidate = cmap.get(symbol, symbol)
        resolved = security_master.resolve(sm, candidate)
        if resolved is None and candidate != symbol:
            resolved = security_master.resolve(sm, symbol)
        codes.append(None if resolved is None else resolved.isec_code)
        resolution_symbols.append(candidate)

    want["resolution_symbol"] = resolution_symbols
    want["request_code"] = codes
    mapped = want.dropna(subset=["request_code"]).reset_index(drop=True)
    report = {
        "requested_pairs": int(len(pairs[["symbol", "date"]].drop_duplicates())),
        "already_settled": int(len(pairs[["symbol", "date"]].drop_duplicates()) - len(want)),
        "pending_pairs": int(len(want)),
        "mapped_pairs": int(len(mapped)),
        "unmapped_pairs": int(want["request_code"].isna().sum()),
        "mapped_symbols": int(mapped["symbol"].nunique()),
        "unmapped_symbols": sorted(want.loc[want["request_code"].isna(),
                                          "symbol"].unique().tolist()),
    }
    return mapped, report


def fetch_batch(pairs: pd.DataFrame, client: BreezeClient, *, workers: int = 4,
                max_calls: int | None = None, checkpoint_every: int = 250,
                verbose: bool = True) -> dict:
    """Fetch mapped requests and checkpoint every bounded batch."""
    required = {"symbol", "date", "request_code"}
    if missing := required - set(pairs.columns):
        raise ValueError(f"bulk intraday pairs need {sorted(missing)}")
    todo = pairs[list(required)].drop_duplicates(["symbol", "date"]).copy()
    todo["date"] = pd.to_datetime(todo["date"])
    todo = todo.sort_values(["date", "symbol"]).reset_index(drop=True)
    if max_calls is not None:
        todo = todo.head(max_calls)

    stats = {"attempted": 0, "with_data": 0, "empty": 0, "errors": 0,
             "rows": 0, "started": datetime.now().isoformat()}
    manifest_rows: list[dict] = []
    frames: list[pd.DataFrame] = []
    lock = threading.Lock()
    t0 = time.perf_counter()

    def flush() -> None:
        if frames:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            pd.concat(frames, ignore_index=True).to_parquet(
                DATA_DIR / f"part-{datetime.now().strftime('%Y%m%dT%H%M%S')}-"
                f"{uuid.uuid4().hex[:8]}.parquet", index=False)
            frames.clear()
        if manifest_rows:
            man = pd.concat([load_manifest(), pd.DataFrame(manifest_rows)],
                            ignore_index=True)
            man["date"] = pd.to_datetime(man["date"])
            man = man.drop_duplicates(["symbol", "date"], keep="last")
            save_manifest(man)
            manifest_rows.clear()

    def one(row) -> tuple[pd.DataFrame | None, dict]:
        d = row.date
        frm = fmt_ts(datetime(d.year, d.month, d.day, *WINDOW_START))
        to = fmt_ts(datetime(d.year, d.month, d.day, *WINDOW_END))
        result = client.minute(str(row.request_code), frm, to)
        rec = {
            "symbol": row.symbol, "date": d,
            "request_code": row.request_code, "n_rows": result.n_rows,
            "status": "ok" if result.ok else ("empty" if not result.error else "error"),
            "duration_s": result.duration_s, "error": result.error,
            "fetched_at": datetime.now().isoformat(),
        }
        norm = storage.normalize(result.raw, str(row.request_code), row.symbol) \
            if result.raw else None
        return norm, rec

    rows = list(todo.itertuples(index=False))
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(one, row) for row in rows]
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    norm, rec = future.result()
                except Exception as exc:  # preserve the rest of the batch
                    with lock:
                        stats["errors"] += 1
                    if verbose:
                        print(f"  worker error: {type(exc).__name__}: {exc}", flush=True)
                    continue
                with lock:
                    stats["attempted"] += 1
                    if rec["status"] == "ok":
                        stats["with_data"] += 1
                        stats["rows"] += rec["n_rows"]
                        if norm is not None:
                            frames.append(norm)
                    elif rec["status"] == "empty":
                        stats["empty"] += 1
                    else:
                        stats["errors"] += 1
                    manifest_rows.append(rec)
                    if i % checkpoint_every == 0:
                        flush()
                        if verbose:
                            print(f"  {i:,}/{len(rows):,}: ok={stats['with_data']:,} "
                                  f"empty={stats['empty']:,} errors={stats['errors']:,}",
                                  flush=True)
    finally:
        flush()
    stats["finished"] = datetime.now().isoformat()
    stats["elapsed_s"] = round(time.perf_counter() - t0, 1)
    return stats


def fetch_nifty_daily(client: BreezeClient, years: list[int]) -> dict:
    """Fetch NIFTY daily bars in sub-cap yearly calls for benchmark exits."""
    frames: list[pd.DataFrame] = []
    stats = {"attempted": 0, "with_data": 0, "errors": 0, "rows": 0}
    for year in sorted(set(years)):
        frm = fmt_ts(datetime(year, 1, 1, 0, 0))
        to = fmt_ts(datetime(year, 12, 31, 23, 59))
        result = client.daily("NIFTY", frm, to)
        stats["attempted"] += 1
        if result.raw:
            norm = storage.normalize(result.raw, "NIFTY", "__NIFTY__")
            frames.append(norm)
            stats["with_data"] += 1
            stats["rows"] += len(norm)
        else:
            stats["errors"] += 1
    if frames:
        out = pd.concat([load_nifty_daily(), *frames], ignore_index=True)
        out = out.drop_duplicates(["symbol", "timestamp"], keep="last")
        NIFTY_DAILY.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(NIFTY_DAILY, index=False)
    return stats


__all__ = [
    "DATA_DIR", "DESIGN", "MANIFEST", "NIFTY_DAILY", "fetch_batch",
    "fetch_nifty_daily", "load_bars", "load_design", "load_manifest",
    "load_nifty_daily", "resolve_requests", "save_design", "save_manifest",
]
