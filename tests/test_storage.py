"""Normalization and validation must be trustworthy before we judge the API."""
import pandas as pd

from src.research_data.pipelines.storage import NORMALIZED_COLUMNS, normalize
from src.research_data.pipelines.validation import check


def test_normalize_empty_payload():
    df = normalize([], "RELIND", "RELIANCE")
    assert list(df.columns) == NORMALIZED_COLUMNS
    assert df.empty


def test_normalize_broadcasts_identifiers():
    rows = [
        {"datetime": "2026-08-17 09:15:01", "open": "1", "high": "2", "low": "0.5",
         "close": "1.5", "volume": "10"},
        {"datetime": "2026-08-17 09:15:02", "open": "1.5", "high": "2.5", "low": "1",
         "close": "2", "volume": "20"},
    ]
    df = normalize(rows, "RELIND", "RELIANCE")
    assert (df["security_id"] == "RELIND").all()
    assert (df["symbol"] == "RELIANCE").all()
    assert df["volume"].tolist() == [10, 20]
    assert str(df["timestamp"].dtype).startswith("datetime64")


def test_normalize_handles_alias_columns_and_z_suffix():
    rows = [{"Datetime": "2026-08-17T09:15:01.000Z", "Open": 1, "High": 2,
             "Low": 1, "Close": 2, "Volume": 5}]
    df = normalize(rows, "X", "Y")
    assert df.loc[0, "timestamp"] == pd.Timestamp("2026-08-17 09:15:01")
    assert df.loc[0, "volume"] == 5


def test_normalize_missing_volume_uses_sentinel():
    rows = [{"datetime": "2026-08-17 09:15:01", "open": 1, "high": 2, "low": 1, "close": 2}]
    df = normalize(rows, "X", "Y")
    assert df.loc[0, "volume"] == -1  # sentinel, not a silent zero


def test_timestamp_is_left_naive_not_shifted_to_utc():
    """Breeze stamps say 'Z' but carry IST wall-clock; we must not shift them."""
    rows = [{"datetime": "2026-08-17T09:15:00.000Z", "open": 1, "high": 1,
             "low": 1, "close": 1, "volume": 1}]
    df = normalize(rows, "X", "Y")
    ts = df.loc[0, "timestamp"]
    assert ts.hour == 9 and ts.minute == 15
    assert ts.tzinfo is None


def _second_rows(n=300, drop=(), zero_vol=()):
    out = []
    for i in range(n):
        if i in drop:
            continue
        mm, ss = 15 + i // 60, i % 60
        out.append({"datetime": f"2026-08-17 09:{mm:02d}:{ss:02d}",
                    "open": 100, "high": 101, "low": 99, "close": 100.5,
                    "volume": 0 if i in zero_vol else 100 + i})
    return out


def test_check_detects_missing_seconds():
    df = normalize(_second_rows(drop={10, 11, 12}), "X", "Y")
    res = check(df, "1second")
    assert res["n_rows"] == 297
    assert res["continuity"]["total_missing_in_span"] == 3
    assert res["first_five_minutes"]["2026-08-17"]["coverage_pct"] == 99.0


def test_check_reconstructs_first_five_minute_volume():
    rows = _second_rows()
    df = normalize(rows, "X", "Y")
    res = check(df, "1second")["first_five_minutes"]["2026-08-17"]
    assert res["n_bars_in_window"] == 300
    assert res["total_volume"] == sum(r["volume"] for r in rows)
    assert res["reconstructable"] is True


def test_check_flags_duplicate_timestamps():
    rows = _second_rows(n=5)
    rows.append(rows[0])
    df = normalize(rows, "X", "Y")
    assert check(df, "1second")["timestamp"]["n_duplicates"] == 1


def test_check_flags_cumulative_volume():
    """A monotonically rising volume series means cumulative, not per-bar."""
    rows = [{"datetime": f"2026-08-17 09:15:{i:02d}", "open": 1, "high": 1,
             "low": 1, "close": 1, "volume": (i + 1) * 100} for i in range(30)]
    df = normalize(rows, "X", "Y")
    assert check(df, "1second")["volume"]["looks_cumulative"] is True


def test_check_flags_out_of_session_timestamps():
    rows = [{"datetime": "2026-08-17 03:45:00", "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 1}]
    df = normalize(rows, "X", "Y")
    res = check(df, "1second")
    assert res["timestamp"]["n_outside_0915_1530_IST"] == 1
    assert res["timestamp"]["reads_as_IST_wallclock"] is False


def test_check_flags_impossible_ohlc():
    rows = [{"datetime": "2026-08-17 09:15:00", "open": 5, "high": 1, "low": 10,
             "close": 5, "volume": 1}]
    df = normalize(rows, "X", "Y")
    res = check(df, "1second")["ohlc"]
    assert res["n_high_lt_low"] == 1


def test_check_empty_frame_is_safe():
    res = check(normalize([], "X", "Y"), "1second")
    assert res["empty"] is True
