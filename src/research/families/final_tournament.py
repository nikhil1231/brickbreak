"""H059: one last, explicitly exploratory, executable F&O tournament.

This module is intentionally a leaf.  It reopens a few measured relationships
on the actual point-in-time stock-futures tape, searches a compact parameter
surface, and compares the best result with the best result produced when
outcomes are shuffled inside each entry session.  It is discovery machinery,
not a production strategy or a new path into parquet files.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ...core import config
from ...research_data import frame, repository
from ...research_data.pipelines import fo_universe
from .bulk_deals import events as bulk_events
from .bulk_deals.separation import _attach_h044_timing
from .opening_window.screener import ScreenConfig, run_screen
from .resilience import ResilienceConfig, build as build_resilience


OUT_DIR = config.METADATA_DIR / "research_store" / "h059"
HOLDS = (1, 3, 5, 10, 15, 20)
COSTS_BPS = (10.0, 20.0)


@dataclass
class PortfolioDef:
    """Sparse portfolio weights over the canonical futures row ids."""

    result_id: int
    family: str
    horizon: int
    row_ids: np.ndarray
    weights: np.ndarray
    n_sessions: int


def hh_mean(x: pd.Series, lag: int) -> dict[str, float | int]:
    """Mean and rectangular Hansen-Hodrick t for an overlapping portfolio."""
    v = pd.Series(x, dtype=float).dropna().to_numpy()
    n = len(v)
    if n < 3:
        return {"n": n, "mean": float("nan"), "t": float("nan")}
    e = v - v.mean()
    def covariance_sum(weights: Any, width: int) -> float:
        gamma = float(e @ e) / n
        for j in range(1, min(width, n - 1) + 1):
            gamma += 2.0 * weights(j) * float(e[j:] @ e[:-j]) / n
        return gamma

    # Overlapping h-session returns have an MA(h-1) structure.  Bartlett would
    # taper away the autocovariances that require the correction.  Rectangular
    # HH is the lab standard; if its non-PSD estimate is negative, use the same
    # twice-bandwidth Bartlett fallback as alpha_eval.diagnostics.
    gamma = covariance_sum(lambda _: 1.0, lag)
    if gamma <= 0:
        wide = min(2 * lag, n - 1)
        gamma = covariance_sum(lambda j: max(0.0, 1.0 - j / (wide + 1.0)), wide)
    se = np.sqrt(max(gamma, 1e-18) / n)
    return {"n": n, "mean": float(v.mean()), "t": float(v.mean() / se)}


def _session_targets(sessions: pd.DatetimeIndex, offset: int) -> pd.Series:
    values = np.full(len(sessions), np.datetime64("NaT"), dtype="datetime64[us]")
    if offset == 0:
        values[:] = sessions.to_numpy(dtype="datetime64[us]")
    elif offset < len(sessions):
        values[:-offset] = sessions.to_numpy(dtype="datetime64[us]")[offset:]
    return pd.Series(values, index=sessions)


def build_futures_frame(holds: Iterable[int] = HOLDS) -> pd.DataFrame:
    """Actual futures entries, same-contract exits, and lagged native features."""
    u = fo_universe.load().copy()
    u["session"] = pd.to_datetime(u["session"])
    u = u.sort_values(["symbol", "session"], kind="stable").reset_index(drop=True)
    u["_row_id"] = np.arange(len(u), dtype=np.int64)

    sessions = pd.DatetimeIndex(sorted(u["session"].unique()))
    ordinal = pd.Series(np.arange(len(sessions)), index=sessions)
    u["_session_i"] = u["session"].map(ordinal).astype(int)

    # The cash close is the underlying in the legacy derivatives era, where the
    # derivatives file does not report one.  It still enters through research_data.
    bars = frame.bars(
        partition=None, adjusted=True,
        columns=["symbol", "date", "close", "close_raw"],
        drop_purged=False,
    )
    bars["date"] = pd.to_datetime(bars["date"])
    bars = bars.sort_values(["symbol", "date"], kind="stable")
    bars["cash_ret_1d_bps"] = (
        bars.groupby("symbol", sort=False)["close"].pct_change(fill_method=None) * 1e4
    )
    cash = bars[["symbol", "date", "close_raw", "cash_ret_1d_bps"]].rename(
        columns={"date": "session"}
    )
    u = u.merge(cash, on=["symbol", "session"], how="left", validate="one_to_one")
    u = u.sort_values("_row_id", kind="stable").reset_index(drop=True)

    underlying = u["underlying_close"].where(u["underlying_close"].gt(0), u["close_raw"])
    u["basis_bps"] = (u["futures_close"] / underlying - 1.0) * 1e4
    g = u.groupby("symbol", sort=False)
    prev_i = g["_session_i"].shift(1)
    consecutive = prev_i.eq(u["_session_i"] - 1)
    same_contract = g["near_expiry"].shift(1).eq(u["near_expiry"])
    u["contract_ret_bps"] = (
        (u["futures_close"] / g["futures_close"].shift(1) - 1.0) * 1e4
    ).where(consecutive & same_contract)
    u["basis_change_bps"] = (u["basis_bps"] - g["basis_bps"].shift(1)).where(consecutive)

    lag_cols = [
        "basis_bps", "basis_change_bps", "contract_ret_bps", "cash_ret_1d_bps",
        "open_interest", "change_in_open_interest", "contracts", "lot_size",
        "traded_value",
    ]
    for col in lag_cols:
        u[f"lag_{col}"] = g[col].shift(1).where(consecutive)
    prior_oi = u["lag_open_interest"] - u["lag_change_in_open_interest"]
    u["lag_doi_frac"] = u["lag_change_in_open_interest"] / prior_oi.abs().clip(lower=1.0)
    u["lag_volume_oi"] = (
        u["lag_contracts"] * u["lag_lot_size"]
        / u["lag_open_interest"].abs().clip(lower=1.0)
    )
    u["lag_price_x_doi"] = u["lag_contract_ret_bps"] * u["lag_doi_frac"]

    # Tradability is decided entirely from lagged activity.
    tradable = fo_universe.tradable(u.drop(columns=[c for c in u.columns if c.startswith("lag_")]))
    u["tradable"] = tradable.sort_values("_row_id")["tradable"].to_numpy()

    reconciliation = repository.corporate_action_reconciliation().copy()
    reconciliation["apply_to_symbol"] = reconciliation["apply_to_symbol"].fillna(
        reconciliation["symbol"])
    action_dates = pd.concat([
        reconciliation[["apply_to_symbol", "ex_date"]].rename(
            columns={"apply_to_symbol": "symbol", "ex_date": "_action_date"}),
        reconciliation[["apply_to_symbol", "observed_date"]].rename(
            columns={"apply_to_symbol": "symbol", "observed_date": "_action_date"}),
    ], ignore_index=True).dropna().drop_duplicates()
    action_dates["_action_date"] = pd.to_datetime(action_dates["_action_date"])

    right = u[["symbol", "session", "near_expiry", "futures_close"]].copy()
    for h in sorted(set(int(v) for v in holds)):
        target = _session_targets(sessions, h - 1)
        left = u[["_row_id", "symbol", "session", "near_expiry", "futures_open"]].copy()
        left["_exit_session"] = left["session"].map(target)
        exit_ = right.rename(columns={
            "session": "_exit_session", "near_expiry": "_exit_expiry",
            "futures_close": "_exit_close",
        })
        joined = left.merge(exit_, on=["symbol", "_exit_session"], how="left", sort=False)
        joined = joined.sort_values("_row_id", kind="stable")
        valid = (
            joined["near_expiry"].eq(joined["_exit_expiry"])
            & joined["futures_open"].gt(0) & joined["_exit_close"].gt(0)
        )
        # A split/bonus changes the futures strike and lot size.  The raw price
        # ratio across that adjustment is not the position's P&L, so omit the
        # span until a contract-adjustment ledger exists rather than booking a
        # fictitious 50-90% move.  The 60% guard catches remaining bad prints.
        spans = joined.loc[valid, ["_row_id", "symbol", "session", "_exit_session"]]
        action_hits = spans.merge(action_dates, on="symbol", how="inner")
        action_hits = action_hits[
            action_hits["_action_date"].gt(action_hits["session"])
            & action_hits["_action_date"].le(action_hits["_exit_session"])
        ]
        if not action_hits.empty:
            valid &= ~joined["_row_id"].isin(set(action_hits["_row_id"]))
        raw = ((joined["_exit_close"] / joined["futures_open"] - 1.0) * 1e4).where(valid)
        raw = raw.where(raw.abs() < 6000.0)
        u[f"ret_{h}_bps"] = raw.to_numpy()
        market = u.groupby("session")[f"ret_{h}_bps"].transform("mean")
        u[f"xs_{h}_bps"] = u[f"ret_{h}_bps"] - market
    return u


def _leg(rows: pd.DataFrame, sign: float, scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    counts = rows.groupby("session")["_row_id"].transform("size").to_numpy(dtype=float)
    return rows["_row_id"].to_numpy(dtype=np.int64), sign * scale / counts


def _combine_legs(legs: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    return np.concatenate([x[0] for x in legs]), np.concatenate([x[1] for x in legs])


def _daily_from_weights(
    master: pd.DataFrame, row_ids: np.ndarray, weights: np.ndarray, horizon: int,
    outcome: str,
) -> pd.Series:
    col = f"{outcome}_{horizon}_bps"
    selected = master.iloc[row_ids][["session", col]].copy()
    selected["weighted"] = selected[col].to_numpy() * weights
    return selected.groupby("session")["weighted"].sum(min_count=1).dropna()


def _add_result(
    master: pd.DataFrame, defs: list[PortfolioDef], rows: list[dict[str, Any]],
    *, family: str, horizon: int, params: dict[str, Any],
    row_ids: np.ndarray, weights: np.ndarray,
) -> None:
    if len(row_ids) == 0:
        return
    dates = master.iloc[row_ids]["session"]
    n_sessions = int(dates.nunique())
    if n_sessions < 10:
        return
    raw = _daily_from_weights(master, row_ids, weights, horizon, "ret")
    xs = _daily_from_weights(master, row_ids, weights, horizon, "xs")
    common = raw.index.intersection(xs.index)
    raw, xs = raw.loc[common], xs.loc[common]
    if len(xs) < 10:
        return
    net20 = xs - 20.0
    stats = hh_mean(net20, max(horizon - 1, 0))
    midpoint = len(xs) // 2
    by_year = net20.groupby(net20.index.year).mean()
    result_id = len(rows)
    rows.append({
        "result_id": result_id, "family": family, "horizon": horizon,
        **params,
        "n_sessions": int(len(xs)), "n_selected_rows": int(len(row_ids)),
        "gross_raw_bps": float(raw.mean()), "gross_xs_bps": float(xs.mean()),
        "net10_xs_bps": float(xs.mean() - 10.0),
        "net20_xs_bps": float(xs.mean() - 20.0),
        "hh_t_net20": float(stats["t"]),
        "effective_n": int(len(xs) // max(horizon, 1)),
        "first_half_net20_bps": float(net20.iloc[:midpoint].mean()),
        "second_half_net20_bps": float(net20.iloc[midpoint:].mean()),
        "positive_years": int((by_year > 0).sum()),
        "years": int(len(by_year)),
        "positive_year_share": float((by_year > 0).mean()) if len(by_year) else np.nan,
    })
    defs.append(PortfolioDef(
        result_id=result_id, family=family, horizon=horizon,
        row_ids=row_ids, weights=weights.astype(np.float64), n_sessions=int(len(xs)),
    ))


STYLE_LEGS = {
    "long_top": (("top", 1.0, 1.0),),
    "short_top": (("top", -1.0, 1.0),),
    "long_bottom": (("bottom", 1.0, 1.0),),
    "short_bottom": (("bottom", -1.0, 1.0),),
    "ls_top_bottom": (("top", 1.0, 0.5), ("bottom", -1.0, 0.5)),
    "ls_bottom_top": (("bottom", 1.0, 0.5), ("top", -1.0, 0.5)),
}


def _rank_grid(
    master: pd.DataFrame, candidate: pd.DataFrame, *, family: str,
    scores: dict[str, str], horizons: Iterable[int], ks: Iterable[int],
    styles: Iterable[str], rows: list[dict[str, Any]], defs: list[PortfolioDef],
    fixed_params: dict[str, Any] | None = None,
) -> None:
    fixed_params = fixed_params or {}
    for score_name, score_col in scores.items():
        base = candidate.dropna(subset=[score_col]).copy()
        for h in horizons:
            d = base.dropna(subset=[f"ret_{h}_bps"]).copy()
            # `groupby.nlargest` dispatches one Python selection per session and
            # dominates the whole tournament on the native 300k-row panel.
            # Rank once, then slice every k from the same two integer vectors.
            d["_rank_top"] = d.groupby("session")[score_col].rank(
                method="first", ascending=False)
            d["_rank_bottom"] = d.groupby("session")[score_col].rank(
                method="first", ascending=True)
            d["_group_n"] = d.groupby("session")[score_col].transform("size")
            for k in ks:
                q = d[d["_group_n"] >= 2 * k]
                if q.empty:
                    continue
                top = q[q["_rank_top"] <= k]
                bottom = q[q["_rank_bottom"] <= k]
                legs = {"top": top, "bottom": bottom}
                for style in styles:
                    pieces = [_leg(legs[name], sign, scale) for name, sign, scale in STYLE_LEGS[style]]
                    row_ids, weights = _combine_legs(pieces)
                    _add_result(
                        master, defs, rows, family=family, horizon=h,
                        params={**fixed_params, "score": score_name, "k": k, "style": style},
                        row_ids=row_ids, weights=weights,
                    )


def build_bulk_candidates(master: pd.DataFrame) -> pd.DataFrame:
    deals = bulk_events.load(partition=None)
    ev = bulk_events.build_events(deals=deals)
    bars = repository.daily_bars(columns=["symbol", "date", "close_raw", "adj_factor"])
    bars["date"] = pd.to_datetime(bars["date"])
    reconciliation = repository.corporate_action_reconciliation()
    ev = _attach_h044_timing(ev, deals, bars, reconciliation)
    ev = ev[ev["deal_date_min"].eq(ev["deal_date_max"]) & ~ev["action_contaminated"]].copy()
    close = bars[["symbol", "date", "close_raw"]].rename(columns={"date": "deal_date_min"})
    ev = ev.merge(close, on=["symbol", "deal_date_min"], how="inner")
    ev["premium_pct"] = 100.0 * (ev["all_vwap"] / ev["close_raw"] - 1.0)
    ev = ev.rename(columns={"date": "session"})
    keep = ["symbol", "session", "premium_pct", "is_directional", "direction"]
    return master.merge(ev[keep], on=["symbol", "session"], how="inner")


def add_bulk_grid(
    master: pd.DataFrame, candidate: pd.DataFrame, rows: list[dict[str, Any]],
    defs: list[PortfolioDef],
) -> None:
    styles = tuple(STYLE_LEGS)
    for liquid_name, liquid in (("all", candidate), ("lagged_liquid", candidate[candidate["tradable"]])):
        for q in (0.20, 1 / 3, 0.50):
            lo, hi = liquid["premium_pct"].quantile([q, 1 - q])
            for h in (1, 3, 5):
                d = liquid.dropna(subset=[f"ret_{h}_bps", "premium_pct"])
                top, bottom = d[d["premium_pct"] >= hi], d[d["premium_pct"] <= lo]
                if top.empty or bottom.empty:
                    continue
                legs = {"top": top, "bottom": bottom}
                for style in styles:
                    pieces = [_leg(legs[name], sign, scale) for name, sign, scale in STYLE_LEGS[style]]
                    row_ids, weights = _combine_legs(pieces)
                    _add_result(
                        master, defs, rows, family="bulk_premium", horizon=h,
                        params={"score": "premium_pct", "tail": round(q, 4),
                                "liquidity": liquid_name, "style": style,
                                "cut_lo": float(lo), "cut_hi": float(hi)},
                        row_ids=row_ids, weights=weights,
                    )


def build_h026_candidates(master: pd.DataFrame) -> pd.DataFrame:
    panel = frame.load_daily_panel(partition=None, include_context=True, drop_purged=False)
    # F&O membership already supplies the economic size/liquidity universe.  Do
    # not reintroduce the present-day index-rank lookahead from the old screen.
    cfg = ScreenConfig(min_size_rank=0, max_size_rank=100_000, min_median_tv_cr=0.0)
    candidates, _ = run_screen(panel, cfg)
    candidates = candidates.dropna(subset=["rs_60d_vs_mkt", "sector_breadth"]).copy()
    candidates["rs60_rank"] = candidates.groupby("date")["rs_60d_vs_mkt"].rank(pct=True)
    candidates["breadth_rank"] = candidates.groupby("date")["sector_breadth"].rank(pct=True)
    candidates["h026_combo"] = (candidates["rs60_rank"] + candidates["breadth_rank"]) / 2.0
    candidates = candidates.rename(columns={"date": "session"})
    cols = ["symbol", "session", "sector", "rs_60d_vs_mkt",
            "sector_breadth", "h026_combo"]
    return master.merge(candidates[cols], on=["symbol", "session"], how="inner")


def build_resilience_candidates(master: pd.DataFrame, k: int) -> pd.DataFrame:
    cfg = ResilienceConfig(decline_windows=(k,), horizons=(1,))
    d = build_resilience(cfg, k=k, mkt_key="large", verbose=False)
    d = d.rename(columns={"date": "session"})
    return master.merge(
        d[["symbol", "session", "raw_win_pct", "mkt_win_pct"]],
        on=["symbol", "session"], how="inner",
    )


def add_resilience_grid(
    master: pd.DataFrame, rows: list[dict[str, Any]], defs: list[PortfolioDef],
) -> None:
    for lookback in (10, 20):
        candidate = build_resilience_candidates(master, lookback)
        per_date = candidate.groupby("session")["mkt_win_pct"].first()
        for decline_q in (0.10, 0.20, 0.30):
            cut = float(per_date.quantile(decline_q))
            d = candidate[candidate["mkt_win_pct"] <= cut]
            _rank_grid(
                master, d, family="drawdown_reversal",
                scores={f"raw_{lookback}d": "raw_win_pct"},
                horizons=(1, 3, 5), ks=(1, 3, 5, 10),
                styles=("long_bottom", "short_top", "ls_bottom_top"),
                rows=rows, defs=defs,
                fixed_params={"lookback": lookback, "decline_q": decline_q,
                              "decline_cut_pct": cut},
            )


def build_h039_candidates(master: pd.DataFrame) -> pd.DataFrame:
    panel = frame.load_daily_panel(
        partition=None, include_context=False,
        columns=["deliv_pct"], drop_purged=False,
    ).rename(columns={"date": "session"})
    d = master.merge(panel[["symbol", "session", "deliv_pct"]],
                     on=["symbol", "session"], how="inner")
    d["selloff_rank"] = d.groupby("session")["lag_cash_ret_1d_bps"].rank(pct=True)
    d["delivery_rank"] = d.groupby("session")["deliv_pct"].rank(pct=True)
    return d


def add_h039_grid(
    master: pd.DataFrame, candidate: pd.DataFrame, rows: list[dict[str, Any]],
    defs: list[PortfolioDef],
) -> None:
    for selloff_q in (0.10, 0.20, 0.30):
        sold = candidate[candidate["selloff_rank"] <= selloff_q]
        for delivery_q in (0.20, 0.40, 0.50):
            low = sold[sold["delivery_rank"] <= delivery_q]
            high = sold[sold["delivery_rank"] >= 1 - delivery_q]
            for h in (1, 3, 5):
                low_h = low.dropna(subset=[f"ret_{h}_bps"])
                high_h = high.dropna(subset=[f"ret_{h}_bps"])
                if len(low_h) == 0:
                    continue
                rid, w = _leg(low_h, 1.0)
                _add_result(
                    master, defs, rows, family="low_delivery_selloff", horizon=h,
                    params={"score": "low_delivery_after_selloff", "selloff_q": selloff_q,
                            "delivery_q": delivery_q, "style": "long_low_delivery"},
                    row_ids=rid, weights=w,
                )
                common_dates = np.intersect1d(low_h["session"].unique(), high_h["session"].unique())
                lo = low_h[low_h["session"].isin(common_dates)]
                hi = high_h[high_h["session"].isin(common_dates)]
                if len(lo) and len(hi):
                    rid, w = _combine_legs([_leg(lo, 1.0, 0.5), _leg(hi, -1.0, 0.5)])
                    _add_result(
                        master, defs, rows, family="low_delivery_selloff", horizon=h,
                        params={"score": "low_vs_high_delivery", "selloff_q": selloff_q,
                                "delivery_q": delivery_q, "style": "ls_low_high"},
                        row_ids=rid, weights=w,
                    )


def add_native_grid(
    master: pd.DataFrame, rows: list[dict[str, Any]], defs: list[PortfolioDef],
) -> None:
    features = {
        "basis": "lag_basis_bps",
        "basis_change": "lag_basis_change_bps",
        "price_change": "lag_contract_ret_bps",
        "doi": "lag_doi_frac",
        "volume_oi": "lag_volume_oi",
        "price_x_doi": "lag_price_x_doi",
        "days_to_expiry": "days_to_expiry",
    }
    d = master[master["tradable"]].copy()
    _rank_grid(
        master, d, family="futures_native", scores=features,
        horizons=(1, 3, 5), ks=(3, 10, 20), styles=tuple(STYLE_LEGS),
        rows=rows, defs=defs, fixed_params={"liquidity": "lagged_liquid"},
    )


def focused_stop_sweep(master: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    """Stops for the surviving H026-shaped entry, on one unchanged population.

    Every row can already complete a 20-session same-contract hold.  Shorter
    holds therefore use exactly the same entries rather than quietly changing
    the population as the contract-availability filter changes.  With no
    target there is no stop/target ordering ambiguity inside a daily bar.
    """
    d = candidate.dropna(subset=["sector_breadth", "ret_20_bps"]).copy()
    d["_n"] = d.groupby("session")["sector_breadth"].transform("size")
    d = d[d["_n"] >= 2]
    d["_rank"] = d.groupby("session")["sector_breadth"].rank(
        method="first", ascending=True)
    d["session_i"] = d["_session_i"]
    minimum = d.groupby("session")["sector_breadth"].transform("min")
    selections = {
        "one_name": d[d["_rank"] == 1],
        "all_weakest_ties": d[d["sector_breadth"].eq(minimum)],
    }
    paths = {
        symbol: group.set_index("_session_i").sort_index()
        for symbol, group in master.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for selection_name, selected in selections.items():
        for hold in (10, 15, 20):
            for stop_pct in (None, 3.0, 5.0, 7.5, 10.0, 15.0):
                trades: list[dict[str, Any]] = []
                for r in selected.itertuples(index=False):
                    path = paths[r.symbol].reindex(range(r.session_i, r.session_i + hold))
                    if len(path) != hold or path["futures_close"].isna().any():
                        continue
                    if not path["near_expiry"].eq(r.near_expiry).all():
                        continue
                    entry = float(r.futures_open)
                    stopped = False
                    if stop_pct is None:
                        exit_price = float(path.iloc[-1]["futures_close"])
                    else:
                        barrier = entry * (1.0 + stop_pct / 100.0)
                        hit = path[path["futures_high"] >= barrier]
                        if hit.empty:
                            exit_price = float(path.iloc[-1]["futures_close"])
                        else:
                            first = hit.iloc[0]
                            exit_price = max(barrier, float(first["futures_open"]))
                            stopped = True
                    trades.append({
                        "session": r.session,
                        "raw_bps": (entry - exit_price) / entry * 1e4,
                        "stopped": stopped,
                    })
                trade = pd.DataFrame(trades)
                if trade.empty:
                    continue
                daily = trade.groupby("session")["raw_bps"].mean().sort_index()
                stats = hh_mean(daily - 20.0, hold - 1)
                midpoint = len(daily) // 2
                rows.append({
                    "selection": selection_name, "hold": hold,
                    "stop_pct": stop_pct, "n_sessions": int(len(daily)),
                    "n_trades": int(len(trade)),
                    "gross_raw_bps": float(daily.mean()),
                    "net20_raw_bps": float(daily.mean() - 20.0),
                    "hh_t_net20": float(stats["t"]),
                    "effective_n": int(len(daily) // hold),
                    "stop_rate": float(trade["stopped"].mean()),
                    "first_half_net20_bps": float(daily.iloc[:midpoint].mean() - 20.0),
                    "second_half_net20_bps": float(daily.iloc[midpoint:].mean() - 20.0),
                })
    return pd.DataFrame(rows)


def _mark_neighbourhood(results: pd.DataFrame) -> pd.DataFrame:
    """Count positive nearby cells without claiming a formal topology."""
    out = results.copy()
    out["positive_neighbours"] = 0
    grouping = [c for c in ("family", "score", "style", "lookback", "decline_q",
                             "selloff_q", "delivery_q", "liquidity", "tail")
                if c in out.columns]
    for _, g in out.groupby(grouping, dropna=False):
        for idx, row in g.iterrows():
            near = g[
                (g["horizon"].sub(row["horizon"]).abs() <= 5)
                & (g.get("k", pd.Series(row.get("k", np.nan), index=g.index))
                   .sub(row.get("k", np.nan)).abs().fillna(0) <= 10)
                & (g.index != idx)
            ]
            out.loc[idx, "positive_neighbours"] = int((near["net20_xs_bps"] > 0).sum())
    return out


def permutation_maxima(
    master: pd.DataFrame, defs: list[PortfolioDef], n_perm: int = 500,
    seed: int = 59,
) -> pd.DataFrame:
    """Maximum net-20-bps fit after shuffling outcomes inside each session."""
    rng = np.random.default_rng(seed)
    horizons = sorted({d.horizon for d in defs})
    by_h = {h: [d for d in defs if d.horizon == h] for h in horizons}
    groups = [g.index.to_numpy(dtype=np.int64) for _, g in master.groupby("session", sort=False)]
    families = sorted({d.family for d in defs})
    packed: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    for h, definitions in by_h.items():
        row_ids = np.concatenate([d.row_ids for d in definitions])
        weights = np.concatenate([d.weights for d in definitions])
        owner = np.concatenate([
            np.full(len(d.row_ids), i, dtype=np.int32)
            for i, d in enumerate(definitions)
        ])
        n_sessions = np.array([d.n_sessions for d in definitions], dtype=float)
        fam = np.array([d.family for d in definitions], dtype=object)
        packed[h] = row_ids, weights, owner, n_sessions, fam
    records: list[dict[str, Any]] = []
    for p in range(n_perm):
        score_parts: list[np.ndarray] = []
        family_parts: list[np.ndarray] = []
        for h in horizons:
            values = master[f"xs_{h}_bps"].to_numpy(copy=True)
            for idx in groups:
                valid = idx[np.isfinite(values[idx])]
                if len(valid) > 1:
                    values[valid] = values[rng.permutation(valid)]
            row_ids, weights, owner, n_sessions, fam = packed[h]
            contribution = np.bincount(
                owner, weights=weights * values[row_ids], minlength=len(n_sessions)
            )
            score_parts.append(contribution / n_sessions - 20.0)
            family_parts.append(fam)
        arr = np.concatenate(score_parts)
        fam_arr = np.concatenate(family_parts)
        records.append({"permutation": p, "scope": "all", "max_net20_bps": float(np.nanmax(arr))})
        for family in families:
            records.append({
                "permutation": p, "scope": family,
                "max_net20_bps": float(np.nanmax(arr[fam_arr == family])),
            })
    return pd.DataFrame(records)


def summarise(results: pd.DataFrame, null: pd.DataFrame) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "exploratory_all_partitions",
        "n_configurations": int(len(results)),
        "families": {},
    }
    for family, group in results.groupby("family"):
        best = group.sort_values("net20_xs_bps", ascending=False).iloc[0]
        n = null[null["scope"] == family]["max_net20_bps"]
        p = (1 + int((n >= best["net20_xs_bps"]).sum())) / (len(n) + 1)
        eligible = group[
            (group["net20_xs_bps"] >= 10.0)
            & (group["n_sessions"] >= (50 if family == "bulk_premium" else 100))
            & (group["positive_year_share"] > 0.5)
            & (group["first_half_net20_bps"] > 0)
            & (group["second_half_net20_bps"] > 0)
            & (group["positive_neighbours"] >= 1)
        ]
        summary["families"][family] = {
            "n_configurations": int(len(group)),
            "best": {k: (None if pd.isna(v) else v.item() if hasattr(v, "item") else v)
                     for k, v in best.to_dict().items()},
            "null_median_max_bps": float(n.median()),
            "null_p95_max_bps": float(n.quantile(0.95)),
            "max_stat_p": float(p),
            "promotion_candidates": int(len(eligible)),
        }
    best = results.sort_values("net20_xs_bps", ascending=False).iloc[0]
    n = null[null["scope"] == "all"]["max_net20_bps"]
    summary["overall"] = {
        "best_result_id": int(best["result_id"]),
        "best_family": str(best["family"]),
        "best_net20_bps": float(best["net20_xs_bps"]),
        "null_median_max_bps": float(n.median()),
        "null_p95_max_bps": float(n.quantile(0.95)),
        "max_stat_p": float((1 + int((n >= best["net20_xs_bps"]).sum())) / (len(n) + 1)),
    }
    return summary


def run(n_perm: int = 500, seed: int = 59, out_dir: Path = OUT_DIR) -> dict[str, Any]:
    master = build_futures_frame()
    rows: list[dict[str, Any]] = []
    defs: list[PortfolioDef] = []

    bulk = build_bulk_candidates(master)
    add_bulk_grid(master, bulk, rows, defs)

    h026 = build_h026_candidates(master)
    _rank_grid(
        master, h026, family="relative_strength_screen",
        scores={"h026_combo": "h026_combo", "rs60": "rs_60d_vs_mkt",
                "sector_breadth": "sector_breadth"},
        horizons=HOLDS, ks=(1, 2, 3),
        styles=("long_top", "short_bottom", "ls_top_bottom"),
        rows=rows, defs=defs,
    )

    add_resilience_grid(master, rows, defs)
    add_h039_grid(master, build_h039_candidates(master), rows, defs)
    add_native_grid(master, rows, defs)

    results = _mark_neighbourhood(pd.DataFrame(rows))
    stops = focused_stop_sweep(master, h026)
    null = permutation_maxima(master, defs, n_perm=n_perm, seed=seed)
    summary = summarise(results, null)
    summary["inputs"] = {
        "futures_rows": int(len(master)),
        "futures_sessions": int(master["session"].nunique()),
        "first_session": str(master["session"].min().date()),
        "last_session": str(master["session"].max().date()),
        "bulk_candidates": int(len(bulk)),
        "h026_candidates": int(len(h026)),
        "permutations": n_perm,
        "seed": seed,
    }
    if not stops.empty:
        best_stop = stops.sort_values("net20_raw_bps", ascending=False).iloc[0]
        summary["focused_stop_sweep"] = {
            "warning": "post-selection optimisation on the same sample",
            "best": {k: (None if pd.isna(v) else v.item() if hasattr(v, "item") else v)
                     for k, v in best_stop.to_dict().items()},
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    results.sort_values("net20_xs_bps", ascending=False).to_csv(
        out_dir / "results.csv", index=False)
    null.to_csv(out_dir / "permutation_maxima.csv", index=False)
    stops.to_csv(out_dir / "focused_stop_sweep.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":  # pragma: no cover
    report = run()
    print(json.dumps(report, indent=2, default=str))
