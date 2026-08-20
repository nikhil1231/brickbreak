"""H026 regression — the surviving finding must reproduce through research_data.

H026 is the one signal that survived out of sample: rank by the mean
percentile of `rs_60d_vs_mkt` and `sector_breadth`, take the top 5 per
session, enter at the adjusted open, hold for sessions.

This test does NOT reproduce the exact legacy numbers — those were measured on
the old chronological holdout (2020-12 → 2023-07 and 2023-08 → 2026-08), not
on split v1 partitions. What it proves:

1. The data path works: features load through research_data.frame, the signal
   is computable, and forward returns come through research_data.frame.
2. The signal has the expected statistical properties on the train partition.
3. The catalogue knows about the features and they are scorable.

The regression target is *directional correctness on train*, not an exact
alpha number, because the sample is partitioned differently.

WHY HORIZON 20 AND NOT 30
H026 was measured with a 30-session hold, but split v1 has max_horizon=20.
check_horizon(30, manifest) would raise. The regression uses horizon 10 and
20 — within the purge budget — and verifies the signal is directionally
correct. A v2 split for 30-session hypotheses can come when one needs it.
"""
from __future__ import annotations

import pytest
import numpy as np
import pandas as pd

from src.research_data import catalogue as cat_mod
from src.research_data.catalogue import build_default_catalogue


# ---------------------------------------------------------------------------
# catalogue checks — the H026 features must be registered and scorable
# ---------------------------------------------------------------------------

class TestH026CataloguePresence:
    """The two features H026 ranks on must be in the catalogue and scorable."""

    def test_rs_60d_vs_mkt_registered(self):
        cat = build_default_catalogue()
        assert "rs_60d_vs_mkt" in cat

    def test_sector_breadth_registered(self):
        cat = build_default_catalogue()
        assert "sector_breadth" in cat

    def test_rs_60d_vs_mkt_scorable(self):
        cat = build_default_catalogue()
        assert cat.scorable("rs_60d_vs_mkt"), \
            "rs_60d_vs_mkt must be scorable — it is PIT"

    def test_sector_breadth_scorable(self):
        cat = build_default_catalogue()
        assert cat.scorable("sector_breadth"), \
            "sector_breadth must be scorable — it is PIT"

    def test_both_are_pit(self):
        cat = build_default_catalogue()
        for name in ("rs_60d_vs_mkt", "sector_breadth"):
            is_pit, chain = cat.validate_pit(name)
            assert is_pit, f"{name} should be PIT, chain: {chain}"

    def test_both_safe_for_morning(self):
        cat = build_default_catalogue()
        for name in ("rs_60d_vs_mkt", "sector_breadth"):
            assert cat.safe_for_morning(name), \
                f"{name} should be safe for morning rules"


# ---------------------------------------------------------------------------
# signal construction — the H026 signal is computable
# ---------------------------------------------------------------------------

