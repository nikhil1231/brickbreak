"""Corporate-action detection and price adjustment for the daily panel.

WHY THIS EXISTS
Bhavcopy prices are raw. TATASTEEL's 1:10 split on 2022-07-28 appears as
close=959.40 followed by open=98.10 — a -90% single-day step that is not a
price move at all. Left alone it corrupts every EMA, `ret_60d`, ATR, and any
target/stop arithmetic that spans the ex-date.

WHAT DOES *NOT* WORK
The obvious shortcut is to read the adjustment out of bhavcopy's own
PREV_CLOSE column. It does not work: NSE does not adjust PREV_CLOSE for
corporate actions. On TATASTEEL's ex-date the file says PREV_CLOSE=959.40
against OPEN=98.10, i.e. the raw prior close. (SETFGOLD's 2022-01-06 1:100
split *is* adjusted there, so the column is not merely unadjusted, it is
inconsistent — which makes it unusable either way.)

THE TWO SOURCES, AND WHY BOTH
  1. NSE's corporate-actions feed gives exact, stated ratios, but says nothing
     about whether a ratio was actually applied to the tape on the day it
     claims, and its `exDate` is occasionally off by a session.
  2. The price series itself shows exactly where the tape stepped, but cannot
     tell a 1:2 split from a stock that genuinely halved on news.

Neither is trustworthy alone, so they are reconciled: an adjustment is applied
only where a stated ratio and an observed step agree. Disagreements in both
directions — a stated ratio with no step, a step with no ratio — are reported
rather than silently resolved, because each one means something different and
a silent choice would bury it.

WHAT IS ADJUSTED
Splits, bonuses and consolidations carry unambiguous ratios and are adjusted.
Rights issues are dilutive at a subscription price, so the correct factor
depends on the cum price and the issue terms; they are computed and, being
reconciled the same way, applied only when the tape agrees. Demergers have no
recoverable ratio at all — the step is genuine value leaving the company — so
they are flagged, never adjusted. Dividends are deliberately ignored: the
strategy is a multi-day swing on percentage moves, and total-return adjustment
would misstate the actual prices a stop or target would have been hit at.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ...core import config

CA_URL = "https://www.nseindia.com/api/corporates-corporateActions"
CA_RAW_DIR = config.RAW_DIR / "corp_actions"
ACTIONS_PATH = config.METADATA_DIR / "corporate_actions.parquet"
FACTORS_PATH = config.NORMALIZED_DIR / "adjustment_factors.parquet"
ADJ_BARS = config.NORMALIZED_DIR / "daily_bars_adj.parquet"
RECON_PATH = config.METADATA_DIR / "ca_reconciliation.parquet"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
JSON_HEADERS = {**HEADERS, "Accept": "application/json, text/plain, */*"}

# Ratios that rescale price. RIGHTS is priced separately (see rights_factor).
RATIO_KINDS = ("SPLIT", "BONUS", "CONSOLIDATION")
# Recorded and flagged, never used to rescale.
UNADJUSTABLE_KINDS = ("DEMERGER",)


# ------------------------------------------------------------------ fetching

def _primed_session() -> requests.Session:
    """NSE's JSON API returns HTML unless the session already holds site cookies."""
    s = requests.Session()
    s.get("https://www.nseindia.com/", headers=HEADERS, timeout=30)
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-actions",
          headers=HEADERS, timeout=30)
    return s


