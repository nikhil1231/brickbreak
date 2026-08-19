"""CLI for the Breeze feasibility spike.

  python -m src.cli login-url     # print the daily login URL (no auth needed)
  python -m src.cli master        # download/summarize the NSE scrip master (no auth)
  python -m src.cli check-auth    # verify the session token works
  python -m src.cli run           # run the full test matrix (needs auth)
  python -m src.cli run --quick   # connectivity + first-5-min only
  python -m src.cli estimate      # extrapolate full-download cost from measurements
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from . import build_screen, config, estimate, fetch_sample, nse_archive, security_master
from .breeze_client import BreezeClient
from .universe import TEST_UNIVERSE

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
    df = pd.read_parquet(p)
    print(f"consolidated -> {p.relative_to(config.PROJECT_ROOT)}  "
          f"rows={len(df):,} symbols={df['symbol'].nunique():,} dates={df['date'].nunique():,}")
    return 0


def cmd_sync_corp_actions(args) -> int:
    """Fetch NSE corporate actions, reconcile against the tape, adjust bars."""
    from datetime import date as _date
    from . import corporate_actions

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end) if args.end else _date.today()
    stats = corporate_actions.build(start=start, end=end, force_fetch=args.force)

    import pandas as pd
    from . import renames

    if renames.MAP_PATH.exists():
        rmap = pd.read_parquet(renames.MAP_PATH)
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

    rec = pd.read_parquet(corporate_actions.RECON_PATH)
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


def cmd_serve(args) -> int:
    from . import serve as serve_mod
    serve_mod.serve(port=args.port)
    return 0


def cmd_screen(args) -> int:
    """Headless screen: print the funnel summary for the default/CLI config."""
    from .screener import ScreenConfig, run_screen, summarize
    df = build_screen.load()
    overrides = {}
    for kv in (args.set or []):
        k, _, v = kv.partition("=")
        cur = getattr(ScreenConfig(), k, None)
        if v == "":
            overrides[k] = None
        elif isinstance(cur, bool):
            overrides[k] = v.lower() in ("1", "true", "yes")
        elif isinstance(cur, int) and not isinstance(cur, bool):
            overrides[k] = int(float(v))
        elif isinstance(cur, float):
            overrides[k] = float(v)
        else:
            overrides[k] = v
    cfg = ScreenConfig(**overrides)
    cands, counts = run_screen(df, cfg)
    out = {"config": cfg.to_dict(), **summarize(counts)}
    print(json.dumps(out, indent=2, default=str))
    _dump(out, config.METADATA_DIR / "screen_summary.json")
    return 0


def cmd_candidate_panel(args) -> int:
    """Join opening-window features to daily screener candidates."""
    import json as _json
    from . import opening_join
    from .screener import ScreenConfig

    panel, cov = opening_join.build(cfg=ScreenConfig())
    print(_json.dumps(cov, indent=2, default=str))
    _dump(cov, config.METADATA_DIR / "candidate_panel_coverage.json")
    print(f"\nwrote {opening_join.PANEL_PATH} ({len(panel):,} rows)")
    return 0


def cmd_characterize(args) -> int:
    """Distributions of the measures the entry rules are stated in."""
    from . import characterize, opening_join
    panel = opening_join.load_panel()
    rep = characterize.report(panel)
    d = rep["distributions"]
    print(f"{rep['panel_rows']:,} candidate symbol-days, {rep['symbols']:,} symbols, "
          f"{rep['window'][0]} -> {rep['window'][1]}\n")
    qs = ["p05", "p25", "p50", "p75", "p90", "p95", "p99"]
    print(f"{'measure':32s}" + "".join(f"{q:>9s}" for q in qs))
    for col, v in d.items():
        print(f"{col:32s}" + "".join(f"{v['quantiles'][q]:9.2f}" for q in qs))
    c = rep["censoring"]
    if c:
        print(f"\nom_low_vs_open_pct is censored at 0: {c['pct_at_zero_overall']}% "
              f"of days sit exactly at the boundary")
        for r in c["by_turnover_quintile"]:
            print(f"  {r['q']:10s} {r['pct_at_zero']:5.1f}% at zero "
                  f"(median {r['median_om_bars']:.0f} bars in the first minute)")
    print("\nmornings surviving each (gap band, volume floor):")
    for r in rep["joint_mass"]:
        print(f"  gap [{r['gap_low']:>4}, {r['gap_high']:>2}]  vol >= {r['vol_floor_pct']:>2}%  "
              f"-> {r['n_days']:6,} days ({r['pct_of_panel']:5.2f}%), "
              f"{r['n_symbols']:4} symbols")
    _dump(rep, characterize.REPORT_PATH)
    return 0


def cmd_label(args) -> int:
    """Forward returns for every candidate morning. The first evaluable output."""
    from . import labelling
    cfg = labelling.LabelConfig(entry_col=args.entry)
    labels, rep = labelling.build(cfg)
    print(f"\n{rep['rows']:,} mornings, {rep['symbols']:,} symbols, "
          f"{rep['window'][0]} -> {rep['window'][1]}, entry = {rep['entry_basis']}\n")

    hdr = f"{'horizon':>8s}{'n':>8s}{'mean%':>8s}{'med%':>8s}{'hit%':>7s}"
    hdr += f"{'MFE%':>8s}{'MAE%':>8s}{'excess%':>9s}{'exc.hit%':>9s}{'t':>7s}"
    print(hdr)
    for r in rep["horizons"]:
        line = (f"{r['horizon_d']:>7d}d{r['n']:>8,}{r['mean_pct']:>8.2f}"
                f"{r['median_pct']:>8.2f}{r['hit_rate_pct']:>7.1f}"
                f"{r['mean_mfe_pct']:>8.2f}{r['mean_mae_pct']:>8.2f}")
        if "mean_excess_pct" in r:
            line += (f"{r['mean_excess_pct']:>9.2f}{r['excess_hit_rate_pct']:>9.1f}"
                     f"{r['excess_t_stat']:>7.1f}")
        print(line)

    s = rep.get("entry_slippage_pct")
    if s:
        print(f"\nwaiting for the opening window to close cost a median "
              f"{s['median']:+.3f}% against the opening print "
              f"(p10 {s['p10']:+.2f}%, p90 {s['p90']:+.2f}%)")

    for title, key, unit in (("gap", "by_gap", "%"),
                             ("opening volume (% of median daily)", "by_open_volume", "")):
        print(f"\nforward return by {title}:")
        print(f"  {'bucket':>16s}{'n':>8s}" +
              "".join(f"{c:>10s}" for c in ("mean 1d", "mean 5d", "exc 5d", "hit 5d")))
        for r in rep[key]:
            print(f"  {r['bucket']:>16s}{r['n']:>8,}"
                  f"{r.get('mean_1d', float('nan')):>10.2f}"
                  f"{r.get('mean_5d', float('nan')):>10.2f}"
                  f"{r.get('excess_5d', float('nan')):>10.2f}"
                  f"{r.get('hit_5d', float('nan')):>10.1f}")
    if rep.get("slippage_by_open_volume"):
        print("\nwhat the first five minutes did (entry price vs opening print):")
        print(f"  {'opening volume':>16s}{'n':>8s}{'mean%':>9s}{'med%':>9s}{'up%':>8s}")
        for r in rep["slippage_by_open_volume"]:
            print(f"  {r['bucket']:>16s}{r['n']:>8,}{r['mean_pct']:>9.3f}"
                  f"{r['median_pct']:>9.3f}{r['pct_up']:>8.1f}")

    print(f"\n-> wrote {labelling.LABELS_PATH.relative_to(config.PROJECT_ROOT)}")
    _dump(rep, labelling.REPORT_PATH)
    return 0


def cmd_entry_window(args) -> int:
    """The opening window evaluated at a grid of candidate entry times (H004).

    Deliberately a grid, not a rule: `t` is still a discovery problem.
    """
    from . import entry_window as ew
    cfg = ew.WindowConfig(stop_buffer_pct=args.stop_buffer)
    grid, rep = ew.build(cfg)
    inv = rep["invariant"]
    print(f"\ninvariant  stop < running_low <= entry: "
          f"{'HOLDS' if inv['ok'] else 'VIOLATED'} on {inv['rows_checked']:,} rows\n")
    print(f"{'t':>6s}{'n':>9s}{'bars':>7s}{'low vs open':>13s}"
          f"{'entry vs open':>15s}{'stop dist':>11s}{'stop >1%':>10s}")
    for r in rep["profile"]:
        print(f"{r['t_offset_s']:>5d}s{r['n']:>9,}{r['median_bars']:>7.0f}"
              f"{r['median_low_vs_open_pct']:>13.3f}"
              f"{r['median_entry_vs_open_pct']:>15.3f}"
              f"{r['median_stop_dist_pct']:>11.3f}"
              f"{r['pct_stop_wider_than_1pct']:>9.1f}%")
    print("\nmedians. `low vs open` is the setup; `stop dist` is the risk; they are")
    print("different measurements and neither implies the other.")
    print(f"\n-> wrote {ew.GRID_PATH.relative_to(config.PROJECT_ROOT)}")
    _dump(rep, config.METADATA_DIR / "entry_window.json")
    return 0


def cmd_opening_report(args) -> int:
    """Quality report + per-symbol-day features for the fetched opening data."""
    import pandas as pd
    from . import fetch_opening as fo
    man = fo.load_manifest()
    if man.empty:
        print("no opening data fetched yet")
        return 1
    man["date"] = pd.to_datetime(man["date"])
    d = fo.load_opening()
    bad = fo.flag_bad_volume(d)
    no_session = fo.find_no_session_dates(man)
    feat = fo.opening_features(d)
    feat_path = config.NORMALIZED_DIR / "opening_features.parquet"
    feat.to_parquet(feat_path, index=False)
    report = {
        "pairs_attempted": int(len(man)),
        "status_counts": man["status"].value_counts().to_dict(),
        "rows": int(len(d)),
        "symbols": int(d["symbol"].nunique()),
        "dates": int(d["timestamp"].dt.date.nunique()),
        "no_opening_session_dates": no_session,
        "suspect_symbol_days_negative_volume": bad.to_dict("records"),
        "clean_symbol_days": int(len(feat)),
        "median_bars_per_symbol_day": float(feat["n_bars"].median()),
        "pct_zero_volume_bars": round(float((d["volume"] == 0).mean() * 100), 2),
        "features_path": str(feat_path.relative_to(config.PROJECT_ROOT)),
    }
    print(json.dumps(report, indent=2, default=str))
    _dump(report, config.METADATA_DIR / "opening_report.json")
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="src.cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login-url").set_defaults(fn=cmd_login_url)

    m = sub.add_parser("master")
    m.add_argument("--force", action="store_true", help="re-download the master")
    m.set_defaults(fn=cmd_master)

    sub.add_parser("check-auth").set_defaults(fn=cmd_check_auth)

    r = sub.add_parser("run")
    r.add_argument("--quick", action="store_true", help="connectivity + first-5-min only")
    r.add_argument("--throttle", type=float, default=0.7,
                   help="min seconds between API calls (default 0.7 ~= 85/min)")
    r.set_defaults(fn=cmd_run)

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
    sn.set_defaults(fn=cmd_sync_nse)

    ca = sub.add_parser("sync-corp-actions",
                        help="fetch NSE corporate actions and write adjusted daily bars")
    ca.add_argument("--start", default="2020-01-01")
    ca.add_argument("--end", default=None)
    ca.add_argument("--force", action="store_true",
                    help="re-download cached corporate-action chunks")
    ca.set_defaults(fn=cmd_sync_corp_actions)

    bm = sub.add_parser("build-metrics", help="compute the screening metrics panel")
    bm.add_argument("--force", action="store_true")
    bm.set_defaults(fn=cmd_build_metrics)

    sv = sub.add_parser("serve", help="run the interactive screener UI")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(fn=cmd_serve)

    sc = sub.add_parser("screen", help="headless screen summary")
    sc.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="override a ScreenConfig field, repeatable")
    sc.set_defaults(fn=cmd_screen)

    cp = sub.add_parser("candidate-panel",
                        help="join opening features to daily screener candidates")
    cp.set_defaults(fn=cmd_candidate_panel)

    ch = sub.add_parser("characterize",
                        help="distributions of gap / opening volume / first-minute shape")
    ch.set_defaults(fn=cmd_characterize)

    lb = sub.add_parser("label",
                        help="forward returns for each candidate morning")
    lb.add_argument("--entry", default="close_5m",
                    choices=["close_5m", "open_px", "open_raw"],
                    help="price the label is measured from (default: end of the "
                         "opening window, the first actionable price)")
    lb.set_defaults(fn=cmd_label)

    ew_ = sub.add_parser("entry-window",
                         help="opening window at a grid of candidate entry times")
    ew_.add_argument("--stop-buffer", type=float, default=0.10,
                     help="%% below the running low for the stop (default 0.10)")
    ew_.set_defaults(fn=cmd_entry_window)

    orp = sub.add_parser("opening-report", help="quality report for fetched opening data")
    orp.set_defaults(fn=cmd_opening_report)

    e = sub.add_parser("estimate")
    e.add_argument("--securities", type=int, default=2900)
    e.add_argument("--bytes-per-row", type=float, default=40.0)
    e.add_argument("--days-per-call", type=int, default=1)
    e.add_argument("--years-per-call", type=int, default=10)
    e.add_argument("--throttle", type=float, default=0.7)
    e.set_defaults(fn=cmd_estimate)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except config.ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
