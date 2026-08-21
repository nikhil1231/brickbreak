"""What was actually knowable at 09:20 on the morning being traded.

WHY THIS EXISTS
The screener gated on indicators computed from date D's own close, and the
entry is at 09:20 on date D. Every candidate morning was therefore selected
using about six hours of information from after the entry. `require_above_ema_mid`
alone meant **every candidate morning was a session that closed above its 50-day
EMA**. Recorded as H015.

THE MECHANISM THAT MAKES THIS WORSE THAN AN ORDINARY LOOKAHEAD
An ordinary lookahead inflates a result. This one can *invert* it.

The contraction filters (`atr_ratio`, `bb_width_pctile`, `base_depth`,
`range_pct_ma`) all read date D's own high and low, so a candidate morning is
required to have been a **quiet day**. Now consider a morning with genuine
persistent buying:

- if it keeps running all day, day D's range is wide, contraction fails, and the
  morning is **excluded from the pool**;
- if the opening demand fades back into a narrow range, contraction passes and
  the morning is **kept**.

The pool therefore retains the persistent-demand mornings that died and discards
the ones that worked. That is enough to manufacture "sustained opening demand
predicts poor returns" out of a strategy in which sustained demand is good — and
it is exactly the inversion Phase 2.5 reported. The effect is concentrated in
the entry-day segment (roughly two thirds of it), which is the segment the
screen conditions on. See the Phase 2.5 addendum in `FINDINGS.md`.

WHAT IS KNOWN AT 09:20 ON DATE D, AND WHAT IS NOT
Known: everything through date D-1's close, plus date D's **opening print**,
which comes from the 09:15:00 pre-open call auction and is on the tape before
the entry. The previous close is known for the same reason.

Not known: date D's close, high, low, whole-day volume, turnover and delivery
percentage — and therefore every indicator derived from them.

The split is applied by column here rather than by a blanket `shift`, because
the two legitimate exceptions matter: lagging `open_raw` would break `gap_pct`
(the gap a trader sees is date D's opening print against date D-1's close), and
lagging it silently would replace a real feature with a stale one.

WHY A SHIFT AND NOT A DATE JOIN
`groupby("symbol").shift(1)` over a date-sorted panel gives each row the values
from that symbol's **previous trading session**, which is what "the last close I
could have seen" means. A calendar-date join would silently produce NaN across
weekends and holidays, and worse, would pick the wrong row for a symbol that was
suspended.

WHAT THIS MODULE DOES NOT FIX
The pool of mornings for which 1-second ticks exist was chosen by the
contaminated screen. Re-lagging the indicators changes which mornings the screen
*would* pick, but it cannot conjure tick data for mornings that were never
pulled. Closing that gap needs a re-pull, which is what `cli.py work-list` and
`scripts/server_pull.py` are for.
"""
from __future__ import annotations

import pandas as pd

# Everything on a candidate row that is derived from date D's own session and
# therefore cannot be seen at 09:20. Any column added to the metrics panel in
# future defaults to this list via `lag_columns(...)`, which lags whatever it
# does not recognise as knowable.
KNOWN_AT_OPEN = frozenset({
    # identity and static metadata
    "symbol", "date", "series", "sector", "size_tier", "size_tier_rank", "is_etf",
    # date D's opening print: the 09:15:00 pre-open auction, on the tape before
    # the 09:20 entry. This is the one date-D price a morning rule may use.
    "open", "open_raw",
    # date D-1's close, carried on the date-D row by construction.
    "prev_close", "prev_close_raw",
    # the corporate-action factor for date D, which is published in advance.
    "adj_factor",
})


def lag_columns(df: pd.DataFrame, sessions: int = 1,
                known: frozenset[str] = KNOWN_AT_OPEN,
                suffix: str = "") -> pd.DataFrame:
    """Replace every date-D-derived column with its value `sessions` bars earlier.

    Anything not explicitly listed as knowable at the open is lagged. That
    default is deliberately the safe direction: a column nobody has thought
    about is treated as unknown, so adding a new indicator cannot silently
    reintroduce the lookahead. Making a column knowable is an explicit act.
    """
    if sessions <= 0:
        return df
    d = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    cols = [c for c in d.columns if c not in known]
    if not cols:
        return d
    lagged = d.groupby("symbol", sort=False)[cols].shift(sessions)
    if suffix:
        return d.join(lagged.add_suffix(suffix))
    d[cols] = lagged
    return d


def audit(df: pd.DataFrame, lagged: pd.DataFrame, sample_symbol: str | None = None
          ) -> dict:
    """Prove the lag actually moved the values, and that it moved them backwards.

    A shift that silently no-ops — wrong sort order, a grouping key that is not
    the symbol — looks exactly like a shift that worked, and the screen would go
    on selecting on the future. This compares the two frames directly and
    reports how many rows changed, so "it is lagged now" is a measurement.
    """
    key = ["symbol", "date"]
    j = df.merge(lagged, on=key, suffixes=("_raw", "_lag"))
    out: dict = {"rows": int(len(j)), "columns": {}}
    for c in ("close", "ema_mid", "px_vs_ema_mid", "ret_20d", "atr_ratio",
              "bb_width_pctile", "deliv_pct", "above_ema_mid"):
        a, b = f"{c}_raw", f"{c}_lag"
        if a not in j or b not in j:
            continue
        both = j[a].notna() & j[b].notna()
        out["columns"][c] = {
            "compared": int(both.sum()),
            "differing": int((j.loc[both, a] != j.loc[both, b]).sum()),
        }
    # The lagged value on date D must equal the unlagged value on the symbol's
    # previous session. Checked directly on one symbol rather than inferred.
    if sample_symbol:
        a = df[df["symbol"] == sample_symbol].sort_values("date")
        b = lagged[lagged["symbol"] == sample_symbol].sort_values("date")
        if len(a) > 3 and "close" in a:
            out["spot_check"] = {
                "symbol": sample_symbol,
                "date": str(b["date"].iloc[3].date()),
                "lagged_close": float(b["close"].iloc[3]),
                "prev_session_close": float(a["close"].iloc[2]),
                "match": bool(abs(b["close"].iloc[3] - a["close"].iloc[2]) < 1e-6),
            }
    return out
