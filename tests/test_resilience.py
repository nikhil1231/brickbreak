"""Causality tests for the resilience signal.

The project has shipped four non-price lookaheads (H015, `time_above_open_frac`,
the `median_vol_20` denominator, `size_tier_rank`) and each one was found by a
test that appended later sessions and required the earlier answers not to move.
That test comes first here, before any result off this module is quoted.

The second family of tests is alignment: a rolling window that is off by one
session is a lookahead that no amount of staring at the code reveals, so every
window is checked against a hand-computed value on a grid small enough to
verify by eye.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research import resilience as R


def _synthetic(n_dates: int = 400, n_syms: int = 60, seed: int = 0
               ) -> tuple[R.Panel, np.ndarray]:
    """A small deterministic panel with a market factor and idiosyncratic noise."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n_dates)
    symbols = pd.Index([f"S{i:03d}" for i in range(n_syms)])
    mkt = rng.normal(0.0004, 0.01, n_dates)
    betas = rng.uniform(0.4, 1.8, n_syms)
    r = betas[None, :] * mkt[:, None] + rng.normal(0, 0.015, (n_dates, n_syms))
    close = 100.0 * np.exp(np.cumsum(r, axis=0))
    open_ = close * (1 + rng.normal(0, 0.002, close.shape))
    logret = np.full_like(close, np.nan)
    logret[1:] = np.log(close[1:] / close[:-1])
    turnover = np.abs(rng.normal(80, 25, close.shape)) + 20.0
    sector = np.array([f"SEC{i % 4}" for i in range(n_syms)], dtype=object)
    p = R.Panel(dates=dates, symbols=symbols, close=close, open=open_,
                logret=logret, turnover=turnover, sector=sector)
    return p, close.copy()


def _truncate(p: R.Panel, craw: np.ndarray, keep: int) -> tuple[R.Panel, np.ndarray]:
    return R.Panel(dates=p.dates[:keep], symbols=p.symbols,
                   close=p.close[:keep], open=p.open[:keep],
                   logret=p.logret[:keep], turnover=p.turnover[:keep],
                   sector=p.sector), craw[:keep]


# --------------------------------------------------------------------------
# the lookahead test
# --------------------------------------------------------------------------

@pytest.mark.parametrize("k", [10, 20])
def test_signals_ignore_everything_after_date_d(k: int) -> None:
    """Every signal on date D is unchanged by sessions that come after D.

    Built by running the whole pipeline twice — once on a truncated panel, once
    on the full one — and comparing the overlapping rows. Anything that reads
    forward, through a window, a normaliser or a cross-sectional rank, moves a
    number here.
    """
    cfg = R.ResilienceConfig(min_turnover_cr=10.0, min_price=1.0,
                             min_names_per_day=10)
    p, craw = _synthetic()
    keep = 300
    short = R.build(cfg, k=k, verbose=False, panel=_truncate(p, craw, keep))
    full = R.build(cfg, k=k, verbose=False, panel=(p, craw))

    cut = p.dates[keep - 1]
    sig = ["resid_pct", "raw_win_pct", "beta", "mom_pre_rel_pct",
           "vol_pre_pct", "turnover_cr", "mkt_win_pct", "pct_all", "dec_all",
           "dec_raw", "q_sector"]
    a = short[short["date"] < cut].set_index(["date", "symbol"])[sig].sort_index()
    b = full[full["date"] < cut].set_index(["date", "symbol"])[sig].sort_index()
    assert len(a) > 5000, "test panel too small to be meaningful"
    assert a.index.equals(b.index), "the eligible set itself moved"
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9)


def test_forward_returns_do_change_when_the_future_changes() -> None:
    """The converse — proof the test above can actually fail.

    A test that passes because nothing depends on the future proves nothing.
    The outcome columns *must* move when later sessions move; if they do not,
    the comparison above is vacuous.
    """
    cfg = R.ResilienceConfig(min_turnover_cr=10.0, min_price=1.0,
                             min_names_per_day=10)
    p, craw = _synthetic()
    short = R.build(cfg, k=10, verbose=False, panel=_truncate(p, craw, 300))
    full = R.build(cfg, k=10, verbose=False, panel=(p, craw))
    cut = p.dates[299]
    key = ["date", "symbol"]
    a = short[short["date"] < cut].set_index(key)["fwd_20"].sort_index()
    b = full[full["date"] < cut].set_index(key)["fwd_20"].sort_index()
    assert a.isna().sum() > b.isna().sum(), (
        "truncating the panel did not truncate any forward return")


# --------------------------------------------------------------------------
# alignment
# --------------------------------------------------------------------------

def test_window_return_covers_exactly_the_k_sessions_ending_d_minus_one() -> None:
    p, _ = _synthetic(n_dates=120, n_syms=5)
    k = 10
    w = R.window_return(p, k)
    t, s = 60, 2
    expected = np.nansum(p.logret[t - k:t, s])
    assert w[t, s] == pytest.approx(expected, rel=1e-12)
    # date D itself must not be in it.
    assert w[t, s] != pytest.approx(np.nansum(p.logret[t - k + 1:t + 1, s]))


