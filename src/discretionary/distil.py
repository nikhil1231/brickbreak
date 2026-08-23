"""DISTILLATION — turning what the judge said into something code can test.

WHY THIS STAGE EXISTS
The loop as it stood ended at LEARNING: the judge's verdicts were scored, the
tags were tabulated, and the next hypothesis was written by hand. That makes
the judge's *selection* the object under test, and a selection is the one thing
this lab cannot afford to test. Measured at the real 7.9% dispersion of 10-day
excess returns, a 500-case replay carries four independent blocks; 8.8% of
pure-noise selectors clear the bar there, and a genuine 150 bps edge is found
less than half the time even at four times that budget. No amount of prompt
work moves those numbers, because they are set by the case budget and the case
budget is set by what a model call costs.

The way out is to stop measuring the picks and start measuring the *reasons*.
A judge that says "these 40" hands over 40 observations. A judge that says "I
took them because the base was tightening while volume dried up" hands over a
predicate, and a predicate can be run across every row of the panel — six
figures of situations, at no cost per row, with the statistical power that
follows. The expensive model becomes the thing that proposes the rule; the
cheap scan becomes the thing that tests it.

So the judge's output is not a verdict to be trusted. It is a hypothesis to be
falsified by machinery that already exists.

THE TWO QUESTIONS, AND WHY BOTH ARE NEEDED
A distilled rule is scored on two axes and they are independent:

  FIDELITY   does the coded rule reproduce the judge's own picks? A rule with
             low fidelity may be a fine rule, but it is not *this judge's*
             reason, so it cannot be read as evidence about discretionary
             judgement. It is a new idea that happened to be found nearby.

  EDGE       does the rule carry a lift at panel scale, where there is enough
             sample to say? This is measured by the signal path, not here.

The interesting cell is high fidelity and no edge: the judge's stated reason is
faithfully captured and is worth nothing, which is the most common way a
persuasive rationale turns out to be a post-hoc story. The dangerous cell is
low fidelity and an edge, because it reads as a success and is not one.

THE AUTHORING RULE THAT MAKES THIS HONEST
A rule must be written from the reasoning text and the case columns **only** —
never with the outcomes in view. Writing a predicate while able to see which
takes worked is not distillation, it is fitting a curve to 40 points and then
claiming a model proposed it. `propose_from_replay` refuses to return anything
if the frame it is handed carries a forward label, and the refusal is the point
rather than a convenience.

WHAT THIS MODULE DOES NOT DO
It does not write the predicate. Extracting a testable claim from a paragraph
of reasoning is the judgement call at the centre of this stage, and hiding it
behind a keyword matcher would produce rules nobody stands behind. This module
supplies the material, checks the predicate once written, scores fidelity, and
hands the survivor to the panel-scale evaluator.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels
from .decision import AI_DECIDER, Decision

logger = logging.getLogger(__name__)


class DistillationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DistilledRule:
    """One claim the judge made, written so a machine can disagree with it.

    `expression` is a pandas `query` string over panel columns. A string rather
    than a lambda so that the rule is serialisable, hashable, diffable, and
    reviewable — a rule nobody can read is a rule nobody can refute.
    """
    name: str
    claim: str                      # the judge's sentence, quoted
    expression: str                 # pandas query over point-in-time columns
    source_replay: str
    source_tags: tuple[str, ...] = ()
    author_note: str = ""

    def __post_init__(self) -> None:
        for field_name in ("name", "claim", "expression", "source_replay"):
            if not str(getattr(self, field_name)).strip():
                raise DistillationError(
                    f"{field_name} is empty. A distilled rule that does not say "
                    f"which replay it came from, what was claimed, and how the "
                    f"claim is computed cannot be audited later, and an "
                    f"unauditable rule is how a lab acquires beliefs it cannot "
                    f"defend.")

    @property
    def rule_hash(self) -> str:
        payload = json.dumps({"expression": self.expression,
                              "source_replay": self.source_replay},
                             sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "rule_hash": self.rule_hash}


def propose_from_replay(decisions: Iterable[Decision],
                        cases_meta: pd.DataFrame | None = None
                        ) -> dict[str, Any]:
    """The material an author needs to write a rule, and nothing else.

    Deliberately outcome-free. `cases_meta`, if given, is checked for forward
    labels and refused if it carries any — writing a predicate with the answers
    on screen is not distillation.
    """
    if cases_meta is not None and len(cases_meta):
        assert_no_forward_labels(cases_meta, context="rule authoring")

    ai = [d for d in decisions if d.decider == AI_DECIDER]
    if not ai:
        raise DistillationError("no AI decisions to distil from")

    taken = [d for d in ai if d.action == "TAKE"]
    if not taken:
        raise DistillationError(
            "the judge took nothing, so it stated no reason for taking "
            "anything. A zero take rate is a valid replay outcome but it is "
            "not material to distil.")

    def _tag_counts(pool: list[Decision]) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in pool:
            for t in d.tags or ():
                out[t] = out.get(t, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    skipped = [d for d in ai if d.action != "TAKE"]
    take_tags, skip_tags = _tag_counts(taken), _tag_counts(skipped)

    # Tags that mark takes rather than merely being common. A tag claimed on
    # 90% of takes and 88% of skips describes the judge's vocabulary, not its
    # selection, and is the likeliest thing to be mistaken for a reason.
    discriminating = []
    for tag, n_take in take_tags.items():
        p_take = n_take / max(len(taken), 1)
        p_skip = skip_tags.get(tag, 0) / max(len(skipped), 1)
        discriminating.append({"tag": tag, "share_of_takes_pct": round(100 * p_take, 1),
                               "share_of_skips_pct": round(100 * p_skip, 1),
                               "separation_pp": round(100 * (p_take - p_skip), 1)})
    discriminating.sort(key=lambda r: -r["separation_pp"])

    return {
        "replay_id": ai[0].replay_id,
        "n_cases": len(ai),
        "n_taken": len(taken),
        "take_rate_pct": round(100 * len(taken) / len(ai), 2),
        "discriminating_tags": discriminating,
        # The raw text, because the rule is in here and not in the tag counts.
        "reasoning": [
            {"case_id": d.case_id, "action": d.action, "confidence": d.confidence,
             "unusual": d.unusual, "thesis": d.thesis,
             "competing_explanation": d.competing_explanation,
             "invalidation": d.invalidation, "asymmetry": d.asymmetry,
             "tags": list(d.tags or ())}
            for d in ai],
        "authoring_rule": (
            "write the predicate from this material and the case columns only. "
            "Outcomes are not available here by design; if you find yourself "
            "wanting them, the rule you are about to write is a fit, not a "
            "distillation."),
    }


def apply_rule(rule: DistilledRule, frame: pd.DataFrame) -> pd.Series:
    """The rule's mask over a frame, with the frame checked for leakage first."""
    assert_no_forward_labels(frame, context=f"applying rule {rule.name!r}")
    try:
        selected = frame.query(rule.expression, engine="python")
    except Exception as exc:                       # pandas raises many types
        raise DistillationError(
            f"rule {rule.name!r} did not evaluate against this frame: {exc}. "
            f"The expression may only reference point-in-time case columns.") from exc
    mask = pd.Series(False, index=frame.index)
    mask.loc[selected.index] = True
    return mask


