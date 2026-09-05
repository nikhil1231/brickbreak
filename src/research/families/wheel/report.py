"""Scoring the wheel against the thing it claims to replace.

THE COMPARISON GRID IS THE EXPIRY CALENDAR
The wheel's equity is only observable where its positions settle: on expiry
days. So the benchmark is sampled on exactly those dates and both series are
scored on the same ~80 monthly steps. Sampling the index daily and the strategy
monthly would flatter whichever one had the smoother clock — usually the
strategy, because monthly sampling cannot see an intra-month drawdown.

WHICH BRINGS UP THE ONE NUMBER THIS FILE CANNOT HONESTLY REPORT
`max_drawdown` here is a *monthly-close* drawdown for both series. It understates
both, and it understates the wheel more, because a short put's worst mark and
its settlement value are not the same thing: a position that is 25% underwater
three weeks in can settle at breakeven. Read it as a comparison between the two
series, never as the drawdown an operator would have watched.

SHARPE IS EXCESS OF THE SAME CASH RATE FOR BOTH
A cash-secured wheel earns the short rate on most of its capital. Comparing its
raw Sharpe to an index's raw Sharpe therefore credits the wheel with the
risk-free rate twice — once in the return and once in the ratio. Both series are
excess of RBI repo here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import RBI_REPO_PATH, _step

PERIODS_PER_YEAR = 12.0


def _drawdown(level: pd.Series) -> float:
    return float((level / level.cummax() - 1.0).min())


def _cagr(level: pd.Series, sessions: pd.Series) -> float:
    years = (sessions.iloc[-1] - sessions.iloc[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float((level.iloc[-1] / level.iloc[0]) ** (1.0 / years) - 1.0)


def metrics(level: pd.Series, sessions: pd.Series, name: str) -> dict:
    level = level.reset_index(drop=True)
    sessions = pd.Series(pd.to_datetime(sessions)).reset_index(drop=True)
    step = level.pct_change().dropna()
    gap = sessions.diff().dt.days.dropna().to_numpy() / 365.0
    rf = _step(RBI_REPO_PATH, sessions.iloc[1:]) * gap
    excess = step.to_numpy() - rf
    vol = float(step.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))
    downside = step[step < 0]
    return {
        "series": name,
        "cagr": _cagr(level, sessions),
        "vol": vol,
        "sharpe": float(excess.mean() / excess.std(ddof=1)
                        * np.sqrt(PERIODS_PER_YEAR)) if len(excess) > 1 else float("nan"),
        "sortino": float(step.mean() / downside.std(ddof=1)
                         * np.sqrt(PERIODS_PER_YEAR)) if len(downside) > 1 else float("nan"),
        "max_drawdown_monthly": _drawdown(level),
        "worst_month": float(step.min()),
        "best_month": float(step.max()),
        "hit_rate": float((step > 0).mean()),
        "periods": int(len(step)),
        "total_return": float(level.iloc[-1] / level.iloc[0] - 1.0),
    }


def align(benchmark: pd.DataFrame, sessions: pd.Series,
          column: str = "total_level") -> pd.Series:
    """Sample an index level on the strategy's own settlement dates."""
    bench = benchmark[["session", column]].dropna().sort_values("session")
    wanted = pd.DataFrame({"session": pd.to_datetime(sessions).sort_values()})
    merged = pd.merge_asof(wanted, bench, on="session", direction="backward")
    return merged[column].reset_index(drop=True)


def compare(curve: pd.DataFrame, benchmark: pd.DataFrame,
            label: str = "wheel") -> pd.DataFrame:
    sessions = pd.to_datetime(curve["session"]).reset_index(drop=True)
    rows = [metrics(curve["equity"].reset_index(drop=True), sessions, label)]
    for column, name in (("price_level", "Nifty 50 (price)"),
                         ("total_level", "Nifty 50 (total return)")):
        if column in benchmark.columns:
            rows.append(metrics(align(benchmark, sessions, column), sessions, name))
    blend = volatility_matched(benchmark, sessions, rows[0]["vol"])
    weight = blend.attrs.get("weight", float("nan"))
    rows.append(metrics(blend, sessions,
                        f"Nifty TR {weight:.0%} + cash {1 - weight:.0%}"))
    return pd.DataFrame(rows)


