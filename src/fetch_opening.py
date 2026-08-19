"""Fetch 09:15-09:20 one-second bars for screened candidates only.

This is the expensive leg, so it is built to be interrupted and resumed: Breeze
session tokens expire daily, and a large pull will not finish inside one token's
life. Every (symbol, date) that has been attempted is recorded in a manifest,
so re-running picks up exactly where it stopped.

Storage is one parquet per trading date containing every symbol fetched for that
date, which keeps file counts sane (a file-per-symbol-per-day layout would mean
tens of thousands of tiny files).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config, security_master, storage
from .breeze_client import BreezeClient, fmt_ts

OPENING_DIR = config.NORMALIZED_DIR / "opening_1s"
MANIFEST = config.METADATA_DIR / "opening_manifest.parquet"

WINDOW_START = (9, 15, 0)
WINDOW_END = (9, 20, 0)


def _date_path(d: pd.Timestamp) -> Path:
    return OPENING_DIR / f"{d.strftime('%Y-%m-%d')}.parquet"


def load_manifest() -> pd.DataFrame:
    if MANIFEST.exists():
        return pd.read_parquet(MANIFEST)
    return pd.DataFrame(columns=["symbol", "date", "isec_code", "n_rows", "status",
                                 "duration_s", "fetched_at"])


def save_manifest(df: pd.DataFrame) -> None:
    config.ensure_dirs()
    df.to_parquet(MANIFEST, index=False)


def resolve_codes(symbols: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map NSE symbols to Breeze ISEC short codes. Breeze rejects NSE symbols."""
    master = security_master.load()
    mapping, missing = {}, []
    for s in symbols:
        r = security_master.resolve(master, s)
        if r:
            mapping[s] = r.isec_code
        else:
            missing.append(s)
    return mapping, missing


def pending_pairs(candidates: pd.DataFrame, manifest: pd.DataFrame,
                  retry_errors: bool = True) -> pd.DataFrame:
    """Candidate (symbol, date) pairs still needing a fetch.

    "ok" and "empty" are settled outcomes — empty means the stock genuinely did
    not trade in the opening window, which re-requesting will not change.
    "error" rows (429s, transport failures) are transient and retried by
    default, otherwise a rate-limit blip permanently pokes holes in the dataset.
    """
    want = candidates[["symbol", "date"]].drop_duplicates().copy()
    want["date"] = pd.to_datetime(want["date"])
    if manifest.empty:
        return want
    settled = manifest[manifest["status"].isin(["ok", "empty"])] if retry_errors else manifest
    done = settled[["symbol", "date"]].copy()
    done["date"] = pd.to_datetime(done["date"])
    done["_d"] = 1
    merged = want.merge(done, on=["symbol", "date"], how="left")
    return merged[merged["_d"].isna()][["symbol", "date"]]


def _checkpoint(manifest_rows: list[dict]) -> None:
    """Fold accumulated rows into the on-disk manifest and clear the buffer."""
    if not manifest_rows:
        return
    man = pd.concat([load_manifest(), pd.DataFrame(manifest_rows)], ignore_index=True)
    man["date"] = pd.to_datetime(man["date"])
    man = man.drop_duplicates(subset=["symbol", "date"], keep="last")
    save_manifest(man)
    manifest_rows.clear()


