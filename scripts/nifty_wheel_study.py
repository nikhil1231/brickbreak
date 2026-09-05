"""Backtest the wheel on Nifty — cash-secured puts and covered calls via the ETF."""
from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd

from src.core import config
from src.research_data.pipelines import index_option_chain as ioc
from src.research.families.covered_call import report, wheel
from src.research.families.covered_call.engine import CoveredCallConfig
from scripts.covered_call_study import benchmarks_for, market_frame

OUT = config.PROJECT_ROOT / "logs" / "covered_call"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chain = ioc.load()
    frame = market_frame()
    chain = chain.loc[chain["session"].isin(set(frame["session"]))]
    frame = frame.loc[frame["session"].isin(set(chain["session"]))].reset_index(drop=True)
    market = pd.DataFrame({"session": frame["session"], "proxy": frame["bees"],
                           "index": frame["index"],
                           "div_yield": frame["div_yield"]})
    bench = benchmarks_for(frame)

    base = wheel.WheelConfig()
    grid = [
        ("weekly wheel, 0.15 delta", base),
        ("weekly wheel, 0.30 delta",
         replace(base, put_delta=0.30, call_delta=0.30)),
        ("weekly wheel, 2% OTM", replace(base, strike_rule="otm")),
        ("monthly wheel, 0.15 delta", replace(base, cadence="monthly")),
        ("monthly wheel, 0.30 delta",
         replace(base, cadence="monthly", put_delta=0.30, call_delta=0.30)),
        ("weekly wheel, cash earns 0%", replace(base, cash_yield=0.0)),
        ("weekly wheel, 5% spread",
         replace(base, costs=replace(base.costs, premium_haircut=0.05))),
    ]

    rows = []
    for label, cfg in grid:
        out = wheel.run(chain, market, cfg)
        tab = report.compare(out["curve"], bench, label=label)
        row = tab.iloc[0].to_dict()
        row.update(wheel.wheel_stats(out["trades"], out["curve"]))
        row["vs_bees_cagr"] = row["cagr"] - tab.loc[
            tab["series"] == "NIFTYBEES buy & hold", "cagr"].iloc[0]
        rows.append(row)
        if label == "weekly wheel, 0.15 delta":
            print("=== BASE: weekly wheel on Nifty ===")
            print(tab.to_string(index=False))
            print(json.dumps(wheel.wheel_stats(out["trades"], out["curve"]),
                             indent=2))
            out["curve"].to_parquet(OUT / "wheel_curve.parquet", index=False)
            out["trades"].to_parquet(OUT / "wheel_trades.parquet", index=False)
            tab.to_csv(OUT / "wheel_metrics.csv", index=False)
            report.edge_test(out["curve"], bench).to_csv(
                OUT / "wheel_edge_test.csv", index=False)
            report.yearly(out["curve"], bench).to_csv(
                OUT / "wheel_yearly.csv", index=False)
        print(f"  {label:30s} cagr={row['cagr']:7.2%} "
              f"vs BeES={row['vs_bees_cagr']:+7.2%} vol={row['vol']:6.2%} "
              f"sharpe={row['sharpe']:5.2f} dd={row['max_drawdown']:7.2%} "
              f"in_mkt={row['time_in_market']:5.1%}", flush=True)

    sens = pd.DataFrame(rows)
    sens.to_csv(OUT / "wheel_sensitivity.csv", index=False)
    print("\n=== WHEEL SENSITIVITY ===")
    print(sens[["series", "cagr", "vs_bees_cagr", "vol", "sharpe",
                "max_drawdown", "time_in_market", "put_assignment_rate",
                "annualised_premium_pct"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
