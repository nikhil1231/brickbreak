"""CLI handlers for the research suite (PLAN.md §7).

Subcommands:
- `catalogue`: Browse features in the catalogue
- `hypotheses`: Browse the hypothesis ledger (H001–H038)
- `ledger`: View sample budget and burned holdouts
- `explore`: Launch an automated exploration
- `compare`: Compare 2–10 signals
- `serve`: Launch the interactive web dashboard
"""
from __future__ import annotations

import argparse
import json
import sys

from ..persistence import migration, store
from ..persistence.ledger import SampleBudgetLedger
from ..research_data import catalogue, frame
from ..runner import compare, runner, spec
from . import app


def cmd_catalogue(args: argparse.Namespace) -> int:
    """Print the feature catalogue with PIT status and scoring guards."""
    cat = catalogue.DEFAULT
    print(f"\nFeature Catalogue ({len(cat)} registered features):\n")
    print(f"{'Feature Name':<30} {'Owner':<12} {'As-Of':<12} {'Lookback':<9} {'PIT':<6} {'Scorable':<8}")
    print("-" * 80)
    for f in cat.all_features():
        if getattr(args, "owner", None) and f.owner != args.owner:
            continue
        scorable = "YES" if cat.scorable(f.name) else "NO"
        pit = "YES" if f.point_in_time else "NO"
        print(f"{f.name:<30} {f.owner:<12} {f.available_as_of:<12} {f.lookback:<9} {pit:<6} {scorable:<8}")
    print("\n" + cat.summary() + "\n")
    return 0


def cmd_hypotheses(args: argparse.Namespace) -> int:
    """Browse stored hypotheses or show one in detail."""
    if getattr(args, "id", None):
        h = store.get_hypothesis(args.id)
        if not h:
            print(f"Hypothesis {args.id} not found.", file=sys.stderr)
            return 1
        print(f"\n=== {h.id} — {h.title} ===")
        print(f"Family: {h.family} | Status: {h.status}")
        print(f"\nStatement:\n  {h.statement}\n")
        print(f"Rationale:\n  {h.rationale}\n")
        if h.edges:
            print("Lineage / Connected Edges:")
            for e in h.edges:
                print(f"  --[{e.relation}]--> {e.target_id}")
        evs = store.list_evidence(hypothesis_id=h.id)
        if evs:
            print(f"\nRecorded Evidence ({len(evs)} items):")
            for ev in evs:
                print(f"  [{ev.role.upper()} / {ev.partition}] {ev.verdict_statement}")
                print(f"    Metrics: {ev.metrics}")
        print()
        return 0

    hyps = store.list_hypotheses(
        status=getattr(args, "status", None),
        family=getattr(args, "family", None),
    )
    if not hyps:
        hyps, _ = migration.migrate(save_to_store=True)

    print(f"\nResearch Ledger ({len(hyps)} hypotheses):\n")
    print(f"{'ID':<6} {'Family':<16} {'Status':<12} {'Title':<45}")
    print("-" * 80)
    for h in hyps:
        title = h.title[:42] + "..." if len(h.title) > 45 else h.title
        print(f"{h.id:<6} {h.family:<16} {h.status:<12} {title:<45}")
    print()
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    """Display sample budget ledger and consumed quarters."""
    l = SampleBudgetLedger.load()
    print(f"\nSample Budget Ledger ({len(l._entries)} recorded entries):\n")
    print(f"{'Hypothesis':<12} {'Family':<16} {'Role':<14} {'Partition':<10} {'Quarters'}")
    print("-" * 80)
    for e in l._entries[-20:]:  # Last 20 entries
        print(f"{e.hypothesis_id:<12} {e.family:<16} {e.role:<14} {e.partition:<10} {', '.join(e.quarters)}")
    print(f"\nTotal Recorded Partition Reads: {len(l._entries)}\n")
    return 0


def cmd_explore(args: argparse.Namespace) -> int:
    """Launch an automated exploration."""
    exp_spec = spec.ExperimentSpec(
        hypothesis_id=args.hypothesis,
        question=args.question or f"Exploration for {args.hypothesis}",
        signal_name=args.signal or "custom_composite_rs",
        partition=args.partition,
        role=args.role,
    )

    print(f"\nLaunching Exploration for {args.hypothesis} on {args.partition}...")

    def _default_signal(df):
        d = df.copy()
        cols = [c for c in ("rs_60d_vs_mkt", "sector_breadth", "dist_52w_high") if c in d.columns]
        mask = (d["median_tv_20_cr"] >= 5.0) & (~d["is_etf"].astype(bool))
        ranks = [d[mask].groupby("date")[c].rank(pct=True) for c in cols]
        sig = sum(ranks) / len(ranks)
        return sig.where(mask)

    res = runner.run_exploration(exp_spec, _default_signal, save_results=True)

    print(f"\n=======================================================")
    print(f"  Verdict: {res['failure_class']}")
    print(f"  {res['interpretation']}")
    print(f"=======================================================\n")
    print(f"Manifest Hash: {res['manifest']['hash']}")
    print(f"Runtime: {res['runtime_seconds']}s\n")
    return 0


def cmd_compare_signals(args: argparse.Namespace) -> int:
    """Compare 2..10 candidate signals."""
    signal_names = args.signals
    print(f"\nComparing signals: {', '.join(signal_names)} on train partition...")

    panel = frame.load_daily_panel(partition="train", include_context=True)
    panel["fwd_ret_10d_pct"] = frame.forward_return(panel, horizon=10)

    res = compare.compare_signals(panel, signal_names, forward_col="fwd_ret_10d_pct")
    print("\nPairwise Cross-Sectional Rank Correlation:")
    print(json.dumps(res.get("pairwise_rank_correlation", {}), indent=2))
    print("\nPairwise Top-K Pick Overlap %:")
    print(json.dumps(res.get("pairwise_top_k_overlap_pct", {}), indent=2))
    print("\nCombined Ensemble Performance:")
    print(json.dumps(res.get("combined_ensemble", {}), indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Launch the interactive web dashboard."""
    app.serve_dashboard(port=args.port, block=True)
    return 0
