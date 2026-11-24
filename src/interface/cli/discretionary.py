"""CLI handlers for the discretionary lab — the loop MISSION.md describes.

    opportunity   an idea becomes a frozen definition
    replay        that definition becomes candidates, cases, decisions,
                  outcomes and a report — one phase at a time
    cases         read what the judge was shown
    decisions     read what it decided, and why

The phases are separate commands on purpose. `replay --phase decide` and
`replay --phase reveal` are the two sides of the seal, and a single command
that ran both would make it easy to forget which side of it you were on.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from ...discretionary import baselines, decider, generators, replay

from ...discretionary.opportunity import (OpportunityDef, OpportunityValidationError,
                                          validate)


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def cmd_opportunity(args: argparse.Namespace) -> int:
    """Freeze an idea into an immutable opportunity definition."""
    criterion = {}
    for item in (args.bar or []):
        if "=" not in item:
            return _fail(f"--bar wants KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        try:
            criterion[k.strip()] = float(v)
        except ValueError:
            return _fail(f"--bar value for {k!r} is not a number: {v!r}")

    params = json.loads(args.generator_params) if args.generator_params else {}
    defn = OpportunityDef(
        id=f"RPL_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        hypothesis_id=args.hypothesis, idea=args.idea,
        generator=args.generator, generator_params=params,
        sample_n=args.n, sample_seed=args.seed,
        anonymise=not args.reveal_identity,
        provider=args.provider, model=args.model or "",
        partition=args.partition, role=args.role,
        primary_horizon=args.horizon,
        horizons=tuple(sorted({5, 10, 20, args.horizon})),
        **({"pass_criterion": criterion} if criterion else {}),
    )
    try:
        validate(defn, check_budget=False)
        r = replay.freeze(defn)
    except (OpportunityValidationError, replay.ReplayError) as exc:
        return _fail(str(exc))

    print(f"\nfroze {r.id}")
    print(f"  idea        {defn.idea}")
    print(f"  hypothesis  {defn.hypothesis_id}")
    print(f"  generator   {defn.generator} {defn.generator_params or ''}")
    print(f"  sample      {defn.sample_n} cases, {defn.sample_strategy}, seed {defn.sample_seed}")
    print(f"  judge       {defn.provider} {defn.model or '(default)'}, "
          f"{'anonymised' if defn.anonymise else 'IDENTITY REVEALED'}")
    print(f"  partition   {defn.partition} ({defn.role}), horizon {defn.primary_horizon}")
    print(f"  bar         {defn.pass_criterion}")
    print(f"  baselines   {', '.join(defn.baselines)}")
    print(f"\nnext:  python -m src.cli replay {r.id} --phase generate\n")
    return 0


def _progress(done: int, total: int) -> None:
    print(f"\r  judged {done}/{total}", end="", flush=True)
    if done == total:
        print()


def cmd_replay(args: argparse.Namespace) -> int:
    """Run one phase of a replay, or report where it has got to."""
    if args.replay_id in ("list", "ls"):
        rows = replay.list_replays()
        if not rows:
            print("\nno replays yet. Start one with `opportunity \"<idea>\"`.\n")
            return 0
        print(f"\n{len(rows)} replays:\n")
        print(f"{'ID':<22} {'next phase':<12} {'verdict'}")
        print("-" * 70)
        for r in rows:
            st = r.status()
            verdict = ""
            if r.report_path.exists():
                rep = json.loads(r.report_path.read_text())
                verdict = rep.get("verdict", {}).get("failure_class", "")
            print(f"{r.id:<22} {str(st['next'] or 'done'):<12} {verdict}")
        print()
        return 0

    try:
        r = replay.get(args.replay_id)
    except replay.ReplayError as exc:
        return _fail(str(exc))

    if args.phase in (None, "status"):
        st = r.status()
        print(f"\n{r.id}")
        for phase, ok in st["phases"].items():
            print(f"  [{'x' if ok else ' '}] {phase}")
        print(f"\n  next: {st['next'] or 'nothing — this replay is complete'}\n")
        return 0

    try:
        if args.phase == "generate":
            picked = replay.generate(r.id)
            print(f"\n{r.id}: {len(picked)} candidates sampled over "
                  f"{picked['date'].nunique()} sessions")
            print(f"next:  python -m src.cli replay {r.id} --phase build\n")

        elif args.phase == "build":
            cases = replay.build(r.id)
            size = sum(len(c.render()) for c in cases) // max(len(cases), 1)
            print(f"\n{r.id}: built {len(cases)} cases, ~{size // 4} tokens each")
            print(f"next:  python -m src.cli replay {r.id} --phase decide\n")

        elif args.phase == "decide":
            d = r.definition()
            print(f"\n{r.id}: judging {len(r.cases())} cases with "
                  f"{decider.resolve(d.provider)}...")
            out = replay.decide(r.id, progress=_progress)
            seal = json.loads(r.seal_path.read_text())
            print(f"  committed {len(out)} decisions "
                  f"({seal['n_decisions'] - len(r.cases()) * len(d.baselines)} AI "
                  f"+ {len(d.baselines)} baseline arms)")
            print(f"  AI take rate {seal['ai_take_rate'] * 100:.1f}%")
            f = seal["failures"]
            if f["n_failed"]:
                print(f"  {f['n_failed']} calls failed ({f['failed_pct']}%): "
                      f"{f['by_kind']}")
            print(f"  seal {seal['commit_hash']}")
            print(f"\nnext:  python -m src.cli replay {r.id} --phase reveal\n")

        elif args.phase == "reveal":
            out = replay.reveal(r.id, enforce_budget=not args.no_budget)
            n = int(out["primary_excess_pct"].notna().sum())
            print(f"\n{r.id}: revealed {n} of {len(out)} outcomes")
            print(f"next:  python -m src.cli replay {r.id} --phase evaluate\n")

        elif args.phase == "evaluate":
            rep = replay.evaluate(r.id, record=not args.no_record)
            _print_report(rep)

    except (replay.ReplayError, replay.SealBrokenError) as exc:
        return _fail(str(exc))
    except Exception as exc:                      # noqa: BLE001 — surfaced
        return _fail(f"{type(exc).__name__}: {exc}")
    return 0


def _bps(v) -> str:
    """A missing number is not a zero and must not print as one."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "       —"
    return "       —" if f != f else f"{f:+8.1f}"


