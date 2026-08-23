"""Turning NSE's bulk-deal file into events that mean what they appear to mean.

THE PROBLEM THIS MODULE EXISTS FOR
A bulk deal is any trade above 0.5% of a company's equity, and the intuition it
invites — "someone large took a position" — is wrong for most of the file.
Measured on the 113,380 usable bulk rows:

    40.4%  of client-name-days are near-flat round trips: the same client
           bought and sold within the session and ended with nothing
    58.6%  of all bulk volume is done by those flat clients
    38.0%  of rows come from twenty clients, of which 83% are round trips
    72%    of name-days carry both a BUY and a SELL

The names at the top of that list are market makers and proprietary traders —
Graviton, HRTI, NK Securities, QE Securities, XTX. Their intraday turnover
crosses the reporting threshold; their overnight position is zero. Treating
them as "a large buyer appeared" is treating liquidity provision as
information, and the share is rising: 24.5% of rows in 2020, 40.7% by 2026.

So the event this family tests is not "a bulk deal happened". It is **net
directional flow that stayed on the book overnight**, which is a strict and
much smaller subset.

WHY THE CLASSIFICATION MUST BE TRAILING
The obvious implementation — label a client a market maker if their whole
history is round trips — reads the future. A client's 2021 deals would be
classified using their 2025 behaviour. Every leak this project has caught has
had exactly this shape, so `client_profile` is computed on an expanding window
that ends strictly before the session being labelled, and a client with too
little history is `unknown` rather than assumed.

WHAT IS NOT CLAIMED HERE
Nothing in this module reads an outcome. It builds events and features, and it
is safe to run and re-run before any hypothesis is registered or any sample is
spent.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ....research_data import frame

logger = logging.getLogger(__name__)

# A client-name-day whose buys and sells offset by more than this is a round
# trip. Not a knife edge: the distribution is strongly bimodal, with the mass
# either near 0 (one-sided) or near 1 (flat).
FLAT_THRESHOLD = 0.90
# Sessions of prior activity before a client may be profiled at all.
MIN_CLIENT_HISTORY = 10
# A client whose trailing record is this round-trip is treated as a liquidity
# provider rather than a position taker.
LIQUIDITY_PROVIDER_SHARE = 0.60


class BulkDealError(RuntimeError):
    pass


def load(partition: str | None = None, deal_type: str = "bulk",
         **kw: Any) -> pd.DataFrame:
    """Usable deals only: those whose first tradable session is on the tape.

    Goes through `research_data.frame.load_events`, which is the lab's single
    door onto the event tables — it applies the split manifest and the purge
    boundary, so an event and the prices it might explain cannot land on
    opposite sides of one. Reading the parquet here directly would be a second
    access path with none of that, which is what `test_architecture` forbids.
    """
    d = frame.load_events("deals", partition=partition, **kw)
    d = d[d["deal_type"] == deal_type]
    d = d.dropna(subset=["first_tradable_session", "quantity", "price"])
    d = d[d["quantity"] > 0]
    d["session"] = pd.to_datetime(d["first_tradable_session"])
    d["client_name"] = d["client_name"].astype(str).str.strip().str.upper()
    d["signed_qty"] = np.where(d["side"].eq("BUY"), 1.0, -1.0) * d["quantity"]
    d["value"] = d["quantity"] * d["price"]
    return d.reset_index(drop=True)


def client_daybook(deals: pd.DataFrame) -> pd.DataFrame:
    """One row per client per name per session, with how flat they ended."""
    g = deals.groupby(["client_name", "symbol", "session"], sort=False)
    book = g.agg(net_qty=("signed_qty", "sum"),
                 gross_qty=("quantity", "sum"),
                 value=("value", "sum"),
                 n_deals=("quantity", "size")).reset_index()
    # A mean of reported prices gives a one-share print the same influence as
    # a million-share print. The disclosure supplies both quantity and value,
    # so the price attached to an event must be the actual volume-weighted one.
    book["vwap"] = book["value"] / book["gross_qty"]
    book["flatness"] = 1.0 - (book["net_qty"].abs() / book["gross_qty"])
    book["is_round_trip"] = book["flatness"] > FLAT_THRESHOLD
    return book


def client_profile(book: pd.DataFrame) -> pd.DataFrame:
    """Each client's round-trip share **using only their own prior sessions**.

    Expanding and shifted. A profile that included the row it labels would let
    a 2021 deal be classified by 2025 behaviour, which is the H015 lookahead
    with a different column name.
    """
    b = book.sort_values(["client_name", "session"]).copy()
    g = b.groupby("client_name", sort=False)
    prior_n = g.cumcount()
    prior_rt = g["is_round_trip"].transform(
        lambda s: s.shift(1).expanding().sum()).fillna(0.0)

    b["prior_sessions"] = prior_n
    b["prior_round_trip_share"] = np.where(
        prior_n > 0, prior_rt / prior_n.replace(0, np.nan), np.nan)

    b["client_type"] = np.select(
        [prior_n < MIN_CLIENT_HISTORY,
         b["prior_round_trip_share"] >= LIQUIDITY_PROVIDER_SHARE],
        ["unknown", "liquidity_provider"],
        default="position_taker")
    return b


def build_events(deals: pd.DataFrame | None = None,
                 bars: pd.DataFrame | None = None,
                 partition: str | None = None) -> pd.DataFrame:
    """One row per symbol-session, with directional flow separated from noise.

    `bars` supplies point-in-time scale — median volume and turnover from a
    trailing window — so a deal can be expressed as a share of a normal day
    rather than as a raw quantity that means nothing across names.
    """
    deals = load(partition=partition) if deals is None else deals
    book = client_profile(client_daybook(deals))

    directional = book[(book["client_type"] == "position_taker")
                       & (~book["is_round_trip"])]

    def _agg(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        g = frame.groupby(["symbol", "session"], sort=False)
        out = g.agg(**{
            f"{prefix}_net_qty": ("net_qty", "sum"),
            f"{prefix}_gross_qty": ("gross_qty", "sum"),
            f"{prefix}_value": ("value", "sum"),
            f"{prefix}_clients": ("client_name", "nunique"),
        })
        out[f"{prefix}_vwap"] = (
            out[f"{prefix}_value"] / out[f"{prefix}_gross_qty"])
        return out.reset_index()

    ev = _agg(book, "all").merge(_agg(directional, "dir"),
                                 on=["symbol", "session"], how="left")
    for c in ("dir_net_qty", "dir_gross_qty", "dir_value", "dir_clients"):
        ev[c] = ev[c].fillna(0.0)

    ev["round_trip_share"] = 1.0 - (ev["dir_gross_qty"] / ev["all_gross_qty"])
    ev["is_directional"] = ev["dir_clients"] > 0
    ev["direction"] = np.select(
        [ev["dir_net_qty"] > 0, ev["dir_net_qty"] < 0],
        ["accumulation", "distribution"], default="none")

    if bars is not None:
        ev = _scale(ev, bars)
    return ev


def _scale(ev: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Express flow against a normal day, and the deal price against the tape.

    Every scale column is a trailing median computed by the caller and shifted,
    so nothing here sees the session it labels.

    **RAW SPACE, NOT ADJUSTED, AND THIS IS NOT A DETAIL.** A deal prints the
    quantity and the price as they stood on the day. The canonical bars are
    back-adjusted, so in any name that later split or issued a bonus, the
    adjusted close is the deal price divided by the factor and the adjusted
    volume is the deal quantity multiplied by it. Mixing the two spaces does
    not add noise — it manufactures exactly the quantity the feature is
    looking for. Measured on the train directional set before this was fixed:
    24.9% of events sit in a name carrying a later adjustment, 17.7% of
    premiums read beyond +/-20% against 1.1% once both sides are raw, and the
    median premium fell from +1.82% to 0.00%. The whole apparent premium was
    the adjustment factor.
    """
    need = {"symbol", "date", "med_vol_raw", "close_raw"}
    missing = need - set(bars.columns)
    if missing:
        raise BulkDealError(f"bars need {sorted(missing)} to scale flow")

    b = bars[["symbol", "date", "med_vol_raw", "close_raw"]].rename(
        columns={"date": "session"})
    ev = ev.merge(b, on=["symbol", "session"], how="left")

    ev["net_flow_vs_volume"] = ev["dir_net_qty"] / ev["med_vol_raw"]
    ev["gross_flow_vs_volume"] = ev["all_gross_qty"] / ev["med_vol_raw"]
    # Where the deal printed against the day's close. A seller taking a
    # discount is a different event from one lifted at a premium, and this is
    # the cheapest expression of the "who needed the trade more" question.
    ev["deal_vs_close_pct"] = 100.0 * (ev["dir_vwap"] / ev["close_raw"] - 1.0)
    return ev.drop(columns=["med_vol_raw", "close_raw"])


def summarise(ev: pd.DataFrame) -> dict[str, Any]:
    """What the event set looks like, before any outcome is attached."""
    d = ev[ev["is_directional"]]
    return {
        "symbol_sessions": int(len(ev)),
        "directional": int(len(d)),
        "directional_pct": round(100 * len(d) / max(len(ev), 1), 1),
        "sessions": int(ev["session"].nunique()),
        "directional_per_session": round(len(d) / max(d["session"].nunique(), 1), 2),
        "accumulation": int((ev["direction"] == "accumulation").sum()),
        "distribution": int((ev["direction"] == "distribution").sum()),
        "median_round_trip_share": round(float(ev["round_trip_share"].median()), 3),
    }
