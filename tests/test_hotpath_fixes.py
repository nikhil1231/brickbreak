"""Regression tests for the six hot-path defects found in the Stage A-E review.

Each test here corresponds to a bug that produced a plausible-looking number
rather than an error, which is the only kind that matters in this project.
Where a fix restores a known quantity, the test asserts against the quantity
rather than against the current output.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.families.opening_window import explore
from src.alpha_eval import backtest as B
from src.alpha_eval import diagnostics as D
from src.alpha_eval import report as R
from src.alpha_eval.guards import ScoringGuardError
from src.persistence import ledger as L
from src.research_data import frame, splits as S
from src.runner import spec as SP


# ---------------------------------------------------------------------------
# helpers: a universe whose answer is known by construction
# ---------------------------------------------------------------------------

DRIFT = 0.001            # every symbol rises exactly 0.1% a session
TRUTH_CAGR = (1 + DRIFT) ** 250 - 1


def _flat_universe(n_sym: int = 120, n_sess: int = 400):
    dates = pd.bdate_range("2021-01-01", periods=n_sess)
    syms = [f"S{i:03d}" for i in range(n_sym)]
    px = 100 * (1 + DRIFT) ** np.arange(n_sess)
    bars = pd.DataFrame(
        [(s, d, p, p) for s in syms for d, p in zip(dates, px)],
        columns=["symbol", "date", "open", "close"])
    rng = np.random.default_rng(0)
    sig = pd.DataFrame({"symbol": np.tile(syms, n_sess),
                        "date": np.repeat(dates, n_sym)})
    sig["score"] = rng.normal(size=len(sig))
    return bars, sig


def _null_frame(rng, n_sym=50, n_sess=250, h=20):
    """Persistent signal, independent returns: true predictive power is zero."""
    r = rng.normal(size=(n_sess + h, n_sym))
    fwd = pd.DataFrame(r).rolling(h).sum().shift(-h).to_numpy()[:n_sess]
    sig = rng.normal(size=n_sym)
    return pd.DataFrame({
        "date": np.repeat(np.arange(n_sess), n_sym),
        "symbol": np.tile(np.arange(n_sym), n_sess),
        "sig": np.tile(sig, n_sess),
        "fwd": fwd.ravel(),
    })


# ---------------------------------------------------------------------------
# 1. the canonical backtest ran the book at `holding_sessions` leverage
# ---------------------------------------------------------------------------

class TestBacktestLeverage:
    """`pnl / top_k` with staggered cohorts is H times levered.

    At hold=10 it reported 334% CAGR on a universe compounding at 28.4%.
    """

    @pytest.mark.parametrize("hold", [5, 10, 20])
    def test_return_never_exceeds_buy_and_hold(self, hold):
        bars, sig = _flat_universe()
        r = B.canonical_backtest(
            sig, "score", B.BacktestConfig(top_k=5, holding_sessions=hold),
            bars=bars)
        cagr = r["portfolio"]["cagr_pct"] / 100
        assert cagr <= TRUTH_CAGR + 1e-6, (
            f"hold={hold} reported {cagr:.1%} on a universe that compounds at "
            f"{TRUTH_CAGR:.1%}; a long-only book cannot beat every constituent")

    def test_cost_drag_falls_as_holds_lengthen(self):
        """Longer holds mean fewer round trips per unit capital, so returns
        rise *toward* buy-and-hold. Under the bug they rose past it."""
        bars, sig = _flat_universe()
        got = [B.canonical_backtest(
                   sig, "score", B.BacktestConfig(top_k=5, holding_sessions=h),
                   bars=bars)["portfolio"]["cagr_pct"]
               for h in (5, 10, 20)]
        assert got == sorted(got)
        assert got[-1] < TRUTH_CAGR * 100

    def test_capital_slots_reported(self):
        bars, sig = _flat_universe()
        r = B.canonical_backtest(
            sig, "score", B.BacktestConfig(top_k=5, holding_sessions=10),
            bars=bars)
        assert r["config"]["capital_slots"] == 50
        assert r["portfolio"]["mean_exposure_pct"] <= 100.0 + 1e-9

    def test_benchmark_says_unavailable_rather_than_zero(self):
        """Too few priced names is an unknown market, not a flat one — a 0.0%
        benchmark makes every signal look like alpha."""
        bars, sig = _flat_universe(n_sym=40)
        r = B.canonical_backtest(sig, "score", bars=bars)
        assert "unavailable" in r["market_benchmark"]

    def test_matched_benchmark_carries_the_book_s_cash_pattern(self):
        """On a non-contiguous partition the book sits in cash while a
        buy-and-hold benchmark keeps compounding. Both are now reported."""
        bars, sig = _flat_universe(n_sess=600)
        live = ((sig["date"].dt.month - 1) % 6) < 2
        r = B.canonical_backtest(sig[live], "score", bars=bars)
        assert r["market_benchmark"]["invested_pct"] == 100.0
        assert r["market_benchmark_matched"]["invested_pct"] < 100.0
        assert (r["market_benchmark_matched"]["cagr_pct"]
                < r["market_benchmark"]["cagr_pct"])

    def test_untraded_session_does_not_shift_later_returns(self):
        """Compressing NaNs out of a price path moves every later return onto
        the wrong session."""
        bars, sig = _flat_universe(n_sym=120, n_sess=300)
        holed = bars.copy()
        gap = (holed["symbol"] == "S000") & (holed["date"].dt.day == 15)
        holed.loc[gap, "close"] = np.nan
        a = B.canonical_backtest(sig, "score", bars=bars)["portfolio"]
        b = B.canonical_backtest(sig, "score", bars=holed)["portfolio"]
        assert abs(a["cagr_pct"] - b["cagr_pct"]) < 1.0
        assert a["n_sessions"] == b["n_sessions"]


# ---------------------------------------------------------------------------
# 2. overlapping forward windows inflated every t-statistic
# ---------------------------------------------------------------------------

class TestOverlapCorrection:
    """At h=20 the uncorrected t rejected a zero-power signal 68% of the time."""

    def test_naive_t_is_still_inflated_so_the_test_proves_something(self):
        rng = np.random.default_rng(11)
        naive = [D.rank_ic(_null_frame(rng), "sig", "fwd", horizon=20)["naive_t_stat"]
                 for _ in range(40)]
        assert np.nanstd(naive) > 2.0

    def test_hac_t_is_far_better_calibrated(self):
        rng = np.random.default_rng(11)
        hac = [D.rank_ic(_null_frame(rng), "sig", "fwd", horizon=20)["t_stat"]
               for _ in range(40)]
        assert np.nanstd(hac) < 2.0

    def test_horizon_is_inferred_from_the_column_name(self):
        assert D.horizon_from_column("fwd_ret_20d_pct") == 20
        assert D.horizon_from_column("excess_ret_5d_pct") == 5
        assert D.horizon_from_column("no_horizon_here") == 1

    def test_lags_zero_reproduces_the_h016_implementation(self):
        """`explore.cluster_stats` is what H016 was measured with; the port
        must not have drifted."""
        rng = np.random.default_rng(0)
        d = pd.DataFrame({"y": rng.normal(size=3000),
                          "date": np.repeat(np.arange(150), 20)})
        d["y"] += np.repeat(rng.normal(size=150), 20) * 2
        new = D.cluster_stats(d["y"], d["date"])
        old = explore.cluster_stats(d["y"], d["date"])
        assert new["mean"] == old["mean"]
        assert new["t"] == old["t"]

    def test_clustered_se_widens_with_lags(self):
        rng = np.random.default_rng(5)
        n_d = 200
        base = np.repeat(rng.normal(size=n_d), 20)
        sm = pd.Series(base).rolling(20).mean().bfill().to_numpy()
        d = pd.DataFrame({"y": sm, "date": np.repeat(np.arange(n_d), 20)})
        assert (D.cluster_stats(d["y"], d["date"], lags=19)["se"]
                > D.cluster_stats(d["y"], d["date"], lags=0)["se"])

    def test_effective_n_is_reported(self):
        rng = np.random.default_rng(3)
        res = D.rank_ic(_null_frame(rng, n_sess=250), "sig", "fwd", horizon=20)
        assert res["effective_n"] == 250 // 20
        assert res["hac_lags"] == 19

    def test_spread_t_is_corrected_too(self):
        rng = np.random.default_rng(7)
        qp = D.quantile_profile(_null_frame(rng), "sig", "fwd", q=5, horizon=20)
        assert qp["hac_lags"] == 19
        assert abs(qp["spread_t"]) <= abs(qp["spread_naive_t"]) + 1e-9


# ---------------------------------------------------------------------------
# 3. quantile buckets collapsed silently on ties
# ---------------------------------------------------------------------------

class TestQuantileTies:
    """`qcut(duplicates='drop')` renumbered, so the top bucket of a tie-heavy
    session came back labelled Q3 and never entered Q5."""

    @staticmethod
    def _mixed(rng, n_d=120, n_s=50):
        rows = []
        for i, d in enumerate(pd.bdate_range("2024-01-01", periods=n_d)):
            sig = rng.normal(size=n_s) if i % 2 == 0 else \
                rng.choice([0.0, 1.0, 2.0], size=n_s)
            rows.append(pd.DataFrame({"date": d,
                                      "symbol": [f"S{j}" for j in range(n_s)],
                                      "sig": sig, "fwd": rng.normal(size=n_s)}))
        return pd.concat(rows, ignore_index=True)

    def test_buckets_are_equal_sized_despite_ties(self):
        qp = D.quantile_profile(self._mixed(np.random.default_rng(3)),
                                "sig", "fwd", q=5, horizon=1)
        sizes = [q["n"] for q in qp["quantiles"]]
        assert len(sizes) == 5
        assert max(sizes) - min(sizes) <= len(sizes)

    def test_tie_fraction_is_reported(self):
        qp = D.quantile_profile(self._mixed(np.random.default_rng(3)),
                                "sig", "fwd", q=5, horizon=1)
        assert 40 <= qp["tie_pct"] <= 60

    def test_tie_breaking_is_deterministic(self):
        df = self._mixed(np.random.default_rng(3))
        a = D.quantile_profile(df, "sig", "fwd", q=5, horizon=1)
        b = D.quantile_profile(df, "sig", "fwd", q=5, horizon=1)
        assert [q["mean"] for q in a["quantiles"]] == \
               [q["mean"] for q in b["quantiles"]]


# ---------------------------------------------------------------------------
# 4. the ledger let the two hypotheses that spent the holdout back in
# ---------------------------------------------------------------------------

class TestLedgerGate:
    """H024 and H026 are family `discovery`; exposure was recorded only under
    `opening_window`, so a confirmatory read of the spent test set was
    ALLOWED for exactly the two rules H033 spent it on."""

    @staticmethod
    def _spec(hid, partition="test", role="confirmatory"):
        return SP.ExperimentSpec(hypothesis_id=hid, question="q",
                                 signal_name="dist_52w_high",
                                 partition=partition, role=role)

    @pytest.fixture()
    def led(self, tmp_path):
        return L.SampleBudgetLedger.load(tmp_path / "ledger.json")

    @pytest.mark.parametrize("hid", ["H024", "H026", "H033", "H037"])
    def test_spent_hypotheses_are_blocked_on_test(self, hid, led):
        with pytest.raises(L.BudgetExhaustedError):
            SP.validate_spec(self._spec(hid), budget_ledger=led)

    def test_unregistered_hypothesis_is_blocked(self, led):
        with pytest.raises(SP.SpecValidationError, match="not in the store"):
            SP.validate_spec(self._spec("H999_NOT_REAL"), budget_ledger=led)

    def test_exploratory_reads_are_not_blocked(self, led):
        SP.validate_spec(self._spec("H024", partition="train",
                                    role="exploratory"), budget_ledger=led)

    def test_an_unrelated_new_family_may_use_test(self, led):
        """The design keeps spent quarters usable for genuinely new ideas."""
        ok, blocked = led.check_permission(
            "H900", "a_brand_new_family", "confirmatory", ["2022Q2"])
        assert ok and blocked == []

    def test_discovery_exposure_is_recorded(self, led):
        fams = {e.family for e in led._entries if e.role == "confirmatory"}
        assert {"discovery", "opening_window", "resilience"} <= fams

    def test_ledger_reseeds_when_exposure_is_corrected(self, tmp_path):
        p = tmp_path / "ledger.json"
        led = L.SampleBudgetLedger.load(p)
        led.record_usage("H500", "mine", "exploratory", "train", ["2021Q3"])
        import json
        data = json.loads(p.read_text())
        data["exposure_version"] = "stale000000"
        p.write_text(json.dumps(data))

        again = L.SampleBudgetLedger.load(p)
        assert any(e.hypothesis_id == "H500" for e in again._entries), \
            "a reseed must not discard real experiment records"
        assert any(e.hypothesis_id == "HISTORICAL" and e.family == "discovery"
                   for e in again._entries)


# ---------------------------------------------------------------------------
# 5. the scoring guard was never called where signals are scored
# ---------------------------------------------------------------------------

class TestScoringGuard:

    @pytest.fixture()
    def df(self):
        rng = np.random.default_rng(0)
        n_d, n_s = 60, 30
        d = pd.DataFrame({
            "date": np.repeat(pd.bdate_range("2024-01-01", periods=n_d), n_s),
            "symbol": np.tile([f"S{i}" for i in range(n_s)], n_d)})
        d["size_tier_rank"] = np.tile(rng.choice([50, 100, 200], n_s), n_d)
        d["my_new_score"] = rng.normal(size=len(d))
        d["fwd_ret_5d_pct"] = rng.normal(size=len(d))
        return d

    def test_evaluate_signal_blocks_a_snapshot_lookahead(self, df):
        with pytest.raises(ScoringGuardError, match="H030"):
            R.evaluate_signal(df, "size_tier_rank", run_backtest=False,
                              run_neutralisation=False)

    def test_backtest_blocks_it_too(self, df):
        with pytest.raises(ScoringGuardError):
            B.canonical_backtest(df, "size_tier_rank")

    def test_unregistered_columns_pass(self, df):
        """The catalogue is a register of hazards, not a whitelist."""
        r = R.evaluate_signal(df, "my_new_score", run_backtest=False,
                              run_neutralisation=False)
        assert r["signal"] == "my_new_score"

    def test_override_is_available_and_explicit(self, df):
        r = R.evaluate_signal(df, "size_tier_rank", run_backtest=False,
                              run_neutralisation=False, allow_unscorable=True)
        assert r["signal"] == "size_tier_rank"


# ---------------------------------------------------------------------------
# 6. forward returns counted rows, and started a session early
# ---------------------------------------------------------------------------

class TestForwardReturn:

    @staticmethod
    def _bars():
        """AAA trades every session; GAPPY skips a long stretch."""
        dates = pd.bdate_range("2021-01-01", periods=60)
        rows = []
        for i, d in enumerate(dates):
            rows.append(("AAA", d, 100.0 + i, 100.0 + i))
            if i < 5 or i > 40:
                rows.append(("GAPPY", d, 50.0 + i, 50.0 + i))
        return pd.DataFrame(rows, columns=["symbol", "date", "open", "close"])

    def test_label_spans_sessions_not_traded_rows(self):
        """GAPPY's 5th *bar* forward is 36 sessions away; its 5th *session*
        forward is a session it did not trade. Counting rows turned the first
        into a '5-day' return."""
        bars = self._bars()
        dates = sorted(bars["date"].unique())
        d = pd.DataFrame({"symbol": ["GAPPY"], "date": [dates[0]]})

        # Session 5 was not traded, so the exit is GAPPY's last trade within
        # `max_staleness` sessions of it — session 4, at 54.0. Never the price
        # 36 sessions later that a row-shift would have picked up.
        got = frame.forward_return(d, 5, bars=bars).iloc[0]
        assert abs(got - (54.0 / 50.0 - 1) * 100) < 1e-9

    def test_stale_exit_is_refused_when_staleness_is_disabled(self):
        bars = self._bars()
        dates = sorted(bars["date"].unique())
        d = pd.DataFrame({"symbol": ["GAPPY"], "date": [dates[0]]})
        assert np.isnan(frame.forward_return(d, 5, bars=bars,
                                             max_staleness=0).iloc[0])

    def test_a_row_shift_would_have_reached_much_further(self):
        """Guards the guard: the row-based answer is wildly different."""
        bars = self._bars().sort_values(["symbol", "date"])
        g = bars[bars["symbol"] == "GAPPY"].reset_index(drop=True)
        row_based = (g["close"].iloc[5] / g["close"].iloc[0] - 1) * 100
        assert row_based > 70.0

    def test_entry_is_date_d_not_the_previous_close(self):
        bars = self._bars()
        dates = sorted(bars["date"].unique())
        d = pd.DataFrame({"symbol": ["AAA"], "date": [dates[10]]})
        got = frame.forward_return(d, 5, bars=bars).iloc[0]
        assert abs(got - (115.0 / 110.0 - 1) * 100) < 1e-9

    def test_entry_on_the_open_is_available(self):
        bars = self._bars()
        dates = sorted(bars["date"].unique())
        d = pd.DataFrame({"symbol": ["AAA"], "date": [dates[10]]})
        assert np.isfinite(frame.forward_return(d, 5, entry="open",
                                                bars=bars).iloc[0])

    def test_excess_return_uses_same_entry_clock_and_horizon(self):
        dates = pd.bdate_range("2021-01-01", periods=3)
        rows = []
        for symbol, scale in (("A", 1.0), ("B", 2.0), ("C", 3.0)):
            for i, date in enumerate(dates):
                rows.append((symbol, date, 100.0 * scale, (100.0 + i) * scale))
        bars = pd.DataFrame(rows, columns=["symbol", "date", "open", "close"])
        panel = bars[["symbol", "date"]].copy()
        out = frame.forward_excess_return(
            panel, 1, entry="open", bars=bars,
            min_breadth=3, ret_guard=100.0)
        # The cross-sectional market benchmark is formed from the identical
        # open-to-D+1-close labels, so excess returns sum to zero each day.
        valid = panel.assign(excess=out).dropna(subset=["excess"])
        assert np.allclose(valid.groupby("date")["excess"].mean(), 0.0)

    def test_bad_entry_argument_raises(self):
        d = pd.DataFrame({"symbol": ["AAA"], "date": [pd.Timestamp("2021-01-01")]})
        with pytest.raises(frame.FrameError, match="entry must be"):
            frame.forward_return(d, 5, entry="vwap", bars=self._bars())

    def test_horizon_beyond_the_purge_budget_is_refused(self):
        d = pd.DataFrame({"symbol": ["AAA"], "date": [pd.Timestamp("2021-01-04")]})
        with pytest.raises(S.SplitError, match="exceeds split"):
            frame.forward_return(d, 21, bars=self._bars())

    def test_result_is_aligned_to_the_callers_index(self):
        bars = self._bars()
        dates = sorted(bars["date"].unique())
        d = pd.DataFrame({"symbol": ["AAA"] * 3, "date": dates[10:13]},
                         index=[7, 99, 42])
        out = frame.forward_return(d, 5, bars=bars)
        assert list(out.index) == [7, 99, 42]

    def test_no_label_crosses_a_purged_boundary_on_the_real_panel(self):
        """The session-based label is what makes the purge bind. Row-based
        shifting put 3,681 kept rows' labels in a higher-priority partition."""
        m = S.load("v1")
        part = S.session_partitions(m)
        pri = np.array([{"": 0, "train": 1, "validation": 2, "test": 3,
                         "forward": 4}[x] for x in part.to_numpy()])
        h = m["purge"]["max_horizon"]
        kept = np.where(pri > 0)[0]
        tgt = kept + h
        inb = tgt < len(pri)
        assert not (pri[tgt[inb]] > pri[kept[inb]]).any()
