"""LLM memory and recognition controls (PLAN.md §8 and H042).

WHY THIS MODULE EXISTS
No frame hygiene closes a leak that lives in the model's weights. An LLM asked
about an Indian equity in a named historical quarter may simply recall what
happened next. Removing the symbol and date is necessary, but distinctive price
paths, volatility scales, and market contexts can still trigger recall.

This module supplies:
1. RECOGNITION PROBE: explicitly tests whether a model can identify the
   underlying ticker or date from the anonymised case description alone.
   Recognised cases are quarantined.
2. MEMORY CLASSIFICATION: tags every discretionary case, decision and replay
   with its provenance (anonymised-unrecognised, anonymised-recognised,
   revealed-control, forward-chronological).
3. H042 PAIRED CONTROL: evaluates a paired experiment (anonymised vs revealed
   identity) over the same case set to measure the recall premium.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Sequence


from .case import Case
from .decision import Decision

logger = logging.getLogger(__name__)


# Memory risk classifications
MEMORY_ANONYMISED_CLEAN = "anonymised_unrecognised"
MEMORY_ANONYMISED_QUARANTINED = "anonymised_recognised"
MEMORY_REVEALED_CONTROL = "revealed_control"
MEMORY_FORWARD_CHRONOLOGICAL = "forward_post_cutoff"

VALID_MEMORY_CLASSES = frozenset({
    MEMORY_ANONYMISED_CLEAN,
    MEMORY_ANONYMISED_QUARANTINED,
    MEMORY_REVEALED_CONTROL,
    MEMORY_FORWARD_CHRONOLOGICAL,
})


class MemoryControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecognitionProbeResult:
    """The result of probing whether a model recognizes an anonymised case."""
    case_id: str
    ground_truth_symbol: str
    ground_truth_date: str
    recognized: bool
    predicted_symbol: str | None
    predicted_date: str | None
    confidence: float
    reasoning: str
    symbol_matched: bool
    date_matched: bool

    @property
    def is_quarantined(self) -> bool:
        """A case is quarantined if the model correctly identified the ticker."""
        return self.symbol_matched

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RECOGNITION_PROBE_SYSTEM_PROMPT = """You are an expert financial analyst inspecting an anonymised trading case.
Your goal is to determine if you can recognize the specific stock ticker (NSE equity) and/or trading date/period from the price action, market context, or numbers.

