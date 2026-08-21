"""What actually happened — computed only after the decisions are sealed.

This module is the only place in the package that touches the future, and it
is reached only through `replay.reveal()`, which refuses to run unless the
decisions on disk hash to what was committed. That ordering is the experiment.

ENTRY IS DATE D'S OPEN, AND THAT IS NOT ARBITRARY
The case is built as-of the open: indicators end at D-1 and the one date-D
price it may use is the 09:15 call-auction print. A decision made on that
information is tradeable at that same open, so the label enters there.
`frame.forward_return(entry="open")` is the existing, tested implementation —
it counts horizons in *market sessions* rather than rows, because
`groupby(symbol).shift(-h)` takes the h-th traded bar, which for a suspended
name can be a year away and can reach across a purged partition boundary.

EXCESS, NOT RAW
Every outcome is reported against the equal-weighted market over the identical
window. AGENTS.md is blunt about why: a wider stop lengthens the hold and
collects more market return, so raw payoff improves while excess worsens. It
also means the market baseline of MISSION §5 is the zero line of every contrast
in the report rather than an arm somebody has to remember to run.

MFE AND MAE ARE NOT DECORATION
A fixed-horizon return says where the price ended. It says nothing about
whether a position would have survived to get there. Two decisions with the
same D+10 return, one of which was 9% underwater on day three, are not the same
decision, and a discretionary judge that names a stop is making a claim about
exactly that.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..research_data import frame

logger = logging.getLogger(__name__)

RET_GUARD = 0.6          # a daily move beyond this is a bad print, as elsewhere
MKT_MIN_SYMBOLS = 50


class OutcomeError(RuntimeError):
    pass


def _market_curve(bars: pd.DataFrame) -> pd.Series:
    """Cumulative log return of the equal-weighted market, per session.

    Same guard and same breadth floor as `context._daily_returns` and
    `alpha_eval.backtest`, so the benchmark here is the same object those
    compute — a session with too few priced names is *unknown*, not flat, and a
    silent 0.0% benchmark makes every selector look like alpha.
    """
    b = bars.sort_values(["symbol", "date"])
    prev = b.groupby("symbol", sort=False)["close"].shift(1)
    r = (b["close"] / prev - 1.0)
    r = r.where(r.abs() < RET_GUARD)
    g = pd.DataFrame({"date": b["date"], "r": r}).groupby("date")["r"]
    mkt = g.mean().where(g.count() >= MKT_MIN_SYMBOLS)
    return mkt


def _mfe_mae(bars: pd.DataFrame, keys: pd.DataFrame, horizon: int
             ) -> pd.DataFrame:
    """Best and worst excursion from the entry open, over the next `horizon`.

    Measured from date D's open forward — the entry — so date D's own high and
    low are included and correctly so: the position exists for the whole
    session after the opening print.
    """
    b = bars.sort_values(["symbol", "date"])
    cal = np.sort(b["date"].unique())
    pos = pd.Series(np.arange(len(cal)), index=cal)

    op = b.pivot(index="date", columns="symbol", values="open")
    hi = b.pivot(index="date", columns="symbol", values="high")
    lo = b.pivot(index="date", columns="symbol", values="low")
    sym_ix = pd.Series(np.arange(len(op.columns)), index=op.columns)

    hv, lv, ov = hi.to_numpy(), lo.to_numpy(), op.to_numpy()
    i = pd.to_datetime(keys["date"]).map(pos).to_numpy()
    j = keys["symbol"].map(sym_ix).to_numpy()

    mfe = np.full(len(keys), np.nan)
    mae = np.full(len(keys), np.nan)
    ok = pd.notna(i) & pd.notna(j)
    for n in np.flatnonzero(ok):
        a, c = int(i[n]), int(j[n])
        end = min(a + horizon, len(cal) - 1)
        entry = ov[a, c]
        if not np.isfinite(entry) or entry <= 0:
            continue
        win_hi = hv[a:end + 1, c]
        win_lo = lv[a:end + 1, c]
        if np.all(~np.isfinite(win_hi)):
            continue
        mfe[n] = (np.nanmax(win_hi) / entry - 1.0) * 100.0
        mae[n] = (np.nanmin(win_lo) / entry - 1.0) * 100.0
    return pd.DataFrame({"mfe_pct": mfe, "mae_pct": mae}, index=keys.index)


def compute(keys: pd.DataFrame, horizons: tuple[int, ...], primary_horizon: int,
            version: str = "v1", bars: pd.DataFrame | None = None,
            entry_timing: str = "open") -> pd.DataFrame:
    """One row per case: raw return, market return, excess, MFE and MAE.

    `keys` needs `case_id`, `symbol` and `date`. Returns are in percent.
    """
    required = {"case_id", "symbol", "date"}
    if not required.issubset(keys.columns):
        raise OutcomeError(f"keys needs {sorted(required)}")
    if primary_horizon not in horizons:
        raise OutcomeError(
            f"primary_horizon {primary_horizon} is not among {horizons}")

    if bars is None:
        bars = frame.bars(version=version,
                          columns=["open", "high", "low", "close"])
    bars = bars.copy()
    bars["date"] = pd.to_datetime(bars["date"])

    out = keys.copy()
    out["date"] = pd.to_datetime(out["date"])

    mkt = _market_curve(bars)
    bad = mkt.isna()
    cum = np.log1p(mkt.fillna(0.0)).cumsum()
    bad_cum = bad.cumsum()
    pos = pd.Series(np.arange(len(cum.index)), index=cum.index)
    start = out["date"].map(pos)

    for h in horizons:
        out[f"ret_{h}d_pct"] = frame.forward_return(
            out, horizon=h, version=version, entry=entry_timing, bars=bars)

        end = (start + h).clip(upper=len(cum) - 1)
        ok = start.notna()
        bench = np.full(len(out), np.nan)
        si, ei = start[ok].to_numpy(int), end[ok].to_numpy(int)
        vals = np.expm1(cum.to_numpy()[ei] - cum.to_numpy()[si]) * 100.0
        # A window containing an unmeasured session has an unknown benchmark.
        vals[bad_cum.to_numpy()[ei] - bad_cum.to_numpy()[si] > 0] = np.nan
        bench[ok.to_numpy()] = vals
        out[f"mkt_{h}d_pct"] = bench
        out[f"excess_{h}d_pct"] = out[f"ret_{h}d_pct"] - bench

    exc = _mfe_mae(bars, out[["symbol", "date"]], primary_horizon)
    out["mfe_pct"] = exc["mfe_pct"]
    out["mae_pct"] = exc["mae_pct"]
    out["primary_excess_pct"] = out[f"excess_{primary_horizon}d_pct"]
    out["primary_ret_pct"] = out[f"ret_{primary_horizon}d_pct"]

    n_ok = int(out["primary_excess_pct"].notna().sum())
    logger.info("outcomes: %d of %d cases have a primary excess return",
                n_ok, len(out))
    return out


def to_jsonl(df: pd.DataFrame) -> str:
    return df.to_json(orient="records", lines=True, date_format="iso") + "\n"


def from_jsonl(text: str) -> pd.DataFrame:
    from io import StringIO
    return pd.read_json(StringIO(text), orient="records", lines=True)
