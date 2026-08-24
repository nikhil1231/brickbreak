"""Canonical alpha backtest (the refactor plan §5.10).

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

from ..research_data import repository
from .guards import assert_scorable


COST_PCT_ROUND_TRIP = 0.40

# Bad-print guard and minimum breadth for the equal-weighted benchmark. Both
# match `context._daily_returns`, so the benchmark here and the market regime
# series elsewhere are the same object computed the same way.
RET_GUARD = 0.6
MKT_MIN_SYMBOLS = 50


def _diff(a, b):
    """Difference of two stats, NaN-safe — a missing stat is not a zero."""
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
        return np.nan
    return round(float(a) - float(b), 2)


@dataclass(frozen=True)
class BacktestConfig:
    top_k: int = 5
    holding_sessions: int = 10
    cost_pct: float = COST_PCT_ROUND_TRIP
    entry_price: str = "close"
    # Entry timing is frozen by the experiment contract; it is not tuned by
    # callers after the outcome is visible.


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
    allow_unscorable: bool = False,
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
    assert_scorable(signal_col, allow_unscorable=allow_unscorable)
    cfg = cfg or BacktestConfig()
    if cfg.entry_price not in ("open", "close"):
        raise ValueError("BacktestConfig.entry_price must be open or close")
    valid = df[[date_col, symbol_col, signal_col]].dropna().copy()
    if len(valid) == 0:
        return {"error": "no valid signal rows"}

    # Load adjusted daily bars if not supplied
    if bars is None:
        bars = repository.daily_bars(
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
    b_piv = bars.pivot(index="date", columns="symbol",
                       values="close").reindex(sessions)
    open_piv = (bars.pivot(index="date", columns="symbol", values="open")
                .reindex(index=sessions, columns=b_piv.columns))
    px_matrix = b_piv.to_numpy()
    open_matrix = open_piv.to_numpy()
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

        # Price path over the holding window, kept ALIGNED to sessions. A
        # non-traded session inside the window earns 0% and the position
        # continues; compressing the NaNs out (as this once did) shifts every
        # later return onto the wrong calendar session.
        i_end = min(i0 + cfg.holding_sessions + 1, n_total_sessions)
        prices = px_matrix[i0:i_end, j].astype(float)
        if len(prices) < 2 or not np.isfinite(prices[0]):
            continue
        prices = pd.Series(prices).ffill().to_numpy()

        if cfg.entry_price == "open":
            entry = float(open_matrix[i0, j])
            if not np.isfinite(entry) or entry <= 0:
                continue
            # The registered h-session open-entry label exits at D+h close:
            # open-to-close on D plus h subsequent close-to-close returns.
            daily_r = np.concatenate((
                np.array([prices[0] / entry - 1.0]),
                (prices[1:] / prices[:-1]) - 1.0,
            ))
        else:
            daily_r = (prices[1:] / prices[:-1]) - 1.0
        daily_r = np.nan_to_num(daily_r, nan=0.0)
        # Entry cost on the first bar, exit cost on the last. For a
        # single-session hold both land on the same bar, which is correct:
        # one round trip is charged once.
        daily_r[0] -= half_cost
        daily_r[-1] -= half_cost

        h_actual = len(daily_r)
        pnl[i0:i0 + h_actual] += daily_r
        active_weights[i0:i0 + h_actual] += 1.0

    # Capital is divided across every slot the construction can hold at once:
    # a new cohort of `top_k` names each session, each held `holding_sessions`
    # sessions, so `top_k * holding_sessions` positions are open at steady
    # state. Dividing by `top_k` alone (as this once did) silently runs the
    # book at `holding_sessions` times leverage — at hold=10 it reported 334%
    # CAGR on a universe compounding at 28%. Unfilled slots sit in cash at 0%.
    slot_sessions = cfg.holding_sessions + (1 if cfg.entry_price == "open" else 0)
    n_slots = cfg.top_k * slot_sessions
    port_daily_returns = pnl / n_slots
    is_live = active_weights > 0

    port_stats = span_stats(port_daily_returns, is_live)
    if not port_stats:
        return {"error": "insufficient live sessions"}
    port_stats["mean_exposure_pct"] = round(
        float(np.mean(active_weights[is_live]) / n_slots * 100), 1) if is_live.any() else 0.0

    # Equal-weighted market return per session, on the same guard the rest of
    # the project uses: a single unadjusted 10x print in a 1,600-name mean
    # moves the index 0.6% on its own and would otherwise define a "regime"
    # (context._daily_returns). Sessions with too few priced names are unknown,
    # not flat, and are carried as 0 rather than inventing a number.
    rets = b_piv.pct_change()
    rets = rets.where(rets.abs() < RET_GUARD)
    n_priced = rets.notna().sum(axis=1)
    mkt = rets.mean(axis=1).where(n_priced >= MKT_MIN_SYMBOLS)
    mkt = mkt.reindex(sessions)

    # A session with too few priced names has an unknown market return, not a
    # flat one. If most of the span is unknown the benchmark is unavailable and
    # says so — a silent 0.0% would read as "the market went nowhere" and make
    # every signal look like alpha.
    coverage = float(mkt.notna().mean())
    benchmark_ok = coverage >= 0.5
    mkt_simple = mkt.fillna(0.0).to_numpy()

    # Two benchmarks, because on a non-contiguous partition they differ and
    # neither alone is honest. `market_benchmark` is buy-and-hold, invested
    # through every session of the span. `market_benchmark_matched` earns only
    # on the sessions the book could be live, so it carries the same cash
    # pattern the book is charged for.
    if benchmark_ok:
        mkt_stats = span_stats(mkt_simple, is_live)
        mkt_stats["invested_pct"] = 100.0
        mkt_stats.pop("deployed_pct", None)      # that field describes the book
        mkt_matched = span_stats(np.where(is_live, mkt_simple, 0.0), is_live)
        mkt_matched["invested_pct"] = round(float(is_live.mean() * 100), 1)
        mkt_matched.pop("deployed_pct", None)
    else:
        unavailable = {
            "unavailable": f"fewer than {MKT_MIN_SYMBOLS} priced names on "
                           f"{100 * (1 - coverage):.0f}% of the span",
            "session_coverage_pct": round(coverage * 100, 1),
        }
        mkt_stats = dict(unavailable)
        mkt_matched = dict(unavailable)

    return {
        "config": {
            "top_k": cfg.top_k,
            "holding_sessions": cfg.holding_sessions,
            "cost_pct_round_trip": cfg.cost_pct,
            "entry_price": cfg.entry_price,
            "capital_slots": n_slots,
        },
        "portfolio": port_stats,
        "market_benchmark": mkt_stats,
        "market_benchmark_matched": mkt_matched,
        "excess_cagr_pct": _diff(port_stats.get("cagr_pct"), mkt_stats.get("cagr_pct")),
        "excess_cagr_matched_pct": _diff(port_stats.get("cagr_pct"),
                                         mkt_matched.get("cagr_pct")),
        "excess_sharpe": _diff(port_stats.get("sharpe"), mkt_stats.get("sharpe")),
    }
