import pandas as pd
import pytest

from src.discretionary.pa_adapter import PriceActionAdapter, PriceActionCaseError
from src.research_data.pipelines.causal_zones import build_zone_state_machine


def bars(n=30):
    times = pd.date_range("2026-01-02 09:15", periods=n, freq="5min")
    close = pd.Series([100 + (i % 7) * 0.2 + i * 0.03 for i in range(n)])
    frame = pd.DataFrame({
        "symbol_asof": "FAMOUSCO",
        "bar_start": times,
        "bar_end": times + pd.Timedelta(minutes=5),
        "available_at": times + pd.Timedelta(minutes=5),
        "open_raw": close - 0.1,
        "high_raw": close + 0.3,
        "low_raw": close - 0.3,
        "close_raw": close,
        "volume_raw": [1000 + i * 17 for i in range(n)],
        "quality_flags": "",
    })
    return build_zone_state_machine(frame)


def test_case_is_byte_identical_with_future_rows_present():
    frame = bars()
    cutoff = frame.loc[19, "available_at"]
    adapter = PriceActionAdapter()
    truncated = adapter.render_case(frame.iloc[:20], decision_at=cutoff)
    full = adapter.render_case(frame, decision_at=cutoff)
    assert truncated["chart_bytes"] == full["chart_bytes"]
    assert truncated["sidecar_bytes"] == full["sidecar_bytes"]
    assert truncated["case_hash"] == full["case_hash"]


def test_future_price_mutation_cannot_change_case():
    frame = bars()
    cutoff = frame.loc[19, "available_at"]
    adapter = PriceActionAdapter()
    before = adapter.render_case(frame, decision_at=cutoff)
    frame.loc[20:, ["open_raw", "high_raw", "low_raw", "close_raw"]] *= 100
    after = adapter.render_case(frame, decision_at=cutoff)
    assert before["case_hash"] == after["case_hash"]


def test_anonymised_case_contains_no_identity_or_calendar_date():
    frame = bars()
    case = PriceActionAdapter().render_case(frame, anonymised=True)
    combined = case["chart_bytes"] + case["sidecar_bytes"]
    assert case["chart_bytes"].startswith(b"\x89PNG\r\n\x1a\n")
    assert b"FAMOUSCO" not in combined
    assert b"2026-01-02" not in combined
    assert case["sidecar"]["instrument"] == "ASSET"
    assert case["sidecar"]["decision_at"] == "t=0"


def test_identity_reveal_is_a_distinct_paired_case():
    frame = bars()
    adapter = PriceActionAdapter()
    anonymous = adapter.render_case(frame, anonymised=True)
    revealed = adapter.render_case(frame, anonymised=False)
    assert revealed["sidecar"]["instrument"] == "FAMOUSCO"
    assert anonymous["case_hash"] != revealed["case_hash"]


def test_negative_volume_is_a_recorded_case_failure_not_clipped():
    frame = bars()
    frame.loc[10, "volume_raw"] = -1
    frame.loc[10, "quality_flags"] = "negative_volume"
    with pytest.raises(PriceActionCaseError, match="source-quality failure"):
        PriceActionAdapter().render_case(frame)
