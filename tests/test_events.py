"""When a corporate event became knowable, and which session it belongs to.

This is the lookahead surface of the event datasets. Every test here pins a
rule that, if it broke, would let an experiment act on information before it
existed — quietly, and with a plausible-looking frame as the evidence.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.research_data.pipelines import events


def _sessions(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(d) for d in days])


# --------------------------------------------------------------- availability

def test_a_deal_is_not_available_on_its_own_deal_date():
    """The bulk-deal file is published after the close.

    Treating the deal date as the availability date lets a strategy buy
    alongside a fund at the price the fund paid, on the day it paid it. The
    published file is the first anyone outside the trade sees it.
    """
    deal_date = pd.Series([pd.Timestamp("2026-08-14")])
    avail = events.deal_availability(deal_date)
    assert avail.iloc[0] == pd.Timestamp("2026-08-14 15:30:00")
    assert avail.iloc[0] > pd.Timestamp("2026-08-14 09:15:00")


def test_availability_is_the_later_of_broadcast_and_dissemination():
    broadcast = pd.Series([pd.Timestamp("2026-08-20 14:45:47")])
    disseminated = pd.Series([pd.Timestamp("2026-08-20 14:46:01")])
    got = events.availability(broadcast, disseminated, pd.Series([True]))
    assert got.iloc[0] == pd.Timestamp("2026-08-20 14:46:01")


def test_a_missing_time_pushes_availability_to_the_end_of_the_day():
    """Every 2005 announcement carries a date and no time.

    The weakest claim consistent with "it happened that day" is that it was
    known by the end of it. Reading the parsed 00:00:00 literally would make
    every pre-2008 announcement tradable at that morning's open, which is a
    full trading day of lookahead across three years of the archive.
    """
    stamp = pd.Series([pd.Timestamp("2005-06-03")])
    got = events.availability(stamp, stamp, pd.Series([False]))
    assert got.iloc[0] == pd.Timestamp("2005-06-03 23:59:59")


def test_a_real_midnight_filing_keeps_its_timestamp():
    stamp = pd.Series([pd.Timestamp("2026-08-19 00:00:04")])
    got = events.availability(stamp, stamp, pd.Series([True]))
    assert got.iloc[0] == pd.Timestamp("2026-08-19 00:00:04")


# ------------------------------------------------------------ session mapping

def test_an_intraday_event_belongs_to_the_next_session():
    """Disseminated at 14:45 on Thursday -> first tradable at Friday's open."""
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-08-20 14:45:47")]})
    out = events.attach_tradable_session(
        df, _sessions("2026-08-20", "2026-08-21"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp("2026-08-21")


def test_an_overnight_event_belongs_to_the_same_session():
    """NSE's batch disseminates at 00:00:0x; that is before the 09:15 open."""
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-08-20 00:00:04")]})
    out = events.attach_tradable_session(
        df, _sessions("2026-08-19", "2026-08-20", "2026-08-21"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp("2026-08-20")


def test_an_event_exactly_at_the_open_is_not_tradable_at_that_open():
    """The opening print is an auction the event may itself have moved.

    Claiming it would be assuming a fill at a price formed from information
    that arrived at the same instant.
    """
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-08-20 09:15:00")]})
    out = events.attach_tradable_session(df, _sessions("2026-08-20", "2026-08-21"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp("2026-08-21")


def test_the_session_calendar_comes_from_the_tape_not_from_weekdays():
    """NSE trades on some Saturdays; a weekday rule moves events off them.

    2026-08-15 is a Saturday here. If it traded, an event available on Friday
    evening belongs to it, not to the following Monday.
    """
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-08-14 18:00:00")]})
    out = events.attach_tradable_session(
        df, _sessions("2026-08-14", "2026-08-15", "2026-08-17"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp("2026-08-15")


def test_a_holiday_is_skipped_because_it_is_absent_from_the_tape():
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-08-14 18:00:00")]})
    out = events.attach_tradable_session(df, _sessions("2026-08-14", "2026-08-19"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp("2026-08-19")


def test_an_event_after_the_last_known_session_has_no_session():
    """It is not yet tradable, and inventing a date would be a forward fill."""
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-09-01 10:00:00")]})
    out = events.attach_tradable_session(df, _sessions("2026-08-20"))
    assert pd.isna(out.loc[0, "first_tradable_session"])


def test_an_empty_calendar_does_not_invent_sessions():
    df = pd.DataFrame({"available_at": [pd.Timestamp("2026-08-20 10:00:00")]})
    out = events.attach_tradable_session(df, pd.DatetimeIndex([]))
    assert out["first_tradable_session"].isna().all()


# --------------------------------------------------------- the joint property

@pytest.mark.parametrize("stamp,expected", [
    ("2026-08-19 09:14:59", "2026-08-19"),   # a minute before the open
    ("2026-08-19 09:15:00", "2026-08-20"),   # at the open
    ("2026-08-19 15:29:00", "2026-08-20"),   # during the session
    ("2026-08-19 23:59:59", "2026-08-20"),   # end of a date-only day
])
def test_the_boundary_is_the_open_of_the_session_being_joined(stamp, expected):
    df = pd.DataFrame({"available_at": [pd.Timestamp(stamp)]})
    out = events.attach_tradable_session(
        df, _sessions("2026-08-19", "2026-08-20", "2026-08-21"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp(expected)


def test_no_event_is_ever_tradable_before_it_is_available():
    """The invariant the whole module exists to hold, over a mixed sample."""
    sessions = _sessions("2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20")
    df = pd.DataFrame({"available_at": pd.to_datetime([
        "2026-08-17 00:00:04", "2026-08-17 09:15:00", "2026-08-17 15:30:00",
        "2026-08-18 23:59:59", "2026-08-19 08:00:00", "2026-08-19 12:00:00",
    ])})
    out = events.attach_tradable_session(df, sessions)
    opens = out["first_tradable_session"] + events.MARKET_OPEN
    assert (opens > out["available_at"]).all()


# ------------------------------------------------- events outside the tape

def test_an_event_predating_the_tape_is_not_dated_to_its_first_session():
    """The bug this rule exists for, caught on the real archive.

    `searchsorted` answers index 0 for anything before the calendar starts, so
    a 2007 result filing is reported as first tradable on the panel's opening
    day. It was tradable in 2007; the tape simply does not reach that far.
    Measured before the fix: 538 filings from 2007-2019 all landed on
    2020-01-01, which any "events in the last N sessions" feature reads as a
    real spike on day one.
    """
    df = pd.DataFrame({"available_at": [pd.Timestamp("2007-07-10 13:42:01")]})
    out = events.attach_tradable_session(
        df, _sessions("2020-01-01", "2020-01-02"))
    assert pd.isna(out.loc[0, "first_tradable_session"])
    assert out.loc[0, "session_status"] == "before_tape"


def test_an_event_on_the_tapes_first_day_still_resolves():
    """The cut is the first session's date, not its open.

    No session can hide inside that day, so an overnight dissemination at
    00:00:04 on the opening day is genuinely tradable at that open.
    """
    df = pd.DataFrame({"available_at": [pd.Timestamp("2020-01-01 00:00:04")]})
    out = events.attach_tradable_session(
        df, _sessions("2020-01-01", "2020-01-02"))
    assert out.loc[0, "first_tradable_session"] == pd.Timestamp("2020-01-01")
    assert out.loc[0, "session_status"] == "resolved"


def test_the_two_unresolved_reasons_are_distinguished():
    """"not yet" and "long ago" are opposite problems and must not be pooled."""
    df = pd.DataFrame({"available_at": pd.to_datetime(
        ["2007-07-10 13:42:01", "2020-01-02 12:00:00", "2026-09-01 10:00:00"])})
    out = events.attach_tradable_session(
        df, _sessions("2020-01-01", "2020-01-02", "2020-01-03"))
    assert out["session_status"].tolist() == ["before_tape", "resolved", "after_tape"]


def test_a_missing_availability_is_not_the_newest_event():
    """NSE backfilled its 2005-2007 result records with no broadcast time.

    `searchsorted` sorts NaT to the end of the calendar, so without this the
    oldest filings in the archive are reported as published after the most
    recent session — the maximum possible misdating, in the wrong direction.
    """
    df = pd.DataFrame({"available_at": pd.to_datetime(
        [None, "2020-01-02 08:00:00"])})
    out = events.attach_tradable_session(
        df, _sessions("2020-01-01", "2020-01-02", "2020-01-03"))
    assert out["session_status"].tolist() == ["unknown_availability", "resolved"]
    assert pd.isna(out.loc[0, "first_tradable_session"])