def fetch_batch(
    pairs: pd.DataFrame,
    client: BreezeClient,
    workers: int = 1,
    max_calls: int | None = None,
    code_map: dict[str, str] | None = None,
    newest_first: bool = False,
    checkpoint_every: int = 500,
    verbose: bool = True,
) -> dict:
    """Fetch the opening window for each (symbol, date). Returns run stats.

    Results are flushed to disk per date as soon as that date completes, so an
    interrupted run keeps everything it already retrieved.
    """
    OPENING_DIR.mkdir(parents=True, exist_ok=True)
    pairs = pairs.sort_values(["date", "symbol"],
                              ascending=[not newest_first, True]).reset_index(drop=True)
    if max_calls:
        pairs = pairs.head(max_calls)

    symbols = sorted(pairs["symbol"].unique())
    # A precomputed map lets a remote runner skip downloading the scrip master.
    if code_map is not None:
        mapping = {s: code_map[s] for s in symbols if s in code_map}
        missing = [s for s in symbols if s not in code_map]
    else:
        mapping, missing = resolve_codes(symbols)
    if verbose:
        print(f"  {len(mapping):,} symbols mapped, {len(missing):,} unmapped "
              f"(skipped)", flush=True)

    pairs = pairs[pairs["symbol"].isin(mapping)].reset_index(drop=True)
    stats = {"attempted": 0, "with_data": 0, "empty": 0, "errors": 0,
             "rows": 0, "unmapped_symbols": len(missing),
             "started": datetime.now().isoformat()}
    manifest_rows: list[dict] = []
    lock = threading.Lock()
    t0 = time.perf_counter()

    def one(row) -> tuple[pd.Timestamp, str, pd.DataFrame | None, dict]:
        sym, d = row.symbol, row.date
        isec = mapping[sym]
        frm = fmt_ts(datetime(d.year, d.month, d.day, *WINDOW_START))
        to = fmt_ts(datetime(d.year, d.month, d.day, *WINDOW_END))
        r = client.second(isec, frm, to)
        rec = {"symbol": sym, "date": d, "isec_code": isec, "n_rows": r.n_rows,
               "status": "ok" if r.ok else ("empty" if not r.error else "error"),
               "duration_s": r.duration_s, "fetched_at": datetime.now().isoformat()}
        norm = storage.normalize(r.raw, isec, sym) if r.raw else None
        return d, sym, norm, rec

    by_date: dict[pd.Timestamp, list[pd.DataFrame]] = {}

    def flush(d: pd.Timestamp) -> None:
        frames = by_date.pop(d, None)
        if not frames:
            return
        out = pd.concat(frames, ignore_index=True)
        p = _date_path(d)
        if p.exists():
            out = pd.concat([pd.read_parquet(p), out], ignore_index=True)
            out = out.drop_duplicates(subset=["symbol", "timestamp"], keep="last")
        out.to_parquet(p, index=False)

    rows = list(pairs.itertuples(index=False))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, r): r for r in rows}
        seen_dates: dict[pd.Timestamp, int] = pairs.groupby("date").size().to_dict()
        done_per_date: dict[pd.Timestamp, int] = {}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                d, sym, norm, rec = fut.result()
            except Exception as exc:
                with lock:
                    stats["errors"] += 1
                continue
            with lock:
                stats["attempted"] += 1
                if rec["status"] == "ok":
                    stats["with_data"] += 1
                    stats["rows"] += rec["n_rows"]
                elif rec["status"] == "empty":
                    stats["empty"] += 1
                else:
                    stats["errors"] += 1
                manifest_rows.append(rec)
                if norm is not None and not norm.empty:
                    by_date.setdefault(d, []).append(norm)
                done_per_date[d] = done_per_date.get(d, 0) + 1
                if done_per_date[d] >= seen_dates.get(d, 0):
                    flush(d)
                if i % checkpoint_every == 0:
                    # Checkpoint so a killed run (or an expired token) resumes
                    # from here instead of re-requesting everything.
                    _checkpoint(manifest_rows)
                if verbose and i % 250 == 0:
                    el = time.perf_counter() - t0
                    print(f"  {i:,}/{len(rows):,} calls  {stats['with_data']:,} with data  "
                          f"{stats['empty']:,} empty  {stats['errors']:,} err  "
                          f"{stats['rows']:,} rows  {i/el:.1f} calls/s", flush=True)
    for d in list(by_date):
        flush(d)

    _checkpoint(manifest_rows)

    stats["elapsed_s"] = round(time.perf_counter() - t0, 1)
    stats["calls_per_s"] = round(stats["attempted"] / max(stats["elapsed_s"], 1e-9), 2)
    return stats


def load_opening(dates: list[str] | None = None) -> pd.DataFrame:
    files = sorted(OPENING_DIR.glob("*.parquet"))
    if dates:
        want = set(dates)
        files = [f for f in files if f.stem in want]
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


# --------------------------------------------------------------- data quality

