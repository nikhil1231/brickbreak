"""The feasibility test matrix: probe Breeze empirically and record everything.

Each probe answers a specific question from the spike brief. Nothing here
assumes the documentation is right; where a limit is claimed, we push until the
API actually pushes back.
"""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from ...core import config
from ..pipelines import storage
from ..pipelines.validation import check
from ..sources import security_master
from ..sources.breeze import BreezeClient, fmt_ts
from .universe import TEST_UNIVERSE, TestSecurity

# Years to walk back through when establishing real historical depth.
DEPTH_YEARS = [2025, 2024, 2023, 2022, 2020, 2018, 2015, 2012, 2010, 2007, 2005, 2002, 2000]


def _day_window(d: date, start=(9, 15), end=(15, 30)) -> tuple[str, str]:
    return (
        fmt_ts(datetime(d.year, d.month, d.day, *start)),
        fmt_ts(datetime(d.year, d.month, d.day, *end)),
    )


def _persist(result, sec: TestSecurity, isec: str, tag: str) -> dict:
    """Store raw + normalized parquet and run quality checks on one call."""
    rec: dict[str, Any] = {
        "probe": tag,
        "symbol": sec.nse_symbol,
        "kind": sec.kind,
        "isec_code": isec,
        **{k: v for k, v in result.log_record().items()},
    }
    if result.raw:
        raw_p = storage.save_raw(result.raw, result.call_id, result.interval, isec)
        norm = storage.normalize(result.raw, isec, sec.nse_symbol)
        norm_p = storage.save_normalized(norm, result.interval, f"{isec}__{result.call_id}")
        rec["raw_path"] = str(raw_p.relative_to(config.PROJECT_ROOT)) if raw_p else None
        rec["raw_bytes_per_row"] = storage.bytes_per_row(raw_p, result.n_rows) if raw_p else None
        rec["normalized_bytes_per_row"] = storage.bytes_per_row(norm_p, result.n_rows) if norm_p else None
        rec["checks"] = check(norm, result.interval, sorted(result.raw[0].keys()))
    return rec


def find_trading_days(client: BreezeClient, isec: str, year: int, month: int,
                      limit: int = 3) -> list[date]:
    """Ask the API which days actually traded, rather than guessing a calendar."""
    last = monthrange(year, month)[1]
    r = client.daily(isec, fmt_ts(datetime(year, month, 1, 9, 0)),
                     fmt_ts(datetime(year, month, last, 16, 0)))
    if not r.raw:
        return []
    df = storage.normalize(r.raw, isec, isec)
    days = sorted({t.date() for t in df["timestamp"].dropna()})
    return days[:limit]


# ------------------------------------------------------------------ probes

def probe_connectivity(client: BreezeClient) -> dict:
    """Does auth work at all, and what does the customer-details call return?"""
    try:
        cust = client.authenticate()
        keys = sorted(cust.keys()) if isinstance(cust, dict) else None
        status = cust.get("Status") if isinstance(cust, dict) else None
        err = cust.get("Error") if isinstance(cust, dict) else None
        return {"authenticated": err is None, "status": status, "error": err,
                "response_keys": keys}
    except Exception as exc:
        return {"authenticated": False, "error": f"{type(exc).__name__}: {exc}"}


def probe_code_form(client: BreezeClient, df_master: pd.DataFrame) -> list[dict]:
    """Must stock_code be the ISEC short code, or is the NSE symbol accepted?"""
    out = []
    sec = TEST_UNIVERSE[0]
    isec = security_master.resolve(df_master, sec.nse_symbol).isec_code
    frm, to = fmt_ts(datetime(2026, 6, 1, 9, 0)), fmt_ts(datetime(2026, 6, 30, 16, 0))
    for label, code in (("isec_short_code", isec), ("nse_symbol", sec.nse_symbol)):
        r = client.daily(code, frm, to)
        out.append({"probe": "code_form", "variant": label, "code_used": code,
                    "ok": r.ok, "n_rows": r.n_rows, "error": r.error,
                    "duration_s": r.duration_s})
    return out


def probe_endpoint_parity(client: BreezeClient, isec: str, sec: TestSecurity) -> list[dict]:
    """v1 vs v2 for the same daily window: same rows? same fields?"""
    frm, to = fmt_ts(datetime(2026, 6, 1, 9, 0)), fmt_ts(datetime(2026, 6, 30, 16, 0))
    out = []
    for ep in ("v1", "v2"):
        r = client.daily(isec, frm, to, endpoint=ep)
        rec = _persist(r, sec, isec, f"endpoint_parity_{ep}")
        rec["fields"] = sorted(r.raw[0].keys()) if r.raw else []
        out.append(rec)
    return out


