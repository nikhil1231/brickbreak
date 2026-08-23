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


def _h047_strata(frame: pd.DataFrame) -> pd.DataFrame:
    """D-known matching buckets shared by events and candidate controls."""
    out = frame.copy()
    out["volx"] = out["volume"] / out["med_vol"]
    for col, target in (("vol20", "vol_q"), ("med_tv", "liq_q"),
                        ("volx", "volx_q")):
        out[target] = out.groupby("date")[col].transform(
            lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    return out.dropna(subset=["vol_q", "liq_q", "volx_q"])


def _match_h047(event: pd.DataFrame, controls: pd.DataFrame,
                seed: int = 47) -> pd.DataFrame:
    """One exact-D, exact-stratum control per event, without replacement."""
    keys = ["date", "vol_q", "liq_q", "volx_q"]
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    grouped_controls = {key: group for key, group in controls.groupby(keys)}
    for key, egroup in event.sort_values(["date", "symbol"]).groupby(keys):
        cgroup = grouped_controls.get(key)
        if cgroup is None or cgroup.empty:
            continue
        egroup = egroup.sort_values("symbol").reset_index(drop=True)
        cgroup = cgroup.sort_values("symbol").iloc[
            rng.permutation(len(cgroup))].reset_index(drop=True)
        n = min(len(egroup), len(cgroup))
        for i in range(n):
            e, c = egroup.iloc[i], cgroup.iloc[i]
            rows.append({
                "event_symbol": e["symbol"],
                "control_symbol": c["symbol"],
                "deal_date": e["date"],
                "entry_date": e["entry_date"],
                "all_vwap": e["all_vwap"],
                "control_vwap_raw": c["vwap_raw"],
                "vol_q": int(e["vol_q"]), "liq_q": int(e["liq_q"]),
                "volx_q": int(e["volx_q"]),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out.insert(0, "pair_id", np.arange(len(out), dtype=int))
    return out


def build_h047_design(partition: str = "train", seed: int = 47,
                      *, save: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Freeze the preregistered 1-crore event/control pairs without outcomes."""
    if partition != "train":
        raise EntryTimingError("H047 design is train-only")
    bars = repository.daily_bars(columns=[
        "symbol", "date", "open", "close", "volume", "close_raw",
        "volume_raw", "vwap_raw", "adj_factor"])
    bars["date"] = pd.to_datetime(bars["date"])
    reconciliation = repository.corporate_action_reconciliation()
    raw_deals = events.load(partition="train")

    ev = events.build_events(deals=raw_deals)
    ev = _attach_h044_timing(ev, raw_deals, bars, reconciliation)
    ev = ev.rename(columns={"date": "entry_date"})
    ev = ev[ev["deal_date_min"].eq(ev["deal_date_max"])].rename(
        columns={"deal_date_min": "date"})

    full = bars.sort_values(["symbol", "date"])[
        ["symbol", "date", "adj_factor"]].copy()
    g = full.groupby("symbol", sort=False)
    full["entry_date"] = g["date"].shift(-1)
    full["entry_adj_factor"] = g["adj_factor"].shift(-1)
    ev = ev.merge(full, on=["symbol", "date", "entry_date"], how="inner")
    ev["action_contaminated"] |= ~np.isclose(
        ev["adj_factor"], ev["entry_adj_factor"], equal_nan=False)

    ctx = report.context(bars, min_tv_cr=1.0)
    ctx = _h047_strata(ctx)
    event = ev.merge(ctx[[
        "symbol", "date", "vol_q", "liq_q", "volx_q"]],
        on=["symbol", "date"], how="inner")
    event = event[~event["action_contaminated"]].copy()

    event_keys = raw_deals[["symbol", "deal_date"]].drop_duplicates().rename(
        columns={"deal_date": "date"})
    date_map = event[["date", "entry_date"]].drop_duplicates()
    date_map = date_map.groupby("date", as_index=False).filter(
        lambda x: x["entry_date"].nunique() == 1).drop_duplicates("date")
    controls = ctx[ctx["date"].isin(set(event["date"]))].merge(
        date_map, on="date", how="inner")
    controls = controls.merge(full, on=["symbol", "date", "entry_date"], how="inner",
                              suffixes=("", "_tape"))
    controls = controls[np.isclose(controls["adj_factor"],
                                   controls["entry_adj_factor"], equal_nan=False)]
    control_spans = controls[["symbol", "date", "entry_date"]].rename(
        columns={"date": "start_date", "entry_date": "end_date"})
    controls = controls[~controls.index.to_series().isin(
        _known_action_keys(reconciliation, control_spans)).to_numpy()]
    controls = controls.merge(event_keys.assign(_bulk=True),
                              on=["symbol", "date"], how="left")
    controls = controls[controls["_bulk"].isna()].copy()

    design = _match_h047(event, controls, seed=seed)
    if save:
        from ....research_data.pipelines import bulk_intraday
        bulk_intraday.save_design(design)
    report_out = {
        "eligible_events": int(len(event)),
        "matched_pairs": int(len(design)),
        "matched_share": float(len(design) / max(len(event), 1)),
        "entry_sessions": int(design["entry_date"].nunique()) if len(design) else 0,
        "event_symbols": int(design["event_symbol"].nunique()) if len(design) else 0,
        "control_symbols": int(design["control_symbol"].nunique()) if len(design) else 0,
        "seed": seed,
    }
    return design, report_out


def h047_requests(design: pd.DataFrame) -> pd.DataFrame:
    """Unique event, control and benchmark windows required by H047."""
    event = design[["event_symbol", "entry_date"]].rename(
        columns={"event_symbol": "symbol", "entry_date": "date"})
    control = design[["control_symbol", "entry_date"]].rename(
        columns={"control_symbol": "symbol", "entry_date": "date"})
    benchmark = design[["entry_date"]].drop_duplicates().rename(
        columns={"entry_date": "date"})
    benchmark["symbol"] = "__NIFTY__"
    return pd.concat([event, control, benchmark], ignore_index=True).drop_duplicates()


def _h047_1515_prices(windows: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Earliest registered minute open, quarantined against the raw daily tape."""
    if windows.empty:
        return pd.DataFrame(columns=["symbol", "entry_date", "entry_px"])
    w = windows.copy()
    w["timestamp"] = pd.to_datetime(w["timestamp"])
    minute = w["timestamp"].dt.hour * 60 + w["timestamp"].dt.minute
    w = w[(minute >= 15 * 60 + 15) & (minute <= 15 * 60 + 16)
          & w["open"].gt(0)].sort_values(["symbol", "timestamp"])
    w["entry_date"] = w["timestamp"].dt.normalize()
    first = w.drop_duplicates(["symbol", "entry_date"], keep="first")

    tape = bars[["symbol", "date", "low_raw", "high_raw"]].rename(
        columns={"date": "entry_date"})
    first = first.merge(tape, on=["symbol", "entry_date"], how="left")
    consistent = (first["open"] >= 0.98 * first["low_raw"])
    consistent &= (first["open"] <= 1.02 * first["high_raw"])
    first["unit_consistent"] = consistent.fillna(False)
    first["entry_px"] = first["open"].where(first["unit_consistent"])
    return first[["symbol", "entry_date", "entry_px", "unit_consistent"]]


def _h047_attach_exit(frame: pd.DataFrame, symbol_col: str,
                      bars: pd.DataFrame, reconciliation: pd.DataFrame,
                      prefix: str) -> pd.DataFrame:
    """Raw D+2 exit for the exact next market session, with action quarantine."""
    out = frame.copy()
    calendar = pd.Series(pd.to_datetime(bars["date"]).sort_values().unique())
    session_map = pd.DataFrame({"entry_date": calendar,
                                "exit_date": calendar.shift(-1)})
    out = out.merge(session_map, on="entry_date", how="left")
    d1 = bars[["symbol", "date", "adj_factor"]].rename(columns={
        "symbol": symbol_col, "date": "entry_date",
        "adj_factor": f"{prefix}_entry_factor"})
    d2 = bars[["symbol", "date", "open_raw", "close_raw", "adj_factor"]].rename(
        columns={"symbol": symbol_col, "date": "exit_date",
                 "open_raw": f"{prefix}_exit_open",
                 "close_raw": f"{prefix}_exit_close",
                 "adj_factor": f"{prefix}_exit_factor"})
    out = out.merge(d1, on=[symbol_col, "entry_date"], how="left")
    out = out.merge(d2, on=[symbol_col, "exit_date"], how="left")
    clean_factor = np.isclose(out[f"{prefix}_entry_factor"],
                              out[f"{prefix}_exit_factor"], equal_nan=False)
    spans = out[[symbol_col, "entry_date", "exit_date"]].rename(columns={
        symbol_col: "symbol", "entry_date": "start_date", "exit_date": "end_date"})
    known = out.index.to_series().isin(
        _known_action_keys(reconciliation, spans)).to_numpy()
    out[f"{prefix}_exit_clean"] = clean_factor & ~known
    return out


def h047_train(partition: str = "train", cost_bps: float = COST_BPS
               ) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score the frozen H047 design after the registered coverage gate."""
    if partition != "train":
        raise EntryTimingError("H047 score is train-only")
    design = repository.h047_design()
    if design.empty:
        raise EntryTimingError("H047 design is missing")
    bars = repository.daily_bars(columns=[
        "symbol", "date", "low_raw", "high_raw", "open_raw", "close_raw",
        "adj_factor"])
    bars["date"] = pd.to_datetime(bars["date"])
    reconciliation = repository.corporate_action_reconciliation()
    prices = _h047_1515_prices(repository.bulk_1515_bars(), bars)

    event_px = prices.rename(columns={"symbol": "event_symbol",
                                      "entry_px": "event_entry_px",
                                      "unit_consistent": "event_unit_consistent"})
    control_px = prices.rename(columns={"symbol": "control_symbol",
                                        "entry_px": "control_entry_px",
                                        "unit_consistent": "control_unit_consistent"})
    d = design.merge(event_px, on=["event_symbol", "entry_date"], how="left")
    d = d.merge(control_px, on=["control_symbol", "entry_date"], how="left")

    nifty_px = repository.bulk_1515_bars()
    nifty_px = nifty_px[nifty_px["symbol"].eq("__NIFTY__")].copy()
    if not nifty_px.empty:
        nifty_px["timestamp"] = pd.to_datetime(nifty_px["timestamp"])
        m = nifty_px["timestamp"].dt.hour * 60 + nifty_px["timestamp"].dt.minute
        nifty_px = nifty_px[(m >= 15 * 60 + 15) & (m <= 15 * 60 + 16)]
        nifty_px["entry_date"] = nifty_px["timestamp"].dt.normalize()
        nifty_px = nifty_px.sort_values("timestamp").drop_duplicates("entry_date")
        nifty_px = nifty_px[["entry_date", "open"]].rename(
            columns={"open": "nifty_entry_px"})
        d = d.merge(nifty_px, on="entry_date", how="left")
    else:
        d["nifty_entry_px"] = np.nan

    coverage = {
        "design_pairs": int(len(design)),
        "event_price_coverage": float(d["event_entry_px"].notna().mean()),
        "control_price_coverage": float(d["control_entry_px"].notna().mean()),
        "nifty_session_coverage": float(
            d.drop_duplicates("entry_date")["nifty_entry_px"].notna().mean()),
        "complete_feature_pairs": int(d[["event_entry_px", "control_entry_px"]]
                                      .notna().all(axis=1).sum()),
        "complete_feature_sessions": int(d.dropna(
            subset=["event_entry_px", "control_entry_px"])["entry_date"].nunique()),
        "event_unit_mismatches": int(d["event_unit_consistent"].eq(False).sum()),
        "control_unit_mismatches": int(d["control_unit_consistent"].eq(False).sum()),
    }

    d = _h047_attach_exit(d, "event_symbol", bars, reconciliation, "event")
    # Reuse the exact same market-session exit date when attaching the control.
    d = d.drop(columns=["exit_date"])
    d = _h047_attach_exit(d, "control_symbol", bars, reconciliation, "control")
    d = d[d["event_exit_clean"] & d["control_exit_clean"]].copy()

    nd = repository.bulk_1515_nifty_daily().copy()
    if nd.empty:
        raise EntryTimingError("H047 NIFTY daily benchmark is missing")
    nd["exit_date"] = pd.to_datetime(nd["timestamp"]).dt.normalize()
    nd = nd[["exit_date", "open", "close"]].drop_duplicates("exit_date").rename(
        columns={"open": "nifty_exit_open", "close": "nifty_exit_close"})
    d = d.merge(nd, on="exit_date", how="left")

    d["premium_pct"] = 100.0 * (d["all_vwap"] / d["event_entry_px"] - 1.0)
    d["analogue_pct"] = 100.0 * (
        d["control_vwap_raw"] / d["control_entry_px"] - 1.0)
    d["event_primary"] = d["event_exit_open"] / d["event_entry_px"] - 1.0
    d["control_primary"] = d["control_exit_open"] / d["control_entry_px"] - 1.0
    d["nifty_primary"] = d["nifty_exit_open"] / d["nifty_entry_px"] - 1.0
    d["event_secondary"] = d["event_exit_close"] / d["event_entry_px"] - 1.0
    d["control_secondary"] = d["control_exit_close"] / d["control_entry_px"] - 1.0
    d["nifty_secondary"] = d["nifty_exit_close"] / d["nifty_entry_px"] - 1.0

    rows: list[dict[str, Any]] = []
    for outcome, lags in (("primary", 0), ("secondary", 1)):
        base = d.dropna(subset=[
            "premium_pct", "analogue_pct", f"event_{outcome}",
            f"control_{outcome}", f"nifty_{outcome}"]).copy()
        base["event_excess"] = 100.0 * (
            base[f"event_{outcome}"] - base[f"nifty_{outcome}"])
        base["control_excess"] = 100.0 * (
            base[f"control_{outcome}"] - base[f"nifty_{outcome}"])
        for cap in (None, 10.0):
            x = base if cap is None else base[base["premium_pct"].abs() <= cap]
            c = base if cap is None else base[base["analogue_pct"].abs() <= cap]
            cuts = x["premium_pct"].quantile([1 / 3, 2 / 3]).to_numpy()
            ef = x[["entry_date", "premium_pct", "event_excess"]].rename(
                columns={"event_excess": "excess_pct"})
            cf = c[["entry_date", "analogue_pct", "control_excess"]].rename(
                columns={"control_excess": "excess_pct"})
            daily = _paired_spreads(ef, cf, float(cuts[0]), float(cuts[1]))
            stats = diagnostics.cluster_stats(
                daily["increment_pct"], daily["entry_date"], lags=lags)
            pf = x[["entry_date", "premium_pct", f"event_{outcome}",
                    "event_excess"]].rename(columns={
                        f"event_{outcome}": "fwd", "event_excess": "excess_pct"})
            portfolio = _portfolio_bps(pf, float(cuts[0]), float(cuts[1]))
            rows.append({
                "outcome": outcome, "extreme_cap_pct": cap,
                "cut_lo_pct": round(float(cuts[0]), 4),
                "cut_hi_pct": round(float(cuts[1]), 4),
                "n_events": int(len(x)), "n_controls": int(len(c)),
                "paired_sessions": int(len(daily)),
                "event_spread_bps": round(
                    100.0 * float(daily["event_spread_pct"].mean()), 1),
                "twin_spread_bps": round(
                    100.0 * float(daily["twin_spread_pct"].mean()), 1),
                "increment_bps": round(
                    100.0 * float(daily["increment_pct"].mean()), 1),
                "t_dk": stats["t"],
                **{k: round(v, 1) for k, v in portfolio.items()},
                "long_excess_net_bps": round(
                    portfolio["long_excess_bps"] - cost_bps, 1),
                "short_excess_net_bps": round(
                    portfolio["short_excess_bps"] - cost_bps, 1),
                "long_short_net_bps": round(
                    portfolio["long_short_gross_bps"] - cost_bps, 1),
            })
    return pd.DataFrame(rows), coverage


def h047_verdict(table: pd.DataFrame, coverage: dict[str, Any]) -> str:
    primary = table[(table["outcome"] == "primary")
                    & table["extreme_cap_pct"].isna()]
    capped = table[(table["outcome"] == "primary")
                   & table["extreme_cap_pct"].eq(10.0)]
    if len(primary) != 1 or len(capped) != 1:
        raise EntryTimingError("H047 verdict needs both registered primary rows")
    p, c = primary.iloc[0], capped.iloc[0]
    covered = (coverage["event_price_coverage"] >= 0.70
               and coverage["control_price_coverage"] >= 0.70
               and coverage["complete_feature_sessions"] >= 300)
    statistical = p["increment_bps"] < 0 and p["t_dk"] <= -2.0
    robust = c["increment_bps"] < 0
    economic = max(p["long_excess_net_bps"], p["short_excess_net_bps"],
                   p["long_short_net_bps"]) > 0
    return "SURVIVES_TRAIN" if covered and statistical and robust and economic else "REJECT"


__all__ = [
    "EntryTimingError", "build_h047_design", "h046_train", "h046_verdict",
    "h047_coverage", "h047_requests", "h047_train", "h047_verdict",
]
