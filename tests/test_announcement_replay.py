from __future__ import annotations

import numpy as np
import pandas as pd

from src.discretionary import baselines, case, generators
from src.discretionary.case import Case
from src.discretionary.providers import batch_cli


def _candidate_rows(n_sessions: int = 6, per_session: int = 6) -> pd.DataFrame:
    rows = []
    for day in range(n_sessions):
        for name in range(per_session):
            rows.append({
                "symbol": f"S{name}",
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                "generator_score": float(name),
                "generator_reason": "test",
            })
    return pd.DataFrame(rows)


def test_clustered_sampler_freezes_four_cases_per_session():
    got = generators.sample(
        _candidate_rows(), n=20, strategy="clustered_by_session", seed=7)
    assert len(got) == 20
    assert got["date"].nunique() == 5
    assert set(got.groupby("date").size()) == {4}


def test_announcement_block_scrubs_identity_and_calendar_date():
    row = pd.Series({
        "symbol": "EXAMPLE",
        "announcements": [{
            "company": "Example Industries Limited",
            "subject": "Bagging/Receiving of orders/contracts",
            "details": ("Example Industries Limited received an order on "
                        "30/08/2024. EXAMPLE will execute it."),
        }],
    })
    block = case._announcement_block(row, anonymise=True)
    text = str(block)
    assert "Example Industries" not in text
    assert "EXAMPLE" not in text
    assert "30/08/2024" not in text
    assert "[company]" in text
    assert "[date]" in text


def test_low_capacity_announcement_generator_filters_and_consolidates(monkeypatch):
    date = pd.Timestamp("2024-01-02")
    panel = pd.DataFrame({
        "symbol": ["A", "B", "C"], "date": [date] * 3,
        "median_tv_20_cr": [2.0, 30.0, 2.0], "close": [50.0, 50.0, 5.0],
        "rs_60d_vs_mkt": [0.1, 0.2, 0.3], "ret_60d": [0.1, 0.2, 0.3],
        "series": ["EQ"] * 3, "is_etf": [False] * 3,
    })
    events = pd.DataFrame({
        "symbol": ["A", "A", "B", "C"],
        "first_tradable_session": [date] * 4,
        "subject": ["Acquisition", "Agreements", "Acquisition", "Acquisition"],
        "details": ["one", "two", "three", "four"],
        "company": ["A Ltd", "A Ltd", "B Ltd", "C Ltd"],
        "available_at": pd.to_datetime(["2024-01-01 16:00"] * 4),
    })
    monkeypatch.setattr(generators.frame, "load_events", lambda *a, **k: events)
    got = generators.low_capacity_announcement(panel, min_history=0)
    assert got[["symbol", "date"]].to_dict("records") == [
        {"symbol": "A", "date": date}]
    assert len(got.iloc[0]["announcements"]) == 2


def test_announcement_heuristic_matches_take_count():
    cases = []
    for i, subject in enumerate((
        "Defaults on Payment of Interest/Principal",
        "Resignation",
        "Agreements",
        "Bagging/Receiving of orders/contracts",
    )):
        cases.append(Case(
            case_id=f"C{i}", symbol=f"S{i}", date="2024-01-02",
            anonymised=True, generator_score=0.0, generator_reason="test",
            blocks={"announcement": {"disclosures": [
                {"subject": subject, "details": ""}]}}))
    got = baselines.announcement_heuristic(cases, "R", n_take=1)
    taken = [d.case_id for d in got if d.took]
    assert taken == ["C3"]


def test_matched_baseline_uses_the_ai_take_sessions():
    cases = [Case(
        case_id=f"C{i}", symbol=f"S{i}", date="2024-01-02" if i < 4 else "2024-01-03",
        anonymised=True, generator_score=float(i), generator_reason="test")
        for i in range(8)]
    got = baselines.top_n_by_score(
        cases, "R", n_take=1, take_by_session={"2024-01-03": 1})
    assert [d.case_id for d in got if d.took] == ["C7"]


def test_batch_parser_accepts_plain_json_array():
    assert batch_cli._extract_array('[{"case_id":"C1"}]') == [
        {"case_id": "C1"}]