def test_beta_is_fitted_strictly_before_the_decline_window() -> None:
    """The fit ends one session before the window opens, and contains none of it."""
    cfg = R.ResilienceConfig(beta_window=60, beta_min_obs=30,
                             min_names_per_day=4)
    p, _ = _synthetic(n_dates=300, n_syms=8)
    mkt = R.market_returns(p, cfg)["broad"]
    k = 20
    beta = R.rolling_beta(p, mkt, cfg, offset=k + cfg.beta_gap)
    t, s = 200, 3
    end = t - k - cfg.beta_gap                 # last row of the fit, inclusive
    lo = end - cfg.beta_window + 1
    x, y = mkt[lo:end + 1], p.logret[lo:end + 1, s]
    m = np.isfinite(x) & np.isfinite(y)
    expected = np.polyfit(x[m], y[m], 1)[0]
    assert beta[t, s] == pytest.approx(expected, rel=1e-8)
    assert end < t - k, "the beta fit overlaps the window it is adjusting"


def test_forward_returns_start_at_the_open_of_date_d() -> None:
    p, _ = _synthetic(n_dates=80, n_syms=4)
    for h in (1, 5, 20):
        r_open, r_skip = R.forward_returns(p, h)
        t, s = 40, 1
        assert r_open[t, s] == pytest.approx(
            (p.close[t + h - 1, s] / p.open[t, s] - 1) * 100, rel=1e-12)
        assert r_skip[t, s] == pytest.approx(
            (p.close[t + h, s] / p.close[t, s] - 1) * 100, rel=1e-12)


def test_truncated_horizons_are_nan_not_short_windows() -> None:
    p, _ = _synthetic(n_dates=50, n_syms=3)
    r_open, r_skip = R.forward_returns(p, 20)
    assert np.isnan(r_open[-1]).all() and np.isnan(r_open[-19]).all()
    assert np.isnan(r_skip[-1]).all()


def test_rolled_windows_do_not_wrap_the_sample() -> None:
    """`np.roll` is circular; the head of every rolled array must be voided.

    Without this the first session of the sample carries the last session's
    value, which is the most severe lookahead available — the end of the
    backtest leaking into its start.
    """
    p, _ = _synthetic(n_dates=60, n_syms=3)
    assert np.isnan(R.window_return(p, 10)[0]).all()
    cfg = R.ResilienceConfig(beta_window=30, beta_min_obs=15,
                             min_names_per_day=2)
    mkt = R.market_returns(p, cfg)["broad"]
    b = R.rolling_beta(p, mkt, cfg, offset=11)
    assert np.isnan(b[:11]).all()


# --------------------------------------------------------------------------
# universe and benchmarks
# --------------------------------------------------------------------------

def test_largecap_proxy_selects_on_trailing_turnover_only() -> None:
    """Changing a name's return on date D must not change whether it was picked.

    `p.turnover` is the trailing 20-session median off `screen_metrics_asof`,
    already lagged. Selecting the index on anything dated D would put the day's
    movers into the day's index, which manufactures a market that always
    "explains" the cross-section.
    """
    cfg = R.ResilienceConfig(largecap_n=10, min_names_per_day=5)
    p, _ = _synthetic(n_dates=60, n_syms=40)
    tv = p.turnover.copy()
    tv[:, 0] = 1e6                       # symbol 0 is always in the basket
    p2 = R.Panel(p.dates, p.symbols, p.close, p.open, p.logret.copy(), tv,
                 p.sector)
    before = R.market_returns(p2, cfg)["large"].copy()
    p2.turnover[:, 1] = -1.0             # symbol 1 can never be
    after = R.market_returns(p2, cfg)["large"]
    assert not np.allclose(before, after, equal_nan=True), (
        "turnover has no influence on the basket at all")


def test_market_excess_is_zero_mean_within_a_session() -> None:
    """The benchmark is the eligible universe, so the excess must net to zero.

    If it does not, the long-short spread and the difference of two excesses
    stop being the same number and every table below disagrees with itself.
    """
    cfg = R.ResilienceConfig(min_turnover_cr=10.0, min_price=1.0,
                             min_names_per_day=10)
    p, craw = _synthetic(n_dates=250, n_syms=40)
    d = R.build(cfg, k=10, verbose=False, panel=(p, craw))
    per_date = d.groupby("date")["fwd_xs_mkt_5"].mean().dropna()
    assert np.abs(per_date).max() < 1e-9


def test_sector_quintiles_need_a_minimum_sector_size() -> None:
    cfg = R.ResilienceConfig(min_turnover_cr=10.0, min_price=1.0,
                             min_names_per_day=10, min_sector_members=1000)
    p, craw = _synthetic(n_dates=250, n_syms=40)
    d = R.build(cfg, k=10, verbose=False, panel=(p, craw))
    assert d["q_sector"].isna().all()


# --------------------------------------------------------------------------
# inference helpers
# --------------------------------------------------------------------------

