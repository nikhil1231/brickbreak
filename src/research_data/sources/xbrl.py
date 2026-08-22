"""The raw XBRL archive, and a faithful reader for it.

TWO JOBS, KEPT SEPARATE ON PURPOSE

**Archiving.** `archive` downloads a filing and stores it under the SHA-256 of
its own bytes, with a manifest recording which filing_id and URL produced that
hash. Content addressing is the point: NSE re-hosts and rewrites, so a URL is
not an identity. If a restatement silently replaces a file at the same URL, the
archive gains a second hash against the same URL and the change is visible
instead of invisible. Nothing here ever overwrites a stored filing.

**Reading.** `parse_facts` returns the filing's contents as a *long* table —
one row per reported fact, carrying the element name, the context it was
reported in, that context's period and dimensions, the unit and the raw text
alongside the parsed number. It does not map anything onto a house schema.

That second decision is the important one. The obvious next step is a wide
table with `revenue`, `pat`, `eps` columns, and it is a trap: these filings use
the `in-bse-fin` taxonomy, whose element for "revenue" differs between the
banking and non-banking variants, between Ind-AS and pre-Ind-AS filings, and
between the 2019 and integrated-filing schemas — and every fact is reported
several times over, once per context (quarter, year-to-date, prior-year
comparative, consolidated segment). Picking one silently is how a number ends
up meaning something other than its column name says, which is this project's
characteristic failure in a new place.

**THE PERIOD DOES NOT IDENTIFY A FACT.** This is not a general worry about
taxonomies; it is a measured property of these files. HDFC Bank's Q3 FY25
filing declares contexts `OneD` and `FourD` with the *same* entity, the *same*
start and end date, and *no* dimensions — and reports InterestEarned as
850,401,700,000 against one and 2,495,881,300,000 against the other. The first
is the quarter, the second the nine months to date; the dates on the
year-to-date context are simply wrong, and the column position survives only
in the context *id*. Across three filings checked: 30 ambiguous
(element, period, dimensions) groups in HDFC Bank's banking filing, 37 in
Reliance's non-banking one, 0 in the integrated-regime filing. So a reduction
keyed on (element, period) picks one of two different numbers by row order in
roughly a third of the line items of any pre-2025 filing.

`context_ref` is therefore carried on every row and must be part of any
selection. `ambiguous_facts` reports exactly these collisions, so a caller
building a wide view can assert their reduction is unambiguous instead of
hoping.

So the long table is what this module promises. Reducing it to a house schema
is a modelling decision that belongs with the person making the claim, and
`facts_for` exists to make that reduction explicit: name the elements and the
context you want, and get back what the filing actually said.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from ...core import config
from . import nse_api

ARCHIVE_DIR = config.RAW_DIR / "xbrl"
MANIFEST_PATH = config.METADATA_DIR / "xbrl_manifest.parquet"

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"

MANIFEST_COLUMNS = ["filing_id", "symbol", "url", "sha256", "n_bytes",
                    "fetched_at", "status"]

FACT_COLUMNS = ["prefix", "element", "context_ref", "period_start",
                "period_end", "instant", "dimensions", "unit", "decimals",
                "value_text", "value_num"]


def blob_path(sha: str) -> Path:
    """Content-addressed location. Sharded so one directory stays listable."""
    return ARCHIVE_DIR / sha[:2] / f"{sha}.xml"


def store(content: bytes) -> tuple[str, Path]:
    """Write bytes under their own hash. Returns (sha256, path)."""
    sha = hashlib.sha256(content).hexdigest()
    path = blob_path(sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return sha, path


def read(sha: str) -> bytes:
    return blob_path(sha).read_bytes()


# ---------------------------------------------------------------- archiving

def archive(rows: list[dict], *, throttle: float = 0.5, timeout: int = 90,
            verbose: bool = True) -> pd.DataFrame:
    """Download and store filings. `rows` need `filing_id`, `symbol`, `url`.

    The archive host (`nsearchives`) is a plain static file server, so this
    does not need the primed website session the metadata endpoints require —
    only a browser User-Agent.

    Already-archived (filing_id, url) pairs are skipped, which makes this
    resumable: a run interrupted at filing 4,000 of 40,000 picks up there.
    Failures are recorded in the manifest with their status rather than being
    retried forever or dropped, so a partial archive can state its own gaps.
    """
    import time

    manifest = load_manifest()
    seen = set(zip(manifest["filing_id"], manifest["url"])) if len(manifest) else set()
    out, last = [], 0.0
    for i, row in enumerate(rows, 1):
        url = row.get("url")
        if not url or (row.get("filing_id"), url) in seen:
            continue
        gap = time.monotonic() - last
        if gap < throttle:
            time.sleep(throttle - gap)
        last = time.monotonic()
        rec = {"filing_id": row.get("filing_id"), "symbol": row.get("symbol"),
               "url": url, "sha256": None, "n_bytes": 0,
               "fetched_at": datetime.now(), "status": "ok"}
        try:
            r = requests.get(url, headers=nse_api.HEADERS, timeout=timeout)
        except requests.RequestException as exc:
            rec["status"] = f"error:{type(exc).__name__}"
        else:
            if r.status_code != 200 or not r.content.strip():
                rec["status"] = f"http:{r.status_code}"
            else:
                sha, _ = store(r.content)
                rec["sha256"] = sha
                rec["n_bytes"] = len(r.content)
        out.append(rec)
        if verbose and i % 100 == 0:
            ok = sum(1 for x in out if x["status"] == "ok")
            print(f"  xbrl {i}/{len(rows)} stored={ok} failed={len(out)-ok}",
                  flush=True)
    if not out:
        return manifest
    merged = pd.concat([manifest, pd.DataFrame(out)], ignore_index=True)
    merged = merged.drop_duplicates(subset=["filing_id", "url", "sha256"])
    save_manifest(merged)
    return merged


def load_manifest() -> pd.DataFrame:
    if not MANIFEST_PATH.exists():
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    return pd.read_parquet(MANIFEST_PATH)


def save_manifest(df: pd.DataFrame) -> Path:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(MANIFEST_PATH, index=False)
    return MANIFEST_PATH


# ------------------------------------------------------------------ reading

def _local(tag: str) -> tuple[str, str]:
    """Split "{ns}name" into a short prefix hint and the local name."""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns.rsplit("/", 1)[-1], local
    return "", tag


def _contexts(root) -> dict[str, dict]:
    """Map contextRef -> period and dimensions.

    A fact is meaningless without its context: the same element carries the
    quarter, the year to date and the prior-year comparative in one filing,
    distinguished only by which context it points at.
    """
    out: dict[str, dict] = {}
    for ctx in root.findall(f"{{{XBRLI}}}context"):
        cid = ctx.get("id")
        if not cid:
            continue
        rec = {"period_start": None, "period_end": None, "instant": None,
               "dimensions": None}
        period = ctx.find(f"{{{XBRLI}}}period")
        if period is not None:
            for field, tag in (("period_start", "startDate"),
                               ("period_end", "endDate"),
                               ("instant", "instant")):
                el = period.find(f"{{{XBRLI}}}{tag}")
                if el is not None and el.text:
                    rec[field] = el.text.strip()
        dims = []
        for member in ctx.iter(f"{{{XBRLDI}}}explicitMember"):
            axis = (member.get("dimension") or "").split(":")[-1]
            value = (member.text or "").strip().split(":")[-1]
            dims.append(f"{axis}={value}")
        rec["dimensions"] = "|".join(sorted(dims)) or None
        out[cid] = rec
    return out


def _units(root) -> dict[str, str]:
    out = {}
    for unit in root.findall(f"{{{XBRLI}}}unit"):
        uid = unit.get("id")
        measures = [(m.text or "").strip().split(":")[-1]
                    for m in unit.iter(f"{{{XBRLI}}}measure")]
        if uid:
            out[uid] = "/".join(m for m in measures if m) or None
    return out


def parse_facts(content: bytes) -> pd.DataFrame:
    """Every reported fact in one filing, with its context resolved.

    Elements carrying a `contextRef` are facts; everything else is structure.
    `value_num` is populated only where the text parses as a number, so
    narrative disclosures survive in `value_text` instead of becoming NaN rows.
    """
    # lxml is imported here rather than at module scope so that a machine
    # with no XML parser can still *collect* — the deals and announcement
    # feeds need nothing but requests, and a package-level import would take
    # them down with it. That is not hypothetical: it broke the first deploy
    # of this package to the pull server.
    from lxml import etree

    if not content.strip():
        return pd.DataFrame(columns=FACT_COLUMNS)
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    root = etree.fromstring(content, parser=parser)
    if root is None:
        return pd.DataFrame(columns=FACT_COLUMNS)

    contexts = _contexts(root)
    units = _units(root)
    rows = []
    for el in root.iter():
        ctx_ref = el.get("contextRef")
        if ctx_ref is None:
            continue
        prefix, name = _local(el.tag)
        text = (el.text or "").strip()
        ctx = contexts.get(ctx_ref, {})
        rows.append({
            "prefix": prefix,
            "element": name,
            "context_ref": ctx_ref,
            "period_start": ctx.get("period_start"),
            "period_end": ctx.get("period_end"),
            "instant": ctx.get("instant"),
            "dimensions": ctx.get("dimensions"),
            "unit": units.get(el.get("unitRef") or ""),
            "decimals": el.get("decimals"),
            "value_text": text or None,
            # `nil` facts are explicitly "not reported", which is different
            # from a zero and different from an absent element.
            "value_num": pd.to_numeric(text, errors="coerce") if text else None,
        })
    if not rows:
        return pd.DataFrame(columns=FACT_COLUMNS)
    df = pd.DataFrame(rows)
    for c in ("period_start", "period_end", "instant"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df[FACT_COLUMNS]


def facts_for(content: bytes, elements: list[str], *,
              dimensions: str | None = None) -> pd.DataFrame:
    """The named elements only, optionally restricted to one context shape.

    This is the explicit reduction the module docstring argues for: a caller
    naming `["RevenueFromOperations", "ProfitLossForPeriod"]` and
    `dimensions=None` (the undimensioned, entity-level context) is stating
    which taxonomy elements their claim depends on, in code, where it can be
    reviewed — rather than a mapping table deciding it for them.
    """
    facts = parse_facts(content)
    if facts.empty:
        return facts
    want = {e.lower() for e in elements}
    out = facts[facts["element"].str.lower().isin(want)]
    if dimensions is None:
        out = out[out["dimensions"].isna()]
    else:
        out = out[out["dimensions"] == dimensions]
    return out.reset_index(drop=True)


def ambiguous_facts(facts: pd.DataFrame) -> pd.DataFrame:
    """(element, period, dimensions) groups reporting more than one value.

    Every row this returns is a place where the filing says two different
    things under labels that a (element, period) reduction cannot tell apart —
    the `OneD`/`FourD` collision described above. A caller flattening facts
    into named columns should require this to be empty over the elements it
    selects, or disambiguate on `context_ref` explicitly.
    """
    if facts.empty:
        return facts.assign(n_values=pd.Series(dtype=int))
    numeric = facts[facts["value_num"].notna()]
    key = ["element", "period_start", "period_end", "dimensions"]
    grouped = (numeric.groupby(key, dropna=False)
               .agg(n_values=("value_num", "nunique"),
                    contexts=("context_ref", lambda s: "|".join(sorted(set(s)))))
               .reset_index())
    return grouped[grouped["n_values"] > 1].reset_index(drop=True)


__all__ = ["ARCHIVE_DIR", "FACT_COLUMNS", "MANIFEST_PATH", "ambiguous_facts", "archive",
           "blob_path", "facts_for", "load_manifest", "parse_facts", "read",
           "save_manifest", "store"]
