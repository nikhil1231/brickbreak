"""Who the counterparty is, from a free-text name and nothing else.

WHY THIS IS NOT COSMETIC
`events` separates position takers from market makers by *behaviour* — did the
client end the session flat. That is the right primary split and it is
outcome-free, but it says nothing about **what kind** of participant took the
position. "A promoter sold 2% of the company" and "an index fund rebalanced"
are the same row in NSE's file and opposite events in every other respect.

The counterparty question is the one MISSION and the archived plan both put
highest — name who is on the other side and why they keep taking it. For most
of this project it had no answer. Here it is written on the row.

TWO PROBLEMS THE FILE HANDS YOU
**Spelling.** The same entity appears many times over:

    QE SECURITIES LLP / QE SECURITIES
    NK SECURITIES RESEARCH PRIVATE LIMITED / N.K. SECURITIES
    ADROIT FINANCIAL SERVICES PRIVATE LIMITED / ADROIT FINANCIAL SERVICES PVT LTD
    ASIT C MEHTA INVESTMENT INTERMEDIATES LTD. / ... INTERRMEDIATES ... / ... INTERRM

This is not tidiness. `events.client_profile` needs ten prior sessions before it
will classify anyone, so an entity split across three spellings can carry
thirty sessions of history and be called `unknown` in all three. Normalising is
what makes the point-in-time profile work at all.

**A long tail.** 29,123 distinct names; the top 500 are 59% of rows. A curated
list cannot cover it, so this is rules first, with a curated override only where
a name is genuinely unguessable from its text (the global prop firms, mostly).

WHAT THE TAXONOMY IS FOR, AND ITS LIMIT
A label here is a hypothesis about a name, not a fact about an entity. "PATEL
MANAV NARESHBHAI" is an individual with high confidence; "OLGA TRADING PRIVATE
LIMITED" could be a family office, a treasury or a prop desk and is labelled
`corporate` because that is all the string supports. Every classification
carries its confidence, and `unknown` is used rather than guessed.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Legal-form noise. Stripped before matching so that "PVT LTD", "PRIVATE
# LIMITED", "P. LTD" and "PVT. LTD." collapse to the same entity.
_SUFFIXES = (
    r"PRIVATE LIMITED", r"PVT\.? LTD\.?", r"PVT\.? LIMITED", r"P\.? LTD\.?",
    r"PUBLIC LIMITED", r"LIMITED", r"LTD\.?", r"LLP", r"LLC", r"INC\.?",
    r"CO\.?$", r"COMPANY", r"S\.A\.?", r"PLC", r"GMBH", r"N\.V\.?", r"AG",
)
_SUFFIX_RE = re.compile(r"\b(?:" + "|".join(_SUFFIXES) + r")\b\.?", re.I)
_PUNCT_RE = re.compile(r"[^A-Z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")

# Common misspellings and abbreviations seen in the file, mapped to one form.
_ALIASES = {
    "INTERRMEDIATES": "INTERMEDIATES",
    "INTERRM": "INTERMEDIATES",
    "SECURITES": "SECURITIES",
    "SEC": "SECURITIES",
    "ADVISOR": "ADVISORS",
    "ADV": "ADVISORS",
    "SHARE": "SHARES",
    "STOCKS": "STOCK",
    "AND": "&",
}

# Firms whose business is intraday liquidity provision. A name alone will never
# reveal this — "GRAVITON RESEARCH CAPITAL" reads like an asset manager — so it
# is the one place a curated list earns its keep. Matched on the normalised
# form, as a prefix, so spelling variants are covered.
PROP_FIRMS = (
    "GRAVITON RESEARCH CAPITAL", "HRTI", "NK SECURITIES RESEARCH",
    "N K SECURITIES", "QE SECURITIES", "TOWER RESEARCH CAPITAL",
    "XTX MARKETS", "JUMP TRADING", "CITADEL SECURITIES", "CROSSLAND TRADING",
    "ALPHAGREP", "IRAGE", "JUNOMONETA", "ALPHA LEON", "AAKRAYA RESEARCH",
    "MICROCURVES", "SHAASTRA SECURITIES", "MATHISYS", "OLGA TRADING",
    "CROSSEAS CAPITAL", "BNP PARIBAS ARBITRAGE", "SURJECTIVE RESEARCH",
    "QUADEYE", "OPTIVER", "IMC TRADING", "DA VINCI", "FLOW TRADERS",
    "SUSQUEHANNA", "MILLENNIUM", "HUDSON RIVER", "VIRTU",
)

_FOREIGN_MARKERS = ("MAURITIUS", "SINGAPORE", "CAYMAN", "LUXEMBOURG",
                    "IRELAND", "CYPRUS", "NETHERLANDS", "ESPANA", "PLC",
                    "OFFSHORE", "GLOBAL OPPORTUNITIES", "EMERGING MARKETS",
                    "ODI", "FII", "FPI", "MASTER FUND", "SICAV")
_FUND_MARKERS = ("MUTUAL FUND", "MUTUALFUND", "ASSET MANAGEMENT", " AMC",
                 "TRUSTEE", "INVESTMENT TRUST", "PENSION", "PROVIDENT")
_INSURANCE_MARKERS = ("INSURANCE", "ASSURANCE", "LIFE INSURANCE", "GIC ",
                      "GENERAL INSURANCE")
_BANK_MARKERS = ("BANK", "NBFC", "FINANCE CORPORATION", "HOUSING FINANCE")
_BROKER_MARKERS = ("SECURITIES", "STOCK BROK", "SHARES & STOCK", "BROKING",
                   "BROKERS", "SHARE & STOCK", "STOCK AND", "COMMODITIES",
                   "INTERMEDIATES", "CAPITAL MARKETS", "FINTRADE", "TRADEFIN")
_CORPORATE_MARKERS = ("ENTERPRISES", "VENTURES", "INDUSTRIES", "TRADING",
                      "INFRA", "REALTY", "EXPORTS", "TECHNOLOGIES", "SERVICES",
                      "CONSULTANTS", "HOLDINGS", "INVESTMENTS", "FINCOT",
                      "VYAPAR", "TRADEMAX", "ADVISORS", "WEALTH")

# An individual, in NSE's file, is a bare personal name — two to four tokens,
# no corporate marker anywhere. `(HUF)` is a Hindu Undivided Family, which is a
# household rather than an institution and belongs with individuals.
_HUF_RE = re.compile(r"\(?\bHUF\b\)?", re.I)

CATEGORIES = ("prop_hft", "broker", "mutual_fund", "insurance",
              "foreign_portfolio", "bank_nbfc", "promoter_related",
              "individual", "corporate", "unknown")


def normalise(name: str) -> str:
    """Canonical form: no legal suffix, no punctuation, spellings collapsed."""
    s = str(name).upper().strip()
    s = _HUF_RE.sub(" HUF ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _SUFFIX_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    tokens = [_ALIASES.get(t, t) for t in s.split()]
    return " ".join(tokens).strip()


def _has(text: str, markers: tuple[str, ...]) -> bool:
    return any(m.strip() in text for m in markers)


def classify(name: str, security_name: str | None = None) -> tuple[str, float]:
    """`(category, confidence)`. Order matters: the specific beats the generic."""
    n = normalise(name)
    if not n:
        return "unknown", 0.0

    if any(n.startswith(p) for p in PROP_FIRMS):
        return "prop_hft", 0.95
    if "HUF" in n.split():
        return "individual", 0.90
    if _has(n, _FUND_MARKERS):
        return "mutual_fund", 0.90
    if _has(n, _INSURANCE_MARKERS):
        return "insurance", 0.90
    if _has(n, _FOREIGN_MARKERS):
        return "foreign_portfolio", 0.80

    # Before the generic buckets: does this name look like the issuer's own
    # people? Promoter entities routinely share a distinctive token with the
    # company — "BAJAJ HOLDINGS" against "BAJAJ AUTO". Common words are
    # excluded or every Indian company matches every other.
    if security_name:
        share = _issuer_overlap(n, normalise(security_name))
        if share >= 0.5:
            return "promoter_related", 0.70

    if _has(n, _BANK_MARKERS):
        return "bank_nbfc", 0.75
    if _has(n, _BROKER_MARKERS):
        return "broker", 0.70
    if _has(n, _CORPORATE_MARKERS):
        return "corporate", 0.60

    tokens = n.split()
    if 2 <= len(tokens) <= 4 and all(t.isalpha() for t in tokens):
        return "individual", 0.65
    return "unknown", 0.0


_STOPWORDS = frozenset((
    "INDIA", "INDIAN", "THE", "OF", "&", "AND", "NEW", "GROUP", "HOLDINGS",
    "INVESTMENTS", "ENTERPRISES", "VENTURES", "INDUSTRIES", "CORPORATION",
    "COMPANY", "TRADING", "SERVICES", "FINANCE", "CAPITAL", "NATIONAL"))


def _issuer_overlap(client: str, security: str) -> float:
    """Share of the client's distinctive tokens that also name the issuer."""
    c = {t for t in client.split() if t not in _STOPWORDS and len(t) > 3}
    s = {t for t in security.split() if t not in _STOPWORDS and len(t) > 3}
    if not c or not s:
        return 0.0
    return len(c & s) / len(c)


def classify_frame(deals: pd.DataFrame) -> pd.DataFrame:
    """Add `client_key`, `client_type` and `client_type_confidence`.

    `client_key` is the normalised name and is what every downstream grouping
    should use — grouping on the raw string splits one entity into several and
    starves the point-in-time profile of history.
    """
    d = deals.copy()
    d["client_key"] = d["client_name"].map(normalise)
    sec = d["security_name"] if "security_name" in d.columns else None

    pairs = [classify(k, s) for k, s in zip(
        d["client_key"], sec if sec is not None else [None] * len(d))]
    d["client_type"] = [p[0] for p in pairs]
    d["client_type_confidence"] = [p[1] for p in pairs]
    return d


def coverage(classified: pd.DataFrame) -> pd.DataFrame:
    """What the taxonomy caught, by rows and by distinct entities."""
    g = classified.groupby("client_type")
    out = g.agg(rows=("client_key", "size"),
                entities=("client_key", "nunique"),
                mean_confidence=("client_type_confidence", "mean"))
    out["row_share_pct"] = (100 * out["rows"] / len(classified)).round(1)
    out["mean_confidence"] = out["mean_confidence"].round(2)
    return out.sort_values("rows", ascending=False)
