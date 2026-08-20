"""Unit and integration tests for interface, CLI commands, and REST API (PLAN.md §6, §7)."""
from __future__ import annotations

import argparse
import json
import urllib.request
import pytest

from src.interface import app, cli
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
        server, thread = app.serve_dashboard(port=0, block=False)
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

    def test_api_ledger(self, server):
        url = f"http://127.0.0.1:{server.server_address[1]}/api/ledger"
        req = urllib.request.urlopen(url)
        assert req.status == 200
        data = json.loads(req.read().decode("utf-8"))
        assert "entries" in data
