"""Scoring a covered call against the thing it is meant to replace.

THE GRID IS DAILY, WHICH IS THE POINT
The wheel study before this one could only observe its own equity monthly, so
its drawdowns were monthly-close drawdowns and flattered it. Here the option
chain carries a settlement mark for every listed strike on every session, so
both the strategy and the benchmark are scored on the same ~1,650 daily steps
and the drawdown is the one an operator would actually have watched.

FOUR HURDLES, AND THE THIRD IS THE ONE THAT DECIDES IT
  1. **NIFTYBEES buy-and-hold.** The strategy's own equity leg, held and left
     alone. This is the honest like-for-like: same instrument, same fees to get
     in, the overlay is the only difference. It is the headline comparison.
  2. **Nifty 50 total return.** The theoretical index, dividends accrued. The
     gap between this and (1) is the ETF's tracking and expense.
  3. **A volatility-matched blend of Nifty and cash.** A covered call sells
     upside for income, so it is structurally lower-volatility than the index.
     Beating the index's Sharpe on that basis proves nothing: an investor can
     buy the same volatility reduction for free by holding part of the book in
     T-bills. The blend holds `w` of the index and `1-w` of cash, with `w` set
     so the blend's realised volatility equals the strategy's. If the covered
     call does not beat *this*, its risk reduction is not worth paying for.
  4. **Nifty 50 price return.** Reported only because it is what people quote,
     and quoting it flatters every strategy by the dividend yield.

The blend uses realised volatility over the whole sample, so it is built with
hindsight — in the *benchmark's* favour, which is the right direction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import RBI_REPO_PATH, _step

PERIODS_PER_YEAR = 252.0


def _repo(stamps: pd.Series) -> np.ndarray:
    return np.array([_step(RBI_REPO_PATH, s) for s in stamps])


def _drawdown(level: pd.Series) -> float:
    return float((level / level.cummax() - 1.0).min())


def metrics(level: pd.Series, sessions: pd.Series, name: str) -> dict:
    level = pd.Series(level).reset_index(drop=True)
    sessions = pd.Series(pd.to_datetime(sessions)).reset_index(drop=True)
    step = level.pct_change().dropna()
    years = (sessions.iloc[-1] - sessions.iloc[0]).days / 365.25
    gap = sessions.diff().dt.days.dropna().to_numpy() / 365.0
    rf = _repo(sessions.iloc[1:]) * gap
    excess = step.to_numpy() - rf
    downside = step[step < 0]
    return {
        "series": name,
        "cagr": float((level.iloc[-1] / level.iloc[0]) ** (1 / years) - 1.0),
        "vol": float(step.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)),
        "sharpe": float(excess.mean() / excess.std(ddof=1)
                        * np.sqrt(PERIODS_PER_YEAR)),
        "sortino": float(step.mean() / downside.std(ddof=1)
                         * np.sqrt(PERIODS_PER_YEAR)) if len(downside) > 1
        else float("nan"),
        "max_drawdown": _drawdown(level),
        "worst_day": float(step.min()),
        "best_day": float(step.max()),
        "total_return": float(level.iloc[-1] / level.iloc[0] - 1.0),
        "days": int(len(step)),
    }


def volatility_matched(index_level: pd.Series, sessions: pd.Series,
                       target_vol: float) -> pd.Series:
    """`w` of the index and `1-w` of cash, matched to the strategy's volatility."""
    step = pd.Series(index_level).reset_index(drop=True).pct_change().dropna()
    stamps = pd.Series(pd.to_datetime(sessions)).reset_index(drop=True)
    index_vol = float(step.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))
    weight = 1.0 if index_vol <= 0 else min(target_vol / index_vol, 1.0)
    gap = stamps.diff().dt.days.dropna().to_numpy() / 365.0
    rf = _repo(stamps.iloc[1:]) * gap
    blended = weight * step.to_numpy() + (1.0 - weight) * rf
    out = pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + blended)]))
    out.attrs["weight"] = weight
    return out