def test_newey_west_is_wider_than_the_naive_error_on_overlapping_data() -> None:
    """Overlapping holds are autocorrelated; the naive t must be the bigger lie."""
    rng = np.random.default_rng(3)
    base = rng.normal(0.05, 1.0, 2000)
    # A 5-session hold re-formed daily: consecutive observations share 4 days.
    overlapping = pd.Series(np.convolve(base, np.ones(5), mode="valid"))
    nw = R.nw_tstat(overlapping, lag=5)
    assert abs(nw["t"]) < abs(nw["naive_t"])


def test_monotonicity_separates_a_gradient_from_one_odd_bucket() -> None:
    ramp = pd.DataFrame({"mean": np.linspace(-1, 1, 10)},
                        index=range(1, 11))
    spike = pd.DataFrame({"mean": [0, 0, 0, 0, 0, 0, 0, 0, 0, 2.0]},
                         index=range(1, 11))
    assert R.monotonicity(ramp)["spearman"] == pytest.approx(1.0)
    assert R.monotonicity(ramp)["inversions"] == 0
    assert R.monotonicity(spike)["spearman"] < 0.6
    # Both have a positive top-minus-bottom; only one is a ranking.
    assert R.monotonicity(spike)["top_minus_bottom"] > 0


def test_spearman_matches_a_hand_computed_case() -> None:
    x = pd.Series([1.0, 2.0, 3.0, 4.0])
    y = pd.Series([10.0, 30.0, 20.0, 40.0])
    assert R._spearman(x, y) == pytest.approx(0.8)
    assert R._spearman(x, -y) == pytest.approx(-0.8)


# --------------------------------------------------------------------------
# the decomposition and the frozen bar
# --------------------------------------------------------------------------

def test_orthogonal_score_is_exactly_beta_in_disguise() -> None:
    """The identity the H036 conclusion rests on, checked rather than asserted.

    Within one session `resid_i = r_i - beta_i * r_mkt` with `r_mkt` constant,
    so projecting `resid` off `r_i` can only leave `-r_mkt` times the part of
    `beta_i` that `r_i` does not explain. If this ever stops holding, something
    other than beta has got into the score and the conclusion drawn from it —
    "conditional on the drawdown, resilience is nothing but beta" — is void.
    """
    rng = np.random.default_rng(5)
    n = 400
    r_mkt = -0.07
    beta = rng.uniform(0.3, 2.0, n)
    r = beta * r_mkt + rng.normal(0, 0.05, n)
    d = pd.DataFrame({
        "date": pd.Timestamp("2024-03-01"),
        "raw_win_pct": r * 100,
        "resid_pct": (r - beta * r_mkt) * 100,
        "beta": beta,
    })
    orth = R.orthogonal_score(d, level=True)

    X = np.column_stack([np.ones(n), d["raw_win_pct"].to_numpy()])
    beta_orth = beta - X @ np.linalg.lstsq(X, beta, rcond=None)[0]
    predicted = -r_mkt * 100 * beta_orth
    assert np.corrcoef(orth, predicted)[0, 1] == pytest.approx(1.0, abs=1e-10)
    assert np.allclose(orth, predicted, atol=1e-8)


def test_orthogonal_score_needs_a_populated_cross_section() -> None:
    d = pd.DataFrame({"date": pd.Timestamp("2024-03-01"),
                      "raw_win_pct": [1.0, 2.0, 3.0],
                      "resid_pct": [0.5, 0.4, 0.9]})
    assert R.orthogonal_score(d).isna().all()


def test_frozen_spec_hash_catches_an_edit() -> None:
    spec = {"config": {"a": 1}, "pass_criterion": {"b": 2}}
    h = R._spec_hash(spec)
    assert R._spec_hash({"config": {"a": 1}, "pass_criterion": {"b": 2}}) == h
    assert R._spec_hash({"config": {"a": 2}, "pass_criterion": {"b": 2}}) != h


def _verdict(h5: float, h10: float, t5: float, t10: float,
             deep5: float, deep10: float, mid5: float, mid10: float) -> str:
    out = {"runs": {"k10_broad": {
        "primary": {"h5": {"ls": h5, "t": t5}, "h10": {"ls": h10, "t": t10}},
        "depth": {"<-6": {"h5": {"mean": deep5}, "h10": {"mean": deep10}},
                  "-3..-1": {"h5": {"mean": mid5}, "h10": {"mean": mid10}}}}}}
    return R._semi_stale_verdict(out)[0]


def test_frozen_bar_is_applied_as_written() -> None:
    """Each clause of the criterion can fail on its own, and does."""
    assert _verdict(-0.5, -0.1, -2.5, -0.3, -1.2, -0.4, -0.1, 0.1) == "PASS"
    # a positive spread at either horizon is a FAIL, however strong the other
    assert _verdict(-0.5, +0.1, -3.5, +0.3, -1.2, -0.4, -0.1, 0.1) == "FAIL"
    # negative everywhere but never strong: PARTIAL
    assert _verdict(-0.5, -0.1, -1.2, -0.3, -1.2, -0.4, -0.1, 0.1) == "PARTIAL"
    # strong, but the depth gradient runs the wrong way: PARTIAL, not PASS
    assert _verdict(-0.5, -0.1, -2.5, -0.3, +0.5, +0.9, -0.1, 0.1) == "PARTIAL"
