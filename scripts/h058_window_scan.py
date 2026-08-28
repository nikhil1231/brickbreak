#!/usr/bin/env python
"""EXPLORATORY. Entry-window scan on an already-spent partition.

This is not confirmatory and cannot become confirmatory. The window is being
chosen with knowledge of an outcome read on this same data, so the best cell is
a fitted number by construction. Two things keep it honest:

  * the whole surface is reported, never the maximum alone -- a real effect is
    broadly positive across neighbouring windows, noise spikes in one cell;
  * the maximum is judged against the permuted maximum of the same scan, as
    PLAN.md 11 requires, because the expected best-of-eight under no edge is
    comfortably positive and quoting it naked would be dishonest.

Only the entry window varies. The hold stays at the registered 15 sessions, so
this is a one-dimensional scan of eight cells rather than a grid.
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

WINDOWS = (3, 5, 8, 10, 15, 20, 25, 30)
CONFIRMATORY_ORIGINALS = 733
PERMUTATIONS = 4000
SEED = 20260829


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
    keep = set(originals[:CONFIRMATORY_ORIGINALS])
    marks["slot"] = marks["case_id"].map(
        lambda c: private[c]["slot_private"] if c in private else -1)
    marks = marks.loc[marks["slot"].isin(keep)]

    paths, adjustments = resolve._paths(
        private, fo_universe.load(), corporate_actions.load_adjusted())
    pairs = resolve.build_pairs(marks, private)

    surface, per_session = [], {}
    for window in WINDOWS:
        rules = {**setup_grind.EXECUTION_RULES, "entry_window_sessions": window,
                 "horizon_sessions": window + 15}
        rows = []
        for _, pair in pairs.iterrows():
            take = resolve.resolve_case(
                private[pair["take_case_id"]], paths, adjustments,
                pair["entry_atr"], pair["stop_atr"], pair["target_atr"], rules=rules)
            if take is None or "excluded" in take:
                continue
            controls = [g["r"] for cid in pair["control_case_ids"]
                        if (g := resolve.resolve_case(
                            private[cid], paths, adjustments, pair["entry_atr"],
                            pair["stop_atr"], pair["target_atr"], rules=rules))
                        is not None and "excluded" not in g]
            rows.append({"session": pair["session"], "take_r": take["r"],
                         "filled": take["outcome"] not in ("no_fill", "invalidated_at_fill"),
                         "difference_r": take["r"] - float(np.mean(controls))
                         if controls else np.nan})
        frame = pd.DataFrame(rows)
        paired = frame.dropna(subset=["difference_r"])
        session_means = paired.groupby("session")["difference_r"].mean()
        per_session[window] = session_means
        surface.append({
            "window": window,
            "fill_rate": float(frame["filled"].mean()),
            "trades": int(frame["filled"].sum()),
            "take_mean_r": float(frame["take_r"].mean()),
            "difference_r": float(session_means.mean()),
            "sessions": int(len(session_means)),
        })

    table = pd.DataFrame(surface)
    print("\n=== EXPLORATORY ENTRY-WINDOW SCAN (spent partition, fitted by construction) ===\n")
    print(f"{'window':>7} {'fills':>7} {'trades':>7} {'take mean R':>12} {'take-skip R':>12}")
    for _, row in table.iterrows():
        print(f"{row['window']:>7.0f} {row['fill_rate']:>6.1%} {row['trades']:>7.0f} "
              f"{row['take_mean_r']:>+12.3f} {row['difference_r']:>+12.3f}")

    # The scan's own null: flip the sign of every session's mean difference.
    # A session is the independent unit, so the flip is applied per session and
    # shared across windows, which preserves the correlation between cells.
    rng = np.random.default_rng(SEED)
    sessions = sorted(set().union(*(set(s.index) for s in per_session.values())))
    observed_max = float(table["difference_r"].max())
    null_max = np.empty(PERMUTATIONS)
    for i in range(PERMUTATIONS):
        signs = pd.Series(rng.choice([-1.0, 1.0], size=len(sessions)), index=sessions)
        null_max[i] = max(float((series * signs.reindex(series.index)).mean())
                          for series in per_session.values())
    p_value = float((null_max >= observed_max).mean())

    print(f"\nbest cell            {observed_max:+.3f}R at a "
          f"{int(table.loc[table['difference_r'].idxmax(), 'window'])}-session window")
    print(f"permuted max, median {np.median(null_max):+.3f}R   "
          f"95th pct {np.percentile(null_max, 95):+.3f}R")
    print(f"p-value of the best cell against its own scan: {p_value:.3f}")
    print(f"cells positive: {int((table['difference_r'] > 0).sum())} of {len(table)}")

    out = {"stage": "H058_EXPLORATORY_WINDOW_SCAN", "confirmatory": False,
           "outcome_accessed": True, "surface": surface,
           "best_cell_r": observed_max, "permuted_p": p_value,
           "permuted_max_median": float(np.median(null_max)),
           "permuted_max_p95": float(np.percentile(null_max, 95))}
    (config.METADATA_DIR / "research_store" / "price_action"
     / "h058_window_scan.json").write_text(json.dumps(out, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