def fetch_actions(start: date, end: date, chunk_days: int = 90,
                  force: bool = False, verbose: bool = True) -> pd.DataFrame:
    """Download the corporate-actions feed in date chunks, caching raw JSON.

    The endpoint degrades on long ranges, so it is walked in ~quarterly chunks.
    Each chunk is cached verbatim; re-running only fetches what is missing.
    """
    CA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    s = _primed_session()
    recs: list[dict] = []
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=chunk_days), end)
        f = CA_RAW_DIR / f"{cur.isoformat()}.json"
        if force or not f.exists():
            for attempt in range(3):
                try:
                    r = s.get(CA_URL, params={"index": "equities",
                                              "from_date": cur.strftime("%d-%m-%Y"),
                                              "to_date": stop.strftime("%d-%m-%Y")},
                              headers=JSON_HEADERS, timeout=60)
                    if (r.status_code == 200
                            and r.headers.get("content-type", "").startswith("application/json")):
                        f.write_bytes(r.content)
                        break
                except requests.RequestException:
                    pass
                time.sleep(2 * (attempt + 1))
                s = _primed_session()
            else:
                if verbose:
                    print(f"  corp-actions chunk {cur} FAILED after 3 tries", flush=True)
                cur = stop + timedelta(days=1)
                continue
            time.sleep(0.4)
        try:
            recs += json.loads(f.read_text())
        except json.JSONDecodeError:
            f.unlink(missing_ok=True)
        cur = stop + timedelta(days=1)

    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df = df.rename(columns={"exDate": "ex_date", "faceVal": "face_value",
                            "recDate": "record_date", "comp": "company"})
    df["ex_date"] = pd.to_datetime(df["ex_date"], format="%d-%b-%Y", errors="coerce")
    df = df[df["ex_date"].notna()]
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["subject"] = df["subject"].astype(str).str.strip()
    df = df.drop_duplicates(subset=["symbol", "ex_date", "subject", "series"])

    parsed = df["subject"].map(parse_subject)
    df["kind"] = [p.kind for p in parsed]
    df["ratio"] = [p.ratio for p in parsed]
    df["ratio_note"] = [p.note for p in parsed]
    keep = ["symbol", "ex_date", "series", "kind", "ratio", "ratio_note",
            "subject", "face_value", "record_date", "company"]
    df = df[[c for c in keep if c in df.columns]].sort_values(["symbol", "ex_date"])
    config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ACTIONS_PATH, index=False)
    return df.reset_index(drop=True)


def load_actions() -> pd.DataFrame:
    if not ACTIONS_PATH.exists():
        raise RuntimeError("corporate_actions.parquet missing. "
                           "Run: python -m src.cli sync-corp-actions")
    return pd.read_parquet(ACTIONS_PATH)


# ------------------------------------------------------------------- parsing

@dataclass(frozen=True)
class Parsed:
    kind: str
    ratio: float | None      # multiply pre-ex-date prices by this
    note: str = ""


# "From Rs 10/- Per Share To Re 1/- Per Share"; Rs/Re and the /- are optional,
# and the same sentence covers consolidation with the values the other way up.
_FV = re.compile(
    r"from\s*(?:rs|re)?\.?\s*([\d.]+)\s*/?-?\s*per\s*share\s*to\s*(?:rs|re)?\.?\s*([\d.]+)",
    re.I)
# The pre-2020 feed writes the same event without "per share" and sometimes
# without "from": "Fv Split Rs.10/- To Rs.2/", "Face Value Split From Rs 10 To
# Re 1". 299 of the 416 legacy splits — 72% — fell through on this alone, which
# left their price steps unexplained and their windows quarantined. The
# currency prefix is mandatory here where it is optional above, so that a bare
# "1 to 2" in some unrelated sentence cannot match.
_FV_LEGACY = re.compile(
    r"(?:from\s*)?(?:rs|re)\.?\s*([\d.]+)\s*/?\s*-?\s*(?:per\s*share\s*)?"
    r"to\s*(?:rs|re)\.?\s*([\d.]+)",
    re.I)


def _face_value_change(text: str) -> tuple[float, float] | None:
    """Old and new face value, from either the modern or the legacy phrasing."""
    for rx in (_FV, _FV_LEGACY):
        m = rx.search(text)
        if m:
            try:
                old_fv, new_fv = float(m.group(1)), float(m.group(2))
            except ValueError:
                continue
            if old_fv > 0 and new_fv > 0:
                return old_fv, new_fv
    return None
# "Bonus 1:1", "Bonus 1: 1", "Rights 13:118 @ Premium Rs 308/-".
# Decimals are real: NSE writes "Rights 1:11.10".
_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
# "Premium", and its abbreviation "Prm", both appear.
_PREMIUM = re.compile(r"(?:premium|prm)\s*(?:rs|re)?\.?\s*([\d.]+)", re.I)