def probe_daily_recent(client: BreezeClient, isec: str, sec: TestSecurity) -> dict:
    """One year of daily bars: the preceding-candle dataset."""
    r = client.daily(isec, fmt_ts(datetime(2025, 8, 1, 9, 0)),
                     fmt_ts(datetime(2026, 8, 17, 16, 0)))
    return _persist(r, sec, isec, "daily_recent_1y")


def probe_daily_depth(client: BreezeClient, isec: str, sec: TestSecurity) -> list[dict]:
    """Walk back year by year until daily data stops coming, to find real depth."""
    out = []
    for yr in DEPTH_YEARS:
        r = client.daily(isec, fmt_ts(datetime(yr, 1, 1, 9, 0)),
                         fmt_ts(datetime(yr, 1, 31, 16, 0)))
        out.append({"probe": "daily_depth", "symbol": sec.nse_symbol, "kind": sec.kind,
                    "isec_code": isec, "year": yr, "ok": r.ok, "n_rows": r.n_rows,
                    "error": r.error, "duration_s": r.duration_s,
                    "first_ts": (storage.normalize(r.raw, isec, sec.nse_symbol)["timestamp"]
                                 .min().isoformat() if r.raw else None)})
    return out


def probe_minute_day(client: BreezeClient, isec: str, sec: TestSecurity,
                     d: date) -> dict:
    """A full trading day of 1-minute bars (expect 375 in a normal session)."""
    frm, to = _day_window(d)
    return _persist(client.minute(isec, frm, to), sec, isec, "minute_full_day")


def probe_second_open(client: BreezeClient, isec: str, sec: TestSecurity,
                      d: date) -> dict:
    """The critical one: 09:15:00-09:20:00 at 1-second resolution."""
    frm, to = _day_window(d, start=(9, 15), end=(9, 20))
    return _persist(client.second(isec, frm, to), sec, isec, "second_first_5min")


def probe_second_depth(client: BreezeClient, isec: str, sec: TestSecurity,
                       df_master: pd.DataFrame) -> list[dict]:
    """How far back does 1-second data actually exist? Probe on real trading days."""
    out = []
    for yr in DEPTH_YEARS:
        days = find_trading_days(client, isec, yr, 1, limit=1)
        if not days:
            out.append({"probe": "second_depth", "symbol": sec.nse_symbol, "year": yr,
                        "trading_day": None, "ok": False, "n_rows": 0,
                        "error": "no daily data for that month, cannot pick a trading day"})
            continue
        d = days[0]
        frm, to = _day_window(d, start=(9, 15), end=(9, 20))
        r = client.second(isec, frm, to)
        out.append({"probe": "second_depth", "symbol": sec.nse_symbol, "year": yr,
                    "trading_day": str(d), "ok": r.ok, "n_rows": r.n_rows,
                    "error": r.error, "duration_s": r.duration_s})
    return out


def probe_max_range(client: BreezeClient, isec: str, sec: TestSecurity,
                    d: date) -> list[dict]:
    """Widen the window until rows stop growing: finds row caps / truncation."""
    out = []
    # 1-second: 5 min -> 30 min -> 2h -> full day -> 2 days -> 5 days
    windows = [
        ("5min", datetime(d.year, d.month, d.day, 9, 15), datetime(d.year, d.month, d.day, 9, 20)),
        ("30min", datetime(d.year, d.month, d.day, 9, 15), datetime(d.year, d.month, d.day, 9, 45)),
        ("2h", datetime(d.year, d.month, d.day, 9, 15), datetime(d.year, d.month, d.day, 11, 15)),
        ("full_day", datetime(d.year, d.month, d.day, 9, 15), datetime(d.year, d.month, d.day, 15, 30)),
        ("2_days", datetime(d.year, d.month, d.day, 9, 15) - timedelta(days=1),
         datetime(d.year, d.month, d.day, 15, 30)),
        ("7_days", datetime(d.year, d.month, d.day, 9, 15) - timedelta(days=6),
         datetime(d.year, d.month, d.day, 15, 30)),
    ]
    for label, a, b in windows:
        r = client.second(isec, fmt_ts(a), fmt_ts(b))
        span_s = (b - a).total_seconds()
        out.append({"probe": "max_range_1second", "symbol": sec.nse_symbol, "window": label,
                    "requested_span_seconds": span_s, "ok": r.ok, "n_rows": r.n_rows,
                    "error": r.error, "duration_s": r.duration_s,
                    "returned_span": _returned_span(r, isec)})
    # daily: how many years in one call?
    for label, years in (("1y", 1), ("3y", 3), ("10y", 10), ("25y", 25)):
        a = datetime(2026, 8, 17) - timedelta(days=365 * years)
        r = client.daily(isec, fmt_ts(a), fmt_ts(datetime(2026, 8, 17, 16, 0)))
        out.append({"probe": "max_range_1day", "symbol": sec.nse_symbol, "window": label,
                    "requested_span_seconds": (datetime(2026, 8, 17) - a).total_seconds(),
                    "ok": r.ok, "n_rows": r.n_rows, "error": r.error,
                    "duration_s": r.duration_s, "returned_span": _returned_span(r, isec)})
    return out


