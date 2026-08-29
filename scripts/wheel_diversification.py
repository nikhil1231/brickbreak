"""H062: map the diversification/strike neighborhood left by H061."""
from __future__ import annotations

from dataclasses import replace
from itertools import product

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

    base = WheelConfig()
    configs: list[tuple[str, WheelConfig]] = [
        (f"fractional s={slots} otm={otm:.0%}",
         replace(base, slots=slots, put_otm=otm, call_otm=otm))
        for slots, otm in product((20, 30, 40), (0.05, 0.10, 0.15))
    ]
    configs.extend(
        (f"whole lots s=20 capital={capital / 10_000_000:.1f}cr",
         replace(base, slots=20, quantise_lots=True,
                 starting_capital=capital,
                 costs=replace(base.costs, brokerage_per_lot_order=20.0)))
        for capital in (5_000_000.0, 20_000_000.0, 100_000_000.0)
    )

    rows = []
    for label, wheel_cfg in configs:
        out = run(tape, prices, wheel_cfg)
        table = report.compare(out["curve"], benchmark, label=label)
        wheel = table.iloc[0]
        matched = table.iloc[-1]
        test = report.edge_test(out["curve"], benchmark)
        matched_test = test.loc[
            test["versus"] == "Nifty TR, volatility-matched"].iloc[0]
        stats = report.trade_stats(out["trades"])
        row = {
            "series": label,
            "slots": wheel_cfg.slots,
            "otm": wheel_cfg.put_otm,
            "capital": wheel_cfg.starting_capital,
            "whole_lots": wheel_cfg.quantise_lots,
            "wheel_cagr": wheel["cagr"],
            "matched_cagr": matched["cagr"],
            "cagr_gap": wheel["cagr"] - matched["cagr"],
            "wheel_sharpe": wheel["sharpe"],
            "matched_sharpe": matched["sharpe"],
            "sharpe_gap": wheel["sharpe"] - matched["sharpe"],
            "wheel_vol": wheel["vol"],
            "wheel_drawdown": wheel["max_drawdown_monthly"],
            "annualised_mean_gap": matched_test["annualised_gap"],
            "bootstrap_lo": matched_test["boot_lo_annual"],
            "bootstrap_hi": matched_test["boot_hi_annual"],
            "puts": stats.get("puts_written"),
            "put_assignment_rate": stats.get("put_assignment_rate"),
            "mean_legs_written": out["curve"]["written"].mean(),
            "min_legs_written": out["curve"]["written"].min(),
            "early_expiry_exclusions": out["curve"][
                "early_expiry_exclusions"].sum(),
        }
        rows.append(row)
        print(f"{label:38s} CAGR {row['wheel_cagr']:6.2%} vs "
              f"{row['matched_cagr']:6.2%} ({row['cagr_gap']:+6.2%}); "
              f"Sharpe {row['wheel_sharpe']:.3f} vs "
              f"{row['matched_sharpe']:.3f}; legs "
              f"{row['mean_legs_written']:.1f}", flush=True)

    result = pd.DataFrame(rows)
    result.to_csv(OUT / "wheel_diversification.csv", index=False)
    print("\nwrote", OUT / "wheel_diversification.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
