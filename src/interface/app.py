"""Lightweight research dashboard server and API (PLAN.md §6, §7).

Provides REST API endpoints and an interactive single-page web console for:
- Explore Console (submit ideas, launch explorations, review findings)
- Hypothesis & Evidence browser
- Idea Graph navigator
- Multi-Signal Compare
- Sample Budget Ledger status
- Feature Catalogue
"""
from __future__ import annotations

import http.server
import json
import socketserver
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from ..persistence import migration, store
from ..persistence.ledger import SampleBudgetLedger
from ..research_data import catalogue
from ..runner import compare, runner, spec


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>brickbreak — Alpha Research Lab</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {
      --bg: #0d1117; --card-bg: #161b22; --border: #30363d;
      --text: #c9d1d9; --text-muted: #8b949e; --accent: #58a6ff;
      --green: #3fb950; --red: #f85149; --yellow: #d29922; --purple: #bc8cff;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
    body { background: var(--bg); color: var(--text); padding: 24px; line-height: 1.5; }
    header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
    h1 { font-size: 20px; font-weight: 600; color: #fff; }
    nav button { background: none; border: 1px solid var(--border); color: var(--text); padding: 8px 16px; margin-left: 8px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }
    nav button.active { background: var(--accent); color: #000; border-color: var(--accent); font-weight: 600; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }
    .card h2 { font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #fff; display: flex; justify-content: space-between; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
    th { color: var(--text-muted); font-weight: 600; background: #0e131a; }
    tr:hover { background: #1f242c; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
    .badge-promising, .badge-validated, .badge-success { background: rgba(63,185,80,0.15); color: var(--green); }
    .badge-rejected, .badge-no_signal { background: rgba(248,81,73,0.15); color: var(--red); }
    .badge-exploring, .badge-proposed { background: rgba(88,166,255,0.15); color: var(--accent); }
    .badge-signal_but_beta, .badge-unstable { background: rgba(210,153,34,0.15); color: var(--yellow); }
    .badge-high_turnover, .badge-superseded { background: rgba(188,140,255,0.15); color: var(--purple); }
    input, select, textarea { width: 100%; background: #0d1117; border: 1px solid var(--border); color: #fff; padding: 10px; border-radius: 6px; font-size: 13px; margin-bottom: 12px; }
    button.btn-primary { background: var(--accent); color: #000; font-weight: 600; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }
    button.btn-primary:hover { opacity: 0.9; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .metric-box { background: #0d1117; border: 1px solid var(--border); border-radius: 6px; padding: 12px; text-align: center; }
    .metric-value { font-size: 22px; font-weight: 700; color: #fff; margin-top: 4px; }
    .metric-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; }
    pre { background: #0d1117; border: 1px solid var(--border); padding: 12px; border-radius: 6px; font-size: 12px; overflow-x: auto; color: #79c0ff; }
  </style>
</head>
<body>
  <header>
    <h1>brickbreak &mdash; Alpha Lab</h1>
    <nav>
      <button class="active" onclick="switchTab('explore')">Explore</button>
      <button onclick="switchTab('hypotheses')">Hypotheses</button>
      <button onclick="switchTab('graph')">Idea Graph</button>
      <button onclick="switchTab('compare')">Signal Compare</button>
      <button onclick="switchTab('ledger')">Budget Ledger</button>
      <button onclick="switchTab('catalogue')">Catalogue</button>
    </nav>
  </header>

  <!-- Explore Console -->
  <div id="tab-explore" class="tab-content active">
    <div class="card">
      <h2>Explore a New Hypothesis</h2>
      <p style="color:var(--text-muted); margin-bottom: 16px; font-size: 13px;">Type a hypothesis question and choose a signal to run the full alpha evaluation battery through the research runner.</p>
      <div class="grid-2">
        <div>
          <label style="font-size:12px; color:var(--text-muted);">Hypothesis ID</label>
          <input type="text" id="exp-hyp-id" value="H026" placeholder="e.g. H026, H039">
          <label style="font-size:12px; color:var(--text-muted);">Research Question</label>
          <textarea id="exp-question" rows="3">Does relative strength against market and sector breadth predict 10-session forward returns?</textarea>
        </div>
        <div>
          <label style="font-size:12px; color:var(--text-muted);">Signal Name</label>
          <input type="text" id="exp-signal-name" value="h026_composite_rs">
          <label style="font-size:12px; color:var(--text-muted);">Partition</label>
          <select id="exp-partition">
            <option value="train" selected>train (exploration window)</option>
            <option value="validation">validation</option>
            <option value="test">test (shuffled holdout)</option>
            <option value="forward">forward (chronological live lane)</option>
          </select>
          <button class="btn-primary" style="margin-top: 10px; width: 100%;" onclick="runExploration()">Launch Exploration</button>
        </div>
      </div>
    </div>

    <div id="explore-results" class="card" style="display:none;">
      <h2>Exploration Result <span id="res-badge" class="badge"></span></h2>
      <p id="res-interp" style="margin-bottom: 16px; font-size: 14px; color: #fff;"></p>
      <div class="grid-2" style="margin-bottom: 16px;">
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px;">
          <div class="metric-box"><div class="metric-label">Mean Rank IC</div><div id="res-ic" class="metric-value">-</div></div>
          <div class="metric-box"><div class="metric-label">IC t-statistic</div><div id="res-t" class="metric-value">-</div></div>
          <div class="metric-box"><div class="metric-label">Q5 - Q1 Spread</div><div id="res-spread" class="metric-value">-</div></div>
          <div class="metric-box"><div class="metric-label">Monotonicity</div><div id="res-mono" class="metric-value">-</div></div>
        </div>
        <div>
          <label style="font-size:12px; color:var(--text-muted);">Immutable Manifest Hash</label>
          <pre id="res-manifest">-</pre>
        </div>
      </div>
      <h3 style="font-size: 13px; color: var(--text-muted); margin-bottom: 8px;">Suggested Next Moves:</h3>
      <ul id="res-moves" style="margin-left: 20px; font-size: 13px;"></ul>
    </div>
  </div>

  <!-- Hypotheses Browser -->
  <div id="tab-hypotheses" class="tab-content">
    <div class="card">
      <h2>Research Ledger (H001 &ndash; H038) <span id="hyp-count" style="font-size:12px; color:var(--text-muted);"></span></h2>
      <table id="hyp-table">
        <thead>
          <tr><th>ID</th><th>Title</th><th>Family</th><th>Status</th><th>Tags</th></tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- Idea Graph -->
  <div id="tab-graph" class="tab-content">
    <div class="card">
      <h2>Idea Graph Network</h2>
      <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">Hypothesis lineage connections and relationship edges.</p>
      <table id="graph-table">
        <thead><tr><th>Source</th><th>Relation</th><th>Target</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- Signal Compare -->
  <div id="tab-compare" class="tab-content">
    <div class="card">
      <h2>Signal Compare &amp; Ensembling</h2>
      <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">Compare cross-sectional correlations, top-pick overlap, and multi-signal ensemble portfolios.</p>
      <div style="margin-bottom: 12px;">
        <label style="font-size:12px; color:var(--text-muted);">Signals to Compare (comma-separated)</label>
        <input type="text" id="cmp-signals" value="rs_60d_vs_mkt, sector_breadth, dist_52w_high">
        <button class="btn-primary" onclick="runCompare()">Run Comparison</button>
      </div>
      <pre id="cmp-output" style="display:none;"></pre>
    </div>
  </div>

  <!-- Budget Ledger -->
  <div id="tab-ledger" class="tab-content">
    <div class="card">
      <h2>Sample Budget Ledger</h2>
      <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">Recorded data partition and quarter consumption across research roles.</p>
      <table id="ledger-table">
        <thead><tr><th>Timestamp</th><th>Hypothesis</th><th>Family</th><th>Role</th><th>Partition</th><th>Quarters</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- Feature Catalogue -->
  <div id="tab-catalogue" class="tab-content">
    <div class="card">
      <h2>Feature Catalogue</h2>
      <table id="cat-table">
        <thead><tr><th>Feature</th><th>Owner</th><th>As-Of</th><th>Lookback</th><th>PIT</th><th>Scorable</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <script>
    function switchTab(name) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('nav button').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      event.target.classList.add('active');
      if (name === 'hypotheses') loadHypotheses();
      if (name === 'graph') loadGraph();
      if (name === 'ledger') loadLedger();
      if (name === 'catalogue') loadCatalogue();
    }

    async function loadHypotheses() {
      const res = await fetch('/api/hypotheses');
      const data = await res.json();
      document.getElementById('hyp-count').innerText = data.length + ' entries';
      const tbody = document.querySelector('#hyp-table tbody');
      tbody.innerHTML = '';
      data.forEach(h => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><strong>${h.id}</strong></td><td>${h.title}</td><td>${h.family}</td><td><span class="badge badge-${h.status}">${h.status}</span></td><td style="color:var(--text-muted)">${h.tags.join(', ')}</td>`;
        tbody.appendChild(tr);
      });
    }

    async function loadGraph() {
      const res = await fetch('/api/idea-graph');
      const data = await res.json();
      const tbody = document.querySelector('#graph-table tbody');
      tbody.innerHTML = '';
      data.edges.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><strong>${e.source}</strong></td><td><code>${e.relation}</code></td><td><strong>${e.target}</strong></td>`;
        tbody.appendChild(tr);
      });
    }

    async function loadLedger() {
      const res = await fetch('/api/ledger');
      const data = await res.json();
      const tbody = document.querySelector('#ledger-table tbody');
      tbody.innerHTML = '';
      data.entries.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${e.timestamp || '-'}</td><td><strong>${e.hypothesis_id}</strong></td><td>${e.family}</td><td><span class="badge badge-${e.role}">${e.role}</span></td><td>${e.partition}</td><td style="font-size:11px;">${e.quarters.join(', ')}</td>`;
        tbody.appendChild(tr);
      });
    }

    async function loadCatalogue() {
      const res = await fetch('/api/catalogue');
      const data = await res.json();
      const tbody = document.querySelector('#cat-table tbody');
      tbody.innerHTML = '';
      data.features.forEach(f => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><code>${f.name}</code></td><td>${f.owner}</td><td>${f.available_as_of}</td><td>${f.lookback}</td><td>${f.point_in_time ? '✅' : '❌'}</td><td>${f.scorable ? '✅' : '🔒'}</td>`;
        tbody.appendChild(tr);
      });
    }

    async function runExploration() {
      const hypId = document.getElementById('exp-hyp-id').value;
      const question = document.getElementById('exp-question').value;
      const signal = document.getElementById('exp-signal-name').value;
      const part = document.getElementById('exp-partition').value;

      document.getElementById('explore-results').style.display = 'block';
      document.getElementById('res-interp').innerText = 'Running exploration across data partitions...';

      const res = await fetch('/api/explore', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ hypothesis_id: hypId, question: question, signal_name: signal, partition: part })
      });
      const data = await res.json();

      document.getElementById('res-badge').className = 'badge badge-' + data.failure_class.toLowerCase();
      document.getElementById('res-badge').innerText = data.failure_class;
      document.getElementById('res-interp').innerText = data.interpretation;

      const pc = data.evaluation?.predictive_content?.primary_ic;
      document.getElementById('res-ic').innerText = pc?.mean_ic != null ? pc.mean_ic : '-';
      document.getElementById('res-t').innerText = pc?.t_stat != null ? pc.t_stat : '-';

      const q = data.evaluation?.quantiles;
      document.getElementById('res-spread').innerText = q?.q5_spread_bps != null ? q.q5_spread_bps + ' bps' : '-';
      document.getElementById('res-mono').innerText = q?.q5_monotonicity != null ? q.q5_monotonicity : '-';

      document.getElementById('res-manifest').innerText = JSON.stringify(data.manifest, null, 2);

      const movesUl = document.getElementById('res-moves');
      movesUl.innerHTML = '';
      (data.suggested_next_moves || []).forEach(m => {
        const li = document.createElement('li');
        li.innerHTML = `<strong>${m.action}</strong> (<em>${m.relation}</em>): ${m.rationale}`;
        movesUl.appendChild(li);
      });
    }

    async function runCompare() {
      const signals = document.getElementById('cmp-signals').value.split(',').map(s => s.trim());
      const pre = document.getElementById('cmp-output');
      pre.style.display = 'block';
      pre.innerText = 'Running multi-signal comparison...';

      const res = await fetch('/api/compare', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ signals: signals })
      });
      const data = await res.json();
      pre.innerText = JSON.stringify(data, null, 2);
    }
  </script>
</body>
</html>
"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler serving dashboard UI and REST API."""

    def log_message(self, format: str, *args: Any) -> None:
        # Silence standard HTTP access logging to keep terminal clean
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
            return

        if path == "/api/hypotheses":
            hyps = store.list_hypotheses()
            if not hyps:
                # auto-migrate if empty
                hyps, _ = migration.migrate(save_to_store=True)
            self._send_json([h.to_dict() for h in hyps])
            return

        if path.startswith("/api/hypotheses/"):
            h_id = path.split("/")[-1]
            h = store.get_hypothesis(h_id)
            if not h:
                self._send_json({"error": "not found"}, status=404)
                return
            evs = store.list_evidence(hypothesis_id=h_id)
            out = h.to_dict()
            out["evidence"] = [e.to_dict() for e in evs]
            self._send_json(out)
            return

        if path == "/api/idea-graph":
            graph = store.get_idea_graph()
            nodes = [h.to_dict() for h in graph._nodes.values()]
            edges = []
            for src_id, edge_list in graph._adjacency.items():
                for e in edge_list:
                    edges.append({"source": src_id, "target": e.target_id, "relation": e.relation})
            self._send_json({"nodes": nodes, "edges": edges, "summary": graph.summary()})
            return

        if path == "/api/ledger":
            l = SampleBudgetLedger.load()
            self._send_json({
                "n_entries": len(l._entries),
                "entries": [e.to_dict() for e in l._entries],
            })
            return

        if path == "/api/catalogue":
            cat = catalogue.DEFAULT
            features = [
                {
                    "name": s.name,
                    "owner": s.owner,
                    "available_as_of": s.available_as_of,
                    "lookback": s.lookback,
                    "point_in_time": s.point_in_time,
                    "scorable": cat.scorable(s.name),
                }
                for s in cat.all_features()
            ]
            self._send_json({"features": features, "summary": cat.summary()})
            return

        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"

        try:
            req_data = json.loads(body.decode("utf-8"))
        except Exception:
            req_data = {}

        if path == "/api/explore":
            exp_spec = spec.ExperimentSpec(
                hypothesis_id=req_data.get("hypothesis_id", "H026"),
                question=req_data.get("question", "Exploration run"),
                signal_name=req_data.get("signal_name", "custom_signal"),
                partition=req_data.get("partition", "train"),
                role=req_data.get("role", "exploratory"),
            )

            # Signal function generator: composite of available context columns
            def _signal_fn(df):
                d = df.copy()
                cols = [c for c in ("rs_60d_vs_mkt", "sector_breadth", "dist_52w_high") if c in d.columns]
                if not cols:
                    return pd.Series(np.random.normal(0, 1, size=len(d)), index=d.index)
                ranks = [d.groupby("date")[c].rank(pct=True) for c in cols]
                return sum(ranks) / len(ranks)

            result = runner.run_exploration(exp_spec, _signal_fn, save_results=True)
            self._send_json(result)
            return

        if path == "/api/compare":
            from ..research_data import frame
            signal_names = req_data.get("signals", ["rs_60d_vs_mkt", "sector_breadth"])
            clean_signals = [s for s in signal_names if s in catalogue.DEFAULT]
            if len(clean_signals) < 2:
                self._send_json({"error": "Provide at least 2 valid catalogue signal names."}, status=400)
                return

            panel = frame.load_daily_panel(partition="train", include_context=True)
            panel["fwd_ret_10d_pct"] = frame.forward_return(panel, horizon=10)
            res = compare.compare_signals(panel, clean_signals, forward_col="fwd_ret_10d_pct")
            self._send_json(res)
            return

        self._send_json({"error": "not found"}, status=404)

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_dashboard(port: int = 8080, block: bool = True) -> tuple[socketserver.TCPServer, threading.Thread | None]:
    """Starts the research dashboard web server."""
    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", port), DashboardHandler)
    print(f"\n=======================================================")
    print(f"  brickbreak Alpha Lab Dashboard running at:")
    print(f"  http://127.0.0.1:{port}")
    print(f"=======================================================\n")

    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server stopped.")
        return server, None
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, t
