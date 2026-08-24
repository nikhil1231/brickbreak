"""CLI handlers for the AI Research Council and Data Broker (PLAN.md Stage AB)."""
from __future__ import annotations

import argparse
import hashlib
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
from ...contracts.compiler import (
    compile_batch,
    load_qualification,
    save_contract,
)
from ...core import config
from ...council import (
    HOSTILE_REVIEW_SYSTEM_PROMPT,
    SCOUT_SYSTEM_PROMPT,
    ScoutLens,
    adjudicate_dossier,
    build_hostile_review_prompt,
    build_scout_prompt,
    parse_dossier_json,
    parse_hostile_review,
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
from ...providers import (
    ProviderError,
    ProviderRole,
    ProviderType,
    SubscriptionPool,
    route_council_call,
)

logger = logging.getLogger(__name__)


def cmd_discover(args: argparse.Namespace) -> int:
    """Propose mechanism dossiers across council lenses."""
    lens_str = getattr(args, "lens", "market_structure")
    try:
        lens = ScoutLens(lens_str)
    except ValueError:
        lens = ScoutLens.MARKET_STRUCTURE

    pool = SubscriptionPool()
    from ...persistence import store
    from ...research_data.catalogue import DEFAULT as FEATURE_CATALOGUE

    hypotheses = store.list_hypotheses()
    ledger_context = [
        f"{h.id} [{h.family}/{h.status}] {h.title}: {h.rationale}"
        for h in hypotheses
    ]
    prompt = build_scout_prompt(
        lens=lens,
        domain_hint=getattr(args, "hint", ""),
        catalogue_features=[
            f"{feature.name} ({feature.available_as_of}, "
            f"{'PIT' if feature.point_in_time else 'not-PIT'})"
            for feature in FEATURE_CATALOGUE
        ],
        graveyard_notes=ledger_context,
    )

    try:
        preferred = ProviderType(getattr(args, "provider", "claude"))
        print(f"[*] Dispatching Mechanism Scout under lens {lens.value.upper()}...")
        resp, provider = route_council_call(
            pool,
            role=ProviderRole.SCOUT,
            prompt=prompt,
            system_prompt=SCOUT_SYSTEM_PROMPT,
            model=getattr(args, "model", "") or "",
            preferred_provider=preferred,
        )
        response_id = hashlib.sha256(resp.encode()).hexdigest()[:10].upper()
        dossier = parse_dossier_json(
            resp,
            dossier_id=f"DOS_{lens.value.upper()[:4]}_{response_id}",
            hypothesis_id=(getattr(args, "hypothesis", None)
                           or f"PROP_{response_id}"),
            family=getattr(args, "family", "general"),
            proposer=(f"{provider.value}:scout_{lens.value};model="
                      f"{getattr(args, 'model', None) or 'cli-default'}"),
        )
        output_arg = getattr(args, "output", None)
        out_path = (Path(output_arg) if output_arg else
                    config.METADATA_DIR / "research_store" / "dossiers" /
                    f"{dossier.dossier_id}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(dossier.to_dict(), indent=2) + "\n")
        print("\n=== MECHANISM DOSSIER ===")
        print(f"ID: {dossier.dossier_id} (Hash: {dossier.dossier_hash})")
        print(f"Claim: {dossier.claim}")
        print(f"Causal Chain: {dossier.causal_chain}")
        print(f"Counterparty: {dossier.counterparty} ({dossier.counterparty_persistence_rationale})")
        print(f"Competing Explanations: {dossier.competing_explanations}")
        print(f"Min Effect: {dossier.min_effect_bps} bps (Baseline: {dossier.strongest_baseline})")
        print(f"Data Gap: {dossier.has_data_gap}")
        print(f"Saved: {out_path}")
        return 0
    except ProviderError as exc:
        print(f"[-] Provider failed without fallback: {exc}")
        return 1
    except Exception as exc:
        if "resp" in locals():
            print(f"[-] Scout response: {resp}")
        print(f"[-] Failed to parse dossier: {exc}")
        return 1


def cmd_attack(args: argparse.Namespace) -> int:
    """Run an independent model critic plus deterministic safety critics."""
    dossier_path = Path(args.dossier_file)
    if not dossier_path.exists():
        print(f"[-] Dossier file {dossier_path} not found")
        return 1

    dossier_dict = json.loads(dossier_path.read_text())
    dossier = MechanismDossier.from_dict(dossier_dict)

    print(f"[*] Attacking dossier {dossier.dossier_id} across council critics...")
    extra_reviews = ()
    reviewer_provider = None
    # Direct Python callers from the pre-director interface do not carry the
    # new provider fields.  Keep those deterministic; the public CLI always
    # carries an explicit provider/auto choice and therefore performs the
    # independent review unless --deterministic-only is stated.
    deterministic_only = getattr(
        args, "deterministic_only", not hasattr(args, "provider"))
    if not deterministic_only:
        proposer_provider = None
        proposer_name = dossier.proposer.split(":", 1)[0]
        try:
            proposer_provider = ProviderType(proposer_name)
        except ValueError:
            pass
        preferred_arg = getattr(args, "provider", "auto")
        preferred = None if preferred_arg == "auto" else ProviderType(preferred_arg)
        try:
            response, reviewer_provider = route_council_call(
                SubscriptionPool(),
                role=ProviderRole.CRITIC,
                prompt=build_hostile_review_prompt(dossier),
                system_prompt=HOSTILE_REVIEW_SYSTEM_PROMPT,
                model=getattr(args, "model", "") or "",
                preferred_provider=preferred,
                proposer_provider=proposer_provider,
            )
            extra_reviews = (parse_hostile_review(
                response, provider=reviewer_provider.value,
                model=getattr(args, "model", "") or ""),)
        except (ProviderError, ValueError) as exc:
            print(f"[-] Independent hostile review failed without fallback: {exc}")
            return 1
    adj = adjudicate_dossier(dossier, additional_reviews=extra_reviews)

    print(f"\nVerdict: {adj.verdict}")
    print(f"Approved: {adj.approved} (Priority Score: {adj.priority_score:.2f})")
    print(f"Novelty: {adj.novelty.verdict} (Nearest: {adj.novelty.nearest_hypothesis_id})")
    print(f"Dissents recorded: {len(adj.all_dissents)}")
    for d in adj.all_dissents:
        print(f"  - [{d.severity.upper()}] {d.reviewer_role}: {d.objection}")

    output_arg = getattr(args, "output", None)
    out_path = (Path(output_arg) if output_arg else
                dossier_path.with_name(f"{dossier.dossier_id}_adjudicated.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(adj.to_dict(), indent=2) + "\n")
    print(f"[+] Saved adjudication to {out_path}")

    return 0 if adj.approved else 2


def cmd_qualify(args: argparse.Namespace) -> int:
    """Author and freeze a signal after label-free structural checks."""
    from ...runner.qualification import qualify_adjudication

    adjudication_path = Path(args.adjudication_file)
    if not adjudication_path.exists():
        print(f"[-] Adjudication file {adjudication_path} not found")
        return 1
    try:
        adjudication = json.loads(adjudication_path.read_text())
        supplied_source = (Path(args.signal_file).read_text()
                           if getattr(args, "signal_file", None) else None)
        supplied_baseline = (Path(args.baseline_file).read_text()
                             if getattr(args, "baseline_file", None) else None)
        supplied_eligibility = (Path(args.eligibility_file).read_text()
                                if getattr(args, "eligibility_file", None) else None)
        artifact, path = qualify_adjudication(
            adjudication,
            signal_name=args.signal,
            provider=args.provider,
            model=args.model,
            signal_source=supplied_source,
            baseline_source=supplied_baseline,
            baseline_name=getattr(args, "baseline_name", None),
            eligibility_source=supplied_eligibility,
            eligibility_name=getattr(args, "eligibility_name", None),
            signal_kind=getattr(args, "signal_kind", None),
            dataset_version=args.dataset_version,
            timeout_s=args.timeout,
            max_turns=args.max_turns,
            output_path=Path(args.output) if args.output else None,
        )
    except Exception as exc:
        print(f"[-] Qualification failed: {type(exc).__name__}: {exc}")
        return 1

    verdict = "PASSED" if artifact.approved else "REJECTED"
    print(f"\n=== QUALIFICATION {verdict} ===")
    print(f"ID: {artifact.qualification_id} (Hash: {artifact.qualification_hash})")
    print(f"Hypothesis: {artifact.mechanism_dossier.hypothesis_id}")
    print(f"Signal: {artifact.signal_name} ({artifact.signal_source_hash})")
    print(f"Independent blocks: {artifact.structural_gate['estimated_independent_blocks']}")
    print(f"MDE: {artifact.structural_gate['min_detectable_effect_bps']} bps")
    for reason in artifact.rejection_reasons:
        print(f"  - {reason}")
    print(f"Saved: {path}")
    return 0 if artifact.approved else 2


def cmd_compile(args: argparse.Namespace) -> int:
    """Compile a passed qualification into a frozen one-shot contract."""
    try:
        qualification_args = (args.qualification if isinstance(args.qualification, list)
                              else [args.qualification])
        qualifications = [load_qualification(value) for value in qualification_args]
        contracts, lifecycles, batch = compile_batch(
            qualifications,
            reviewer=args.reviewer,
            cost_round_trip_bps=args.cost_bps,
            capacity_limit_inr=args.capacity_inr,
            min_significance_t=args.min_t,
        )
        canonical_paths = [
            save_contract(contract, lifecycle)
            for contract, lifecycle in zip(contracts, lifecycles)
        ]
        if args.output and len(contracts) != 1:
            raise ValueError("--output is only valid for a one-member batch")
        paths = canonical_paths
        if args.output:
            paths = [save_contract(contracts[0], lifecycles[0], Path(args.output))]
    except Exception as exc:
        print(f"[-] Compile failed: {type(exc).__name__}: {exc}")
        return 1
    print("\n=== EXPERIMENT CONTRACT FROZEN ===")
    print(f"Members: {len(contracts)}")
    print(f"Batch: {batch.batch_id} (Hash: {batch.batch_hash})")
    for contract, path in zip(contracts, paths):
        print(f"  {contract.contract_id} ({contract.contract_hash}) -> {path}")
        print(f"    run: python -m src.cli execute {contract.contract_id} "
              "--confirm-outcome-access")
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    """Spend one registered outcome access on a frozen contract."""
    if not args.confirm_outcome_access:
        print("[-] Refusing to reveal outcomes without --confirm-outcome-access")
        return 2
    from ...runner.director import execute_contract
    try:
        payload, path = execute_contract(
            args.contract, enroll_forward=args.enroll_forward)
    except Exception as exc:
        print(f"[-] Contract execution failed: {type(exc).__name__}: {exc}")
        return 1
    result = payload["result"]
    print("\n=== REGISTERED RESULT ===")
    print(f"Contract: {payload['contract_id']}")
    print(f"Verdict: {result['failure_class']}")
    print(result["interpretation"])
    print(f"Manifest: {result['manifest']['hash']}")
    print(f"Saved: {path}")
    return 0


def cmd_data_probe(args: argparse.Namespace) -> int:
    """Run generic micro-probe on a raw data file."""
    from ...research_data.frame import load_raw_file_slice
    p = Path(args.file)
    if not p.exists():
        print(f"[-] File {p} not found")
        return 1

    try:
        df = load_raw_file_slice(p, nrows=args.sample_size or 500)
    except Exception as exc:
        print(f"[-] Failed to load {p}: {exc}")
        return 1

    probe = run_source_micro_probe(
        source_name=args.source_name or p.stem,
        sample_df=df,
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
