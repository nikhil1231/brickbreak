"""H071: supplied 30/12.5-delta bull-put spread, with/without H070 filter."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.core import config
from src.research.families.wheel import report
from src.research.families.wheel.engine import WheelConfig, prepare, run
from src.research_data.pipelines import option_chain as oc
from src.research_data.pipelines import piotroski_approx
from src.research_data.sources import nse_index_close as ic

OUT = config.PROJECT_ROOT / "logs" / "wheel"
SYMBOLS = {"BEL", "HAL", "SIEMENS", "ABB", "INDHOTEL", "HAVELLS",
           "JUBLFOOD"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    prices = oc.settlement_prices()
    chain = oc.load()
    chain = chain.loc[chain["symbol"].isin(SYMBOLS)
                      & (chain["session"] <= prices["session"].max())]
    tape = prepare(chain)
    entries = [entry for entry, _, _ in tape.pairs]
    all_names = {pd.Timestamp(entry): set(SYMBOLS) for entry in entries}
    high = piotroski_approx.eligible_map(
        piotroski_approx.load(), entries, minimum=8)
    high = {entry: names & SYMBOLS for entry, names in high.items()}
    benchmark = ic.series("Nifty 50")

    base = WheelConfig(
        slots=len(SYMBOLS), put_delta=.30, call_otm=.10,
        lag_selection=True, premium_column="close",
        min_strike_contracts=250.0)
    base = replace(base, costs=replace(base.costs, premium_haircut=.10))
    spread = replace(base, put_hedge_delta=.125)
    arms = [
        ("seven-stock 0.30-delta short-put wheel", base, all_names),
        ("seven-stock 0.30/0.125 delta spread wheel", spread, all_names),
        ("H071 score 8-9 + 0.30/0.125 spread wheel", spread, high),
    ]
    rows = []
    for label, cfg, allowed in arms:
        out = run(tape, prices, cfg, eligible_by_entry=allowed)
        table = report.compare(out["curve"], benchmark, label=label)
        edge = report.edge_test(out["curve"], benchmark)
        strategy, matched = table.iloc[0], table.iloc[-1]
        row = {
            "series": label, "cagr": strategy["cagr"],
            "vol": strategy["vol"], "sharpe": strategy["sharpe"],
            "drawdown": strategy["max_drawdown_monthly"],
            "matched_cagr": matched["cagr"],
            "matched_sharpe": matched["sharpe"],
            "mean_positions": out["curve"]["positions"].mean(),
            "mean_written": out["curve"]["written"].mean(),
            **report.trade_stats(out["trades"]),
        }
        rows.append(row)
        stem = ("mohanty_delta_combined" if "H071" in label else
                "mohanty_delta_spread" if "spread" in label else
                "mohanty_delta_short")
        out["curve"].to_parquet(OUT / f"{stem}_curve.parquet", index=False)
        edge.to_csv(OUT / f"{stem}_edge.csv", index=False)
        print("\n", table.to_string(index=False))
        print(pd.Series(report.trade_stats(out["trades"])).to_string())
    pd.DataFrame(rows).to_csv(OUT / "mohanty_delta_spread_study.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
