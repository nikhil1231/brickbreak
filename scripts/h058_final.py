#!/usr/bin/env python
"""H058 final analysis. The study stopped early on its registered futility rule.

Inference follows PLAN.md 11: session clustering AND a Hansen-Hodrick correction
at the registered 18-session horizon, with effective independent blocks reported.
Clustering handles same-day cross-sectional dependence; HH handles serial
overlap. Autocovariances are accumulated only inside contiguous session runs,
because the test partition is five non-adjacent quarters and a lag that straddles
a two-year gap is not a lag.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.core import config  # noqa: E402
from src.research_data.pipelines import corporate_actions, fo_universe  # noqa: E402
from src.research.families import setup_grind, setup_grind_outcome as resolve  # noqa: E402

CONFIRMATORY_ORIGINALS = 733
HH_LAG = 18


def hansen_hodrick(series: pd.Series, sessions: pd.Series, lag: int):
    """Mean, HH standard error, and effective independent blocks."""
    frame = pd.DataFrame({"x": series.values}, index=pd.to_datetime(sessions.values))
    frame = frame.sort_index()
    x = frame["x"].to_numpy(dtype=float)
    n = len(x)
    if n < 3:
        return float(np.mean(x)) if n else np.nan, np.nan, np.nan
    dev = x - x.mean()
    gamma0 = float(dev @ dev) / n
    # Only pair observations that are genuinely `j` sessions apart in the same
    # contiguous run; the partition's quarter gaps are not lags.
    days = frame.index.to_numpy()
    total = gamma0
    for j in range(1, min(lag, n - 1) + 1):
        gap = (days[j:] - days[:-j]).astype("timedelta64[D]").astype(int)
        ok = gap <= j * 5          # ~5 calendar days per 1 session of slack
        if not ok.any():
            continue
        gj = float(dev[j:][ok] @ dev[:-j][ok]) / n
        total += 2.0 * gj
    total = max(total, gamma0 * 1e-6)      # HH is not guaranteed PSD
    se = float(np.sqrt(total / n))
    iid_se = float(np.sqrt(gamma0 / n))
    effective = n * (iid_se / se) ** 2 if se > 0 else np.nan
    return float(x.mean()), se, effective


def report(label, series, sessions):
    mean, se, blocks = hansen_hodrick(series, sessions, HH_LAG)
    t = mean / se if se and np.isfinite(se) and se > 0 else np.nan
    lo, hi = mean - 1.96 * se, mean + 1.96 * se
    print(f"  {label:<34} {mean:+.3f}R  SE {se:.3f}  t {t:+.2f}  "
          f"95% [{lo:+.3f}, {hi:+.3f}]  blocks {blocks:.0f}")
    return {"mean_r": mean, "se": se, "t": t, "ci95": [lo, hi],
            "effective_blocks": blocks, "n": int(len(series))}


def main() -> int:
    bundle = config.METADATA_DIR / "research_store" / "price_action" / "h058_stage2"
    private = {r["case_id"]: r for r in
               (json.loads(l) for l in
                (bundle / "cases_private.jsonl").read_text().splitlines() if l.strip())
               if r.get("case_status") == "ready"}
    draft = json.loads((bundle / "human_drafts" / "owner.json").read_text())
    marks = pd.DataFrame([{"case_id": k, **v["values"]}
                          for k, v in draft["annotations"].items()])
    for column in ("entry_atr", "stop_atr", "target_atr", "conviction"):
        marks[column] = pd.to_numeric(marks[column], errors="coerce")
    originals = sorted(r["slot_private"] for r in private.values()
                       if not r.get("is_repeat_private"))
    confirmatory = set(originals[:CONFIRMATORY_ORIGINALS])
    marks["slot"] = marks["case_id"].map(
        lambda c: private[c]["slot_private"] if c in private else -1)
    marks = marks.loc[marks["slot"].isin(confirmatory)]

    paths, adjustments = resolve._paths(
        private, fo_universe.load(), corporate_actions.load_adjusted())
    pairs = resolve.build_pairs(marks, private)

    rows = []
    for _, pair in pairs.iterrows():
        case = private[pair["take_case_id"]]
        take = resolve.resolve_case(case, paths, adjustments, pair["entry_atr"],
                                    pair["stop_atr"], pair["target_atr"])
        if take is None or "excluded" in take:
            continue
        controls = [g["r"] for cid in pair["control_case_ids"]
                    if (g := resolve.resolve_case(
                        private[cid], paths, adjustments, pair["entry_atr"],
                        pair["stop_atr"], pair["target_atr"])) is not None
                    and "excluded" not in g]
        # The registered mechanical comparator: Stage 0's median geometry.
        mech = resolve.resolve_case(case, paths, adjustments, 0.0, -0.88, 0.88 * 2.45)
        rows.append({
            "session": pd.Timestamp(case["decision_at_private"]),
            "take_r": take["r"], "outcome": take["outcome"],
            "control_r": float(np.mean(controls)) if controls else np.nan,
            "difference_r": take["r"] - float(np.mean(controls)) if controls else np.nan,
            "mechanical_r": mech["r"] if mech and "excluded" not in mech else np.nan,
            "direction": "long" if pair["stop_atr"] < pair["entry_atr"] else "short",
            "conviction": pair["conviction"],
            "reward_risk": abs(pair["target_atr"] - pair["entry_atr"])
                           / abs(pair["entry_atr"] - pair["stop_atr"]),
            "stop_distance": abs(pair["entry_atr"] - pair["stop_atr"]),
        })
    scored = pd.DataFrame(rows)
    paired = scored.dropna(subset=["difference_r"])

    print("\n=== H058 STAGE 2 — STOPPED EARLY ON THE REGISTERED FUTILITY RULE ===")
    print(f"takes resolved {len(scored)}, paired {len(paired)}, "
          f"unpairable {len(scored) - len(paired)}, "
          f"sessions {scored['session'].nunique()}")
    print(f"confirmatory population: first {CONFIRMATORY_ORIGINALS} originals; "
          f"{len(marks)} of them marked before the stop\n")

    print("PRIMARY — selection value (bar: >= +0.30R, clustered t >= 2.5)")
    primary = report("take minus matched skips", paired["difference_r"], paired["session"])
    print("\nSECONDARY — tradability (bar: >= +0.20R), all takes")
    tradability = report("mean R on takes, net of costs", scored["take_r"], scored["session"])
    print("\nREPORTED, NOT GATED")
    control = report("matched skips, same geometry", paired["control_r"], paired["session"])
    execution = report("his geometry minus mechanical",
                       (scored["take_r"] - scored["mechanical_r"]).dropna(),
                       scored.loc[(scored["take_r"] - scored["mechanical_r"]).notna(), "session"])

    print(f"\noutcome mix: {scored['outcome'].value_counts().to_dict()}")

    print("\nPRE-REGISTERED SPLITS — underpowered by construction at this size,")
    print("reported with intervals because the plan requires it, not because they")
    print("can distinguish anything. None may be promoted.")
    splits = {}
    for name, mask in [
        ("direction: long", scored["direction"].eq("long")),
        ("direction: short", scored["direction"].eq("short")),
        ("conviction: at/above median", scored["conviction"].ge(scored["conviction"].median())),
        ("conviction: below median", scored["conviction"].lt(scored["conviction"].median())),
        ("reward:risk >= median", scored["reward_risk"].ge(scored["reward_risk"].median())),
        ("reward:risk < median", scored["reward_risk"].lt(scored["reward_risk"].median())),
        ("stop >= median", scored["stop_distance"].ge(scored["stop_distance"].median())),
        ("stop < median", scored["stop_distance"].lt(scored["stop_distance"].median())),
    ]:
        cell = scored.loc[mask]
        if len(cell) >= 8:
            splits[name] = report(name, cell["take_r"], cell["session"])

    out = {"stage": "H058_STAGE2_FINAL_STOPPED_EARLY", "outcome_accessed": True,
           "takes": int(len(scored)), "paired": int(len(paired)),
           "primary": primary, "secondary_tradability": tradability,
           "control": control, "execution": execution, "splits": splits,
           "outcome_mix": scored["outcome"].value_counts().to_dict()}
    (config.METADATA_DIR / "research_store" / "price_action"
     / "h058_stage2_final.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    print("\nwritten to h058_stage2_final.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
