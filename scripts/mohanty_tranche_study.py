"""H069: test the user-supplied 33/33/34 staggered covered-call method."""
from __future__ import annotations

import pandas as pd

from src.core import config
from src.research.families.covered_call import report
from src.research.families.wheel.engine import prepare
from src.research.families.wheel.mohanty import TrancheConfig, run
from src.research_data.pipelines import option_chain as oc
from src.research_data.sources import nse_index_close as ic

OUT = config.PROJECT_ROOT / "logs" / "wheel"
SYMBOLS = ("BEL", "HAL", "SIEMENS", "ABB", "INDHOTEL", "HAVELLS",
           "JUBLFOOD")


def benchmarks(curve: pd.DataFrame, prices: pd.DataFrame,
               control: pd.DataFrame | None = None) -> dict[str, pd.Series]:
    nifty = ic.series("Nifty 50").sort_values("session")
    wanted = curve[["session"]].sort_values("session")
    aligned = pd.merge_asof(
        wanted, nifty[["session", "price_level", "total_level"]],
        on="session", direction="backward")
    daily = prices.copy()
    daily["adjusted"] = daily["price"] * daily["adj_factor"]
    basket = daily.pivot(index="session", columns="symbol", values="adjusted")
    basket = basket.reindex(pd.DatetimeIndex(curve["session"])).ffill()
    basket = basket.divide(basket.iloc[0]).mean(axis=1).reset_index(drop=True)
    out = {
        "seven-stock equal-weight price return": basket,
        "Nifty 50 (total return)": (aligned["total_level"]
                                    / aligned["total_level"].iloc[0]),
        "Nifty 50 (price)": (aligned["price_level"]
                             / aligned["price_level"].iloc[0]),
    }
    if control is not None:
        level = control.set_index("session")["equity"].reindex(
            pd.DatetimeIndex(curve["session"])).ffill().reset_index(drop=True)
        out["full-funded covered-call control"] = level / level.iloc[0]
    return out


def stats(trades: pd.DataFrame, curve: pd.DataFrame) -> dict:
    writes = trades.loc[trades["kind"] == "call_write"]
    assignments = trades.loc[trades["kind"] == "call_assignment"]
    buys = trades.loc[trades["kind"] == "stock_buy"]
    return {
        "calls_written": len(writes), "calls_assigned": len(assignments),
        "assignment_rate": len(assignments) / len(writes) if len(writes) else None,
        "initial_buys": int((buys["reason"] == "initial").sum()),
        "midpoint_buys": int((buys["reason"] == "midpoint").sum()),
        "strike_buys": int((buys["reason"] == "strike").sum()),
        "terminal_cover_buys": int((buys["reason"] == "terminal_cover").sum()),
        "peak_uncovered_pct": float(curve["uncovered_pct"].max()),
        "peak_uncovered_pct_equity": float(
            curve["uncovered_pct_equity"].max()),
        "peak_funding_pct": float(curve["funding_pct"].min()),
        "mean_equity_exposure": float((curve["shares"] / curve["equity"]).mean()),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    columns = ["session", "symbol", "expiry", "strike", "option_type",
               "settle", "close", "contracts", "lot_size", "underlying",
               "adj_factor"]
    chain = oc.load(columns=columns)
    chain = chain.loc[chain["symbol"].isin(SYMBOLS)].reset_index(drop=True)
    prices = oc.settlement_prices()
    prices = prices.loc[prices["symbol"].isin(SYMBOLS)].reset_index(drop=True)
    chain = chain.loc[chain["session"] <= prices["session"].max()]
    tape = prepare(chain)
    cfg = TrancheConfig(symbols=SYMBOLS)

    rows = []
    full_curve = None
    for label, staged in (
        ("full funded seven-stock covered call", False),
        ("H069 33-33-34 staggered covered call", True),
    ):
        out = run(chain, prices, tape, cfg, staged=staged)
        curve, trades = out["curve"], out["trades"]
        bench = benchmarks(curve, prices, control=full_curve if staged else None)
        table = report.compare(curve, bench, label=label)
        edge = report.edge_test(curve, bench)
        strategy, matched = table.iloc[0], table.iloc[-1]
        row = {**strategy.to_dict(),
               "matched_cagr": matched["cagr"],
               "matched_sharpe": matched["sharpe"],
               **stats(trades, curve)}
        rows.append(row)
        if not staged:
            full_curve = curve
        stem = "mohanty_staged" if staged else "mohanty_full_control"
        curve.to_parquet(OUT / f"{stem}_curve.parquet", index=False)
        trades.to_parquet(OUT / f"{stem}_trades.parquet", index=False)
        table.to_csv(OUT / f"{stem}_metrics.csv", index=False)
        edge.to_csv(OUT / f"{stem}_edge.csv", index=False)
        print("\n", table.to_string(index=False))
        print(pd.Series(stats(trades, curve)).to_string())
    pd.DataFrame(rows).to_csv(OUT / "mohanty_tranche_study.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
