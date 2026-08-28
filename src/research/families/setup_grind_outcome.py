"""H058 outcome resolution. This is the module that crosses the seal.

Everything else in this family is outcome-free by construction. This file is the
one place that reads a bar after a decision, and it is separate so that importing
it is a deliberate act rather than a side effect of loading the deck.

The rules are not chosen here. They were registered in `setup_grind` before the
deck existed and this module transcribes them. Where the registration was silent
the gap is closed explicitly and recorded as an amendment.

REWRITTEN 2026-08-29 after review found three defects in the first version, all
in the direction that flatters the result. They are listed here because a bug
that inflates a P&L is worth a paragraph, not a line:

  * A long filled on a gap *below* its own stop booked the "stop" as a profit --
    entered at 92 with a stop at 94, exiting at 94 is +0.5R. Now the setup is
    invalidated at the fill and scores nothing.
  * A gap down *through* a stop exited at the stop price rather than the open,
    recording -1.00R where the tape only offered -3.00R.
  * The whole fill-day range was treated as post-entry, so a low printed before
    the breakout trigger counted as a stop.

The structural fix is the invariant asserted in `_check`: an outcome labelled
`stop` may never carry a positive R. That single assertion would have caught the
first defect on the day it was written.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import setup_grind


class ResolutionError(RuntimeError):
    pass


# Registered before any resolution ran: an entry that never triggers scores
# zero. No trigger means no trade and no money, and zero keeps the take paired
# with its control instead of deleting a pair whenever one leg fails to fill.
NO_FILL_R = 0.0
# A fill that is already through its own stop is not a trade a person takes. The
# setup was invalidated by the gap before entry, so it scores zero rather than a
# fabricated profit or a loss that was never risked.
INVALIDATED_R = 0.0


def continuous_futures(frame: pd.DataFrame) -> pd.DataFrame:
    """A roll-free futures path for one symbol, in fractional space.

    An 18-session hold spans a monthly roll about 86% of the time, so the raw
    near-month series is not a tradeable path: the contract change puts a step in
    it that is basis, not profit. Returns are therefore chained, and on a roll
    session the cash return stands in for the futures return, which is the part
    of that day's move a position actually earns. What survives is the real
    thing basis costs a holder -- its decay toward zero as expiry approaches --
    while the artificial step disappears.
    """
    frame = frame.sort_values("session", kind="stable").reset_index(drop=True)
    fut_close = pd.to_numeric(frame["futures_close"], errors="coerce")
    cash_close = pd.to_numeric(frame["underlying_close"], errors="coerce")
    rolled = frame["near_expiry"].ne(frame["near_expiry"].shift(1)) & frame.index.to_series().gt(0)

    ret = fut_close.pct_change()
    ret = ret.where(~rolled, cash_close.pct_change())
    index = (1.0 + ret.fillna(0.0)).cumprod()

    # Intraday extremes as ratios to the same session's close, so they ride the
    # continuous index rather than the raw contract price.
    out = pd.DataFrame({
        "session": frame["session"],
        "close": index,
        "open": index * (pd.to_numeric(frame["futures_open"], errors="coerce") / fut_close),
        "high": index * (pd.to_numeric(frame["futures_high"], errors="coerce") / fut_close),
        "low": index * (pd.to_numeric(frame["futures_low"], errors="coerce") / fut_close),
        "rolled": rolled.fillna(False),
    })
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def _check(outcome: str, r: float) -> None:
    """A stop is a loss. Asserting it is what catches a sign error in the path."""
    if outcome == "stop" and r > 0:
        raise ResolutionError(
            f"a stop-out produced {r:+.3f}R. The barrier logic is wrong; this "
            "is the assertion the first resolver did not have.")


def resolve_trade(path: pd.DataFrame, entry_off: float, stop_off: float,
                  target_off: float, *,
                  rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve one marked-up trade into an R multiple.

    `path` holds the sessions strictly after the decision bar, as fractional
    multiples of the decision-session close (so the decision close is 1.0).
    Offsets are in ATR from that close, exactly as the reviewer clicked them,
    scaled into fractions by the caller.
    """
    rules = rules or setup_grind.EXECUTION_RULES
    entry, stop, target = 1.0 + entry_off, 1.0 + stop_off, 1.0 + target_off
    if entry == stop:
        raise ResolutionError("entry and stop coincide")
    long_side = stop < entry
    # 1R is the planned risk, entry to stop, as registered. Gap slippage on the
    # fill therefore lands in the numerator, where a trader feels it, instead of
    # being hidden by rescaling the denominator.
    risk = abs(entry - stop)
    window, hold = int(rules["entry_window_sessions"]), int(rules["max_hold_sessions"])
    breakout = entry > 1.0

    fill_idx = fill_px = None
    for i in range(min(window, len(path))):
        bar = path.iloc[i]
        if breakout and bar["high"] >= entry:
            fill_idx, fill_px = i, max(float(bar["open"]), entry)
            break
        if not breakout and bar["low"] <= entry:
            fill_idx, fill_px = i, min(float(bar["open"]), entry)
            break
    if fill_idx is None:
        return {"outcome": "no_fill", "r": NO_FILL_R, "sessions_held": 0, "rolls": 0}

    # The gap that filled you may already have carried price through the stop.
    # Nobody enters a setup that is invalidated before the entry prints.
    if (long_side and fill_px <= stop) or (not long_side and fill_px >= stop):
        return {"outcome": "invalidated_at_fill", "r": INVALIDATED_R,
                "sessions_held": 0, "rolls": 0}

    held = path.iloc[fill_idx: fill_idx + hold + 1]
    rolls = int(held["rolled"].sum())
    # Every roll is a round trip of its own and is charged as one.
    cost = float(rules["cost_bps_round_trip"]) / 10_000.0 * (1 + rolls) / risk

    def done(outcome: str, exit_px: float, sessions: int) -> dict[str, Any]:
        gross = (exit_px - fill_px) if long_side else (fill_px - exit_px)
        r = gross / risk - cost
        _check(outcome, r)
        return {"outcome": outcome, "r": r, "sessions_held": sessions,
                "rolls": rolls}

    for offset, (_, bar) in enumerate(held.iterrows()):
        open_px, high, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
        through_stop = (low <= stop) if long_side else (high >= stop)
        through_target = (high >= target) if long_side else (low <= target)

        if offset > 0:
            # A gap through the stop fills at the open, not at the level. This
            # is where the first resolver understated real losses.
            gapped = (open_px <= stop) if long_side else (open_px >= stop)
            if gapped:
                return done("stop", open_px, offset + 1)
            gapped_target = (open_px >= target) if long_side else (open_px <= target)
            if gapped_target and not through_stop:
                return done("target", open_px, offset + 1)
        if through_stop:
            # A daily bar cannot order the touches, so the stop is taken -- both
            # on the fill day, where the adverse extreme may even predate the
            # entry, and on any later day where both barriers print.
            return done("stop", stop, offset + 1)
        if through_target:
            return done("target", target, offset + 1)

    return done("time_exit", float(held.iloc[-1]["close"]), len(held))


