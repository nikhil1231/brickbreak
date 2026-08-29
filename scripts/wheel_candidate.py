"""H063: attack the 20-slot, 10%-OTM wheel lead."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.core import config
from src.research.families.wheel import report
from src.research.families.wheel.engine import WheelConfig, prepare, run
from src.research_data.pipelines import option_chain as oc
from src.research_data.sources import nse_index_close as ic

OUT = config.PROJECT_ROOT / "logs" / "wheel"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    prices = oc.settlement_prices()
    chain = oc.load()
    chain = chain.loc[chain["session"] <= prices["session"].max()]
    benchmark = ic.series("Nifty 50")
    print(f"preparing {len(chain):,} option rows", flush=True)
    tape = prepare(chain)

    found = WheelConfig(slots=20, put_otm=.10, call_otm=.10)
    lagged = replace(found, lag_selection=True)
    execution = replace(
        lagged, premium_column="close", min_strike_contracts=250.0,
        costs=replace(lagged.costs, premium_haircut=.10))
    configs: list[tuple[str, WheelConfig]] = [
        ("found: same-day selection", found),
        ("lagged selection", lagged),
        ("lagged + haircut 10%",
         replace(lagged, costs=replace(lagged.costs, premium_haircut=.10))),
        ("lagged + haircut 20%",
         replace(lagged, costs=replace(lagged.costs, premium_haircut=.20))),
        ("lagged + last trade", replace(lagged, premium_column="close")),
        ("lagged + 250 contracts", replace(lagged, min_strike_contracts=250.0)),
        ("lagged + combined execution", execution),
    ]
    for capital in (5_000_000.0, 20_000_000.0, 100_000_000.0):
        configs.append((
            f"combined + whole lots {capital / 10_000_000:.1f}cr",
            replace(execution, quantise_lots=True, starting_capital=capital,
                    costs=replace(execution.costs,
                                  brokerage_per_lot_order=20.0))))

    rows = []
    primary_curve = None
    for label, wheel_cfg in configs:
        out = run(tape, prices, wheel_cfg)
        table = report.compare(out["curve"], benchmark, label=label)
        wheel, matched = table.iloc[0], table.iloc[-1]
        edge = report.edge_test(out["curve"], benchmark)
        edge = edge.loc[
            edge["versus"] == "Nifty TR, volatility-matched"].iloc[0]
        stats = report.trade_stats(out["trades"])
        rows.append({
            "series": label,
            "wheel_cagr": wheel["cagr"],
            "matched_cagr": matched["cagr"],
            "cagr_gap": wheel["cagr"] - matched["cagr"],
            "wheel_sharpe": wheel["sharpe"],
            "matched_sharpe": matched["sharpe"],
            "sharpe_gap": wheel["sharpe"] - matched["sharpe"],
            "vol": wheel["vol"],
            "drawdown": wheel["max_drawdown_monthly"],
            "annualised_mean_gap": edge["annualised_gap"],
            "bootstrap_lo": edge["boot_lo_annual"],
            "bootstrap_hi": edge["boot_hi_annual"],
            "months_ahead": edge["months_ahead"],
            "mean_legs_written": out["curve"]["written"].mean(),
            "min_legs_written": out["curve"]["written"].min(),
            "put_assignment_rate": stats.get("put_assignment_rate"),
            "call_assignment_rate": stats.get("call_assignment_rate"),
        })
        row = rows[-1]
        print(f"{label:36s} CAGR {row['wheel_cagr']:6.2%} vs "
              f"{row['matched_cagr']:6.2%} ({row['cagr_gap']:+6.2%}); "
              f"Sharpe {row['wheel_sharpe']:.3f} vs "
              f"{row['matched_sharpe']:.3f}; CI "
              f"[{row['bootstrap_lo']:+.1%}, {row['bootstrap_hi']:+.1%}]; "
              f"legs {row['mean_legs_written']:.1f}", flush=True)
        if label == "lagged selection":
            primary_curve = out["curve"]

    result = pd.DataFrame(rows)
    result.to_csv(OUT / "wheel_candidate.csv", index=False)
    if primary_curve is not None:
        report.yearly(primary_curve, benchmark).to_csv(
            OUT / "wheel_candidate_yearly.csv", index=False)
        report.attribution(primary_curve).to_csv(
            OUT / "wheel_candidate_attribution.csv", index=False)
    print("\nwrote H063 outputs under", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