def parse_subject(subject: str) -> Parsed:
    """Classify an NSE corporate-action subject line and extract its ratio.

    The ratio returned is the multiplier applied to prices *before* the ex-date
    so they line up with prices after it (0.1 for a 1:10 split). Rights are
    classified and their terms captured, but their factor depends on the cum
    price and so is computed later, per event.
    """
    t = " ".join(str(subject).split())
    u = t.upper()

    if "SPLIT" in u or "SUB-DIVISION" in u or "SUB DIVISION" in u:
        fv = _face_value_change(t)
        if fv:
            old_fv, new_fv = fv
            return Parsed("SPLIT", new_fv / old_fv,
                          f"face value {old_fv} -> {new_fv}")
        return Parsed("SPLIT", None, "unparsed face-value change")

    if "CONSOLIDAT" in u:
        fv = _face_value_change(t)
        if fv:
            old_fv, new_fv = fv
            return Parsed("CONSOLIDATION", new_fv / old_fv,
                          f"face value {old_fv} -> {new_fv}")
        return Parsed("CONSOLIDATION", None, "unparsed face-value change")

    if "BONUS" in u:
        # Only a bonus of equity shares rescales the equity price. A bonus of
        # debentures, warrants or preference shares (NCRPS / NCDs, e.g.
        # TVSMOTOR's "Bonus Ncrps 4:1") leaves the share count untouched, and
        # treating one as a 5-for-1 equity bonus would rescale history by 0.2
        # for nothing.
        if any(k in u for k in ("DEBENTURE", "WARRANT", "NCRPS", "NCD",
                                "PREFERENCE", "PREF SHARE")):
            return Parsed("OTHER", None, "non-equity bonus")
        m = _RATIO.search(t)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                # `a` new shares for every `b` held: b old become a+b.
                return Parsed("BONUS", b / (a + b), f"bonus {m.group(1)}:{m.group(2)}")
        return Parsed("BONUS", None, "unparsed bonus ratio")

    if "RIGHT" in u:
        m = _RATIO.search(t)
        prem = _PREMIUM.search(t)
        if m:
            note = f"rights {m.group(1)}:{m.group(2)}"
            if prem:
                note += f" @ premium {prem.group(1)}"
            # Factor needs the cum price, so it is left to rights_factor().
            return Parsed("RIGHTS", None, note)
        return Parsed("RIGHTS", None, "unparsed rights ratio")

    if "DEMERGER" in u or "DE-MERGER" in u:
        return Parsed("DEMERGER", None, "no recoverable ratio")

    if "DIVIDEND" in u:
        return Parsed("DIVIDEND", None, "")

    return Parsed("OTHER", None, "")


def rights_factor(subject: str, cum_price: float, face_value: float | None) -> float | None:
    """Theoretical ex-rights price ratio for `Rights a:b @ Premium Rs P`.

    `a` new shares are offered per `b` held at an issue price of face value plus
    premium, so b shares worth `cum_price` each become a+b shares worth
    (b*cum + a*issue)/(a+b). Returns None when the terms or the cum price are
    not usable, which leaves the event flagged rather than adjusted.

    A stated premium of zero is common and legitimate (an at-par issue), so it
    is the *issue price* — premium plus face value — that has to be positive,
    not the premium. Subjects that omit the premium entirely give no issue
    price at all and cannot be priced.
    """
    m = _RATIO.search(str(subject))
    prem = _PREMIUM.search(str(subject))
    if not m or not prem or not cum_price or cum_price <= 0:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if a <= 0 or b <= 0:
        return None
    try:
        fv = float(face_value)
    except (TypeError, ValueError):
        fv = 0.0
    if not np.isfinite(fv) or fv < 0:
        fv = 0.0
    try:
        issue = float(prem.group(1)) + fv
    except (TypeError, ValueError):
        return None
    if issue <= 0:
        return None
    theo = (b * cum_price + a * issue) / (a + b)
    if theo <= 0:
        return None
    f = theo / cum_price
    # A rights issue can only dilute, and a factor near zero means junk terms.
    return f if 0.2 < f <= 1.0 else None


# ------------------------------------------------- empirical step detection

