"""The screen that decides whether this family is worth a replay: does anything
*separate* the outcomes of a directional bulk-deal day?

WHAT THE FAMILY HAS, AND WHY IT IS NOT ENOUGH
The dispersion gate says outcomes after directional flow fan out at 1.233-1.240
against a null of 1.061 — about 3 sd, stable across every liquidity floor
tested. That is a statement about a second moment and it is not tradeable. A
family whose outcomes fan out but whose fanning is unpredictable is a family
that widens your distribution and pays you nothing for it.

So before any case is dispatched, the cheap question: **within those days, does
any simple coded feature sort the outcomes?** It costs compute and no sample,
and it has strictly more power than the replay it gates — 1,208 events on train
against the 500 cases a replay can afford. A null here is therefore not a
neutral result. It is a ceiling on what the replay could have found, which is
the argument for not commissioning it.

WHAT MAKES THIS DIFFERENT FROM EVERYTHING ELSE IN THE FAMILY
Every previous measurement was label-free or second-moment. This one reads the
sign of an outcome, which means it can be fitted, which means the design is
pre-registered in HYPOTHESES.md ("H043 pre-flight") and every configuration it
names is reported whatever it says. Eleven features, three liquidity floors,
two horizons, sixty-six readings, no subset promoted after the fact.

THE NULL IS BUILT, NOT ASSUMED
`_null` re-points each event at a random non-event name from the same session,
matched on the volatility, liquidity and volume-surprise quintile, and keeps
the event's features. Two hundred draws give the distribution of the statistic
when the features explain nothing — including, and this is the part a t-test
cannot do, the distribution of the **largest** absolute spread across all
eleven features. An eleven-feature screen must clear that, not the
single-feature band. The lab has already measured a corrected |t| over-
rejecting 13.3% of the time at this block count; a built null is the only kind
worth quoting.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ....alpha_eval import diagnostics
from ....research_data import repository
from . import events, report

logger = logging.getLogger(__name__)

FLOORS = (1.00, 0.25, 0.10)
HORIZONS = (1, 10)
N_NULL = 200
# Below this a tercile is not a group. Falls back to a median split, which is
# what a heavily tied feature (`dir_clients` is 1 for 85% of events) needs.
MIN_GROUP = 30
MIN_GROUP_SHARE = 0.05
# The round trip. A spread under this is not a finding whatever its t.
COST_BPS = 40.0

# Registered before the screen was run. Adding a twelfth after seeing these is
# a new test, not a longer version of this one.
FEATURES: dict[str, str] = {
    "net_flow_signed": "net directional quantity / trailing median raw volume",
    "net_flow_abs": "the same, unsigned — size of the position taken",
    "value_vs_turnover": "directional deal value / a normal day's turnover",
    "premium_pct": "deal VWAP against the session's raw close, %",
    "premium_signed": "premium signed by flow direction — who paid up",
    "dir_clients": "how many position-taking clients printed that day",
    "round_trip_share": "share of the day's bulk volume that was market making",
    "direction_sign": "+1 accumulation, -1 distribution",
    "volx": "session volume against the trailing median",
    "vol20": "trailing 20-session return volatility",
    "mom20": "trailing 20-session return",
}


class SeparationError(RuntimeError):
    pass


def _feature_frame(ev: pd.DataFrame, panel: pd.DataFrame,
                   liquid: pd.DataFrame) -> pd.DataFrame:
    """Directional events that landed in the liquid panel, with the eleven.

    Every column is knowable at the session's close, which is where the
    outcome window starts. `med_vol_raw`, `med_tv`, `vol20` and `mom20` are
    trailing windows ending at the session itself; the deal columns are the
    day's own prints.
    """
    d = ev[ev["is_directional"]].copy()
    ctx = liquid[["symbol", "date", "med_vol_raw", "mom20"]]
    d = d.merge(ctx, on=["symbol", "date"], how="left")
    d = d.merge(panel, on=["symbol", "date"], how="inner")

    d["net_flow_signed"] = d["dir_net_qty"] / d["med_vol_raw"]
    d["net_flow_abs"] = d["net_flow_signed"].abs()
    d["value_vs_turnover"] = d["dir_value"] / (d["med_tv"] * 1e7)
    d["premium_pct"] = d["deal_vs_close_pct"]
    d["direction_sign"] = np.sign(d["dir_net_qty"])
    d["premium_signed"] = d["premium_pct"] * d["direction_sign"]
    return d


def _split(x: pd.Series) -> tuple[np.ndarray, np.ndarray, str]:
    """Top and bottom third of a feature, or halves when it is too tied.

    Ranking by average percentile rather than `qcut` is deliberate: a feature
    that is 1 for 85% of events has no terciles, and `qcut` would either raise
    or silently hand back a group of forty. Ties land in one group together,
    which is the only honest thing to do with them.
    """
    r = x.rank(method="average", pct=True)
    top, bot = (r > 2 / 3).to_numpy(), (r <= 1 / 3).to_numpy()
    floor = max(MIN_GROUP, int(MIN_GROUP_SHARE * len(x)))
    if top.sum() >= floor and bot.sum() >= floor:
        return top, bot, "tercile"
    top, bot = (r > 0.5).to_numpy(), (r <= 0.5).to_numpy()
    if top.sum() >= MIN_GROUP and bot.sum() >= MIN_GROUP:
        return top, bot, "median"
    return top, bot, "unreadable"


def _contrast(y: np.ndarray, top: np.ndarray, bot: np.ndarray) -> np.ndarray:
    """Top-minus-bottom mean, written as a per-row series whose mean is it.

    `cluster_stats` estimates the variance of a *mean*, so the contrast is
    expressed as one — each row weighted +n/n_top or -n/n_bot — rather than as
    a difference of two means whose sessions overlap.
    """
    n = len(y)
    w = np.zeros(n)
    w[top] = n / max(top.sum(), 1)
    w[bot] = -n / max(bot.sum(), 1)
    return y * w


def _control_pool(panel: pd.DataFrame, ev: pd.DataFrame,
                  keys: tuple[str, ...]) -> dict[tuple, np.ndarray]:
    """Same-session, same-quintile non-events, as raw outcome arrays."""
    marked = panel.merge(ev[["symbol", "date"]].drop_duplicates().assign(_ev=True),
                         on=["symbol", "date"], how="left")
    ctl = marked[marked["_ev"].isna()]
    return {k: g["excess_pct"].to_numpy()
            for k, g in ctl.groupby(list(keys), sort=False)}


def _null(d: pd.DataFrame, panel: pd.DataFrame, n_null: int,
          seed: int) -> np.ndarray | None:
    """`n_null` x `n_events` of outcomes the events could have had for nothing.

    Each event is re-pointed at a random non-event name in the same session and
    the same volatility, liquidity and volume-surprise quintile — the matching
    `spread.check` already uses. The event's own features stay attached, so the
    resulting statistic is what an eleven-feature screen produces when the
    features explain nothing. Matching is relaxed one key at a time rather than
    dropping an event, because dropping the events that are hardest to match
    would build the null on the easy half of the sample.
    """
    tiers = [("date", "vol_q", "liq_q", "volx_q"), ("date", "vol_q", "liq_q"),
             ("date",)]
    pools = [_control_pool(panel, d, k) for k in tiers]

    chosen: list[np.ndarray] = []
    for row in d[["date", "vol_q", "liq_q", "volx_q"]].itertuples(index=False):
        for keys, pool in zip(tiers, pools):
            k = tuple(getattr(row, f) for f in keys)
            arr = pool.get(k[0] if len(k) == 1 else k)
            if arr is not None and len(arr):
                chosen.append(arr)
                break
        else:
            return None

    rng = np.random.default_rng(seed)
    sizes = np.array([len(a) for a in chosen])
    flat = np.concatenate(chosen)
    offs = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    idx = offs + (rng.random((n_null, len(sizes))) * sizes).astype(int)
    return flat[idx]


def _read_one(d: pd.DataFrame, feature: str, horizon: int,
              null: np.ndarray | None) -> dict[str, Any]:
    x = d[feature]
    ok = x.notna().to_numpy()
    sub = d[ok]
    if len(sub) < 3 * MIN_GROUP:
        return {"feature": feature, "n": int(len(sub)), "split": "unreadable"}

    top, bot, how = _split(x[ok])
    y = sub["excess_pct"].to_numpy()
    contrast = _contrast(y, top, bot)
    stats = diagnostics.cluster_stats(pd.Series(contrast), sub["date"],
                                      lags=max(horizon - 1, 0))

    absy = np.abs(y)
    disp = (absy[top].mean() / absy[bot].mean()) if absy[bot].mean() else np.nan

    out = {
        "feature": feature,
        "n": int(len(sub)),
        "n_top": int(top.sum()),
        "n_bot": int(bot.sum()),
        "split": how,
        "spread_bps": round(100 * stats["mean"], 1),
        "t_dk": stats["t"],
        "dispersion_top_over_bot": round(float(disp), 3),
    }
    if null is not None:
        nn = null[:, ok]
        ns = 100 * (nn[:, top].mean(axis=1) - nn[:, bot].mean(axis=1))
        # CENTRED, and the correction matters most for exactly the features
        # that look best. A control is matched on the volatility quintile, so
        # a volatility feature partly reproduces itself in its own null: the
        # top-tercile events draw high-volatility controls. Reading the raw
        # spread against a band assumed to be centred on zero would credit the
        # feature with what the matching already contains.
        mu = float(ns.mean())
        centred = ns - mu
        out["null_mean_bps"] = round(mu, 1)
        out["excess_bps"] = round(out["spread_bps"] - mu, 1)
        out["null_sd_bps"] = round(float(ns.std()), 1)
        out["null_p95_bps"] = round(float(np.percentile(np.abs(centred), 95)), 1)
        out["_null_spreads"] = centred
    return out


def screen(partition: str = "train", horizons: tuple[int, ...] = HORIZONS,
           floors: tuple[float, ...] = FLOORS, n_null: int = N_NULL,
           seed: int = 0) -> pd.DataFrame:
    """The whole pre-registered screen, every configuration, in one table.

    Reads `train` by default and nothing else. The dispersion work ran
    unpartitioned, which is defensible for a second moment; the first moment
    is read on the exploration partition or it is not read.
    """
    if partition not in ("train", "validation"):
        raise SeparationError(
            f"partition={partition!r}: this screen is exploration. The "
            f"confirmatory partitions are not a place to look for a feature.")

    bars = repository.daily_bars(
        columns=["symbol", "date", "close", "volume", "close_raw", "volume_raw"])
    rows: list[dict[str, Any]] = []
    for floor in floors:
        liquid = report.context(bars, min_tv_cr=floor)
        liquid["mom20"] = liquid.groupby("symbol", sort=False)["close"].transform(
            lambda s: s / s.shift(20) - 1.0)
        ev = events.build_events(bars=liquid, partition=partition).rename(
            columns={"session": "date"})
        for h in horizons:
            p = report.panel(liquid, h)
            d = _feature_frame(ev, p, liquid)
            if d.empty:
                raise SeparationError(f"floor={floor} h={h}: no events on the panel")
            null = _null(d, p, n_null, seed)
            reads = [_read_one(d, f, h, null) for f in FEATURES]

            spreads = np.vstack([r.pop("_null_spreads") for r in reads
                                 if "_null_spreads" in r])
            max_null = np.percentile(np.abs(spreads).max(axis=0), 95)
            for r in reads:
                rows.append({"floor_cr": floor, "horizon": h,
                             "null_max_p95_bps": round(float(max_null), 1), **r})
    return pd.DataFrame(rows)


def verdict(table: pd.DataFrame, cost_bps: float = COST_BPS) -> pd.DataFrame:
    """The pre-registered decision rule, applied to the table it was written for.

    A feature separates outcomes if it clears the eleven-feature null band, is
    the same sign at every liquidity floor, and is worth more than the round
    trip. All three. Anything less is a feature that looked good in one cell.
    """
    t = table[table["split"] != "unreadable"].copy()
    t["clears_null"] = t["excess_bps"].abs() > t["null_max_p95_bps"]
    t["clears_cost"] = t["excess_bps"].abs() > cost_bps

    sign = t.groupby(["feature", "horizon"])["excess_bps"].apply(
        lambda s: bool(np.sign(s).nunique() == 1))
    out = t.groupby(["feature", "horizon"]).agg(
        floors=("floor_cr", "count"),
        min_bps=("excess_bps", "min"),
        max_bps=("excess_bps", "max"),
        band_bps=("null_max_p95_bps", "max"),
        clears_null=("clears_null", "all"),
        clears_cost=("clears_cost", "all")).reset_index()
    out["stable_sign"] = out.set_index(["feature", "horizon"]).index.map(sign)
    out["separates"] = out["clears_null"] & out["clears_cost"] & out["stable_sign"]
    return out.sort_values(["horizon", "max_bps"], ascending=[True, False])


# ---------------------------------------------------------------------------
# is it about the deal, or about the stock?
# ---------------------------------------------------------------------------

# A feature that clears the band has one more question to answer, and it is
# the one that decides whether this family exists. `vol20` and `mom20` are
# properties of the *name*, not of the deal — every stock has them every day.
# `premium_pct` looks like a property of the deal and is not: NSE publishes
# bulk deals after the close, so the first tradable session is D+1 (100% of
# rows; 76% at a one-day gap), and the deal price is therefore compared
# against the *next* session's close. That makes it the negative of the move
# from the print to the close — a day-and-a-half of realised return, which
# every name in the panel has whether or not anyone printed a block in it.
# Its structural analogue is the previous session's VWAP against today's
# close, and if that carries the same spread on non-event names then the
# feature is the market's short-horizon momentum wearing a deal's clothes.
PANEL_ANALOGUES: dict[str, str] = {
    "vol20": "vol20",
    "volx": "volx",
    "mom20": "mom20",
    "premium_pct": "prev_vwap_vs_close",
}


def _with_analogues(liquid: pd.DataFrame) -> pd.DataFrame:
    g = liquid.groupby("symbol", sort=False)
    liquid = liquid.copy()
    liquid["mom20"] = g["close"].transform(lambda s: s / s.shift(20) - 1.0)
    # The deal-free twin of `premium_pct`: a price printed on the previous
    # session, read against the close the outcome window starts at. H044
    # supplies `prev_vwap_raw` before applying its liquidity floor: shifting a
    # filtered panel can silently jump over a below-floor session and turn a
    # one-session feature into a multi-session one.
    previous = (liquid["prev_vwap_raw"] if "prev_vwap_raw" in liquid.columns
                else g["vwap_raw"].shift(1))
    liquid["prev_vwap_vs_close"] = 100.0 * (
        previous / liquid["close_raw"] - 1.0)
    return liquid


def _previous_tape_columns(bars: pd.DataFrame) -> pd.DataFrame:
    """Previous *traded-session* values, computed before universe filtering."""
    b = bars.sort_values(["symbol", "date"]).copy()
    g = b.groupby("symbol", sort=False)
    b["prev_vwap_raw"] = g["vwap_raw"].shift(1)
    b["prev_adj_factor"] = g["adj_factor"].shift(1)
    return b


def panel_analogue(partition: str = "train",
                   horizons: tuple[int, ...] = HORIZONS,
                   floors: tuple[float, ...] = FLOORS) -> pd.DataFrame:
    """The same statistic, on the names that had no deal, on the same sessions.

    Restricted to sessions carrying a directional event and to non-event names,
    so the only thing that differs from the screen is the presence of a bulk
    deal. A feature that scores the same here scored nothing there.
    """
    bars = repository.daily_bars(
        columns=["symbol", "date", "close", "volume", "close_raw",
                 "volume_raw", "vwap_raw"])
    rows: list[dict[str, Any]] = []
    for floor in floors:
        liquid = _with_analogues(report.context(bars, min_tv_cr=floor))
        ev = events.build_events(bars=liquid, partition=partition).rename(
            columns={"session": "date"})
        d_ev = ev[ev["is_directional"]][["symbol", "date"]].drop_duplicates()
        for h in horizons:
            p = report.panel(liquid, h).merge(
                liquid[["symbol", "date", "mom20", "prev_vwap_vs_close"]],
                on=["symbol", "date"], how="left")
            p = p[p["date"].isin(set(d_ev["date"]))]
            non = p.merge(d_ev.assign(_ev=True), on=["symbol", "date"],
                          how="left")
            non = non[non["_ev"].isna()]
            for feature, analogue in PANEL_ANALOGUES.items():
                r = _read_one(non, analogue, h, None)
                rows.append({"floor_cr": floor, "horizon": h,
                             "screen_feature": feature, **r})
    return pd.DataFrame(rows)


def round_trip_arm(partition: str = "train",
                   horizons: tuple[int, ...] = HORIZONS,
                   floors: tuple[float, ...] = FLOORS,
                   features: tuple[str, ...] = ("premium_pct", "vol20"),
                   n_null: int = N_NULL, seed: int = 0) -> pd.DataFrame:
    """The same features on days whose only bulk activity was market making.

    This is the control the family already argues for. A round-trip day
    discloses no position: a prop desk crossed its own book and went home
    flat. It still carries a large print away from the close and it still
    carries the day's volatility, so any feature that scores the same here is
    not a feature about *directional flow* — at best it is a feature about
    bulk-deal days, and the increment H043 claims is not where it lives.

    The premium is read against `all_vwap`, which is what the round-trip
    population has in place of a directional VWAP: the same quantity, computed
    over the clients who ended flat.
    """
    bars = repository.daily_bars(
        columns=["symbol", "date", "close", "volume", "close_raw",
                 "volume_raw", "vwap_raw"])
    rows: list[dict[str, Any]] = []
    for floor in floors:
        liquid = _with_analogues(report.context(bars, min_tv_cr=floor))
        ev = events.build_events(bars=liquid, partition=partition).rename(
            columns={"session": "date"})
        rt = ev[~ev["is_directional"]].copy()
        rt = rt.merge(liquid[["symbol", "date", "close_raw", "med_vol_raw",
                              "mom20"]], on=["symbol", "date"], how="left")
        rt["premium_pct"] = 100.0 * (rt["all_vwap"] / rt["close_raw"] - 1.0)
        for h in horizons:
            p = report.panel(liquid, h)
            d = rt.merge(p, on=["symbol", "date"], how="inner")
            null = _null(d, p, n_null, seed)
            for f in features:
                r = _read_one(d, f, h, null)
                r.pop("_null_spreads", None)
                rows.append({"floor_cr": floor, "horizon": h, "arm": "round_trip",
                             **r})
    return pd.DataFrame(rows)


def magnitude_matched_panel(partition: str = "train",
                            horizons: tuple[int, ...] = HORIZONS,
                            floors: tuple[float, ...] = FLOORS) -> pd.DataFrame:
    """`prev_vwap_vs_close` on non-event names, cut at the *event's* thresholds.

    The plain analogue is not a fair twin: a bulk print deviates from the close
    by 10% where a whole session's VWAP deviates by 2%, so a linear effect
    would show up five times larger in the event set for no reason but scale.
    This applies the event set's own tercile boundaries to the deal-free panel,
    which asks the question that matters — *is it the print, or is it the size
    of the move?* — on a population where nothing printed.
    """
    bars = repository.daily_bars(
        columns=["symbol", "date", "close", "volume", "close_raw",
                 "volume_raw", "vwap_raw"])
    rows: list[dict[str, Any]] = []
    for floor in floors:
        liquid = _with_analogues(report.context(bars, min_tv_cr=floor))
        ev = events.build_events(bars=liquid, partition=partition).rename(
            columns={"session": "date"})
        d_ev = ev[ev["is_directional"]][["symbol", "date"]].drop_duplicates()
        for h in horizons:
            p = report.panel(liquid, h).merge(
                liquid[["symbol", "date", "prev_vwap_vs_close"]],
                on=["symbol", "date"], how="left")
            d = _feature_frame(ev, report.panel(liquid, h), liquid)
            cuts = d["deal_vs_close_pct"].quantile([1 / 3, 2 / 3]).to_numpy()

            pool = p[p["date"].isin(set(d_ev["date"]))]
            pool = pool.merge(d_ev.assign(_ev=True), on=["symbol", "date"],
                              how="left")
            pool = pool[pool["_ev"].isna()].dropna(
                subset=["prev_vwap_vs_close", "excess_pct"])
            top = (pool["prev_vwap_vs_close"] > cuts[1]).to_numpy()
            bot = (pool["prev_vwap_vs_close"] <= cuts[0]).to_numpy()
            y = pool["excess_pct"].to_numpy()
            stats = diagnostics.cluster_stats(
                pd.Series(_contrast(y, top, bot)), pool["date"],
                lags=max(h - 1, 0))
            rows.append({
                "floor_cr": floor, "horizon": h,
                "cut_lo_pct": round(float(cuts[0]), 2),
                "cut_hi_pct": round(float(cuts[1]), 2),
                "n": int(len(pool)), "n_top": int(top.sum()),
                "n_bot": int(bot.sum()),
                "spread_bps": round(100 * stats["mean"], 1), "t_dk": stats["t"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# H044: the print-to-entry move against its exact no-deal twin
# ---------------------------------------------------------------------------

def _attach_h044_timing(ev: pd.DataFrame, deals: pd.DataFrame,
                        bars: pd.DataFrame,
                        reconciliation: pd.DataFrame) -> pd.DataFrame:
    """Attach deal dates and quarantine corporate actions in the feature gap.

    H044 compares a raw deal print on D with the first-tradable close on D+1.
    A factor change anywhere in that interval manufactures the feature. The
    tape factor is the primary guard; the reconciliation table is a second
    guard for an action whose tape match is incomplete.
    """
    d = ev.copy()
    if "session" in d.columns and "date" not in d.columns:
        d = d.rename(columns={"session": "date"})

    span = deals.groupby(["symbol", "session"], sort=False).agg(
        deal_date_min=("deal_date", "min"),
        deal_date_max=("deal_date", "max")).reset_index().rename(
            columns={"session": "date"})
    d = d.merge(span, on=["symbol", "date"], how="left")

    factors = bars[["symbol", "date", "adj_factor"]].drop_duplicates(
        ["symbol", "date"])
    for source, target in (("deal_date_min", "factor_at_print_min"),
                           ("deal_date_max", "factor_at_print_max"),
                           ("date", "factor_at_entry")):
        f = factors.rename(columns={"date": source, "adj_factor": target})
        d = d.merge(f, on=["symbol", source], how="left")

    fs = d[["factor_at_print_min", "factor_at_print_max", "factor_at_entry"]]
    d["factor_unresolved"] = fs.isna().any(axis=1)
    d["factor_changed"] = (
        ~np.isclose(d["factor_at_print_min"], d["factor_at_entry"],
                    equal_nan=False)
        | ~np.isclose(d["factor_at_print_max"], d["factor_at_entry"],
                     equal_nan=False))

    d["known_action_in_gap"] = False
    if not reconciliation.empty:
        ca = reconciliation.copy()
        ca["apply_to_symbol"] = ca["apply_to_symbol"].fillna(ca["symbol"])
        action_dates = pd.concat([
            ca[["apply_to_symbol", "ex_date"]].rename(
                columns={"apply_to_symbol": "symbol", "ex_date": "action_date"}),
            ca[["apply_to_symbol", "observed_date"]].rename(
                columns={"apply_to_symbol": "symbol", "observed_date": "action_date"}),
        ], ignore_index=True).dropna().drop_duplicates()
        cand = d[["symbol", "date", "deal_date_min"]].reset_index().merge(
            action_dates, on="symbol", how="inner")
        hit = cand["action_date"].between(cand["deal_date_min"], cand["date"])
        hit_index = set(cand.loc[hit, "index"].astype(int))
        d["known_action_in_gap"] = d.index.to_series().isin(hit_index).to_numpy()

    d["action_contaminated"] = (
        d["factor_unresolved"] | d["factor_changed"] | d["known_action_in_gap"])
    return d


def _paired_h044_spreads(event: pd.DataFrame, twin: pd.DataFrame,
                         cut_lo: float, cut_hi: float) -> pd.DataFrame:
    """One equal-weight, fully paired H044 contrast per session."""
    e = event.dropna(subset=["premium_pct", "excess_pct", "date"]).copy()
    c = twin.dropna(subset=["prev_vwap_vs_close", "excess_pct", "date"]).copy()

    def _spread(frame: pd.DataFrame, feature: str, prefix: str) -> pd.DataFrame:
        top = frame[frame[feature] > cut_hi].groupby("date")["excess_pct"].mean()
        bot = frame[frame[feature] <= cut_lo].groupby("date")["excess_pct"].mean()
        return pd.concat({f"{prefix}_top": top, f"{prefix}_bot": bot}, axis=1)

    out = _spread(e, "premium_pct", "event").join(
        _spread(c, "prev_vwap_vs_close", "twin"), how="inner").dropna()
    out["event_spread_pct"] = out["event_top"] - out["event_bot"]
    out["twin_spread_pct"] = out["twin_top"] - out["twin_bot"]
    out["increment_pct"] = out["event_spread_pct"] - out["twin_spread_pct"]
    return out.reset_index()


def _h044_outcome_panel(bars: pd.DataFrame, liquid: pd.DataFrame,
                        leg: str = "close_to_close") -> pd.DataFrame:
    """H044 outcome on the full tape, never shifted after universe filtering.

    `close_to_close` reproduces the diagnostic claim, with the important fix
    that h=1 is the immediately next traded row. `next_intraday` is the first
    executable leg: the feature needs today's completed close, so the earliest
    honest entry is the next session's open.
    """
    if leg not in ("close_to_close", "next_intraday"):
        raise SeparationError(f"unknown H044 outcome leg {leg!r}")
    full = bars.sort_values(["symbol", "date"])[
        ["symbol", "date", "open", "close"]].copy()
    g = full.groupby("symbol", sort=False)
    full["next_open"] = g["open"].shift(-1)
    full["next_close"] = g["close"].shift(-1)
    if leg == "close_to_close":
        full["fwd"] = full["next_close"] / full["close"] - 1.0
    else:
        full["fwd"] = full["next_close"] / full["next_open"] - 1.0
    out = liquid.merge(full[["symbol", "date", "fwd"]],
                       on=["symbol", "date"], how="left").dropna(subset=["fwd"])
    out["excess_pct"] = 100.0 * (
        out["fwd"] - out.groupby("date")["fwd"].transform("mean"))
    return out


def h044_cleanup(partition: str = "train",
                 floors: tuple[float, ...] = FLOORS,
                 extreme_caps: tuple[float | None, ...] = (None, 10.0),
                 cost_bps: float = COST_BPS,
                 outcome_leg: str = "close_to_close") -> pd.DataFrame:
    """Registered final exploration of H044; deliberately train-only.

    The function has a partition argument solely so an attempted accidental
    confirmation fails loudly before any data is loaded. Validation needs a
    separate frozen dispatch after this exploration is interpreted.
    """
    if partition != "train":
        raise SeparationError(
            "H044 cleanup is train-only; freeze a separate validation dispatch")

    bars = _previous_tape_columns(repository.daily_bars(
        columns=["symbol", "date", "open", "close", "volume", "close_raw",
                 "volume_raw", "vwap_raw", "adj_factor"]))
    reconciliation = repository.corporate_action_reconciliation()
    raw_deals = events.load(partition="train")
    all_event_keys = raw_deals[["symbol", "session"]].drop_duplicates().rename(
        columns={"session": "date"})

    rows: list[dict[str, Any]] = []
    for floor in floors:
        liquid = _with_analogues(report.context(bars, min_tv_cr=floor))
        ev = events.build_events(deals=raw_deals, bars=liquid)
        ev = _attach_h044_timing(ev, raw_deals, bars, reconciliation)
        ev = ev.merge(liquid[["symbol", "date", "close_raw"]],
                      on=["symbol", "date"], how="inner")
        ev["premium_pct"] = 100.0 * (ev["all_vwap"] / ev["close_raw"] - 1.0)

        panel = _h044_outcome_panel(bars, liquid, leg=outcome_leg)
        ev = ev.merge(panel[["symbol", "date", "fwd", "excess_pct"]],
                      on=["symbol", "date"], how="inner")
        clean = ev[~ev["action_contaminated"]].copy()

        twin = panel[panel["date"].isin(set(clean["date"]))].merge(
            all_event_keys.assign(_bulk_event=True),
            on=["symbol", "date"], how="left")
        twin = twin[twin["_bulk_event"].isna()].copy()
        # The twin spans the previous traded session to this close. A changed
        # factor is the exact analogue of the event contamination above.
        twin = twin[np.isclose(twin["prev_adj_factor"], twin["adj_factor"],
                               equal_nan=False)]

        for cap in extreme_caps:
            e = clean if cap is None else clean[clean["premium_pct"].abs() <= cap]
            c = twin if cap is None else twin[twin["prev_vwap_vs_close"].abs() <= cap]
            cuts = e["premium_pct"].quantile([1 / 3, 2 / 3]).to_numpy()
            daily = _paired_h044_spreads(e, c, float(cuts[0]), float(cuts[1]))
            stats = diagnostics.cluster_stats(
                daily["increment_pct"], daily["date"], lags=0)
            increment_bps = 100.0 * float(daily["increment_pct"].mean())
            long_tail = e[e["premium_pct"] <= cuts[0]]
            short_tail = e[e["premium_pct"] > cuts[1]]
            rows.append({
                "outcome_leg": outcome_leg,
                "floor_cr": floor,
                "extreme_cap_pct": cap,
                "cut_lo_pct": round(float(cuts[0]), 4),
                "cut_hi_pct": round(float(cuts[1]), 4),
                "n_events": int(len(e)),
                "n_twin": int(len(c)),
                "paired_sessions": int(len(daily)),
                "action_events_dropped": int(ev["action_contaminated"].sum()),
                "event_spread_bps": round(
                    100.0 * float(daily["event_spread_pct"].mean()), 1),
                "twin_spread_bps": round(
                    100.0 * float(daily["twin_spread_pct"].mean()), 1),
                "increment_bps": round(increment_bps, 1),
                "t_dk": stats["t"],
                "long_gross_bps": round(1e4 * float(long_tail["fwd"].mean()), 1),
                "short_gross_bps": round(-1e4 * float(short_tail["fwd"].mean()), 1),
                "clears_cost": bool(increment_bps < -abs(cost_bps)),
            })
    return pd.DataFrame(rows)


def h044_verdict(table: pd.DataFrame) -> str:
    """Apply the registered all-cells rule without selecting a good cell."""
    required = {(float(f), c) for f in FLOORS for c in (None, 10.0)}
    seen = {(float(r.floor_cr), None if pd.isna(r.extreme_cap_pct)
             else float(r.extreme_cap_pct)) for r in table.itertuples()}
    if not required <= seen:
        raise SeparationError("H044 verdict needs every registered floor and cap")
    return "SURVIVES_TRAIN" if bool(table["clears_cost"].all()) else "REJECT"
