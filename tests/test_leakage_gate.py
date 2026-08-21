"""Leakage gate tests — each of the four known lookaheads must be caught.

These tests are the architectural encoding of lessons learned expensively.
They do not test that the data is correct in general; they test that the
specific failure modes this project has already seen are structurally blocked
by the catalogue, the frame API and the split module.

The four known lookaheads (the refactor plan §2):
1. H015 — selecting on the entry day's own close
2. Denominator lookahead — median_vol_20 including date D's volume
3. Snapshot attribute scoring — size_tier_rank used as a ranking (H030)
4. Gap-between-observations — time_above_open_frac reading the next tick
"""
from __future__ import annotations

import pytest

from src.research_data import catalogue as cat_mod
from src.research_data.catalogue import (
    Catalogue,
    CatalogueError,
    FeatureSpec,
    build_default_catalogue,
)


# ---------------------------------------------------------------------------
# the default catalogue loads without error
# ---------------------------------------------------------------------------

class TestCatalogueConstruction:
    def test_default_catalogue_loads(self):
        cat = build_default_catalogue()
        assert len(cat) > 80, \
            f"expected ~90 features, got {len(cat)}"

    def test_no_duplicate_names(self):
        """Each feature name appears exactly once."""
        cat = build_default_catalogue()
        names = cat.names
        assert len(names) == len(set(names))

    def test_summary_runs(self):
        cat = build_default_catalogue()
        s = cat.summary()
        assert "Feature catalogue" in s
        assert "scorable" in s

    def test_register_duplicate_raises(self):
        cat = Catalogue()
        spec = FeatureSpec("x", "test", "static", 0, False, True)
        cat.register(spec)
        with pytest.raises(CatalogueError, match="already registered"):
            cat.register(spec)


# ---------------------------------------------------------------------------
# 1. H015 — entry-day close is not a morning feature
# ---------------------------------------------------------------------------

class TestH015EntryDayClose:
    """The catalogue must mark `close` as available_as_of='close', which
    means it requires lagging before use in a morning rule. The frame API
    enforces this by defaulting to asof_open=True.
    """

    def test_close_requires_lagging(self):
        cat = build_default_catalogue()
        spec = cat["close"]
        assert spec.available_as_of == "close", \
            "close must be marked as knowable only after the session ends"
        assert cat.safe_for_morning("close") is False, \
            "close must NOT be safe for morning rules"

    def test_high_low_volume_require_lagging(self):
        cat = build_default_catalogue()
        for col in ("high", "low", "volume", "turnover", "deliv_pct"):
            spec = cat[col]
            assert spec.available_as_of == "close", \
                f"{col} must be marked as close-only"
            assert not cat.safe_for_morning(col), \
                f"{col} must NOT be safe for morning rules"

    def test_open_is_safe_for_morning(self):
        cat = build_default_catalogue()
        assert cat["open"].available_as_of == "open"
        assert cat.safe_for_morning("open") is True

    def test_prev_close_is_safe_for_morning(self):
        cat = build_default_catalogue()
        assert cat["prev_close"].available_as_of == "open"
        assert cat.safe_for_morning("prev_close") is True

    def test_indicators_served_as_prev_close(self):
        """Indicators in the as-of panel carry D-1 values, so they are
        registered as available at prev_close."""
        cat = build_default_catalogue()
        for col in ("ema_fast", "ema_mid", "atr_ratio", "bb_width_pctile",
                     "ret_20d", "above_ema_mid"):
            spec = cat[col]
            assert spec.available_as_of == "prev_close", \
                f"{col} should be available at prev_close in the as-of panel"
            assert cat.safe_for_morning(col), \
                f"{col} should be safe for morning when served as-of"


# ---------------------------------------------------------------------------
# 2. Denominator lookahead — PIT inheritance catches contaminated inputs
# ---------------------------------------------------------------------------