def measure_steps(bars: pd.DataFrame) -> pd.DataFrame:
    """Per symbol-date, two independent measures of a price discontinuity.

    `step_prev` is open/PREV_CLOSE, both from the same bhavcopy line.
    `step_prior` is open/(previous session's close in our own panel).

    Both are needed because NSE is inconsistent about PREV_CLOSE. It is raw on
    TATASTEEL's 2022-07-28 split (959.40 against an open of 98.10) and already
    adjusted on DRCSYSTEMS' 2022-03-16 split (38.15 against an open of 36.80),
    so `step_prev` sees the first and is blind to the second. `step_prior`
    measures the discontinuity in the series actually being adjusted, but goes
    stale across a long trading gap, where it also carries genuine drift.
    Neither dominates, so both are reported and either may confirm a ratio.
    """
    d = bars[["symbol", "date", "prev_close", "open", "close"]].copy()
    d = d.sort_values(["symbol", "date"])
    g = d.groupby("symbol", sort=False)
    prior_close = g["close"].shift(1)
    d["step_prev"] = np.where(d["prev_close"].gt(0) & d["open"].gt(0),
                              d["open"] / d["prev_close"], np.nan)
    d["step_prior"] = np.where(prior_close.gt(0) & d["open"].gt(0),
                               d["open"] / prior_close, np.nan)
    return d


def detect_steps(bars: pd.DataFrame, min_step: float = 0.15) -> pd.DataFrame:
    """Single-session price discontinuities exceeding `min_step`.

    A row qualifies if *either* measure shows the jump, since either measure
    alone can be blind to a real one.
    """
    d = measure_steps(bars)
    a = (d["step_prev"] - 1.0).abs()
    b = (d["step_prior"] - 1.0).abs()
    out = d[(a >= min_step) | (b >= min_step)].copy()
    out["step"] = np.where(a.loc[out.index].fillna(-1) >= b.loc[out.index].fillna(-1),
                           out["step_prev"], out["step_prior"])
    return out.reset_index(drop=True)


# ------------------------------------------------------------ reconciliation

def group_events(actions: pd.DataFrame) -> pd.DataFrame:
    """Collapse actions to one row per (symbol, ex_date), combining ratios.

    Several actions routinely share an ex-date and compound into a single price
    step. BAJFINANCE's 2025-06-16 is a 1:2 split *and* a 4:1 bonus, a combined
    0.5 * 0.2 = 0.10 against an observed 0.1024; matched separately, both look
    like gross mismatches. Only the product is comparable to the tape, and only
    the product is the right thing to rescale history by.
    """
    ca = actions[actions["kind"].isin(
        list(RATIO_KINDS) + list(UNADJUSTABLE_KINDS) + ["RIGHTS"])].copy()
    if ca.empty:
        return pd.DataFrame()
    ca["ex_date"] = pd.to_datetime(ca["ex_date"])
    rows = []
    for (sym, ex), g in ca.groupby(["symbol", "ex_date"], sort=False):
        rows.append({
            "symbol": sym, "ex_date": ex,
            "kinds": "+".join(sorted(set(g["kind"]))),
            "n_actions": len(g),
            "has_unadjustable": bool(g["kind"].isin(UNADJUSTABLE_KINDS).any()),
            "has_rights": bool((g["kind"] == "RIGHTS").any()),
            # NaN here means at least one component could not be parsed.
            "ratio_known": g.loc[g["kind"].isin(RATIO_KINDS), "ratio"],
            "subjects": " | ".join(g["subject"]),
            "face_value": g["face_value"].iloc[0] if "face_value" in g else None,
            "rights_subjects": list(g.loc[g["kind"] == "RIGHTS", "subject"]),
            "n_ratio_kinds": int(g["kind"].isin(RATIO_KINDS).sum()),
        })
    return pd.DataFrame(rows)


def find_renamed_symbol(bars: pd.DataFrame, steps: pd.DataFrame, symbol: str,
                        ex_date: pd.Timestamp, stated: float,
                        tolerance: float = 0.20, window_days: int = 4,
                        handover_days: int = 7) -> str | None:
    """Find the ticker a symbol traded under before it was renamed.

    NSE's corporate-actions feed keys on a company's *current* symbol, while
    bhavcopy recorded whatever it traded as at the time. MINDA INDUSTRIES'
    2022-07-07 bonus is filed under UNOMINDA, but the tape that day says
    MINDAIND. Left unresolved the event looks like it never happened and, worse,
    the pre-rename history keeps an unadjusted split in it.

    A candidate has to clear two independent tests: it stepped by the stated
    ratio around the ex-date, and it stopped trading exactly where the current
    symbol started. The second test is what makes this safe — a ratio match
    alone is ambiguous, since TORNTPHARM also halved within a day of UNOMINDA's
    bonus, but TORNTPHARM is still trading and so cannot be the same listing.
    Only an unambiguous single candidate is accepted.
    """
    first = bars.loc[bars["symbol"] == symbol, "date"]
    if first.empty:
        return None
    first_seen = first.min()

    lo, hi = ex_date - pd.Timedelta(days=window_days), ex_date + pd.Timedelta(days=window_days)
    w = steps[steps["date"].between(lo, hi) & (steps["symbol"] != symbol)]
    near = w[((w["step_prior"] / stated - 1.0).abs() <= tolerance)
             | ((w["step_prev"] / stated - 1.0).abs() <= tolerance)]
    if near.empty:
        return None

    span = bars.groupby("symbol")["date"].agg(["min", "max"])
    hits = []
    for cand in near["symbol"].unique():
        if cand not in span.index:
            continue
        last_seen = span.loc[cand, "max"]
        # The old listing must end just as the new one begins, and never
        # trade alongside it.
        if last_seen >= first_seen:
            continue
        if (first_seen - last_seen).days > handover_days:
            continue
        hits.append(cand)
    return hits[0] if len(hits) == 1 else None


