"""The case — one situation, as a good discretionary trader could have known it.

A case is what the AI is shown, and it is the single most dangerous object in
this package. Everything downstream is arithmetic; this is where the future can
get in, and it would not look wrong when it did.

THE GUARANTEE, AND HOW IT IS MADE RATHER THAN PROMISED
Every number in a case is drawn from the as-of panel, whose indicators end at
D-1, plus date D's **opening print** — the 09:15:00 call-auction price, on the
tape before any entry, and the one date-D price a morning decision may use
(`research_data.pipelines.asof.KNOWN_AT_OPEN`). Nothing else from date D exists
here.

That is a promise until something checks it, so `tests/test_case_pit.py` builds
the same case against a panel truncated at D and against the full panel and
requires the serialised bytes to be **identical**. This project has caught four
distinct non-price lookaheads, none in an obvious place; the standing assumption
is that there is a fifth.

THE DENOMINATOR TRAP, WHICH IS WHY THIS MODULE COMPUTES ALMOST NOTHING
`behaviour.py` once divided opening volume by a 20-session median volume that
included date D's own full-day volume. The numerator was clean and the feature
was contaminated. So this module derives as little as it can: it *selects*
columns the pipelines already built under test, and where it must compute — the
rebasing, the percentiles, the analogue distances — it does so from those
columns only, never from raw bars spanning D.

WHAT A CASE IS NOT
Not a feature vector. MISSION §3 asks for what a good discretionary trader
could reasonably know, and a trader reads a chart, a market, a sector and a
history of similar situations. So a case carries a compact bar table, a
narrative summary of shape, the market and sector state, and analogues — and it
carries each block under a heading that says what kind of thing it is.

ANONYMISATION IS THE DEFAULT AND IT IS NOT COSMETIC
A model may remember what a named Indian equity did in a named quarter. No
amount of frame hygiene closes that: the leak is in the weights. Under
`anonymise` the symbol never appears, dates become session offsets, prices are
rebased to 100 at the window start, and the sector becomes an opaque group id
that still lets "my sector is strong" be stated without naming the sector.
What survives is the judgement, which is the thing under test.

SNAPSHOT ATTRIBUTES ARE LABELLED, NOT HIDDEN
`sector` and `size_tier` are NSE's *present-day* membership applied to
historical rows. The lab's rule is that a non-PIT feature may stratify but
never score; a case is neither, so the honest treatment is to include them and
say what they are. The case text marks them as present-day classifications so a
judge does not read them as facts about the session.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels

logger = logging.getLogger(__name__)


class CaseError(RuntimeError):
    pass


# Which panel columns feed which block. Selection, not derivation — every one
# of these is produced by a pipeline that has its own causality test.
BLOCK_COLUMNS: dict[str, tuple[str, ...]] = {
    "location": (
        "prior_high_20", "prior_low_20", "base_range_20_pct",
        "days_since_high_20", "n_touches_20", "prev_close_vs_high_20_pct",
        "open_vs_high_20_pct", "open_above_high_20", "open_base_pos_20",
        "base_low_dist_20_pct", "prior_high_50", "days_since_high_50",
        "n_touches_50", "open_vs_high_50_pct", "open_base_pos_50",
        "dist_52w_high",
    ),
    "market": (
        "mkt_regime", "mkt_ret_5d", "mkt_ret_20d", "mkt_ret_60d",
        "mkt_vol_20d", "mkt_trend_eff", "mkt_vs_ema50_pct",
        "mkt_dd_from_60d_high_pct", "mkt_breadth_pct",
    ),
    "sector": (
        "sec_ret_20d", "sec_ret_60d", "sec_rs_20d_vs_mkt",
        "sector_uptrend_index", "sector_breadth",
    ),
    "relative_strength": (
        "rs_20d_vs_mkt", "rs_60d_vs_mkt", "rs_20d_vs_sec",
    ),
    "volatility_liquidity": (
        "atr_pct", "atr_ratio", "atr_ratio_pctile", "bb_width_pctile",
        "range_pct_ma", "median_tv_20_cr",
    ),
    "volume": (
        "deliv_pct", "median_vol_20", "turnover",
    ),
    "extension_contraction": (
        "base_depth", "base_depth_pctile", "nr_k", "inside_day", "doji_like",
        "body_ratio", "n_small_bodies_5", "vol_squeeze", "contraction_steps",
        "ret_20d", "ret_60d", "gap_pct", "px_vs_ema_fast", "px_vs_ema_mid",
        "ema_stack_up", "above_ema_mid",
    ),
}

# Features the analogue search runs on. Deliberately few and deliberately
# scale-free: an analogue is "a situation shaped like this one", and a distance
# over forty columns is dominated by whichever handful happen to co-move.
ANALOGUE_FEATURES = (
    "ret_20d", "rs_20d_vs_mkt", "atr_ratio_pctile", "bb_width_pctile",
    "open_base_pos_20", "dist_52w_high",
)

# Columns whose value is a present-day snapshot rather than a fact about the
# session. Included, and labelled as such wherever they are rendered.
SNAPSHOT_COLUMNS = ("sector", "size_tier", "size_tier_rank")

# Absolute levels, dropped under anonymisation. Two reasons, and the second is
# the one that would have been missed: a price of 2,351 and a turnover of 37
# crore narrow the identity of an NSE name considerably, *and* they contradict
# the rest of the case, where the chart is rebased to 100. A judge shown both
# cannot compare them. Every one of these already has a relative twin in the
# same block — `open_vs_high_20_pct` says what `prior_high_20` was for — so
# nothing is lost but the identity.
# Flags the panel stores as 0/1. Rendered as yes/no, because "inside_day: 0"
# asks a reader to know the polarity of a column name and "inside_day: no"
# does not. Cheap, and this text is the entire input to the judgement.
BOOLEAN_COLUMNS = frozenset((
    "open_above_high_20", "open_above_high_50", "nr_k", "inside_day",
    "doji_like", "vol_squeeze", "ema_stack_up", "above_ema_mid",
    "sector_uptrend_index",
))

ABSOLUTE_LEVEL_COLUMNS = (
    "prior_high_20", "prior_low_20", "prior_high_50", "prior_low_50",
    "turnover", "median_vol_20",
)


@dataclass
class Case:
    """One situation, serialisable, hashable, and free of the future by test."""
    case_id: str
    # Identity is carried so outcomes can be joined later. It is *never*
    # rendered into the text a decider sees when `anonymise` is set.
    symbol: str
    date: str
    anonymised: bool
    generator_score: float
    generator_reason: str
    blocks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        return cls(**d)

    @property
    def case_hash(self) -> str:
        """Over what the decider is shown, not over who it is about.

        Two cases differing only in identity are the same question, and under
        anonymisation they are literally the same prompt. Hashing the rendered
        content rather than the record keeps that true.
        """
        return hashlib.sha256(
            self.render().encode("utf-8")).hexdigest()[:16]

    def render(self) -> str:
        """The case as the decider receives it."""
        return render(self)


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

def _clean(value: Any) -> Any:
    """JSON-safe, and rounded so trivial float noise cannot change a hash."""
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if not np.isfinite(f) else round(f, 4)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
        return None
    return str(value)


def _price_history(bars: pd.DataFrame, symbol: str, date: pd.Timestamp,
                   sessions: int, anonymise: bool) -> dict[str, Any]:
    """The chart, as a table plus the shape a reader would describe.

    Bars strictly before D, plus date D's **open** and nothing else of D. The
    cut is `< date`, not `<= date`: taking date D's bar would hand over its
    high, low and close, which is the H015 lookahead in its original form.
    """
    g = bars[(bars["symbol"] == symbol) & (bars["date"] < date)]
    g = g.sort_values("date").tail(sessions)
    if g.empty:
        return {"n_sessions": 0, "bars": [], "summary": "no prior history"}

    base = float(g["close"].iloc[0])
    if not np.isfinite(base) or base <= 0:
        return {"n_sessions": 0, "bars": [], "summary": "no usable prior history"}

    def _px(v):
        # Two decimals on a series rebased to 100 is a tenth of a percent,
        # which is finer than anything a judgement turns on — and 60 bars of
        # four-decimal prices is ~8% of the case's token budget spent on noise.
        return round(float(v) / base * 100.0, 2)

    rows = []
    vol_base = float(g["volume"].median()) or 1.0
    for i, r in enumerate(g.itertuples(index=False)):
        rows.append({
            # Sessions before the decision, so the axis carries no calendar.
            "t": i - len(g),
            **({} if anonymise else {"date": _clean(r.date)}),
            "o": _px(r.open), "h": _px(r.high), "l": _px(r.low),
            "c": _px(r.close),
            "vol_x_median": round(float(r.volume) / vol_base, 2),
        })

    closes = g["close"].to_numpy(dtype=float)
    highs, lows = g["high"].to_numpy(dtype=float), g["low"].to_numpy(dtype=float)
    hi_i, lo_i = int(np.argmax(highs)), int(np.argmin(lows))
    net = (closes[-1] / closes[0] - 1.0) * 100.0
    travel = float(np.abs(np.diff(np.log(np.maximum(closes, 1e-9)))).sum())
    straightness = abs(np.log(max(closes[-1], 1e-9) / max(closes[0], 1e-9))) / travel \
        if travel > 0 else np.nan
    summary = (
        f"{len(g)} sessions before the decision. Rebased to 100 at the start, "
        f"the last close is {closes[-1] / base * 100:.1f} "
        f"({net:+.1f}% over the window). The high came {len(g) - hi_i} sessions "
        f"before the decision and the low {len(g) - lo_i}. Path straightness "
        f"{straightness:.2f} (1.0 = a straight line, 0 = round trips)."
    )
    return {"n_sessions": int(len(g)), "rebased_to": 100.0,
            "bars": rows, "summary": summary}


def _select(row: pd.Series, columns: tuple[str, ...],
            anonymise: bool = False) -> dict[str, Any]:
    keep = [c for c in columns if c in row.index
            and not (anonymise and c in ABSOLUTE_LEVEL_COLUMNS)]
    return {c: _clean(row[c]) for c in keep}


def _quant_block(row: pd.Series, session: pd.DataFrame,
                 generator_score: float) -> dict[str, Any]:
    """Where this name sits in *today's* cross-section, not in the whole panel.

    A percentile against the full history would leak: the distribution it ranks
    against contains every session after D. Ranking within the session is both
    causal and the more meaningful statement — "third decile of relative
    strength today" is what a trader means.
    """
    out: dict[str, Any] = {"generator_score": _clean(generator_score)}
    for col in ("ret_20d", "rs_20d_vs_mkt", "rs_60d_vs_mkt", "atr_pct",
                "median_tv_20_cr", "deliv_pct", "dist_52w_high"):
        if col not in session.columns or col not in row.index:
            continue
        vals = session[col].dropna()
        if len(vals) < 20 or not np.isfinite(_as_float(row[col])):
            continue
        out[f"{col}_session_pctile"] = _clean(
            float((vals < row[col]).mean() * 100.0))
    out["session_breadth_names"] = int(len(session))
    return out


def _as_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _announcement_block(row: pd.Series, anonymise: bool) -> dict[str, Any]:
    """Disclosure text available before the decision, with identity scrubbed.

    The source rows have already been moved to their first tradable session by
    ``frame.load_events``. This function does no timing work; it only prepares
    what the judge sees. Amounts and operational facts survive because they are
    the substance being judged. Company, symbol, ISIN and calendar dates do not.
    """
    raw = row.get("announcements", [])
    if not isinstance(raw, (list, tuple)):
        raw = []
    symbol = str(row.get("symbol", "")).strip()
    company_names = {
        str(item.get("company", "")).strip()
        for item in raw if isinstance(item, dict) and item.get("company")
    }

    def scrub(value: Any) -> str:
        text = str(value or "")
        if not anonymise:
            return text
        for identity in sorted(company_names | ({symbol} if symbol else set()),
                               key=len, reverse=True):
            if identity:
                text = re.sub(re.escape(identity), "[company]", text,
                              flags=re.IGNORECASE)
        text = re.sub(r"\bINE[A-Z0-9]{9}\b", "[isin]", text,
                      flags=re.IGNORECASE)
        text = re.sub(r"\bCIN\s*:?\s*[A-Z0-9-]+", "CIN: [redacted]", text,
                      flags=re.IGNORECASE)
        text = re.sub(r"\bDIN\s*:?\s*\d+", "DIN: [redacted]", text,
                      flags=re.IGNORECASE)
        text = re.sub(r"\bScrip\s+Code\s*:?\s*[A-Z0-9-]+",
                      "Scrip Code: [redacted]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
                      "[email]", text)
        text = re.sub(r"\b(?:https?://|www\.)\S+", "[website]", text,
                      flags=re.IGNORECASE)
        text = re.sub(r"\S+@\S+", "[email]", text)
        text = re.sub(
            r"\b(?:0?[1-9]|[12][0-9]|3[01])[-/.](?:0?[1-9]|1[0-2])"
            r"[-/.](?:19|20)\d{2}\b", "[date]", text)
        text = re.sub(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
            r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+(?:19|20)\d{2}\b",
            "[date]", text, flags=re.IGNORECASE)
        text = re.sub(
            r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
            r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?),?\s+(?:19|20)\d{2}\b",
            "[date]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:19|20)\d{2}\b", "[year]", text)

        # Most exchange PDFs begin with a letterhead and exchange addresses.
        # Keep the filing from its own subject/salutation, not the metadata
        # that makes the issuer trivially searchable. Signatures are equally
        # identifying and add no economic content.
        first = text[:2500]
        markers = [m for marker in (r"\n\s*Sub(?:ject)?\s*:", r"\n\s*Dear Sir")
                   if (m := re.search(marker, first, flags=re.IGNORECASE))]
        if markers:
            text = text[min(m.start() for m in markers):]
        close = re.search(r"\n\s*(?:Thanking you|Yours faithfully)", text,
                          flags=re.IGNORECASE)
        if close and close.start() > 200:
            text = text[:close.start()]

        noisy = re.compile(
            r"(?:national stock exchange|\bbse limited\b|exchange plaza|"
            r"pj towers|dalal street|bandra.kurla|registered office|"
            r"corporate office|CIN:\s*\[redacted\]|\[email\]|\[website\]|"
            r"\bT\s*\+91|\bF\s*\+91)", re.IGNORECASE)
        text = "\n".join(line for line in text.splitlines()
                         if not noisy.search(line))
        return text

    disclosures = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        disclosures.append({
            "subject": scrub(item.get("subject", "")),
            "details": scrub(item.get("details", "")),
            "attachment_text": scrub(item.get("attachment_text", "")),
        })
    return {
        "n_disclosures": len(disclosures),
        "disclosures": disclosures,
        "_caveat": (
            "published before this session's open; identity and calendar date "
            "removed, wording otherwise preserved" if anonymise else
            "published before this session's open"),
    }


def _analogues(row: pd.Series, history: pd.DataFrame, k: int,
               anonymise: bool) -> dict[str, Any]:
    """The k most similar situations that had already happened by date D.

    Legitimate, and worth being explicit about why: the outcome of a case from
    two years before the decision was *known* at the decision. What would not
    be legitimate is drawing analogues from the whole panel, so `history` is
    built strictly before D by the caller and the outcome column it carries is
    a realised past return, not a forward label.

    Reported with the spread as well as the mean. Five analogues whose outcomes
    range from -14% to +21% say something different from five that all landed
    near +2%, and collapsing them to an average hides exactly that.
    """
    feats = [f for f in ANALOGUE_FEATURES
             if f in history.columns and f in row.index]
    if not feats or history.empty or k < 1:
        return {"n": 0, "note": "no comparable prior situations available"}

    h = history[feats + ["analogue_outcome_pct"]].dropna()
    if len(h) < k * 4:
        return {"n": 0, "note": "too few comparable prior situations to draw on"}

    # Standardised on the *prior* distribution — the only one that existed.
    mu, sd = h[feats].mean(), h[feats].std().replace(0.0, np.nan)
    target = pd.Series({f: _as_float(row[f]) for f in feats})
    if target.isna().any():
        return {"n": 0, "note": "this situation is missing the comparison features"}
    z = (h[feats] - mu) / sd
    tz = (target - mu) / sd
    dist = np.sqrt(((z - tz) ** 2).sum(axis=1))
    near = h.loc[dist.nsmallest(k).index]

    outcomes = near["analogue_outcome_pct"].to_numpy(dtype=float)
    return {
        "n": int(len(near)),
        "note": ("the closest prior situations by shape, and what happened "
                 "next in each. Past cases only — every one had already "
                 "resolved before this decision."),
        "outcomes_pct": [_clean(v) for v in outcomes],
        "mean_pct": _clean(float(np.mean(outcomes))),
        "median_pct": _clean(float(np.median(outcomes))),
        "worst_pct": _clean(float(np.min(outcomes))),
        "best_pct": _clean(float(np.max(outcomes))),
        "share_positive_pct": _clean(float((outcomes > 0).mean() * 100)),
    }


def build_one(row: pd.Series, session: pd.DataFrame, bars: pd.DataFrame,
              history: pd.DataFrame, blocks: tuple[str, ...],
              anonymise: bool, history_sessions: int, n_analogues: int,
              case_id: str) -> Case:
    """One case. `session` is date D's whole cross-section; `history` is prior."""
    out: dict[str, Any] = {}

    if "announcement" in blocks:
        out["announcement"] = _announcement_block(row, anonymise)

    if "price_history" in blocks:
        out["price_history"] = _price_history(
            bars, str(row["symbol"]), pd.Timestamp(row["date"]),
            history_sessions, anonymise)

    for name in ("location", "market", "sector", "relative_strength",
                 "volatility_liquidity", "volume", "extension_contraction"):
        if name in blocks:
            out[name] = _select(row, BLOCK_COLUMNS[name], anonymise)

    if "sector" in blocks:
        # Present-day membership, carried under a name that says so. Opaque
        # under anonymisation: "my sector" has to be sayable without naming it.
        label = str(row.get("sector", "UNCLASSIFIED"))
        out["sector"]["group_id"] = (
            "G" + hashlib.sha256(label.encode()).hexdigest()[:4]
            if anonymise else label)
        out["sector"]["_caveat"] = (
            "sector and size are NSE's present-day classifications applied to "
            "this historical session, not facts recorded at the time")
        if not anonymise:
            out["sector"]["size_tier"] = _clean(row.get("size_tier"))

    if "quant" in blocks:
        out["quant"] = _quant_block(row, session,
                                    float(row.get("generator_score", 0.0)))

    if "analogues" in blocks:
        out["analogues"] = _analogues(row, history, n_analogues, anonymise)

    return Case(
        case_id=case_id,
        symbol=str(row["symbol"]),
        date=pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
        anonymised=bool(anonymise),
        generator_score=float(row.get("generator_score", 0.0)),
        generator_reason=str(row.get("generator_reason", "")),
        blocks=out,
    )


