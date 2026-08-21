"""Future-blindness of the case builder. The load-bearing test of the package.

A case is what the AI is shown. Everything downstream is arithmetic; this is
where the future can get in, and it would not look wrong when it did. This
project has caught four distinct non-price lookaheads — the entry day's own
close (H015), a contaminated denominator, a present-day snapshot attribute, and
a gap between observations inside a window — and none of them was in an obvious
place. The standing assumption is that there is a fifth.

The shape of the check is the one `tests/test_context.py` already uses and
which AGENTS.md names as the thing to write before trusting a feature: build
the case from a panel that stops at D, build it again from a panel that runs
years past D, and require the bytes to be identical. A feature that reads even
one value from after D cannot survive it.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from src.discretionary import case as C
from src.discretionary import generators as G


DATES = pd.bdate_range("2022-01-03", periods=180)
SYMS = [f"S{i:02d}" for i in range(40)]


def _fixture(seed: int = 7):
    """A panel and bars with enough structure that the blocks are non-trivial."""
    rng = np.random.default_rng(seed)
    prows, brows = [], []
    for s in SYMS:
        px = 100.0 * (1 + rng.random())
        hist = []
        for d in DATES:
            ret = rng.normal(0.0005, 0.02)
            px *= (1 + ret)
            hist.append(px)
            hi, lo = px * (1 + abs(rng.normal(0, .01))), px * (1 - abs(rng.normal(0, .01)))
            brows.append({"symbol": s, "date": d, "open": px * (1 + rng.normal(0, .003)),
                          "high": hi, "low": lo, "close": px,
                          "volume": float(rng.integers(1e5, 1e6))})
            w = hist[-21:-1] or [px]
            prows.append({
                "symbol": s, "date": d, "series": "EQ", "is_etf": False,
                "sector": f"SEC{hash(s) % 5}", "size_tier": "mid",
                "close": px, "median_tv_20_cr": 5.0 + rng.random() * 20,
                "median_vol_20": 5e5, "turnover": 1e7, "deliv_pct": 40 + rng.random() * 20,
                "ret_20d": (px / w[0] - 1) * 100, "ret_60d": rng.normal(0, 8),
                "atr_pct": 2 + rng.random(), "atr_ratio": 0.8 + rng.random() * .5,
                "atr_ratio_pctile": rng.random() * 100,
                "bb_width_pctile": rng.random() * 100,
                "range_pct_ma": 2.0, "base_depth": 5.0, "base_depth_pctile": 50.0,
                "nr_k": False, "inside_day": False, "doji_like": False,
                "body_ratio": 0.5, "n_small_bodies_5": 1, "vol_squeeze": False,
                "contraction_steps": 1, "gap_pct": rng.normal(0, 1),
                "px_vs_ema_fast": rng.normal(0, 3), "px_vs_ema_mid": rng.normal(0, 5),
                "ema_stack_up": True, "above_ema_mid": True,
                "dist_52w_high": -rng.random() * 30,
                "prior_high_20": px * 1.05, "prior_low_20": px * 0.92,
                "base_range_20_pct": 14.0, "days_since_high_20": 6.0,
                "n_touches_20": 3.0, "prev_close_vs_high_20_pct": -3.0,
                "open_vs_high_20_pct": -2.0, "open_above_high_20": False,
                "open_base_pos_20": rng.random(), "base_low_dist_20_pct": 8.0,
                "prior_high_50": px * 1.1, "days_since_high_50": 20.0,
                "n_touches_50": 5.0, "open_vs_high_50_pct": -6.0,
                "open_base_pos_50": rng.random(),
                "rs_20d_vs_mkt": rng.normal(0, 5), "rs_60d_vs_mkt": rng.normal(0, 9),
                "rs_20d_vs_sec": rng.normal(0, 4),
                "sec_ret_20d": rng.normal(0, 3), "sec_ret_60d": rng.normal(0, 6),
                "sec_rs_20d_vs_mkt": rng.normal(0, 2),
                "sector_uptrend_index": True, "sector_breadth": 55.0,
                "mkt_regime": "trending_up", "mkt_ret_5d": 1.0, "mkt_ret_20d": 3.0,
                "mkt_ret_60d": 7.0, "mkt_vol_20d": 14.0, "mkt_trend_eff": 0.4,
                "mkt_vs_ema50_pct": 2.0, "mkt_dd_from_60d_high_pct": -3.0,
                "mkt_breadth_pct": 58.0,
            })
    return pd.DataFrame(prows), pd.DataFrame(brows)


PANEL, BARS = _fixture()
CUT = DATES[120]
BLOCKS = ("price_history", "location", "market", "sector", "relative_strength",
          "volatility_liquidity", "volume", "extension_contraction", "quant",
          "analogues")


def _cases(panel, bars, cands, blocks=BLOCKS, anonymise=True):
    return C.build(cands, panel, bars, blocks=blocks, anonymise=anonymise,
                   history_sessions=60, n_analogues=5, analogue_horizon=10,
                   replay_id="T")


@pytest.fixture(scope="module")
def candidates():
    return pd.DataFrame({
        "symbol": SYMS[:6],
        "date": [CUT] * 6,
        "generator_score": np.arange(6, dtype=float),
        "generator_reason": ["fixture"] * 6,
    })


def test_a_case_is_identical_whether_or_not_the_future_exists(candidates):
    """The whole package rests on this.

    Truncating the panel and the bars at the decision session must change
    nothing about the case built for that session. Any difference is a value
    read from after D.
    """
    full = _cases(PANEL, BARS, candidates)
    truncated = _cases(PANEL[PANEL["date"] <= CUT], BARS[BARS["date"] <= CUT],
                       candidates)
    assert len(full) == len(truncated) == 6
    for a, b in zip(full, truncated):
        assert a.render() == b.render(), f"{a.case_id} differs when the future exists"
        assert a.case_hash == b.case_hash


def test_appending_later_sessions_changes_nothing(candidates):
    """The mirror of the above, and the form AGENTS.md prescribes.

    `test_context.py` appends later bars and requires every feature at t to be
    bit-identical. A case is a bundle of features, so it inherits the rule.
    """
    before = _cases(PANEL[PANEL["date"] <= CUT], BARS[BARS["date"] <= CUT],
                    candidates)
    extra_panel, extra_bars = _fixture(seed=99)
    later = extra_panel[extra_panel["date"] > CUT]
    after = _cases(
        pd.concat([PANEL[PANEL["date"] <= CUT], later], ignore_index=True),
        pd.concat([BARS[BARS["date"] <= CUT],
                   extra_bars[extra_bars["date"] > CUT]], ignore_index=True),
        candidates)
    for a, b in zip(before, after):
        assert a.case_hash == b.case_hash


def test_the_decision_day_bar_is_not_in_the_price_history(candidates):
    """`< date`, never `<= date`.

    Including date D's own bar hands over its high, low and close — the H015
    lookahead in its original form, and the one that inverts results rather
    than merely inflating them.
    """
    cases = _cases(PANEL, BARS, candidates)
    hist = cases[0].blocks["price_history"]
    assert hist["n_sessions"] > 0
    assert all(r["t"] < 0 for r in hist["bars"]), "a bar at or after t=0"


def test_an_analogue_whose_outcome_had_not_printed_is_excluded():
    """A situation three sessions old has not resolved at a ten-session horizon.

    Filtering analogues on their own date rather than on when their outcome
    landed would hand the decider a return from after its own decision — the
    subtlest leak available here, because the analogue genuinely is in the past.
    """
    pool = C._analogue_pool(PANEL, BARS, horizon=10)
    assert not pool.empty
    assert (pool["resolved_by"] > pool["date"]).all()
    usable = pool[pool["resolved_by"] < CUT]
    assert usable["date"].max() < CUT
    # The most recent usable analogue must be at least the horizon back.
    gap = np.busday_count(usable["date"].max().date(), CUT.date())
    assert gap >= 10, f"an analogue resolved only {gap} sessions before D"


def test_a_forward_label_in_the_frame_is_refused(candidates):
    """The guard is called, not assumed.

    A case built from a frame carrying `fwd_ret_10d_pct` is indistinguishable
    from a correct one by inspection, so the refusal has to be structural.
    """
    dirty = PANEL.copy()
    dirty["fwd_ret_10d_pct"] = 1.0
    with pytest.raises(Exception, match="[Ff]orward label"):
        _cases(dirty, BARS, candidates)


def test_anonymisation_removes_the_symbol_and_the_calendar(candidates):
    """A model may simply remember the name and the quarter.

    No frame hygiene closes that channel — the leak is in the weights — so the
    identity must not reach the rendered case at all.
    """
    for c in _cases(PANEL, BARS, candidates, anonymise=True):
        text = c.render()
        assert c.symbol not in text
        assert c.date not in text
        # A bare year substring is not the test: a rebased price of 118.2022
        # contains "2022" and leaks nothing. What must be absent is a date.
        assert not re.search(r"(?<![\d.])(19|20)\d{2}-\d{2}-\d{2}(?![\d.])", text)
        # A year must not appear as a token of its own either. The lookarounds
        # exclude decimals: a rebased price of 109.2006 is not a leak.
        assert not re.search(r"(?<![\d.])(19|20)\d{2}(?![\d.])", text)
        real_sector = PANEL.loc[PANEL["symbol"] == c.symbol, "sector"].iloc[0]
        assert real_sector not in text    # the real sector label is withheld
        assert "group_id: G" in text      # but "my sector" is still sayable


def test_absolute_levels_are_withheld_under_anonymisation(candidates):
    """A price of 2,351 narrows an NSE name considerably.

    It also contradicts the rest of the case, where the chart is rebased to
    100: a judge shown both cannot compare them. Every dropped field has a
    relative twin in the same block, so only the identity goes.
    """
    anon = _cases(PANEL, BARS, candidates, anonymise=True)[0]
    named = _cases(PANEL, BARS, candidates, anonymise=False)[0]
    for col in ("prior_high_20", "prior_low_20"):
        assert col not in anon.blocks["location"]
        assert col in named.blocks["location"]
    for col in ("turnover", "median_vol_20"):
        assert col not in anon.blocks["volume"]
    # The relative twin survives, so nothing about location is actually lost.
    assert "open_vs_high_20_pct" in anon.blocks["location"]
    assert "open_base_pos_20" in anon.blocks["location"]


def test_identity_is_retained_on_the_record_even_when_hidden(candidates):
    """Hidden from the decider, kept on the row: outcomes have to join back."""
    c = _cases(PANEL, BARS, candidates, anonymise=True)[0]
    assert c.symbol in SYMS and c.date == CUT.strftime("%Y-%m-%d")


def test_revealing_identity_changes_the_case_and_therefore_the_hash(candidates):
    """Anonymised and revealed are different questions, and must hash apart.

    They are two arms of the memorisation measurement; if they shared a hash
    the cache would serve one arm's decisions to the other.
    """
    a = _cases(PANEL, BARS, candidates, anonymise=True)[0]
    b = _cases(PANEL, BARS, candidates, anonymise=False)[0]
    assert a.case_hash != b.case_hash
    assert b.symbol in b.render()


def test_session_percentiles_rank_within_the_session_not_the_panel(candidates):
    """A percentile against the whole panel ranks against sessions after D."""
    cases = _cases(PANEL, BARS, candidates)
    q = cases[0].blocks["quant"]
    assert q["session_breadth_names"] == len(SYMS)
    assert 0.0 <= q["ret_20d_session_pctile"] <= 100.0


def test_flags_render_as_words_not_as_zero_and_one(candidates):
    """"inside_day: 0" asks the reader to know the polarity of a column name."""
    text = _cases(PANEL, BARS, candidates)[0].render()
    assert "inside_day: no" in text
    assert "ema_stack_up: yes" in text
    assert "inside_day: 0" not in text


def test_the_case_set_hash_tracks_content(candidates):
    cases = _cases(PANEL, BARS, candidates)
    assert C.case_set_hash(cases) == C.case_set_hash(list(cases))
    assert C.case_set_hash(cases) != C.case_set_hash(cases[:-1])


def test_jsonl_round_trip_preserves_the_hash(candidates):
    cases = _cases(PANEL, BARS, candidates)
    back = C.from_jsonl(C.to_jsonl(cases))
    assert [c.case_hash for c in back] == [c.case_hash for c in cases]


def test_a_generator_may_not_see_a_forward_label():
    """Generation is not selection, and it certainly is not selection on the outcome."""
    dirty = PANEL.copy()
    dirty["fwd_ret_5d_pct"] = 1.0
    with pytest.raises(Exception, match="[Ff]orward label"):
        G.generate(dirty, "liquid_universe")
