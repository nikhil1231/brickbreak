"""Scrip-master parsing and cost extrapolation."""
import pytest

from src.research_data.sources import security_master as sm
from src.research_data.feasibility.estimate import estimate_daily_history, estimate_full_download, measured_throughput
from src.research_data.feasibility.universe import TEST_UNIVERSE


@pytest.fixture(scope="module")
def master():
    return sm.load()


def test_master_parses_and_has_expected_columns(master):
    for col in ("Token", "ShortName", "ExchangeCode", "Series", "CompanyName"):
        assert col in master.columns
    assert len(master) > 3000


def test_resolve_maps_nse_symbol_to_isec_code(master):
    assert sm.resolve(master, "RELIANCE").isec_code == "RELIND"
    assert sm.resolve(master, "INFY").isec_code == "INFTEC"


def test_resolve_accepts_isec_code_too(master):
    assert sm.resolve(master, "RELIND").nse_symbol == "RELIANCE"


def test_resolve_unknown_symbol_returns_none(master):
    assert sm.resolve(master, "NOTAREALTICKER123") is None


def test_every_test_universe_symbol_resolves(master):
    """The spike's conclusions depend on these ten symbols being real."""
    for t in TEST_UNIVERSE:
        assert sm.resolve(master, t.nse_symbol) is not None, t.nse_symbol


def test_inactive_securities_carry_token_zero(master):
    for t in [s for s in TEST_UNIVERSE if s.kind == "inactive"]:
        assert sm.resolve(master, t.nse_symbol).looks_inactive


def test_liquid_securities_carry_real_tokens(master):
    for t in [s for s in TEST_UNIVERSE if s.kind == "liquid"]:
        assert not sm.resolve(master, t.nse_symbol).looks_inactive


def test_summarize_reports_delisting_fields_as_unpopulated(master):
    """Documented finding: the master ships these columns but never fills them."""
    s = sm.summarize(master)
    assert s["rows_with_delisting_date"] == 0
    assert s["rows_with_delete_flag"] == 0
    assert s["eq_active_token"] > 2000


def test_estimate_scales_linearly_with_securities():
    a = estimate_full_download(100, 3, 40.0, 1.0, 1, 0.7)
    b = estimate_full_download(200, 3, 40.0, 1.0, 1, 0.7)
    assert b["total_rows"] == 2 * a["total_rows"]
    assert b["api_calls"] == 2 * a["api_calls"]


def test_estimate_respects_throttle_floor():
    """If the API is faster than our throttle, the throttle sets the pace."""
    fast = estimate_full_download(10, 1, 40.0, 0.1, 1, 2.0)
    assert fast["serial_hours"] == round(fast["api_calls"] * 2.0 / 3600, 1)


def test_estimate_days_per_call_reduces_calls():
    one = estimate_full_download(10, 1, 40.0, 1.0, 1, 0.7)
    five = estimate_full_download(10, 1, 40.0, 1.0, 5, 0.7)
    assert five["api_calls"] < one["api_calls"]


def test_measured_throughput_empty():
    assert measured_throughput([])["n_calls"] == 0


def test_measured_throughput_ignores_failed_calls():
    calls = [
        {"ok": True, "duration_s": 1.0, "n_rows": 10, "interval": "1day"},
        {"ok": False, "duration_s": 9.0, "n_rows": 0, "interval": "1day"},
    ]
    tp = measured_throughput(calls, "1day")
    assert tp["n_calls"] == 1 and tp["mean_duration_s"] == 1.0


def test_daily_history_estimate_is_modest():
    est = estimate_daily_history(2900, 20, 40.0, 1.5, 10, 0.7)
    assert est["storage_mb_parquet"] < 2000


def test_bhavcopy_parser_trusts_file_date_not_url():
    """NSE serves the prior session for holiday URLs; the parser must not
    relabel those rows with the requested date."""
    from datetime import date as _date
    from src.research_data.sources.nse import parse_bhavcopy
    csv = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
        "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, "
        "NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "ACME, EQ, 23-Jan-2026, 100, 101, 105, 99, 104, 104, 102, 1000, 10.5, 50, 500, 50.0\n"
    )
    df = parse_bhavcopy(csv, _date(2026, 1, 26))   # requested a holiday
    assert str(df["date"].iloc[0].date()) == "2026-01-23"  # file's date wins
    assert df["turnover"].iloc[0] == 10.5 * 1e5            # lacs -> rupees


def test_bhavcopy_parser_keeps_only_cash_series():
    from src.research_data.sources.nse import parse_bhavcopy
    csv = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
        "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, "
        "NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "ACME, EQ, 23-Jan-2026, 100, 101, 105, 99, 104, 104, 102, 1000, 10.5, 50, 500, 50.0\n"
        "1018GS2026, GS, 23-Jan-2026, 106, 107, 107, 106, 107, 107, 107, 681, 0.73, 7, 681, 100.0\n"
        "SMALLCO, BE, 23-Jan-2026, 10, 10, 11, 9, 10, 10, 10, 100, 0.1, 5, 50, 50.0\n"
    )
    df = parse_bhavcopy(csv)
    assert set(df["symbol"]) == {"ACME", "SMALLCO"}   # GS (gilt) dropped


def _mk_opening(rows):
    import pandas as pd
    return pd.DataFrame(rows, columns=["security_id", "symbol", "timestamp",
                                       "open", "high", "low", "close", "volume"])