def build(candidates: pd.DataFrame, panel: pd.DataFrame, bars: pd.DataFrame,
          blocks: tuple[str, ...], anonymise: bool = True,
          history_sessions: int = 60, n_analogues: int = 5,
          analogue_horizon: int = 10, replay_id: str = "RPL") -> list[Case]:
    """Build every case in a candidate set.

    `panel` must be the as-of panel with context merged. `bars` are adjusted
    daily bars. Neither may carry a forward label, and the guard is called
    rather than assumed — a case built from a frame containing `fwd_ret_10d_pct`
    would be indistinguishable from a correct one by inspection.
    """
    assert_no_forward_labels(panel, context="case construction (panel)")
    assert_no_forward_labels(bars, context="case construction (bars)")

    if candidates.empty:
        return []

    key = ["symbol", "date"]
    merged = candidates.merge(panel, on=key, how="left", suffixes=("", "_panel"))
    missing = merged["close"].isna().sum() if "close" in merged else 0
    if missing:
        logger.warning("%d candidates had no panel row and are dropped", missing)
        merged = merged[merged["close"].notna()]

    bars = bars.sort_values(["symbol", "date"])
    analogue_pool = _analogue_pool(panel, bars, analogue_horizon) \
        if "analogues" in blocks else pd.DataFrame()

    cases: list[Case] = []
    sessions = {d: g for d, g in panel.groupby("date", sort=False)}
    for i, (_, row) in enumerate(merged.iterrows()):
        d = pd.Timestamp(row["date"])
        session = sessions.get(row["date"], panel.iloc[0:0])
        # Strictly before D. The analogue's own outcome window must also have
        # closed by D, which `_analogue_pool` already enforces.
        hist = (analogue_pool[analogue_pool["resolved_by"] < d]
                if not analogue_pool.empty else analogue_pool)
        cases.append(build_one(
            row, session, bars, hist, blocks, anonymise, history_sessions,
            n_analogues, case_id=f"{replay_id}_C{i:05d}"))
    return cases


