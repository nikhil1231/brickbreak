"""Batch pre-registration and commitment freezing (PLAN.md §5, Stage 3).

Freezes N candidate specifications in a cryptographic manifest BEFORE any
member of the batch is scored. This prevents cherry-picking and enables
Benjamini-Hochberg false-discovery rate correction across the pre-registered batch.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from ..persistence import BatchManifest, store
from .spec import ExperimentSpec

logger = logging.getLogger(__name__)


def compute_batch_hash(specs: list[dict[str, Any]]) -> str:
    """Deterministic cryptographic fingerprint of a batch of experiment specs."""
    raw = json.dumps(specs, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def preregister_batch(
    proposal_ids: list[str],
    partition: str = "train",
    role: str = "exploratory",
    primary_horizon: int = 10,
) -> BatchManifest:
    """Pre-register and freeze a batch of candidate proposals before scoring."""
    if not proposal_ids:
        raise ValueError("Cannot pre-register an empty batch of proposals.")

    specs: list[dict[str, Any]] = []
    valid_proposals = []

    for pid in proposal_ids:
        prop = store.get_proposal(pid)
        if not prop:
            raise KeyError(f"Proposal {pid!r} not found in store.")

        exp_spec = ExperimentSpec(
            hypothesis_id=prop.hypothesis_id,
            question=prop.question,
            signal_name=prop.signal_name,
            partition=partition,
            role=role,
            primary_horizon=primary_horizon,
        )
        specs.append(exp_spec.to_dict())
        valid_proposals.append(prop)

    batch_hash = compute_batch_hash(specs)
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    batch = BatchManifest(
        batch_id=batch_id,
        partition=partition,
        proposal_ids=proposal_ids,
        specs=specs,
        batch_hash=batch_hash,
        status="preregistered",
    )
    store.save_batch(batch)

    # Update proposals with batch pointer
    for prop in valid_proposals:
        prop.status = "preregistered"
        prop.batch_id = batch_id
        store.save_proposal(prop)

    return batch


def get_batch(batch_id: str) -> BatchManifest | None:
    return store.get_batch(batch_id)


def list_batches(partition: str | None = None) -> list[BatchManifest]:
    return store.list_batches(partition=partition)
