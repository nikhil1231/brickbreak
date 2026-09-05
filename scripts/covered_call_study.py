"""Backtest the weekly Nifty covered call, and the grid that decides its sign.

The base case is the strategy as posed: hold Nifty BeES, write a weekly
out-of-the-money NIFTY call against it, hold to expiry, repeat. Everything else
in the grid exists to answer "would a different reasonable choice have changed
the answer" — strike distance, tenor, spread assumption, the ETF versus the
index, and whether closing early at half the premium helps.
"""
from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd

from src.core import config
from src.research_data.pipelines import index_option_chain as ioc
from src.research_data.sources import nse_index_close as ic
from src.research.families.covered_call import report
from src.research.families.covered_call.engine import (CostModel,
                                                       CoveredCallConfig, run)

OUT = config.PROJECT_ROOT / "logs" / "covered_call"
ZERO = (("2000-01-01", 0.0),)


def market_frame() -> pd.DataFrame:
    """Sessions with the tradable proxy, the index it settles on, and its yield."""
    nifty = ic.series("Nifty 50")[["session", "close", "div_yield",
                                   "price_level", "total_level"]]
    bars = pd.read_parquet(config.NORMALIZED_DIR / "daily_bars_adj.parquet",
                           columns=["symbol", "series", "date", "close_raw"])
    bees = bars.loc[(bars["symbol"] == "NIFTYBEES") & (bars["series"] == "EQ")]
    bees = bees.rename(columns={"date": "session", "close_raw": "bees"})
    frame = nifty.merge(bees[["session", "bees"]], on="session", how="inner")
    return frame.rename(columns={"close": "index"}).sort_values(
        "session").reset_index(drop=True)


