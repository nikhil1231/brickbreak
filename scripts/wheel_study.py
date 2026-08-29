"""Run the options-wheel study and write its tables.

One base configuration and a grid around it. The grid is not a search for the
best wheel — nothing here is promoted on the strongest cell — it is there so
that the answer can be read as "the wheel beats/loses to Nifty across this
region" rather than at one arbitrary point. The axes are chosen to be the ones
that could flip the sign: how far out the strike sits, what the spread takes,
what the collateral earns, and whether the physical-settlement fee is paid.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src.core import config
from src.research_data.pipelines import option_chain as oc
from src.research_data.sources import nse_index_close as ic
from src.research.families.wheel import report
from src.research.families.wheel.engine import CostModel, WheelConfig, prepare, run

OUT = config.PROJECT_ROOT / "logs" / "wheel"


def summarise(chain, prices, benchmark, cfg, label):
    out = run(chain, prices, cfg)
    if out["curve"].empty:
        return None, None, None
    table = report.compare(out["curve"], benchmark, label=label)
    stats = report.trade_stats(out["trades"])
    return out, table, stats


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chain = oc.load()
    prices = oc.settlement_prices()
    benchmark = ic.series("Nifty 50")
    # The cash tape ends before the option archive does; never simulate a
    # settlement we cannot price.
    last = prices["session"].max()
    chain = chain.loc[chain["session"] <= last]
    print(f"chain {len(chain):,} rows  {chain['session'].min().date()}"
          f" .. {chain['session'].max().date()}  "
          f"{chain['symbol'].nunique()} symbols", flush=True)
    chain = prepare(chain)

    base = WheelConfig()
    out, table, stats = summarise(chain, prices, benchmark, base, "wheel (base)")
    print("\n=== BASE ===")
    print(table.to_string(index=False))
    print(json.dumps(stats, indent=2))
    out["curve"].to_parquet(OUT / "wheel_base_curve.parquet", index=False)
    out["trades"].to_parquet(OUT / "wheel_base_trades.parquet", index=False)
    yearly = report.yearly(out["curve"], benchmark)
    print("\n--- calendar year, on the expiry grid ---")
    print(yearly.to_string(index=False))
    yearly.to_csv(OUT / "wheel_base_yearly.csv", index=False)

    edge = report.edge_test(out["curve"], benchmark)
    print("\n--- is the gap distinguishable from luck? ---")
    print(edge.to_string(index=False))
    edge.to_csv(OUT / "wheel_base_edge_test.csv", index=False)

    attrib = report.attribution(out["curve"])
    print("\n--- where the rupees came from (share of opening equity) ---")
    print(attrib.to_string(index=False))
    attrib.to_csv(OUT / "wheel_base_attribution.csv", index=False)

    free = CostModel(stt_option_path=(("2000-01-01", 0.0),), exchange_option=0.0,
                     sebi_fee=0.0, gst=0.0, premium_haircut=0.0,
                     stt_delivery=0.0, exchange_delivery=0.0, stamp_on_buy=0.0,
                     physical_settlement_fee=0.0)

    grid: list[tuple[str, WheelConfig]] = [
        ("frictionless ceiling", replace(base, costs=free)),
        ("no physical-settlement fee",
         replace(base, costs=replace(base.costs, physical_settlement_fee=0.0))),
        ("cash earns 0%", replace(base, cash_yield=0.0)),
        ("haircut 0%", replace(base, costs=replace(base.costs, premium_haircut=0.0))),
        ("haircut 10%", replace(base, costs=replace(base.costs, premium_haircut=0.10))),
        ("haircut 20%", replace(base, costs=replace(base.costs, premium_haircut=0.20))),
        ("strike ATM", replace(base, put_otm=0.0, call_otm=0.0)),
        ("strike 2% OTM", replace(base, put_otm=0.02, call_otm=0.02)),
        ("strike 10% OTM", replace(base, put_otm=0.10, call_otm=0.10)),
        ("5 slots", replace(base, slots=5)),
        ("20 slots", replace(base, slots=20)),
        ("call floored at basis", replace(base, call_floor_at_basis=True)),
        ("fills at last trade", replace(base, premium_column="close")),
        ("strict liquidity (250 lots)", replace(base, min_strike_contracts=250.0)),
        ("whole lots, ₹50 lakh",
         replace(base, quantise_lots=True, starting_capital=5_000_000.0,
                 costs=replace(base.costs, brokerage_per_lot_order=20.0))),
        ("whole lots, ₹2 crore",
         replace(base, quantise_lots=True, starting_capital=20_000_000.0,
                 costs=replace(base.costs, brokerage_per_lot_order=20.0))),
        ("whole lots, ₹10 crore",
         replace(base, quantise_lots=True, starting_capital=100_000_000.0,
                 costs=replace(base.costs, brokerage_per_lot_order=20.0))),
    ]

    rows = []
    for label, cfg in grid:
        _, tab, st = summarise(chain, prices, benchmark, cfg, label)
        if tab is None:
            print(f"  {label}: produced no cycles", flush=True)
            continue
        wheel = tab.iloc[0].to_dict()
        wheel.update({k: st.get(k) for k in
                      ("put_assignment_rate", "call_assignment_rate",
                       "puts_written", "premium_per_put_notional")})
        rows.append(wheel)
        print(f"  {label:32s} cagr={wheel['cagr']:7.2%} "
              f"vol={wheel['vol']:6.2%} sharpe={wheel['sharpe']:5.2f} "
              f"dd={wheel['max_drawdown_monthly']:7.2%}", flush=True)

    sens = pd.DataFrame(rows)
    sens.to_csv(OUT / "wheel_sensitivity.csv", index=False)
    print("\n=== SENSITIVITY ===")
    print(sens[["series", "cagr", "vol", "sharpe", "max_drawdown_monthly",
                "put_assignment_rate", "premium_per_put_notional"]]
          .to_string(index=False))
    table.to_csv(OUT / "wheel_base_metrics.csv", index=False)
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