def _returned_span(r, isec: str) -> dict | None:
    if not r.raw:
        return None
    df = storage.normalize(r.raw, isec, isec)
    ts = df["timestamp"].dropna()
    if ts.empty:
        return None
    return {"first": ts.min().isoformat(), "last": ts.max().isoformat()}


def probe_stability(client: BreezeClient, isec: str, sec: TestSecurity, d: date,
                    repeats: int = 3) -> dict:
    """Identical call, N times: are rows and values reproducible?"""
    frm, to = _day_window(d, start=(9, 15), end=(9, 20))
    runs, frames = [], []
    for _ in range(repeats):
        r = client.second(isec, frm, to)
        runs.append({"ok": r.ok, "n_rows": r.n_rows, "duration_s": r.duration_s,
                     "error": r.error})
        if r.raw:
            frames.append(storage.normalize(r.raw, isec, sec.nse_symbol))
    identical = None
    if len(frames) > 1:
        identical = all(frames[0].equals(f) for f in frames[1:])
    return {"probe": "stability", "symbol": sec.nse_symbol, "repeats": repeats,
            "runs": runs, "row_counts": [x["n_rows"] for x in runs],
            "byte_identical_payloads": identical,
            "durations_s": [x["duration_s"] for x in runs]}


def probe_inactive(client: BreezeClient, df_master: pd.DataFrame) -> list[dict]:
    """Can delisted/merged securities be queried at all? (Survivorship bias.)"""
    out = []
    for sec in [s for s in TEST_UNIVERSE if s.kind == "inactive"]:
        resolved = security_master.resolve(df_master, sec.nse_symbol)
        isec = resolved.isec_code if resolved else sec.nse_symbol
        # Ask for a window while the security was definitely still trading.
        year = {"ANDHRABANK": 2019, "CENTBOP": 2007, "BHARATFIN": 2018}.get(sec.nse_symbol, 2018)
        for label, code in (("isec_code", isec), ("nse_symbol", sec.nse_symbol)):
            r = client.daily(code, fmt_ts(datetime(year, 6, 1, 9, 0)),
                             fmt_ts(datetime(year, 6, 30, 16, 0)))
            out.append({"probe": "inactive_security", "symbol": sec.nse_symbol,
                        "note": sec.note, "variant": label, "code_used": code,
                        "master_token": resolved.token if resolved else None,
                        "queried_year": year, "ok": r.ok, "n_rows": r.n_rows,
                        "error": r.error, "duration_s": r.duration_s})
    return out


def probe_corporate_action(client: BreezeClient, df_master: pd.DataFrame) -> list[dict]:
    """Are daily prices split/bonus adjusted? Check known corporate actions.

    RELIANCE did a 1:1 bonus in Oct 2017 (ex-date ~2017-09-07) and a 1:1 bonus
    in Oct 2024. If the raw series shows a ~50% single-day drop across the
    ex-date, the data is UNADJUSTED. If it is smooth, it is back-adjusted.
    """
    out = []
    events = [("RELIANCE", "2017-09-07", "1:1 bonus"),
              ("RELIANCE", "2024-10-28", "1:1 bonus")]
    for symbol, ex_date, desc in events:
        resolved = security_master.resolve(df_master, symbol)
        isec = resolved.isec_code
        ex = datetime.fromisoformat(ex_date)
        r = client.daily(isec, fmt_ts(ex - timedelta(days=12)),
                         fmt_ts(ex + timedelta(days=12)))
        rec = {"probe": "corporate_action", "symbol": symbol, "event": desc,
               "ex_date": ex_date, "ok": r.ok, "n_rows": r.n_rows, "error": r.error}
        if r.raw:
            df = storage.normalize(r.raw, isec, symbol).sort_values("timestamp")
            df["pct_change"] = df["close"].pct_change() * 100
            worst = df.loc[df["pct_change"].abs().idxmax()] if len(df) > 1 else None
            rec["largest_daily_move_pct"] = round(float(worst["pct_change"]), 2) if worst is not None else None
            rec["largest_move_date"] = worst["timestamp"].isoformat() if worst is not None else None
            rec["appears_unadjusted"] = bool(worst is not None and abs(worst["pct_change"]) > 35)
            rec["closes"] = [
                {"date": t.isoformat()[:10], "close": float(c)}
                for t, c in zip(df["timestamp"], df["close"])
            ]
        out.append(rec)
    return out