Inspect the case carefully and answer in JSON format:
{
  "recognized": true | false,
  "predicted_symbol": "<NSE ticker or null>",
  "predicted_date": "<YYYY-MM-DD or approx period, or null>",
  "confidence": <float from 0.0 to 1.0>,
  "reasoning": "<concise explanation of clues that identify or fail to identify the entity>"
}
Do not guess randomly; state high confidence only if specific idiosyncratic features identify the entity.
"""


def format_recognition_prompt(case_text: str) -> str:
    """Prepare the recognition probe user prompt."""
    return (
        f"Here is an anonymised trading situation:\n\n"
        f"{case_text}\n\n"
        f"Can you identify which NSE stock and time period this situation represents?\n"
        f"Respond strictly in the JSON format specified."
    )


def parse_recognition_response(case: Case, response_text: str) -> RecognitionProbeResult:
    """Parse probe JSON output and evaluate ground truth match."""
    # Extract JSON blob
    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if not match:
        return RecognitionProbeResult(
            case_id=case.case_id,
            ground_truth_symbol=case.symbol,
            ground_truth_date=case.date,
            recognized=False,
            predicted_symbol=None,
            predicted_date=None,
            confidence=0.0,
            reasoning="Unparseable response",
            symbol_matched=False,
            date_matched=False,
        )

    try:
        data = json.loads(match.group(0))
    except Exception:
        return RecognitionProbeResult(
            case_id=case.case_id,
            ground_truth_symbol=case.symbol,
            ground_truth_date=case.date,
            recognized=False,
            predicted_symbol=None,
            predicted_date=None,
            confidence=0.0,
            reasoning="Invalid JSON",
            symbol_matched=False,
            date_matched=False,
        )

    pred_sym = str(data.get("predicted_symbol") or "").strip().upper() or None
    pred_dt = str(data.get("predicted_date") or "").strip() or None
    conf = float(data.get("confidence") or 0.0)
    reasoning = str(data.get("reasoning") or "").strip()
    recognized = bool(data.get("recognized", False)) or (pred_sym is not None and pred_sym != "NULL")

    sym_match = False
    if pred_sym and case.symbol and pred_sym != "NULL":
        gt_sym = case.symbol.strip().upper()
        sym_match = (pred_sym == gt_sym or pred_sym in gt_sym or gt_sym in pred_sym)

    dt_match = False
    if pred_dt and case.date and pred_dt != "NULL":
        gt_dt = case.date[:7]  # YYYY-MM prefix match
        dt_match = gt_dt in pred_dt

    return RecognitionProbeResult(
        case_id=case.case_id,
        ground_truth_symbol=case.symbol,
        ground_truth_date=case.date,
        recognized=recognized,
        predicted_symbol=pred_sym,
        predicted_date=pred_dt,
        confidence=conf,
        reasoning=reasoning,
        symbol_matched=sym_match,
        date_matched=dt_match,
    )


def quarantine_cases(cases: Sequence[Case],
                     probe_results: Sequence[RecognitionProbeResult]
                     ) -> tuple[list[Case], list[Case]]:
    """Partition cases into clean (unrecognised) and quarantined (recognised)."""
    quarantined_ids = {p.case_id for p in probe_results if p.is_quarantined}
    clean: list[Case] = []
    quarantined: list[Case] = []
    for c in cases:
        if c.case_id in quarantined_ids:
            quarantined.append(c)
        else:
            clean.append(c)
    return clean, quarantined


def classify_case_memory_risk(case: Case,
                              is_recognised: bool = False,
                              is_forward: bool = False) -> str:
    """Return the memory classification for a case."""
    if is_forward:
        return MEMORY_FORWARD_CHRONOLOGICAL
    if not case.anonymised:
        return MEMORY_REVEALED_CONTROL
    if is_recognised:
        return MEMORY_ANONYMISED_QUARANTINED
    return MEMORY_ANONYMISED_CLEAN


def evaluate_h042_paired_control(anonymised_report: dict[str, Any],
                                  revealed_report: dict[str, Any],
                                  anonymised_decisions: Sequence[Decision] | None = None,
                                  revealed_decisions: Sequence[Decision] | None = None
                                  ) -> dict[str, Any]:
    """H042 control: compare anonymised replay vs revealed-identity replay.

    Claim: Revealed identity beats anonymised identity, i.e. the model remembers.
    A positive result (revealed beats anonymised materially) indicates memory
    contamination in historical replays.
    """
    anon_hl = anonymised_report.get("headline", {})
    rev_hl = revealed_report.get("headline", {})

    anon_lift = anon_hl.get("excess_lift_bps", 0.0)
    rev_lift = rev_hl.get("excess_lift_bps", 0.0)
    lift_delta = rev_lift - anon_lift

    anon_t = anon_hl.get("excess_lift_t", 0.0)
    rev_t = rev_hl.get("excess_lift_t", 0.0)
    t_delta = rev_t - anon_t

    agreement_pct = None
    if anonymised_decisions and revealed_decisions:
        anon_dict = {d.case_id: d.action for d in anonymised_decisions}
        rev_dict = {d.case_id: d.action for d in revealed_decisions}
        common = [c for c in anon_dict if c in rev_dict]
        if common:
            same = sum(1 for c in common if anon_dict[c] == rev_dict[c])
            agreement_pct = round(100.0 * same / len(common), 2)

    # Classification logic based on PLAN §8 & H042
    if lift_delta >= 40.0 and t_delta >= 2.0:
        verdict = "RECALL_DOMINATED"
        reading = (
            f"Revealed identity outscored anonymised identity by +{lift_delta:.1f} bps "
            f"(t-delta +{t_delta:.2f}). The decider shows strong evidence of memorisation "
            f"advantage. Historical anonymised results carry substantial memory risk."
        )
        hypothesis_h042_confirmed = True
    elif lift_delta >= 20.0 and t_delta >= 1.5:
        verdict = "MARGINAL_RECALL"
        reading = (
            f"Revealed identity showed modest lift over anonymised (+{lift_delta:.1f} bps, "
            f"t-delta +{t_delta:.2f}). Memory effect is non-zero but not fully dominant."
        )
        hypothesis_h042_confirmed = True
    else:
        verdict = "NO_EVIDENT_RECALL"
        reading = (
            f"Revealed identity did not materially beat anonymised identity "
            f"(lift delta {lift_delta:+.1f} bps, t-delta {t_delta:+.2f}). "
            f"No evidence that historical ticker/date visibility drives performance. "
            f"Anonymised replay decisions reflect case features rather than memorised tape."
        )
        hypothesis_h042_confirmed = False

    return {
        "hypothesis": "H042",
        "verdict": verdict,
        "hypothesis_h042_confirmed": hypothesis_h042_confirmed,
        "anonymised_excess_lift_bps": anon_lift,
        "revealed_excess_lift_bps": rev_lift,
        "lift_delta_bps": round(lift_delta, 2),
        "anonymised_excess_lift_t": anon_t,
        "revealed_excess_lift_t": rev_t,
        "t_delta": round(t_delta, 2),
        "decision_agreement_pct": agreement_pct,
        "reading": reading,
    }