def reconcile(bars: pd.DataFrame, actions: pd.DataFrame,
              tolerance: float = 0.20, window: int = 3,
              save: bool = False) -> pd.DataFrame:
    """Match combined stated ratios to observed steps; one row per ex-date.

    A stated ratio is accepted only when the tape stepped by roughly that much
    within `window` sessions of the stated ex-date. The window exists because
    NSE's exDate is occasionally a session out, and because a symbol may simply
    not have traded on its own ex-date.

    There is deliberately no minimum-step floor. A bonus of 1:20 is a 4.8%
    step, indistinguishable in size from an ordinary gap, and screening it out
    before matching would silently drop every small-ratio event. The floor
    belongs in `unexplained_steps`, where there is no stated ratio to match
    against and size is the only signal available.

    The 20% default tolerance is read off the data rather than assumed. Across
    731 events carrying both a stated ratio and an observed step, 99.5% agree
    to within 20% and only four fall outside, so the gap between the two
    populations is where the cut belongs. The residual spread is real: a stated
    ratio is exact, but the ex-date open still contains that morning's genuine
    move, and the errors skew slightly positive (median +1.5%) because bonus
    and split ex-dates tend to open firm. A tolerance tight enough to exclude
    that ordinary drift would reject hundreds of perfectly good ratios.

    `status` is one of matched / no_step / ratio_mismatch / unparsed /
    unadjustable, and `matched_on` records which measure confirmed it.

    Writing is opt-in via `save`. Computing a reconciliation is a question, not
    a commitment, and a function that answers it should not overwrite the
    project's artifacts as a side effect of being called.
    """
    ev = group_events(actions)
    if ev.empty:
        return pd.DataFrame()

    steps = measure_steps(bars)
    by_symbol = {s: g for s, g in steps.groupby("symbol", sort=False)}
    cal = np.sort(bars["date"].unique())

    rows = []
    for r in ev.itertuples(index=False):
        ex = pd.Timestamp(r.ex_date)
        i = int(np.searchsorted(cal, ex))
        lo = cal[max(0, i - window)] if len(cal) else ex
        hi = cal[min(len(cal) - 1, i + window)] if len(cal) else ex

        g = by_symbol.get(r.symbol)
        cand = g[g["date"].between(lo, hi)] if g is not None else None

        # Combined ratio: product of every component that could be priced.
        parts = [float(x) for x in r.ratio_known if not pd.isna(x)]
        unparsed_component = len(parts) < r.n_ratio_kinds
        if r.has_rights:
            cum = None
            if g is not None:
                prior = g[g["date"] < ex]
                cum = float(prior["close"].iloc[-1]) if len(prior) else None
            for subj in r.rights_subjects:
                rf = rights_factor(subj, cum, r.face_value) if cum else None
                if rf is None:
                    unparsed_component = True
                else:
                    parts.append(rf)

        stated = float(np.prod(parts)) if parts else None

        obs_step = obs_date = matched_on = None
        if cand is not None and len(cand) and stated is not None:
            # Whichever measure lands closest to the stated ratio confirms it;
            # both are recorded so a disagreement stays visible.
            best = None
            for col in ("step_prev", "step_prior"):
                v = cand[col]
                if v.notna().any():
                    idx = (v - stated).abs().idxmin()
                    err = abs(float(v.loc[idx]) / stated - 1.0)
                    if best is None or err < best[0]:
                        best = (err, float(v.loc[idx]), cand.loc[idx, "date"], col)
            if best:
                _, obs_step, obs_date, matched_on = best

        # A symbol with no bars anywhere near its own ex-date was almost
        # certainly trading under an earlier name; the adjustment belongs on
        # that ticker, which is where the history actually lives.
        apply_to = r.symbol
        if obs_step is None and stated is not None and not r.has_unadjustable:
            old = find_renamed_symbol(bars, steps, r.symbol, ex, stated,
                                      tolerance=tolerance)
            if old is not None:
                g2 = by_symbol.get(old)
                cand2 = g2[g2["date"].between(lo, hi)] if g2 is not None else None
                if cand2 is not None and len(cand2):
                    best = None
                    for col in ("step_prev", "step_prior"):
                        v = cand2[col]
                        if v.notna().any():
                            idx = (v - stated).abs().idxmin()
                            err = abs(float(v.loc[idx]) / stated - 1.0)
                            if best is None or err < best[0]:
                                best = (err, float(v.loc[idx]), cand2.loc[idx, "date"], col)
                    if best:
                        _, obs_step, obs_date, matched_on = best
                        apply_to = old

        if r.has_unadjustable:
            status = "unadjustable"
        elif stated is None or unparsed_component:
            status = "unparsed"
        elif obs_step is None:
            status = "no_step"
        elif abs(obs_step / stated - 1.0) <= tolerance:
            status = "matched"
        else:
            status = "ratio_mismatch"

        rows.append({"symbol": r.symbol, "apply_to_symbol": apply_to, "ex_date": ex,
                     "kinds": r.kinds, "n_actions": r.n_actions,
                     "stated_ratio": stated, "observed_step": obs_step,
                     "observed_date": obs_date, "matched_on": matched_on,
                     "status": status, "renamed_from": apply_to if apply_to != r.symbol else None,
                     "subjects": r.subjects})

    out = pd.DataFrame(rows).sort_values(["symbol", "ex_date"]).reset_index(drop=True)
    if save:
        config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(RECON_PATH, index=False)
    return out


