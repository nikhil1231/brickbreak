"""H058 outcome resolution. This is the module that crosses the seal.

Everything else in this family is outcome-free by construction. This file is
the one place that reads a bar after a decision, and it is separate so that
importing it is a deliberate act rather than a side effect of loading the deck.

The rules it implements are not chosen here. They were registered in
`setup_grind.EXECUTION_RULES` and `setup_grind.ANALYSIS_PLAN` before the deck
existed, and this module is a transcription of them. Where the registration was
silent -- what an unfilled entry scores -- the gap is closed explicitly below and
recorded as an amendment, before any resolution was run.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import setup_grind


class ResolutionError(RuntimeError):
    pass


# The registration says an unfilled entry is "recorded, not dropped silently"
# but does not say what it scores. It scores zero: no trigger means no trade and
# no money, and zero keeps the take paired with its control instead of deleting
# a pair whenever one leg happens not to fill. Fixed before any resolution ran.
NO_FILL_R = 0.0


def resolve_trade(future: pd.DataFrame, last_close: float, atr_pct: float,
                  entry_off: float, stop_off: float, target_off: float,
                  *, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve one marked-up trade into an R multiple.

    `future` holds the sessions strictly after the decision bar, in order.
    Offsets are in ATR from the last close, exactly as the reviewer clicked
    them, and `atr_pct` is that ATR as a percentage of the same close.
    """
    rules = rules or setup_grind.EXECUTION_RULES
    scale = atr_pct / 100.0
    entry = last_close * (1.0 + entry_off * scale)
    stop = last_close * (1.0 + stop_off * scale)
    target = last_close * (1.0 + target_off * scale)
    if not np.isfinite([entry, stop, target]).all() or entry == stop:
        raise ResolutionError("degenerate geometry")
    long_side = stop < entry
    # 1R is the planned risk, entry to stop, as registered. Gap slippage on the
    # fill therefore shows up in the numerator, where a trader would feel it,
    # rather than being hidden by rescaling the denominator.
    risk = abs(entry - stop)

    window = int(rules["entry_window_sessions"])
    hold = int(rules["max_hold_sessions"])
    breakout = entry > last_close

    fill_idx, fill_px = None, None
    for i in range(min(window, len(future))):
        bar = future.iloc[i]
        if breakout and bar["high"] >= entry:
            # A gap through the level fills at the open, which is the worse
            # price for a breakout entry and the one that actually happens.
            fill_idx, fill_px = i, max(float(bar["open"]), entry)
            break
        if not breakout and bar["low"] <= entry:
            fill_idx, fill_px = i, min(float(bar["open"]), entry)
            break
    if fill_idx is None:
        return {"outcome": "no_fill", "r": NO_FILL_R, "sessions_held": 0}

    cost_r = float(rules["cost_bps_round_trip"]) / 10_000.0 * fill_px / risk
    path = future.iloc[fill_idx: fill_idx + hold + 1]
    for offset, (_, bar) in enumerate(path.iterrows()):
        hit_stop = (bar["low"] <= stop) if long_side else (bar["high"] >= stop)
        hit_target = (bar["high"] >= target) if long_side else (bar["low"] <= target)
        # The fill bar itself is included: a level touched intraday after the
        # fill counts, and when both are touched in one session the daily bar
        # cannot say which came first, so the registered rule takes the stop.
        if hit_stop and hit_target:
            hit_target = False        # registered: the stop is taken
        if hit_stop or hit_target:
            exit_px = stop if hit_stop else target
            gross = (exit_px - fill_px) if long_side else (fill_px - exit_px)
            return {"outcome": "stop" if hit_stop else "target",
                    "r": gross / risk - cost_r, "sessions_held": offset + 1}
    exit_px = float(path.iloc[-1]["close"])
    gross = (exit_px - fill_px) if long_side else (fill_px - exit_px)
    return {"outcome": "time_exit", "r": gross / risk - cost_r,
            "sessions_held": len(path)}


def build_pairs(marks: pd.DataFrame, private: dict[str, dict[str, Any]],
                *, seed: int) -> pd.DataFrame:
    """Pair every take with one of the reviewer's own skips from that session.

    Repeats are excluded: a second showing is the same decision, and counting it
    would double one judgement and break the independence of the pair.
    """
    rng = np.random.default_rng(seed)
    rows = []
    frame = marks.copy()
    frame["session"] = frame["case_id"].map(
        lambda c: private[c]["decision_at_private"])
    frame["is_repeat"] = frame["case_id"].map(
        lambda c: bool(private[c].get("is_repeat_private")))
    frame = frame.loc[~frame["is_repeat"]]
    for session, group in frame.groupby("session", sort=True):
        takes = group.loc[group["action"].eq("take")]
        skips = group.loc[group["action"].eq("skip")]
        if takes.empty or skips.empty:
            continue
        for _, take in takes.iterrows():
            control = skips.iloc[int(rng.integers(len(skips)))]
            rows.append({"session": session,
                         "take_case_id": take["case_id"],
                         "control_case_id": control["case_id"],
                         "entry_atr": take["entry_atr"],
                         "stop_atr": take["stop_atr"],
                         "target_atr": take["target_atr"],
                         "conviction": take["conviction"]})
    return pd.DataFrame(rows)


def resolve_pairs(pairs: pd.DataFrame, private: dict[str, dict[str, Any]],
                  bars: pd.DataFrame) -> pd.DataFrame:
    """Resolve both legs of every pair. This reads bars after the decision."""
    setup_grind.assert_session_aligned(bars, context="H058 resolution")
    history = {symbol: group.sort_values("date", kind="stable")
               for symbol, group in bars.groupby("symbol", sort=False)}
    out = []
    for _, pair in pairs.iterrows():
        legs = {}
        for role in ("take", "control"):
            case = private[pair[f"{role}_case_id"]]
            frame = history.get(case["symbol_private"])
            if frame is None:
                legs = {}
                break
            decision = pd.Timestamp(case["decision_at_private"])
            future = frame.loc[pd.to_datetime(frame["date"]) > decision]
            past = frame.loc[pd.to_datetime(frame["date"]) <= decision]
            if past.empty or future.empty:
                legs = {}
                break
            legs[role] = resolve_trade(
                future, float(past["close"].iloc[-1]),
                float(case["sidecar"]["atr_rebased"]),
                float(pair["entry_atr"]), float(pair["stop_atr"]),
                float(pair["target_atr"]))
        if not legs:
            continue
        out.append({**pair.to_dict(),
                    "take_r": legs["take"]["r"],
                    "control_r": legs["control"]["r"],
                    "take_outcome": legs["take"]["outcome"],
                    "control_outcome": legs["control"]["outcome"],
                    "difference_r": legs["take"]["r"] - legs["control"]["r"]})
    return pd.DataFrame(out)