def volatility_matched(benchmark: pd.DataFrame, sessions: pd.Series,
                       target_vol: float, column: str = "total_level"
                       ) -> pd.Series:
    """Nifty blended with cash until it has the strategy's volatility.

    THIS IS THE HURDLE THAT ACTUALLY BITES. A cash-secured wheel is structurally
    a low-beta position: most of its capital sits in collateral and its upside
    is capped by the strike. Comparing it to a fully invested index and finding
    a better Sharpe proves nothing — a passive investor can buy the same lower
    volatility for free by holding part of the book in T-bills. So the wheel is
    also scored against `w` of the index and `1 - w` of cash, with `w` chosen so
    the blend's realised volatility equals the wheel's.

    The blend is built with hindsight (`w` uses realised vol over the whole
    sample), which favours the *benchmark*. That is the right direction for a
    hurdle to be wrong in.
    """
    level = align(benchmark, sessions, column)
    stamps = pd.Series(pd.to_datetime(sessions)).reset_index(drop=True)
    step = level.pct_change().dropna()
    index_vol = float(step.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))
    weight = 1.0 if index_vol <= 0 else min(target_vol / index_vol, 1.0)
    gap = stamps.diff().dt.days.dropna().to_numpy() / 365.0
    rf = _step(RBI_REPO_PATH, stamps.iloc[1:]) * gap
    blended = weight * step.to_numpy() + (1.0 - weight) * rf
    out = pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + blended)]))
    out.attrs["weight"] = weight
    return out


def attribution(curve: pd.DataFrame) -> pd.DataFrame:
    """Where the rupees came from, as a share of starting equity per year."""
    if "premium" not in curve.columns:
        return pd.DataFrame()
    frame = curve.copy()
    frame["opening"] = frame["equity"].shift(1)
    frame.loc[frame.index[0], "opening"] = (
        frame["equity"].iloc[0] - frame[["premium", "interest",
                                         "underlying"]].iloc[0].sum()
        + frame["settlement_fee"].iloc[0])
    frame["year"] = pd.to_datetime(frame["session"]).dt.year
    for column in ("premium", "interest", "settlement_fee", "underlying"):
        frame[column + "_pct"] = frame[column] / frame["opening"]
    grouped = frame.groupby("year")[
        ["premium_pct", "interest_pct", "settlement_fee_pct", "underlying_pct"]
    ].sum()
    grouped["net_pct"] = (grouped["premium_pct"] + grouped["interest_pct"]
                          + grouped["underlying_pct"]
                          - grouped["settlement_fee_pct"])
    return grouped.reset_index()


def edge_test(curve: pd.DataFrame, benchmark: pd.DataFrame,
              seed: int = 20260829, draws: int = 5000) -> pd.DataFrame:
    """Is the gap to each benchmark distinguishable from luck?

    Seventy-nine monthly observations is not many. A three-point CAGR gap over
    that sample is comfortably inside what a coin lands on, so the difference is
    reported with an interval rather than as a number. The interval comes from a
    **stationary block bootstrap** on the monthly return *differences*, mean
    block length six months: the wheel's edge is not i.i.d. across months —
    short volatility earns steadily and loses in clusters — and an i.i.d.
    bootstrap would price that away and produce an interval far too tight.

    In the house style, this is a description, not a gate. Nothing is promoted
    because an interval excluded zero.
    """
    sessions = pd.to_datetime(curve["session"]).reset_index(drop=True)
    wheel = curve["equity"].reset_index(drop=True).pct_change().dropna().to_numpy()
    rng = np.random.default_rng(seed)
    rows = []
    targets = {"Nifty 50 (price)": align(benchmark, sessions, "price_level"),
               "Nifty 50 (total return)": align(benchmark, sessions, "total_level")}
    wheel_vol = float(pd.Series(wheel).std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))
    targets["Nifty TR, volatility-matched"] = volatility_matched(
        benchmark, sessions, wheel_vol)
    for name, level in targets.items():
        other = level.pct_change().dropna().to_numpy()
        diff = wheel - other
        n = len(diff)
        mean = float(diff.mean())
        t = mean / (diff.std(ddof=1) / np.sqrt(n))
        # Stationary bootstrap: geometric block lengths, mean 6.
        samples = np.empty(draws)
        for k in range(draws):
            picked = []
            while len(picked) < n:
                index = rng.integers(n)
                length = rng.geometric(1.0 / 6.0)
                for _ in range(length):
                    picked.append(diff[index % n])
                    index += 1
            samples[k] = np.mean(picked[:n])
        lo, hi = np.percentile(samples, [2.5, 97.5])
        rows.append({"versus": name,
                     "mean_monthly_gap": mean,
                     "annualised_gap": mean * PERIODS_PER_YEAR,
                     "t_naive": float(t),
                     "boot_lo_annual": float(lo * PERIODS_PER_YEAR),
                     "boot_hi_annual": float(hi * PERIODS_PER_YEAR),
                     "months_ahead": float((diff > 0).mean())})
    return pd.DataFrame(rows)


