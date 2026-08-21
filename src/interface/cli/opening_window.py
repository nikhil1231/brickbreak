"""CLI handlers for the opening-window research family."""
from __future__ import annotations

import json

from ...core import config
from ...research_data import repository
from ...research_data.pipelines import daily_panel as build_screen
from .data import _dump


def cmd_serve(args) -> int:
    from .. import screener_api
    screener_api.serve_standalone(port=args.port)
    return 0


def cmd_screen(args) -> int:
    """Headless screen: print the funnel summary for the default/CLI config."""
    from ...research.families.opening_window.screener import ScreenConfig, run_screen, summarize
    df = build_screen.load(asof_open=not args.unlagged)
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
    from ...research.families.opening_window import join as opening_join
    from ...research.families.opening_window.screener import ScreenConfig

    panel, cov = opening_join.build(cfg=ScreenConfig())
    print(_json.dumps(cov, indent=2, default=str))
    _dump(cov, config.METADATA_DIR / "candidate_panel_coverage.json")
    print(f"\nwrote {opening_join.PANEL_PATH} ({len(panel):,} rows)")
    return 0


def cmd_characterize(args) -> int:
    """Distributions of the measures the entry rules are stated in."""
    from ...research.families.opening_window import characterize, join as opening_join
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
    from ...research.families.opening_window import labelling
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
    from ...research.families.opening_window import entry_window as ew
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


def cmd_behaviour(args) -> int:
    """Second-level behavioural features for the opening window (H008).

    Exploration window only by default. The 2020-2023 backfill is holdout and
    building it here would put it one careless `groupby` away from being looked
    at, which is the whole thing the split exists to prevent.
    """
    from ...research.families.opening_window import behaviour, explore
    cfg = behaviour.BehaviourConfig()
    lo = None if args.all_dates else explore.EXPLORE_START
    panel = behaviour.build(cfg, date_min=lo)
    n_sparse = int(panel["sparse_t"].sum())
    print(f"\n  {n_sparse:,} rows ({n_sparse/len(panel)*100:.1f}%) have fewer than "
          f"{cfg.min_bars_for_shape} prints by `t`; their shape features are NaN,")
    print("  not zero — a thin morning has no behaviour to describe, and pretending")
    print("  otherwise is what censored `om_low_vs_open_pct` in Phase 2.3.")
    return 0


def cmd_explore(args) -> int:
    """Exploratory search over the opening-behaviour family (H008-H014).

    Everything printed here is EXPLORATORY / DATA-GENERATED. It is produced by
    the same data that would confirm it, so it confirms nothing.
    """
    import pandas as pd
    from ...research.families.opening_window import archetypes, explore
    d = explore.load_explore_frame()
    d["archetype"] = archetypes.assign(d)
    y = args.horizon
    s = d[d["t_offset_s"] == args.t]

    print(f"\n== archetypes at t={args.t}s, outcome {y} ==")
    prof = archetypes.profile(s, y)
    cols = ["archetype", "share_pct", "n", "mean", "median", "hit_pct", "t", "naive_t"]
    print(prof[cols].to_string(index=False))
    print("\n`t` is clustered by session; `naive_t` treats mornings as independent,")
    print("which they are not. The gap between them is roughly a factor of three.")

    print(f"\n== band sensitivity (does the archetype survive moving its bands?) ==")
    print(archetypes.band_sensitivity(s, y).to_string())

    out = {"n_rows": int(len(d)), "t": args.t, "horizon": y,
           "archetypes": prof.to_dict("records")}
    _dump(out, config.METADATA_DIR / "exploration.json")
    return 0


def cmd_context(args) -> int:
    """Market regime, breakout location and relative strength (as-of)."""
    from ...research_data.pipelines import context
    ctx, mkt = context.build(context.ContextConfig())
    reg = mkt["mkt_regime"].value_counts()
    print("\nsessions by market regime:")
    for k, v in reg.items():
        if v:
            print(f"  {str(k):16s} {v:5,}")
    return 0


def cmd_discover(args) -> int:
    """Reverse discovery: start from outcomes, work backwards to setups.

    EXPLORATORY / DATA-GENERATED throughout. Nothing printed here is a result;
    it is a shortlist of structures to freeze and test on the 2020-2023
    holdout, which this command is fenced away from by `explore.fence()`.
    """
    from ...research.families.opening_window import discovery
    rep = discovery.report(t=args.t, n_perm=args.n_perm, cluster_k=args.k,
                           verbose=True)
    _dump(rep, discovery.REPORT_PATH)
    if args.freeze:
        discovery.freeze(discovery.build_frozen(rep))
    print("\nEVERY LINE ABOVE IS EXPLORATORY. It was generated by the same "
          "window it\nwas measured on. Promotion requires the holdout.")
    return 0


def cmd_shotgun(args) -> int:
    """The H024 rule and every check that qualifies it. EXPLORATORY."""
    from ...research.families.opening_window import shotgun
    rep = shotgun.report(t=args.t, top_n=args.top_n, time_stop=args.hold,
                         cost_pct=args.cost, n_perm=args.n_perm, verbose=True)
    _dump(rep, shotgun.REPORT_PATH)
    if args.freeze:
        shotgun.freeze(rep)
    print("\nEXPLORATORY. Searched on the window it is measured on, on explicit"
          "\ninstruction to overfit. Promotion requires the 2020-2023 holdout.")
    return 0