def fidelity(rule_mask: pd.Series, ai_took: pd.Series,
             dates: pd.Series | None = None) -> dict[str, Any]:
    """Does the coded rule reproduce the judge's own picks?

    Reported alongside per-session agreement because a rule that matches the
    judge's *rate* while picking different names on every day has not captured
    the reason — it has captured the take rate, which is a property of the
    prompt rather than of the judgement.
    """
    r = np.asarray(rule_mask, dtype=bool)
    a = np.asarray(ai_took, dtype=bool)
    if len(r) != len(a):
        raise DistillationError(
            f"rule mask has {len(r)} rows and the decisions have {len(a)}; "
            f"fidelity is only defined on the same case set")

    tp = int((r & a).sum())
    out: dict[str, Any] = {
        "n_cases": int(len(r)),
        "rule_take_rate_pct": round(100 * float(r.mean()), 2),
        "ai_take_rate_pct": round(100 * float(a.mean()), 2),
        "agreement_pct": round(100 * float((r == a).mean()), 2),
        "precision_pct": round(100 * tp / max(int(r.sum()), 1), 2),
        "recall_pct": round(100 * tp / max(int(a.sum()), 1), 2),
    }
    # Cohen's kappa: agreement above what two arms with these rates would reach
    # by chance. The raw agreement of two 15% selectors is ~75% before either
    # has understood anything.
    po = float((r == a).mean())
    pe = float(r.mean() * a.mean() + (1 - r.mean()) * (1 - a.mean()))
    out["kappa"] = round((po - pe) / (1 - pe), 3) if pe < 1 else None

    if dates is not None:
        d = pd.DataFrame({"_d": np.asarray(dates), "_r": r, "_a": a})
        per = d.groupby("_d").apply(
            lambda g: float((g["_r"] == g["_a"]).mean()), include_groups=False)
        out["per_session_agreement_pct"] = round(100 * float(per.mean()), 2)
        out["sessions"] = int(len(per))
    return out


FIDELITY_FLOOR_KAPPA = 0.35


