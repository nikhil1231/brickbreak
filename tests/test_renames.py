"""Symbol-rename validation and merging.

Every fixture here is a real case from the panel. The rejects especially: the
four long suspensions and the QUALITY off-by-one date are the cases that
decided the thresholds, so they are the cases worth pinning.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.research_data.pipelines.renames import (
    APPLIED, apply_renames, build_rename_map, canonical_map, fetch_symbol_changes,
)


def _bars(spans: dict[str, tuple[str, str, float, float]]) -> pd.DataFrame:
    """{symbol: (first_date, last_date, first_close, last_close)} -> daily bars."""
    frames = []
    for sym, (d0, d1, px0, px1) in spans.items():
        dates = pd.bdate_range(d0, d1)
        px = pd.Series(px0, index=range(len(dates)), dtype=float)
        px.iloc[-1] = px1
        frames.append(pd.DataFrame({"symbol": sym, "date": dates,
                                    "close_raw": px.values, "close": px.values}))
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"])


def _changes(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame([{"company": c, "old_symbol": o, "new_symbol": n,
                          "change_date": pd.Timestamp(d)}
                         for c, o, n, d in [(r[0], r[1], r[2], r[3]) for r in rows]])


# ------------------------------------------------------------------ accepting

def test_clean_handover_is_applied():
    """UNO Minda: MINDAIND stops, UNOMINDA starts the next session, price holds."""
    bars = _bars({"MINDAIND": ("2020-01-01", "2022-08-04", 400.0, 420.0),
                  "UNOMINDA": ("2022-08-05", "2026-08-18", 421.0, 900.0)})
    ch = _changes([("UNO Minda Limited", "MINDAIND", "UNOMINDA", "2022-08-05")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == APPLIED
    assert m.loc[0, "canonical"] == "UNOMINDA"


def test_applied_merge_makes_one_continuous_series():
    bars = _bars({"MINDAIND": ("2020-01-01", "2022-08-04", 400.0, 420.0),
                  "UNOMINDA": ("2022-08-05", "2026-08-18", 421.0, 900.0)})
    ch = _changes([("UNO Minda Limited", "MINDAIND", "UNOMINDA", "2022-08-05")])
    merged = apply_renames(bars, build_rename_map(bars, ch))
    assert set(merged["symbol"]) == {"UNOMINDA"}
    assert len(merged) == len(bars)
    assert merged["date"].is_monotonic_increasing


def test_stated_date_ahead_of_the_tape_still_applies():
    """QUALITY's stated change is 2025-07-18 but it printed that day; QUALITY30
    only began on the 21st. The map is scoped by the tape, not the filing."""
    bars = _bars({"QUALITY": ("2024-01-01", "2025-07-18", 100.0, 101.0),
                  "QUALITY30": ("2025-07-21", "2026-08-18", 101.5, 130.0)})
    ch = _changes([("Quality Care", "QUALITY", "QUALITY30", "2025-07-18")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == APPLIED


# ------------------------------------------------------------------ rejecting

def test_long_suspension_is_not_merged():
    """SPENTEX last printed 0.75 in Sept 2020 and resumed as CLCIND at 8.96 in
    Jan 2026. Same company, but merging manufactures a 12x overnight return."""
    bars = _bars({"SPENTEX": ("2020-01-01", "2020-09-01", 1.0, 0.75),
                  "CLCIND": ("2026-01-30", "2026-08-18", 8.96, 12.0)})
    ch = _changes([("CLC Industries Limited", "SPENTEX", "CLCIND", "2026-01-01")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == "long_gap"
    assert m.loc[0, "canonical"] is None or pd.isna(m.loc[0, "canonical"])


def test_price_break_is_not_merged():
    bars = _bars({"OLDCO": ("2020-01-01", "2023-06-30", 100.0, 100.0),
                  "NEWCO": ("2023-07-03", "2026-08-18", 210.0, 250.0)})
    ch = _changes([("Newco Limited", "OLDCO", "NEWCO", "2023-07-03")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == "price_break"


def test_overlap_is_not_merged():
    """Both tickers trading at once is a reused ticker, not a rename."""
    bars = _bars({"OLDCO": ("2020-01-01", "2024-12-31", 100.0, 100.0),
                  "NEWCO": ("2023-01-02", "2026-08-18", 100.0, 120.0)})
    ch = _changes([("Newco Limited", "OLDCO", "NEWCO", "2023-01-02")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == "overlap"


def test_self_rename_is_ignored():
    """NSE files company-name changes under an unchanged ticker."""
    bars = _bars({"QUALITY30": ("2025-07-21", "2026-08-18", 100.0, 130.0)})
    ch = _changes([("Quality Care", "QUALITY30", "QUALITY30", "2025-07-21")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == "self"
    assert canonical_map(m) == {}


def test_rename_outside_the_window_is_absent_not_applied():
    bars = _bars({"NEWCO": ("2020-01-01", "2026-08-18", 100.0, 130.0)})
    ch = _changes([("Newco Limited", "OLDCO", "NEWCO", "2015-04-01")])
    m = build_rename_map(bars, ch)
    assert m.loc[0, "status"] == "absent"


def test_changes_touching_nothing_are_dropped():
    """The published file reaches back to 1999 and is mostly mutual funds."""
    bars = _bars({"NEWCO": ("2020-01-01", "2026-08-18", 100.0, 130.0)})
    ch = _changes([("Nippon India MF", "RDAXEDG", "NDAXEDG", "2019-10-30")])
    assert build_rename_map(bars, ch).empty


# --------------------------------------------------------------------- chains

def test_chain_collapses_to_the_final_ticker():
    """Sudarshan Colorants: CLNINDIA -> HEUBACHIND -> SUDARCOLOR."""
    bars = _bars({"CLNINDIA": ("2020-01-01", "2023-03-09", 100.0, 105.0),
                  "HEUBACHIND": ("2023-03-10", "2026-01-19", 105.0, 400.0),
                  "SUDARCOLOR": ("2026-01-20", "2026-08-18", 400.0, 450.0)})
    ch = _changes([("Sudarshan Colorants", "CLNINDIA", "HEUBACHIND", "2023-03-10"),
                   ("Sudarshan Colorants", "HEUBACHIND", "SUDARCOLOR", "2026-01-20")])
    m = build_rename_map(bars, ch)
    assert canonical_map(m) == {"CLNINDIA": "SUDARCOLOR", "HEUBACHIND": "SUDARCOLOR"}
    merged = apply_renames(bars, m)
    assert set(merged["symbol"]) == {"SUDARCOLOR"}


def test_a_broken_link_stops_the_chain():
    """WEIZFOREX -> EBIXFOREX is a 55-day suspension and is rejected; the
    surviving EBIXFOREX -> DELPHIFX link must still apply, and WEIZFOREX must
    not be dragged across the gap it was rejected for."""
    bars = _bars({"WEIZFOREX": ("2020-01-01", "2020-02-26", 400.0, 391.9),
                  "EBIXFOREX": ("2020-04-21", "2021-08-31", 514.8, 500.0),
                  "DELPHIFX": ("2021-09-01", "2026-08-18", 500.0, 600.0)})
    ch = _changes([("Delphi World Money", "WEIZFOREX", "EBIXFOREX", "2020-03-20"),
                   ("Delphi World Money", "EBIXFOREX", "DELPHIFX", "2021-09-01")])
    m = build_rename_map(bars, ch)
    assert canonical_map(m) == {"EBIXFOREX": "DELPHIFX"}
    assert set(apply_renames(bars, m)["symbol"]) == {"WEIZFOREX", "DELPHIFX"}


# ------------------------------------------------------------------- guarding

def test_ticker_reuse_fails_loudly():
    """A plain symbol->symbol map is only safe because tickers are not reused.
    If NSE ever reissues one, this must raise rather than weld two companies
    into a single series."""
    bars = _bars({"OLDCO": ("2020-01-01", "2022-12-30", 100.0, 100.0),
                  "NEWCO": ("2023-01-02", "2026-08-18", 100.0, 120.0)})
    m = build_rename_map(bars, _changes(
        [("Newco Limited", "OLDCO", "NEWCO", "2023-01-02")]))
    assert m.loc[0, "status"] == APPLIED
    # A later listing reusing the retired ticker on dates NEWCO also trades.
    reused = _bars({"OLDCO": ("2025-01-01", "2026-08-18", 50.0, 60.0)})
    with pytest.raises(RuntimeError, match="reused"):
        apply_renames(pd.concat([bars, reused], ignore_index=True), m)


def test_empty_map_is_a_no_op():
    bars = _bars({"NEWCO": ("2020-01-01", "2026-08-18", 100.0, 130.0)})
    out = apply_renames(bars, pd.DataFrame())
    pd.testing.assert_frame_equal(out, bars)


# ------------------------------------------------------------------ live file

@pytest.mark.network
def test_published_file_parses_and_contains_known_renames():
    ch = fetch_symbol_changes()
    pairs = set(zip(ch["old_symbol"], ch["new_symbol"]))
    assert {("MINDAIND", "UNOMINDA"), ("AMIORG", "ACUTAAS"),
            ("TIDEWATER", "VEEDOL")} <= pairs
    assert ch["change_date"].notna().all()