def _print_report(rep: dict) -> None:
    hl, v = rep["headline"], rep["verdict"]
    print(f"\n{'=' * 72}")
    print(f"{rep['replay_id']}  —  {rep['idea']}")
    print(f"{'=' * 72}")
    print(f"\n{rep['n_cases']} cases over {rep['n_sessions']} sessions, "
          f"{rep['partition']}, horizon {rep['primary_horizon']}, "
          f"generator {rep['generator']}"
          f"{'' if rep['anonymised'] else '  [IDENTITY REVEALED]'}")

    print(f"\nSELECTION")
    print(f"  take rate            {hl['take_rate_pct']}%  ({hl['n_taken']} taken)")
    print(f"  taken, mean excess  {_bps(hl['taken_mean_excess_bps'])} bps  "
          f"({_bps(hl['taken_net_of_costs_bps']).strip()} after costs)")

    print(f"\nDID SELECTION HELP?   (per-session paired, HAC-corrected)")
    for label, key in (("vs the pool it was given", "excess_lift_bps"),
                       ("vs what it skipped", "take_vs_skip_bps")):
        t = hl[key.replace("_bps", "_t")]
        print(f"  {label:<24} {_bps(hl[key])} bps   t={t if t == t else '—'}")
    if hl.get("best_baseline"):
        t = hl["lift_over_baseline_t"]
        print(f"  vs {hl['best_baseline']:<21} {_bps(hl['lift_over_baseline_bps'])} bps   "
              f"t={t if t == t else '—'}")

    print(f"\nARMS  (identical cases, matched take rate)")
    print(f"  {'arm':<18} {'take%':>7} {'mean excess':>13}")
    print(f"  {'ai':<18} {hl['take_rate_pct']:>7.1f} "
          f"{_bps(hl['taken_mean_excess_bps']):>10} bps")
    for name, b in rep["baselines"].items():
        m = b["taken"].get("mean")
        m = f"{m * 100:>10.1f} bps" if m is not None and m == m else f"{'—':>14}"
        print(f"  {name:<18} {b['take_rate_pct']:>7.1f} {m}")

    cal = rep["calibration"]
    print(f"\nCALIBRATION")
    if "slope_bps_per_unit" in cal:
        print(f"  slope {cal['slope_bps_per_unit']:+.0f} bps per unit of "
              f"confidence, monotone={cal['monotone']}")
        for b in cal["buckets"]:
            print(f"    {b['bucket']:<12} n={b['n']:<5} {b['mean_excess_bps']:+.0f} bps")
    else:
        print(f"  {cal.get('note', 'not measured')}")

    if rep.get("by_tag"):
        print(f"\nREASONING THAT PRECEDED THE TAKES  (association, not cause)")
        for t in rep["by_tag"][:6]:
            print(f"  {t['tag']:<24} n={t['n_taken_with_tag']:<5} "
                  f"{t['mean_excess_bps']:+.0f} bps  "
                  f"(vs other takes {t['vs_other_takes_bps']:+.0f})")

    print(f"\nVERDICT  {v['failure_class']}")
    print(f"  {v['statement']}")
    for c in v["checks"]:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['criterion']}: "
              f"measured {c['measured']} against a bar of {c['bar']}")
    print(f"\n  {v['sample_caveat']}")
    m = rep.get("multiplicity", {})
    if m and m.get("n_tests") is not None:
        print(f"\n  multiplicity: {m['n_tests']} tests against this partition; "
              f"bar |t| > {m.get('required_t')}")
    print()