def trade_stats(trades: pd.DataFrame) -> dict:
    """What the wheel actually did, as distinct from what it earned."""
    if trades.empty:
        return {}
    puts = trades.loc[trades["kind"] == "put"]
    calls = trades.loc[trades["kind"] == "call"]
    premium = trades["premium_net"].sum()
    notional = (puts["strike"] * puts["qty"]).sum()
    hedged = (puts["hedge_strike"].notna()
              if "hedge_strike" in puts else pd.Series(False, index=puts.index))
    exercised = (puts["hedge_exercised"].fillna(False)
                 if "hedge_exercised" in puts
                 else pd.Series(False, index=puts.index))
    widths = ((puts.loc[hedged, "strike"] - puts.loc[hedged, "hedge_strike"])
              / puts.loc[hedged, "strike"] if hedged.any()
              else pd.Series(dtype=float))
    return {
        "cycles": int(trades["expiry"].nunique()),
        "legs": int(len(trades)),
        "puts_written": int(len(puts)),
        "calls_written": int(len(calls)),
        "put_assignment_rate": float(puts["assigned"].mean()) if len(puts) else float("nan"),
        "call_assignment_rate": float(calls["assigned"].mean()) if len(calls) else float("nan"),
        "stranded_holds": int((trades["kind"] == "hold").sum()),
        "premium_per_put_notional": float(
            puts["premium_net"].sum() / notional) if notional else float("nan"),
        "hedged_puts": int(hedged.sum()),
        "hedge_exercise_rate": float(exercised[hedged].mean())
        if hedged.any() else float("nan"),
        "median_hedge_width": float(widths.median()) if len(widths) else float("nan"),
        "hedge_cost_per_put_notional": float(
            puts["hedge_cost"].sum() / notional)
        if notional and "hedge_cost" in puts else 0.0,
        "net_premium_collected": float(premium),
        "distinct_symbols": int(trades["symbol"].nunique()),
    }


def yearly(curve: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    """Calendar-year returns, on the same expiry grid, for both series."""
    sessions = pd.to_datetime(curve["session"]).reset_index(drop=True)
    frame = pd.DataFrame({
        "session": sessions,
        "wheel": curve["equity"].reset_index(drop=True),
        "nifty_price": align(benchmark, sessions, "price_level"),
        "nifty_total": align(benchmark, sessions, "total_level"),
    })
    frame["year"] = frame["session"].dt.year
    out = []
    for year, block in frame.groupby("year"):
        prior = frame.loc[frame["session"] < block["session"].iloc[0]]
        base = prior.iloc[-1] if len(prior) else block.iloc[0]
        out.append({
            "year": year,
            "wheel": block["wheel"].iloc[-1] / base["wheel"] - 1.0,
            "nifty_price": block["nifty_price"].iloc[-1] / base["nifty_price"] - 1.0,
            "nifty_total": block["nifty_total"].iloc[-1] / base["nifty_total"] - 1.0,
        })
    return pd.DataFrame(out)


__all__ = ["align", "attribution", "compare", "edge_test", "metrics",
           "trade_stats", "volatility_matched", "yearly"]
