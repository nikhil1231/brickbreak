"""Causality tests for `src.research_data.pipelines.context`.

The point of every test here is the same one: a feature dated D must not change
when sessions after D are appended. That bug has shipped twice in this project
already — once in the screen (H015, which could *invert* a result rather than
merely inflate it) and once in `behaviour.time_above_open_frac` — so the rule in
`AGENTS.md` is that the test is written before the feature is trusted, not after
it is doubted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research_data.pipelines import context


def _bars(n: int = 120, seed: int = 0, symbols=("AAA", "BBB")) -> pd.DataFrame:
    """A small synthetic panel with a real trend and a real base."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    out = []
    for k, s in enumerate(symbols):
        r = rng.normal(0.0006, 0.015, n)
        close = 100 * np.exp(np.cumsum(r)) * (1 + 0.1 * k)
        high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
        low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
        openp = np.concatenate([[close[0]], close[:-1]]) * (
            1 + rng.normal(0, 0.004, n))
        out.append(pd.DataFrame({
            "symbol": s, "date": dates, "open": openp,
            "high": np.maximum.reduce([high, openp, close]),
            "low": np.minimum.reduce([low, openp, close]), "close": close}))
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------
# the central property
# --------------------------------------------------------------------------

def test_breakout_location_ignores_everything_after_the_date():
    """Appending later sessions must not move a single value on an earlier date.

    This is the direct analogue of `test_features_at_t_ignore_everything_after_t`
    for the daily side, and it is the test that would have caught H015.
    """
    full = _bars(120)
    cut = full[full["date"] < full["date"].unique()[90]]

    a = context.breakout_location(cut).set_index(["symbol", "date"])
    b = context.breakout_location(full).set_index(["symbol", "date"])
    common = a.index.intersection(b.index)
    assert len(common) > 100

    for col in a.columns:
        x, y = a.loc[common, col], b.loc[common, col]
        both = x.notna() & y.notna()
        assert x.isna().equals(y.isna()), f"{col} changed which rows are NaN"
        assert np.allclose(x[both].astype(float), y[both].astype(float)), (
            f"{col} on an earlier date changed when later sessions were added")


def test_market_regime_ignores_everything_after_the_date():
    full = _bars(160, symbols=tuple(f"S{i}" for i in range(60)))
    cut = full[full["date"] < full["date"].unique()[120]]

    a = context.market_regime(cut).set_index("date")
    b = context.market_regime(full).set_index("date")
    common = a.index.intersection(b.index)
    assert len(common) > 100

    for col in a.columns:
        if col in ("mkt_regime",):
            assert (a.loc[common, col].astype(str)
                    == b.loc[common, col].astype(str)).all()
            continue
        x, y = a.loc[common, col], b.loc[common, col]
        both = x.notna() & y.notna()
        assert np.allclose(x[both].astype(float), y[both].astype(float)), (
            f"{col} changed when later sessions were added")


# --------------------------------------------------------------------------
# the levels are the previous sessions', and the open is date D's
# --------------------------------------------------------------------------

def test_prior_high_excludes_date_d():
    """A single enormous high on date D must not appear in date D's own level.

    If it did, `open_vs_high_20_pct` would be measuring the open against a high
    the stock had not printed yet — which is precisely the breakout-location
    version of the screener bug.
    """
    b = _bars(80, symbols=("AAA",))
    d0 = b["date"].unique()[60]
    spike = b.copy()
    spike.loc[spike["date"] == d0, "high"] *= 5.0

    base = context.breakout_location(b)
    hit = context.breakout_location(spike)
    row_b = base[base["date"] == d0].iloc[0]
    row_h = hit[hit["date"] == d0].iloc[0]
    assert row_b["prior_high_20"] == pytest.approx(row_h["prior_high_20"])

    # And it must appear on the *next* session, or the window is not rolling.
    d1 = b["date"].unique()[61]
    assert (hit[hit["date"] == d1].iloc[0]["prior_high_20"]
            > base[base["date"] == d1].iloc[0]["prior_high_20"])


def test_open_vs_level_uses_date_d_open():
    """Date D's opening print is the one date-D price allowed in, per `asof`."""
    b = _bars(80, symbols=("AAA",))
    d0 = b["date"].unique()[60]
    moved = b.copy()
    moved.loc[moved["date"] == d0, "open"] *= 1.10

    a = context.breakout_location(b)
    c = context.breakout_location(moved)
    x = a[a["date"] == d0].iloc[0]["open_vs_high_20_pct"]
    y = c[c["date"] == d0].iloc[0]["open_vs_high_20_pct"]
    assert y > x + 5.0, "the open must feed the location feature"


def test_days_since_high_counts_backwards_from_the_previous_session():
    """A level set on D-1 is one session old; the age must never be negative."""
    b = _bars(80, symbols=("AAA",))
    out = context.breakout_location(b).dropna(subset=["days_since_high_20"])
    assert (out["days_since_high_20"] >= 0).all()
    assert (out["days_since_high_20"] <= 20).all()


# --------------------------------------------------------------------------
# regime construction
# --------------------------------------------------------------------------

def test_trend_efficiency_separates_a_straight_line_from_a_round_trip():
    """The measure has to do the one job it was added for.

    Two markets with the same 20-day return, one monotone and one thrashing.
    If `mkt_trend_eff` cannot tell them apart, no regime claim in this phase
    means anything.
    """
    n = 80
    dates = pd.bdate_range("2024-01-01", periods=n)
    straight = np.full(n, 0.002)
    thrash = np.where(np.arange(n) % 2 == 0, 0.032, -0.028)

    def frame(rets):
        rows = []
        for s in [f"S{i}" for i in range(60)]:
            close = 100 * np.exp(np.cumsum(rets))
            rows.append(pd.DataFrame({
                "symbol": s, "date": dates, "open": close, "high": close,
                "low": close, "close": close}))
        return pd.concat(rows, ignore_index=True)

    a = context.market_regime(frame(straight))["mkt_trend_eff"].dropna()
    b = context.market_regime(frame(thrash))["mkt_trend_eff"].dropna()
    assert a.mean() > 0.95, "a monotone advance must score near 1"
    assert b.mean() < 0.35, "a round trip must not look like a trend"


