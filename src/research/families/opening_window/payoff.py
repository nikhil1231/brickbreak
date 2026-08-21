"""The strategy's actual payoff, bracketed — not a fixed-horizon return.

WHY THIS EXISTS
Everything up to here asked "if I buy at 09:20, what is the excess return at
D+5". That is not this strategy's payoff. The stated rule is

    enter → stop below the running low → +15-20% target → sell half
          → stop to breakeven → trail the rest on the 10-EMA

and those are different functions of the same price path. They can disagree in
*sign* on the same trades: if most setups drift to -3% by D+5 but the stop takes
them out at -1%, and a minority reach +18%, fill the target, then give it back
by D+5, the fixed-horizon label says the strategy loses while the traded rule
makes money. Every negative result in H001, H002, H009 and H013 is subject to
that, and none of them is a verdict on the strategy as traded. See H017.

WHY THIS PRODUCES A BRACKET RATHER THAN A NUMBER
A daily bar records a high and a low and not their order. On a session where
both the stop and the target were touched, the outcome is genuinely
undetermined by the data — the same bar is a winner if the target filled first
and a loser if the stop did. So the simulation runs twice, resolving every
ambiguity first in the trade's favour and then against it, and reports both. The
truth lies between.

That width is the whole point. **If the bracket is narrow, the question is
settled without the full-session intraday pull. If it is wide, the width is
exactly what the pull would buy** — and H006 has been the standing justification
for that pull without anyone measuring how much it is worth.

THE ENTRY DAY, WHICH IS NOT AS UNUSABLE AS IT LOOKS
The entry day's daily high and low include 09:15-09:20, before the position
exists. Pairing those with a 09:20 entry is exactly the H004 error, which is why
`labelling.py` offers clean `mfe_*` from D+1 and contaminated `*_incl_d0` twins.
But dropping the entry day understates stop-outs badly — a stop 2% below entry
is very often hit the same afternoon — and that biases the payoff upward.

The 1-second panel closes this exactly. `low_D <= low_t` always, because the
window is part of the day. So:

- `low_D < low_t` → the day's low came **after** entry; the post-entry low is
  `low_D`, and this is certain, not assumed;
- `low_D == low_t` → the low happened **inside** the window, so price never
  traded below `low_t` after entry; and since `stop < low_t` by construction,
  the stop certainly was **not** hit on the entry day.

Symmetrically for the high and the target. The entry-day afternoon is therefore
fully usable for touch detection, with no ambiguity introduced and none assumed
away. This is a strict improvement on the `*_incl_d0` twins.

GAP-THROUGH, WITHOUT WHICH THE STOP IS FICTION
A stop is not a fill. A session that opens below the stop fills at the open, and
on this pool that is where much of the loss actually lives. Every level here —
initial stop, target, breakeven stop — is checked against the session's open
first and filled there when the open has already passed it.

WHAT THIS IS NOT
Not a backtest. There is no position sizing, no capital constraint, no
sequencing across overlapping trades, no costs, and no slippage beyond the gap
logic. It answers one question: on these trades, does the traded payoff disagree
with the fixed-horizon label, and by how much.

THE SIMULATOR ITSELF NOW LIVES IN `alpha_eval.trade_sim`
It was extracted there on 2026-08-22 because the question it answers — *a
fixed-horizon label is not a strategy's payoff* — is not specific to this
family, and the discretionary lab needs it for any decision that names its own
entry and stop. This module is now the family's binding of it: the opening
window supplies `running_low_t` / `running_high_t`, so it uses
`entry_timing="intraday_window"`, which is what makes the entry day exact here.

Everything below is a thin wrapper. The numbers are unchanged, and
`tests/test_trade_sim.py` pins them against the extracted implementation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ....alpha_eval import trade_sim
from ....alpha_eval.trade_sim import (
    OPEN_AT_END,
    STOP,
    STOP_GAP,
    TARGET_THEN_BREAKEVEN,
    TARGET_THEN_TRAIL,
    TIMEOUT,
    TRAIL,
    daily_market_return,
)

# The opening window is what makes this family's entry day exact (see the
# module docstring, and `trade_sim._entry_day_extremes`).
ENTRY_TIMING = "intraday_window"

# The stated rule, made executable. Every field is the uncle's, not tuned.
# `BracketRule` is the general object; this alias is what the family's callers
# and its recorded measurements refer to.
PayoffConfig = trade_sim.BracketRule


def _symbol_arrays(bars: pd.DataFrame, cfg: PayoffConfig) -> dict:
    return trade_sim._symbol_arrays(bars, cfg)


def _simulate_one(a: dict, i0: int, entry: float, stop: float,
                  d0_low: float, d0_high: float,
                  cfg: PayoffConfig, optimistic: bool) -> tuple:
    return trade_sim._simulate_one(a, i0, entry, stop, d0_low, d0_high,
                                   cfg, optimistic)


def simulate(trades: pd.DataFrame, bars: pd.DataFrame,
             cfg: PayoffConfig | None = None, optimistic: bool = False,
             verbose: bool = True) -> pd.DataFrame:
    """Run the rule over every trade. One row in, one row out.

    `trades` needs `symbol`, `date`, `entry_px_adj`, `stop_px_adj`, and the
    opening-window extremes `running_low_t` / `running_high_t` on the same
    adjusted basis, so the entry day can be resolved exactly.
    """
    return trade_sim.simulate(trades, bars, rule=cfg, optimistic=optimistic,
                              entry_timing=ENTRY_TIMING, verbose=verbose)


def attach_benchmark(sim: pd.DataFrame, bars: pd.DataFrame,
                     cfg: PayoffConfig | None = None,
                     min_symbols: int = 50) -> pd.DataFrame:
    """Compound the equal-weighted market over each trade's own holding window."""
    return trade_sim.attach_benchmark(sim, bars, rule=cfg,
                                      min_symbols=min_symbols)


def bracket(trades: pd.DataFrame, bars: pd.DataFrame,
            cfg: PayoffConfig | None = None, verbose: bool = True) -> tuple:
    """Both orderings, and the width between them.

    The width is the answer to "what would the intraday pull buy": it is the
    part of the expectancy that the data on hand genuinely cannot determine.
    """
    out, pes, opt = trade_sim.bracket(trades, bars, rule=cfg,
                                      entry_timing=ENTRY_TIMING, verbose=verbose)
    # This family's recorded results name the field `config`, not `rule`.
    out["config"] = out.pop("rule")
    return out, pes, opt


def compare_to_fixed_horizon(pes: pd.DataFrame, opt: pd.DataFrame,
                             horizon: int = 5) -> pd.DataFrame:
    """The H017 question, in one table: do the two labels disagree, and where.

    Reports the fixed-horizon excess return and the payoff excess return on the
    **identical** trades, so any difference is the label and not the sample.
    """
    from .explore import cluster_stats
    col = f"excess_ret_{horizon}d_pct"
    rows = []
    for name, d in (("fixed_horizon", pes), ("payoff_pessimistic", pes),
                    ("payoff_optimistic", opt)):
        y = d[col] if name == "fixed_horizon" else d["payoff_excess_pct"]
        s = cluster_stats(y, d["date"])
        s["label"] = name
        rows.append(s)
    return pd.DataFrame(rows)[["label", "n", "n_dates", "mean", "median",
                               "hit_pct", "t", "naive_t"]]
