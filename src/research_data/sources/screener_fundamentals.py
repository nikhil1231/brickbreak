"""Small, explicitly approximate annual-fundamentals archive from Screener.

This source exists only for H070, where the user explicitly accepted a rough
historical Piotroski reconstruction after the proper NSE XBRL coverage gate
failed. Screener's page presents historical annual tables as they look today;
they may contain restatements and are not evidence of what was published at the
time. The raw HTML is content-addressed and the normalized rows carry that
warning in `pit_status` so downstream code cannot mistake the result for PIT.
"""
from __future__ import annotations

import hashlib
import io
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from ...core import config

BASE = "https://www.screener.in/company/{symbol}/{variant}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; brickbreak-research/1.0)"}
RAW_DIR = config.RAW_DIR / "screener_fundamentals"
PATH = config.NORMALIZED_DIR / "screener_fundamentals_approx.parquet"

FIELDS = {
    "sales": "Sales",
    "operating_profit": "Operating Profit",
    "net_income": "Net Profit",
    "total_assets": "Total Assets",
    "borrowings": "Borrowings",
    "other_assets": "Other Assets",
    "other_liabilities": "Other Liabilities",
    "equity_capital": "Equity Capital",
    "operating_cash_flow": "Cash from Operating Activity",
}


class ScreenerFundamentalsError(RuntimeError):
    pass


def _labels(table: pd.DataFrame) -> set[str]:
    return set(table.iloc[:, 0].map(_clean_label))


def _clean_label(value) -> str:
    return str(value).replace("\xa0", " ").strip().rstrip("+").strip()


def _annual_tables(html: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tables = pd.read_html(io.StringIO(html))
    try:
        profit = next(t for t in tables
                      if {"Sales", "Dividend Payout %"} <= _labels(t))
        balance = next(t for t in tables if "Total Assets" in _labels(t))
        cashflow = next(t for t in tables
                        if "Cash from Operating Activity" in _labels(t))
    except StopIteration as exc:
        raise ScreenerFundamentalsError("annual statement tables not found") from exc
    return tuple(t.set_index(t.columns[0]) for t in (profit, balance, cashflow))


def _row(table: pd.DataFrame, label: str, periods: list[str]) -> pd.Series:
    lookup = {_clean_label(index): index for index in table.index}
    if label not in lookup:
        raise ScreenerFundamentalsError(f"missing annual row {label!r}")
    raw = table.loc[lookup[label], periods]
    return pd.to_numeric(raw.astype(str).str.replace(",", "", regex=False),
                         errors="coerce")


def parse(html: str, *, symbol: str, source_url: str,
          statement_scope: str, fetched_at=None, sha256: str | None = None
          ) -> pd.DataFrame:
    """Normalize the common annual P&L, balance-sheet and cash-flow rows."""
    profit, balance, cashflow = _annual_tables(html)
    period_re = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 20\d\d$")
    periods = [str(column) for column in profit.columns
               if period_re.match(str(column))
               and column in balance.columns and column in cashflow.columns]
    if len(periods) < 2:
        raise ScreenerFundamentalsError(
            f"{symbol} has only {len(periods)} common annual periods")
    sources = {
        **{name: profit for name in ("sales", "operating_profit", "net_income")},
        **{name: balance for name in (
            "total_assets", "borrowings", "other_assets",
            "other_liabilities", "equity_capital")},
        "operating_cash_flow": cashflow,
    }
    out = pd.DataFrame({
        name: _row(sources[name], label, periods).to_numpy(dtype=float)
        for name, label in FIELDS.items()
    })
    out.insert(0, "period_label", periods)
    out.insert(0, "period_end", pd.to_datetime(periods, format="%b %Y")
                                 + pd.offsets.MonthEnd(0))
    out.insert(0, "symbol", symbol)
    out["statement_scope"] = statement_scope
    out["source_url"] = source_url
    out["source_sha256"] = sha256 or hashlib.sha256(html.encode()).hexdigest()
    out["fetched_at"] = pd.Timestamp(fetched_at or datetime.now())
    out["pit_status"] = "current_restated_page_not_point_in_time"
    return out


def _store(html: str) -> str:
    payload = html.encode()
    sha = hashlib.sha256(payload).hexdigest()
    path = RAW_DIR / sha[:2] / f"{sha}.html"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return sha


def _fetch(symbol: str, scope: str, timeout: int = 30) -> tuple[str, str]:
    variant = "consolidated/" if scope == "consolidated" else ""
    url = BASE.format(symbol=symbol, variant=variant)
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    if response.status_code != 200:
        raise ScreenerFundamentalsError(
            f"{symbol} {scope}: HTTP {response.status_code}")
    return url, response.text


def sync(symbols: list[str], *, throttle: float = 0.35,
         timeout: int = 30) -> pd.DataFrame:
    """Fetch both scopes and deterministically keep the longer common history.

    Consolidated wins a tie. This makes ABB use standalone (12 common annual
    periods rather than four) without hand-picking the better-looking score.
    """
    frames = []
    for symbol in symbols:
        candidates = []
        for scope in ("consolidated", "standalone"):
            url, html = _fetch(symbol, scope, timeout)
            sha = _store(html)
            candidates.append(parse(
                html, symbol=symbol, source_url=url, statement_scope=scope,
                sha256=sha))
            time.sleep(throttle)
        best = max(candidates,
                   key=lambda f: (len(f), f["statement_scope"].iloc[0]
                                  == "consolidated"))
        frames.append(best)
    panel = pd.concat(frames, ignore_index=True).sort_values(
        ["symbol", "period_end"]).reset_index(drop=True)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PATH, index=False)
    return panel


def load(path: Path | None = None) -> pd.DataFrame:
    target = path or PATH
    if not target.exists():
        raise FileNotFoundError(
            f"approximate fundamentals missing: {target}; run sync first")
    return pd.read_parquet(target)


__all__ = ["PATH", "ScreenerFundamentalsError", "load", "parse", "sync"]
