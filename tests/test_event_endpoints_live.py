"""Live NSE endpoint behaviour, pinned so a change is noticed rather than absorbed.

Excluded from the default run (`-m network`). These are not correctness tests
of our code — they assert the *site's* behaviour, and each one is the evidence
behind a design decision made on 2026-08-22. If one starts failing, the
decision it justifies is the thing to revisit.

    .venv/bin/python -m pytest -m network tests/test_event_endpoints_live.py
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.research_data.sources import announcements, deals, filings, nse_api

pytestmark = pytest.mark.network


def _recent(days_back: int, span: int = 6) -> tuple[date, date]:
    end = date.today() - timedelta(days=days_back)
    return end - timedelta(days=span), end


def test_the_json_deals_route_still_truncates_at_seventy():
    """The reason this package speaks CSV to the deals endpoint.

    The JSON form returns 70 records for any range, keeps the earliest, and
    offers no cursor. If this ever stops being true the CSV detour can go —
    until then, removing it silently caps every deal window at 70 rows.
    """
    client = nse_api.Client(area="deals", throttle=1.0)
    a, b = _recent(7, span=30)
    body = client.get(deals.DEALS_URL,
                      {"optionType": "bulk_deals",
                       "from": a.strftime("%d-%m-%Y"),
                       "to": b.strftime("%d-%m-%Y")}, want="json")
    records = nse_api.decode_json(body)
    assert len(records) == 70, (
        f"the JSON deals route returned {len(records)} rows, not the measured "
        f"cap of 70 — re-check whether the CSV detour is still needed")


def test_the_csv_deals_route_is_complete_over_the_same_window():
    """Same request, `csv=true`: more rows and more than one date."""
    client = nse_api.Client(area="deals", throttle=1.0)
    a, b = _recent(7, span=30)
    df = deals.fetch_window(client, "bulk_deals", a, b, force=True)
    assert len(df) > 70
    assert df["deal_date"].nunique() > 1
    assert df["deal_date"].min().date() >= a
    assert df["deal_date"].max().date() <= b


@pytest.mark.parametrize("option_type,floor", [
    ("bulk_deals", date(2004, 1, 4)),
    ("block_deals", date(2005, 11, 17)),
])
def test_the_deal_archive_reaches_its_measured_floor(option_type, floor):
    """Bulk deals begin 2004-01-04 and block deals 2005-11-17, by bisection."""
    client = nse_api.Client(area="deals", throttle=1.0)
    df = deals.fetch_window(client, option_type, floor,
                            floor + timedelta(days=30), force=True)
    assert not df.empty
    assert df["deal_date"].min().date() <= floor + timedelta(days=7)


def test_the_announcement_feed_has_no_row_cap():
    """Two single days must sum exactly to the two-day range.

    This is the check the deals endpoint fails, and it is the reason
    announcements are fetched by month while deals are fetched by year and
    verified.
    """
    client = nse_api.Client(area="announcements", throttle=1.0)
    d2 = date.today() - timedelta(days=7)
    d1 = d2 - timedelta(days=1)
    one = announcements.fetch_window(client, d1, d1, force=True)
    two = announcements.fetch_window(client, d2, d2, force=True)
    both = announcements.fetch_window(client, d1, d2, force=True)
    assert len(one) + len(two) == len(both)


def test_announcements_carry_the_dissemination_timestamps():
    client = nse_api.Client(area="announcements", throttle=1.0)
    a, b = _recent(7, span=2)
    df = announcements.fetch_window(client, a, b, force=True)
    assert not df.empty
    assert df["broadcast_at"].notna().all()
    assert df["time_known"].all(), "modern announcements should all carry a time"


def test_the_legacy_results_endpoint_is_frozen_at_the_regime_change():
    """It stopped at the 2025-04-01 Integrated Filing switch and did not migrate.

    A pipeline that reads only this endpoint looks healthy and silently holds
    no earnings after 2024-12-31.
    """
    client = nse_api.Client(area="results", throttle=1.0)
    df = filings.fetch_symbol(client, "HDFCBANK", period="Quarterly",
                              regime="legacy", force=True)
    assert not df.empty
    assert df["period_end"].max() < pd.Timestamp(filings.INTEGRATED_FROM)


def test_the_integrated_endpoint_serves_the_post_2025_regime():
    client = nse_api.Client(area="results", throttle=1.0)
    df = filings.fetch_symbol(client, "HDFCBANK", period="Quarterly",
                              regime="integrated", force=True)
    assert not df.empty
    assert df["period_end"].max() >= pd.Timestamp(filings.INTEGRATED_FROM)
    assert (df["regime"] == "integrated").all()


def test_the_results_endpoint_has_no_working_date_range_form():
    """Why the filings collector is per-symbol and therefore expensive."""
    client = nse_api.Client(area="results", throttle=1.0)
    a, b = _recent(7, span=6)
    body = client.get(filings.LEGACY_URL,
                      {"index": "equities", "period": "Quarterly",
                       "from_date": a.strftime("%d-%m-%Y"),
                       "to_date": b.strftime("%d-%m-%Y")}, want="json")
    assert nse_api.decode_json(body) == []


def test_restatements_exist_in_the_wild():
    """RELIANCE carried 6 periods with more than one filing when measured.

    The number may drift; that there is more than one is the property the
    revision machinery depends on.
    """
    client = nse_api.Client(area="results", throttle=1.0)
    df = filings.mark_revisions(
        filings.fetch_symbol(client, "RELIANCE", period="Quarterly",
                             regime="legacy", force=True))
    assert (df["revision_number"] > 0).any()


def test_the_documented_bulk_deals_route_is_dead():
    """`/api/historical/bulk-deals` is the route in every guide, and it 503s.

    This is the correction the whole deals collector rests on: the live route
    is `/api/historicalOR/bulk-block-short-deals`. It is pinned because a
    persistent 503 reads as rate limiting, and a collector written against the
    documented route retries forever instead of failing usefully.
    """
    a, b = _recent(7, span=2)
    client = nse_api.Client(area="deals", throttle=1.0, max_retries=1)
    with pytest.raises(nse_api.NSEBlocked):
        client.get(f"{nse_api.BASE}/api/historical/bulk-deals",
                   {"from": a.strftime("%d-%m-%Y"),
                    "to": b.strftime("%d-%m-%Y")}, want="json")


def test_pre_2018_xbrl_filings_are_no_longer_served():
    """The metadata reaches 2005; the filings themselves start at 2018.

    Measured across five symbols: 556 of 940 linked XBRL URLs 404, and the
    boundary is a date rather than a symbol — nothing with a period end before
    2018-03-31 was retrievable. An earnings pipeline that assumes the metadata
    depth is the data depth is off by thirteen years.
    """
    import requests

    from src.research_data.sources import xbrl as xbrl_mod

    client = nse_api.Client(area="results", throttle=1.0)
    df = filings.fetch_symbol(client, "RELIANCE", period="Quarterly",
                              regime="legacy", force=True)
    old = df[df["period_end"] < pd.Timestamp("2015-01-01")]
    assert not old.empty, "expected pre-2015 metadata to exist"
    url = old.sort_values("period_end")["xbrl_url"].dropna().iloc[0]
    resp = requests.get(url, headers=nse_api.HEADERS, timeout=60)
    assert resp.status_code == 404, (
        f"{url} now returns {resp.status_code} — pre-2018 filings may have "
        f"been restored; re-measure the retrievable depth")