class TestDenominatorLookahead:
    """A clean numerator over a contaminated denominator is contaminated.
    validate_pit() must walk the input graph transitively.
    """

    def test_synthetic_non_pit_input_detected(self):
        """Register a feature with PIT=True that has a non-PIT input.
        validate_pit() must flag it."""
        cat = Catalogue()
        cat.register(FeatureSpec(
            "bad_denom", "a snapshot attribute", "static", 0,
            False, False, owner="test"))
        cat.register(FeatureSpec(
            "clean_numerator", "a clean feature", "prev_close", 0,
            True, True, owner="test"))
        cat.register(FeatureSpec(
            "contaminated_ratio", "ratio using bad denominator",
            "prev_close", 20, True, True,
            inputs=("clean_numerator", "bad_denom"), owner="test"))

        is_pit, chain = cat.validate_pit("contaminated_ratio")
        assert not is_pit, \
            "a feature with a non-PIT input must be flagged as non-PIT"
        assert "bad_denom" in chain, \
            "the non-PIT ancestor must appear in the chain"

    def test_real_median_vol_20_is_pit_when_lagged(self):
        """In the served catalogue, median_vol_20 is PIT because the as-of
        panel already lagged it."""
        cat = build_default_catalogue()
        spec = cat["median_vol_20"]
        assert spec.point_in_time is True, \
            "median_vol_20 in the lagged panel is PIT"

    def test_vol_rel_daily_inherits_pit_from_median_vol(self):
        """vol_rel_daily_pct uses median_vol_20 as denominator. In the
        served catalogue both are PIT (because the panel is lagged)."""
        cat = build_default_catalogue()
        is_pit, chain = cat.validate_pit("vol_rel_daily_pct")
        assert is_pit, \
            f"vol_rel_daily_pct should be PIT in the served catalogue, " \
            f"but chain shows: {chain}"


# ---------------------------------------------------------------------------
# 3. Snapshot attribute scoring guard (H030)
# ---------------------------------------------------------------------------

class TestSnapshotScoringGuard:
    """Non-PIT features (current-day snapshots) may stratify, never score."""

    def test_size_tier_rank_not_scorable(self):
        cat = build_default_catalogue()
        assert not cat.scorable("size_tier_rank"), \
            "size_tier_rank is a snapshot lookahead (H030); scoring blocked"

    def test_sector_not_scorable(self):
        cat = build_default_catalogue()
        assert not cat.scorable("sector"), \
            "sector is a present-day snapshot; scoring blocked"

    def test_size_tier_not_scorable(self):
        cat = build_default_catalogue()
        assert not cat.scorable("size_tier"), \
            "size_tier is derived from size_tier_rank; scoring blocked"

    def test_is_etf_not_scorable(self):
        cat = build_default_catalogue()
        assert not cat.scorable("is_etf")

    def test_scorable_features_are_scorable(self):
        """PIT features should be scorable."""
        cat = build_default_catalogue()
        for col in ("ret_20d", "atr_ratio", "rs_60d_vs_mkt",
                     "sector_breadth", "gap_pct"):
            assert cat.scorable(col), f"{col} should be scorable"

    def test_forward_labels_not_scorable(self):
        """Forward labels are never scorable — they're the future."""
        cat = build_default_catalogue()
        for col in ("fwd_ret_1d_pct", "fwd_ret_10d_pct", "excess_ret_5d_pct"):
            assert not cat.scorable(col), \
                f"{col} is a forward label and must not be scorable"

    def test_non_pit_features_marked_stratification_only(self):
        cat = build_default_catalogue()
        for spec in cat.non_pit():
            assert spec.stratification_only, \
                f"{spec.name} is non-PIT but not marked stratification_only"


# ---------------------------------------------------------------------------
# 4. Gap-between-observations — intraday feature invariance
# ---------------------------------------------------------------------------

class TestGapBetweenObservations:
    """The catalogue must flag time_above_open_frac's fixed bug, and
    intraday features must be correctly categorised."""

    def test_time_above_open_frac_caveat(self):
        """The fixed boundary lookahead bug must be documented."""
        cat = build_default_catalogue()
        spec = cat["time_above_open_frac"]
        assert "boundary" in spec.known_caveats.lower() or \
               "lookahead" in spec.known_caveats.lower(), \
            "time_above_open_frac must document the fixed boundary bug"

    def test_intraday_features_marked_correctly(self):
        """All opening-window features must be available_as_of='intraday_t'."""
        cat = build_default_catalogue()
        for spec in cat.by_owner("opening"):
            assert spec.available_as_of == "intraday_t", \
                f"{spec.name} should be available_as_of='intraday_t'"


# ---------------------------------------------------------------------------
# 5. PIT inheritance transitivity
# ---------------------------------------------------------------------------

