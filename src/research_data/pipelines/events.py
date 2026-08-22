"""Corporate events, timestamped by when the market could first know them.

WHY THIS MODULE EXISTS SEPARATELY FROM THE COLLECTORS
`sources/deals.py`, `sources/announcements.py` and `sources/filings.py` fetch
and parse; none of them decides *when* a row became knowable. That decision is
made once, here, because it is the decision this project keeps getting wrong.
Four distinct non-price lookaheads have been caught in this codebase and none
of them was in an obvious place (`AGENTS.md`). An event dataset is a fifth
opportunity: every row carries an appealing date that is not the date the
information was available.

    a bulk deal dated 14-Aug     was published after the close on 14-Aug
    a result for the quarter to 31-Dec   was broadcast on 23-Jan
    an announcement dated 2005-06-03     carries no time at all

THE THREE RULES

1. **`available_at` is derived, never taken.** For announcements and filings
   it is the later of broadcast and dissemination, both of which the exchange
   records. For deals it is the close of the deal date plus the publication
   lag, because the deal report is an end-of-day file. The period end, the
   deal date and the filing date are never used as availability.

2. **A missing time is not midnight.** NSE's pre-2008 announcements and its
   pre-2007 result broadcasts carry a date with no time. Parsing those to
   00:00:00 hands an experiment the entire trading day for free. Where
   `time_known` is False, availability is pushed to the *end* of that day,
   which is the weakest claim consistent with the evidence.

3. **Availability is converted to a session, and the session is the join
   key.** `first_tradable_session` is the first trading day whose open comes
   strictly after `available_at`. An event disseminated at 14:45 is not
   tradable at that day's open, so it belongs to the next session — and an
   event disseminated at 07:00 belongs to the same day. Joining an event
   table to the daily panel on the raw date instead is the H015 lookahead
   wearing different clothes.

WHAT IS DELIBERATELY NOT DONE HERE
No signal is computed. There is no "days since last bulk deal", no earnings
surprise, no announcement sentiment. Those are features and belong to a
hypothesis family with a catalogue entry, not to the data layer.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ...core import config
from ..sources import announcements as ann_src
from ..sources import deals as deals_src
from ..sources import filings as filings_src

DEALS_PATH = config.NORMALIZED_DIR / "deals.parquet"
ANNOUNCEMENTS_PATH = config.NORMALIZED_DIR / "announcements.parquet"
FILINGS_PATH = config.NORMALIZED_DIR / "financial_result_filings.parquet"

# NSE's continuous session. The open is what an event has to beat to be
# actionable on a given day; `AGENTS.md` records that the pre-open auction
# prints at 09:15:00 and that bhavcopy's OPEN comes from it.
MARKET_OPEN = pd.Timedelta(hours=9, minutes=15)
MARKET_CLOSE = pd.Timedelta(hours=15, minutes=30)

# Bulk/block deal reports are an end-of-day publication. NSE does not stamp
# them with a publication time, so the close is used as the floor and the
# rule that actually protects an experiment is the session mapping below:
# whatever the true publication minute, it is after the close, so the first
# tradable session is the next one.
DEAL_PUBLICATION = MARKET_CLOSE


def _end_of_day(ts: pd.Series) -> pd.Series:
    return ts.dt.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)


def availability(broadcast_at: pd.Series, disseminated_at: pd.Series,
                 time_known: pd.Series) -> pd.Series:
    """When a disclosed event became public.

    The later of broadcast and dissemination: the two differ by seconds
    normally, but the exchange's own dissemination is the moment the market
    could act, and where one is missing the other stands in.
    """
    later = pd.concat([broadcast_at, disseminated_at], axis=1).max(axis=1)
    known = time_known.fillna(False).astype(bool)
    return later.where(known, _end_of_day(later))


def deal_availability(deal_date: pd.Series) -> pd.Series:
    return deal_date.dt.normalize() + DEAL_PUBLICATION


def trading_sessions() -> pd.DatetimeIndex:
    """Every session the tape holds, from the daily bars.

    The calendar is taken from the data rather than from a weekday rule: NSE
    trades on some Saturdays and Sundays and closes on a shifting list of
    holidays, and a synthetic calendar would silently move events onto days
    that never traded.
    """
    import pandas as _pd

    path = config.NORMALIZED_DIR / "daily_bars.parquet"
    if not path.exists():
        return _pd.DatetimeIndex([])
    dates = _pd.read_parquet(path, columns=["date"])["date"]
    return _pd.DatetimeIndex(sorted(dates.dropna().unique()))


def attach_tradable_session(events: pd.DataFrame,
                            sessions: pd.DatetimeIndex | None = None,
                            *, column: str = "available_at") -> pd.DataFrame:
    """Add `first_tradable_session`: the first open strictly after availability.

    `searchsorted` on session opens, with side="right" so an event landing
    exactly at 09:15:00 is treated as *not* actionable at that open. The
    boundary matters more than it looks: NSE's overnight batch disseminates a
    block of announcements at 00:00:0x, and getting the inequality backwards
    would make every one of them tradable at an open it preceded by nine hours
    — which is correct — while an event at exactly the opening print would be
    claimed as tradable at a price it may itself have caused.

    AN EVENT OUTSIDE THE TAPE HAS NO SESSION, IN EITHER DIRECTION
    `session_status` records why a row is unresolved, because the two reasons
    are not the same thing and neither is a lookahead:

      * `after_tape` — published after the last session we hold. Not tradable
        yet; it will be, once the tape catches up.
      * `unknown_availability` — the source carries no usable disclosure
        timestamp at all. NSE's 2005-2007 result records were backfilled
        without one; there are 86 across five symbols. They cannot be dated
        and must not be guessed at.
      * `before_tape` — available before our calendar begins. The naive
        `searchsorted` answer here is index 0, i.e. the panel's *first*
        session, and it is wrong in a way that manufactures data: the deal or
        filing was tradable years earlier, at a session we do not hold. Left
        alone it piles every pre-history event onto one day — measured on the
        real archive, 538 result filings from 2007-2019 all landed on
        2020-01-01 — which any "events in the last N sessions" feature reads
        as a genuine spike. It is not a lookahead, it is a misdating, and it
        is worse for being plausible.

    The cut is the calendar date of the first session, not its open, so an
    event at 00:00:04 on the tape's first day still resolves to it: no session
    can have been missed inside that day.
    """
    out = events.copy()
    if sessions is None:
        sessions = trading_sessions()
    if len(sessions) == 0 or out.empty:
        out["first_tradable_session"] = pd.NaT
        out["session_status"] = "no_calendar"
        return out

    sessions = pd.DatetimeIndex(sessions)
    opens = sessions.normalize() + MARKET_OPEN
    avail = pd.to_datetime(out[column])
    idx = opens.searchsorted(avail.values, side="right")

    # A missing availability is not a late one. NSE backfilled its 2005-2007
    # result records without any broadcast timestamp, and `searchsorted` sorts
    # NaT to the end, which would file all 86 of them as "published after the
    # last session" — i.e. as the newest filings in the archive. They are the
    # oldest. Unknown gets its own status and no session.
    unknown = avail.isna().to_numpy()
    before = (avail < sessions.min().normalize()).to_numpy() & ~unknown
    after = (idx >= len(opens)) & ~unknown & ~before
    resolved = ~unknown & ~before & ~after

    session = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    session[resolved] = sessions[idx[resolved]]
    out["first_tradable_session"] = session.values
    out["session_status"] = np.select(
        [resolved, before, after], ["resolved", "before_tape", "after_tape"],
        default="unknown_availability")
    return out


# ------------------------------------------------------------------- builds

def build_deals(sessions: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    df = deals_src.load()
    if df.empty:
        return df
    df["available_at"] = deal_availability(df["deal_date"])
    df["time_known"] = False        # no publication time is stamped, ever
    return attach_tradable_session(df, sessions)


def build_announcements(sessions: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    df = ann_src.load()
    if df.empty:
        return df
    df["available_at"] = availability(df["broadcast_at"], df["disseminated_at"],
                                      df["time_known"])
    return attach_tradable_session(df, sessions)


def build_filings(sessions: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    df = filings_src.load()
    if df.empty:
        return df
    df["available_at"] = availability(df["broadcast_at"], df["disseminated_at"],
                                      df["time_known"])
    return attach_tradable_session(df, sessions)


def build(verbose: bool = True) -> dict:
    """Build all three event tables from the cached raw payloads."""
    config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    sessions = trading_sessions()
    stats = {"sessions_known": len(sessions)}
    for name, fn, path in (("deals", build_deals, DEALS_PATH),
                           ("announcements", build_announcements, ANNOUNCEMENTS_PATH),
                           ("filings", build_filings, FILINGS_PATH)):
        df = fn(sessions)
        if df.empty:
            stats[name] = {"rows": 0}
            continue
        df.to_parquet(path, index=False)
        status = df["session_status"].value_counts().to_dict()
        no_time = int((~df["time_known"].astype(bool)).sum())
        stats[name] = {"rows": len(df), "symbols": int(df["symbol"].nunique()),
                       "first": str(df["available_at"].min()),
                       "last": str(df["available_at"].max()),
                       "without_a_stamped_time": no_time,
                       "resolved_to_a_session": int(status.get("resolved", 0)),
                       "published_after_the_tape": int(status.get("after_tape", 0)),
                       "predates_the_tape": int(status.get("before_tape", 0)),
                       "no_availability_timestamp": int(
                           status.get("unknown_availability", 0)),
                       "path": str(path.relative_to(config.PROJECT_ROOT))}
        if verbose:
            print(f"  {name:14} {len(df):8,} rows  "
                  f"{stats[name]['first'][:10]} .. {stats[name]['last'][:10]}  "
                  f"({no_time:,} without a stamped time)", flush=True)
    return stats


# -------------------------------------------------------------------- reads

def load_deals() -> pd.DataFrame:
    return pd.read_parquet(DEALS_PATH)


def load_announcements() -> pd.DataFrame:
    return pd.read_parquet(ANNOUNCEMENTS_PATH)


def load_filings() -> pd.DataFrame:
    return pd.read_parquet(FILINGS_PATH)


__all__ = [
    "ANNOUNCEMENTS_PATH", "DEALS_PATH", "FILINGS_PATH", "MARKET_CLOSE",
    "MARKET_OPEN", "attach_tradable_session", "availability", "build",
    "build_announcements", "build_deals", "build_filings", "deal_availability",
    "load_announcements", "load_deals", "load_filings", "trading_sessions",
]
