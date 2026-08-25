"""The derivatives archive's two eras, and the universe built from them."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.research_data.pipelines import fo_universe
from src.research_data.sources import nse_derivatives


LEGACY = pd.DataFrame({
    "INSTRUMENT": ["FUTSTK", "FUTSTK", "OPTSTK", "FUTIDX"],
    "SYMBOL": ["RELIANCE", "RELIANCE", "RELIANCE", "NIFTY"],
    "EXPIRY_DT": ["24-Jun-2021", "29-Jul-2021", "24-Jun-2021", "24-Jun-2021"],
    "STRIKE_PR": [0.0, 0.0, 2200.0, 0.0],
    "OPTION_TYP": ["XX", "XX", "CE", "XX"],
    "OPEN": [2100.0, 2110.0, 30.0, 15700.0],
    "HIGH": [2150.0, 2160.0, 35.0, 15800.0],
    "LOW": [2090.0, 2100.0, 28.0, 15650.0],
    "CLOSE": [2120.0, 2130.0, 32.0, 15750.0],
    "SETTLE_PR": [2120.0, 2130.0, 32.0, 15750.0],
    "CONTRACTS": [1000, 50, 200, 5000],
    # lot 250: 1000 contracts x 250 x 2120 = 530,000,000 rupees = 5300 lakh
    "VAL_INLAKH": [5300.0, 265.0, 16.0, 590625.0],
    "OPEN_INT": [500000, 25000, 100000, 9000000],
    "CHG_IN_OI": [1000, -500, 250, -3000],
    "TIMESTAMP": ["15-JUN-2021"] * 4,
})

UDIFF = pd.DataFrame({
    "TradDt": ["2025-06-17"] * 3,
    "FinInstrmTp": ["STF", "STF", "STO"],
    "TckrSymb": ["RELIANCE", "RELIANCE", "RELIANCE"],
    "XpryDt": ["2025-06-26", "2025-07-31", "2025-06-26"],
    "StrkPric": [0.0, 0.0, 1400.0],
    "OptnTp": [None, None, "CE"],
    "OpnPric": [1400.0, 1410.0, 20.0],
    "HghPric": [1420.0, 1430.0, 25.0],
    "LwPric": [1390.0, 1400.0, 18.0],
    "ClsPric": [1410.0, 1420.0, 22.0],
    "SttlmPric": [1410.0, 1420.0, 22.0],
    "UndrlygPric": [1405.0, 1405.0, 1405.0],
    "OpnIntrst": [600000, 30000, 120000],
    "ChngInOpnIntrst": [2000, -100, 500],
    "TtlTradgVol": [1200, 60, 300],
    "TtlTrfVal": [845_000_000.0, 42_600_000.0, 3_300_000.0],
    "NewBrdLotQty": [500, 500, 500],
})


def test_both_eras_normalise_to_one_schema():
    legacy = nse_derivatives.parse_legacy(LEGACY)
    udiff = nse_derivatives.parse_udiff(UDIFF)
    assert list(legacy.columns) == list(nse_derivatives.COLUMNS)
    assert list(udiff.columns) == list(nse_derivatives.COLUMNS)
    assert set(legacy["instrument"]) == {"stock_future", "stock_option", "index_future"}
    assert set(udiff["instrument"]) == {"stock_future", "stock_option"}


def test_legacy_turnover_is_converted_from_lakh_to_rupees():
    """The unit difference between eras is silent and would be a 10^5 error."""
    legacy = nse_derivatives.parse_legacy(LEGACY)
    row = legacy.loc[legacy["instrument"].eq("stock_future")].iloc[0]
    assert row["traded_value"] == pytest.approx(530_000_000.0)


def test_lot_size_is_derived_in_the_legacy_era_and_reported_in_udiff():
    legacy = nse_derivatives.parse_legacy(LEGACY)
    udiff = nse_derivatives.parse_udiff(UDIFF)
    row = legacy.loc[legacy["instrument"].eq("stock_future")].iloc[0]
    assert row["lot_size"] == pytest.approx(250.0)
    assert (legacy["lot_size_source"] == "derived_from_turnover").all()
    assert (udiff["lot_size_source"] == "reported").all()
    assert udiff["lot_size"].iloc[0] == 500


def test_session_comes_from_the_file_not_the_url():
    """The holiday trap: a URL can serve a neighbouring session with HTTP 200."""
    legacy = nse_derivatives.parse_legacy(LEGACY)
    assert legacy["session"].unique().tolist() == [pd.Timestamp("2021-06-15")]
    udiff = nse_derivatives.parse_udiff(UDIFF)
    assert udiff["session"].unique().tolist() == [pd.Timestamp("2025-06-17")]


def test_a_missing_required_column_is_refused():
    with pytest.raises(nse_derivatives.DerivativesError):
        nse_derivatives.parse_udiff(UDIFF.drop(columns=["XpryDt"]))


def _contracts() -> pd.DataFrame:
    sessions = pd.bdate_range("2024-01-01", periods=6)
    rows = []
    for session in sessions:
        for offset, expiry in enumerate(
                [pd.Timestamp("2024-01-25"), pd.Timestamp("2024-02-29")]):
            rows.append({
                "session": session, "symbol": "AAA", "instrument": "stock_future",
                "expiry": expiry, "open": 100.0, "high": 102.0, "low": 99.0,
                "close": 101.0 + offset, "settle": 101.0 + offset,
                "underlying_close": 100.5, "contracts": 1000 - offset * 900,
                "traded_value": 1e8, "open_interest": 50_000,
                "change_in_open_interest": 100, "lot_size": 500.0,
                "lot_size_source": "reported", "source_era": "udiff",
            })
    return pd.DataFrame(rows)


def test_universe_keeps_the_near_month_and_names_the_roll(monkeypatch):
    monkeypatch.setattr(nse_derivatives, "load_range",
                        lambda **kwargs: _contracts())
    universe = fo_universe.build()
    assert len(universe) == 6, "one row per symbol-session, not per contract"
    assert (universe["near_expiry"] == pd.Timestamp("2024-01-25")).all()
    assert (universe["next_expiry"] == pd.Timestamp("2024-02-29")).all()
    assert np.allclose(universe["lot_notional"].to_numpy(float), 500 * 101.0)
    assert not universe["is_expiry_session"].any()


def test_expired_contracts_never_represent_a_session(monkeypatch):
    contracts = _contracts()
    contracts.loc[contracts["expiry"].eq(pd.Timestamp("2024-01-25")),
                  "expiry"] = pd.Timestamp("2019-01-01")
    monkeypatch.setattr(nse_derivatives, "load_range", lambda **kwargs: contracts)
    universe = fo_universe.build()
    assert (universe["near_expiry"] == pd.Timestamp("2024-02-29")).all()


def test_tradable_flags_use_only_lagged_activity(monkeypatch):
    contracts = _contracts()
    # Make the final session enormously liquid and every prior one dead.
    contracts["contracts"] = 0
    contracts["traded_value"] = 0.0
    last = contracts["session"].max()
    contracts.loc[contracts["session"].eq(last), "contracts"] = 100_000
    contracts.loc[contracts["session"].eq(last), "traded_value"] = 1e12
    monkeypatch.setattr(nse_derivatives, "load_range", lambda **kwargs: contracts)
    flagged = fo_universe.tradable(
        fo_universe.build(),
        fo_universe.UniverseConfig(min_sessions_in_window=1))
    # The liquid session itself must not be selectable on its own liquidity.
    assert not bool(flagged.loc[flagged["session"].eq(last), "tradable"].iloc[0])


def test_lot_report_states_its_margin_assumption(monkeypatch):
    monkeypatch.setattr(nse_derivatives, "load_range",
                        lambda **kwargs: _contracts())
    report = fo_universe.lot_notional_report(fo_universe.build())
    assert report["margin_fraction_assumed"] == 0.18
    row = report["by_year"][0]
    assert row["median_lot_notional"] == pytest.approx(50500.0)
    assert row["concurrent_positions_at_5L"] >= 1