class TestPITTransitivity:
    """A chain A→B→C where A is non-PIT: C must inherit non-PIT status
    even though B and C are declared PIT."""

    def test_three_level_chain(self):
        cat = Catalogue()
        cat.register(FeatureSpec(
            "snapshot_root", "non-PIT snapshot", "static", 0,
            False, False, owner="test"))
        cat.register(FeatureSpec(
            "derived_b", "derives from snapshot", "prev_close", 20,
            True, True, inputs=("snapshot_root",), owner="test"))
        cat.register(FeatureSpec(
            "derived_c", "derives from B", "prev_close", 20,
            True, True, inputs=("derived_b",), owner="test"))

        is_pit_b, chain_b = cat.validate_pit("derived_b")
        is_pit_c, chain_c = cat.validate_pit("derived_c")

        assert not is_pit_b, \
            "derived_b has a non-PIT input and must be non-PIT"
        assert not is_pit_c, \
            "derived_c inherits non-PIT transitively through B"
        assert "snapshot_root" in chain_c, \
            "the root non-PIT ancestor must appear in the chain"

    def test_diamond_dependency(self):
        """A->C, A->B, B->C. If A is non-PIT, C is contaminated
        through both paths."""
        cat = Catalogue()
        cat.register(FeatureSpec(
            "root", "non-PIT", "static", 0, False, False, owner="test"))
        cat.register(FeatureSpec(
            "mid", "via root", "prev_close", 0, True, True,
            inputs=("root",), owner="test"))
        cat.register(FeatureSpec(
            "leaf", "via root and mid", "prev_close", 0, True, True,
            inputs=("root", "mid"), owner="test"))

        is_pit, chain = cat.validate_pit("leaf")
        assert not is_pit

    def test_clean_chain_is_pit(self):
        """All-PIT chain should validate as PIT."""
        cat = Catalogue()
        cat.register(FeatureSpec(
            "a", "PIT root", "prev_close", 0, True, True, owner="test"))
        cat.register(FeatureSpec(
            "b", "PIT mid", "prev_close", 0, True, True,
            inputs=("a",), owner="test"))
        cat.register(FeatureSpec(
            "c", "PIT leaf", "prev_close", 0, True, True,
            inputs=("b",), owner="test"))

        is_pit, chain = cat.validate_pit("c")
        assert is_pit
        assert chain == []


# ---------------------------------------------------------------------------
# 6. Frame API blocks forward labels as features
# ---------------------------------------------------------------------------

class TestFrameBlocksForwardLabels:
    """The frame API must refuse to serve forward labels as columns."""

    def test_forward_label_column_rejected(self):
        from src.research_data.frame import FrameError
        # We can test this without actual data by checking the validation
        # logic directly.
        with pytest.raises(FrameError, match="forward label"):
            # This will fail at column validation before trying to load data
            from src.research_data import frame
            frame.load_daily_panel(columns=["fwd_ret_10d_pct"])


# ---------------------------------------------------------------------------
# 7. Availability ordering
# ---------------------------------------------------------------------------

class TestAvailability:
    def test_invalid_availability_rejected(self):
        with pytest.raises(ValueError, match="available_as_of"):
            FeatureSpec("bad", "test", "yesterday", 0, False, True)

    def test_all_valid_availabilities_accepted(self):
        from src.research_data.catalogue import AVAILABILITY_ORDER
        for avail in AVAILABILITY_ORDER:
            spec = FeatureSpec("test", "test", avail, 0, False, True)
            assert spec.available_as_of == avail


# ---------------------------------------------------------------------------
# 8. Frame API helpers (market, universe, bars)
# ---------------------------------------------------------------------------

class TestFrameHelpers:
    """Check frame module helpers for market, universe, and bars."""

    def test_market_helper(self):
        from src.research_data import frame
        mkt = frame.market(version="v1")
        assert "partition" in mkt.columns
        assert "mkt_regime" in mkt.columns
        assert len(mkt) > 0

    def test_universe_helper(self):
        from src.research_data import frame
        u = frame.universe(version="v1", partition="train", min_median_tv_cr=1.0)
        assert "symbol" in u.columns
        assert "date" in u.columns
        assert "partition" in u.columns
        assert (u["partition"] == "train").all()
        assert not u["is_etf"].any()

    def test_bars_helper(self):
        from src.research_data import frame
        b = frame.bars(version="v1", partition="train", adjusted=True)
        assert "symbol" in b.columns
        assert "date" in b.columns
        assert "partition" in b.columns
        assert (b["partition"] == "train").all()

