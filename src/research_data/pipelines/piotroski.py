"""Feasibility gate for a point-in-time Piotroski F-score panel.

An F-score is not built from a current fundamentals snapshot. It needs two
comparable reporting periods, the original filing bytes, and the timestamp at
which each filing first became tradable. Before spending judgement on taxonomy
mapping, this module asks the cheaper question: can the local XBRL archive even
cover the stock-option rows the wheel would select from?

`archive_coverage` is deliberately an upper bound. A symbol counts as archived
when it has any successfully stored XBRL file. It does not yet require all nine
facts or a prior comparable. If this generous bound fails, a real F-score panel
cannot pass and no outcome test is licensed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..sources import xbrl


def eligible_symbols(selection_book: pd.DataFrame, *, premium_column: str,
                     min_strike_contracts: float,
                     min_chain_contracts: float) -> list[str]:
    """Replicate the wheel's pre-outcome option-liquidity eligibility."""
    live = selection_book.loc[
        (selection_book["contracts"] >= min_strike_contracts)
        & (selection_book[premium_column] > 0)]
    activity = (live.assign(
        premium_turnover=live["contracts"] * live["lot_size"]
        * live[premium_column])
        .groupby("symbol")["premium_turnover"].sum()
        .sort_values(ascending=False))
    total_contracts = selection_book.groupby("symbol")["contracts"].sum()
    return [symbol for symbol in activity.index
            if activity[symbol] > 0
            and total_contracts.get(symbol, 0.0) >= min_chain_contracts]


def archive_coverage(tape, *, premium_column: str = "close",
                     min_strike_contracts: float = 250.0,
                     min_chain_contracts: float = 500.0,
                     slots: int = 20,
                     manifest: pd.DataFrame | None = None
                     ) -> tuple[pd.DataFrame, dict]:
    """Return per-cycle coverage and its upper-bound gate summary.

    `tape` is a `PreparedWheelChain`. Only prior-session books are inspected,
    matching H063/H068's lagged selection. No settlement price or outcome is
    read here.
    """
    manifest = xbrl.load_manifest() if manifest is None else manifest
    archived = set(manifest.loc[
        manifest["status"].eq("ok") & manifest["sha256"].notna(), "symbol"])

    rows = []
    for entry, _, _ in tape.pairs:
        selection = tape.prior_by_session.get(entry)
        if selection is None or selection.empty:
            continue
        eligible = eligible_symbols(
            selection, premium_column=premium_column,
            min_strike_contracts=min_strike_contracts,
            min_chain_contracts=min_chain_contracts)
        top = eligible[:slots]
        rows.append({
            "entry": entry,
            "eligible_names": len(eligible),
            "archived_eligible_names": sum(s in archived for s in eligible),
            "top_slot_names": len(top),
            "archived_top_slot_names": sum(s in archived for s in top),
        })
    cycles = pd.DataFrame(rows)
    total = int(cycles["eligible_names"].sum()) if len(cycles) else 0
    covered = int(cycles["archived_eligible_names"].sum()) if len(cycles) else 0
    ratio = covered / total if total else float("nan")
    median_top = (float(cycles["archived_top_slot_names"].median())
                  if len(cycles) else float("nan"))
    stats = {
        "gate_kind": "generous_archive_upper_bound",
        "cycles": int(len(cycles)),
        "archive_symbols": int(len(archived)),
        "eligible_symbol_entries": total,
        "archived_eligible_symbol_entries": covered,
        "coverage_upper_bound": ratio,
        "median_archived_names_in_top_slots": median_top,
        "required_coverage": 0.80,
        "required_median_names": 10,
        "passes": bool(np.isfinite(ratio) and ratio >= .80
                       and np.isfinite(median_top) and median_top >= 10),
    }
    return cycles, stats


__all__ = ["archive_coverage", "eligible_symbols"]
