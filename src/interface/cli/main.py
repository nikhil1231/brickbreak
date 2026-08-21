"""brickbreak command-line interface.

The public invocation remains ``python -m src.cli``; handlers live in modules
grouped by operational domain.
"""
from __future__ import annotations

import argparse
import sys

from ...core import config
from . import data, lab as iface_cli, opening_window


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="src.cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login-url").set_defaults(fn=data.cmd_login_url)

    m = sub.add_parser("master")
    m.add_argument("--force", action="store_true", help="re-download the master")
    m.set_defaults(fn=data.cmd_master)

    sub.add_parser("check-auth").set_defaults(fn=data.cmd_check_auth)

    r = sub.add_parser("run")
    r.add_argument("--quick", action="store_true", help="connectivity + first-5-min only")
    r.add_argument("--throttle", type=float, default=0.7,
                   help="min seconds between API calls (default 0.7 ~= 85/min)")
    r.set_defaults(fn=data.cmd_run)

    sn = sub.add_parser("sync-nse", help="download NSE bhavcopy + index lists (no auth)")
    sn.add_argument("--start", default="2022-01-01")
    sn.add_argument("--end", default=None)
    sn.add_argument("--throttle", type=float, default=0.25)
    sn.add_argument("--workers", type=int, default=4)
    sn.add_argument("--force-lists", action="store_true")
    sn.add_argument("--recheck-empty", action="store_true",
                    help="re-request days currently held as non-trading markers; "
                         "needed once to pick up weekend sessions an earlier "
                         "weekday-only sync never asked for")
    sn.set_defaults(fn=data.cmd_sync_nse)

    ca = sub.add_parser("sync-corp-actions",
                        help="fetch NSE corporate actions and write adjusted daily bars")
    ca.add_argument("--start", default="2020-01-01")
    ca.add_argument("--end", default=None)
    ca.add_argument("--force", action="store_true",
                    help="re-download cached corporate-action chunks")
    ca.set_defaults(fn=data.cmd_sync_corp_actions)

    bm = sub.add_parser("build-metrics", help="compute the screening metrics panel")
    bm.add_argument("--force", action="store_true")
    bm.set_defaults(fn=data.cmd_build_metrics)

    sv = sub.add_parser("serve-screener", help="run the standalone legacy screener service")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(fn=opening_window.cmd_serve)

    sc = sub.add_parser("screen", help="headless screen summary")
    sc.add_argument("--unlagged", action="store_true",
                    help="screen on the entry day's own close (the H015 lookahead; "
                         "for comparison only)")
    sc.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="override a ScreenConfig field, repeatable")
    sc.set_defaults(fn=opening_window.cmd_screen)

    cp = sub.add_parser("candidate-panel",
                        help="join opening features to daily screener candidates")
    cp.set_defaults(fn=opening_window.cmd_candidate_panel)

    ch = sub.add_parser("characterize",
                        help="distributions of gap / opening volume / first-minute shape")
    ch.set_defaults(fn=opening_window.cmd_characterize)

    lb = sub.add_parser("label",
                        help="forward returns for each candidate morning")
    lb.add_argument("--entry", default="close_5m",
                    choices=["close_5m", "open_px", "open_raw"],
                    help="price the label is measured from (default: end of the "
                         "opening window, the first actionable price)")
    lb.set_defaults(fn=opening_window.cmd_label)

    ew_ = sub.add_parser("entry-window",
                         help="opening window at a grid of candidate entry times")
    ew_.add_argument("--stop-buffer", type=float, default=0.10,
                     help="%% below the running low for the stop (default 0.10)")
    ew_.set_defaults(fn=opening_window.cmd_entry_window)

    bh = sub.add_parser("behaviour",
                        help="second-level behavioural features for the opening window")
    bh.add_argument("--all-dates", action="store_true",
                    help="include holdout dates (do not use for exploration)")
    bh.set_defaults(fn=opening_window.cmd_behaviour)

    ex = sub.add_parser("explore-opening",
                        help="exploratory search over the opening-behaviour family (legacy)")
    ex.add_argument("--t", type=int, default=300, help="entry time in seconds (default 300)")
    ex.add_argument("--horizon", default="excess_ret_5d_pct")
    ex.set_defaults(fn=opening_window.cmd_explore)

    cx = sub.add_parser("context",
                        help="build market regime + breakout location + relative strength")
    cx.set_defaults(fn=opening_window.cmd_context)

    dv = sub.add_parser("discover",
                        help="reverse discovery: outcome archetypes, matched controls, "
                             "discriminant search (EXPLORATORY)")
    dv.add_argument("--t", type=int, default=180,
                    help="entry time in seconds inside the opening window (default 180)")
    dv.add_argument("--n-perm", type=int, default=200,
                    help="permutations for the max-|t| null (default 200)")
    dv.add_argument("--k", type=int, default=4, help="winner clusters (default 4)")
    dv.add_argument("--freeze", action="store_true",
                    help="write the shortlist to discovery_frozen.json for the holdout")
    dv.set_defaults(fn=opening_window.cmd_discover)

    sh = sub.add_parser("shotgun",
                        help="the H024 ranking rule and its checks (EXPLORATORY)")
    sh.add_argument("--t", type=int, default=180)
    sh.add_argument("--top-n", type=int, default=5, help="picks per session")
    sh.add_argument("--hold", type=int, default=30, help="sessions held")
    sh.add_argument("--cost", type=float, default=0.40,
                    help="round-trip cost in %% (default 0.40)")
    sh.add_argument("--n-perm", type=int, default=400)
    sh.add_argument("--freeze", action="store_true")
    sh.set_defaults(fn=opening_window.cmd_shotgun)

    fm = sub.add_parser("family",
                        help="search, stress-test and freeze the rule family (EXPLORATORY)")
    fm.add_argument("--n-perm", type=int, default=200)
    fm.add_argument("--no-freeze", action="store_true",
                    help="report without writing family_frozen.json")
    fm.set_defaults(fn=opening_window.cmd_family)

    ho = sub.add_parser("holdout",
                        help="open the 2020-2023 holdout against the frozen family (ONCE)")
    ho.set_defaults(fn=opening_window.cmd_holdout)

    wl = sub.add_parser("work-list",
                        help="build the pull work list (as-of-open screen minus manifest)")
    wl.add_argument("--date-min", default=None)
    wl.add_argument("--date-max", default=None)
    wl.add_argument("--manifest", default=None,
                    help="manifest parquet to dedup against (default: local)")
    wl.add_argument("--unlagged", action="store_true",
                    help="screen on the entry day's own close (the H015 lookahead)")
    wl.set_defaults(fn=opening_window.cmd_work_list)

    pf = sub.add_parser("payoff",
                        help="simulate the stop/target/trail rule and bracket it (H017)")
    pf.add_argument("--t", type=int, default=300)
    pf.add_argument("--stop-buffer", type=float, default=2.0,
                    help="%% below the running low for the stop (default 2.0)")
    pf.add_argument("--target", type=float, default=15.0)
    pf.add_argument("--max-sessions", type=int, default=60)
    pf.set_defaults(fn=opening_window.cmd_payoff)

    sp = sub.add_parser("split", help="build/freeze/describe a dataset split")
    sp.add_argument("--version", default="v1")
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--max-horizon", type=int, default=20,
                    help="longest forward horizon this split is purged for")
    sp.add_argument("--show", action="store_true", help="describe the frozen split")
    sp.add_argument("--freeze", action="store_true", help="write the manifest")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an existing frozen split — almost never right")
    sp.set_defaults(fn=data.cmd_split)

    pl = sub.add_parser("plan", help="turn an idea into an experiment plan")
    pl.add_argument("idea")
    pl.add_argument("--with-columns", action="store_true",
                    help="show the planner the available columns (slower)")
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--provider", choices=("claude", "codex"), default="claude")
    pl.add_argument("--model", default=None)
    pl.set_defaults(fn=iface_cli.cmd_plan)

    sg = sub.add_parser("suggest",
                        help="the research inbox: what to test next")
    sg.add_argument("--new", action="store_true",
                    help="ask for fresh proposals (spends a model call)")
    sg.add_argument("-n", type=int, default=3,
                    help="how many to propose with --new (default 3)")
    sg.add_argument("--refresh", default=None, metavar="Sxxx",
                    help="replace one open suggestion with a new one")
    sg.add_argument("--json", action="store_true")
    sg.add_argument("--provider", choices=("claude", "codex"), default="claude")
    sg.add_argument("--model", default=None)
    sg.set_defaults(fn=iface_cli.cmd_suggest)

    jb_ = sub.add_parser("job", help="run an LLM-backed research job")
    jb_.add_argument("--hypothesis", required=True)
    jb_.add_argument("--question", required=True)
    jb_.add_argument("--signal", required=True)
    jb_.add_argument("--partition", default="train")
    jb_.add_argument("--role", default="exploratory")
    jb_.add_argument("--horizon", type=int, default=10)
    jb_.add_argument("--timeout", type=int, default=1800)
    jb_.add_argument("--max-turns", type=int, default=40)
    jb_.add_argument("--provider", choices=("claude", "codex"), default="claude")
    jb_.add_argument("--model", default=None)
    jb_.add_argument("--keep-worktree", action="store_true")
    jb_.set_defaults(fn=iface_cli.cmd_job)

    js = sub.add_parser("jobs", help="list research jobs")
    js.add_argument("--limit", type=int, default=20)
    js.set_defaults(fn=iface_cli.cmd_jobs)

    fw = sub.add_parser("forward", help="forward-lane status and accrual")
    fw.add_argument("--accrue", action="store_true")
    fw.set_defaults(fn=iface_cli.cmd_forward)

    bd = sub.add_parser("burden", help="multiple-comparisons load on a partition")
    bd.add_argument("--partition", default="train")
    bd.add_argument("--fdr", type=float, default=0.10)
    bd.add_argument("--limit", type=int, default=25)
    bd.set_defaults(fn=iface_cli.cmd_burden)

    orp = sub.add_parser("opening-report", help="quality report for fetched opening data")
    orp.set_defaults(fn=opening_window.cmd_opening_report)

    e = sub.add_parser("estimate")
    e.add_argument("--securities", type=int, default=2900)
    e.add_argument("--bytes-per-row", type=float, default=40.0)
    e.add_argument("--days-per-call", type=int, default=1)
    e.add_argument("--years-per-call", type=int, default=10)
    e.add_argument("--throttle", type=float, default=0.7)
    e.set_defaults(fn=data.cmd_estimate)

    # -----------------------------------------------------------------------
    # Research Lab Subcommands (the refactor plan §7)
    # -----------------------------------------------------------------------
    cat_p = sub.add_parser("catalogue", help="browse registered features in the catalogue")
    cat_p.add_argument("--owner", default=None, help="filter by feature owner")
    cat_p.set_defaults(fn=iface_cli.cmd_catalogue)

    hyp_p = sub.add_parser("hypotheses", help="browse research ledger hypotheses (H001–H038)")
    hyp_p.add_argument("--id", default=None, help="show specific hypothesis details")
    hyp_p.add_argument("--status", default=None, help="filter by status")
    hyp_p.add_argument("--family", default=None, help="filter by family")
    hyp_p.set_defaults(fn=iface_cli.cmd_hypotheses)

    led_p = sub.add_parser("ledger", help="view sample budget ledger and consumed quarters")
    led_p.set_defaults(fn=iface_cli.cmd_ledger)

    exp_p = sub.add_parser("explore", help="launch an automated exploration from a spec")
    exp_p.add_argument("hypothesis", help="hypothesis ID (e.g. H026)")
    exp_p.add_argument("--question", default=None, help="research question")
    exp_p.add_argument("--signal", default=None, help="signal name")
    exp_p.add_argument("--partition", default="train", help="partition (train/validation/test/forward)")
    exp_p.add_argument("--role", default="exploratory", help="role (exploratory/confirmatory)")
    exp_p.add_argument("--provider", choices=("claude", "codex"), default="claude")
    exp_p.add_argument("--model", default=None, help="provider model (default: CLI default)")
    exp_p.set_defaults(fn=iface_cli.cmd_explore)

    cmp_p = sub.add_parser("compare", help="compare 2–10 candidate signals")
    cmp_p.add_argument("signals", nargs="+", help="signal names to compare")
    cmp_p.set_defaults(fn=iface_cli.cmd_compare_signals)

    srv_p = sub.add_parser("serve", help="launch the primary backend and web application")
    srv_p.add_argument("--port", type=int, default=8080, help="port to listen on (default 8080)")
    srv_p.set_defaults(fn=iface_cli.cmd_serve)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except config.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
