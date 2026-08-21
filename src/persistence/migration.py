"""Migration tool to parse and ingest HYPOTHESES.md into the research store (PLAN.md line 677).

Migrates H001–H038 into first-class Hypothesis and Evidence records, maps
lineage edges, and records historical partition exposure into the SampleBudgetLedger.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core import config
from . import ledger, models, store


HYPOTHESES_MD_PATH = config.PROJECT_ROOT / "HYPOTHESES.md"


STATUS_MAP = {
    "SUPPORTED": "promising",
    "REJECTED": "rejected",
    "SUPERSEDED": "superseded",
    "PROPOSED": "proposed",
    "TESTING": "exploring",
    "INCONCLUSIVE": "exploring",
}


def infer_family(h_id: str, title: str, body: str) -> str:
    """Classifies a hypothesis into its thematic family."""
    t_lower = (title + " " + body).lower()
    if int(h_id[1:]) in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 21, 22, 23, 33):
        return "opening_window"
    if int(h_id[1:]) in (34, 35, 36, 37, 38):
        return "resilience"
    if int(h_id[1:]) in (15, 16, 17, 18, 19, 20, 24, 25, 26, 27, 28, 29, 30, 31, 32):
        return "discovery"
    return "general"


def extract_edges(body: str, current_id: str) -> list[models.Edge]:
    """Finds cross-references to other hypotheses and infers relation types."""
    edges = []
    # Match H001..H038 mentions
    refs = re.findall(r"\b(H\d{3})\b", body)
    unique_refs = [r for r in set(refs) if r != current_id]

    for ref in unique_refs:
        # Default relation: adjacent-to or specialises
        rel = "adjacent-to"
        if "supersede" in body.lower() or "replaces" in body.lower():
            rel = "retest-of"
        elif "conditions" in body.lower():
            rel = "conditions-on"
        elif "specialises" in body.lower():
            rel = "specialises"
        edges.append(models.Edge(target_id=ref, relation=rel))

    return edges


def parse_hypotheses_md(path: Path | None = None) -> list[models.Hypothesis]:
    """Parses HYPOTHESES.md and returns a list of Hypothesis model objects."""
    p = path or HYPOTHESES_MD_PATH
    if not p.exists():
        raise FileNotFoundError(f"HYPOTHESES.md not found at {p}")

    text = p.read_text(encoding="utf-8")
    # Split on markdown H2 headers "## H0XX"
    sections = re.split(r"\n##\s+(H\d{3})\s+[—\-]\s+", text)
    if len(sections) < 3:
        raise ValueError("Failed to parse sections in HYPOTHESES.md")

    hypotheses = []

    # sections[0] is preamble, then alternating (id, content)
    for i in range(1, len(sections), 2):
        h_id = sections[i]
        content = sections[i + 1]

        # Extract title (first line before newline)
        title_line = content.split("\n", 1)[0].strip()
        body = content.split("\n", 1)[1] if "\n" in content else ""

        # Extract status
        status_match = re.search(r"Status:\s*\*\*([A-Z_]+)\*\*", body)
        raw_status = status_match.group(1) if status_match else "PROPOSED"
        status = STATUS_MAP.get(raw_status, "exploring")

        # Extract statement / rationale
        hyp_text = ""
        hyp_match = re.search(r"\*\*Hypothesis:\*\*\s*\n(.*?)(?=\n\*\*|\n---|\Z)", body, re.DOTALL)
        if hyp_match:
            hyp_text = hyp_match.group(1).strip()
        else:
            hyp_text = title_line

        family = infer_family(h_id, title_line, body)
        edges = extract_edges(body, h_id)

        h = models.Hypothesis(
            id=h_id,
            title=title_line,
            statement=hyp_text,
            rationale=f"Migrated from HYPOTHESES.md ({raw_status})",
            status=status,
            family=family,
            edges=edges,
            tags=[family, f"status_{status}"],
        )
        hypotheses.append(h)

    return hypotheses


def migrate(save_to_store: bool = True) -> tuple[list[models.Hypothesis], ledger.SampleBudgetLedger]:
    """Executes the full migration of HYPOTHESES.md and initializes the ledger."""
    hyps = parse_hypotheses_md()

    if save_to_store:
        for h in hyps:
            store.save_hypothesis(h)

    # Initialize and save the sample budget ledger
    l = ledger.SampleBudgetLedger.load()

    # Historical exposure is NOT re-recorded here. It is seeded from
    # `splits.PRIOR_EXPOSURE` inside the ledger itself, which is the single
    # authority. This block used to hardcode its own quarter lists and cover
    # only two families, so `discovery` — which holds H024 and H026, the two
    # rules H033 actually spent the holdout on — got no exposure at all.

    if save_to_store:
        l.save()

    return hyps, l