def test_find_no_session_dates_detects_muhurat():
    """Diwali Muhurat is an evening session: bhavcopy has bars, but the
    09:15-09:20 window is empty for every symbol."""
    import pandas as pd
    from src.research_data.pipelines.opening import find_no_session_dates
    man = pd.DataFrame({
        "symbol": list("ABCDEF"),
        "date": pd.to_datetime(["2025-10-20"] * 3 + ["2025-10-21"] * 3),
        "status": ["ok", "ok", "ok", "empty", "empty", "empty"],
    })
    assert find_no_session_dates(man) == ["2025-10-21"]


def test_find_no_session_dates_ignores_thin_days():
    """A date with too few attempts is not evidence of a missing session."""
    import pandas as pd
    from src.research_data.pipelines.opening import find_no_session_dates
    man = pd.DataFrame({"symbol": ["A"], "date": pd.to_datetime(["2025-01-02"]),
                        "status": ["empty"]})
    assert find_no_session_dates(man, min_attempts=3) == []


def test_flag_bad_volume_and_exclusion():
    """Negative volume is an archive defect; the symbol-day is dropped, not clipped."""
    import pandas as pd
    from src.research_data.pipelines.opening import flag_bad_volume, opening_features
    ts = pd.Timestamp("2024-01-09 09:15:10")
    d = _mk_opening([
        ["X", "GOOD", ts, 10.0, 10.5, 9.9, 10.2, 500],
        ["X", "GOOD", ts + pd.Timedelta(seconds=5), 10.2, 10.3, 10.1, 10.25, 300],
        ["Y", "BAD", ts, 20.0, 20.0, 20.0, 20.0, -1347],
        ["Y", "BAD", ts + pd.Timedelta(seconds=5), 20.0, 20.1, 20.0, 20.05, 100],
    ])
    bad = flag_bad_volume(d)
    assert list(bad["symbol"]) == ["BAD"] and int(bad["n_negative_bars"].iloc[0]) == 1
    feat = opening_features(d, exclude_bad=True)
    assert set(feat["symbol"]) == {"GOOD"}          # BAD excluded, not clipped
    assert int(feat["vol_5m"].iloc[0]) == 800
    assert set(opening_features(d, exclude_bad=False)["symbol"]) == {"GOOD", "BAD"}


def test_bhavcopy_parser_reads_xlsx_served_at_csv_url(tmp_path):
    """On 2022-08-08 NSE served an XLSX workbook from the .csv URL."""
    import io
    import pandas as pd
    from src.research_data.sources.nse import parse_bhavcopy

    book = pd.DataFrame([{
        "SYMBOL": "ACME", "SERIES": "EQ", "DATE1": "08-Aug-2022",
        "PREV_CLOSE": 100, "OPEN_PRICE": 101, "HIGH_PRICE": 105,
        "LOW_PRICE": 99, "LAST_PRICE": 104, "CLOSE_PRICE": 104,
        "AVG_PRICE": 102, "TTL_TRD_QNTY": 1000, "TURNOVER_LACS": 10.5,
        "NO_OF_TRADES": 50, "DELIV_QTY": 500, "DELIV_PER": 50.0,
    }])
    buf = io.BytesIO()
    book.to_excel(buf, index=False)
    payload = buf.getvalue()
    assert payload[:2] == b"PK"                      # really a zip/xlsx

    df = parse_bhavcopy(payload)
    assert str(df["date"].iloc[0].date()) == "2022-08-08"
    assert df["symbol"].iloc[0] == "ACME"


def test_sync_files_a_session_under_its_own_date(tmp_path, monkeypatch):
    """The 2021-11-04 Muhurat bhavcopy is served at the 05112021 URL.

    Asking for the 5th must store the session on the 4th and mark the 5th
    itself as non-trading, rather than discarding the response.
    """
    from datetime import date as _date
    import pandas as pd
    from src.research_data.sources import nse as nse_archive

    monkeypatch.setattr(nse_archive, "BHAV_DIR", tmp_path)

    served = _date(2021, 11, 4)
    frame = pd.DataFrame([{"symbol": "ACME", "series": "EQ",
                           "date": pd.Timestamp(served), "close": 100.0}])

    def fake_fetch(d, session=None, timeout=60):
        # Only the 5th's URL yields anything; the 4th's own URL is stale.
        return (served, frame) if d == _date(2021, 11, 5) else None

    monkeypatch.setattr(nse_archive, "fetch_day", fake_fetch)
    stats = nse_archive.sync(_date(2021, 11, 4), _date(2021, 11, 5),
                             throttle=0.0, workers=1, verbose=False)

    assert stats["relocated"] == ["2021-11-05->2021-11-04"]
    assert len(pd.read_parquet(nse_archive._day_path(served))) == 1
    # the 5th is recorded as a non-trading day, so it is never re-requested
    assert len(pd.read_parquet(nse_archive._day_path(_date(2021, 11, 5)))) == 0


def test_sync_requests_weekends_so_special_sessions_are_not_lost(tmp_path, monkeypatch):
    """Budget Saturdays and Muhurat Sundays are real sessions."""
    from datetime import date as _date
    from src.research_data.sources import nse as nse_archive

    monkeypatch.setattr(nse_archive, "BHAV_DIR", tmp_path)
    asked: list[_date] = []

    def fake_fetch(d, session=None, timeout=60):
        asked.append(d)
        return None

    monkeypatch.setattr(nse_archive, "fetch_day", fake_fetch)
    # 2020-02-01 is a Saturday: the Union Budget session.
    nse_archive.sync(_date(2020, 1, 31), _date(2020, 2, 2),
                     throttle=0.0, workers=1, verbose=False)
    assert _date(2020, 2, 1) in asked and _date(2020, 2, 2) in asked
