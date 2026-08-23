"""The pre-2020 panel, and the two ways building it goes silently wrong.

Both failures below were real and both were caught by measuring the return
distribution rather than by reading the code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research_data.pipelines import corporate_actions as CA
from src.research_data.pipelines import legacy as L


# --------------------------------------------------------------------------
# the parser gap that left 72% of legacy splits unexplained
# --------------------------------------------------------------------------

@pytest.mark.parametrize("subject,expected", [
    ("Fv Split Rs.10/- To Rs.2/", 0.2),
    ("Face Value Split From Rs.10/- To Rs.2/-", 0.2),
    ("Fv Split Rs.10/- To Re.1/", 0.1),
    ("Face Value Split From Rs 10 To Re 1", 0.1),
    ("Face Value Split From Rs.2/- To Re.1/-", 0.5),
    ("Fv Split Rs.2/- To Re.1/-", 0.5),
    # the modern phrasing must keep working
    ("Face Value Split From Rs.10/- Per Share To Rs.1/- Per Share", 0.1),
])
def test_legacy_face_value_phrasings_parse(subject, expected):
    assert CA.parse_subject(subject).ratio == pytest.approx(expected)


def test_a_bare_number_pair_is_not_read_as_a_face_value_change():
    """The currency prefix is what stops "1 to 2" anywhere in a sentence."""
    assert CA.parse_subject("Split of the board meeting 1 to 2 adjourned").ratio is None


def test_a_non_equity_bonus_still_does_not_rescale():
    assert CA.parse_subject("Bonus Ncrps 4:1").ratio is None


# --------------------------------------------------------------------------
# the ratio list that turned ordinary sessions into corporate actions
# --------------------------------------------------------------------------

def test_only_structural_ratios_are_ever_adjusted():
    """A 20% fall is a 20% fall.

    An earlier ratio list included 4:5 and 5:4 and 'adjusted' 5,722 ordinary
    20-25% moves. That does not lose data, it manufactures it, and nothing
    downstream could have seen it.
    """
    assert L.STRUCTURAL_RATIOS.min() <= 0.5
    assert not np.any((L.STRUCTURAL_RATIOS > 0.55) & (L.STRUCTURAL_RATIOS < 1.8))
    for r in (0.8, 1.25, 0.75, 1.5):
        assert r not in set(L.STRUCTURAL_RATIOS), r
        assert r in set(np.round(L.AMBIGUOUS_RATIOS, 4)) or any(
            abs(r - a) < 1e-9 for a in L.AMBIGUOUS_RATIOS), r


def _bars(n=60, split_at=30, ratio=0.5):
    """One symbol that splits once, with the share count moving to match."""
    dates = pd.bdate_range("2010-01-04", periods=n)
    close = np.full(n, 100.0)
    close[split_at:] *= ratio
    vol = np.full(n, 1000.0)
    vol[split_at:] /= ratio
    d = pd.DataFrame({"symbol": "AAA", "date": dates, "close": close,
                      "open": close, "high": close, "low": close,
                      "volume": vol, "series": "EQ"})
    d["prev_close"] = d["close"].shift(1).fillna(d["close"].iloc[0])
    d["turnover"] = d["close"] * d["volume"]
    return d


def test_a_split_with_matching_volume_is_adjusted():
    steps = L.classify_steps(_bars())
    assert (steps["action"] == "adjust").sum() == 1
    assert steps.loc[steps["action"] == "adjust", "snapped_ratio"].iloc[0] == pytest.approx(0.5)


def test_a_halving_with_no_volume_response_is_quarantined_not_adjusted():
    """A price that halves while the share count stays put is a crash."""
    d = _bars()
    d["volume"] = 1000.0                      # no share-count change
    steps = L.classify_steps(d)
    assert (steps["action"] == "adjust").sum() == 0
    assert (steps["action"] == "quarantine").sum() == 1


def test_an_ordinary_twenty_percent_fall_is_left_alone():
    d = _bars(ratio=0.8)
    d["volume"] = 1000.0
    steps = L.classify_steps(d)
    assert (steps["action"] == "adjust").sum() == 0


# --------------------------------------------------------------------------
# quarantine has to actually remove the window, not just mark the row
# --------------------------------------------------------------------------

def test_a_quarantined_row_removes_the_windows_that_would_span_it():
    dates = pd.bdate_range("2010-01-04", periods=30)
    d = pd.DataFrame({"symbol": "AAA", "date": dates, "close": 100.0,
                      "ca_confidence": "clean"})
    d.loc[20, "ca_confidence"] = "quarantined"
    out = L.drop_quarantined_windows(d, horizon=5)
    kept = set(out["date"])
    assert dates[20] not in kept
    for i in range(15, 21):
        assert dates[i] not in kept, f"window starting {dates[i].date()} spans the step"
    assert dates[14] in kept
    assert dates[21] in kept