def _analogue_pool(panel: pd.DataFrame, bars: pd.DataFrame,
                   horizon: int) -> pd.DataFrame:
    """Prior situations whose outcome had already printed, with that outcome.

    The subtle requirement is `resolved_by`, not the case's own date. A
    situation from three sessions before the decision has *not* resolved if the
    outcome takes ten sessions to arrive, and including it would hand the
    decider a return from after its own decision date. So each pooled row
    carries the session its outcome landed on, and the caller filters on that.
    """
    b = bars[["symbol", "date", "close"]].dropna().sort_values(["symbol", "date"])
    cal = np.sort(b["date"].unique())
    pos = pd.Series(np.arange(len(cal)), index=cal)

    fwd = b.groupby("symbol", sort=False)["close"].shift(-horizon)
    out = pd.DataFrame({
        "symbol": b["symbol"].to_numpy(),
        "date": b["date"].to_numpy(),
        "analogue_outcome_pct": ((fwd / b["close"] - 1.0) * 100.0).to_numpy(),
    })
    idx = out["date"].map(pos)
    out["resolved_by"] = cal[np.clip(idx.to_numpy() + horizon, 0, len(cal) - 1)]
    out = out[out["analogue_outcome_pct"].notna()]

    feats = [f for f in ANALOGUE_FEATURES if f in panel.columns]
    return out.merge(panel[["symbol", "date"] + feats], on=["symbol", "date"],
                     how="inner")


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

