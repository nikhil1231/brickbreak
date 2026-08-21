"""The comparative evaluation — did selection improve on the pool it was given?

MISSION §7 asks for the selector to be evaluated separately from the strategy,
and the distinction is the whole report: "the AI made 3%" is not a finding,
"the AI's picks beat the candidates it picked them from by 80 bps, and beat a
ranking on the generator's own score by 30" is.

EVERY CONTRAST IS PAIRED WITHIN THE SESSION
This project already paid for the lesson (H020): matched controls drawn from
+/-2 sessions tripled every contrast, because winners cluster on local market
troughs and a control two days away sits 0.45% higher in the index 71% of the
time. So a contrast here is a *per-session difference of means* — computed only
on sessions where both arms are present — and never a pooled difference across
a shuffled calendar.

That also removes the market from the comparison twice over: the outcomes are
already excess returns over the equal-weighted market, and the pairing removes
whatever the session did on top. MISSION §5's market baseline is therefore the
zero line of every number here rather than an arm someone has to remember.

THE T-STATISTIC IS CORRECTED TWICE, AND STILL WANTS READING AGAINST n
Overlapping forward windows inflate every t by roughly sqrt(horizon), which
`cluster_stats(lags=h-1)` corrects, and clustering handles the cross-section
within a session. Neither invents independent observations: at 500 cases over a
few hundred sessions at a ten-session horizon there are only tens of
non-overlapping blocks, so `n_sessions` is reported beside every t and a
marginal result should be read against it. This loop detects *large* selector
effects. That is consistent with what the lab already knows about itself — it
is short of magnitude, not of significance.

COSTS ARE CHARGED WHERE THEY BITE
A lift is a difference between two selections that both pay the round trip, so
the cost does not enter it. A *level* — what a TAKE actually returned — does,
and both are reported: `mean_excess_pct` gross and `net_of_costs_pct` after
0.40%, which is this project's measured conservative floor.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ..alpha_eval.backtest import COST_PCT_ROUND_TRIP
from ..alpha_eval import diagnostics
from ..runner import burden as burden_mod
from .decision import AI_DECIDER, Decision
from .opportunity import MIN_MEANINGFUL, OpportunityDef

logger = logging.getLogger(__name__)

# Confidence buckets for the calibration read. Coarse on purpose: at 500 cases
# a ten-bucket calibration curve is mostly sampling noise dressed as a shape.
CONFIDENCE_BINS = (0.0, 0.4, 0.55, 0.7, 1.01)
CONFIDENCE_LABELS = ("<0.40", "0.40-0.55", "0.55-0.70", ">0.70")

# Strata the report always breaks results down by, where the column exists.
STRATA = {
    "regime": "mkt_regime",
    "sector": "sector",
    "liquidity_quintile": "_liq_q",
    "size_tier": "size_tier",
}


class EvaluationError(RuntimeError):
    pass


def _stats(y: pd.Series, dates: pd.Series, lags: int) -> dict[str, Any]:
    s = diagnostics.cluster_stats(y, dates, lags=lags)
    vals = y.dropna()
    wins, losses = vals[vals > 0], vals[vals <= 0]
    s["mean_win_pct"] = round(float(wins.mean()), 4) if len(wins) else np.nan
    s["mean_loss_pct"] = round(float(losses.mean()), 4) if len(losses) else np.nan
    s["payoff_ratio"] = (round(abs(float(wins.mean()) / float(losses.mean())), 3)
                         if len(wins) and len(losses) and losses.mean() != 0
                         else np.nan)
    s["net_of_costs_pct"] = (round(float(vals.mean()) - COST_PCT_ROUND_TRIP, 4)
                             if len(vals) else np.nan)
    return s


def session_paired_contrast(df: pd.DataFrame, a: pd.Series, b: pd.Series,
                            value_col: str, lags: int) -> dict[str, Any]:
    """Mean per-session difference between two arms, with a corrected t.

    Only sessions carrying *both* arms contribute. A session where one side is
    empty carries no information about their difference, and including it as a
    one-sided level would smuggle the session's own return into the contrast —
    which is exactly the H020 error in a different costume.
    """
    d = df[["date", value_col]].copy()
    d["_a"], d["_b"] = a.to_numpy(), b.to_numpy()
    d = d[d[value_col].notna()]
    if d.empty:
        return {"n_sessions": 0, "mean_diff_bps": np.nan, "t": np.nan}

    g = d.groupby("date")
    ma = g.apply(lambda x: x.loc[x["_a"], value_col].mean(), include_groups=False)
    mb = g.apply(lambda x: x.loc[x["_b"], value_col].mean(), include_groups=False)
    both = ma.notna() & mb.notna()
    delta = (ma[both] - mb[both])
    if delta.empty:
        return {"n_sessions": 0, "mean_diff_bps": np.nan, "t": np.nan,
                "note": "no session carried both arms"}

    st = diagnostics.cluster_stats(delta, pd.Series(delta.index, index=delta.index),
                                   lags=lags)
    return {
        "n_sessions": int(len(delta)),
        "mean_diff_pct": round(float(delta.mean()), 4),
        "mean_diff_bps": round(float(delta.mean()) * 100.0, 1),
        "median_diff_bps": round(float(delta.median()) * 100.0, 1),
        "sessions_positive_pct": round(float((delta > 0).mean() * 100), 1),
        "t": st["t"],
        "naive_t": st["naive_t"],
        "hac_lags": lags,
    }


def _frame(decisions: list[Decision], outcomes: pd.DataFrame,
           cases_meta: pd.DataFrame | None, value_col: str) -> pd.DataFrame:
    """One row per (case, arm), with the outcome and the strata attached."""
    dec = pd.DataFrame([{
        "case_id": d.case_id, "decider": d.decider, "action": d.action,
        "took": d.took, "confidence": d.confidence, "tags": d.tags,
        "error": d.error,
    } for d in decisions])
    if dec.empty:
        raise EvaluationError("no decisions to evaluate")

    out = outcomes.copy()
    out["date"] = pd.to_datetime(out["date"])
    keep = ["case_id", "symbol", "date", "mfe_pct", "mae_pct"]
    keep += [c for c in out.columns if c.startswith(("ret_", "excess_", "mkt_",
                                                     "primary_"))]
    merged = dec.merge(out[[c for c in keep if c in out.columns]],
                       on="case_id", how="left")
    if cases_meta is not None and not cases_meta.empty:
        merged = merged.merge(cases_meta, on="case_id", how="left")

    if "median_tv_20_cr" in merged.columns:
        merged["_liq_q"] = pd.qcut(merged["median_tv_20_cr"], 5,
                                   labels=[f"Q{i}" for i in range(1, 6)],
                                   duplicates="drop")
    return merged


def evaluate(decisions: list[Decision], outcomes: pd.DataFrame,
             defn: OpportunityDef,
             cases_meta: pd.DataFrame | None = None) -> dict[str, Any]:
    """The full selector report."""
    h = defn.primary_horizon
    lags = max(h - 1, 0)
    value_col = "primary_excess_pct"
    if value_col not in outcomes.columns:
        raise EvaluationError(
            f"outcomes carry no {value_col}; run the reveal phase first")

    df = _frame(decisions, outcomes, cases_meta, value_col)
    ai = df[df["decider"] == AI_DECIDER].reset_index(drop=True)
    if ai.empty:
        raise EvaluationError("no AI decisions in this replay")

    report: dict[str, Any] = {
        "replay_id": defn.id,
        "hypothesis_id": defn.hypothesis_id,
        "idea": defn.idea,
        "partition": defn.partition,
        "primary_horizon": h,
        "generator": defn.generator,
        "anonymised": defn.anonymise,
        "n_cases": int(len(ai)),
        "n_sessions": int(ai["date"].nunique()),
        "cost_pct_round_trip": COST_PCT_ROUND_TRIP,
        "benchmark_note": (
            "every outcome is excess return over the equal-weighted market "
            "compounded across the same holding window, so MISSION §5's market "
            "baseline is the zero line of every number here"),
    }

    # -- 1. the arms, as levels ------------------------------------------
    took = ai["took"].to_numpy(bool)
    report["ai"] = {
        "take_rate_pct": round(float(took.mean() * 100), 2),
        "n_taken": int(took.sum()),
        "action_mix": ai["action"].value_counts().to_dict(),
        "n_failed_calls": int((ai["error"].fillna("") != "").sum()),
        "taken": _stats(ai.loc[took, value_col], ai.loc[took, "date"], lags),
        "skipped": _stats(ai.loc[~took, value_col], ai.loc[~took, "date"], lags),
        "all_candidates": _stats(ai[value_col], ai["date"], lags),
    }
    for name in ("mfe_pct", "mae_pct"):
        if name in ai.columns:
            report["ai"][f"taken_{name}"] = round(
                float(ai.loc[took, name].mean()), 3)
            report["ai"][f"pool_{name}"] = round(float(ai[name].mean()), 3)

    # -- 2. the contrasts MISSION §7 names --------------------------------
    all_true = pd.Series(np.ones(len(ai), dtype=bool))
    contrasts = {
        "take_vs_skip": session_paired_contrast(
            ai, pd.Series(took), pd.Series(~took), value_col, lags),
        "take_vs_pool": session_paired_contrast(
            ai, pd.Series(took), all_true, value_col, lags),
    }

    # -- 3. against each baseline, on the identical cases ------------------
    baseline_rows = {}
    for name in sorted(set(df["decider"]) - {AI_DECIDER}):
        arm = df[df["decider"] == name].set_index("case_id").reindex(
            ai["case_id"]).reset_index()
        arm_took = arm["took"].fillna(False).to_numpy(bool)
        baseline_rows[name] = {
            "take_rate_pct": round(float(arm_took.mean() * 100), 2),
            "taken": _stats(ai.loc[arm_took, value_col],
                            ai.loc[arm_took, "date"], lags),
            "ai_minus_this": session_paired_contrast(
                ai, pd.Series(took), pd.Series(arm_took), value_col, lags),
        }
    report["baselines"] = baseline_rows

    quant = {n: v for n, v in baseline_rows.items() if n != "take_all"}
    if quant:
        best = max(
            quant.items(),
            key=lambda kv: (kv[1]["taken"].get("mean") if
                            np.isfinite(kv[1]["taken"].get("mean", np.nan))
                            else -np.inf))
        contrasts["ai_vs_best_baseline"] = dict(
            best[1]["ai_minus_this"], baseline=best[0])
    report["contrasts"] = contrasts

    # -- 4. calibration ----------------------------------------------------
    report["calibration"] = _calibration(ai, value_col, lags)

    # -- 5. stratification and stability -----------------------------------
    report["by_stratum"] = {
        label: _by_group(ai, col, value_col, lags)
        for label, col in STRATA.items() if col in ai.columns}
    report["by_quarter"] = _by_group(
        ai.assign(_q=ai["date"].dt.to_period("Q").astype(str)),
        "_q", value_col, lags)

    # -- 6. the reasoning, for MISSION §8 ----------------------------------
    report["by_tag"] = _by_tag(ai, value_col, lags)

    # -- 7. the verdict against the frozen bar -----------------------------
    report["headline"] = _headline(report)
    report["multiplicity"] = burden_mod.assess(
        report["headline"].get("take_vs_skip_t"), defn.partition).to_dict()
    report["verdict"] = _verdict(report, defn)
    return report


def _calibration(ai: pd.DataFrame, value_col: str, lags: int) -> dict[str, Any]:
    """Does stated confidence predict, and does more of it predict more?

    Reported as a slope in bps per unit of confidence *and* as buckets, because
    a slope can be produced by two points and the buckets show whether the
    relationship is monotone — which is the property MISSION §7 actually asks
    about ("whether higher-confidence decisions actually perform better").
    """
    d = ai[ai["took"]][["confidence", value_col, "date"]].dropna()
    # Three distinct values, not two: a line through two points is exact by
    # construction, and a judge that only ever says 0.6 or 0.7 would produce a
    # slope that means nothing and could still clear a calibration bar.
    if len(d) < 20 or d["confidence"].nunique() < 3:
        return {"n": int(len(d)),
                "distinct_confidences": int(d["confidence"].nunique()),
                "note": "too few taken cases, or fewer than three distinct "
                        "confidence values, to say anything about calibration"}
    x = d["confidence"].to_numpy(float)
    y = d[value_col].to_numpy(float)
    slope, intercept = np.polyfit(x, y, 1)
    buckets = []
    d = d.assign(_b=pd.cut(d["confidence"], bins=list(CONFIDENCE_BINS),
                           labels=list(CONFIDENCE_LABELS), right=False))
    for label, g in d.groupby("_b", observed=True):
        if len(g) < 5:
            continue
        buckets.append({"bucket": str(label), "n": int(len(g)),
                        "mean_excess_bps": round(float(g[value_col].mean()) * 100, 1)})
    means = [b["mean_excess_bps"] for b in buckets]
    return {
        "n": int(len(d)),
        "slope_bps_per_unit": round(float(slope) * 100, 1),
        "intercept_bps": round(float(intercept) * 100, 1),
        "buckets": buckets,
        "monotone": bool(len(means) > 1 and all(
            b >= a for a, b in zip(means, means[1:]))),
    }


def _by_group(ai: pd.DataFrame, col: str, value_col: str, lags: int,
              min_taken: int = 8) -> list[dict[str, Any]]:
    """Take-vs-pool lift within each level of a conditioning variable."""
    rows = []
    for g, sub in ai.groupby(col, observed=True, sort=True):
        took = sub["took"].to_numpy(bool)
        if took.sum() < min_taken:
            continue
        rows.append({
            "group": str(g),
            "n_cases": int(len(sub)),
            "n_taken": int(took.sum()),
            "take_rate_pct": round(float(took.mean() * 100), 1),
            "taken_mean_bps": round(float(sub.loc[took, value_col].mean()) * 100, 1),
            "pool_mean_bps": round(float(sub[value_col].mean()) * 100, 1),
            "lift": session_paired_contrast(
                sub.reset_index(drop=True), pd.Series(took),
                pd.Series(np.ones(len(sub), dtype=bool)), value_col, lags),
        })
    return rows


def _by_tag(ai: pd.DataFrame, value_col: str, lags: int,
            min_taken: int = 8) -> list[dict[str, Any]]:
    """Which kinds of reasoning actually preceded a good outcome (MISSION §8).

    Association, not cause. A tag is claimed by the judge, not assigned by the
    lab, so a tag that reads well may only mark the cases where the judge felt
    articulate. Reported because the question is worth asking and because the
    closed vocabulary makes it answerable — not because the answer is causal.
    """
    taken = ai[ai["took"]]
    if taken.empty:
        return []
    rows = []
    all_tags = sorted({t for tags in taken["tags"] for t in (tags or [])})
    for tag in all_tags:
        mask = taken["tags"].apply(lambda ts: tag in (ts or []))
        if mask.sum() < min_taken:
            continue
        sub = taken[mask]
        rows.append({
            "tag": tag,
            "n_taken_with_tag": int(mask.sum()),
            "share_of_takes_pct": round(float(mask.mean() * 100), 1),
            "mean_excess_bps": round(float(sub[value_col].mean()) * 100, 1),
            "vs_other_takes_bps": round(
                (float(sub[value_col].mean())
                 - float(taken.loc[~mask, value_col].mean())) * 100, 1)
            if (~mask).sum() else np.nan,
            "hit_rate_pct": round(float((sub[value_col] > 0).mean() * 100), 1),
        })
    return sorted(rows, key=lambda r: -(r["mean_excess_bps"] or 0))


def _headline(report: dict[str, Any]) -> dict[str, Any]:
    c = report["contrasts"]
    best = c.get("ai_vs_best_baseline", {})
    return {
        "take_rate_pct": report["ai"]["take_rate_pct"],
        "n_taken": report["ai"]["n_taken"],
        "taken_mean_excess_bps": round(
            (report["ai"]["taken"].get("mean") or 0.0) * 100, 1),
        "taken_net_of_costs_bps": round(
            (report["ai"]["taken"].get("net_of_costs_pct") or 0.0) * 100, 1),
        "excess_lift_bps": c["take_vs_pool"].get("mean_diff_bps"),
        "excess_lift_t": c["take_vs_pool"].get("t"),
        "take_vs_skip_bps": c["take_vs_skip"].get("mean_diff_bps"),
        "take_vs_skip_t": c["take_vs_skip"].get("t"),
        "lift_over_baseline_bps": best.get("mean_diff_bps"),
        "lift_over_baseline_t": best.get("t"),
        "best_baseline": best.get("baseline"),
        "calibration_slope_bps": report["calibration"].get("slope_bps_per_unit"),
        "effective_sessions": c["take_vs_pool"].get("n_sessions"),
        # Sessions overlap: at horizon h only about n/h of them are
        # independent. Quoted directly because it is the number a marginal
        # t-statistic has to be read against, and it is usually startling.
        "independent_blocks": (
            int((c["take_vs_pool"].get("n_sessions") or 0)
                / max(report["primary_horizon"], 1))),
    }


def _verdict(report: dict[str, Any], defn: OpportunityDef) -> dict[str, Any]:
    """Against the bar frozen before the run, and only against that bar.

    A bar applied only when it is passed is not a bar. Every criterion the
    definition named is checked; anything it did not name is reported but
    cannot rescue the result.
    """
    hl = report["headline"]
    measured = {
        "min_excess_lift_bps": hl.get("excess_lift_bps"),
        "min_take_vs_skip_bps": hl.get("take_vs_skip_bps"),
        "min_lift_over_baseline_bps": hl.get("lift_over_baseline_bps"),
        "min_calibration_slope_bps": hl.get("calibration_slope_bps"),
    }
    checks = []
    for key, bar in defn.pass_criterion.items():
        got = measured.get(key)
        ok = bool(got is not None and np.isfinite(got) and got >= bar)
        checks.append({"criterion": key, "bar": bar, "measured": got,
                       "passed": ok})
    passed = bool(checks) and all(c["passed"] for c in checks)

    if not report["ai"]["n_taken"]:
        cls, statement = "INSUFFICIENT_SAMPLE", (
            "the selector took nothing, so there is no selection to evaluate")
    elif passed:
        cls, statement = "SUCCESS", (
            f"selection beat the pool it was drawn from by "
            f"{hl['excess_lift_bps']} bps (t={hl['excess_lift_t']}) over "
            f"{hl['effective_sessions']} sessions, and cleared every bar frozen "
            f"before the run")
    elif (hl.get("excess_lift_bps") or 0) > 0 and not any(
            c["passed"] for c in checks):
        cls, statement = "SIGNAL_TOO_SMALL", (
            f"selection was positive at {hl['excess_lift_bps']} bps but did not "
            f"reach the bar; on this sample that is indistinguishable from a "
            f"selector with no edge")
    else:
        cls, statement = "NO_SIGNAL", (
            f"selection did not improve on the pool it was given "
            f"({hl.get('excess_lift_bps')} bps, t={hl.get('excess_lift_t')})")

    return {
        "failure_class": cls,
        "passed": passed,
        "checks": checks,
        "statement": statement,
        "sample_caveat": (
            f"{hl.get('effective_sessions')} sessions carried both arms at a "
            f"{report['primary_horizon']}-session horizon — about "
            f"{hl.get('independent_blocks')} independent blocks. The "
            f"t-statistics are session-clustered and Hansen-Hodrick corrected, "
            f"but neither correction invents independent observations: measured "
            f"on a null selector at this block count the corrected |t| still "
            f"exceeds 1.96 about 13% of the time, not 5%. That is why the bar "
            f"is denominated in basis points rather than in t — magnitude is "
            f"what this lab is short of, and a bar in bps rejected the same "
            f"null selectors 98% of the time. Do not promote on the "
            f"t-statistic alone."),
    }
