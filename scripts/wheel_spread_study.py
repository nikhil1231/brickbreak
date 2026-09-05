"""H067: test a physically settled bull-put-spread wheel extension.

This does not claim SPAN margin relief. Every short put remains fully cash
secured, so the comparison isolates what the long put buys: less net premium,
a capped crash loss, and a different probability of entering the share/call
half of the wheel.
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.core import config
from src.research.families.wheel import report
from src.research.families.wheel.engine import WheelConfig, prepare, run
from src.research_data.pipelines import option_chain as oc
from src.research_data.sources import nse_index_close as ic

OUT = config.PROJECT_ROOT / "logs" / "wheel"


def _execution_config() -> WheelConfig:
    base = WheelConfig(slots=20, put_otm=.10, call_otm=.10,
                       lag_selection=True, premium_column="close",
                       min_strike_contracts=250.0)
    return replace(base, costs=replace(base.costs, premium_haircut=.10))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    prices = oc.settlement_prices()
    chain = oc.load()
    chain = chain.loc[chain["session"] <= prices["session"].max()]
    benchmark = ic.series("Nifty 50")
    print(f"preparing {len(chain):,} option rows", flush=True)
    tape = prepare(chain)

    unhedged = _execution_config()
    primary = replace(unhedged, put_hedge_width=.05)
    diagnostic = replace(unhedged, put_hedge_width=.10)
    configs: list[tuple[str, WheelConfig]] = [
        ("H063 combined execution, unhedged", unhedged),
        ("H067 bull put spread, 5pt hedge", primary),
        ("H067 shape diagnostic, 10pt hedge", diagnostic),
    ]
    for capital in (20_000_000.0, 100_000_000.0):
        configs.append((
            f"H067 5pt, whole lots {capital / 10_000_000:.0f}cr",
            replace(primary, quantise_lots=True, starting_capital=capital,
                    costs=replace(primary.costs,
                                  brokerage_per_lot_order=20.0))))

    rows = []
    curves: dict[str, pd.DataFrame] = {}
    for label, wheel_cfg in configs:
        out = run(tape, prices, wheel_cfg)
        curves[label] = out["curve"]
        table = report.compare(out["curve"], benchmark, label=label)
        strategy, matched = table.iloc[0], table.iloc[-1]
        edge = report.edge_test(out["curve"], benchmark)
        edge = edge.loc[
            edge["versus"] == "Nifty TR, volatility-matched"].iloc[0]
        stats = report.trade_stats(out["trades"])
        row = {
            "series": label,
            "hedge_width_target": wheel_cfg.put_hedge_width,
            "capital": wheel_cfg.starting_capital,
            "whole_lots": wheel_cfg.quantise_lots,
            "wheel_cagr": strategy["cagr"],
            "matched_cagr": matched["cagr"],
            "cagr_gap": strategy["cagr"] - matched["cagr"],
            "wheel_sharpe": strategy["sharpe"],
            "matched_sharpe": matched["sharpe"],
            "sharpe_gap": strategy["sharpe"] - matched["sharpe"],
            "vol": strategy["vol"],
            "drawdown": strategy["max_drawdown_monthly"],
            "annualised_mean_gap": edge["annualised_gap"],
            "bootstrap_lo": edge["boot_lo_annual"],
            "bootstrap_hi": edge["boot_hi_annual"],
            "mean_legs_written": out["curve"]["written"].mean(),
            "min_legs_written": out["curve"]["written"].min(),
            **{k: stats.get(k) for k in (
                "puts_written", "calls_written", "put_assignment_rate",
                "call_assignment_rate", "hedged_puts", "hedge_exercise_rate",
                "median_hedge_width", "hedge_cost_per_put_notional",
                "premium_per_put_notional")},
        }
        rows.append(row)
        print(f"{label:39s} CAGR {row['wheel_cagr']:6.2%} vs "
              f"{row['matched_cagr']:6.2%} ({row['cagr_gap']:+6.2%}); "
              f"Sharpe {row['wheel_sharpe']:.3f} vs "
              f"{row['matched_sharpe']:.3f}; CI "
              f"[{row['bootstrap_lo']:+.1%}, {row['bootstrap_hi']:+.1%}]; "
              f"legs {row['mean_legs_written']:.1f}", flush=True)

    result = pd.DataFrame(rows)
    baseline = result.iloc[0]
    result["cagr_vs_unhedged"] = result["wheel_cagr"] - baseline["wheel_cagr"]
    result["sharpe_vs_unhedged"] = (
        result["wheel_sharpe"] - baseline["wheel_sharpe"])
    result.to_csv(OUT / "wheel_spread_study.csv", index=False)
    curves[configs[1][0]].to_parquet(
        OUT / "wheel_spread_primary_curve.parquet", index=False)
    print("\nwrote H067 outputs under", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
