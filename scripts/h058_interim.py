#!/usr/bin/env python
"""Run the registered H058 futility criteria. Prints two words.

Rewritten 2026-08-29. The 2026-08-28 verdicts are void: they were computed with
a resolver that booked profitable stop-outs and exited gaps at the stop rather
than the open. See amendments.json.

What changed here, all registered before this ran:
  * the confirmatory population is the first 733 originals in frozen deck order,
    which is what Stage 0's gate actually opened;
  * execution is a roll-free continuous futures path, not the cash tape;
  * each take is compared against *every* same-session skip, not one draw;
  * tradability is read over all takes, not only pairable ones.

The estimates are written to a sealed file and are NOT printed. A number that
reaches the terminal has reached both the reviewer and the assistant.
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
from src.research.families import setup_grind_outcome as resolve  # noqa: E402

CONFIRMATORY_ORIGINALS = 733
SELECTION_THRESHOLD = 0.00
TRADABILITY_THRESHOLD = 0.00


def main() -> int:
    bundle = (config.METADATA_DIR / "research_store" / "price_action" / "h058_stage2")
    private = {r["case_id"]: r for r in
               (json.loads(l) for l in
                (bundle / "cases_private.jsonl").read_text().splitlines() if l.strip())
               if r.get("case_status") == "ready"}
    draft = json.loads((bundle / "human_drafts" / "owner.json").read_text())
    marks = pd.DataFrame([{"case_id": k, **v["values"]}
                          for k, v in draft["annotations"].items()])
    for column in ("entry_atr", "stop_atr", "target_atr", "conviction"):
        marks[column] = pd.to_numeric(marks[column], errors="coerce")

    # Stage 0's gate opened the 733-chart study. Deck order is randomised, so
    # its first 733 originals are a valid random subsample; anything past them
    # is exploratory and cannot promote the bar.
    originals = sorted((r["slot_private"] for r in private.values()
                        if not r.get("is_repeat_private")))
    confirmatory = set(originals[:CONFIRMATORY_ORIGINALS])
    marks["slot"] = marks["case_id"].map(lambda c: private[c]["slot_private"]
                                         if c in private else -1)
    marks = marks.loc[marks["slot"].isin(confirmatory)]

    universe = fo_universe.load()
    cash = corporate_actions.load_adjusted()
    paths, adjustments = resolve._paths(private, universe, cash)

    pairs = resolve.build_pairs(marks, private)
    rows, excluded, unpaired = [], 0, 0
    for _, pair in pairs.iterrows():
        take = resolve.resolve_case(private[pair["take_case_id"]], paths, adjustments,
                                    pair["entry_atr"], pair["stop_atr"], pair["target_atr"])
        if take is None or "excluded" in take:
            excluded += 1
            continue
        controls = []
        for control_id in pair["control_case_ids"]:
            got = resolve.resolve_case(private[control_id], paths, adjustments,
                                       pair["entry_atr"], pair["stop_atr"],
                                       pair["target_atr"])
            if got is not None and "excluded" not in got:
                controls.append(got["r"])
        row = {"session": pair["session"], "take_case_id": pair["take_case_id"],
               "take_r": take["r"], "take_outcome": take["outcome"],
               "n_controls": len(controls),
               "control_r": float(np.mean(controls)) if controls else np.nan}
        row["difference_r"] = row["take_r"] - row["control_r"] if controls else np.nan
        if not controls:
            unpaired += 1
        rows.append(row)
    scored = pd.DataFrame(rows)
    if scored.empty:
        print("INCONCLUSIVE — no take could be resolved")
        return 1

    paired = scored.dropna(subset=["difference_r"])
    selection = ("STOP" if paired["difference_r"].mean() <= SELECTION_THRESHOLD
                 else "CONTINUE")
    tradability = ("STOP" if scored["take_r"].mean() <= TRADABILITY_THRESHOLD
                   else "CONTINUE")

    report = {
        "stage": "H058_STAGE2_FUTILITY_INTERIM_v2",
        "supersedes": "the 2026-08-28 verdicts, voided for resolver defects",
        "outcome_accessed": True,
        "execution": "continuous stock futures, rolls charged",
        "confirmatory_originals": CONFIRMATORY_ORIGINALS,
        "marks_in_confirmatory_set": int(len(marks)),
        "takes_resolved": int(len(scored)),
        "takes_paired": int(len(paired)),
        "takes_without_a_same_session_skip": int(unpaired),
        "excluded_corporate_action_or_no_path": int(excluded),
        "selection_verdict": selection,
        "tradability_verdict": tradability,
        "mean_difference_r": float(paired["difference_r"].mean()),
        "sd_difference_r": float(paired["difference_r"].std()),
        "take_mean_r": float(scored["take_r"].mean()),
        "take_sd_r": float(scored["take_r"].std()),
        "take_outcomes": scored["take_outcome"].value_counts().to_dict(),
        "median_controls_per_take": float(scored["n_controls"].median()),
    }
    destination = (config.METADATA_DIR / "research_store" / "price_action"
                   / "h058_stage2_interim_SEALED.json")
    destination.write_text(json.dumps(report, indent=2) + "\n")

    print(f"  selection   (takes vs matched skips): {selection}")
    print(f"  tradability (takes net of costs)    : {tradability}")
    print(f"\n({len(scored)} takes resolved on futures, {len(paired)} of them paired, "
          f"{excluded} excluded. Estimates sealed, not printed.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
