"""Executable entry-timing follow-ups to H044.

H046 uses only information disclosed after the bulk-deal session closes and
enters at the next session's open. H047 is deliberately stopped at a coverage
gate until a broad full-session intraday dataset exists behind
``research_data.repository``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ....alpha_eval import diagnostics
from ....research_data import repository
from . import events, report
from .separation import COST_BPS, FLOORS, _attach_h044_timing

RET_GUARD = 0.6


class EntryTimingError(RuntimeError):
    pass


def _full_next_intraday(bars: pd.DataFrame) -> pd.DataFrame:
    """Attach the immediately next traded row before any liquidity filtering."""
    cols = ["symbol", "date", "open", "close", "close_raw", "vwap_raw",
            "adj_factor"]
    full = bars.sort_values(["symbol", "date"])[cols].copy()
    g = full.groupby("symbol", sort=False)
    for col in ("date", "open", "close", "adj_factor"):
        full[f"next_{col}"] = g[col].shift(-1)
    full["fwd"] = full["next_close"] / full["next_open"] - 1.0

    valid = (full["fwd"].replace([np.inf, -np.inf], np.nan).notna()
             & (full["fwd"].abs() < RET_GUARD))
    breadth = full.loc[valid].groupby("next_date")["fwd"].transform("size")
    market = full.loc[valid].groupby("next_date")["fwd"].transform("mean")
    full.loc[valid, "market_fwd"] = market.to_numpy()
    full.loc[valid, "market_breadth"] = breadth.to_numpy()
    full["excess_pct"] = 100.0 * (full["fwd"] - full["market_fwd"])
    return full


def _known_action_keys(reconciliation: pd.DataFrame,
                       spans: pd.DataFrame) -> set[int]:
    """Indices whose inclusive start/end interval contains a known action."""
    if reconciliation.empty or spans.empty:
        return set()
    ca = reconciliation.copy()
    ca["apply_to_symbol"] = ca["apply_to_symbol"].fillna(ca["symbol"])
    action_dates = pd.concat([
        ca[["apply_to_symbol", "ex_date"]].rename(
            columns={"apply_to_symbol": "symbol", "ex_date": "action_date"}),
        ca[["apply_to_symbol", "observed_date"]].rename(
            columns={"apply_to_symbol": "symbol", "observed_date": "action_date"}),
    ], ignore_index=True).dropna().drop_duplicates()
    cand = spans.reset_index().merge(action_dates, on="symbol", how="inner")
    hit = cand["action_date"].between(cand["start_date"], cand["end_date"])
    return set(cand.loc[hit, "index"].astype(int))


def _paired_spreads(event: pd.DataFrame, twin: pd.DataFrame,
                    cut_lo: float, cut_hi: float) -> pd.DataFrame:
    """One event-minus-exact-twin contrast per D+1 entry session."""
    def spread(frame: pd.DataFrame, feature: str, prefix: str) -> pd.DataFrame:
        top = frame[frame[feature] > cut_hi].groupby("entry_date")["excess_pct"].mean()
        bot = frame[frame[feature] <= cut_lo].groupby("entry_date")["excess_pct"].mean()
        return pd.concat({f"{prefix}_top": top, f"{prefix}_bot": bot}, axis=1)

    out = spread(event, "premium_pct", "event").join(
        spread(twin, "analogue_pct", "twin"), how="inner").dropna()
    out["event_spread_pct"] = out["event_top"] - out["event_bot"]
    out["twin_spread_pct"] = out["twin_top"] - out["twin_bot"]
    out["increment_pct"] = out["event_spread_pct"] - out["twin_spread_pct"]
    return out.reset_index()


def _portfolio_bps(event: pd.DataFrame, cut_lo: float,
                   cut_hi: float) -> dict[str, float]:
    """Equal-weight daily gross returns for the registered tradable arms."""
    long = event[event["premium_pct"] <= cut_lo].groupby("entry_date")["fwd"].mean()
    short = -event[event["premium_pct"] > cut_hi].groupby("entry_date")["fwd"].mean()
    paired = pd.concat({"long": long, "short": short}, axis=1).dropna()

    long_excess = event[event["premium_pct"] <= cut_lo].groupby(
        "entry_date")["excess_pct"].mean()
    short_excess = -event[event["premium_pct"] > cut_hi].groupby(
        "entry_date")["excess_pct"].mean()
    return {
        "long_gross_bps": 1e4 * float(long.mean()),
        "short_gross_bps": 1e4 * float(short.mean()),
        "long_excess_bps": 100.0 * float(long_excess.mean()),
        "short_excess_bps": 100.0 * float(short_excess.mean()),
        "long_short_gross_bps": 1e4 * float(paired.mean(axis=1).mean()),
    }


def h046_train(partition: str = "train",
               floors: tuple[float, ...] = FLOORS,
               extreme_caps: tuple[float | None, ...] = (None, 10.0),
               cost_bps: float = COST_BPS,
               *, bars: pd.DataFrame | None = None,
               deals: pd.DataFrame | None = None,
               reconciliation: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run the preregistered H046 exploration, and nothing beyond train."""
    if partition != "train":
        raise EntryTimingError("H046 is train-only; validation needs a frozen dispatch")

    if bars is None:
        bars = repository.daily_bars(columns=[
            "symbol", "date", "open", "close", "volume", "close_raw",
            "volume_raw", "vwap_raw", "adj_factor"])
    if deals is None:
        deals = events.load(partition="train")
    if reconciliation is None:
        reconciliation = repository.corporate_action_reconciliation()

    bars = bars.copy()
    bars["date"] = pd.to_datetime(bars["date"])
    next_panel = _full_next_intraday(bars)
    next_panel = next_panel[next_panel["market_breadth"] >= 50].copy()

    # One bulk event is keyed by the first session when the disclosure can be
    # traded. The feature, however, is explicitly attached to the deal date D.
    ev = events.build_events(deals=deals)
    ev = _attach_h044_timing(ev, deals, bars, reconciliation)
    ev = ev.rename(columns={"date": "entry_date"})
    ev = ev[ev["deal_date_min"].eq(ev["deal_date_max"])].copy()
    ev = ev.rename(columns={"deal_date_min": "date"})

    tape = next_panel.rename(columns={
        "next_date": "entry_date", "next_open": "entry_open",
        "next_close": "entry_close", "next_adj_factor": "entry_adj_factor",
    })
    tape_cols = [
        "symbol", "date", "entry_date", "close_raw", "vwap_raw",
        "adj_factor", "entry_adj_factor", "fwd", "excess_pct",
    ]
    ev = ev.merge(tape[tape_cols], on=["symbol", "date", "entry_date"], how="inner")
    ev["premium_pct"] = 100.0 * (ev["all_vwap"] / ev["close_raw"] - 1.0)
    ev["action_contaminated"] |= ~np.isclose(
        ev["adj_factor"], ev["entry_adj_factor"], equal_nan=False)

    event_keys = deals[["symbol", "deal_date"]].drop_duplicates().rename(
        columns={"deal_date": "date"})
    rows: list[dict[str, Any]] = []
    for floor in floors:
        liquid_d = report.context(bars, min_tv_cr=floor)[["symbol", "date"]]
        e0 = ev.merge(liquid_d, on=["symbol", "date"], how="inner")
        clean = e0[~e0["action_contaminated"]].copy()

        twin = tape[tape["date"].isin(set(clean["date"]))].merge(
            liquid_d, on=["symbol", "date"], how="inner")
        # The ordinary name must traverse the same market-session pair as the
        # event. A suspended name's later next print is not a D -> D+1 twin.
        session_map = clean[["date", "entry_date"]].drop_duplicates()
        session_map = session_map.groupby("date", as_index=False).filter(
            lambda x: x["entry_date"].nunique() == 1).drop_duplicates("date")
        session_map = session_map.rename(columns={"entry_date": "expected_entry_date"})
        twin = twin.merge(session_map, on="date", how="inner")
        twin = twin[twin["entry_date"].eq(twin["expected_entry_date"])]
        twin = twin.merge(event_keys.assign(_bulk=True),
                          on=["symbol", "date"], how="left")
        twin = twin[twin["_bulk"].isna()].copy()
        twin = twin[np.isclose(twin["adj_factor"], twin["entry_adj_factor"],
                               equal_nan=False)]
        twin["analogue_pct"] = 100.0 * (twin["vwap_raw"] / twin["close_raw"] - 1.0)
        spans = twin[["symbol", "date", "entry_date"]].rename(
            columns={"date": "start_date", "entry_date": "end_date"})
        twin = twin[~twin.index.to_series().isin(
            _known_action_keys(reconciliation, spans)).to_numpy()]

        for cap in extreme_caps:
            e = clean if cap is None else clean[clean["premium_pct"].abs() <= cap]
            t = twin if cap is None else twin[twin["analogue_pct"].abs() <= cap]
            cuts = e["premium_pct"].quantile([1 / 3, 2 / 3]).to_numpy()
            daily = _paired_spreads(e, t, float(cuts[0]), float(cuts[1]))
            stats = diagnostics.cluster_stats(
                daily["increment_pct"], daily["entry_date"], lags=0)
            portfolio = _portfolio_bps(e, float(cuts[0]), float(cuts[1]))
            rows.append({
                "floor_cr": floor,
                "extreme_cap_pct": cap,
                "cut_lo_pct": round(float(cuts[0]), 4),
                "cut_hi_pct": round(float(cuts[1]), 4),
                "n_events": int(len(e)),
                "n_twin": int(len(t)),
                "paired_sessions": int(len(daily)),
                "action_events_dropped": int(e0["action_contaminated"].sum()),
                "event_spread_bps": round(
                    100.0 * float(daily["event_spread_pct"].mean()), 1),
                "twin_spread_bps": round(
                    100.0 * float(daily["twin_spread_pct"].mean()), 1),
                "increment_bps": round(
                    100.0 * float(daily["increment_pct"].mean()), 1),
                "t_dk": stats["t"],
                **{k: round(v, 1) for k, v in portfolio.items()},
                "long_net_bps": round(portfolio["long_gross_bps"] - cost_bps, 1),
                "short_net_bps": round(portfolio["short_gross_bps"] - cost_bps, 1),
                "long_excess_net_bps": round(
                    portfolio["long_excess_bps"] - cost_bps, 1),
                "short_excess_net_bps": round(
                    portfolio["short_excess_bps"] - cost_bps, 1),
                "long_short_net_bps": round(
                    portfolio["long_short_gross_bps"] - cost_bps, 1),
            })
    return pd.DataFrame(rows)