_HEADINGS = {
    "announcement": "CORPORATE DISCLOSURE KNOWN BEFORE THIS OPEN",
    "price_history": "PRICE HISTORY (rebased to 100 at the window start)",
    "location": "LOCATION IN THE RANGE",
    "market": "THE MARKET, as of the previous close",
    "sector": "THE SECTOR",
    "relative_strength": "RELATIVE STRENGTH",
    "volatility_liquidity": "VOLATILITY AND LIQUIDITY",
    "volume": "VOLUME AND DELIVERY",
    "extension_contraction": "EXTENSION AND CONTRACTION",
    "quant": "WHERE THIS SITS IN TODAY'S CROSS-SECTION",
    "analogues": "COMPARABLE PRIOR SITUATIONS",
}


def _ordered(name: str, body: dict[str, Any]) -> list[tuple[str, Any]]:
    """Block fields in a fixed order: declared first, then anything else sorted.

    Insertion order is not a property worth depending on. It survives a
    JSON round trip only by accident, and `sort_keys=True` destroys it — which
    silently changed `case_hash` on reload, so a cached decision would not have
    matched the case it was made against.
    """
    declared = [c for c in BLOCK_COLUMNS.get(name, ()) if c in body]
    rest = sorted(k for k in body if k not in declared and not k.startswith("_"))
    return [(k, body[k]) for k in declared + rest]