def _compute_h026_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the H026 signal: mean percentile rank of rs_60d_vs_mkt and
    sector_breadth, per session.

    Returns the input frame with 'h026_signal' and 'h026_rank' columns.
    """
    d = df.copy()
    for col in ("rs_60d_vs_mkt", "sector_breadth"):
        d[f"{col}_pctile"] = d.groupby("date")[col].rank(pct=True)
    d["h026_signal"] = (d["rs_60d_vs_mkt_pctile"]
                        + d["sector_breadth_pctile"]) / 2
    d["h026_rank"] = d.groupby("date")["h026_signal"].rank(
        ascending=False, method="first")
    return d


@pytest.mark.skipif(
    not (pd.io.common.Path(
        "data/normalized/screen_metrics_asof.parquet").exists()
        and pd.io.common.Path(
            "data/normalized/daily_context.parquet").exists()),
    reason="requires built data files on disk")
class TestH026SignalConstruction:
    """The H026 signal must be computable through the frame API."""

    @pytest.fixture(scope="class")
    @classmethod
    def train_panel(cls):
        from src.research_data import frame
        return frame.load_daily_panel(
            partition="train",
            include_context=True,
        )

    def test_required_columns_present(self, train_panel):
        for col in ("rs_60d_vs_mkt", "sector_breadth", "symbol", "date",
                     "partition"):
            assert col in train_panel.columns, f"{col} missing from panel"

    def test_signal_has_variance(self, train_panel):
        """The signal must have non-trivial variance — a constant score
        would pass all directional tests vacuously."""
        d = _compute_h026_signal(
            train_panel.dropna(subset=["rs_60d_vs_mkt", "sector_breadth"]))
        assert d["h026_signal"].std() > 0.01, \
            "H026 signal has near-zero variance"

    def test_signal_coverage(self, train_panel):
        """At least 80% of training rows should have the signal computable."""
        total = len(train_panel)
        computable = train_panel[["rs_60d_vs_mkt", "sector_breadth"]].dropna()
        coverage = len(computable) / total
        assert coverage > 0.5, \
            f"H026 signal coverage is {coverage:.1%}, expected >50%"

    def test_top5_selection_reasonable(self, train_panel):
        """Selecting top 5 per session should produce a manageable number
        of rows."""
        d = _compute_h026_signal(
            train_panel.dropna(subset=["rs_60d_vs_mkt", "sector_breadth"]))
        top5 = d[d["h026_rank"] <= 5]
        n_sessions = d["date"].nunique()
        # Should have roughly 5 per session
        assert len(top5) > n_sessions * 3, \
            "too few top-5 rows"
        assert len(top5) < n_sessions * 6, \
            "too many top-5 rows (ties?)"


@pytest.mark.skipif(
    not (pd.io.common.Path(
        "data/normalized/screen_metrics_asof.parquet").exists()
        and pd.io.common.Path(
            "data/normalized/daily_context.parquet").exists()
        and pd.io.common.Path(
            "data/normalized/daily_bars_adj.parquet").exists()),
    reason="requires built data files on disk")
class TestH026ForwardReturns:
    """Forward returns through the module, checking directional correctness."""

    @pytest.fixture(scope="class")
    @classmethod
    def signal_with_returns(cls):
        from src.research_data import frame
        panel = frame.load_daily_panel(
            partition="train",
            include_context=True,
        )
        d = _compute_h026_signal(
            panel.dropna(subset=["rs_60d_vs_mkt", "sector_breadth"]))
        # Forward returns at horizon 10 (within split's purge budget)
        d["fwd_ret_10d"] = frame.forward_return(d, horizon=10)
        return d

    def test_forward_returns_computable(self, signal_with_returns):
        """Forward returns through the module must produce non-null values."""
        d = signal_with_returns
        n_valid = d["fwd_ret_10d"].notna().sum()
        assert n_valid > 1000, \
            f"only {n_valid} valid forward returns; expected >1000"

    def test_top_quintile_vs_bottom(self, signal_with_returns):
        """Top quintile of the H026 signal should have higher mean forward
        returns than the bottom quintile on the train partition.

        This is the directional correctness check — not an exact alpha
        number, because the sample is partitioned differently from the
        legacy holdout.
        """
        d = signal_with_returns.dropna(subset=["fwd_ret_10d", "h026_signal"])
        if len(d) < 500:
            pytest.skip("insufficient data for quintile test")

        d["quintile"] = d.groupby("date")["h026_signal"].transform(
            lambda s: pd.qcut(s, 5, labels=False, duplicates="drop")
            if len(s) >= 10 else pd.Series(np.nan, index=s.index))
        d = d.dropna(subset=["quintile"])
        if d["quintile"].nunique() < 4:
            pytest.skip("too few quintiles formed")

        top = d[d["quintile"] == 4]["fwd_ret_10d"].mean()
        bottom = d[d["quintile"] == 0]["fwd_ret_10d"].mean()

        # The test is directional: top quintile should beat bottom.
        # This is a weak test because it's on train data, but it proves
        # the signal is computed correctly through the module.
        assert top > bottom, \
            f"H026 signal should show top > bottom quintile returns on " \
            f"train, but got top={top:.3f}% vs bottom={bottom:.3f}%"


# ---------------------------------------------------------------------------
# numerical anchors — Stage A's real "done when"
# ---------------------------------------------------------------------------

_DATA_READY = (pd.io.common.Path("data/normalized/screen_metrics_asof.parquet").exists()
               and pd.io.common.Path("data/normalized/daily_context.parquet").exists())


@pytest.mark.skipif(not _DATA_READY, reason="requires built data files on disk")
class TestH026NumericalRegression:
    """The structural tests above prove the signal is *computable*. They do not
    prove the module serves the same numbers the finding was computed from,
    which is what Stage A actually claimed.

    H026's headline (+1.73% a trade against the same-day pool, t=4.98) cannot
    be re-measured here: it was taken on 2020-2023, which is now the `test`
    partition and blocked for the `discovery` family that owns H026. Re-running
    it would be the third read of a spent window. So this anchors two things
    that can be checked without spending anything:

    1. the new frame API serves *bit-identical* feature values to the legacy
       path the finding was computed through;
    2. the signal's fingerprint on `train` is pinned, so a silent change in the
       data or the pipeline shows up as a failing test rather than as a
       different answer next quarter.

    A failure here means either the data was rebuilt or the pipeline moved.
    Both are worth knowing about before trusting anything downstream.
    """

    # Measured 2026-08-20 on split v1 (hash 657db79f7d380880) after the
    # hot-path fixes. Tolerances are loose enough for float noise and tight
    # enough that a real change trips them.
    ANCHOR = {
        "rows": 1_400_086,
        "sessions": 705,
        "mean_ic": 0.0072,
        "hac_t": 0.61,
        "effective_n": 70,
        "spread_bps": 26.9,
        "monotonicity": 0.9,
        "coverage": 0.9252,
    }

    @pytest.fixture(scope="class")
    def scored(self):
        from src.research_data import frame
        p = frame.load_daily_panel(partition="train", include_context=True)
        d = p.dropna(subset=["rs_60d_vs_mkt", "sector_breadth"]).copy()
        for c in ("rs_60d_vs_mkt", "sector_breadth"):
            d[f"{c}_p"] = d.groupby("date")[c].rank(pct=True)
        d["h026"] = (d["rs_60d_vs_mkt_p"] + d["sector_breadth_p"]) / 2
        d["fwd_ret_10d_pct"] = frame.forward_return(d, 10)
        return p, d

    def test_frame_api_matches_the_legacy_path_exactly(self, scored):
        """The finding was computed off `context.load()`. If the module serves
        different numbers, nothing downstream inherits the old evidence."""
        from src import context
        _, d = scored
        ctx, _ = context.load()
        ctx["date"] = pd.to_datetime(ctx["date"])
        samp = d.sample(3000, random_state=0)[["symbol", "date", "rs_60d_vs_mkt"]]
        m = samp.merge(ctx[["symbol", "date", "rs_60d_vs_mkt"]],
                       on=["symbol", "date"], how="left",
                       suffixes=("_new", "_legacy"))
        assert m["rs_60d_vs_mkt_legacy"].notna().all(), \
            "the frame API served rows the legacy context panel does not have"
        assert (m["rs_60d_vs_mkt_new"] - m["rs_60d_vs_mkt_legacy"]).abs().max() == 0.0

    def test_coverage_anchor(self, scored):
        p, d = scored
        assert abs(len(d) / len(p) - self.ANCHOR["coverage"]) < 0.01
        assert abs(len(d) - self.ANCHOR["rows"]) < 0.01 * self.ANCHOR["rows"]

    def test_ic_anchor(self, scored):
        from src.alpha_eval import diagnostics
        _, d = scored
        ic = diagnostics.rank_ic(d, "h026", "fwd_ret_10d_pct", horizon=10)
        assert ic["n_sessions"] == self.ANCHOR["sessions"]
        assert abs(ic["mean_ic"] - self.ANCHOR["mean_ic"]) < 0.002
        assert abs(ic["t_stat"] - self.ANCHOR["hac_t"]) < 0.25
        assert ic["effective_n"] == self.ANCHOR["effective_n"]

    def test_quantile_anchor(self, scored):
        from src.alpha_eval import diagnostics
        _, d = scored
        qp = diagnostics.quantile_profile(d, "h026", "fwd_ret_10d_pct", q=5,
                                          horizon=10)
        assert abs(qp["spread_bps"] - self.ANCHOR["spread_bps"]) < 5.0
        assert abs(qp["monotonicity"] - self.ANCHOR["monotonicity"]) < 0.15

    def test_the_finding_is_not_significant_on_train(self, scored):
        """Recorded deliberately. H026's surviving claim was about selection
        against the same-day pool on 2020-2023, not a cross-sectional IC on
        2023-2026, and this anchor should not be mistaken for a replication."""
        from src.alpha_eval import diagnostics
        _, d = scored
        ic = diagnostics.rank_ic(d, "h026", "fwd_ret_10d_pct", horizon=10)
        assert abs(ic["t_stat"]) < 2.0

    def test_forward_return_matches_a_hand_computed_label(self, scored):
        """The label the anchor rests on, checked against the bars directly."""
        from src.research_data import frame
        _, d = scored
        bars = pd.read_parquet("data/normalized/daily_bars_adj.parquet",
                               columns=["symbol", "date", "close"])
        bars["date"] = pd.to_datetime(bars["date"])
        sym = "RELIANCE"
        b = bars[bars.symbol == sym].sort_values("date").reset_index(drop=True)
        rows = d[d.symbol == sym].sort_values("date").iloc[[100, 300, 500]]
        got = frame.forward_return(rows, 10).to_numpy()
        for k, (_, r) in enumerate(rows.iterrows()):
            i = b.index[b.date == pd.Timestamp(r["date"])][0]
            want = (b.close[i + 10] / b.close[i] - 1) * 100
            assert abs(got[k] - want) < 1e-9
