"""CLI handlers for the research suite (the refactor plan §7).

Subcommands:
- `catalogue`: Browse features in the catalogue
- `hypotheses`: Browse the hypothesis ledger (H001–H038)
- `ledger`: View sample budget and burned holdouts
- `suggest`: Read or regenerate the research inbox
- `explore`: Launch an automated exploration
- `compare`: Compare 2–10 signals
- `serve`: Launch the primary backend and web application
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...persistence import migration, store
from ...persistence.ledger import SampleBudgetLedger
from ...research_data import catalogue, frame
from ...runner import agent, compare, job, spec
from .. import backend


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
    """Generate a signal with the selected provider, then evaluate it."""
    exp_spec = spec.ExperimentSpec(
        hypothesis_id=args.hypothesis,
        question=args.question or f"Exploration for {args.hypothesis}",
        signal_name=args.signal or "custom_composite_rs",
        partition=args.partition,
        role=args.role,
    )

    provider = agent.validate_provider(getattr(args, "provider", "claude"))
    if not agent.available(provider=provider):
        print(agent.install_hint(provider), file=sys.stderr)
        return 2
    model = getattr(args, "model", None)
    print(f"\nLaunching Exploration for {args.hypothesis} on {args.partition} "
          f"with {provider}/{model or 'cli-default'}...")
    jb = job.run_job(exp_spec, provider=provider, model=model)
    if jb.state != "succeeded":
        print(jb.error or f"job ended in state {jb.state}", file=sys.stderr)
        return 1
    res = json.loads(Path(jb.result_path).read_text())

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
    """Launch the primary backend and web application."""
    backend.serve_backend(port=args.port, block=True)
    return 0


def cmd_plan(args) -> int:
    """Turn a typed idea into an amendable experiment plan."""
    from ...research_data import frame
    from ...runner import planner

    cols = None
    if args.with_columns:
        cols = list(frame.load_daily_panel(partition="train").columns)
    plan = planner.propose(args.idea, columns=cols, provider=args.provider,
                           model=args.model)

    print(f"question   {plan.question}")
    print(f"hypothesis {plan.hypothesis_id}   family {plan.family}")
    if plan.rationale:
        print(f"rationale  {plan.rationale}")
    if plan.what_it_measures:
        print(f"measures   {plan.what_it_measures}")
    if plan.signal_sketch:
        print(f"signal     {plan.signal_name}: {plan.signal_sketch}")
    if plan.lineage:
        print("lineage    " + ", ".join(
            f"{e.get('relation')} -> {e.get('target_id')}" for e in plan.lineage))
    print(f"bar        {plan.pass_criterion}")
    print(f"falsified  {plan.falsification_condition}")
    for w in plan.warnings:
        print(f"WARNING    {w}")
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
    return 0


def _print_suggestion(sug) -> None:
    print(f"\n{sug.id}  [slot {sug.slot}]  {sug.title}")
    print(f"  question   {sug.question}")
    if sug.rationale:
        print(f"  mechanism  {sug.rationale}")
    if sug.signal_sketch:
        print(f"  signal     {sug.signal_name}: {sug.signal_sketch}")
    else:
        print(f"  signal     {sug.signal_name}")
    if sug.lineage:
        print("  lineage    " + ", ".join(
            f"{e['relation']} -> {e['target_id']}" for e in sug.lineage))
    if sug.evidence_basis:
        print(f"  because    {sug.evidence_basis}")
    if sug.novelty_note:
        print(f"  novelty    {sug.novelty_note}")
    if sug.expected_correlation:
        print(f"  overlaps   {sug.expected_correlation}")
    print(f"  bar        {sug.pass_criterion}")
    if sug.falsification_condition:
        print(f"  falsified  {sug.falsification_condition}")
    print(f"  source     {sug.source}"
          + (f"/{sug.model}" if sug.model else ""))
    for w in sug.warnings:
        print(f"  WARNING    {w}")


def cmd_suggest(args) -> int:
    """Read the research inbox, or ask for new proposals.

    Reading is free and does not call a model; `--new` and `--refresh` are the
    only paths that spend one.
    """
    from ...runner import suggest as suggest_mod

    if getattr(args, "refresh", None):
        try:
            sug = suggest_mod.refresh(args.refresh, provider=args.provider,
                                      model=args.model)
        except (KeyError, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 1
        _print_suggestion(sug)
        return 0

    if getattr(args, "new", False):
        # The inbox is a fixed set of slots, not a growing pile: `--new`
        # refills them. Anything it displaces is kept as `replaced`, so a
        # regenerated inbox still cannot propose what it just discarded.
        suggest_mod.generate(args.n, slots=list(range(args.n)),
                             provider=args.provider, model=args.model)

    inbox = suggest_mod.open_suggestions()
    if not inbox:
        print("the research inbox is empty. `--new` asks for proposals.")
        return 0
    if args.json:
        print(json.dumps([s.to_dict() for s in inbox], indent=2))
        return 0
    print(f"\nResearch inbox ({len(inbox)} open):")
    for sug in inbox:
        _print_suggestion(sug)
    print()
    return 0



def cmd_job(args) -> int:
    """Dispatch one research job to an LLM worker in its own worktree."""
    from ...runner import agent, job as job_mod
    from ...runner.spec import ExperimentSpec

    try:
        provider = agent.validate_provider(args.provider)
    except agent.AgentError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not agent.available(provider=provider):
        print(agent.install_hint(provider), file=sys.stderr)
        return 2

    spec = ExperimentSpec(
        hypothesis_id=args.hypothesis, question=args.question,
        signal_name=args.signal, partition=args.partition, role=args.role,
        primary_horizon=args.horizon)
    jb = job_mod.run_job(spec, timeout_s=args.timeout, max_turns=args.max_turns,
                         provider=provider, model=args.model,
                         keep_worktree=args.keep_worktree)
    print(f"{jb.id}  {jb.state}  {jb.runtime_s}s  provider={jb.provider}"
          f"  model={jb.model or 'cli-default'}  turns={jb.agent_turns}"
          + (f"  ${jb.agent_cost_usd:.3f}" if jb.agent_cost_usd else ""))
    if jb.error:
        print(jb.error, file=sys.stderr)
        return 1
    result = json.loads(Path(jb.result_path).read_text())
    print(f"\n{result['failure_class']}\n\n{result['interpretation']}")
    m = result.get("multiplicity") or {}
    if m:
        print(f"\nmultiplicity: {m.get('note')}")
    return 0


def cmd_jobs(args) -> int:
    from ...runner import job as job_mod
    jobs = job_mod.list_jobs()
    if not jobs:
        print("no jobs yet")
        return 0
    print(f"{'job':<22} {'state':<10} {'runtime':>8}  hypothesis  signal")
    for j in jobs[:args.limit]:
        print(f"{j.id:<22} {j.state:<10} {j.runtime_s:>7}s  "
              f"{j.spec.get('hypothesis_id',''):<10}  {j.spec.get('signal_name','')}")
    return 0


def cmd_forward(args) -> int:
    """Status of the chronological forward lane, and accrual into it."""
    from ...runner import forward
    st = forward.status()
    print(f"forward lane: {st['n_sessions']} sessions from {st['start']}, "
          f"{st['n_registered']} signal(s) registered")
    print(st["note"])
    if args.accrue:
        out = forward.accrue()
        print(f"\naccrued {out['accrued']} result(s)")
        for r in out.get("results", []):
            print("  ", r)
    return 0


def cmd_burden(args) -> int:
    """How many questions this partition has already been asked, or batch multiplicity assessment."""
    from ...runner import burden

    if getattr(args, "batch", None):
        try:
            b_res = burden.assess_batch(args.batch, q=args.fdr)
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if getattr(args, "json", False):
            print(json.dumps(b_res, indent=2))
            return 0

        print(f"\nBatch Multiplicity Assessment: {b_res['batch_id']} on {b_res['partition']}")
        print(f"  Batch Size:     {b_res['batch_size']}")
        print(f"  Batch Hash:     {b_res['batch_hash']}")
        print(f"  Batch Šidák:    |t| >= {b_res['batch_sidak_bar']}")
        print(f"  Surviving FDR:  {b_res['n_surviving_fdr']} at q={b_res['fdr_q']}\n")
        print(f"{'Hypothesis':<12} {'Signal':<24} {'t-stat':<10} {'p-val':<10} {'FDR':<8} {'Šidák'}")
        print("-" * 75)
        for r in b_res["results"]:
            t_str = f"{r['t_stat']:+.2f}" if r['t_stat'] is not None else "N/A"
            p_str = f"{r['p_value']:.4f}" if r['p_value'] is not None else "N/A"
            fdr_str = "KEEP" if r.get("survives_fdr") else "-"
            sidak_str = "PASS" if r.get("clears_batch_sidak") else "-"
            print(f"{r['hypothesis_id']:<12} {str(r['signal']):<24} {t_str:<10} {p_str:<10} {fdr_str:<8} {sidak_str}")
        print()
        return 0

    s = burden.partition_summary(args.partition, q=args.fdr)
    if getattr(args, "json", False):
        print(json.dumps(s, indent=2))
        return 0

    print(f"{args.partition}: {s['n_tests']} recorded test(s); "
          f"a maximum over that many needs |t| > {s['sidak_bar']}")
    print(f"surviving BH at q={s['fdr_q']}: {s['n_surviving_fdr']}")
    for r in s["results"][:args.limit]:
        mark = "keep" if r.get("survives_fdr") else "   -"
        print(f"  {mark}  {r['hypothesis_id']:<8} {str(r['signal']):<24} "
              f"t={r['t_stat']}")
    return 0



def cmd_preflight(args: argparse.Namespace) -> int:
    """Run label-free pre-flight screening on a signal."""
    from ...runner import preflight, spec as spec_mod
    from ...runner.burden import count_tests

    partition = getattr(args, "partition", "train")
    signal_name = args.signal
    hypo_id = getattr(args, "hypothesis", None) or "H_PREFLIGHT"

    prior_count = count_tests(partition)

    # Load panel strictly WITHOUT forward labels
    df = frame.load_daily_panel(partition=partition, asof_open=True, include_context=True)

    exp_spec = spec_mod.ExperimentSpec(
        hypothesis_id=hypo_id,
        question=f"Pre-flight check for {signal_name}",
        signal_name=signal_name,
        partition=partition,
    )

    res = preflight.run_preflight(df, signal_name, spec=exp_spec, save_results=True)

    if getattr(args, "json", False):
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.passed else 1

    verdict_str = "PASSED" if res.passed else f"REJECTED ({res.failure_class})"
    print(f"\nPre-flight Screening: {signal_name} on {partition} -> {verdict_str}\n")
    if res.mechanics:
        print("Signal Mechanics:")
        print(f"  Turnover:           {res.mechanics.get('mean_turnover', 'N/A')}")
        print(f"  1d Autocorrelation: {res.mechanics.get('autocorrelation_1d', 'N/A')}")
        print(f"  5d Autocorrelation: {res.mechanics.get('autocorrelation_5d', 'N/A')}")
        print(f"  Mean Coverage:      {res.mechanics.get('mean_coverage_names', 'N/A')} names")
    if res.factor_correlations:
        print("\nFactor Correlations:")
        for factor, corr in res.factor_correlations.items():
            print(f"  {factor:<12}: {corr:+.3f}")
    if res.reasons:
        print("\nRejection Reasons:")
        for r in res.reasons:
            print(f"  - {r}")

    after_count = count_tests(partition)
    print(f"\nMultiplicity Count Check: {prior_count} prior -> {after_count} after (budget spent: {after_count - prior_count})")
    print()
    return 0 if res.passed else 1


def cmd_gate(args: argparse.Namespace) -> int:
    """View dispatch rate limit status and budget allowance."""
    from ...runner import gate

    if getattr(args, "partition", None):
        allowed, recent, max_allowed, reason = gate.check_dispatch_allowance(args.partition)
        if getattr(args, "json", False):
            print(json.dumps({
                "partition": args.partition,
                "allowed": allowed,
                "dispatches_in_period": recent,
                "max_dispatches": max_allowed,
                "reason": reason,
            }, indent=2))
            return 0
        print(f"\nDispatch Gate — {args.partition}:")
        print(f"  {reason}\n")
        return 0

    st = gate.gate_status()
    if getattr(args, "json", False):
        print(json.dumps(st, indent=2))
        return 0

    print(f"\nDispatch Gate Status (7-Day Rolling Windows):\n")
    print(f"{'Partition':<14} {'Used':<8} {'Limit':<8} {'Allowed':<10} {'Details'}")
    print("-" * 75)
    for part, info in st.items():
        lim_str = str(info['max_dispatches']) if info['max_dispatches'] is not None else "unlimited"
        allow_str = "YES" if info['allowed'] else "NO"
        print(f"{part:<14} {info['dispatches_in_period']:<8} {lim_str:<8} {allow_str:<10} {info['status_text']}")
    print()
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    """Browse or rank candidates in the deep research queue."""
    from ...runner import queue

    if getattr(args, "rank", False):
        proposals = queue.rank_queue()
    else:
        proposals = queue.list_queue(status=getattr(args, "status", None))

    if getattr(args, "json", False):
        print(json.dumps([p.to_dict() for p in proposals], indent=2))
        return 0

    print(f"\nDeep Candidate Queue ({len(proposals)} proposals):\n")
    print(f"{'ID':<6} {'Status':<16} {'Score':<8} {'Hypothesis':<12} {'Signal':<22} {'Title'}")
    print("-" * 80)
    for p in proposals:
        title = p.title[:25] + "..." if len(p.title) > 28 else p.title
        print(f"{p.id:<6} {p.status:<16} {p.priority_score:<8.1f} {p.hypothesis_id:<12} {p.signal_name:<22} {title}")
    print()
    return 0


def cmd_preregister(args: argparse.Namespace) -> int:
    """Pre-register and freeze a batch of candidate proposals."""
    from ...runner import preregistration

    p_ids = [p.strip() for p in args.proposals.split(",") if p.strip()]
    if not p_ids:
        print("No proposal IDs provided.", file=sys.stderr)
        return 1

    try:
        batch = preregistration.preregister_batch(p_ids, partition=args.partition)
    except Exception as exc:
        print(f"Error pre-registering batch: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(batch.to_dict(), indent=2))
        return 0

    print(f"\nBatch Pre-Registered Successfully!")
    print(f"  Batch ID:   {batch.batch_id}")
    print(f"  Partition:  {batch.partition}")
    print(f"  Candidates: {len(batch.proposal_ids)} ({', '.join(batch.proposal_ids)})")
    print(f"  Batch Hash: {batch.batch_hash}")
    print(f"  Status:     {batch.status}\n")
    return 0