def h046_verdict(table: pd.DataFrame) -> str:
    """Apply the preregistered primary, robustness and economic clauses."""
    primary = table[(table["floor_cr"] == 1.0)
                    & table["extreme_cap_pct"].isna()]
    if len(primary) != 1 or len(table) != len(FLOORS) * 2:
        raise EntryTimingError("H046 verdict needs every registered floor and cap")
    p = primary.iloc[0]
    statistical = p["increment_bps"] < 0 and p["t_dk"] <= -2.0
    robust = bool((table["increment_bps"] < 0).all())
    economic = max(p["long_excess_net_bps"], p["short_excess_net_bps"],
                   p["long_short_net_bps"]) > 0
    return "SURVIVES_TRAIN" if statistical and robust and economic else "REJECT"


def h047_coverage(partition: str = "train") -> dict[str, Any]:
    """Outcome-free gate: broad 15:15 data must exist behind the repository."""
    if partition != "train":
        raise EntryTimingError("H047 coverage gate is train-only")
    d = events.load(partition="train")
    keys = d[["symbol", "session"]].drop_duplicates()
    has_dataset = callable(getattr(repository, "intraday_bars", None))
    return {
        "partition": "train",
        "bulk_symbol_events": int(len(keys)),
        "bulk_symbols": int(keys["symbol"].nunique()),
        "repository_has_full_session_intraday": has_dataset,
        "scorable_symbol_events": None if has_dataset else 0,
        "status": "READY_FOR_COVERAGE_JOIN" if has_dataset else "DATA_GAP",
        "reason": ("named full-session intraday dataset is available"
                   if has_dataset else
                   "research_data exposes opening ticks only, not broad 15:15 history"),
    }


__all__ = ["EntryTimingError", "h046_train", "h046_verdict", "h047_coverage"]