def test_market_return_is_nan_when_too_few_names_are_priced():
    """An unmeasured session is unknown, not flat — the `payoff.py` rule."""
    b = _bars(60, symbols=("AAA", "BBB"))          # 2 names, below the floor
    m = context.market_regime(b)
    assert m["mkt_ret_20d"].isna().all()
    assert (m["mkt_regime"].astype(str) == "unknown").all()


def test_relative_strength_differences_are_aligned_in_time():
    """Stock minus market only means something if both sides end on D-1."""
    bars = _bars(160, symbols=tuple(f"S{i}" for i in range(60)))
    mkt = context.market_regime(bars)
    metrics = pd.DataFrame({
        "symbol": "S0", "date": mkt["date"], "sector": "X",
        "ret_20d": 5.0, "ret_60d": 9.0})
    sector = pd.DataFrame({"sector": "X", "date": mkt["date"],
                           "mean_ret": 0.001, "n_members": 10})
    rs = context.relative_strength(metrics, mkt, sector)
    joined = rs.merge(mkt[["date", "mkt_ret_20d"]], on="date")
    ok = joined["rs_20d_vs_mkt"].notna()
    assert ok.sum() > 50
    assert np.allclose(joined.loc[ok, "rs_20d_vs_mkt"],
                       5.0 - joined.loc[ok, "mkt_ret_20d"])


# --------------------------------------------------------------------------
# the investable benchmark (2026-08-29)
# --------------------------------------------------------------------------

def test_investable_index_ignores_everything_after_the_date():
    """Same rule as every other column: appending sessions cannot move history.

    `_investable_index` carries state across sessions in a Python loop, which is
    exactly the shape that leaks a future value if the loop is ever restructured.
    """
    bars = _bars(n=200, symbols=("AAA", "BBB", "CCC"))
    cut = bars["date"].unique()[150]
    full = context.market_regime(bars, context.ContextConfig(mkt_min_symbols=2))
    early = context.market_regime(bars[bars["date"] <= cut],
                                  context.ContextConfig(mkt_min_symbols=2))
    m = early.merge(full, on="date", suffixes=("_e", "_f"))
    d = (m["mkt_index_investable_e"] - m["mkt_index_investable_f"]).abs()
    assert d.max() < 1e-12, f"investable index moved by {d.max()}"


def test_investable_index_pays_a_cost_and_the_free_index_does_not():
    """The whole reason the column exists: it is charged and `mkt_index` is not.

    With the rebalance clock set to every session, the two indices differ by
    nothing but the cost, so the investable one must sit strictly below.
    """
    bars = _bars(n=120, symbols=("AAA", "BBB", "CCC"))
    cfg = context.ContextConfig(mkt_min_symbols=2, bench_rebal_sessions=1,
                                bench_cost_pct_round_trip=0.40)
    out = context.market_regime(bars, cfg).dropna(
        subset=["mkt_index", "mkt_index_investable"])
    assert (out["mkt_index_investable"] <= out["mkt_index"] + 1e-12).all()
    assert out["mkt_index_investable"].iloc[-1] < out["mkt_index"].iloc[-1]

    free = context.market_regime(
        bars, context.ContextConfig(mkt_min_symbols=2, bench_rebal_sessions=1,
                                    bench_cost_pct_round_trip=0.0)
    ).dropna(subset=["mkt_index", "mkt_index_investable"])
    # At zero cost and a nightly clock the two constructions earn the same
    # thing. Their *levels* differ by one session: `mkt_index` books the first
    # session's return, while the investable one buys at that session's close.
    # So the comparison is on returns, not levels.
    a = np.diff(np.log(free["mkt_index"].to_numpy()))
    b = np.diff(np.log(free["mkt_index_investable"].to_numpy()))
    assert np.allclose(a, b, atol=1e-12)


# --------------------------------------------------------------------------
# the snapshot-label check that H059 needed and did not have (2026-08-29)
# --------------------------------------------------------------------------

def test_snapshot_labels_are_rejected():
    """A label constant per symbol across years is a snapshot, not a panel."""
    from src.research_data.pipelines import sector as sector_mod
    dates = pd.bdate_range("2020-01-01", periods=400)
    frozen = pd.DataFrame({
        "symbol": np.repeat(["AAA", "BBB", "CCC"], len(dates)),
        "date": np.tile(dates, 3),
        "sector": np.repeat(["Banks", "Pharma", "Banks"], len(dates)),
    })
    with pytest.raises(ValueError, match="present-day snapshot"):
        sector_mod.assert_label_is_not_a_snapshot(frozen)


def test_genuinely_reclassified_labels_pass():
    from src.research_data.pipelines import sector as sector_mod
    dates = pd.bdate_range("2020-01-01", periods=400)
    lab = np.where(np.arange(len(dates)) < 200, "Banks", "Finance")
    moving = pd.DataFrame({
        "symbol": np.repeat(["AAA", "BBB"], len(dates)),
        "date": np.tile(dates, 2),
        "sector": np.concatenate([lab, np.full(len(dates), "Pharma")]),
    })
    sector_mod.assert_label_is_not_a_snapshot(moving)
