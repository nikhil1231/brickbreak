import pandas as pd

from src.research_data.pipelines import bulk_intraday


def _master():
    return pd.DataFrame({
        "ExchangeCode": ["ABC"], "ShortName": ["ABCISEC"],
        "CompanyName": ["ABC LTD"], "Series": ["EQ"],
        "Token": ["1"], "ISINCode": ["INE000A"],
    })


def test_resolve_requests_maps_nifty_and_reports_unmapped(monkeypatch):
    monkeypatch.setattr(bulk_intraday, "load_manifest", lambda: pd.DataFrame())
    pairs = pd.DataFrame({
        "symbol": ["ABC", "__NIFTY__", "MISSING"],
        "date": pd.to_datetime(["2024-01-02"] * 3),
    })
    work, report = bulk_intraday.resolve_requests(
        pairs, master=_master(), rename_map=pd.DataFrame())
    assert dict(zip(work.symbol, work.request_code)) == {
        "ABC": "ABCISEC", "__NIFTY__": "NIFTY"}
    assert report["unmapped_pairs"] == 1


def test_resolve_requests_does_not_retry_settled_empty(monkeypatch):
    manifest = pd.DataFrame({
        "symbol": ["ABC"], "date": pd.to_datetime(["2024-01-02"]),
        "status": ["empty"],
    })
    monkeypatch.setattr(bulk_intraday, "load_manifest", lambda: manifest)
    pairs = manifest[["symbol", "date"]]
    work, report = bulk_intraday.resolve_requests(
        pairs, master=_master(), rename_map=pd.DataFrame())
    assert work.empty
    assert report["already_settled"] == 1
