"""Fixtures shared across the test suite.

The research store is a *record*, not a scratch space. A test that writes into
the real one adds fixture data to the lab's own ledger, and the damage is quiet:
`EXP_*` and `EV_*` records shaped exactly like real ones, indistinguishable
after the fact except by the signal name. That happened — one integration test
running with `save_results=True` deposited eighteen copies of `h026_test_run`
over eighteen suite runs, and they were counted as eighteen tests against the
train partition until `burden.partition_summary` learned to deduplicate.

Anything that persists must therefore take `research_store`.
"""
from __future__ import annotations

import pytest

from src.persistence import ledger as ledger_mod
from src.persistence import store
from src.firewall import exposure as exposure_mod


@pytest.fixture()
def research_store(tmp_path, monkeypatch):
    """Redirect every write the research store performs into `tmp_path`.

    The paths are module-level constants resolved at import time, so patching
    `config.METADATA_DIR` after the fact would move nothing. Each one is
    redirected individually, and the sample-budget ledger — which lives beside
    the store rather than inside it — along with them.
    """
    store_dir = tmp_path / "research_store"
    monkeypatch.setattr(store, "STORE_DIR", store_dir)
    for name, sub in (("HYPOTHESES_DIR", "hypotheses"),
                      ("EXPLORATIONS_DIR", "explorations"),
                      ("SIGNALS_DIR", "signals"),
                      ("EVIDENCE_DIR", "evidence"),
                      ("SUGGESTIONS_DIR", "suggestions")):
        monkeypatch.setattr(store, name, store_dir / sub)
    monkeypatch.setattr(ledger_mod, "LEDGER_PATH", store_dir / "ledger.json")
    monkeypatch.setattr(
        exposure_mod, "EXPOSURE_LOG_PATH", store_dir / "exposure_log.json")
    return tmp_path