def find_no_session_dates(manifest: pd.DataFrame, min_attempts: int = 3) -> list[str]:
    """Dates where every attempted symbol returned nothing for 09:15-09:20.

    NSE's Diwali Muhurat session is a ~1-hour *evening* session, so those dates
    have daily bhavcopy bars (and therefore produce screener candidates) but no
    opening window at all. Detected from the data rather than hardcoded, so any
    future special session is caught the same way.
    """
    if manifest.empty:
        return []
    g = manifest.groupby(manifest["date"].dt.date).agg(
        n=("status", "size"), ok=("status", lambda s: (s == "ok").sum()))
    dead = g[(g["n"] >= min_attempts) & (g["ok"] == 0)]
    return [str(d) for d in dead.index]


def flag_bad_volume(opening: pd.DataFrame) -> pd.DataFrame:
    """Symbol-days containing negative volume.

    Breeze reports negative volume on a handful of bars, and its 1-MINUTE bars
    carry the same negative values — so this is an archive-wide defect, not a
    1-second artifact, and it cannot be repaired by re-fetching. Volume cannot
    be negative, so these symbol-days are flagged for exclusion rather than
    clipped: clipping would yield a wrong-but-plausible opening volume, which is
    worse than a known hole.
    """
    if opening.empty:
        return pd.DataFrame(columns=["symbol", "day", "n_negative_bars", "min_volume"])
    bad = opening[opening["volume"] < 0]
    if bad.empty:
        return pd.DataFrame(columns=["symbol", "day", "n_negative_bars", "min_volume"])
    out = (bad.assign(day=bad["timestamp"].dt.date)
              .groupby(["symbol", "day"])
              .agg(n_negative_bars=("volume", "size"), min_volume=("volume", "min"))
              .reset_index())
    return out


def opening_features(opening: pd.DataFrame, exclude_bad: bool = True) -> pd.DataFrame:
    """Per symbol-day summary of the 09:15-09:20 window.

    This is the bridge from raw ticks to the entry rule: opening volume, the
    first candle's shape, and how far the low sat below the open. Nothing here
    decides anything — it just makes the rule's inputs available.
    """
    if opening.empty:
        return pd.DataFrame()
    d = opening.copy()
    d["day"] = d["timestamp"].dt.date
    d = d.sort_values(["symbol", "timestamp"])

    g = d.groupby(["symbol", "day"])
    out = g.agg(
        n_bars=("volume", "size"),
        first_ts=("timestamp", "min"),
        last_ts=("timestamp", "max"),
        open_px=("open", "first"),
        high_5m=("high", "max"),
        low_5m=("low", "min"),
        close_5m=("close", "last"),
        vol_5m=("volume", "sum"),
        n_zero_vol_bars=("volume", lambda s: int((s == 0).sum())),
        n_neg_vol_bars=("volume", lambda s: int((s < 0).sum())),
    ).reset_index()

    # First minute (09:15-09:15:59) — the "opening candle" the rule refers to.
    first_min = d[d["timestamp"].dt.time < pd.Timestamp("09:16").time()]
    if not first_min.empty:
        fm = first_min.groupby(["symbol", "day"]).agg(
            om_open=("open", "first"), om_high=("high", "max"),
            om_low=("low", "min"), om_close=("close", "last"),
            om_vol=("volume", "sum"), om_bars=("volume", "size")).reset_index()
        out = out.merge(fm, on=["symbol", "day"], how="left")
        out["om_low_vs_open_pct"] = (out["om_low"] / out["om_open"] - 1) * 100
        out["om_body_pct"] = ((out["om_close"] - out["om_open"]).abs()
                              / (out["om_high"] - out["om_low"]).replace(0, pd.NA) * 100)

    out["range_5m_pct"] = (out["high_5m"] - out["low_5m"]) / out["open_px"] * 100
    out["low_vs_open_pct"] = (out["low_5m"] / out["open_px"] - 1) * 100
    out["suspect_volume"] = out["n_neg_vol_bars"] > 0
    if exclude_bad:
        out = out[~out["suspect_volume"]]
    return out
