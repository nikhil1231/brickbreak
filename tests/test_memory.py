"""Tests for memory controls, recognition probe and H042 paired control."""
from __future__ import annotations


from src.discretionary.case import Case
from src.discretionary.memory import (
    MEMORY_ANONYMISED_CLEAN,
    MEMORY_ANONYMISED_QUARANTINED,
    MEMORY_FORWARD_CHRONOLOGICAL,
    MEMORY_REVEALED_CONTROL,
    classify_case_memory_risk,
    evaluate_h042_paired_control,
    format_recognition_prompt,
    parse_recognition_response,
    quarantine_cases,
)


def _sample_case(case_id="C001", symbol="RELIANCE", date="2022-05-10", anonymised=True):
    return Case(
        case_id=case_id,
        symbol=symbol,
        date=date,
        anonymised=anonymised,
        generator_reason="breakout",
        generator_score=1.0,
        blocks={"location": {"open_vs_high_20_pct": -0.5}},
    )


def test_recognition_prompt_formatting():
    case = _sample_case()
    prompt = format_recognition_prompt("Anonymised case text with rebased prices")
    assert "anonymised trading situation" in prompt.lower()
    assert "Anonymised case text" in prompt


def test_parse_recognition_response_matched_symbol():
    case = _sample_case(symbol="TCS", date="2021-08-15")
    llm_resp = '{"recognized": true, "predicted_symbol": "TCS", "predicted_date": "2021-08-15", "confidence": 0.95, "reasoning": "Clear IT bounce"}'
    res = parse_recognition_response(case, llm_resp)
    assert res.recognized
    assert res.predicted_symbol == "TCS"
    assert res.symbol_matched
    assert res.date_matched
    assert res.is_quarantined


def test_parse_recognition_response_unrecognised():
    case = _sample_case(symbol="INFY", date="2021-08-15")
    llm_resp = '{"recognized": false, "predicted_symbol": null, "predicted_date": null, "confidence": 0.1, "reasoning": "Generic chart"}'
    res = parse_recognition_response(case, llm_resp)
    assert not res.recognized
    assert not res.symbol_matched
    assert not res.is_quarantined


def test_quarantine_cases_partitions_properly():
    cases = [_sample_case(case_id=f"C{i:02d}", symbol=f"SYM{i}") for i in range(5)]
    from src.discretionary.memory import RecognitionProbeResult
    probes = [
        RecognitionProbeResult(
            case_id="C00", ground_truth_symbol="SYM0", ground_truth_date="2022-01-01",
            recognized=True, predicted_symbol="SYM0", predicted_date="2022-01-01",
            confidence=0.9, reasoning="", symbol_matched=True, date_matched=True,
        ),
        RecognitionProbeResult(
            case_id="C01", ground_truth_symbol="SYM1", ground_truth_date="2022-01-01",
            recognized=False, predicted_symbol="OTHER", predicted_date="2022-01-01",
            confidence=0.2, reasoning="", symbol_matched=False, date_matched=True,
        ),
    ]
    clean, quarantined = quarantine_cases(cases, probes)
    assert len(quarantined) == 1
    assert quarantined[0].case_id == "C00"
    assert len(clean) == 4


def test_classify_case_memory_risk():
    anon_case = _sample_case(anonymised=True)
    rev_case = _sample_case(anonymised=False)

    assert classify_case_memory_risk(anon_case, is_recognised=False) == MEMORY_ANONYMISED_CLEAN
    assert classify_case_memory_risk(anon_case, is_recognised=True) == MEMORY_ANONYMISED_QUARANTINED
    assert classify_case_memory_risk(rev_case) == MEMORY_REVEALED_CONTROL
    assert classify_case_memory_risk(anon_case, is_forward=True) == MEMORY_FORWARD_CHRONOLOGICAL


def test_h042_paired_control_evaluation():
    anon_rep = {"headline": {"excess_lift_bps": 50.0, "excess_lift_t": 2.2}}
    rev_rep_recall = {"headline": {"excess_lift_bps": 120.0, "excess_lift_t": 4.5}}

    res1 = evaluate_h042_paired_control(anon_rep, rev_rep_recall)
    assert res1["verdict"] == "RECALL_DOMINATED"
    assert res1["hypothesis_h042_confirmed"]
    assert res1["lift_delta_bps"] == 70.0

    rev_rep_clean = {"headline": {"excess_lift_bps": 52.0, "excess_lift_t": 2.3}}
    res2 = evaluate_h042_paired_control(anon_rep, rev_rep_clean)
    assert res2["verdict"] == "NO_EVIDENT_RECALL"
    assert not res2["hypothesis_h042_confirmed"]