def cmd_cases(args: argparse.Namespace) -> int:
    """Print what the judge was actually shown."""
    try:
        r = replay.get(args.replay_id)
        cases = r.cases()
    except replay.ReplayError as exc:
        return _fail(str(exc))
    if args.index >= len(cases):
        return _fail(f"{r.id} has {len(cases)} cases; {args.index} is past the end")
    c = cases[args.index]
    if args.json:
        print(json.dumps(c.to_dict(), indent=2, default=str))
        return 0
    print(f"\n--- {c.case_id}  (hash {c.case_hash}) ---")
    if not c.anonymised:
        print(f"[identity revealed: {c.symbol} {c.date}]")
    print(c.render())
    return 0


def cmd_decisions(args: argparse.Namespace) -> int:
    """Print committed decisions, optionally filtered."""
    try:
        r = replay.get(args.replay_id)
        decisions = [d for d in r.decisions() if d.decider == args.decider]
    except replay.ReplayError as exc:
        return _fail(str(exc))
    if args.tag:
        decisions = [d for d in decisions if args.tag in (d.tags or [])]
    if args.action:
        decisions = [d for d in decisions if d.action == args.action.upper()]

    if args.json:
        print(json.dumps([d.to_dict() for d in decisions], indent=2, default=str))
        return 0

    print(f"\n{len(decisions)} decisions ({args.decider})\n")
    for d in decisions[:args.limit]:
        print(f"--- {d.case_id}  {d.action} @ {d.confidence:.2f}  "
              f"{','.join(d.tags)}")
        if d.error:
            print(f"    ERROR {d.error}")
            continue
        if args.full:
            for label, field in (("unusual", d.unusual), ("thesis", d.thesis),
                                 ("competing", d.competing_explanation),
                                 ("invalidation", d.invalidation),
                                 ("asymmetry", d.asymmetry)):
                if field:
                    print(f"    {label:<13} {field}")
        else:
            print(f"    {d.rationale}")
    print()
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Attach the discretionary loop to the top-level CLI."""
    op = sub.add_parser(
        "opportunity",
        help="freeze an idea into a discretionary experiment definition")
    op.add_argument("idea", help="the hypothesis, in plain language")
    op.add_argument("--hypothesis", required=True,
                    help="registered hypothesis ID this belongs to (e.g. H040)")
    op.add_argument("--generator", default="liquid_universe",
                    choices=generators.available(),
                    help="candidate generator (default: the broadest one)")
    op.add_argument("--generator-params", default=None,
                    help='JSON, e.g. \'{"min_tv_cr": 5}\'')
    op.add_argument("-n", type=int, default=500, help="case budget (default 500)")
    op.add_argument("--seed", type=int, default=0)
    op.add_argument("--horizon", type=int, default=10, help="sessions (default 10)")
    op.add_argument("--partition", default="train",
                    choices=("train", "validation", "test", "forward"))
    op.add_argument("--role", default="exploratory",
                    choices=("generation", "exploratory", "confirmatory"))
    op.add_argument("--provider", default="auto", choices=("auto", "api", "cli"))
    op.add_argument("--model", default=None)
    op.add_argument("--bar", action="append", metavar="KEY=VALUE",
                    help="pass criterion, repeatable; see opportunity.MIN_MEANINGFUL")
    op.add_argument("--reveal-identity", action="store_true",
                    help="show the symbol and the real dates to the judge. The "
                         "difference against an anonymised run measures "
                         "memorisation, so use it deliberately and in pairs.")
    op.set_defaults(fn=cmd_opportunity)

    rp = sub.add_parser("replay", help="run one phase of a discretionary replay")
    rp.add_argument("replay_id", help="replay ID, or 'list'")
    rp.add_argument("--phase", default=None,
                    choices=("status", "generate", "build", "decide", "reveal",
                             "evaluate"),
                    help="omit to show where this replay has got to")
    rp.add_argument("--no-budget", action="store_true",
                    help="skip the dispatch gate on reveal (dry runs only)")
    rp.add_argument("--no-record", action="store_true",
                    help="do not file Evidence or draw down the ledger")
    rp.set_defaults(fn=cmd_replay)

    cs = sub.add_parser("cases", help="print a case exactly as the judge saw it")
    cs.add_argument("replay_id")
    cs.add_argument("--index", type=int, default=0)
    cs.add_argument("--json", action="store_true")
    cs.set_defaults(fn=cmd_cases)

    dc = sub.add_parser("decisions", help="print committed decisions")
    dc.add_argument("replay_id")
    dc.add_argument("--decider", default="ai",
                    help=f"'ai' or a baseline: {', '.join(baselines.available())}")
    dc.add_argument("--tag", default=None, help="filter to one reasoning tag")
    dc.add_argument("--action", default=None, help="TAKE / SKIP / WATCH")
    dc.add_argument("--limit", type=int, default=20)
    dc.add_argument("--json", action="store_true")
    dc.add_argument("--full", action="store_true",
                    help="show the full reasoning, not just the rationale")
    dc.set_defaults(fn=cmd_decisions)