def unexplained_steps(bars: pd.DataFrame, actions: pd.DataFrame,
                      min_step: float = 0.30, window: int = 3) -> pd.DataFrame:
    """Observed steps with no corporate action anywhere near them.

    These are the residual risk: either a genuine one-day move (common in
    smallcaps, where a 40% day is unremarkable) or a corporate action NSE's
    feed did not carry. Reported so the pile can be eyeballed rather than
    assumed away.
    """
    steps = detect_steps(bars, min_step=min_step)
    if actions.empty:
        return steps
    cal = np.sort(bars["date"].unique())
    ca = actions[actions["kind"] != "DIVIDEND"]
    near = set()
    for sym, ex in zip(ca["symbol"], pd.to_datetime(ca["ex_date"])):
        i = int(np.searchsorted(cal, ex))
        for j in range(max(0, i - window), min(len(cal), i + window + 1)):
            near.add((sym, cal[j]))
    mask = [(s, d) not in near for s, d in zip(steps["symbol"], steps["date"])]
    return steps[mask].reset_index(drop=True)


# -------------------------------------------------------------- adjustment

def build_factors(bars: pd.DataFrame, recon: pd.DataFrame,
                  save: bool = False) -> pd.DataFrame:
    """Cumulative back-adjustment factor per symbol-date, from matched events.

    Back-adjusted rather than forward-adjusted: the most recent price is left
    equal to the traded price and history is scaled to meet it. That keeps the
    latest bars — the ones a live screener sees — identical to what the
    exchange actually printed, so nothing downstream has to know about this
    layer to quote a price correctly.
    """
    ok = recon[(recon["status"] == "matched") & recon["stated_ratio"].notna()]
    # `apply_to_symbol` differs from `symbol` only for a resolved rename, where
    # the pre-ex-date history sits under the previous ticker.
    key = "apply_to_symbol" if "apply_to_symbol" in ok.columns else "symbol"
    frames = []
    for sym, g in bars.groupby("symbol", sort=False):
        dates = g["date"].sort_values().to_numpy()
        f = np.ones(len(dates), dtype="float64")
        ev = ok[ok[key] == sym]
        for ex, ratio in zip(pd.to_datetime(ev["ex_date"]), ev["stated_ratio"]):
            # Everything strictly before the ex-date is scaled by the ratio.
            f[dates < np.datetime64(ex)] *= float(ratio)
        frames.append(pd.DataFrame({"symbol": sym, "date": dates, "adj_factor": f}))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if save and not out.empty:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(FACTORS_PATH, index=False)
    return out


