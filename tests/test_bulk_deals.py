"""Bulk-deal events, and the leak the obvious implementation would introduce.

The file NSE publishes does not describe what it appears to describe: 40% of
client-name-days are round trips and 59% of the volume belongs to clients who
end the session flat. Separating those out is the whole job of this module, and
the separation is where a lookahead would enter — classifying a 2021 deal by a
client's 2025 behaviour is the H015 error with a different column name.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.families.bulk_deals import events as E


def _deals(rows):
    d = pd.DataFrame(rows)
    d["deal_type"] = "bulk"
    d["first_tradable_session"] = pd.to_datetime(d["session"])
    d["client_name"] = d["client_name"].str.upper()
    d["signed_qty"] = np.where(d["side"].eq("BUY"), 1.0, -1.0) * d["quantity"]
    d["value"] = d["quantity"] * d["price"]
    d["session"] = pd.to_datetime(d["session"])
    return d


def _round_tripper(name, sessions, symbol="AAA"):
    out = []
    for s in sessions:
        out.append({"client_name": name, "symbol": symbol, "session": s,
                    "side": "BUY", "quantity": 1000.0, "price": 100.0})
        out.append({"client_name": name, "symbol": symbol, "session": s,
                    "side": "SELL", "quantity": 1000.0, "price": 100.0})
    return out


def _buyer(name, sessions, symbol="AAA"):
    return [{"client_name": name, "symbol": symbol, "session": s,
             "side": "BUY", "quantity": 1000.0, "price": 100.0} for s in sessions]


DATES = pd.bdate_range("2021-01-04", periods=40).strftime("%Y-%m-%d").tolist()


# --------------------------------------------------------------------------
# the separation itself
# --------------------------------------------------------------------------

def test_a_client_who_ends_flat_is_a_round_trip():
    book = E.client_daybook(_deals(_round_tripper("HFT LLP", DATES[:3])))
    assert book["is_round_trip"].all()
    assert book["flatness"].min() > 0.99


def test_a_one_sided_client_is_not():
    book = E.client_daybook(_deals(_buyer("A FUND", DATES[:3])))
    assert not book["is_round_trip"].any()
    assert book["flatness"].max() == 0.0


def test_event_vwap_is_weighted_by_the_reported_quantity():
    rows = [
        {"client_name": "A", "symbol": "AAA", "session": DATES[0],
         "side": "BUY", "quantity": 1.0, "price": 200.0},
        {"client_name": "B", "symbol": "AAA", "session": DATES[0],
         "side": "BUY", "quantity": 99.0, "price": 100.0},
    ]
    ev = E.build_events(_deals(rows))
    assert ev.loc[0, "all_vwap"] == pytest.approx(101.0)


def test_partial_offset_sits_between():
    d = _deals([{"client_name": "X", "symbol": "AAA", "session": DATES[0],
                 "side": "BUY", "quantity": 1000.0, "price": 100.0},
                {"client_name": "X", "symbol": "AAA", "session": DATES[0],
                 "side": "SELL", "quantity": 600.0, "price": 100.0}])
    book = E.client_daybook(d)
    assert 0.7 < float(book["flatness"].iloc[0]) < 0.8
    assert not bool(book["is_round_trip"].iloc[0])


# --------------------------------------------------------------------------
# the leak
# --------------------------------------------------------------------------

def test_a_client_is_profiled_only_on_its_own_past():
    """The first sessions of a market maker cannot know it is a market maker.

    If they did, the classification would be reading the future, and every
    event before a client's behaviour became apparent would be labelled with
    hindsight.
    """
    prof = E.client_profile(E.client_daybook(_deals(_round_tripper("HFT LLP", DATES))))
    prof = prof.sort_values("session").reset_index(drop=True)

    early = prof.iloc[:E.MIN_CLIENT_HISTORY]
    assert (early["client_type"] == "unknown").all(), (
        "a client was classified before it had the required history")
    late = prof.iloc[E.MIN_CLIENT_HISTORY:]
    assert (late["client_type"] == "liquidity_provider").all()


def test_a_profile_never_uses_the_session_it_labels():
    """Shift, not just expand: including the current row is a one-row leak."""
    rows = _round_tripper("MIXED", DATES[:20]) + _buyer("MIXED", DATES[20:])
    prof = E.client_profile(E.client_daybook(_deals(rows)))
    prof = prof.sort_values("session").reset_index(drop=True)
    first = prof[prof["prior_sessions"] == 0].iloc[0]
    assert np.isnan(first["prior_round_trip_share"]), (
        "the first session of a client already had a round-trip share")


def test_the_profile_updates_as_behaviour_changes():
    """A client that stops round-tripping stops being a liquidity provider."""
    rows = _round_tripper("TURNCOAT", DATES[:15]) + _buyer("TURNCOAT", DATES[15:])
    prof = E.client_profile(E.client_daybook(_deals(rows))).sort_values("session")
    share = prof["prior_round_trip_share"].to_numpy()
    tail = share[~np.isnan(share)]
    assert tail[len(tail) // 2] > tail[-1], "the trailing share never came down"


# --------------------------------------------------------------------------
# the event set
# --------------------------------------------------------------------------

def test_a_session_of_pure_round_trips_is_not_a_directional_event():
    rows = _round_tripper("HFT LLP", DATES)
    ev = E.build_events(_deals(rows))
    assert not ev["is_directional"].any()
    assert (ev["direction"] == "none").all()
    assert ev["round_trip_share"].min() == 1.0


def test_a_real_buyer_produces_an_accumulation_event():
    rows = _round_tripper("HFT LLP", DATES) + _buyer("A FUND", DATES)
    ev = E.build_events(_deals(rows))
    late = ev[ev["session"] > pd.Timestamp(DATES[E.MIN_CLIENT_HISTORY + 1])]
    assert (late["direction"] == "accumulation").all()
    assert late["dir_net_qty"].min() > 0
    # the HFT leg is excluded from directional flow but still counted as gross
    assert (late["round_trip_share"] > 0).all()


def test_scaling_needs_the_columns_it_says_it_needs():
    ev = E.build_events(_deals(_buyer("A FUND", DATES)))
    with pytest.raises(E.BulkDealError, match="med_vol"):
        E._scale(ev, pd.DataFrame({"symbol": ["AAA"], "date": [pd.Timestamp(DATES[0])]}))


def test_summarise_counts_what_it_says():
    rows = _round_tripper("HFT LLP", DATES) + _buyer("A FUND", DATES)
    s = E.summarise(E.build_events(_deals(rows)))
    assert s["symbol_sessions"] == len(DATES)
    assert 0 < s["directional"] < s["symbol_sessions"]
    assert s["accumulation"] == s["directional"]


# --------------------------------------------------------------------------
# who the counterparty is
# --------------------------------------------------------------------------

from src.research.families.bulk_deals import clients as CL


@pytest.mark.parametrize("a,b", [
    ("QE SECURITIES LLP", "QE SECURITIES"),
    ("ADROIT FINANCIAL SERVICES PRIVATE LIMITED", "ADROIT FINANCIAL SERVICES PVT LTD"),
    ("ASIT C MEHTA INVESTMENT INTERMEDIATES LTD.",
     "ASIT C MEHTA INVESTMENT INTERRMEDIATES LTD"),
    ("MANSUKH SECURITIES & FINANCE LIMITED", "MANSUKH SECURITIES & FINANCE LTD"),
])
def test_spellings_of_one_entity_collapse_to_one_key(a, b):
    """Not tidiness: `client_profile` needs ten prior sessions before it will
    classify anyone, so an entity split across three spellings can carry thirty
    sessions of history and be `unknown` in all three."""
    assert CL.normalise(a) == CL.normalise(b)


def test_two_different_entities_do_not_collapse():
    assert CL.normalise("NK SECURITIES RESEARCH") != CL.normalise("SHARE INDIA SECURITIES")


@pytest.mark.parametrize("name,expected", [
    ("GRAVITON RESEARCH CAPITAL LLP", "prop_hft"),
    ("XTX MARKETS LLP", "prop_hft"),
    ("JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED", "prop_hft"),
    ("SBI MUTUAL FUND", "mutual_fund"),
    ("LIFE INSURANCE CORPORATION OF INDIA", "insurance"),
    ("PRASHANT JAYANTILAL PATEL", "individual"),
    ("DINESH MUNJAL(HUF)", "individual"),
    ("SHARE INDIA SECURITIES LIMITED", "broker"),
])
def test_the_taxonomy_reads_the_obvious_cases(name, expected):
    assert CL.classify(name)[0] == expected


def test_a_prop_firm_is_not_mistaken_for_an_asset_manager():
    """"GRAVITON RESEARCH CAPITAL" reads like a fund and is a market maker.
    No rule over the string can know that, which is why a curated list exists."""
    assert CL.classify("GRAVITON RESEARCH CAPITAL LLP")[0] == "prop_hft"
    assert CL.classify("GRAVITON RESEARCH CAPITAL LLP")[1] >= 0.9


def test_an_entity_sharing_the_issuer_s_name_is_flagged_as_related():
    got, conf = CL.classify("BAJAJ HOLDINGS INVESTMENT LIMITED",
                            security_name="Bajaj Auto Limited")
    assert got == "promoter_related", (got, conf)


def test_a_common_word_does_not_make_everything_promoter_related():
    """Without stopwords every Indian company is related to every other."""
    assert CL.classify("INDIA INFOLINE LIMITED",
                       security_name="India Cements Limited")[0] != "promoter_related"


def test_an_unrecognisable_name_is_unknown_not_guessed():
    assert CL.classify("XQ")[0] == "unknown"


def test_classify_frame_adds_the_key_every_grouping_should_use():
    d = _deals(_buyer("A FUND", DATES[:3]) + _round_tripper("HFT LLP", DATES[:3]))
    d["security_name"] = "Some Company Limited"
    out = CL.classify_frame(d)
    assert {"client_key", "client_type", "client_type_confidence"} <= set(out.columns)
    assert out["client_key"].notna().all()


# --------------------------------------------------------------------------
# the separation screen, and the two ways it could lie
# --------------------------------------------------------------------------

from src.research.families.bulk_deals import separation as SEP


def _bars_with_a_split():
    """One name, one 5:1 split, so raw and adjusted space disagree by 5x."""
    dates = pd.to_datetime(DATES[:30])
    raw_close = np.full(len(dates), 500.0)
    factor = np.where(np.arange(len(dates)) < 20, 0.2, 1.0)
    return pd.DataFrame({
        "symbol": "AAA", "date": dates,
        "close": raw_close * factor, "close_raw": raw_close,
        "volume": 1000.0 / factor, "volume_raw": 1000.0,
        "med_vol_raw": 1000.0,
    })


def test_the_premium_is_read_in_the_space_the_deal_printed_in():
    """A deal at the close of a name that later split is not a 400% premium.

    Before this was fixed, `_scale` compared a raw deal price against a
    back-adjusted close: 24.9% of train directional events sit in a name with
    a later adjustment and the median premium read +1.82% instead of 0.00%.
    The feature was measuring the corporate-action factor.
    """
    rows = _buyer("A FUND", DATES[:30])
    for r in rows:
        r["price"] = 500.0
    ev = E.build_events(_deals(rows), bars=_bars_with_a_split())
    prem = ev["deal_vs_close_pct"].dropna()
    assert len(prem) > 0
    assert prem.abs().max() < 1e-6, "the premium picked up the split factor"


def test_scaling_refuses_adjusted_columns():
    """The failure has to be loud: a `close` column is not a `close_raw` one."""
    ev = E.build_events(_deals(_buyer("A FUND", DATES)))
    adjusted = pd.DataFrame({"symbol": ["AAA"], "date": [pd.Timestamp(DATES[0])],
                             "close": [100.0], "med_vol": [1000.0]})
    with pytest.raises(E.BulkDealError, match="close_raw"):
        E._scale(ev, adjusted)


def test_the_screen_refuses_the_confirmatory_partitions():
    """The dispersion work ran unpartitioned. A first moment may not."""
    for p in ("test", "forward"):
        with pytest.raises(SEP.SeparationError, match="exploration"):
            SEP.screen(partition=p)


def test_a_tied_feature_falls_back_to_halves_rather_than_lying():
    """`dir_clients` is 1 for 85% of events; it has no terciles.

    The failure mode this guards is silent: `qcut` on a heavily tied feature
    hands back a "tercile" of forty rows and the spread is then computed from
    whichever few were not tied.
    """
    tied = pd.Series([1.0] * 850 + [2.0] * 150)
    top, bot, how = SEP._split(tied)
    assert how == "median"
    assert bot.sum() == 850 and top.sum() == 150


def test_a_clean_feature_splits_into_thirds():
    top, bot, how = SEP._split(pd.Series(np.arange(900.0)))
    assert how == "tercile"
    assert top.sum() == bot.sum() == 300


def test_the_contrast_is_the_difference_of_means_it_claims_to_be():
    """`cluster_stats` estimates the variance of a mean, so the contrast is
    written as one. If the weights were wrong the standard error would be
    estimated for a quantity nobody reported."""
    y = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
    top = np.array([False, False, False, True, True, True])
    bot = ~top
    c = SEP._contrast(y, top, bot)
    assert c.mean() == pytest.approx(20.0 - 2.0)


def test_the_null_never_draws_an_event_as_its_own_control():
    """A null built from the events would carry the effect it is measuring."""
    dates = pd.to_datetime(DATES[:10])
    panel = pd.DataFrame({
        "symbol": [f"S{i}" for i in range(5)] * 10,
        "date": np.repeat(dates, 5),
        "excess_pct": np.arange(50.0),
        "vol_q": 0.0, "liq_q": 0.0, "volx_q": 0.0})
    ev = panel[panel["symbol"] == "S0"][["symbol", "date", "vol_q", "liq_q",
                                         "volx_q"]].copy()
    drawn = SEP._null(ev, panel, n_null=50, seed=1)
    assert drawn.shape == (50, len(ev))
    event_outcomes = set(panel[panel["symbol"] == "S0"]["excess_pct"])
    assert not (set(np.unique(drawn)) & event_outcomes), (
        "an event was drawn as its own control")


def test_h044_quarantines_a_factor_change_between_print_and_entry():
    ev = pd.DataFrame({"symbol": ["AAA", "BBB"],
                       "session": pd.to_datetime(["2021-01-05", "2021-01-05"])})
    deals = pd.DataFrame({
        "symbol": ["AAA", "BBB"],
        "session": pd.to_datetime(["2021-01-05", "2021-01-05"]),
        "deal_date": pd.to_datetime(["2021-01-04", "2021-01-04"]),
    })
    bars = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB", "BBB"],
        "date": pd.to_datetime(["2021-01-04", "2021-01-05"] * 2),
        "adj_factor": [0.5, 1.0, 1.0, 1.0],
    })
    out = SEP._attach_h044_timing(ev, deals, bars, pd.DataFrame())
    contaminated = out.set_index("symbol")["action_contaminated"].to_dict()
    assert contaminated == {"AAA": True, "BBB": False}


def test_h044_contrast_is_paired_inside_the_session():
    event = pd.DataFrame({
        "date": pd.to_datetime(["2021-01-05"] * 2 + ["2021-01-06"]),
        "premium_pct": [-2.0, 2.0, 2.0],
        "excess_pct": [1.0, -1.0, 99.0],
    })
    twin = pd.DataFrame({
        "date": pd.to_datetime(["2021-01-05"] * 2 + ["2021-01-06"] * 2),
        "prev_vwap_vs_close": [-2.0, 2.0, -2.0, 2.0],
        "excess_pct": [0.5, -0.5, -50.0, 50.0],
    })
    out = SEP._paired_h044_spreads(event, twin, -1.0, 1.0)
    assert out["date"].tolist() == [pd.Timestamp("2021-01-05")]
    assert out.loc[0, "increment_pct"] == pytest.approx(-1.0)


def test_h044_twin_uses_the_previous_tape_row_not_previous_liquid_row():
    bars = pd.DataFrame({
        "symbol": ["AAA"] * 3,
        "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"]),
        "vwap_raw": [100.0, 80.0, 90.0],
        "close_raw": [100.0, 80.0, 100.0],
        "adj_factor": [1.0, 1.0, 1.0],
        "close": [100.0, 80.0, 100.0],
    })
    full = SEP._previous_tape_columns(bars)
    # Pretend the middle row failed the liquidity screen. The precomputed
    # previous value on Jan 6 must remain Jan 5's 80, not jump back to Jan 4.
    liquid = full.iloc[[0, 2]].copy()
    out = SEP._with_analogues(liquid)
    assert out.iloc[-1]["prev_vwap_vs_close"] == pytest.approx(-20.0)


def test_h044_outcome_is_shifted_before_the_liquidity_filter():
    bars = pd.DataFrame({
        "symbol": ["AAA"] * 3,
        "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"]),
        "open": [100.0, 105.0, 115.0],
        "close": [100.0, 110.0, 120.0],
    })
    # Jan 5 is absent from the liquid universe. The old implementation shifted
    # this filtered frame and called Jan 4 -> Jan 6 a one-session outcome.
    liquid = bars.iloc[[0, 2]].copy()
    close = SEP._h044_outcome_panel(bars, liquid, "close_to_close")
    intraday = SEP._h044_outcome_panel(bars, liquid, "next_intraday")
    assert close.iloc[0]["fwd"] == pytest.approx(0.10)
    assert intraday.iloc[0]["fwd"] == pytest.approx(110 / 105 - 1)


def test_h044_cleanup_refuses_to_open_validation():
    with pytest.raises(SEP.SeparationError, match="train-only"):
        SEP.h044_cleanup(partition="validation")
