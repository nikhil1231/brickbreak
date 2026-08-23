"""Imports used by offline research must not perform network work."""
from __future__ import annotations

import importlib
import sys


def test_importing_breeze_wrapper_does_not_import_network_active_sdk(monkeypatch):
    monkeypatch.delitem(sys.modules, "breeze_connect", raising=False)

    wrapper = importlib.import_module("src.research_data.sources.breeze")
    importlib.reload(wrapper)

    assert "breeze_connect" not in sys.modules
