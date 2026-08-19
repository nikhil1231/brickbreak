"""Tests for the as-of-open lag (H015) and the work-list dedup.

Both failures these guard against are silent. A `shift` that no-ops looks exactly
like one that worked and the screen goes on reading the future; a work list built
on the wrong symbol convention looks exactly like a correct one and quietly
re-pulls thousands of mornings already on disk.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import asof, fetch_opening as fo


def _panel(symbols=("AAA", "BBB"), n=6):
    """Two symbols with interleaved dates, so a naive global shift would leak."""
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=n)
    for s in symbols:
        for i, d in enumerate(dates):
            rows.append({"symbol": s, "date": d,
                         "close": 100.0 + i + (0 if s == "AAA" else 50),
                         "open": 99.0 + i, "open_raw": 99.0 + i,
                         "adj_factor": 1.0, "series": "EQ",
                         "ret_20d": float(i), "above_ema_mid": i % 2})
    # Deliberately shuffled: the lag must not depend on incoming row order.
    return pd.DataFrame(rows).sample(frac=1, random_state=0).reset_index(drop=True)


def test_lag_takes_the_previous_session_of_the_same_symbol():
    d = _panel()
    out = asof.lag_columns(d).sort_values(["symbol", "date"])
    for s in ("AAA", "BBB"):
        sub = out[out["symbol"] == s]
        src = d[d["symbol"] == s].sort_values("date")
        assert pd.isna(sub["close"].iloc[0])            # nothing precedes the first
        assert np.allclose(sub["close"].iloc[1:].to_numpy(),
                           src["close"].iloc[:-1].to_numpy())


def test_lag_does_not_bleed_across_symbols():
    """The first row of each symbol must be NaN, not the last row of the previous one."""
    out = asof.lag_columns(_panel()).sort_values(["symbol", "date"])
    firsts = out.groupby("symbol").head(1)
    assert firsts["close"].isna().all()
    assert firsts["ret_20d"].isna().all()


def test_columns_knowable_at_the_open_are_not_lagged():
    """`open_raw` prints in the 09:15 auction and is on the tape before the entry.

    Lagging it would replace a real feature with a stale one and silently break
    `gap_pct`, which is date D's opening print against date D-1's close.
    """
    d = _panel()
    out = asof.lag_columns(d)
    j = d.merge(out, on=["symbol", "date"], suffixes=("_a", "_b"))
    assert (j["open_raw_a"] == j["open_raw_b"]).all()
    assert (j["adj_factor_a"] == j["adj_factor_b"]).all()
    assert (j["series_a"] == j["series_b"]).all()


def test_an_unrecognised_column_is_lagged_by_default():
    """Safe direction: a new indicator nobody classified must not stay same-day.

    This is what stops the H015 lookahead from creeping back in the next time a
    feature is added to the metrics panel.
    """
    d = _panel()
    d["some_new_indicator"] = np.arange(len(d), dtype=float)
    out = asof.lag_columns(d).sort_values(["symbol", "date"])
    assert out.groupby("symbol")["some_new_indicator"].head(1).isna().all()


def test_audit_detects_a_lag_that_did_nothing():
    """A no-op shift must be visible as a measurement, not assumed away."""
    d = _panel()
    rep = asof.audit(d, d.copy())          # "lagged" frame that was never lagged
    assert rep["columns"]["close"]["differing"] == 0
    real = asof.audit(d, asof.lag_columns(d))
    assert real["columns"]["close"]["differing"] > 0


def test_lag_of_zero_sessions_is_a_no_op():
    d = _panel()
    pd.testing.assert_frame_equal(asof.lag_columns(d, sessions=0), d)


# --------------------------------------------------------------------------
# work list
# --------------------------------------------------------------------------

def _cands(pairs):
    return pd.DataFrame(pairs, columns=["symbol", "date"]).assign(
        date=lambda d: pd.to_datetime(d["date"]))


def _man(pairs, status="ok"):
    return pd.DataFrame(pairs, columns=["symbol", "date"]).assign(
        date=lambda d: pd.to_datetime(d["date"]), status=status,
        isec_code="X", n_rows=1, duration_s=0.1, fetched_at="2026-01-01")


def test_settled_pairs_are_never_refetched(monkeypatch):
    monkeypatch.setattr(fo, "resolve_codes",
                        lambda syms: ({s: s[:6] for s in syms}, []))
    cands = _cands([("AAA", "2024-01-02"), ("AAA", "2024-01-03"),
                    ("BBB", "2024-01-02")])
    man = _man([("AAA", "2024-01-02")])
    work, rep = fo.build_work_list(cands, manifest=man, rmap=pd.DataFrame(),
                                   verbose=False)
    got = set(map(tuple, work[["symbol", "date"]].astype(str).values))
    assert ("AAA", "2024-01-02 00:00:00") not in got
    assert rep["already_settled"] == 1
    assert rep["to_fetch"] == 2


def test_an_empty_morning_counts_as_settled(monkeypatch):
    """A stock that did not trade in the window will not trade on a re-request."""
    monkeypatch.setattr(fo, "resolve_codes", lambda syms: ({s: s for s in syms}, []))
    cands = _cands([("AAA", "2024-01-02")])
    work, rep = fo.build_work_list(cands, manifest=_man([("AAA", "2024-01-02")],
                                                        status="empty"),
                                   rmap=pd.DataFrame(), verbose=False)
    assert rep["to_fetch"] == 0


def test_an_errored_morning_is_retried(monkeypatch):
    """A 429 must not poke a permanent hole in the dataset."""
    monkeypatch.setattr(fo, "resolve_codes", lambda syms: ({s: s for s in syms}, []))
    cands = _cands([("AAA", "2024-01-02")])
    work, rep = fo.build_work_list(cands, manifest=_man([("AAA", "2024-01-02")],
                                                        status="error"),
                                   rmap=pd.DataFrame(), verbose=False)
    assert rep["to_fetch"] == 1


def test_a_renamed_symbol_is_not_refetched_under_its_new_ticker(monkeypatch):
    """The manifest holds the ticker each morning was fetched under.

    The candidate panel holds the canonical post-rename ticker. Compared
    directly, every renamed company's entire history looks unfetched — thousands
    of wasted calls against data already on disk.
    """
    monkeypatch.setattr(fo, "resolve_codes", lambda syms: ({s: s for s in syms}, []))
    rmap = pd.DataFrame([{"old_symbol": "OLDNAME", "new_symbol": "NEWNAME",
                          "status": "applied"}])
    cands = _cands([("NEWNAME", "2024-01-02")])
    man = _man([("OLDNAME", "2024-01-02")])          # fetched under the old ticker

    import src.renames as renames
    monkeypatch.setattr(renames, "canonical_map",
                        lambda m=None: {"OLDNAME": "NEWNAME"})
    work, rep = fo.build_work_list(cands, manifest=man, rmap=rmap, verbose=False)
    assert rep["to_fetch"] == 0, "renamed symbol was queued for a needless re-pull"


def test_date_window_is_respected(monkeypatch):
    monkeypatch.setattr(fo, "resolve_codes", lambda syms: ({s: s for s in syms}, []))
    cands = _cands([("AAA", "2019-01-02"), ("AAA", "2024-01-02"),
                    ("AAA", "2027-01-02")])
    work, rep = fo.build_work_list(cands, date_min="2020-01-01",
                                   date_max="2026-08-18",
                                   manifest=_man([]), rmap=pd.DataFrame(),
                                   verbose=False)
    assert rep["to_fetch"] == 1
    assert str(work["date"].iloc[0].date()) == "2024-01-02"


def test_symbols_without_an_isec_code_are_dropped_not_silently_kept(monkeypatch):
    """Breeze rejects NSE tickers, so an unmapped symbol is a guaranteed error."""
    monkeypatch.setattr(fo, "resolve_codes",
                        lambda syms: ({"AAA": "AAACOD"}, ["BBB"]))
    cands = _cands([("AAA", "2024-01-02"), ("BBB", "2024-01-02")])
    work, rep = fo.build_work_list(cands, manifest=_man([]), rmap=pd.DataFrame(),
                                   verbose=False)
    assert rep["to_fetch"] == 1
    assert rep["unmappable_pairs"] == 1
    assert work["isec_code"].notna().all()
