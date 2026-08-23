"""CLI handlers for the AI Research Council and Data Broker (PLAN.md Stage AB)."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from ...contracts import (
    DataContract,
    ExperimentContract,
    LifecycleState,
    LifecycleTracker,
    MechanismDossier,
)
from ...council import (
    ScoutLens,
    adjudicate_dossier,
    build_scout_prompt,
    parse_dossier_json,
)
from ...data_broker import (
    create_approval_card,
    run_source_micro_probe,
    synthesize_data_contract,
)
from ...firewall import (
    ExposureLevel,
    evaluate_shape_gate,
    evaluate_structural_gate,
    load_exposure_log,
)
from ...providers import ProviderRole, ProviderType, SubscriptionPool, route_council_call

logger = logging.getLogger(__name__)


def cmd_discover(args: argparse.Namespace) -> int:
    """Propose mechanism dossiers across council lenses."""
    lens_str = getattr(args, "lens", "market_structure")
    try:
        lens = ScoutLens(lens_str)
    except ValueError:
        lens = ScoutLens.MARKET_STRUCTURE

    pool = SubscriptionPool()
    prompt = build_scout_prompt(lens=lens, domain_hint=getattr(args, "hint", ""))

    print(f"[*] Dispatching Mechanism Scout under lens {lens.value.upper()}...")
    resp, provider = route_council_call(
        pool,
        role=ProviderRole.SCOUT,
        prompt=prompt,
        system_prompt="Propose MechanismDossier JSON",
        preferred_provider=ProviderType.CLAUDE,
    )

    try:
        dossier = parse_dossier_json(
            resp,
            dossier_id=f"DOS_{lens.value.upper()[:4]}_{hash(resp)%10000:04d}",
            hypothesis_id=getattr(args, "hypothesis", "H_PROP"),
            family=getattr(args, "family", "general"),
            proposer=f"scout_{lens.value}",
        )
        print("\n=== MECHANISM DOSSIER ===")
        print(f"ID: {dossier.dossier_id} (Hash: {dossier.dossier_hash})")
        print(f"Claim: {dossier.claim}")
        print(f"Causal Chain: {dossier.causal_chain}")
        print(f"Counterparty: {dossier.counterparty} ({dossier.counterparty_persistence_rationale})")
        print(f"Competing Explanations: {dossier.competing_explanations}")
        print(f"Min Effect: {dossier.min_effect_bps} bps (Baseline: {dossier.strongest_baseline})")
        print(f"Data Gap: {dossier.has_data_gap}")
        return 0
    except Exception as exc:
        print(f"[-] Scout response: {resp}")
        print(f"[-] Failed to parse dossier: {exc}")
        return 1


def cmd_attack(args: argparse.Namespace) -> int:
    """Run council critics (economic, leakage, power) and adjudicate a dossier."""
    dossier_path = Path(args.dossier_file)
    if not dossier_path.exists():
        print(f"[-] Dossier file {dossier_path} not found")
        return 1

    dossier_dict = json.loads(dossier_path.read_text())
    dossier = MechanismDossier.from_dict(dossier_dict)

    print(f"[*] Attacking dossier {dossier.dossier_id} across council critics...")
    adj = adjudicate_dossier(dossier)

    print(f"\nVerdict: {adj.verdict}")
    print(f"Approved: {adj.approved} (Priority Score: {adj.priority_score:.2f})")
    print(f"Novelty: {adj.novelty.verdict} (Nearest: {adj.novelty.nearest_hypothesis_id})")
    print(f"Dissents recorded: {len(adj.all_dissents)}")
    for d in adj.all_dissents:
        print(f"  - [{d.severity.upper()}] {d.reviewer_role}: {d.objection}")

    if args.save:
        out_path = dossier_path.with_name(f"{dossier.dossier_id}_adjudicated.json")
        out_path.write_text(json.dumps(adj.to_dict(), indent=2) + "\n")
        print(f"[+] Saved adjudication to {out_path}")

    return 0 if adj.approved else 2


def cmd_data_probe(args: argparse.Namespace) -> int:
    """Run generic micro-probe on a raw data file."""
    import pandas as pd
    p = Path(args.file)
    if not p.exists():
        print(f"[-] File {p} not found")
        return 1

    if p.suffix == ".parquet":
        df = pd.read_parquet(p)
    elif p.suffix == ".csv":
        df = pd.read_csv(p)
    else:
        print(f"[-] Unsupported file format {p.suffix}")
        return 1

    probe = run_source_micro_probe(
        source_name=args.source_name or p.stem,
        sample_df=df.head(args.sample_size or 500),
        date_col=args.date_col or "date",
    )

    print(f"=== MICRO-PROBE: {probe.source_name} ===")
    print(f"Passed: {probe.passed} (Rows: {probe.n_sample_rows})")
    print(f"Dates: {probe.usable_start_date} -> {probe.usable_end_date}")
    print(f"Join Rate: {probe.join_rate_pct}%")
    print(f"Silent Cap Detected: {probe.silent_cap_detected}")
    print(f"Timestamp Fidelity: {probe.timestamp_fidelity}")
    for c in probe.checks:
        status = "PASS" if c.passed else "FAIL"
        print(f"  [{status}] {c.name}: {c.details}")

    return 0 if probe.passed else 1


def cmd_exposure_status(args: argparse.Namespace) -> int:
    """Print the outcome exposure log and weekly quota status."""
    entries = load_exposure_log()
    from ...firewall.exposure import check_weekly_exposure_limit, WEEKLY_OUTCOME_ACCESS_CEILING

    count, can_proceed = check_weekly_exposure_limit(entries)
    print("=== RESEARCH EXPOSURE LEDGER ===")
    print(f"Weekly outcome exposure count: {count} / {WEEKLY_OUTCOME_ACCESS_CEILING}")
    print(f"Outcome access permitted: {can_proceed}")
    print(f"Total historical exposure records: {len(entries)}")
    for e in entries[-10:]:
        print(f"  [{e.exposure_level.value}] {e.timestamp} | {e.hypothesis_id} ({e.family}) -> {e.partition} by {e.actor}")
    return 0
