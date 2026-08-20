"""The four core research objects and the idea graph (PLAN.md §3).

THE FOUR OBJECTS:
Hypothesis  ->  Exploration  ->  Signal  ->  Evidence

- Hypothesis: A durable idea with a stable ID, in natural language, with an
  economic or behavioural rationale.
- Exploration: One concrete, immutable investigation of a hypothesis.
- Signal: A named, versioned, computable cross-sectional score over the universe.
- Evidence: One measured result attached to a signal or hypothesis, tagged with
  the partition and its role (generation, exploratory, confirmatory).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


HYPOTHESIS_STATUSES = (
    "proposed",
    "exploring",
    "promising",
    "rejected",
    "validated",
    "decayed",
    "superseded",
)

RELATION_TYPES = (
    "specialises",
    "generalises",
    "conditions-on",
    "contradicts",
    "subsumed-by",
    "adjacent-to",
    "retest-of",
)

FAILURE_CLASSES = (
    "NO_SIGNAL",
    "SIGNAL_BUT_BETA",
    "SIGNAL_ONLY_ONE_REGIME",
    "SIGNAL_TOO_SMALL",
    "HIGH_TURNOVER",
    "UNSTABLE",
    "LIKELY_OVERFIT",
    "INSUFFICIENT_SAMPLE",
    "DATA_QUALITY",
    "REDUNDANT_WITH_EXISTING_ALPHA",
    "SUCCESS",
)

EVIDENCE_ROLES = (
    "generation",
    "exploratory",
    "confirmatory",
)


@dataclass(frozen=True)
class Edge:
    """A typed relationship pointing from one hypothesis to another."""
    target_id: str
    relation: str

    def __post_init__(self) -> None:
        if self.relation not in RELATION_TYPES:
            raise ValueError(f"invalid relation {self.relation!r}; must be one of {RELATION_TYPES}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Hypothesis:
    """A durable research hypothesis."""
    id: str
    title: str
    statement: str
    rationale: str
    status: str = "proposed"
    family: str = "general"
    edges: list[Edge] = field(default_factory=list)
    created_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"invalid status {self.status!r}; must be one of {HYPOTHESIS_STATUSES}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["edges"] = [e.to_dict() if isinstance(e, Edge) else e for e in self.edges]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Hypothesis:
        d = dict(data)
        d["edges"] = [Edge(**e) if isinstance(e, dict) else e for e in d.get("edges", [])]
        return cls(**d)


@dataclass
class Exploration:
    """One immutable investigation of a hypothesis."""
    id: str
    hypothesis_id: str
    spec: dict[str, Any]
    verdict: str
    failure_class: str
    signals_produced: list[str] = field(default_factory=list)
    manifest_hash: str = ""
    created_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def __post_init__(self) -> None:
        if self.failure_class not in FAILURE_CLASSES:
            raise ValueError(f"invalid failure_class {self.failure_class!r}; must be one of {FAILURE_CLASSES}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Exploration:
        return cls(**data)


@dataclass
class Signal:
    """A named cross-sectional score."""
    name: str
    owner_hypothesis_id: str
    definition: str
    coverage_profile: dict[str, Any] = field(default_factory=dict)
    turnover_profile: dict[str, Any] = field(default_factory=dict)
    created_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Signal:
        return cls(**data)


@dataclass
class Evidence:
    """One measured empirical result attached to a hypothesis/signal."""
    id: str
    hypothesis_id: str
    signal_id: str
    exploration_id: str
    role: str
    dataset_version: str
    partition: str
    metrics: dict[str, Any]
    verdict_statement: str
    manifest_hash: str = ""
    created_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def __post_init__(self) -> None:
        if self.role not in EVIDENCE_ROLES:
            raise ValueError(f"invalid role {self.role!r}; must be one of {EVIDENCE_ROLES}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Evidence:
        return cls(**data)


# ---------------------------------------------------------------------------
# Idea Graph
# ---------------------------------------------------------------------------

class IdeaGraph:
    """Graph structure connecting hypotheses via typed edges."""

    def __init__(self, hypotheses: list[Hypothesis] | None = None) -> None:
        self._nodes: dict[str, Hypothesis] = {}
        self._adjacency: dict[str, list[Edge]] = {}
        self._reverse_adjacency: dict[str, list[tuple[str, str]]] = {}  # target -> [(source, relation)]

        if hypotheses:
            for h in hypotheses:
                self.add_hypothesis(h)

    def add_hypothesis(self, h: Hypothesis) -> None:
        self._nodes[h.id] = h
        self._adjacency.setdefault(h.id, [])
        self._reverse_adjacency.setdefault(h.id, [])

        for edge in h.edges:
            self._adjacency[h.id].append(edge)
            self._reverse_adjacency.setdefault(edge.target_id, []).append((h.id, edge.relation))

    def get_hypothesis(self, id: str) -> Hypothesis | None:
        return self._nodes.get(id)

    def neighbors(self, id: str) -> list[Edge]:
        """Outgoing edges from hypothesis id."""
        return self._adjacency.get(id, [])

    def incoming(self, id: str) -> list[tuple[str, str]]:
        """Incoming edges to hypothesis id: list of (source_id, relation)."""
        return self._reverse_adjacency.get(id, [])

    def ancestors(self, id: str) -> set[str]:
        """Set of all hypotheses this hypothesis specializes, conditions on, or retests."""
        visited: set[str] = set()
        queue = [id]
        while queue:
            curr = queue.pop(0)
            for edge in self._adjacency.get(curr, []):
                if edge.relation in ("specialises", "conditions-on", "retest-of", "subsumed-by"):
                    if edge.target_id not in visited:
                        visited.add(edge.target_id)
                        queue.append(edge.target_id)
        return visited

    def descendants(self, id: str) -> set[str]:
        """Set of all hypotheses derived from this hypothesis."""
        visited: set[str] = set()
        queue = [id]
        while queue:
            curr = queue.pop(0)
            for src_id, rel in self._reverse_adjacency.get(curr, []):
                if rel in ("specialises", "conditions-on", "retest-of", "subsumed-by"):
                    if src_id not in visited:
                        visited.add(src_id)
                        queue.append(src_id)
        return visited

    def related_family(self, id: str) -> set[str]:
        """All hypotheses in the connected component (lineage and relations)."""
        h = self._nodes.get(id)
        if not h:
            return set()
        res = {id}
        res.update(self.ancestors(id))
        res.update(self.descendants(id))
        # Include same family members
        for other_id, other_h in self._nodes.items():
            if other_h.family == h.family:
                res.add(other_id)
        return res

    def summary(self) -> str:
        n_nodes = len(self._nodes)
        n_edges = sum(len(edges) for edges in self._adjacency.values())
        return f"IdeaGraph: {n_nodes} hypotheses, {n_edges} typed edges"