# Candidate Breeze codes for the indices the strategy's trend filter needs.
# The NSE cash scrip master contains only index *ETFs*, not the indices
# themselves, so the real codes have to be discovered by probing. The first six
# are the codes breeze_connect's own config uses for AGGRESSIVE_LIMIT_INDICES.
INDEX_CODE_CANDIDATES = [
    "NIFTY", "CNXBAN", "NIFSEL", "NIFFIN", "BSESEN", "BANKEX",
    "CNXIT", "CNXAUT", "CNXPHA", "CNXMET", "CNXFMC", "CNXENE",
    "NIFTY 50", "NIFTY50", "NIFTYIT", "NIFTYBANK", "CNXNIF",
]


def probe_indices(client: BreezeClient) -> list[dict]:
    """Can index / sector-index history be fetched? Needed for the trend filter.

    Tried against NSE cash. A hit here means sector trend can be computed from
    Breeze directly; a total miss means indices must come from elsewhere (or be
    proxied by ETFs / equal-weight baskets of constituents).
    """
    out = []
    frm, to = fmt_ts(datetime(2026, 6, 1, 9, 0)), fmt_ts(datetime(2026, 6, 30, 16, 0))
    for code in INDEX_CODE_CANDIDATES:
        r = client.daily(code, frm, to)
        out.append({"probe": "index_code", "code_tried": code, "ok": r.ok,
                    "n_rows": r.n_rows, "error": r.error, "duration_s": r.duration_s,
                    "sample_row": r.raw[0] if r.raw else None})
    return out


def probe_volume_cross_validation(client: BreezeClient, isec: str, sec: TestSecurity,
                                  d: date) -> dict:
    """Do 1-second volumes sum to the 1-minute totals for the same window?

    This is the decisive check for the strategy. 1-second bars are sparse (only
    seconds with activity are returned), so bar-count coverage is meaningless;
    what matters is whether summing them loses volume. If the two agree, the
    opening-volume rule can be reconstructed from 1-second data.
    """
    frm, to = _day_window(d, start=(9, 15), end=(9, 20))
    r_s = client.second(isec, frm, to)
    r_m = client.minute(isec, frm, to)
    out: dict[str, Any] = {
        "probe": "volume_cross_validation", "symbol": sec.nse_symbol,
        "trading_day": str(d),
        "second_rows": r_s.n_rows, "minute_rows": r_m.n_rows,
        "second_error": r_s.error, "minute_error": r_m.error,
    }
    if not (r_s.raw and r_m.raw):
        out["comparable"] = False
        return out

    ds = storage.normalize(r_s.raw, isec, sec.nse_symbol)
    dm = storage.normalize(r_m.raw, isec, sec.nse_symbol)
    # Compare only the five whole minutes 09:15-09:19, excluding the boundary
    # bar at 09:20 which the inclusive range adds.
    ds = ds[ds["timestamp"].dt.time < __import__("datetime").time(9, 20)]
    dm = dm[dm["timestamp"].dt.time < __import__("datetime").time(9, 20)]

    per_min = ds.groupby(ds["timestamp"].dt.floor("min"))["volume"].sum()
    minute_map = dm.set_index("timestamp")["volume"]
    rows = []
    for ts, mvol in minute_map.items():
        svol = int(per_min.get(ts, 0))
        rows.append({"minute": ts.isoformat(), "minute_bar_volume": int(mvol),
                     "sum_of_1s_volume": svol, "diff": svol - int(mvol),
                     "match": svol == int(mvol)})
    out["per_minute"] = rows
    out["total_1s_volume"] = int(ds["volume"].clip(lower=0).sum())
    out["total_1m_volume"] = int(dm["volume"].clip(lower=0).sum())
    out["total_diff"] = out["total_1s_volume"] - out["total_1m_volume"]
    out["total_match"] = out["total_diff"] == 0
    out["n_minutes_matching"] = sum(1 for r in rows if r["match"])
    out["comparable"] = True
    out["distinct_seconds_present"] = int(ds["timestamp"].nunique())
    out["sparse_not_gridded"] = bool(ds["timestamp"].nunique() < 300)
    return out