def render(case: Case) -> str:
    """The case as text. Deterministic — the hash depends on these bytes.

    Blocks are emitted in the canonical order of `_HEADINGS` and fields in the
    canonical order of `BLOCK_COLUMNS`, never in whatever order the dict
    happens to hold. That keeps the hash stable across serialisation, and it
    keeps the prompt prefix byte-identical between cases, which is what lets it
    cache.
    """
    lines: list[str] = []
    if case.anonymised:
        lines.append("SITUATION (identity withheld; prices rebased, dates "
                     "given as sessions before the decision)")
    else:
        lines.append(f"SITUATION: {case.symbol} on {case.date}")
    lines.append(f"How it was selected for review: {case.generator_reason}")
    lines.append("")

    ordered_blocks = ([n for n in _HEADINGS if n in case.blocks]
                      + sorted(n for n in case.blocks if n not in _HEADINGS))
    for name in ordered_blocks:
        body = case.blocks[name]
        lines.append(f"## {_HEADINGS.get(name, name.upper())}")
        if name == "price_history":
            lines.append(body.get("summary", ""))
            if body.get("bars"):
                lines.append("")
                lines.append("t | open | high | low | close | volume vs median")
                for r in body["bars"]:
                    lines.append(
                        f"{r['t']} | {r['o']} | {r['h']} | {r['l']} | "
                        f"{r['c']} | {r['vol_x_median']}")
        elif name == "announcement":
            lines.append(f"number of disclosures: {body.get('n_disclosures', 0)}")
            for i, item in enumerate(body.get("disclosures", []), 1):
                lines.append(f"disclosure {i} subject: {item.get('subject', '')}")
                lines.append(f"disclosure {i} text: {item.get('details', '')}")
                if item.get("attachment_text"):
                    lines.append(
                        f"disclosure {i} attachment text: "
                        f"{item.get('attachment_text', '')}")
            if "_caveat" in body:
                lines.append(f"note: {body['_caveat']}")
        else:
            for k, v in _ordered(name, body):
                if k in BOOLEAN_COLUMNS and v is not None:
                    v = "yes" if float(v) else "no"
                lines.append(f"{k}: {v}")
            if "_caveat" in body:
                lines.append(f"note: {body['_caveat']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def case_set_hash(cases: list[Case]) -> str:
    """One hash over the whole case set — the third term of a test's identity."""
    h = hashlib.sha256()
    for c in cases:
        h.update(c.case_hash.encode())
    return h.hexdigest()[:16]


def to_jsonl(cases: list[Case]) -> str:
    return "".join(json.dumps(c.to_dict(), sort_keys=True, default=str) + "\n"
                   for c in cases)


def from_jsonl(text: str) -> list[Case]:
    return [Case.from_dict(json.loads(line))
            for line in text.splitlines() if line.strip()]