def benchmarks_for(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Levels normalised to 1.0 on the first session, on the strategy's grid."""
    base = frame.iloc[0]
    return {
        "NIFTYBEES buy & hold": frame["bees"] / base["bees"],
        "Nifty 50 (total return)": frame["total_level"] / base["total_level"],
        "Nifty 50 (price)": frame["price_level"] / base["price_level"],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chain = ioc.load()
    frame = market_frame()
    chain = chain.loc[chain["session"].isin(set(frame["session"]))]
    frame = frame.loc[frame["session"].isin(set(chain["session"]))].reset_index(
        drop=True)

    def market_for(cfg: CoveredCallConfig) -> pd.DataFrame:
        """The equity leg the config asks for: the real ETF, or the index TR.

        `index_tr` is not investable — it is here so the ETF's contribution can
        be read off as the difference between the two runs.
        """
        proxy = (frame["bees"] if cfg.proxy == "NIFTYBEES"
                 else frame["total_level"])
        return pd.DataFrame({"session": frame["session"], "proxy": proxy,
                             "index": frame["index"],
                             "div_yield": frame["div_yield"]})

    market = market_for(CoveredCallConfig())
    print(f"sessions {len(frame)}  {frame['session'].min().date()}"
          f" .. {frame['session'].max().date()}", flush=True)

    base = CoveredCallConfig()
    out = run(chain, market, base)
    curve, trades = out["curve"], out["trades"]
    bench = benchmarks_for(frame.loc[frame["session"].isin(set(curve["session"]))])

    table = report.compare(curve, bench, label="weekly CC, 0.15 delta")
    print("\n=== BASE: weekly covered call, 0.15 delta, Nifty BeES ===")
    print(table.to_string(index=False))
    print("\n--- what the overlay did ---")
    print(json.dumps(report.overlay_stats(trades, curve), indent=2))
    print("\n--- capture vs the index ---")
    print(json.dumps(report.capture(curve, bench["Nifty 50 (total return)"]),
                     indent=2))
    print("\n--- calendar year ---")
    year = report.yearly(curve, bench)
    print(year.to_string(index=False))
    print("\n--- by market regime (rolling 12m, overlapping) ---")
    regime = report.regime_table(curve, bench["Nifty 50 (total return)"])
    print(regime.to_string(index=False))

    curve.to_parquet(OUT / "base_curve.parquet", index=False)
    trades.to_parquet(OUT / "base_trades.parquet", index=False)
    table.to_csv(OUT / "base_metrics.csv", index=False)
    year.to_csv(OUT / "base_yearly.csv", index=False)
    regime.to_csv(OUT / "base_regime.csv", index=False)

    free = CostModel(stt_option_path=ZERO, exchange_option_path=ZERO,
                     sebi_fee=0.0, gst=0.0, premium_haircut=0.0,
                     etf_stt_sale=0.0, etf_exchange=0.0, etf_stamp_buy=0.0,
                     stamp_option_buy=0.0)

    grid: list[tuple[str, CoveredCallConfig]] = [
        ("weekly 0.10 delta", replace(base, target_delta=0.10)),
        ("weekly 0.15 delta (base)", base),
        ("weekly 0.20 delta", replace(base, target_delta=0.20)),
        ("weekly 0.30 delta", replace(base, target_delta=0.30)),
        ("weekly 0.45 delta (near ATM)", replace(base, target_delta=0.45)),
        ("weekly 1% OTM", replace(base, strike_rule="otm", otm=0.01)),
        ("weekly 2% OTM", replace(base, strike_rule="otm", otm=0.02)),
        ("weekly 3% OTM", replace(base, strike_rule="otm", otm=0.03)),
        ("monthly 0.15 delta", replace(base, cadence="monthly")),
        ("monthly 0.30 delta", replace(base, cadence="monthly",
                                       target_delta=0.30)),
        ("monthly 2% OTM", replace(base, cadence="monthly", strike_rule="otm",
                                   otm=0.02)),
        ("weekly, on index TR not ETF", replace(base, proxy="index_tr")),
        ("weekly, no spread cost",
         replace(base, costs=replace(base.costs, premium_haircut=0.0))),
        ("weekly, 2% spread cost",
         replace(base, costs=replace(base.costs, premium_haircut=0.02))),
        ("weekly, 5% spread cost",
         replace(base, costs=replace(base.costs, premium_haircut=0.05))),
        ("weekly, frictionless ceiling", replace(base, costs=free)),
        ("weekly, fills at last trade", replace(base, premium_column="close")),
        ("weekly, close at 50% profit", replace(base, profit_take=0.50)),
        ("weekly, no funding cost", replace(base, funding_spread=0.0)),
        ("whole lots, ₹20 lakh",
         replace(base, quantise_lots=True, starting_capital=2_000_000.0,
                 costs=replace(base.costs, brokerage_per_order=20.0))),
        ("whole lots, ₹50 lakh",
         replace(base, quantise_lots=True, starting_capital=5_000_000.0,
                 costs=replace(base.costs, brokerage_per_order=20.0))),
        ("whole lots, ₹2 crore",
         replace(base, quantise_lots=True, starting_capital=20_000_000.0,
                 costs=replace(base.costs, brokerage_per_order=20.0))),
    ]

    rows = []
    for label, cfg in grid:
        result = run(chain, market_for(cfg), cfg)
        if result["curve"].empty:
            print(f"  {label}: no cycles", flush=True)
            continue
        sub_bench = benchmarks_for(
            frame.loc[frame["session"].isin(set(result["curve"]["session"]))])
        tab = report.compare(result["curve"], sub_bench, label=label)
        row = tab.iloc[0].to_dict()
        row.update(report.overlay_stats(result["trades"], result["curve"]))
        row["vs_bees_cagr"] = row["cagr"] - tab.loc[
            tab["series"] == "NIFTYBEES buy & hold", "cagr"].iloc[0]
        rows.append(row)
        print(f"  {label:32s} cagr={row['cagr']:7.2%} "
              f"vs BeES={row['vs_bees_cagr']:+7.2%} vol={row['vol']:6.2%} "
              f"sharpe={row['sharpe']:5.2f} dd={row['max_drawdown']:7.2%}",
              flush=True)

    sens = pd.DataFrame(rows)
    sens.to_csv(OUT / "sensitivity.csv", index=False)
    print("\n=== SENSITIVITY ===")
    print(sens[["series", "cagr", "vs_bees_cagr", "vol", "sharpe",
                "max_drawdown", "pct_finished_itm", "annualised_premium_pct",
                "total_upside_given_up_pct"]].to_string(index=False))
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
