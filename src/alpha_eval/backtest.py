"""Canonical alpha backtest (PLAN.md §5.10).

Deliberately simple, non-optimised standard portfolio simulation:
- Daily ranking by signal.
- Hold top K equal-weight for H sessions.
- 0.40% round-trip transaction costs (0.20% entry, 0.20% exit).
- Cash-charged calendar span annualisation (cash days earn 0% and count toward calendar time).
- Aligned comparisons against buy-and-hold market index and equal-weight universe.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from .. import config


COST_PCT_ROUND_TRIP = 0.40


@dataclass(frozen=True)
class BacktestConfig:
    top_k: int = 5
    holding_sessions: int = 10
    cost_pct: float = COST_PCT_ROUND_TRIP
    entry_col: str = "close"      # or "open"
    price_col: str = "close"


def span_stats(daily_returns: np.ndarray, is_live: np.ndarray | None = None) -> dict:
    """Portfolio statistics over the calendar span, with cash days counted.

    Charging a book for its cash: uninvested days earn 0.0% and still count
    toward the calendar clock, preventing cash-heavy rules from exaggerating
    annualized CAGR.
    """
    if len(daily_returns) == 0:
        return {}

    if is_live is not None and is_live.any():
        i0 = int(np.argmax(is_live))
        i1 = int(len(is_live) - 1 - np.argmax(is_live[::-1]))
        rr = daily_returns[i0:i1 + 1]
        live_sub = is_live[i0:i1 + 1]
    else:
        rr = daily_returns
        live_sub = np.ones(len(rr), dtype=bool)

    n_sessions = len(rr)
    if n_sessions < 5:
        return {}

    equity = np.cumprod(1.0 + rr)
    total_ret = float(equity[-1] - 1.0)
    years = n_sessions / 250.0
    cagr = float(equity[-1] ** (1.0 / years) - 1.0) if equity[-1] > 0 and years > 0 else np.nan

    # Drawdown
    peaks = np.maximum.accumulate(equity)
    drawdowns = (equity / peaks) - 1.0
    max_dd = float(np.min(drawdowns))

    # Sharpe ratio
    std_r = float(np.std(rr))
    sharpe = float((np.mean(rr) / std_r) * np.sqrt(250)) if std_r > 0 else np.nan
    deployed_pct = float(np.mean(live_sub) * 100.0)

    return {
        "total_return_pct": round(total_ret * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2) if np.isfinite(cagr) else np.nan,
        "sharpe": round(sharpe, 2) if np.isfinite(sharpe) else np.nan,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "deployed_pct": round(deployed_pct, 1),
        "n_sessions": int(n_sessions),
    }


def canonical_backtest(
    df: pd.DataFrame,
    signal_col: str,
    cfg: BacktestConfig | None = None,
    date_col: str = "date",
    symbol_col: str = "symbol",
    bars: pd.DataFrame | None = None,
) -> dict:
    """Runs standard canonical alpha backtest.

    Parameters
    ----------
    df : pd.DataFrame
        Frame with symbol, date, and signal_col.
    signal_col : str
        Column name of the signal to rank on.
    cfg : BacktestConfig
        Configuration parameters (top_k, holding_sessions, cost_pct).
    bars : pd.DataFrame or None
        Adjusted daily bars for price paths. If None, loaded from disk.

    Returns
    -------
    dict
        Portfolio performance and aligned benchmark comparisons.
    """
    cfg = cfg or BacktestConfig()
    valid = df[[date_col, symbol_col, signal_col]].dropna().copy()
    if len(valid) == 0:
        return {"error": "no valid signal rows"}

    # Load adjusted daily bars if not supplied
    if bars is None:
        bars = pd.read_parquet(
            config.NORMALIZED_DIR / "daily_bars_adj.parquet",
            columns=["symbol", "date", "open", "close"])

    # Rank daily and pick top K
    valid["rank"] = valid.groupby(date_col)[signal_col].rank(ascending=False, method="first")
    picks = valid[valid["rank"] <= cfg.top_k].copy()
    if len(picks) == 0:
        return {"error": "no picks produced"}

    # Construct unique session timeline
    sessions = np.sort(bars["date"].unique())
    session_map = {d: i for i, d in enumerate(sessions)}
    n_total_sessions = len(sessions)

    # Track open positions and pnl per session
    # PnL array across all calendar sessions
    pnl = np.zeros(n_total_sessions, dtype=float)
    active_weights = np.zeros(n_total_sessions, dtype=float)

    # Build 2D price matrix for fast vector slicing (date x symbol)
    b_piv = bars.pivot(index="date", columns="symbol", values="close").reindex(sessions)
    px_matrix = b_piv.to_numpy()
    sym_map = {sym: j for j, sym in enumerate(b_piv.columns)}

    half_cost = (cfg.cost_pct / 2.0) / 100.0  # 0.20% = 0.0020

    # Simulate each selected trade
    for row in picks.itertuples():
        sym = getattr(row, symbol_col)
        start_date = getattr(row, date_col)
        i0 = session_map.get(start_date)
        j = sym_map.get(sym)
        if i0 is None or j is None:
            continue

        # Look up price path for holding_sessions directly from matrix
        i_end = min(i0 + cfg.holding_sessions + 1, n_total_sessions)
        prices = px_matrix[i0:i_end, j]
        prices = prices[np.isfinite(prices)]

        if len(prices) < 2:
            continue

        # Compute daily simple returns over holding span
        daily_r = (prices[1:] / prices[:-1]) - 1.0
        # Deduct entry cost on first bar, exit cost on last bar
        daily_r[0] -= half_cost
        daily_r[-1] -= half_cost

        h_actual = len(daily_r)
        pnl[i0:i0 + h_actual] += daily_r
        active_weights[i0:i0 + h_actual] += 1.0

    # Portfolio daily return = sum of trade PnLs / top_k (unfilled slots sit in cash at 0%)
    port_daily_returns = pnl / cfg.top_k
    is_live = active_weights > 0

    port_stats = span_stats(port_daily_returns, is_live)
    if not port_stats:
        return {"error": "insufficient live sessions"}

    # Benchmark 1: Buy-and-Hold Market Index over the identical span
    # Compute market equal-weighted return per session
    mkt_daily = bars.groupby("date")["close"].apply(
        lambda s: np.nanmean(s.pct_change()) if len(s) > 1 else 0.0
    ).reindex(sessions).fillna(0.0).to_numpy()

    # Or compute market simple return on priced closes
    b_piv = bars.pivot(index="date", columns="symbol", values="close")
    mkt_simple = b_piv.pct_change().mean(axis=1).reindex(sessions).fillna(0.0).to_numpy()

    mkt_stats = span_stats(mkt_simple, is_live)

    return {
        "config": {
            "top_k": cfg.top_k,
            "holding_sessions": cfg.holding_sessions,
            "cost_pct_round_trip": cfg.cost_pct,
        },
        "portfolio": port_stats,
        "market_benchmark": mkt_stats,
        "excess_cagr_pct": round(port_stats.get("cagr_pct", 0) - mkt_stats.get("cagr_pct", 0), 2),
        "excess_sharpe": round(port_stats.get("sharpe", 0) - mkt_stats.get("sharpe", 0), 2),
    }
