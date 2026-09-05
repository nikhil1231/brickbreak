"""Approximate annual Piotroski scores for H070; never claim PIT from these."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..sources import screener_fundamentals as sf

COMPONENTS = (
    "f_roa", "f_cfo", "f_delta_roa", "f_accrual", "f_delta_leverage",
    "f_delta_liquidity_proxy", "f_no_equity_issue",
    "f_delta_operating_margin_proxy", "f_delta_asset_turnover",
)


def score(financials: pd.DataFrame) -> pd.DataFrame:
    """Calculate nine directions, with the three H070 proxies kept visible."""
    required = {
        "symbol", "period_end", "sales", "operating_profit", "net_income",
        "total_assets", "borrowings", "other_assets", "other_liabilities",
        "equity_capital", "operating_cash_flow", "pit_status",
    }
    if missing := required - set(financials.columns):
        raise ValueError(f"approximate fundamentals missing {sorted(missing)}")
    groups = []
    for symbol, block in financials.groupby("symbol", sort=False):
        out = block.sort_values("period_end").copy()
        prior_assets = out["total_assets"].shift()
        average_assets = (out["total_assets"] + prior_assets) / 2.0
        roa = out["net_income"] / average_assets
        prior_roa = roa.shift()
        leverage = out["borrowings"] / out["total_assets"]
        liquidity = out["other_assets"] / out["other_liabilities"]
        margin = out["operating_profit"] / out["sales"]
        turnover = out["sales"] / average_assets
        flags = {
            "f_roa": roa > 0,
            "f_cfo": out["operating_cash_flow"] > 0,
            "f_delta_roa": roa > prior_roa,
            "f_accrual": out["operating_cash_flow"] > out["net_income"],
            "f_delta_leverage": leverage < leverage.shift(),
            "f_delta_liquidity_proxy": liquidity > liquidity.shift(),
            "f_no_equity_issue": out["equity_capital"]
                                 <= out["equity_capital"].shift(),
            "f_delta_operating_margin_proxy": margin > margin.shift(),
            "f_delta_asset_turnover": turnover > turnover.shift(),
        }
        complete = out[[
            "sales", "operating_profit", "net_income", "total_assets",
            "borrowings", "other_assets", "other_liabilities",
            "equity_capital", "operating_cash_flow",
        ]].notna().all(axis=1) & prior_assets.notna() & prior_roa.notna()
        for name, values in flags.items():
            out[name] = values.astype("Int8").where(complete)
        out["f_score_approx"] = out[list(COMPONENTS)].sum(
            axis=1, min_count=len(COMPONENTS)).astype("Int8")
        out["available_at_approx"] = (
            pd.to_datetime(out["period_end"]) + pd.DateOffset(months=6))
        out["score_status"] = (
            "approximate_current_restated_history; six_month_availability_lag")
        groups.append(out)
    return pd.concat(groups, ignore_index=True)


def load() -> pd.DataFrame:
    return score(sf.load())


def asof(scores: pd.DataFrame, sessions) -> pd.DataFrame:
    """Latest approximate annual score available for each symbol/session."""
    stamps = pd.Series(pd.to_datetime(pd.Index(sessions).unique()), name="session")
    symbols = scores["symbol"].dropna().unique()
    wanted = pd.MultiIndex.from_product(
        [symbols, stamps.sort_values()], names=["symbol", "session"]
    ).to_frame(index=False)
    parts = []
    for symbol, left in wanted.groupby("symbol", sort=False):
        right = scores.loc[scores["symbol"] == symbol].dropna(
            subset=["f_score_approx"]).sort_values("available_at_approx")
        merged = pd.merge_asof(
            left.sort_values("session"), right,
            left_on="session", right_on="available_at_approx",
            direction="backward", suffixes=("", "_score"))
        merged["symbol"] = symbol
        parts.append(merged)
    return pd.concat(parts, ignore_index=True)


def eligible_map(scores: pd.DataFrame, sessions,
                 minimum: int = 8) -> dict[pd.Timestamp, set[str]]:
    panel = asof(scores, sessions)
    panel = panel.loc[panel["f_score_approx"] >= minimum]
    return {pd.Timestamp(session): set(block["symbol"])
            for session, block in panel.groupby("session")}


__all__ = ["COMPONENTS", "asof", "eligible_map", "load", "score"]