def probe_second_start_boundary(client: BreezeClient, isec: str = "RELIND") -> dict:
    """Find the first date for which 1-second data exists, month by month.

    Measured result (2026-08): data begins 2018-04-02. Jan-Mar 2018 return zero
    rows with no error; April 2018 onward return ~250-300 bars per 5-min window.
    That is the start of Indian FY2018-19, which suggests an archive cutover
    rather than a gradual backfill.
    """
    out = []
    for yr, mo in [(2018, m) for m in range(1, 7)]:
        last = monthrange(yr, mo)[1]
        d = client.daily(isec, fmt_ts(datetime(yr, mo, 1, 9, 0)),
                         fmt_ts(datetime(yr, mo, last, 16, 0)))
        if not d.raw:
            out.append({"year": yr, "month": mo, "trading_day": None, "n_rows": 0})
            continue
        day = d.raw[0]["datetime"][:10]
        y, m, dd = (int(x) for x in day.split("-"))
        r = client.second(isec, fmt_ts(datetime(y, m, dd, 9, 15)),
                          fmt_ts(datetime(y, m, dd, 9, 20)))
        out.append({"year": yr, "month": mo, "trading_day": day, "n_rows": r.n_rows,
                    "has_data": r.n_rows > 0})
    first = next((x for x in out if x.get("has_data")), None)
    return {"probe": "second_start_boundary", "per_month": out,
            "first_month_with_1s_data": f"{first['year']}-{first['month']:02d}" if first else None}


# Known NSE splits/bonuses spanning the suspected adjustment cutover.
ADJUSTMENT_EVENTS = [
    ("ITC", "2016-07-12", "ITC 1:2 bonus"),
    ("RELIND", "2017-09-07", "RELIANCE 1:1 bonus"),
    ("INFTEC", "2018-09-12", "INFOSYS 1:1 bonus"),
    ("HDFBAN", "2019-09-19", "HDFCBANK 1:2 split"),
    ("TATSTE", "2022-07-29", "TATASTEEL 1:10 split"),
    ("NESIND", "2024-01-05", "NESTLEIND 1:10 split"),
    ("RELIND", "2024-10-28", "RELIANCE 1:1 bonus"),
    ("BAJFI", "2025-06-16", "BAJFINANCE split + bonus"),
]


def probe_adjustment_cutoff(client: BreezeClient) -> dict:
    """Is the daily series back-adjusted for splits/bonuses? Where does it stop?

    A ~50%/90% single-day close-to-close drop across a known ex-date means the
    series is RAW. Measured result (2026-08): events through Jul 2022 show no
    such drop (adjusted); Jan 2024 onward show the full raw drop (unadjusted).
    """
    rows = []
    for isec, ex, desc in ADJUSTMENT_EVENTS:
        d = datetime.fromisoformat(ex)
        r = client.daily(isec, fmt_ts(d - timedelta(days=10)), fmt_ts(d + timedelta(days=10)))
        if not r.raw:
            rows.append({"event": desc, "ex_date": ex, "n_rows": 0, "verdict": "no_data"})
            continue
        df = storage.normalize(r.raw, isec, isec).sort_values("timestamp")
        pc = df["close"].pct_change() * 100
        i = pc.abs().idxmax()
        move = float(pc.loc[i])
        rows.append({"event": desc, "ex_date": ex, "n_rows": r.n_rows,
                     "largest_move_pct": round(move, 2),
                     "largest_move_date": str(df.loc[i, "timestamp"])[:10],
                     "verdict": "UNADJUSTED" if abs(move) > 25 else "adjusted"})
    adj = [r["ex_date"] for r in rows if r.get("verdict") == "adjusted"]
    unadj = [r["ex_date"] for r in rows if r.get("verdict") == "UNADJUSTED"]
    return {"probe": "adjustment_cutoff", "events": rows,
            "latest_adjusted_event": max(adj) if adj else None,
            "earliest_unadjusted_event": min(unadj) if unadj else None}
