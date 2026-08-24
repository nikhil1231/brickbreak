import json
from dataclasses import dataclass

import pandas as pd
import pytest

from src.research_data import frame as frame_api
from src.research_data import splits
from src.research_data.pipelines import intraday


def request_pairs(n=25):
    sessions = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame({
        "instrument_id": "TESTCODE",
        "symbol_asof": "TEST",
        "session": sessions,
    }), sessions


def test_request_manifest_is_hashed_non_overlapping_and_below_cap():
    pairs, sessions = request_pairs()
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", interval="5minute",
        all_sessions=sessions)
    assert requests["expected_max_rows"].max() < 1000
    assert requests["request_id"].is_unique
    all_requested = []
    for value in requests["requested_sessions"]:
        all_requested.extend(json.loads(value))
    assert len(all_requested) == len(set(all_requested)) == len(sessions)
    assert len(intraday.manifest_fingerprint(requests)) == 64


def test_wide_one_minute_requests_are_split_before_cap():
    pairs, sessions = request_pairs(8)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", interval="1minute",
        all_sessions=sessions)
    assert len(requests) >= 4
    assert requests["expected_max_rows"].max() <= 900


def test_frozen_manifest_detects_parquet_tampering(tmp_path):
    pairs, sessions = request_pairs(3)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=sessions)
    intraday.write_request_manifest(requests, tmp_path)
    loaded = pd.read_parquet(tmp_path / "requests.parquet")
    loaded.loc[0, "symbol_asof"] = "ALTERED"
    loaded.to_parquet(tmp_path / "requests.parquet", index=False)
    with pytest.raises(intraday.IntradayError, match="hash"):
        intraday.load_request_manifest(tmp_path)


def test_frozen_manifest_pins_remote_acquisition_code(tmp_path):
    pairs, sessions = request_pairs(3)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=sessions)
    intraday.write_request_manifest(requests, tmp_path)
    assert intraday.assert_acquisition_code(tmp_path) == \
        intraday.acquisition_code_fingerprint()
    metadata = json.loads((tmp_path / "requests.json").read_text())
    metadata["acquisition_code_hash"] = "0" * 64
    (tmp_path / "requests.json").write_text(json.dumps(metadata))
    with pytest.raises(intraday.IntradayError, match="code hash mismatch"):
        intraday.assert_acquisition_code(tmp_path)


def test_normalisation_sets_availability_at_bar_end():
    request = {
        "instrument_id": "TESTCODE", "symbol_asof": "TEST",
        "interval": "5minute", "request_id": "abc",
        "dataset_version": "v1",
    }
    rows = [{
        "datetime": "2026-01-02 09:15:00", "open": "100", "high": "101",
        "low": "99", "close": "100.5", "volume": "1000",
    }]
    result = intraday.normalise_response(rows, request)
    assert result.loc[0, "bar_start"] == pd.Timestamp("2026-01-02 09:15")
    assert result.loc[0, "bar_end"] == pd.Timestamp("2026-01-02 09:20")
    assert result.loc[0, "available_at"] == result.loc[0, "bar_end"]


@dataclass
class Result:
    raw: list
    error: str | None = None
    status: int = 200
    call_id: str = "call"
    duration_s: float = 0.1


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def raw(self, *args, **kwargs):
        return Result(self.rows)


def test_capped_response_is_never_admitted(tmp_path):
    pairs, sessions = request_pairs(1)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=sessions)
    row = {
        "datetime": "2026-01-02 09:15:00", "open": "100", "high": "101",
        "low": "99", "close": "100", "volume": "10",
    }
    result = intraday.fetch_requests(
        requests, FakeClient([row] * 1000), tmp_path, workers=1)
    assert result["capped"] == 1
    assert not list((tmp_path / "normalised").glob("*.parquet"))
    assert result["remaining"] == 1


def test_nonregular_markers_are_preserved_but_not_admitted_as_bars(tmp_path):
    pairs, sessions = request_pairs(1)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=sessions)
    session = pd.Timestamp(sessions[0]).strftime("%Y-%m-%d")
    rows = [
        {
            "datetime": f"{session} 09:15:00", "open": "100", "high": "101",
            "low": "99", "close": "100", "volume": "10",
        },
        {
            "datetime": f"{session} 09:05:00", "open": "99", "high": "99",
            "low": "99", "close": "99", "volume": "0",
        },
        {
            "datetime": f"{session} 15:30:00", "open": "102", "high": "102",
            "low": "101", "close": "101", "volume": "7",
        },
    ]
    result = intraday.fetch_requests(
        requests, FakeClient(rows), tmp_path, workers=1)
    assert result["ok"] == 1
    request_id = requests.iloc[0]["request_id"]
    bars = pd.read_parquet(tmp_path / "normalised" / f"{request_id}.parquet")
    markers = pd.read_parquet(
        tmp_path / "session_markers" / f"{request_id}.parquet")
    attempt = json.loads(
        (tmp_path / "attempts" / f"{request_id}.json").read_text())
    assert bars["bar_start"].dt.strftime("%H:%M").tolist() == ["09:15"]
    assert markers["bar_start"].dt.strftime("%H:%M").tolist() == ["09:05", "15:30"]
    assert markers["quality_flags"].tolist() == [
        "preopen_marker", "terminal_close_marker"]
    assert attempt["n_session_marker_rows_excluded"] == 2
    assert attempt["session_markers_sha256"] == intraday.file_sha256(
        tmp_path / "session_markers" / f"{request_id}.parquet")