def compare(curve: pd.DataFrame, benchmarks: dict[str, pd.Series],
            label: str = "covered call") -> pd.DataFrame:
    sessions = pd.to_datetime(curve["session"]).reset_index(drop=True)
    equity = curve["equity"].reset_index(drop=True)
    rows = [metrics(equity, sessions, label)]
    for name, level in benchmarks.items():
        rows.append(metrics(level, sessions, name))
    blend = volatility_matched(benchmarks["Nifty 50 (total return)"], sessions,
                               rows[0]["vol"])
    weight = blend.attrs["weight"]
    rows.append(metrics(blend, sessions,
                        f"Nifty TR {weight:.0%} + cash {1 - weight:.0%}"))
    return pd.DataFrame(rows)


def overlay_stats(trades: pd.DataFrame, curve: pd.DataFrame) -> dict:
    """What the overlay actually did, as distinct from what it earned."""
    if trades.empty:
        return {}
    itm = trades["itm"]
    notional = trades["qty"] * trades["spot_at_write"]
    premium_rate = trades["premium_net"] / notional
    # How much upside each in-the-money call handed over, on notional.
    given_up = np.where(itm, (trades["terminal"] - trades["strike"])
                        * trades["qty"] / notional, 0.0)
    return {
        "calls_written": int(len(trades)),
        "pct_finished_itm": float(itm.mean()),
        "median_delta": float(trades["delta"].median()),
        "median_otm_pct": float(np.expm1(trades["moneyness"]).median()),
        "median_premium_pct_of_notional": float(premium_rate.median()),
        "annualised_premium_pct": float(premium_rate.sum()
                                        / ((pd.to_datetime(curve["session"]).iloc[-1]
                                            - pd.to_datetime(curve["session"]).iloc[0]).days
                                           / 365.25)),
        "total_premium_pct": float(premium_rate.sum()),
        "total_upside_given_up_pct": float(given_up.sum()),
        "worst_single_call_give_up_pct": float(given_up.max()),
        "peak_funding_pct_of_equity": float(curve["funding"].min()),
        "closed_early": int((trades["closed"] == "profit_take").sum()),
    }


def yearly(curve: pd.DataFrame, benchmarks: dict[str, pd.Series]) -> pd.DataFrame:
    frame = pd.DataFrame({"session": pd.to_datetime(curve["session"]),
                          "strategy": curve["equity"].to_numpy()})
    for name, level in benchmarks.items():
        frame[name] = np.asarray(level)
    frame["year"] = frame["session"].dt.year
    columns = ["strategy"] + list(benchmarks)
    rows = []
    for year, block in frame.groupby("year"):
        prior = frame.loc[frame["session"] < block["session"].iloc[0]]
        base = prior.iloc[-1] if len(prior) else block.iloc[0]
        rows.append({"year": year,
                     **{c: block[c].iloc[-1] / base[c] - 1.0 for c in columns}})
    return pd.DataFrame(rows)


def regime_table(curve: pd.DataFrame, index_level: pd.Series,
                 window: int = 252) -> pd.DataFrame:
    """The strategy's edge, bucketed by what the market did over the same window.

    This is the direct test of a "performs well in sideways markets, badly in
    strong bull markets" claim. Windows are rolling and therefore overlap
    heavily, so `windows` counts observations that are nowhere near independent
    — read the medians, not any significance you might be tempted to attach.
    """
    strategy = pd.Series(curve["equity"].to_numpy())
    index = pd.Series(np.asarray(index_level))
    s_fwd = strategy.shift(-window) / strategy - 1.0
    i_fwd = index.shift(-window) / index - 1.0
    frame = pd.DataFrame({"strategy": s_fwd, "index": i_fwd}).dropna()
    buckets = [(-np.inf, 0.0, "bear (<0%)"), (0.0, 0.06, "sideways (0-6%)"),
               (0.06, 0.15, "moderate bull (6-15%)"),
               (0.15, np.inf, "strong bull (>15%)")]
    rows = []
    for lo, hi, name in buckets:
        mask = (frame["index"] > lo) & (frame["index"] <= hi)
        block = frame.loc[mask]
        if block.empty:
            continue
        rows.append({
            "regime": name, "windows": int(len(block)),
            "median_index": float(block["index"].median()),
            "median_strategy": float(block["strategy"].median()),
            "median_gap": float((block["strategy"] - block["index"]).median()),
            "strategy_ahead_pct": float((block["strategy"] > block["index"]).mean()),
        })
    return pd.DataFrame(rows)