def classify(fidelity_report: dict[str, Any],
             panel_edge_bps: float | None,
             panel_passed: bool | None) -> dict[str, Any]:
    """The two-by-two the whole stage exists to fill in.

    `panel_edge_bps` and `panel_passed` come from the signal path — this module
    does not measure edge, because the point of distillation is that edge gets
    measured where the sample is, not where the judge is.
    """
    k = fidelity_report.get("kappa")
    faithful = k is not None and k >= FIDELITY_FLOOR_KAPPA

    if panel_passed is None:
        cell, reading = "UNTESTED", (
            "the rule has been written and its fidelity scored, but it has not "
            "been run at panel scale, which is the only place it can be judged")
    elif faithful and panel_passed:
        cell, reading = "DISTILLED", (
            "the judge's stated reason was captured and it carries an edge at "
            "panel scale — the strongest outcome this loop can produce, and "
            "the only one that yields something tradeable without a model in "
            "the execution path")
    elif faithful and not panel_passed:
        cell, reading = "REASON_WITHOUT_EDGE", (
            "the judge's reason was captured faithfully and is worth nothing. "
            "This is the common outcome and it is a real finding: a persuasive "
            "rationale that does not survive contact with sample")
    elif not faithful and panel_passed:
        cell, reading = "EDGE_WITHOUT_REASON", (
            "the rule works but does not reproduce the judge's picks, so it is "
            "not evidence about discretionary judgement — it is a new "
            "quantitative idea found nearby, and it must be registered as one "
            "rather than credited to the replay")
    else:
        cell, reading = "NEITHER", (
            "the rule neither reproduces the judge nor carries an edge; the "
            "distillation failed and the reasoning it came from is unexplained")

    return {"cell": cell, "faithful": bool(faithful),
            "kappa": k, "kappa_floor": FIDELITY_FLOOR_KAPPA,
            "panel_edge_bps": panel_edge_bps, "reading": reading}


@dataclass(frozen=True)
class FidelityHoldout:
    """A separate, frozen outcome-free case set for measuring fidelity (PLAN §8.1).

    Fidelity should be measured on an independent held-out set of cases
    so that rule authoring does not overfit to the discovery prompt cases.
    """
    holdout_id: str
    cases_hash: str
    n_cases: int
    fidelity_tokens_spent: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def measure_fidelity_on_holdout(rule: DistilledRule,
                                holdout_cases_meta: pd.DataFrame,
                                holdout_decisions: Iterable[Decision]
                                ) -> dict[str, Any]:
    """Measure fidelity of a distilled rule against an independent held-out case set."""
    assert_no_forward_labels(holdout_cases_meta, context="holdout fidelity scoring")
    ai_decisions = [d for d in holdout_decisions if d.decider == AI_DECIDER]
    if not ai_decisions:
        raise DistillationError("no AI decisions in holdout set")

    dec_map = {d.case_id: (d.action == "TAKE") for d in ai_decisions}
    if "case_id" not in holdout_cases_meta.columns:
        raise DistillationError("holdout_cases_meta must contain 'case_id'")

    common = [cid for cid in holdout_cases_meta["case_id"] if cid in dec_map]
    if len(common) != len(holdout_cases_meta):
        sub_meta = holdout_cases_meta[holdout_cases_meta["case_id"].isin(common)].copy()
    else:
        sub_meta = holdout_cases_meta

    rule_mask = apply_rule(rule, sub_meta)
    ai_took = pd.Series([dec_map[cid] for cid in sub_meta["case_id"]], index=sub_meta.index)
    dates = sub_meta["date"] if "date" in sub_meta.columns else None

    rep = fidelity(rule_mask, ai_took, dates=dates)
    rep["holdout_cases"] = len(sub_meta)
    return rep


def evaluate_distilled_rule(rule: DistilledRule,
                            panel_df: pd.DataFrame,
                            fidelity_report: dict[str, Any] | None = None,
                            forward_col: str = "fwd_ret_10d_pct",
                            horizons: tuple[int, ...] = (5, 10, 20),
                            run_backtest: bool = True,
                            run_neutralisation: bool = False
                            ) -> dict[str, Any]:
    """Connect a distilled rule directly to panel-scale alpha evaluation (PLAN §8.1).

    Evaluates whether the rule's predicate carries an edge across the full panel.
    Combines fidelity and edge into the 2x2 classification.
    """
    from ..alpha_eval import evaluate_signal

    df = panel_df.copy()
    sig_col = f"_distil_{rule.name}_{rule.rule_hash[:6]}"
    # Apply rule strictly on point-in-time columns (assert_no_forward_labels inside apply_rule)
    pit_cols = [c for c in df.columns if not str(c).startswith(("fwd_ret_", "excess_ret_"))]
    mask = apply_rule(rule, df[pit_cols])
    df[sig_col] = mask.astype(float)

    eval_rep = evaluate_signal(
        df,
        signal_col=sig_col,
        forward_col=forward_col,
        horizons=horizons,
        run_backtest=run_backtest,
        run_neutralisation=run_neutralisation,
    )

    q_prof = eval_rep.get("quantiles", {})
    spread_pct = q_prof.get("q5_spread_pct", 0.0)
    edge_bps = round(spread_pct * 100.0, 2)
    passed = bool(eval_rep.get("verdict", {}).get("passed", False))

    f_rep = fidelity_report or {}
    cls_rep = classify(f_rep, panel_edge_bps=edge_bps, panel_passed=passed)

    return {
        "rule": rule.to_dict(),
        "fidelity": f_rep,
        "classification": cls_rep,
        "alpha_evaluation": eval_rep,
    }