def test_evening_special_session_is_explicit_not_a_missing_regular_session(tmp_path):
    pairs = pd.DataFrame({
        "instrument_id": ["TESTCODE"], "symbol_asof": ["TEST"],
        "session": [pd.Timestamp("2026-11-08")],
    })
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=[pd.Timestamp("2026-11-08")])
    row = {
        "datetime": "2026-11-08 18:15:00", "open": "100", "high": "101",
        "low": "99", "close": "100", "volume": "10",
    }
    result = intraday.fetch_requests(
        requests, FakeClient([row]), tmp_path, workers=1)
    assert result["ok"] == 1
    assert result["remaining"] == 0
    request_id = requests.iloc[0]["request_id"]
    assert pd.read_parquet(
        tmp_path / "session_markers" / f"{request_id}.parquet"
    )["quality_flags"].tolist() == ["special_session_bar"]
    assert pd.read_parquet(
        tmp_path / "normalised" / f"{request_id}.parquet").empty


def test_partial_response_is_settled_with_explicit_coverage_gap(tmp_path):
    pairs, sessions = request_pairs(2)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=sessions)
    first = pd.Timestamp(sessions[0]).strftime("%Y-%m-%d")
    row = {
        "datetime": f"{first} 09:15:00", "open": "100", "high": "101",
        "low": "99", "close": "100", "volume": "10",
    }
    result = intraday.fetch_requests(
        requests, FakeClient([row]), tmp_path, workers=1)
    assert result["partial"] == 1
    assert result["remaining"] == 0
    attempt = intraday.load_attempts(tmp_path).iloc[0]
    assert json.loads(json.dumps(attempt["missing_sessions"])) == [
        pd.Timestamp(sessions[1]).strftime("%Y-%m-%d")]
    assert len(pd.read_parquet(next(
        (tmp_path / "normalised").glob("*.parquet")))) == 1
    intraday.write_request_manifest(requests, tmp_path)
    report = intraday.verify_acquisition(tmp_path)
    assert report["partial"] == 1
    assert report["bad"] == 0
    assert report["session_coverage_pct"] == 50.0


def test_auth_failure_stops_dispatching_new_requests(tmp_path):
    pairs, sessions = request_pairs(8)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", interval="1minute",
        all_sessions=sessions)
    client = FakeClient([])
    client.rows = []

    def expired(*args, **kwargs):
        return Result([], error="Session key is expired")

    client.raw = expired
    result = intraday.fetch_requests(requests, client, tmp_path, workers=1)
    assert len(requests) >= 4
    assert result["attempted"] == 1
    assert result["auth_failed"] == 1
    assert result["remaining"] == len(requests)


def test_acquisition_verifier_detects_shard_tampering(tmp_path):
    pairs, sessions = request_pairs(1)
    requests = intraday.build_request_manifest(
        pairs, version="bootstrap_v1", all_sessions=sessions)
    intraday.write_request_manifest(requests, tmp_path)
    session = pd.Timestamp(sessions[0]).strftime("%Y-%m-%d")
    row = {
        "datetime": f"{session} 09:15:00", "open": "100", "high": "101",
        "low": "99", "close": "100", "volume": "10",
    }
    intraday.fetch_requests(requests, FakeClient([row]), tmp_path, workers=1)
    report = intraday.verify_acquisition(tmp_path)
    assert report["ok"] == 1
    shard = next((tmp_path / "normalised").glob("*.parquet"))
    changed = pd.read_parquet(shard)
    changed.loc[0, "close_raw"] = 999.0
    changed.to_parquet(shard, index=False)
    with pytest.raises(intraday.IntradayError, match="shard hash mismatch"):
        intraday.verify_acquisition(tmp_path)


def test_loader_keeps_partition_guard_when_columns_omit_session(tmp_path, monkeypatch):
    manifest = splits.load("v1")
    train_day = splits.partition("train", manifest=manifest)[0]
    test_day = splits.partition("test", manifest=manifest)[0]
    part = tmp_path / "part-2020.parquet"
    rows = []
    for day, price in ((train_day, 100.0), (test_day, 200.0)):
        start = pd.Timestamp(day) + pd.Timedelta(hours=9, minutes=15)
        rows.append({
            "instrument_id": "TESTCODE", "symbol_asof": "TEST",
            "session": pd.Timestamp(day), "bar_start": start,
            "bar_end": start + pd.Timedelta(minutes=5),
            "available_at": start + pd.Timedelta(minutes=5),
            "close_raw": price,
        })
    pd.DataFrame(rows).to_parquet(part, index=False)
    dataset_manifest = {
        "status": "ready", "dataset_version": "v1",
        "base_interval": "5minute", "parent_split_version": "v1",
        "parent_split_hash": manifest["hash"],
        "columns": list(rows[0]), "outcome_columns": [],
    }
    monkeypatch.setattr(intraday, "load_dataset_manifest",
                        lambda version, interval: dataset_manifest)
    monkeypatch.setattr(intraday, "dataset_root",
                        lambda version, interval: tmp_path)
    loaded = frame_api.load_intraday_panel(
        version="v1", partition="train", columns=["close_raw"])
    assert loaded["close_raw"].tolist() == [100.0]
    assert loaded["partition"].tolist() == ["train"]


def test_loader_rejects_outcome_columns_before_read(monkeypatch):
    manifest = splits.load("v1")
    dataset_manifest = {
        "status": "ready", "dataset_version": "v1",
        "base_interval": "5minute", "parent_split_version": "v1",
        "parent_split_hash": manifest["hash"],
        "columns": ["future_return"], "outcome_columns": ["future_return"],
    }
    monkeypatch.setattr(intraday, "load_dataset_manifest",
                        lambda version, interval: dataset_manifest)
    with pytest.raises(frame_api.FrameError, match="outcome"):
        frame_api.load_intraday_panel(columns=["future_return"])
