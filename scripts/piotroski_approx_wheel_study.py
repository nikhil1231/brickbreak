"""H070: approximate annual Piotroski 8-9 filter on the supplied stock basket."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.core import config
from src.research.families.wheel import report
from src.research.families.wheel.engine import WheelConfig, prepare, run
from src.research_data.pipelines import option_chain as oc
from src.research_data.pipelines import piotroski, piotroski_approx
from src.research_data.sources import nse_index_close as ic

OUT = config.PROJECT_ROOT / "logs" / "wheel"
SYMBOLS = {"BEL", "HAL", "SIEMENS", "ABB", "INDHOTEL", "HAVELLS",
           "JUBLFOOD"}


def execution_config() -> WheelConfig:
    base = WheelConfig(slots=len(SYMBOLS), put_otm=.10, call_otm=.10,
                       lag_selection=True, premium_column="close",
                       min_strike_contracts=250.0)
    return replace(base, costs=replace(base.costs, premium_haircut=.10))


def coverage(tape, score_panel: pd.DataFrame, cfg: WheelConfig) -> pd.DataFrame:
    rows = []
    asof = piotroski_approx.asof(score_panel, [p[0] for p in tape.pairs])
    by_entry = {pd.Timestamp(day): block.set_index("symbol")
                for day, block in asof.groupby("session")}
    for entry, _, _ in tape.pairs:
        book = tape.prior_by_session.get(entry)
        if book is None or book.empty:
            continue
        liquid = set(piotroski.eligible_symbols(
            book, premium_column=cfg.premium_column,
            min_strike_contracts=cfg.min_strike_contracts,
            min_chain_contracts=cfg.min_chain_contracts)) & SYMBOLS
        scores = by_entry.get(pd.Timestamp(entry), pd.DataFrame())
        available = {symbol for symbol in liquid
                     if symbol in scores.index
                     and pd.notna(scores.loc[symbol, "f_score_approx"])}
        high = {symbol for symbol in available
                if scores.loc[symbol, "f_score_approx"] >= 8}
        rows.append({"entry": entry, "liquid_names": len(liquid),
                     "score_available_names": len(available),
                     "high_score_names": len(high)})
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scores = piotroski_approx.load()
    prices = oc.settlement_prices()
    chain = oc.load()
    chain = chain.loc[chain["session"] <= prices["session"].max()]
    tape = prepare(chain)
    benchmark = ic.series("Nifty 50")
    cfg = execution_config()
    entries = [p[0] for p in tape.pairs]
    all_basket = {pd.Timestamp(entry): set(SYMBOLS) for entry in entries}
    high_score = piotroski_approx.eligible_map(scores, entries, minimum=8)
    high_score = {entry: names & SYMBOLS for entry, names in high_score.items()}

    cov = coverage(tape, scores, cfg)
    total = int(cov["liquid_names"].sum())
    available = int(cov["score_available_names"].sum())
    coverage_ratio = available / total if total else float("nan")
    print(f"score coverage {available}/{total} = {coverage_ratio:.1%}; "
          f"median high-score names {cov['high_score_names'].median():.1f}")

    rows = []
    for label, allowed in (
        ("seven-stock wheel, unfiltered", all_basket),
        ("H070 approximate Piotroski 8-9 wheel", high_score),
    ):
        out = run(tape, prices, cfg, eligible_by_entry=allowed)
        table = report.compare(out["curve"], benchmark, label=label)
        edge = report.edge_test(out["curve"], benchmark)
        strategy, matched = table.iloc[0], table.iloc[-1]
        rows.append({
            "series": label, "cagr": strategy["cagr"],
            "vol": strategy["vol"], "sharpe": strategy["sharpe"],
            "drawdown": strategy["max_drawdown_monthly"],
            "matched_cagr": matched["cagr"],
            "matched_sharpe": matched["sharpe"],
            "mean_positions": out["curve"]["positions"].mean(),
            "mean_written": out["curve"]["written"].mean(),
            **report.trade_stats(out["trades"]),
        })
        out["curve"].to_parquet(
            OUT / ("piotroski_approx_curve.parquet" if "H070" in label
                   else "seven_stock_curve.parquet"), index=False)
        if "H070" in label:
            edge.to_csv(OUT / "piotroski_approx_edge.csv", index=False)
        print(table.to_string(index=False), "\n")

    score_columns = ["symbol", "period_end", "available_at_approx",
                     "f_score_approx", *piotroski_approx.COMPONENTS,
                     "statement_scope", "pit_status", "score_status"]
    scores[score_columns].to_csv(OUT / "piotroski_approx_scores.csv", index=False)
    cov.to_csv(OUT / "piotroski_approx_coverage.csv", index=False)
    pd.DataFrame(rows).to_csv(OUT / "piotroski_approx_wheel.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