def build_pairs(marks: pd.DataFrame, private: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Pair every take with *all* of the reviewer's skips from the same session.

    The first version drew one skip at random, which made the answer depend on a
    seed, let a single skip serve several takes, and threw away most of the
    controls that had already been collected. Averaging over every same-session
    skip uses all of them, removes the seed, and lowers the variance of the
    contrast for free.

    Repeats are excluded: a second showing is the same decision, and counting it
    would double one judgement and break the independence of the pair.
    """
    frame = marks.copy()
    frame["session"] = frame["case_id"].map(lambda c: private[c]["decision_at_private"])
    frame["is_repeat"] = frame["case_id"].map(
        lambda c: bool(private[c].get("is_repeat_private")))
    frame = frame.loc[~frame["is_repeat"]]
    rows = []
    for session, group in frame.groupby("session", sort=True):
        takes = group.loc[group["action"].eq("take")]
        skips = group.loc[group["action"].eq("skip")]
        for _, take in takes.iterrows():
            rows.append({
                "session": session,
                "take_case_id": take["case_id"],
                "control_case_ids": list(skips["case_id"]),
                "entry_atr": take["entry_atr"], "stop_atr": take["stop_atr"],
                "target_atr": take["target_atr"], "conviction": take["conviction"],
            })
    return pd.DataFrame(rows)


def _paths(private: dict[str, dict[str, Any]], universe: pd.DataFrame,
           cash: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Continuous futures paths per symbol, and the cash adjustment factors.

    The futures series is raw. A split inside a hold would otherwise read as a
    catastrophic loss, so the cash `adj_factor` is carried alongside to detect
    one and exclude the case rather than let it print a number.
    """
    universe = universe.copy()
    universe["session"] = pd.to_datetime(universe["session"])
    paths = {symbol: continuous_futures(group)
             for symbol, group in universe.groupby("symbol", sort=False)}
    adj = cash[["symbol", "date", "adj_factor"]].copy()
    adj["date"] = pd.to_datetime(adj["date"])
    return paths, {s: g.sort_values("date") for s, g in adj.groupby("symbol", sort=False)}


def resolve_case(case: dict[str, Any], paths, adjustments,
                 entry_off: float, stop_off: float, target_off: float,
                 *, rules: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Resolve one case's geometry on the futures path. Reads the future."""
    rules = rules or setup_grind.EXECUTION_RULES
    symbol = case["symbol_private"]
    path = paths.get(symbol)
    if path is None:
        return None
    decision = pd.Timestamp(case["decision_at_private"])
    horizon = int(rules["horizon_sessions"])

    at_or_before = path.loc[path["session"] <= decision]
    future = path.loc[path["session"] > decision].head(horizon + 1)
    if at_or_before.empty or future.empty:
        return None
    base = float(at_or_before["close"].iloc[-1])
    if not np.isfinite(base) or base <= 0:
        return None

    # A corporate action inside the hold moves the raw futures price for reasons
    # that are not profit. Exclude rather than resolve.
    adj = adjustments.get(symbol)
    if adj is not None:
        span = adj.loc[(adj["date"] > decision)
                       & (adj["date"] <= future["session"].iloc[-1]), "adj_factor"]
        if span.nunique() > 1:
            return {"excluded": "corporate_action_in_hold"}

    scaled = future.assign(
        open=future["open"] / base, high=future["high"] / base,
        low=future["low"] / base, close=future["close"] / base)
    atr = float(case["sidecar"]["atr_rebased"]) / 100.0
    return resolve_trade(scaled, entry_off * atr, stop_off * atr,
                         target_off * atr, rules=rules)
