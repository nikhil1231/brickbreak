"""The opening window as a function of time, not as a single snapshot.

WHY THIS EXISTS
The strategy does not enter at a fixed clock time. It enters at some point `t`
inside the opening window, once the setup has developed, and the stop goes just
below the lowest price seen *so far*. Everything about the entry — the price,
the stop, whether the setup even qualifies — is a function of `t`, and none of
it may look forward past `t`.

THE INVARIANT, AND THE BUG IT WOULD HAVE CAUGHT
For any entry time `t`:

    stop_price < running_low_t <= entry_price

`running_low_t` is the minimum low over 09:15:00 through `t`, so it includes the
bar being entered on and therefore cannot exceed the price at `t`. The stop sits
below it by construction. A stop above the entry is not a market condition; it
is a bug, and `check_invariant` raises on it.

Phase 2.4 shipped exactly that bug. It paired `om_low` — the low of the *first
minute* — with an entry at 09:20, five minutes later. Nothing ties those two
times together, so on mornings where price fell between 09:16 and 09:20 the
"stop" landed above the entry: 31.96% of the panel, up to +6.53% above. The
conclusion drawn from it ("the stated stop is already breached at entry") was an
artifact of the pairing, not a property of the strategy, and has been retracted.
Pairing the low and the price at the *same* `t` violates the invariant on 0.00%
of the same 63,698 mornings. See H004 in `HYPOTHESES.md`.

A SECOND THING THAT PAIRING GOT WRONG
"The running low is close to the day's open" is a statement about the *setup*.
It says nothing about how far the stop sits from the entry, because the entry
can be well above both. Open 100, running low 99.80, entry 103: the low is 0.2%
below the open and the stop is 3.2% below the entry. The two distances are
separate measurements and are reported separately here — `low_vs_open_pct` for
the setup, `stop_dist_pct` for the risk.

WHAT THIS MODULE DOES NOT DO
It does not choose `t`, and it does not define an entry rule. It evaluates the
window on a grid of candidate times so that a rule can later be discovered
against evidence rather than asserted. Picking one of these offsets and calling
it the strategy would be exactly the mistake this grid exists to avoid.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config, renames

TICKS_DIR = config.NORMALIZED_DIR / "opening_1s"
GRID_PATH = config.NORMALIZED_DIR / "entry_window_grid.parquet"


@dataclass(frozen=True)
class WindowConfig:
    """Measurement choices. None of these is an entry rule.

    `offsets_s` are seconds after 09:15:00 at which the window is evaluated.
    `stop_buffer_pct` is the "slightly below" in "slightly below the running
    low" — a placeholder so the invariant can be checked with a real number, not
    a tuned parameter.
    """
    offsets_s: tuple[int, ...] = (30, 60, 90, 120, 180, 240, 300)
    stop_buffer_pct: float = 0.10
    session_start: str = "09:15:00"


def load_ticks(dates: list[pd.Timestamp] | None = None,
               ticks_dir: Path = TICKS_DIR,
               rmap: pd.DataFrame | None = None) -> pd.DataFrame:
    """Load 1-second opening bars, symbols folded to canonical tickers.

    Same reason as everywhere else in this pipeline: the pull ran against
    whatever ticker was current that day, and the daily panel is keyed on the
    post-rename one.
    """
    files = sorted(ticks_dir.glob("*.parquet"))
    if dates is not None:
        want = {pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates}
        files = [f for f in files if f.stem in want]
    if not files:
        return pd.DataFrame()
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)

    rmap = renames.load_map() if rmap is None else rmap
    cmap = renames.canonical_map(rmap)
    if cmap:
        df["symbol"] = df["symbol"].map(lambda s: cmap.get(s, s))
    df["date"] = df["timestamp"].dt.normalize()
    return df


def window_grid(ticks: pd.DataFrame, cfg: WindowConfig | None = None) -> pd.DataFrame:
    """Per (symbol, date, t): the price at `t` and the extremes through `t`.

    One row per candidate entry time. Long rather than wide because the whole
    point is to compare across `t`, and because a rule may later pick `t` per
    morning rather than globally.
    """
    cfg = cfg or WindowConfig()
    if ticks.empty:
        return pd.DataFrame()

    d = ticks.sort_values(["symbol", "date", "timestamp"])
    start = d["date"] + pd.Timedelta(cfg.session_start)
    d = d.assign(_elapsed=(d["timestamp"] - start).dt.total_seconds())

    out = []
    for t in cfg.offsets_s:
        # Strictly "information available by t": no bar after t is consulted.
        sub = d[d["_elapsed"] <= t]
        if sub.empty:
            continue
        g = sub.groupby(["symbol", "date"], sort=False).agg(
            price_t=("close", "last"),
            running_low_t=("low", "min"),
            running_high_t=("high", "max"),
            first_px=("open", "first"),
            n_bars_t=("close", "size"),
            vol_t=("volume", "sum"),
        ).reset_index()
        g["t_offset_s"] = t
        out.append(g)
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True).sort_values(
        ["date", "symbol", "t_offset_s"]).reset_index(drop=True)


def add_setup_and_stop(grid: pd.DataFrame, bars: pd.DataFrame,
                       cfg: WindowConfig | None = None) -> pd.DataFrame:
    """Attach the session open, the setup measure, and the implied stop.

    `day_open` is bhavcopy's opening print, not the first tick. Phase 2.3
    established that these are different prices and that the auction print is
    the session's open; the tick series starts at the first continuous-session
    trade. Using the first tick here would quietly redefine the setup.
    """
    cfg = cfg or WindowConfig()
    cols = [c for c in ("symbol", "date", "open_raw", "adj_factor") if c in bars.columns]
    d = grid.merge(bars[cols], on=["symbol", "date"], how="left")
    d = d.rename(columns={"open_raw": "day_open"})

    # The setup: is the running low at or only modestly below the day's open?
    d["low_vs_open_pct"] = (d["running_low_t"] / d["day_open"] - 1) * 100
    # Where the entry sits relative to the open. Independent of the above.
    d["entry_vs_open_pct"] = (d["price_t"] / d["day_open"] - 1) * 100

    # The risk: how far the stop sits below the price you paid.
    d["stop_px"] = d["running_low_t"] * (1 - cfg.stop_buffer_pct / 100)
    d["stop_dist_pct"] = (d["stop_px"] / d["price_t"] - 1) * 100
    # Distance to the low itself, before the buffer — the floor on the above.
    d["low_to_entry_pct"] = (d["running_low_t"] / d["price_t"] - 1) * 100
    return d


def check_invariant(grid: pd.DataFrame, tol: float = 1e-9) -> dict:
    """`stop_price < running_low_t <= entry_price`, or the implementation is wrong.

    Returns counts rather than raising when clean, so it can be reported; raises
    only when the invariant is actually broken, because at that point every
    downstream number about risk is meaningless.
    """
    d = grid.dropna(subset=["running_low_t", "price_t", "stop_px"])
    low_above_entry = int((d["running_low_t"] > d["price_t"] + tol).sum())
    stop_at_or_above_low = int((d["stop_px"] >= d["running_low_t"] - tol).sum())
    out = {
        "rows_checked": int(len(d)),
        "running_low_above_entry": low_above_entry,
        "stop_at_or_above_running_low": stop_at_or_above_low,
        "ok": low_above_entry == 0 and stop_at_or_above_low == 0,
    }
    if not out["ok"]:
        raise AssertionError(
            f"entry/stop invariant violated: {low_above_entry} rows with the "
            f"running low above the entry, {stop_at_or_above_low} with the stop "
            f"at or above the running low. stop < running_low <= entry must hold "
            f"by construction; a violation means the low and the price were read "
            f"at different times."
        )
    return out


def profile(grid: pd.DataFrame) -> list[dict]:
    """How the setup and the risk vary with `t`. Descriptive only."""
    rows = []
    for t, sub in grid.groupby("t_offset_s"):
        rows.append({
            "t_offset_s": int(t),
            "n": int(len(sub)),
            "median_bars": float(sub["n_bars_t"].median()),
            "median_low_vs_open_pct": round(float(sub["low_vs_open_pct"].median()), 4),
            "median_entry_vs_open_pct": round(float(sub["entry_vs_open_pct"].median()), 4),
            "median_stop_dist_pct": round(float(sub["stop_dist_pct"].median()), 4),
            "p90_stop_dist_pct": round(float(sub["stop_dist_pct"].quantile(0.10)), 4),
            "pct_stop_wider_than_1pct": round(
                float((sub["stop_dist_pct"] < -1).mean() * 100), 2),
        })
    return rows


def build(cfg: WindowConfig | None = None, save: bool = True,
          verbose: bool = True) -> tuple[pd.DataFrame, dict]:
    cfg = cfg or WindowConfig()
    ticks = load_ticks()
    bars = pd.read_parquet(config.NORMALIZED_DIR / "daily_bars_adj.parquet",
                           columns=["symbol", "date", "open_raw", "adj_factor"])
    grid = add_setup_and_stop(window_grid(ticks, cfg), bars, cfg)
    inv = check_invariant(grid)
    if save:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        grid.to_parquet(GRID_PATH, index=False)
    if verbose:
        print(f"  {len(grid):,} rows across {len(cfg.offsets_s)} entry times, "
              f"invariant clean on {inv['rows_checked']:,}")
    return grid, {"invariant": inv, "profile": profile(grid)}


def load_grid() -> pd.DataFrame:
    if not GRID_PATH.exists():
        raise RuntimeError("entry_window_grid.parquet missing. "
                           "Run: python -m src.cli entry-window")
    return pd.read_parquet(GRID_PATH)
