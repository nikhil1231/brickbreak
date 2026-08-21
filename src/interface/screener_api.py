"""Opening-window screener API mounted by :mod:`src.interface.backend`.

Filtering happens here in pandas rather than in the browser: the metrics panel
is millions of rows, and shipping it to the client would be slow and cap what
can be explored. A screen over the full panel takes tens of milliseconds, so
the UI stays responsive while retaining the entire history.

The standalone server at the bottom is retained for the legacy
``serve-screener`` command and focused debugging. Normal application use goes
through the primary backend.
"""
from __future__ import annotations

import json
import threading
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from ..core import config
from ..research.opening_window.screener import STAGES, ScreenConfig, run_screen, summarize
from ..research_data.pipelines import daily_panel as build_screen

FRONTEND = config.PROJECT_ROOT / "frontend"

_state: dict = {}
_lock = threading.Lock()


def _load() -> pd.DataFrame:
    with _lock:
        if "metrics" not in _state:
            # Screens interactively, so it must not read the entry day's own
            # close either (H015).
            df = build_screen.load(asof_open=True)
            df["date"] = pd.to_datetime(df["date"])
            _state["metrics"] = df
        return _state["metrics"]


def _cfg_from_query(q: dict[str, list[str]]) -> ScreenConfig:
    """Build a ScreenConfig from query params, honouring each field's type."""
    kwargs = {}
    for f in fields(ScreenConfig):
        if f.name not in q:
            continue
        raw = q[f.name][0]
        if raw == "" or raw.lower() == "null":
            kwargs[f.name] = None
            continue
        t = f.type if isinstance(f.type, str) else str(f.type)
        try:
            if "bool" in t:
                kwargs[f.name] = raw.lower() in ("1", "true", "yes", "on")
            elif "int" in t and "float" not in t:
                kwargs[f.name] = int(float(raw))
            elif "float" in t:
                kwargs[f.name] = float(raw)
            elif "tuple" in t:
                kwargs[f.name] = tuple(x for x in raw.split(",") if x)
            else:
                kwargs[f.name] = raw
        except ValueError:
            continue
    return ScreenConfig(**kwargs)


def _json_safe(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 4)
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    if o is pd.NaT or (isinstance(o, float) and np.isnan(o)):
        return None
    return o


DISPLAY_COLS = [
    "symbol", "sector", "size_tier", "size_tier_rank", "close",
    "median_tv_20_cr", "atr_ratio", "base_depth", "bb_width_pctile",
    "range_pct_ma", "contraction_steps", "nr_k", "n_small_bodies_5",
    "vol_squeeze", "px_vs_ema_fast", "ret_20d", "ret_60d", "dist_52w_high",
    "sector_breadth", "sec_slope", "deliv_pct",
]


def api_meta() -> dict:
    df = _load()
    dates = sorted(df["date"].dt.strftime("%Y-%m-%d").unique().tolist())
    sectors = sorted(s for s in df["sector"].dropna().unique().tolist())
    defaults = ScreenConfig().to_dict()
    defaults["allowed_series"] = ",".join(defaults["allowed_series"])
    return {
        "dates": dates,
        "sectors": sectors,
        "n_symbols": int(df["symbol"].nunique()),
        "n_rows": int(len(df)),
        "stages": STAGES,
        "defaults": defaults,
        "size_tiers": sorted(int(x) for x in df["size_tier_rank"].dropna().unique()),
    }


def api_screen(q: dict) -> dict:
    df = _load()
    cfg = _cfg_from_query(q)
    sel_date = q.get("date", [None])[0]

    cands, counts = run_screen(df, cfg)
    counts = counts.sort_values("date")

    series = {
        "dates": counts["date"].dt.strftime("%Y-%m-%d").tolist(),
        **{s: counts[s].astype(int).tolist() for s in STAGES},
    }

    # Candidate table for one date (default: the most recent date with any).
    if not sel_date:
        nz = counts[counts["contraction"] > 0]
        sel_date = (nz["date"].max() if len(nz) else counts["date"].max())
        sel_date = pd.Timestamp(sel_date).strftime("%Y-%m-%d")
    day = cands[cands["date"] == pd.Timestamp(sel_date)]
    cols = [c for c in DISPLAY_COLS if c in day.columns]
    rows = [{k: _json_safe(v) for k, v in r.items()}
            for r in day[cols].sort_values("median_tv_20_cr", ascending=False)
            .head(300).to_dict("records")]

    # Per-sector candidate mix over the whole window, for the sector panel.
    by_sector = (cands.groupby("sector").size().sort_values(ascending=False)
                 .head(25).to_dict())

    return {
        "config": cfg.to_dict() | {"allowed_series": ",".join(cfg.allowed_series)},
        "summary": summarize(counts),
        "series": series,
        "selected_date": sel_date,
        "candidates": rows,
        "columns": cols,
        "total_candidates": int(len(cands)),
        "by_sector": {str(k): int(v) for k, v in by_sector.items()},
    }


def api_symbol(q: dict) -> dict:
    """Recent daily history for one symbol, for the detail sparkline."""
    df = _load()
    sym = q.get("symbol", [""])[0]
    n = int(q.get("n", ["120"])[0])
    d = df[df["symbol"] == sym].sort_values("date").tail(n)
    if d.empty:
        return {"symbol": sym, "bars": []}
    cols = ["date", "open", "high", "low", "close", "volume",
            "ema_fast", "ema_mid", "atr_ratio", "base_depth", "bb_width_pctile"]
    cols = [c for c in cols if c in d.columns]
    bars = [{k: _json_safe(v) for k, v in r.items()} for r in d[cols].to_dict("records")]
    return {"symbol": sym, "sector": str(d["sector"].iloc[-1]), "bars": bars}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/meta":
                return self._send(json.dumps(api_meta()).encode(), "application/json")
            if u.path == "/api/screen":
                return self._send(json.dumps(api_screen(q)).encode(), "application/json")
            if u.path == "/api/symbol":
                return self._send(json.dumps(api_symbol(q)).encode(), "application/json")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._send(json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(),
                              "application/json", 500)

        static_root = (FRONTEND / "dist") if (FRONTEND / "dist").exists() else FRONTEND
        name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        p = (static_root / name).resolve()
        if not str(p).startswith(str(static_root.resolve())) or not p.exists():
            p = (static_root / "index.html").resolve()
            if not p.exists():
                return self._send(b"not found", "text/plain", 404)
        ctype = {"html": "text/html", "js": "text/javascript",
                 "css": "text/css", "svg": "image/svg+xml",
                 "json": "application/json", "png": "image/png",
                 "ico": "image/x-icon"}.get(p.suffix.lstrip("."), "application/octet-stream")
        return self._send(p.read_bytes(), f"{ctype}; charset=utf-8")


def serve_standalone(port: int = 8765) -> None:
    """Run only the screener API and UI for focused legacy workflows."""
    print("warming metrics panel ...", flush=True)
    df = _load()
    print(f"  {len(df):,} rows, {df['symbol'].nunique():,} symbols", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"standalone screener -> http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
