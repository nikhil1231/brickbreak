"""CLI handlers for market-data ingestion and feasibility operations."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from ...core import config
from ...research_data import repository
from ...research_data.feasibility import estimate, probes as fetch_sample
from ...research_data.feasibility.universe import TEST_UNIVERSE
from ...research_data.pipelines import daily_panel as build_screen
from ...research_data.sources import nse as nse_archive, security_master
from ...research_data.sources.breeze import BreezeClient

REPORT = config.METADATA_DIR / "feasibility_report.json"
MASTER_REPORT = config.METADATA_DIR / "universe_summary.json"


def _dump(obj, path) -> None:
    config.ensure_dirs()
    path.write_text(json.dumps(obj, indent=2, default=str))
    print(f"\n-> wrote {path.relative_to(config.PROJECT_ROOT)}")


def cmd_login_url(_args) -> int:
    creds = config.load_credentials(require_session=False)
    print("\n1. Open this URL and log in with your ICICI Direct credentials:\n")
    print(f"   {creds.login_url}\n")
    print("2. After login you are redirected to your registered redirect URL.")
    print("   Copy the `apisession` (a.k.a. API_Session) query-parameter value.")
    print("3. Put it in .env as BREEZE_SESSION_TOKEN=<value>\n")
    print("   The token expires daily, so this is a once-per-day step.\n")
    return 0


def cmd_master(_args) -> int:
    df = security_master.load(force_download=getattr(_args, "force", False))
    summary = security_master.summarize(df)
    security_master.save_parquet(df)
    print(json.dumps(summary, indent=2, default=str))
    _dump(summary, MASTER_REPORT)
    return 0


def cmd_check_auth(_args) -> int:
    creds = config.load_credentials(require_session=True)
    client = BreezeClient(creds)
    res = fetch_sample.probe_connectivity(client)
    print(json.dumps(res, indent=2, default=str))
    return 0 if res.get("authenticated") else 1


def cmd_run(args) -> int:
    creds = config.load_credentials(require_session=True)
    client = BreezeClient(creds, min_interval_s=args.throttle)
    df_master = security_master.load()

    report: dict = {
        "run_started_at": datetime.now().isoformat(),
        "throttle_s": args.throttle,
        "universe_summary": security_master.summarize(df_master),
    }

    print("== connectivity ==")
    report["connectivity"] = fetch_sample.probe_connectivity(client)
    print(json.dumps(report["connectivity"], indent=2, default=str))
    if not report["connectivity"].get("authenticated"):
        _dump(report, REPORT)
        print("\nAuthentication failed - cannot run the matrix. "
              "Regenerate BREEZE_SESSION_TOKEN (`python -m src.cli login-url`).")
        return 1

    resolved = {s.nse_symbol: security_master.resolve(df_master, s.nse_symbol)
                for s in TEST_UNIVERSE}
    report["symbol_resolution"] = {
        k: (None if v is None else {"isec_code": v.isec_code, "token": v.token,
                                    "series": v.series, "company": v.company})
        for k, v in resolved.items()
    }

    primary = TEST_UNIVERSE[0]
    primary_isec = resolved[primary.nse_symbol].isec_code

    print("\n== stock_code form (ISEC short code vs NSE symbol) ==")
    report["code_form"] = fetch_sample.probe_code_form(client, df_master)
    print(json.dumps(report["code_form"], indent=2, default=str))

    print("\n== v1 vs v2 endpoint parity ==")
    report["endpoint_parity"] = fetch_sample.probe_endpoint_parity(client, primary_isec, primary)

    # Pick a real recent trading day from the API itself rather than guessing.
    days = fetch_sample.find_trading_days(client, primary_isec, 2026, 8, limit=3)
    report["recent_trading_days_found"] = [str(d) for d in days]
    if not days:
        days = fetch_sample.find_trading_days(client, primary_isec, 2026, 7, limit=3)
        report["fallback_trading_days"] = [str(d) for d in days]
    test_day = days[-1] if days else None
    report["test_day"] = str(test_day)
    print(f"test day chosen from API: {test_day}")

    targets = TEST_UNIVERSE if not args.quick else TEST_UNIVERSE[:2]

    print("\n== daily recent + first 5 minutes per security ==")
    report["daily_recent"], report["second_first_5min"], report["minute_full_day"] = [], [], []
    for sec in targets:
        r = resolved[sec.nse_symbol]
        if r is None:
            continue
        report["daily_recent"].append(
            fetch_sample.probe_daily_recent(client, r.isec_code, sec))
        if test_day and sec.kind != "inactive":
            report["second_first_5min"].append(
                fetch_sample.probe_second_open(client, r.isec_code, sec, test_day))
            report["minute_full_day"].append(
                fetch_sample.probe_minute_day(client, r.isec_code, sec, test_day))
        print(f"  {sec.nse_symbol:12} daily_rows={report['daily_recent'][-1]['n_rows']:5} "
              f"1s_rows={report['second_first_5min'][-1]['n_rows'] if report['second_first_5min'] else '-'}")

    if not args.quick:
        print("\n== historical depth (daily) ==")
        report["daily_depth"] = []
        for sec in [s for s in TEST_UNIVERSE if s.kind == "liquid"][:3]:
            report["daily_depth"] += fetch_sample.probe_daily_depth(
                client, resolved[sec.nse_symbol].isec_code, sec)

        print("== historical depth (1-second) ==")
        report["second_depth"] = fetch_sample.probe_second_depth(
            client, primary_isec, primary, df_master)

        print("== max usable range per call ==")
        report["max_range"] = fetch_sample.probe_max_range(
            client, primary_isec, primary, test_day) if test_day else []

        print("== repeat stability ==")
        report["stability"] = fetch_sample.probe_stability(
            client, primary_isec, primary, test_day) if test_day else {}

        print("== inactive / delisted securities ==")
        report["inactive"] = fetch_sample.probe_inactive(client, df_master)

        print("== corporate actions ==")
        report["corporate_actions"] = fetch_sample.probe_corporate_action(client, df_master)

        print("== 1s vs 1m volume cross-validation ==")
        report["volume_cross_validation"] = [
            fetch_sample.probe_volume_cross_validation(
                client, resolved[s.nse_symbol].isec_code, s, test_day)
            for s in TEST_UNIVERSE if s.kind != "inactive" and resolved[s.nse_symbol]
        ] if test_day else []
        for x in report["volume_cross_validation"]:
            print(f"  {x['symbol']:12} 1s_total={x.get('total_1s_volume')} "
                  f"1m_total={x.get('total_1m_volume')} match={x.get('total_match')}")

        print("== 1-second start boundary ==")
        report["second_start_boundary"] = fetch_sample.probe_second_start_boundary(client)
        print(f"  first month with 1s data: {report['second_start_boundary']['first_month_with_1s_data']}")

        print("== corporate-action adjustment cutoff ==")
        report["adjustment_cutoff"] = fetch_sample.probe_adjustment_cutoff(client)
        ac = report["adjustment_cutoff"]
        print(f"  latest adjusted: {ac['latest_adjusted_event']}  "
              f"earliest unadjusted: {ac['earliest_unadjusted_event']}")

        print("== index / sector-index availability ==")
        report["indices"] = fetch_sample.probe_indices(client)
        hits = [x["code_tried"] for x in report["indices"] if x["ok"]]
        print(f"  index codes that returned data: {hits or 'NONE'}")

    calls = estimate.load_call_log()
    report["throughput"] = {
        "overall": estimate.measured_throughput(calls),
        "by_interval": {iv: estimate.measured_throughput(calls, iv)
                        for iv in ("1second", "1minute", "1day")},
    }
    report["n_api_calls_this_run"] = len(calls)
    report["run_finished_at"] = datetime.now().isoformat()
    _dump(report, REPORT)
    print("\nDone. Inspect data/metadata/feasibility_report.json and api_calls.jsonl.")
    return 0


def cmd_sync_nse(args) -> int:
    """Download NSE bhavcopy + index constituent lists. No authentication."""
    from datetime import date as _date
    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end) if args.end else _date.today()
    print("fetching index constituent lists ...")
    meta = nse_archive.build_symbol_metadata(force=args.force_lists)
    print(f"  {len(meta)} symbols, {int(meta['sector'].notna().sum())} with a sector label")
    print(f"syncing bhavcopy {start} -> {end} ...")
    stats = nse_archive.sync(start, end, throttle=args.throttle, workers=args.workers,
                             recheck_empty=args.recheck_empty)
    print("  ", stats)
    p = nse_archive.consolidate()
    import pandas as pd
    df = repository.daily_bars(adjusted=False)
    print(f"consolidated -> {p.relative_to(config.PROJECT_ROOT)}  "
          f"rows={len(df):,} symbols={df['symbol'].nunique():,} dates={df['date'].nunique():,}")
    return 0


def cmd_sync_corp_actions(args) -> int:
    """Fetch NSE corporate actions, reconcile against the tape, adjust bars."""
    from datetime import date as _date
    from ...research_data.pipelines import corporate_actions

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end) if args.end else _date.today()
    stats = corporate_actions.build(start=start, end=end, force_fetch=args.force)

    import pandas as pd
    from ...research_data.pipelines import renames

    if renames.MAP_PATH.exists():
        rmap = repository.rename_map()
        print("\nsymbol renames validated against the tape:")
        for status, n in rmap["status"].value_counts().items():
            print(f"  {status:16s} {n:5d}")
        rejected = rmap[rmap["status"].isin(["long_gap", "price_break", "overlap"])]
        if len(rejected):
            print(f"\n{len(rejected)} published rename(s) NOT merged (left as "
                  f"separate symbols, see {renames.MAP_PATH.name}):")
            for r in rejected.itertuples():
                print(f"  {r.old_symbol:12s} -> {r.new_symbol:12s} "
                      f"gap={r.gap_days}d step={r.px_step:.2f}  {r.status}")

    rec = repository.corporate_action_reconciliation()
    print("\nreconciliation of stated ratios against observed price steps:")
    for status, n in rec["status"].value_counts().items():
        print(f"  {status:16s} {n:5d}")
    renamed = rec[rec["renamed_from"].notna()]
    if len(renamed):
        print(f"\n{len(renamed)} event(s) resolved to a pre-rename ticker:")
        for r in renamed.itertuples():
            print(f"  {r.symbol} <- {r.renamed_from}  {r.ex_date.date()}  {r.kinds}")
    bad = rec[rec["status"].isin(["no_step", "ratio_mismatch", "unparsed"])]
    if len(bad):
        print(f"\n{len(bad)} event(s) NOT adjusted (left raw, see "
              f"{corporate_actions.RECON_PATH.name}):")
        for r in bad.head(20).itertuples():
            print(f"  {r.symbol:12s} {r.ex_date.date()}  {r.kinds:14s} {r.status}")
        if len(bad) > 20:
            print(f"  ... and {len(bad)-20} more")
    return 0


def cmd_build_metrics(args) -> int:
    build_screen.build(force=args.force)
    return 0


def cmd_estimate(args) -> int:
    calls = estimate.load_call_log()
    if not calls:
        print("No measurements in data/metadata/api_calls.jsonl yet. Run `run` first.")
        return 1
    sec_tp = estimate.measured_throughput(calls, "1second")
    day_tp = estimate.measured_throughput(calls, "1day")
    out = {
        "measured": {"1second": sec_tp, "1day": day_tp,
                     "overall": estimate.measured_throughput(calls)},
        "first_5min_1second_3y": estimate.estimate_full_download(
            n_securities=args.securities, years=3,
            bytes_per_row=args.bytes_per_row,
            mean_call_duration_s=sec_tp.get("mean_duration_s") or 1.0,
            days_per_call=args.days_per_call, min_interval_s=args.throttle),
        "daily_history_20y": estimate.estimate_daily_history(
            n_securities=args.securities, years=20,
            bytes_per_row=args.bytes_per_row,
            mean_call_duration_s=day_tp.get("mean_duration_s") or 1.0,
            years_per_call=args.years_per_call, min_interval_s=args.throttle),
    }
    print(json.dumps(out, indent=2, default=str))
    _dump(out, config.METADATA_DIR / "cost_estimate.json")
    return 0


def cmd_split(args) -> int:
    """Build, freeze or describe a dataset split.

    A split is a commitment: every result the lab produces is denominated in
    it. `--freeze` writes it once and refuses to overwrite, so re-drawing is a
    new version with a stated reason rather than a silent edit (PLAN.md §5.2).
    """
    from ...research_data import splits

    if args.show:
        m = splits.load(args.version)
    else:
        cfg = splits.SplitConfig(version=args.version,
                                 seed=args.seed,
                                 max_horizon=args.max_horizon)
        m = splits.build(cfg)

    print(splits.summary(m))
    print()
    hdr = f"{'quarter':<8} {'set':<11} {'sessions':>8}  {'vol':>6} {'trend':>6}  exposure"
    print(hdr)
    print("-" * len(hdr))
    for q in m["quarters"]:
        ex = ", ".join(sorted({f"{e['family']}:{e['role'][:4]}"
                               for e in q["prior_exposure"]})) or "-"
        print(f"{q['quarter']:<8} {q['set']:<11} {q['n_sessions']:>8}  "
              f"{q['mkt_vol_20d']:>6.1f} {q['mkt_trend_eff']:>6.2f}  {ex}")

    if args.freeze:
        path = splits.save(m, overwrite=args.force)
        print(f"\nfrozen -> {path}")
    elif not args.show:
        print("\n(not written — pass --freeze to commit this split)")
    return 0