def cmd_family(args) -> int:
    """Search the axes, stress-test the winners, freeze the family. EXPLORATORY."""
    from ...research.families.opening_window import family
    rep = family.report(n_perm=args.n_perm, do_freeze=not args.no_freeze,
                        verbose=True)
    _dump(rep, family.REPORT_PATH)
    print("\nEXPLORATORY. Everything above was searched on the window it is "
          "measured on.\nThe verdict comes from `python -m src.cli holdout`, "
          "which may be run once.")
    return 0


def cmd_holdout(args) -> int:
    """Open the 2020-2023 holdout against the frozen family. ONCE.

    Deliberately a separate command from `family`. Freezing and testing in one
    invocation would mean the definitions and the result arrive together, and
    the whole value of the arrangement is that the definitions are written down
    and *then* the window is opened.
    """
    from ...research.families.opening_window import family
    out = family.holdout(verbose=True)
    return 0 if out["verdict"] in ("PASS", "PARTIAL") else 1


def cmd_work_list(args) -> int:
    """Build the pull work list from the as-of-open screen, minus what is done.

    The manifest is the record of what has already been fetched, and it is
    consulted here rather than trusted later: the point of this command is that
    re-running it after a screen change pulls only the difference.
    """
    import pandas as pd
    from ...research.families.opening_window.screener import ScreenConfig, run_screen
    from ...research_data.pipelines import daily_panel as build_screen, opening as fo

    metrics = build_screen.load(asof_open=not args.unlagged)
    print(f"screening on the {'UNLAGGED (H015 lookahead)' if args.unlagged else 'as-of-open'} "
          f"panel ...")
    cands, _ = run_screen(metrics, ScreenConfig())
    print(f"  {len(cands):,} candidate symbol-days")

    man = None
    if args.manifest:
        man = repository.opening_manifest(args.manifest)
        print(f"  manifest: {len(man):,} settled pairs from {args.manifest}")
    work, rep = fo.build_work_list(cands, date_min=args.date_min,
                                   date_max=args.date_max, manifest=man)
    out = config.METADATA_DIR / "work_list.parquet"
    config.ensure_dirs()
    work.to_parquet(out, index=False)
    print(f"\n-> wrote {out.relative_to(config.PROJECT_ROOT)} ({len(work):,} pairs)")
    _dump(rep, config.METADATA_DIR / "work_list_summary.json")
    return 0


def cmd_payoff(args) -> int:
    """Simulate the stated stop/target/trail rule and bracket the ordering (H017).

    Reports the traded payoff beside the fixed-horizon label on the identical
    trades, so any difference is the measurement and not the sample.
    """
    import json as _json
    import pandas as pd
    from ...research.families.opening_window import behaviour, explore, payoff
    from ...research.families.opening_window.explore import cluster_stats

    d = explore.load_explore_frame(verbose=False)
    s = d[d["t_offset_s"] == args.t].copy()
    # The stop and the running low must be read at the same `t` as the entry,
    # and lifted onto the adjusted basis before anything is divided. See H004.
    s["running_low_t"] = s["running_low_t"] * s["adj_factor"]
    s["running_high_t"] = s["running_high_t"] * s["adj_factor"]
    s["stop_px_adj"] = s["running_low_t"] * (1 - args.stop_buffer / 100)
    bad = int((s["stop_px_adj"] >= s["running_low_t"]).sum()
              + (s["running_low_t"] > s["entry_px_adj"] + 1e-6).sum())
    if bad:
        raise AssertionError(f"stop < running_low <= entry violated on {bad} rows")

    bars = repository.daily_bars(
        columns=["symbol", "date", "open", "high", "low", "close"])
    cfg = payoff.PayoffConfig(target_pct=args.target, max_sessions=args.max_sessions)
    rep, pes, opt = payoff.bracket(s, bars, cfg)

    print(f"\n== traded payoff vs fixed horizon, t={args.t}s, "
          f"stop {args.stop_buffer}% below the running low ==")
    print(payoff.compare_to_fixed_horizon(pes, opt, horizon=5).to_string(index=False))
    print(f"\nexit mix: {rep['pessimistic']['exit_mix_pct']}")
    print(f"target filled on {rep['pessimistic']['target_filled_pct']}% of trades; "
          f"median hold {rep['pessimistic']['median_sessions_held']:.0f} sessions")
    print(f"\nordering bracket: {rep['bracket_width_pct']:.4f}% of expectancy, over "
          f"{rep['trades_whose_outcome_the_data_cannot_resolve']} trades "
          f"({rep['share_unresolved_pct']}%) the data cannot resolve.")
    print("Only SAME-session stop-and-target touches are ambiguous; across sessions")
    print("the order is known from the dates. That is what H006 conflated.")
    _dump(rep, config.METADATA_DIR / "payoff.json")
    return 0


def cmd_opening_report(args) -> int:
    """Quality report + per-symbol-day features for the fetched opening data."""
    import pandas as pd
    from ...research_data.pipelines import opening as fo
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

