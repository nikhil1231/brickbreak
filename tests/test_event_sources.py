"""Parsers for the three corporate-event feeds.

Every fixture here is the real shape of a real payload, trimmed. The fields
that get their own test are the ones that were measured to misbehave against
the live site on 2026-08-22 — Indian digit grouping in deal quantities, the
date-only timestamp era in announcements, and the two result regimes with
their different spellings for the same facts.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src.research_data.sources import announcements, deals, filings, nse_api


# ------------------------------------------------------------------- deals

BULK_CSV = (
    b'\xef\xbb\xbf"Date ","Symbol ","Security Name ","Client Name ",'
    b'"Buy / Sell ","Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "\n'
    b'"21-AUG-2025","ADL","Archidply Decor Limted","ZALA SHAILENDRASINH C",'
    b'"BUY","24,183","99.14","-"\n'
    b'"21-AUG-2025","ATALREAL","Atal Realtech Limited","PASHUPATI CAPITA SER PVT LTD",'
    b'"SELL","6,91,650","19.00","-"\n'
)


def test_indian_digit_grouping_is_stripped():
    """"6,91,650" is 691650, not 6.9150 and not NaN.

    Indian grouping puts separators every two digits after the first three, so
    a parser written for thousands separators either mangles the number or
    drops the row. Both failures are silent and both understate large deals,
    which are the only ones worth looking at.
    """
    df = deals.parse(BULK_CSV, "bulk")
    assert df["quantity"].tolist() == [24183.0, 691650.0]
    assert df["price"].tolist() == [99.14, 19.0]


def test_deal_side_survives_parsing():
    """A round trip is two rows; losing the side turns selling into buying."""
    df = deals.parse(BULK_CSV, "bulk")
    assert df["side"].tolist() == ["BUY", "SELL"]


def test_empty_cells_become_na_not_the_string_dash():
    df = deals.parse(BULK_CSV, "bulk")
    assert df["remarks"].isna().all()


def test_deal_type_is_recorded_on_every_row():
    """Bulk and block deals share a schema and mean different things."""
    assert deals.parse(BULK_CSV, "block")["deal_type"].unique().tolist() == ["block"]


def test_empty_extract_keeps_the_schema():
    """NSE returns zero bytes, not a header row, for an empty window."""
    df = deals.parse(b"", "bulk")
    assert df.empty
    assert list(df.columns) == deals.COLUMNS


def test_year_chunks_never_exceed_a_year():
    """A range wider than one year returns HTTP 500 from this endpoint."""
    from datetime import date

    windows = list(deals._chunk_years(date(2004, 3, 1), date(2007, 2, 1)))
    assert windows[0] == (date(2004, 3, 1), date(2004, 12, 31))
    assert windows[-1] == (date(2007, 1, 1), date(2007, 2, 1))
    assert all((b - a).days < 366 for a, b in windows)


# ----------------------------------------------------------- announcements

def _ann(**kw) -> dict:
    base = {
        "symbol": "SHREDIGCEM", "sm_name": "Shree Digvijay Cement Co.Ltd",
        "sm_isin": "INE232A01011", "smIndustry": None,
        "desc": "General Updates", "attchmntText": "informed the Exchange",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/x.pdf",
        "fileSize": "3.88 MB", "an_dt": "20-Aug-2026 23:56:28",
        "exchdisstime": "20-Aug-2026 23:56:28", "difference": "00:00:00",
        "seq_id": "106751826", "hasXbrl": True,
    }
    base.update(kw)
    return base


def test_a_zero_time_is_not_a_known_time():
    """NSE ships a literal zero, not an absent field, for its early era.

    Every one of the 1,578 announcements in June 2005 reads
    "30-Jun-2005 00:00:00" with `exchdisstime` of "-". So "does the source
    string contain a colon" is NOT the test — it passes for all of them and
    marks the whole pre-2008 archive as disseminated at midnight, i.e.
    tradable at that morning's open. That is a full trading day of lookahead
    across several years, and it is the bug this assertion pins.
    """
    df = announcements.parse([_ann(an_dt="30-Jun-2005 00:00:00", exchdisstime="-")])
    assert bool(df.loc[0, "time_known"]) is False
    assert df.loc[0, "broadcast_at"] == pd.Timestamp("2005-06-30")


def test_a_genuine_midnight_filing_is_still_known():
    """NSE's overnight batch really does disseminate at 00:00:04.

    So the rule cannot simply be "midnight means unknown" either: a non-zero
    time-of-day is a real one, however close to midnight it sits.
    """
    df = announcements.parse([_ann(an_dt="19-Aug-2026 00:00:04")])
    assert bool(df.loc[0, "time_known"]) is True
    assert df.loc[0, "broadcast_at"] == pd.Timestamp("2026-08-19 00:00:04")


def test_a_dissemination_stamp_rescues_an_exact_midnight_broadcast():
    """A real filing at exactly 00:00:00 still carries a dissemination time.

    The early era is distinguished by having neither, not by the broadcast
    clock alone.
    """
    df = announcements.parse([_ann(an_dt="19-Aug-2026 00:00:00",
                                   exchdisstime="19-Aug-2026 00:01:12")])
    assert bool(df.loc[0, "time_known"]) is True


def test_both_disclosure_timestamps_are_kept():
    df = announcements.parse([_ann(an_dt="20-Aug-2026 14:45:47",
                                   exchdisstime="20-Aug-2026 14:46:01")])
    assert df.loc[0, "broadcast_at"] == pd.Timestamp("2026-08-20 14:45:47")
    assert df.loc[0, "disseminated_at"] == pd.Timestamp("2026-08-20 14:46:01")


def test_month_chunks_cover_the_range_exactly():
    from datetime import date

    windows = list(announcements._chunk_months(date(2020, 1, 15), date(2020, 3, 10)))
    assert windows[0] == (date(2020, 1, 15), date(2020, 1, 31))
    assert windows[1] == (date(2020, 2, 1), date(2020, 2, 29))
    assert windows[2] == (date(2020, 3, 1), date(2020, 3, 10))


# ------------------------------------------------------------ result filings

LEGACY_REC = {
    "symbol": "HDFCBANK", "companyName": "HDFC Bank Limited",
    "isin": "INE040A01018", "fromDate": "01-Oct-2024", "toDate": "31-Dec-2024",
    "period": "Quarterly", "relatingTo": "Third Quarter",
    "financialYear": "01-Apr-2024 To 31-Mar-2025", "consolidated": "Consolidated",
    "audited": "Un-Audited", "cumulative": "Non-cumulative", "indAs": "Non-Ind-AS",
    "bank": "B", "broadCastDate": "23-Jan-2025 12:27:21",
    "filingDate": "23-Jan-2025 12:27", "exchdisstime": "23-Jan-2025 12:28:01",
    "difference": "00:00:40", "seqNumber": "1190261",
    "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/BANKING_1.xml",
    "resultDetailedDataLink": None,
}

INTEGRATED_REC = {
    "symbol": "HDFCBANK", "cmName": "HDFC Bank Limited",
    "qe_Date": "30-JUN-2026", "consolidated": "Consolidated",
    "audited": "Un-Audited", "broadcast_Date": "18-Jul-2026 16:01:12",
    "creation_Date": "18-Jul-2026 16:01:26", "diff": "00:00:14",
    "seq_Id": "175752", "type": "Integrated Filing- Financials",
    "type_Sub": "Original", "revised_Date": None, "revision_Remark": None,
    "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_1.xml",
    "ixbrl": "https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_1.html",
    "pdf_attach": "https://nsearchives.nseindia.com/corporate/null",
}


def test_legacy_uses_the_broadcast_time_not_the_period_end():
    df = filings.parse_legacy([LEGACY_REC])
    assert df.loc[0, "period_end"] == pd.Timestamp("2024-12-31")
    assert df.loc[0, "broadcast_at"] == pd.Timestamp("2025-01-23 12:27:21")
    assert df.loc[0, "regime"] == "legacy"
    assert bool(df.loc[0, "is_bank"]) is True


def test_governance_filings_are_dropped_from_the_results_table():
    """The integrated endpoint serves both; only one can carry financials."""
    gov = {**INTEGRATED_REC, "type": "Integrated Filing- Governance"}
    assert filings.parse_integrated([gov]).empty
    assert len(filings.parse_integrated([INTEGRATED_REC])) == 1


def test_integrated_leaves_the_period_start_missing_rather_than_guessing():
    """The feed states a quarter-end only, and the field also carries
    half-yearly and annual filings, so a quarter-start is an assumption."""
    df = filings.parse_integrated([INTEGRATED_REC])
    assert pd.isna(df.loc[0, "period_start"])
    assert df.loc[0, "period_end"] == pd.Timestamp("2026-06-30")


def test_a_null_pdf_attachment_is_not_a_url():
    df = filings.parse_integrated([INTEGRATED_REC])
    assert pd.isna(df.loc[0, "pdf_url"])


def test_a_restatement_does_not_replace_the_original():
    """RELIANCE has 6 such periods, SUZLON 8 — measured, not hypothetical.

    Both versions must survive: the original is what the market traded on,
    the revision is what is true. Keying on (symbol, period) keeps only one
    and it is always the wrong one for a backtest.
    """
    original = {**LEGACY_REC, "seqNumber": "1", "broadCastDate": "23-Jan-2025 12:27:21"}
    revised = {**LEGACY_REC, "seqNumber": "2", "broadCastDate": "05-Feb-2025 09:10:00"}
    df = filings.mark_revisions(filings.parse_legacy([revised, original]))
    assert len(df) == 2
    assert df["revision_number"].tolist() == [0, 1]
    assert df.loc[0, "is_latest"] is False or df.loc[0, "is_latest"] == False
    assert bool(df.loc[1, "is_latest"]) is True
    # The later filing points back at the one it replaced.
    assert df.loc[1, "supersedes"] == df.loc[0, "filing_id"]


def test_filing_id_distinguishes_versions_of_one_period():
    a = filings.filing_id("RELIANCE", pd.Timestamp("2024-12-31"), "consolidated", "1")
    b = filings.filing_id("RELIANCE", pd.Timestamp("2024-12-31"), "consolidated", "2")
    assert a != b


def test_both_regimes_union_into_one_schema():
    both = pd.concat([filings.parse_legacy([LEGACY_REC]),
                      filings.parse_integrated([INTEGRATED_REC])],
                     ignore_index=True)
    assert list(both.columns) == filings.COLUMNS
    assert set(both["regime"]) == {"legacy", "integrated"}


# ----------------------------------------------------------------- decoding

def test_decode_json_handles_both_envelope_shapes():
    """Announcements return a bare list; the deals route wraps in {"data":...}."""
    assert nse_api.decode_json(json.dumps([{"a": 1}]).encode()) == [{"a": 1}]
    assert nse_api.decode_json(json.dumps({"data": [{"a": 1}]}).encode()) == [{"a": 1}]
    assert nse_api.decode_json(b"") == []
    assert nse_api.decode_json(b"<html>blocked</html>") == []


def test_a_challenge_page_is_treated_as_a_block_not_as_data():
    """NSE serves its challenge page with status 200 as readily as with 503."""
    import requests

    class _Resp:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b"<html>Access Denied</html>"

    class _Session:
        def get(self, *a, **kw):
            return _Resp()

    client = nse_api.Client(area="deals", throttle=0.0, max_retries=2)
    client._session = _Session()
    client.prime = lambda: client._session
    with pytest.raises(nse_api.NSEBlocked):
        client.get("https://example.invalid/api", {}, want="json")
