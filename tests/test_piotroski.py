"""The H068 gate must fail before accounting or outcome access when XBRL is thin."""
from types import SimpleNamespace

import pandas as pd

from src.research_data.pipelines import piotroski


def selection_book(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for rank, symbol in enumerate(symbols):
        for strike, kind in ((90.0, "PE"), (110.0, "CE")):
            rows.append({"symbol": symbol, "strike": strike,
                         "option_type": kind, "contracts": 500.0 - rank,
                         "lot_size": 100.0, "close": 2.0})
    return pd.DataFrame(rows)


def manifest(symbols: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"symbol": symbols, "status": "ok",
                         "sha256": [f"sha-{s}" for s in symbols]})


def test_archive_coverage_is_an_upper_bound_that_fails_on_thin_xbrl():
    entry = pd.Timestamp("2024-01-25")
    names = [f"S{i:02d}" for i in range(20)]
    tape = SimpleNamespace(
        pairs=[(entry, pd.Timestamp("2024-02-29"),
                pd.Timestamp("2024-02-29"))],
        prior_by_session={entry: selection_book(names)},
    )
    cycles, stats = piotroski.archive_coverage(
        tape, manifest=manifest(names[:5]))
    assert stats["coverage_upper_bound"] == 0.25
    assert stats["median_archived_names_in_top_slots"] == 5
    assert not stats["passes"]
    assert cycles["eligible_names"].iloc[0] == 20


def test_archive_coverage_passes_only_when_both_thresholds_clear():
    entry = pd.Timestamp("2024-01-25")
    names = [f"S{i:02d}" for i in range(20)]
    tape = SimpleNamespace(
        pairs=[(entry, pd.Timestamp("2024-02-29"),
                pd.Timestamp("2024-02-29"))],
        prior_by_session={entry: selection_book(names)},
    )
    _, stats = piotroski.archive_coverage(
        tape, manifest=manifest(names[:16]))
    assert stats["coverage_upper_bound"] == 0.80
    assert stats["median_archived_names_in_top_slots"] == 16
    assert stats["passes"]