def adjust_bars(bars: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Apply factors to OHLC and volume, keeping raw prices alongside.

    Volume is divided by the factor so that price*volume still reconciles to
    the turnover the exchange reported; `turnover` itself is already a value
    and is left untouched.

    `prev_close` is scaled by the *previous* session's factor, not this row's.
    They differ by exactly the ratio on an ex-date — which is the one row where
    it matters — and using this row's factor would leave `close/prev_close - 1`
    reading as a -90% return on every split. The sector index is built from
    precisely that expression.

    Every adjusted column keeps a `_raw` twin. A stop, a circuit limit and a
    minimum-price screen all apply to the price that actually printed, so the
    traded price has to survive this transformation rather than be replaced
    by it.
    """
    d = bars.merge(factors, on=["symbol", "date"], how="left")
    d["adj_factor"] = d["adj_factor"].fillna(1.0)
    d = d.sort_values(["symbol", "date"])
    prev_factor = d.groupby("symbol", sort=False)["adj_factor"].shift(1)
    prev_factor = prev_factor.fillna(d["adj_factor"])

    for c in ("open", "high", "low", "close", "vwap", "last"):
        if c in d.columns:
            d[f"{c}_raw"] = d[c]
            d[c] = d[c] * d["adj_factor"]
    if "prev_close" in d.columns:
        d["prev_close_raw"] = d["prev_close"]
        d["prev_close"] = d["prev_close"] * prev_factor
    if "volume" in d.columns:
        d["volume_raw"] = d["volume"]
        d["volume"] = d["volume"] / d["adj_factor"]
    return d.reset_index(drop=True)


def build(start: date = date(2020, 1, 1), end: date | None = None,
          force_fetch: bool = False, verbose: bool = True) -> dict:
    """Full pipeline: merge renames, fetch actions, reconcile, adjust, write bars."""
    from ..sources import nse as nse_archive
    from . import renames

    end = end or date.today()
    bars = nse_archive.load_range()
    if bars.empty:
        raise RuntimeError("No bhavcopy data. Run: python -m src.cli sync-nse")

    # Renames first, deliberately. Adjusting first would accumulate a separate
    # factor chain for each half of a renamed listing and leave a step at the
    # handover that is pure bookkeeping. See research_data.pipelines.renames.
    if verbose:
        print("merging symbol renames ...", flush=True)
    bars, rmap = renames.build(bars, force_fetch=force_fetch, verbose=verbose)

    if verbose:
        print("fetching NSE corporate actions ...", flush=True)
    actions = fetch_actions(start, end, force=force_fetch, verbose=verbose)
    if verbose:
        print(f"  {len(actions):,} actions, {actions['symbol'].nunique():,} symbols",
              flush=True)
        print("reconciling stated ratios against observed price steps ...", flush=True)

    recon = reconcile(bars, actions, save=True)
    counts = recon["status"].value_counts().to_dict() if not recon.empty else {}
    factors = build_factors(bars, recon, save=True)
    adj = adjust_bars(bars, factors)
    config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    adj.to_parquet(ADJ_BARS, index=False)

    n_adj = int((factors["adj_factor"] != 1.0).sum()) if not factors.empty else 0
    n_renamed = int((rmap["status"] == renames.APPLIED).sum()) if not rmap.empty else 0
    stats = {"actions": len(actions), "reconciled": len(recon), "status": counts,
             "renames_applied": n_renamed,
             "symbols_adjusted": int(recon[recon["status"] == "matched"]["symbol"].nunique())
             if not recon.empty else 0,
             "rows_rescaled": n_adj, "adjusted_bars": str(ADJ_BARS)}
    if verbose:
        print(f"  {stats}", flush=True)
    return stats


def load_adjusted() -> pd.DataFrame:
    if not ADJ_BARS.exists():
        raise RuntimeError("daily_bars_adj.parquet missing. "
                           "Run: python -m src.cli sync-corp-actions")
    return pd.read_parquet(ADJ_BARS)
