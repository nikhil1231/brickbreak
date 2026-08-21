"""Corporate-action parsing, reconciliation and price adjustment.

The cases here are all drawn from events that actually occurred in the panel,
because the failure modes this module exists to handle were only visible in
real NSE data — inconsistent PREV_CLOSE, several actions sharing one ex-date,
and symbols renamed between the tape and the corporate-actions feed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research_data.pipelines.corporate_actions import (
    adjust_bars, build_factors, find_renamed_symbol, group_events,
    measure_steps, parse_subject, reconcile, rights_factor,
)


# ------------------------------------------------------------------ parsing

@pytest.mark.parametrize("subject,kind,ratio", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share",
     "SPLIT", 0.1),
    ("Face Value Split (Sub-Division) - From Rs 10 Per Share To Rs 5  Per Share",
     "SPLIT", 0.5),
    ("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share",
     "CONSOLIDATION", 10.0),
    ("Bonus 1:1", "BONUS", 0.5),            # 1 free per 1 held -> 1 becomes 2
    ("Bonus 4:1", "BONUS", 0.2),            # 4 free per 1 held -> 1 becomes 5
    ("Bonus 1:2", "BONUS", 2 / 3),          # 1 free per 2 held -> 2 becomes 3
    ("Bonus 1: 1", "BONUS", 0.5),           # stray space
    ("Dividend - Rs 15 Per Share", "DIVIDEND", None),
    ("Demerger", "DEMERGER", None),
])
def test_parse_subject_ratios(subject, kind, ratio):
    p = parse_subject(subject)
    assert p.kind == kind
    if ratio is None:
        assert p.ratio is None
    else:
        assert p.ratio == pytest.approx(ratio)


@pytest.mark.parametrize("subject", [
    "Scheme Of Arrangement - Bonus Ncrps 4:1",       # preference shares
    "Scheme Of Arangement- Bonus - 1 Debenture For 1 Equity Share Held",
])
def test_non_equity_bonus_is_not_a_price_ratio(subject):
    """A bonus of preference shares or debentures leaves the equity count alone.

    TVSMOTOR's "Bonus Ncrps 4:1" would otherwise rescale its whole history by
    0.2 for an event that never touched the share price.
    """
    assert parse_subject(subject).ratio is None


def test_rights_factor_dilutes_toward_the_issue_price():
    # 1 new share per 1 held at 50 (premium 40 + face 10), cum price 100.
    # Two shares worth 100 and 50 -> 75 each.
    assert rights_factor("Rights 1:1 @ Premium Rs 40/-", 100.0, 10.0) == pytest.approx(0.75)
    # An at-par issue states a zero premium; the face value is the issue price.
    assert rights_factor("Rights 1:1 @ Premium Rs 0/-", 100.0, 50.0) == pytest.approx(0.75)
    # No premium stated at all -> no issue price -> not priceable.
    assert rights_factor("Rights 27:47", 100.0, 10.0) is None


# ------------------------------------------------------- combining ex-dates

def test_actions_sharing_an_ex_date_are_combined():
    """BAJFINANCE 2025-06-16 was a 1:2 split *and* a 4:1 bonus.

    The tape stepped by 0.5 * 0.2 = 0.10. Matched separately each ratio looks
    like a gross mismatch against that step, and adjusting by only one of them
    would leave the series discontinuous.
    """
    actions = pd.DataFrame([
        {"symbol": "BAJFINANCE", "ex_date": pd.Timestamp("2025-06-16"),
         "kind": "SPLIT", "ratio": 0.5, "subject": "split", "face_value": 2},
        {"symbol": "BAJFINANCE", "ex_date": pd.Timestamp("2025-06-16"),
         "kind": "BONUS", "ratio": 0.2, "subject": "Bonus 4:1", "face_value": 2},
    ])
    ev = group_events(actions)
    assert len(ev) == 1
    assert float(np.prod(list(ev.iloc[0]["ratio_known"]))) == pytest.approx(0.10)


# ------------------------------------------------------------- step measures

def _bars(rows):
    return pd.DataFrame(rows, columns=["symbol", "date", "prev_close",
                                       "open", "high", "low", "close", "volume"]) \
        .assign(date=lambda d: pd.to_datetime(d["date"]))


def test_both_step_measures_are_needed():
    """NSE is inconsistent about whether PREV_CLOSE is already adjusted.

    TATASTEEL's split shows in open/PREV_CLOSE; DRCSYSTEMS' does not, because
    there PREV_CLOSE was pre-adjusted. Only the pair catches both.
    """
    bars = _bars([
        # TATASTEEL: PREV_CLOSE raw, so step_prev sees the 1:10 split.
        ("TATASTEEL", "2022-07-27", 949.5, 951.0, 961.55, 943.6, 959.4, 5_255_902),
        ("TATASTEEL", "2022-07-28", 959.4, 98.1, 102.0, 97.15, 100.35, 137_156_107),
        # DRCSYSTEMS: PREV_CLOSE already adjusted, so only step_prior sees it.
        ("DRCSYSTEMS", "2022-03-14", 390.0, 385.0, 392.0, 380.0, 381.3, 4_000),
        ("DRCSYSTEMS", "2022-03-21", 38.15, 36.8, 40.05, 36.8, 40.05, 6_132),
    ])
    s = measure_steps(bars).set_index(["symbol", "date"])
    tata = s.loc[("TATASTEEL", pd.Timestamp("2022-07-28"))]
    assert tata["step_prev"] == pytest.approx(0.1022, abs=1e-3)

    drc = s.loc[("DRCSYSTEMS", pd.Timestamp("2022-03-21"))]
    assert drc["step_prev"] == pytest.approx(0.965, abs=1e-3)   # blind to it
    assert drc["step_prior"] == pytest.approx(0.0965, abs=1e-3)  # sees it


# ------------------------------------------------------------ reconciliation

def _tata_bars():
    return _bars([
        ("TATASTEEL", "2022-07-26", 960.7, 972.0, 976.7, 946.05, 949.5, 12_626_469),
        ("TATASTEEL", "2022-07-27", 949.5, 951.0, 961.55, 943.6, 959.4, 5_255_902),
        ("TATASTEEL", "2022-07-28", 959.4, 98.1, 102.0, 97.15, 100.35, 137_156_107),
        ("TATASTEEL", "2022-07-29", 100.35, 103.0, 109.3, 102.15, 107.6, 166_959_934),
    ])


def _tata_action():
    return pd.DataFrame([{
        "symbol": "TATASTEEL", "ex_date": pd.Timestamp("2022-07-28"),
        "kind": "SPLIT", "ratio": 0.1, "face_value": 1,
        "subject": "Face Value Split - From Rs 10/- Per Share To Re 1/- Per Share",
    }])


def test_reconcile_matches_a_stated_ratio_to_the_tape():
    rec = reconcile(_tata_bars(), _tata_action())
    assert rec["status"].tolist() == ["matched"]
    assert rec["stated_ratio"].iloc[0] == pytest.approx(0.1)


def test_reconcile_rejects_a_ratio_the_tape_contradicts():
    """A stated ratio with no corresponding step must not be applied."""
    actions = _tata_action().assign(
        ratio=0.5, subject="Face Value Split - From Rs 10 Per Share To Rs 5 Per Share")
    rec = reconcile(_tata_bars(), actions)
    assert rec["status"].iloc[0] == "ratio_mismatch"
    # and nothing is rescaled as a result
    factors = build_factors(_tata_bars(), rec)
    assert (factors["adj_factor"] == 1.0).all()


def test_demergers_are_flagged_and_never_adjusted():
    actions = pd.DataFrame([{
        "symbol": "TATASTEEL", "ex_date": pd.Timestamp("2022-07-28"),
        "kind": "DEMERGER", "ratio": None, "face_value": 1, "subject": "Demerger",
    }])
    rec = reconcile(_tata_bars(), actions)
    assert rec["status"].iloc[0] == "unadjustable"
    assert (build_factors(_tata_bars(), rec)["adj_factor"] == 1.0).all()


# ----------------------------------------------------------------- renames

def test_rename_resolution_requires_a_clean_handover():
    """A ratio match alone is ambiguous; the listing handover disambiguates.

    UNOMINDA's 2022-07-07 bonus is on the tape under MINDAIND. TORNTPHARM also
    halved that week, but it is still trading, so it cannot be the same listing.
    """
    rows = []
    for d in pd.date_range("2022-07-04", "2022-07-06"):
        rows.append(("MINDAIND", d, 960.0, 958.8, 960.0, 950.0, 958.8, 1000))
    rows.append(("MINDAIND", pd.Timestamp("2022-07-07"), 958.8, 479.4, 480.0,
                 470.0, 479.4, 5000))                     # the bonus, old ticker
    # The old ticker keeps trading until the rename itself takes effect, which
    # is a month after the bonus; the new one picks up the next session.
    for d in pd.date_range("2022-07-08", "2022-08-04"):
        rows.append(("MINDAIND", d, 479.4, 479.4, 485.0, 475.0, 479.4, 1000))
    for d in pd.date_range("2022-08-05", "2022-08-09"):
        rows.append(("UNOMINDA", d, 500.0, 500.0, 505.0, 495.0, 500.0, 1000))
    # A decoy that halves in the same window but keeps trading afterwards.
    rows.append(("TORNTPHARM", pd.Timestamp("2022-07-07"), 900.0, 450.0, 455.0,
                 445.0, 450.0, 2000))
    for d in pd.date_range("2022-09-01", "2022-09-05"):
        rows.append(("TORNTPHARM", d, 450.0, 450.0, 455.0, 445.0, 450.0, 2000))
    bars = _bars(rows)

    old = find_renamed_symbol(bars, measure_steps(bars), "UNOMINDA",
                              pd.Timestamp("2022-07-07"), 0.5)
    assert old == "MINDAIND"


def test_rename_resolution_declines_when_ambiguous():
    """Two equally plausible predecessors must resolve to neither."""
    rows = []
    rows.append(("OLDA", pd.Timestamp("2022-07-07"), 100.0, 50.0, 51.0, 49.0, 50.0, 1000))
    rows.append(("OLDB", pd.Timestamp("2022-07-07"), 200.0, 100.0, 101.0, 99.0, 100.0, 1000))
    for d in pd.date_range("2022-07-08", "2022-07-12"):
        rows.append(("NEWCO", d, 50.0, 50.0, 51.0, 49.0, 50.0, 1000))
    bars = _bars(rows)
    assert find_renamed_symbol(bars, measure_steps(bars), "NEWCO",
                               pd.Timestamp("2022-07-07"), 0.5) is None


# --------------------------------------------------------------- adjustment

def test_adjustment_makes_the_series_continuous_and_keeps_raw_prices():
    bars = _tata_bars()
    rec = reconcile(bars, _tata_action())
    adj = adjust_bars(bars, build_factors(bars, rec)).sort_values("date")

    # Pre-split closes are scaled onto the post-split scale ...
    assert adj["close"].iloc[1] == pytest.approx(95.94)
    # ... while the price that actually printed is preserved.
    assert adj["close_raw"].iloc[1] == pytest.approx(959.4)
    # ... and post-ex-date bars are untouched.
    assert adj["close"].iloc[2] == pytest.approx(100.35)

    # No residual -90% discontinuity across the ex-date.
    step = adj["close"].iloc[2] / adj["close"].iloc[1] - 1
    assert abs(step) < 0.10

    # Volume is scaled the other way, so price*volume still reconciles.
    assert adj["volume"].iloc[1] == pytest.approx(5_255_902 / 0.1)


def test_prev_close_uses_the_previous_sessions_factor():
    """Otherwise close/prev_close reads as a -90% return on every ex-date.

    The synthetic sector index is built from exactly that expression, so this
    is the difference between a sector reading correctly and one megacap split
    dragging its whole sector down for a day.
    """
    bars = _tata_bars()
    rec = reconcile(bars, _tata_action())
    adj = adjust_bars(bars, build_factors(bars, rec)).sort_values("date")
    ex = adj[adj["date"] == pd.Timestamp("2022-07-28")].iloc[0]

    assert ex["prev_close_raw"] == pytest.approx(959.4)   # what NSE published
    assert ex["prev_close"] == pytest.approx(95.94)       # scaled to today's terms
    assert (ex["close"] / ex["prev_close"] - 1) == pytest.approx(0.046, abs=0.01)