def edge_test(curve: pd.DataFrame, benchmarks: dict[str, pd.Series],
              seed: int = 20260905, draws: int = 5000,
              mean_block: int = 21) -> pd.DataFrame:
    """Is the gap to each benchmark distinguishable from luck?

    A **stationary block bootstrap** on the daily return *differences*, mean
    block one trading month. Blocks matter here more than usual: a covered call's
    shortfall is not spread evenly across days, it is concentrated in the handful
    of weeks the index gapped through the strike, so an i.i.d. bootstrap would
    scatter those weeks and produce an interval far too tight.

    A t-statistic on 1,642 overlapping-in-character daily observations is not a
    hypothesis test and is printed only as a scale. In the house style nothing is
    promoted because an interval excluded zero.
    """
    sessions = pd.to_datetime(curve["session"]).reset_index(drop=True)
    strategy = curve["equity"].reset_index(drop=True).pct_change().dropna().to_numpy()
    years = (sessions.iloc[-1] - sessions.iloc[0]).days / 365.25
    rng = np.random.default_rng(seed)
    targets = dict(benchmarks)
    targets["Nifty TR, volatility-matched"] = volatility_matched(
        benchmarks["Nifty 50 (total return)"], sessions,
        float(pd.Series(strategy).std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)))

    rows = []
    for name, level in targets.items():
        other = pd.Series(np.asarray(level)).pct_change().dropna().to_numpy()
        diff = strategy - other
        n = len(diff)
        mean = float(diff.mean())
        samples = np.empty(draws)
        for k in range(draws):
            picked = np.empty(n)
            filled, index = 0, rng.integers(n)
            while filled < n:
                length = min(rng.geometric(1.0 / mean_block), n - filled)
                take = (np.arange(index, index + length)) % n
                picked[filled:filled + length] = diff[take]
                filled += length
                index = rng.integers(n)
            samples[k] = picked.mean()
        lo, hi = np.percentile(samples, [2.5, 97.5])
        rows.append({
            "versus": name,
            "annualised_gap": mean * PERIODS_PER_YEAR,
            "boot_lo_annual": float(lo * PERIODS_PER_YEAR),
            "boot_hi_annual": float(hi * PERIODS_PER_YEAR),
            "t_naive": float(mean / (diff.std(ddof=1) / np.sqrt(n))),
            "days_ahead": float((diff > 0).mean()),
        })
    return pd.DataFrame(rows)


def capture(curve: pd.DataFrame, index_level: pd.Series) -> dict:
    """Upside and downside capture against the index, on daily moves."""
    s = pd.Series(curve["equity"].to_numpy()).pct_change().dropna()
    i = pd.Series(np.asarray(index_level)).pct_change().dropna()
    up, down = i > 0, i < 0
    return {
        "upside_capture": float(s[up].mean() / i[up].mean()),
        "downside_capture": float(s[down].mean() / i[down].mean()),
        "beta": float(np.cov(s, i)[0, 1] / np.var(i, ddof=1)),
        "correlation": float(np.corrcoef(s, i)[0, 1]),
    }


__all__ = ["capture", "compare", "edge_test", "metrics", "overlay_stats",
           "regime_table",
           "volatility_matched", "yearly"]
