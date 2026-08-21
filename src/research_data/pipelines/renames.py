"""Symbol-rename detection: stitch one company's history back into one series.

WHY THIS EXISTS
Bhavcopy records whatever ticker a company traded under on the day. When a
company renames, its history splits across two tickers with no link between
them. UNO Minda is MINDAIND until 2022-08-04 and UNOMINDA from 2022-08-05;
the panel sees two symbols, one that stops and one that starts, each with
half the history. Every rolling indicator restarts at the handover, `ret_60d`
and `dist_52w_high` go NaN for a quarter, and a symbol with six years of
history is screened as if it had six months.

THE TWO SOURCES, AND WHY BOTH
  1. NSE publishes `symbolchange.csv`, the authoritative list of *which*
     renames happened — company, old ticker, new ticker, effective date.
     What it does not say is whether the two tickers are actually one
     continuous tradeable series in our window.
  2. The tape shows the handover: one ticker stops, the other starts, and the
     price carries across unbroken.

Same reconciliation as `corporate_actions`: NSE says what, the tape says
whether. A link is applied only when the tape agrees, and disagreements are
recorded rather than resolved silently.

WHY THE STATED DATE IS NOT USED TO SPLIT
`change_date` is the effective date, and it is occasionally a session ahead of
the tape — QUALITY's stated change is 2025-07-18 but QUALITY printed that day
and QUALITY30 only began on the 21st. Splitting on the stated date would put a
day of real trading under the wrong ticker, so the observed handover (old
ticker's last print, new ticker's first) is what the map is scoped by.

WHY CONTINUITY IS MEASURED ON RAW PRICES
`close_raw`, never the adjusted close. Adjustment factors are accumulated per
ticker, so the pre- and post-rename halves of one listing carry different
factors and the *adjusted* series has an artificial step at the handover that
the raw series does not: MOTHERSUMI -> MOTHERSON is 1.003 raw and 0.446
adjusted. Across the 258 candidate links the raw step never deviates more
than 11.7% while the adjusted step reaches 94%.

That same fact sets the order of the pipeline: **renames are merged before
corporate-action adjustment, not after.** Adjusting first would compute two
independent factor chains for one listing and bake the fake step in.

WHAT IS NOT MERGED
A rename whose two halves do not join cleanly. Four cases in this window are
long suspensions where the ticker changed while the stock was not trading —
SPENTEX last printed at 0.75 in September 2020 and resumed as CLCIND at 8.96
in January 2026. It is the same company, but splicing those into one series
would manufacture a 12x overnight return and let rolling windows blend prices
five years apart. They are flagged `long_gap` and left as separate symbols.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from ...core import config

CHANGES_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
CHANGES_PATH = config.METADATA_DIR / "symbol_changes.parquet"
MAP_PATH = config.METADATA_DIR / "rename_map.parquet"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}

# A link is applied only if both hold. Both cuts sit in empty space rather than
# on top of a population: handover gaps are 1-7 calendar days for 258 of 262
# candidates and then jump to 23, 55, 463, 1977; raw price steps deviate at
# most 11.7% and the rejects are 31%, 110%, 1094%.
MAX_GAP_DAYS = 10
PRICE_TOLERANCE = 0.25

APPLIED = "applied"


def fetch_symbol_changes(force: bool = False) -> pd.DataFrame:
    """Download NSE's symbol-change list; cache it as a parquet.

    The file is headerless and has exactly four comma-separated fields, but it
    is parsed from the right anyway — company names are the one field that
    could ever contain a comma, and losing the alignment would silently pair
    the wrong tickers.
    """
    if CHANGES_PATH.exists() and not force:
        return pd.read_parquet(CHANGES_PATH)

    r = requests.get(CHANGES_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()

    rows = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 4:
            continue
        company = ",".join(parts[:-3]).strip()
        old_symbol, new_symbol, change_date = (p.strip() for p in parts[-3:])
        rows.append({"company": company, "old_symbol": old_symbol,
                     "new_symbol": new_symbol, "change_date": change_date})

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"{CHANGES_URL} returned no parseable rows")
    df["change_date"] = pd.to_datetime(df["change_date"], format="%d-%b-%Y",
                                       errors="coerce")
    df = df[df["change_date"].notna()].reset_index(drop=True)

    config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CHANGES_PATH, index=False)
    return df


def build_rename_map(bars: pd.DataFrame, changes: pd.DataFrame,
                     max_gap_days: int = MAX_GAP_DAYS,
                     tolerance: float = PRICE_TOLERANCE,
                     save: bool = False) -> pd.DataFrame:
    """Validate each published rename against the tape; one row per link.

    Only changes touching a ticker that actually appears in the bars are
    returned — the published file goes back to 1999 and is mostly mutual-fund
    tickers that never trade in the equity panel, and carrying them would bury
    the handful of rows worth reading.

    `status` is one of applied / self / absent / overlap / long_gap /
    price_break. Everything except `applied` leaves the two tickers separate.

    Writing is opt-in via `save`, for the same reason as
    `corporate_actions.reconcile`: computing the map is a question, not a
    commitment.
    """
    price_col = "close_raw" if "close_raw" in bars.columns else "close"
    if bars.empty:
        return pd.DataFrame()

    span = bars.groupby("symbol")["date"].agg(["min", "max", "size"])
    ordered = bars.sort_values("date")
    last_px = ordered.groupby("symbol")[price_col].last()
    first_px = ordered.groupby("symbol")[price_col].first()
    present = set(span.index)

    ch = changes[changes["old_symbol"].isin(present)
                 | changes["new_symbol"].isin(present)].copy()

    rows = []
    for r in ch.itertuples():
        old, new = r.old_symbol, r.new_symbol
        rec = {"company": r.company, "old_symbol": old, "new_symbol": new,
               "change_date": r.change_date, "old_last": pd.NaT, "new_first": pd.NaT,
               "gap_days": pd.NA, "px_old_last": pd.NA, "px_new_first": pd.NA,
               "px_step": pd.NA, "n_bars_old": pd.NA, "status": None}

        if old == new:
            # NSE files a company-name change under the same ticker; there is
            # no listing to stitch.
            rec["status"] = "self"
            rows.append(rec)
            continue
        if old not in present or new not in present:
            # One half of the rename falls outside the 2020 floor. Nothing to
            # merge either way.
            rec["status"] = "absent"
            rows.append(rec)
            continue

        old_last, new_first = span.loc[old, "max"], span.loc[new, "min"]
        rec["old_last"], rec["new_first"] = old_last, new_first
        rec["n_bars_old"] = int(span.loc[old, "size"])
        gap = (new_first - old_last).days
        rec["gap_days"] = gap
        po, pn = float(last_px[old]), float(first_px[new])
        rec["px_old_last"], rec["px_new_first"] = po, pn
        step = pn / po if po else float("nan")
        rec["px_step"] = step

        if old_last >= new_first:
            # Both tickers trading at once is not a rename: it is either a
            # reused ticker or a mis-filed row, and merging would create
            # duplicate (symbol, date) rows.
            rec["status"] = "overlap"
        elif gap > max_gap_days:
            rec["status"] = "long_gap"
        elif not (abs(step - 1.0) <= tolerance):
            rec["status"] = "price_break"
        else:
            rec["status"] = APPLIED
        rows.append(rec)

    cols = ["company", "old_symbol", "new_symbol", "change_date", "old_last",
            "new_first", "gap_days", "px_old_last", "px_new_first", "px_step",
            "n_bars_old", "status", "canonical"]
    if not rows:
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(rows).sort_values(["change_date", "old_symbol"]).reset_index(drop=True)
    # Keyed on the old ticker: `canonical` answers "where did this listing end
    # up", so a terminal link resolves to its own new symbol and a chained one
    # resolves past it. Mapping the new symbol instead leaves every terminal
    # link NaN.
    out["canonical"] = out["old_symbol"].map(_closure(out))
    out = out[cols]
    if save:
        config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(MAP_PATH, index=False)
    return out


def _closure(rmap: pd.DataFrame) -> dict[str, str]:
    """Follow applied links to the ticker each listing ends up under.

    Renames chain: CLNINDIA -> HEUBACHIND -> SUDARCOLOR, and Indiabulls went
    IBULISL -> YAARII -> YAARI -> IBULLSLTD in five years. Only *applied*
    links are followed, so a chain broken by a rejected link stops there
    instead of leaping the gap it was rejected for.
    """
    links = rmap[rmap["status"] == APPLIED]
    parent = dict(zip(links["old_symbol"], links["new_symbol"]))

    resolved: dict[str, str] = {}
    for start in parent:
        seen, node = [], start
        while node in parent and node not in seen:
            seen.append(node)
            node = parent[node]
        for s in seen:
            resolved[s] = node
    return resolved


def canonical_map(rmap: pd.DataFrame) -> dict[str, str]:
    """`{old_ticker: current_ticker}` for every applied link, chains collapsed.

    Exposed because the map is not only a bars concern: anything else keyed on
    symbol — opening features, the Breeze ISEC lookup, index membership — has
    to be folded to the same canonical ticker or the joins quietly miss.
    """
    return _closure(rmap) if not rmap.empty else {}


def apply_renames(bars: pd.DataFrame, rmap: pd.DataFrame) -> pd.DataFrame:
    """Rewrite pre-rename tickers to their canonical symbol.

    Merging to the *newest* ticker rather than the oldest is deliberate: the
    index-membership and sector files NSE publishes are a current snapshot, so
    the canonical name is the one those joins already match on.
    """
    mapping = canonical_map(rmap)
    if not mapping:
        return bars

    out = bars.copy()
    out["symbol"] = out["symbol"].map(lambda s: mapping.get(s, s))

    # The no-overlap test is what makes a plain symbol->symbol map safe. Assert
    # the result rather than trust it: if NSE ever reissues a retired ticker to
    # a different company, this must fail loudly instead of silently welding
    # two companies into one series.
    dupes = out.duplicated(subset=["symbol", "date"]).sum()
    if dupes:
        raise RuntimeError(
            f"applying the rename map produced {dupes} duplicate (symbol, date) "
            "rows — a ticker was reused; the map needs date scoping")
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def build(bars: pd.DataFrame, force_fetch: bool = False,
          verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch, validate and apply in one step. Returns (merged_bars, rename_map)."""
    changes = fetch_symbol_changes(force=force_fetch)
    rmap = build_rename_map(bars, changes, save=True)
    merged = apply_renames(bars, rmap)
    if verbose:
        n = int((rmap["status"] == APPLIED).sum()) if not rmap.empty else 0
        print(f"  {len(changes):,} published symbol changes, "
              f"{len(rmap):,} touch the panel, {n} applied "
              f"({bars['symbol'].nunique():,} -> {merged['symbol'].nunique():,} symbols)",
              flush=True)
    return merged, rmap


def load_map() -> pd.DataFrame:
    if not MAP_PATH.exists():
        raise RuntimeError("rename_map.parquet missing. "
                           "Run: python -m src.cli sync-corp-actions")
    return pd.read_parquet(MAP_PATH)
