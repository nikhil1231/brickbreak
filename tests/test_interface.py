"""Unit and integration tests for interface, CLI commands, and REST API (the refactor plan §6, §7)."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from types import SimpleNamespace
import pytest

from src.interface import backend
from src.interface.cli import lab as cli
from src.persistence import store


class TestInterfaceCLI:
    def test_cli_catalogue(self, capsys):
        args = argparse.Namespace(owner=None)
        res = cli.cmd_catalogue(args)
        assert res == 0
        captured = capsys.readouterr()
        assert "Feature Catalogue" in captured.out
        assert "rs_60d_vs_mkt" in captured.out

    def test_cli_hypotheses_list(self, capsys):
        args = argparse.Namespace(id=None, status=None, family=None)
        res = cli.cmd_hypotheses(args)
        assert res == 0
        captured = capsys.readouterr()
        assert "Research Ledger" in captured.out
        assert "H001" in captured.out
        assert "H026" in captured.out

    def test_cli_hypotheses_detail(self, capsys):
        args = argparse.Namespace(id="H026")
        res = cli.cmd_hypotheses(args)
        assert res == 0
        captured = capsys.readouterr()
        assert "H026" in captured.out
        assert "Statement" in captured.out

    def test_cli_ledger(self, capsys):
        args = argparse.Namespace()
        res = cli.cmd_ledger(args)
        assert res == 0
        captured = capsys.readouterr()
        assert "Sample Budget Ledger" in captured.out


class TestInterfaceAPI:
    @pytest.fixture(scope="class")
    @classmethod
    def server(cls):
        # Port 0 lets the OS pick a free one. A fixed port makes the whole
        # class error out if anything else on the machine happens to hold it.
        server, thread = backend.serve_backend(port=0, block=False)
        yield server
        server.shutdown()

    def test_get_dashboard_html(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        html = req.read().decode("utf-8")
        assert "brickbreak" in html
        assert "Alpha Lab" in html

    def test_api_hypotheses(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/hypotheses"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert isinstance(data, list)
        assert len(data) >= 38

    def test_api_idea_graph(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/idea-graph"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert "nodes" in data
        assert "edges" in data

    def test_api_catalogue(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/catalogue"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert "features" in data
        assert len(data["features"]) > 50

    def test_api_provider_catalogue(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/providers"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert data["default_provider"] == "claude"
        assert {p["id"] for p in data["providers"]} == {"claude", "codex"}
        assert all(p["models"] for p in data["providers"])

    def test_create_hypothesis_registers_server_assigned_id(self, server,
                                                              monkeypatch):
        saved = []
        monkeypatch.setattr(backend.store, "next_hypothesis_id", lambda: "H039")
        monkeypatch.setattr(
            backend.store, "get_hypothesis",
            lambda hyp_id: SimpleNamespace(id=hyp_id) if hyp_id == "H026" else None)
        monkeypatch.setattr(backend.store, "save_hypothesis", saved.append)
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/hypotheses",
            data=json.dumps({
                "statement": "Does a new signal predict returns?",
                "rationale": "It may capture a delayed market response.",
                "family": "discovery",
                "parent_id": "H026",
                "relation": "specialises",
            }).encode(),
            headers={"Content-Type": "application/json"}, method="POST")

        response = urllib.request.urlopen(request)
        payload = json.loads(response.read().decode("utf-8"))

        assert response.status == 201
        assert payload["id"] == "H039"
        assert payload["statement"] == "Does a new signal predict returns?"
        assert payload["edges"] == [
            {"target_id": "H026", "relation": "specialises"}
        ]
        assert saved and saved[0].id == "H039"

    def test_create_hypothesis_requires_rationale(self, server):
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/hypotheses",
            data=json.dumps({"statement": "An unsupported idea"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        assert exc_info.value.code == 400
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert "rationale" in payload["error"].lower()

    def test_screener_api_is_mounted_on_primary_backend(self, server, monkeypatch):
        monkeypatch.setattr(
            backend.screener_api,
            "api_meta",
            lambda: {"service": "opening-window-screener"},
        )
        url = f"http://127.0.0.1:{server.server_address[1]}/api/meta"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        assert json.loads(req.read().decode("utf-8")) == {
            "service": "opening-window-screener"
        }

    def test_explore_forwards_provider_and_model(self, server, monkeypatch,
                                                 tmp_path):
        result_path = tmp_path / "result.json"
        result_path.write_text(json.dumps({
            "job_id": "J_API", "provider": "codex", "model": "gpt-test",
            "failure_class": "NO_SIGNAL", "interpretation": "test",
        }))
        captured = {}

        def fake_run_job(exp_spec, provider, model):
            captured.update(provider=provider, model=model,
                            signal=exp_spec.signal_name)
            return SimpleNamespace(
                state="succeeded", result_path=str(result_path), id="J_API",
                error="")

        monkeypatch.setattr(backend.agent, "available", lambda provider: True)
        monkeypatch.setattr(backend.job, "run_job", fake_run_job)
        payload = json.dumps({
            "hypothesis_id": "H026", "question": "q",
            "signal_name": "from_codex", "partition": "train",
            "provider": "codex", "model": "gpt-test",
        }).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/explore",
            data=payload, headers={"Content-Type": "application/json"},
            method="POST")
        response = urllib.request.urlopen(request)
        assert response.status == 200
        assert captured == {"provider": "codex", "model": "gpt-test",
                            "signal": "from_codex"}

    def test_new_idea_is_planned_registered_and_launched(self, server,
                                                          monkeypatch, tmp_path):
        result_path = tmp_path / "planned-result.json"
        result_path.write_text(json.dumps({
            "job_id": "J_PLANNED", "hypothesis_id": "H039",
            "signal_name": "planned_signal", "provider": "codex",
            "model": "gpt-test", "failure_class": "NO_SIGNAL",
            "interpretation": "test",
        }))
        saved = []
        captured = {}
        proposed = backend.planner.Plan(
            idea="a new idea",
            question="Does the planned signal predict returns?",
            rationale="It may capture delayed repricing.",
            what_it_measures="Delayed repricing",
            hypothesis_id="NEW",
            lineage=[{"target_id": "H026", "relation": "adjacent-to"}],
            family="discovery",
            signal_name="planned_signal",
            signal_sketch="Rank the lagged feature cross-sectionally.",
            pass_criterion={"min_mean_ic": 0.015, "min_spread_bps": 30.0,
                            "min_monotonicity": 0.6},
            source="codex",
        )

        def fake_propose(idea, provider, model):
            captured.update(idea=idea, provider=provider, model=model)
            return proposed

        def fake_run_job(exp_spec, provider, model, existing=None):
            captured.update(hypothesis_id=exp_spec.hypothesis_id,
                            signal=exp_spec.signal_name,
                            question=exp_spec.question,
                            handed_over=existing)
            return SimpleNamespace(
                state="succeeded", result_path=str(result_path), id="J_PLANNED",
                error="")

        # Planning opens the job record before it starts, so the interface can
        # show planning as planning. Keep that record out of the real store.
        opened = []

        def fake_open_job(exp_spec, provider, model, phase="planning"):
            jb = SimpleNamespace(id="J_PLANNED", spec=exp_spec.to_dict(),
                                 state="running", phase=phase, error="",
                                 enter=lambda p: None)
            opened.append(jb)
            return jb

        monkeypatch.setattr(backend.agent, "available", lambda provider: True)
        monkeypatch.setattr(backend.planner, "propose", fake_propose)
        monkeypatch.setattr(backend.store, "next_hypothesis_id", lambda: "H039")
        monkeypatch.setattr(
            backend.store, "get_hypothesis",
            lambda hyp_id: SimpleNamespace(id=hyp_id) if hyp_id == "H026" else None)
        monkeypatch.setattr(backend.store, "save_hypothesis", saved.append)
        monkeypatch.setattr(backend.job, "run_job", fake_run_job)
        monkeypatch.setattr(backend.job, "open_job", fake_open_job)

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/explore",
            data=json.dumps({
                "idea": "a new idea", "provider": "codex", "model": "gpt-test",
            }).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        response = urllib.request.urlopen(request)

        assert response.status == 200
        assert json.loads(response.read())["hypothesis_id"] == "H039"
        assert saved[0].id == "H039"
        assert saved[0].rationale == "It may capture delayed repricing."
        assert saved[0].edges[0].target_id == "H026"
        assert captured["hypothesis_id"] == "H039"
        # One exploration is one job: the record opened for planning is the
        # record the run continues into, not a second one.
        assert opened and captured["handed_over"] is opened[0]
        assert opened[0].phase == "planning"
        assert captured["signal"] == "planned_signal"
        assert "Signal plan:" in captured["question"]

    def test_explore_failure_returns_job_diagnostics(self, server, monkeypatch):
        monkeypatch.setattr(backend.agent, "available", lambda provider: True)
        monkeypatch.setattr(
            backend.job,
            "run_job",
            lambda *args, **kwargs: SimpleNamespace(
                state="failed", id="J_DIAGNOSTIC", provider="codex",
                model="gpt-test", agent_session="thread-123",
                error="rate limit reached; rate_limit"),
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/explore",
            data=json.dumps({"provider": "codex"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert payload == {
            "error": "rate limit reached; rate_limit",
            "job_id": "J_DIAGNOSTIC",
            "state": "failed",
            "provider": "codex",
            "model": "gpt-test",
            "agent_session": "thread-123",
        }

    def test_api_ledger(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/ledger"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert "entries" in data


# ---------------------------------------------------------------------------
# the wire format
# ---------------------------------------------------------------------------

def test_the_backend_never_emits_bare_nan():
    """Python's json.dumps writes `NaN`, which is not JSON.

    `JSON.parse` throws on it, so the whole view fails to load rather than
    showing a blank cell — and a replay whose selector took nothing has NaN in
    every headline field, which makes this the normal path rather than an edge
    case. Caught by loading the page, not by a unit test, which is why one
    exists now.
    """
    import json
    import math

    from src.interface.backend import _json_safe

    payload = {
        "headline": {"excess_lift_bps": float("nan"),
                     "take_rate_pct": 0.0,
                     "t": float("inf")},
        "rows": [1.0, float("-inf"), {"nested": float("nan")}],
        "text": "fine",
    }
    safe = _json_safe(payload)
    # allow_nan=False is what a browser's parser effectively enforces.
    encoded = json.dumps(safe, allow_nan=False)
    back = json.loads(encoded)

    assert back["headline"]["excess_lift_bps"] is None
    assert back["headline"]["t"] is None
    assert back["headline"]["take_rate_pct"] == 0.0, (
        "a real zero must survive; only non-finite values become null")
    assert back["rows"][1] is None
    assert back["rows"][2]["nested"] is None
    assert back["text"] == "fine"
    assert "NaN" not in encoded and "Infinity" not in encoded


def test_json_safe_leaves_ordinary_values_alone():
    from src.interface.backend import _json_safe
    payload = {"a": 1, "b": "x", "c": [1, 2, 3], "d": None, "e": True}
    assert _json_safe(payload) == payload


def test_cli_exposure_status(capsys):
    from src.interface.cli import council
    args = argparse.Namespace()
    res = council.cmd_exposure_status(args)
    assert res == 0
    captured = capsys.readouterr()
    assert "RESEARCH EXPOSURE LEDGER" in captured.out


def test_cli_data_probe(tmp_path, capsys):
    from src.interface.cli import council
    import pandas as pd
    p = tmp_path / "sample.csv"
    pd.DataFrame({"date": ["2021-01-04", "2021-01-05"], "val": [1, 2]}).to_csv(p, index=False)

    args = argparse.Namespace(file=str(p), source_name="Sample", date_col="date", sample_size=100)
    res = council.cmd_data_probe(args)
    assert res == 0
    captured = capsys.readouterr()
    assert "MICRO-PROBE: Sample" in captured.out


def test_cli_attack_dossier(tmp_path, capsys):
    from src.contracts.dossier import MechanismDossier
    from src.interface.cli import council

    dos = MechanismDossier(
        dossier_id="DOS_CLI_TEST",
        hypothesis_id="H099",
        family="test_fam",
        claim="Test claim for attack CLI",
        population="NIFTY 500",
        expected_horizon_days=10,
        observable_facts=("Fact 1",),
        interpretation="Interp",
        causal_chain="Causal chain explanation",
        counterparty="Counterparty name",
        counterparty_persistence_rationale="Persistence reason",
        competing_explanations=("Comp 1", "Comp 2"),
        strongest_baseline="Baseline",
        unique_predictions=("Pred 1",),
        natural_falsifiers=("Falsifier 1",),
        confounds=(),
        capacity_notes="Capacity",
        min_effect_bps=50.0,
        nearest_hypothesis_ids=(),
        required_observations_absent=(),
        memory_risk_classification="anon",
        forward_confirmation_path="fwd",
        proposer="scout",
        hostile_reviewer="critic",
    )
    p = tmp_path / "dossier.json"
    p.write_text(json.dumps(dos.to_dict()))

    args = argparse.Namespace(dossier_file=str(p), save=True)
    res = council.cmd_attack(args)
    assert res == 0
    captured = capsys.readouterr()
    assert "Attacking dossier" in captured.out
    assert "Verdict: APPROVED" in captured.out

