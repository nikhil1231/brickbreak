"""Primary brickbreak backend and web application server (the refactor plan §6, §7).

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
import html
import json
import math
import socketserver
import threading
import urllib.parse
from typing import Any

from ..core import config
from ..persistence import migration, store
from ..persistence.ledger import SampleBudgetLedger
from ..persistence.models import Edge, Hypothesis, RELATION_TYPES
from ..discretionary import replay as d_replay
from ..research_data import catalogue
from ..runner import agent, compare, job
from . import breeze_auth, director_api, screener_api

FRONTEND_DIR = config.PROJECT_ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"


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
      <button onclick="switchTab('settings')">Settings</button>
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

  <!-- Local Settings -->
  <div id="tab-settings" class="tab-content">
    <div class="card">
      <h2>ICICI Direct Breeze <span><span id="breeze-status" class="badge"></span>
        <small id="breeze-refreshed" style="color:var(--text-muted); margin-left:8px;"></small></span></h2>
      <p style="color:var(--text-muted); margin-bottom:16px; font-size:13px;">
        Set this exact URL as the redirect URL on your Breeze API app. The server
        verifies each callback before updating BREEZE_SESSION_TOKEN in .env.
      </p>
      <label style="font-size:12px; color:var(--text-muted);">Registered callback URL</label>
      <input id="breeze-callback" type="text" readonly>
      <div style="margin:16px 0; padding:14px; border:1px solid var(--border); border-radius:8px;">
        <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
          <div>
            <label style="font-size:12px; color:var(--text-muted);">Authenticator code</label>
            <div id="breeze-totp" style="font:700 28px monospace; letter-spacing:.2em; margin-top:4px;">Not configured</div>
          </div>
          <small id="breeze-totp-countdown" style="color:var(--text-muted);"></small>
        </div>
        <small id="breeze-totp-help" style="color:var(--text-muted);">Add BREEZE_TOTP_SECRET to .env and restart the server.</small>
      </div>
      <p id="breeze-error" style="color:var(--red); margin-bottom:12px; font-size:12px;"></p>
      <button id="breeze-login" class="btn-primary" onclick="beginBreezeLogin()">Connect Breeze</button>
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
      if (name === 'settings') loadBreezeSettings();
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

    let breezeLoginUrl = '/auth/breeze/login';
    let breezeTotpTimer = null;

    async function loadBreezeTotp() {
      const code = document.getElementById('breeze-totp');
      const countdown = document.getElementById('breeze-totp-countdown');
      try {
        const res = await fetch('/api/settings/breeze/totp', {cache: 'no-store'});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Could not generate code');
        code.innerText = data.code;
        countdown.innerText = 'Refreshes in ' + data.valid_for_seconds + 's';
      } catch (error) {
        code.innerText = 'Unavailable';
        countdown.innerText = error.message;
      }
    }

    async function loadBreezeSettings() {
      const res = await fetch('/api/settings/breeze');
      const data = await res.json();
      breezeLoginUrl = data.login_url || data.login_path || breezeLoginUrl;
      document.getElementById('breeze-callback').value = data.callback_url || '';
      document.getElementById('breeze-error').innerText = data.error || '';
      const status = document.getElementById('breeze-status');
      status.className = 'badge ' + (data.has_session_token ? 'badge-success' : 'badge-exploring');
      status.innerText = data.has_session_token ? 'token saved' : 'login needed';
      const refreshed = document.getElementById('breeze-refreshed');
      refreshed.innerText = data.has_session_token
        ? (data.session_refreshed_at
          ? 'Last refreshed ' + new Date(data.session_refreshed_at).toLocaleString()
          : 'Last refresh time unavailable')
        : '';
      const button = document.getElementById('breeze-login');
      button.disabled = !data.configured;
      button.innerText = data.has_session_token ? 'Refresh Breeze login' : 'Connect Breeze';
      clearInterval(breezeTotpTimer);
      breezeTotpTimer = null;
      const totpHelp = document.getElementById('breeze-totp-help');
      if (data.totp_configured) {
        totpHelp.innerText = 'Generated locally; the seed is never sent to this page.';
        loadBreezeTotp();
        breezeTotpTimer = setInterval(loadBreezeTotp, 1000);
      } else {
        document.getElementById('breeze-totp').innerText = 'Not configured';
        document.getElementById('breeze-totp-countdown').innerText = '';
        totpHelp.innerText = 'Add BREEZE_TOTP_SECRET to .env and restart the server.';
      }
    }

    function beginBreezeLogin() {
      const loginUrl = new URL(breezeLoginUrl, window.location.href);
      loginUrl.searchParams.set('opener_origin', window.location.origin);
      const loginTab = window.open(loginUrl.toString(), '_blank');
      if (!loginTab) window.location.assign(loginUrl.toString());
    }

    window.addEventListener('message', e => {
      if (e.origin === window.location.origin && e.data?.type === 'breeze-auth-complete') {
        loadBreezeSettings();
      }
    });
    window.addEventListener('focus', loadBreezeSettings);

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


def _hypothesis_title(hypothesis_id: str) -> str:
    if not hypothesis_id:
        return ""
    hyp = store.get_hypothesis(hypothesis_id)
    return hyp.title if hyp else ""


class BackendHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler serving the application UI and REST APIs."""

    def log_message(self, format: str, *args: Any) -> None:
        # Silence standard HTTP access logging to keep terminal clean
        pass

    @staticmethod
    def _replay_row(r) -> dict:
        """Enough to render a row without opening every artefact."""
        st = r.status()
        row = {"id": r.id, "phases": st["phases"], "next": st["next"]}
        try:
            d = r.definition()
            row.update({"idea": d.idea, "hypothesis_id": d.hypothesis_id,
                        "generator": d.generator, "partition": d.partition,
                        "sample_n": d.sample_n, "anonymised": d.anonymise,
                        "primary_horizon": d.primary_horizon})
        except Exception:
            pass
        if r.report_path.exists():
            try:
                rep = json.loads(r.report_path.read_text())
                row["headline"] = rep.get("headline", {})
                row["verdict"] = rep.get("verdict", {})
            except Exception:
                pass
        return row

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == breeze_auth.LOGIN_PATH:
            try:
                creds = config.load_credentials(require_session=False)
            except config.ConfigError as exc:
                self._send_auth_result(False, str(exc), status=400)
                return
            login_query = urllib.parse.parse_qs(parsed.query)
            opener_origin = breeze_auth.safe_local_origin(
                next(iter(login_query.get("opener_origin", [])), None)
            )
            nonce = breeze_auth.PENDING_LOGINS.begin(opener_origin)
            self.send_response(302)
            self.send_header("Location", creds.login_url)
            self.send_header("Set-Cookie", breeze_auth.login_cookie(nonce))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        if path == breeze_auth.CALLBACK_PATH:
            self._handle_breeze_callback(parsed)
            return

        if path in ("/", "/index.html"):
            if DIST_DIR.exists() and (DIST_DIR / "index.html").exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write((DIST_DIR / "index.html").read_bytes())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
            return

        if path.startswith("/assets/"):
            p = (DIST_DIR / path.lstrip("/")).resolve()
            if str(p).startswith(str(DIST_DIR.resolve())) and p.exists():
                ctype = {"js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}.get(
                    p.suffix.lstrip("."), "application/octet-stream"
                )
                self.send_response(200)
                self.send_header("Content-Type", f"{ctype}; charset=utf-8")
                self.send_header("Cache-Control", "public, max-age=31536000")
                self.end_headers()
                self.wfile.write(p.read_bytes())
                return

        # The opening-window screener is one feature of the research app, not
        # a second core service. Keep its data-heavy implementation isolated,
        # but mount its API on the primary backend.
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/meta":
                self._send_json(screener_api.api_meta())
                return
            if path == "/api/screen":
                self._send_json(screener_api.api_screen(query))
                return
            if path == "/api/symbol":
                self._send_json(screener_api.api_symbol(query))
                return
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
            return

        if path == "/api/providers":
            self._send_json(agent.provider_catalog())
            return

        if path == "/api/director":
            try:
                self._send_json(director_api.state())
            except Exception as exc:
                self._send_json(
                    {"error": f"{type(exc).__name__}: {exc}"}, status=500)
            return

        if path == "/api/settings/breeze":
            port = int(self.server.server_address[1])
            self._send_json(breeze_auth.settings_payload(port))
            return

        if path == "/api/settings/breeze/totp":
            try:
                payload = breeze_auth.totp_payload()
            except breeze_auth.BreezeAuthError as exc:
                self._send_json({"error": str(exc)}, status=400,
                                cache_control="no-store")
                return
            self._send_json(payload, cache_control="no-store")
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

        # --- the discretionary loop, read-only -------------------------
        # Read-only on purpose. A replay spends the sample at its reveal
        # phase, and a button that spends sample does not belong on a page
        # somebody opens to look around. Dispatch stays on the CLI where the
        # phase you are running is the thing you typed.
        if path == "/api/replays":
            self._send_json({"replays": [self._replay_row(r)
                                         for r in d_replay.list_replays()[:50]]})
            return

        if path.startswith("/api/replays/"):
            parts = [p for p in path.split("/") if p]
            rid = parts[2]
            try:
                r = d_replay.get(rid)
            except d_replay.ReplayError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            leaf = parts[3] if len(parts) > 3 else None
            try:
                if leaf == "cases":
                    idx = int(query.get("index", ["0"])[0])
                    cases = r.cases()
                    if not 0 <= idx < len(cases):
                        self._send_json({"error": "index out of range"}, status=404)
                        return
                    c = cases[idx]
                    self._send_json({"n_cases": len(cases), "index": idx,
                                     "case_id": c.case_id,
                                     "case_hash": c.case_hash,
                                     "anonymised": c.anonymised,
                                     "rendered": c.render()})
                    return
                if leaf == "decisions":
                    who = query.get("decider", ["ai"])[0]
                    self._send_json({"decisions": [
                        d.to_dict() for d in r.decisions() if d.decider == who]})
                    return
                if leaf == "report":
                    if not r.report_path.exists():
                        self._send_json({"error": "not evaluated yet"}, status=404)
                        return
                    self._send_json(json.loads(r.report_path.read_text()))
                    return
                out = self._replay_row(r)
                out["definition"] = r.definition().to_dict()
                if r.seal_path.exists():
                    out["seal"] = json.loads(r.seal_path.read_text())
                self._send_json(out)
                return
            except Exception as exc:
                self._send_json({"error": f"{type(exc).__name__}: {exc}"},
                                status=500)
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

        # ICICI Direct returns the popup login as a form POST in some browser
        # flows. Pasting the same callback URL into the address bar creates a
        # GET, so both methods must reach the identical verified handler.
        if path == breeze_auth.CALLBACK_PATH:
            self._handle_breeze_callback(parsed, body)
            return

        try:
            req_data = json.loads(body.decode("utf-8"))
        except Exception:
            req_data = {}

        if path.startswith("/api/director/"):
            try:
                self._send_json(director_api.dispatch_post(path, req_data))
            except director_api.DirectorAPIError as exc:
                self._send_json({"error": str(exc)}, status=exc.status)
            return

        if path == "/api/hypotheses":
            statement = str(req_data.get("statement") or "").strip()
            rationale = str(req_data.get("rationale") or "").strip()
            family = str(req_data.get("family") or "general").strip() or "general"
            if not statement:
                self._send_json({"error": "A testable hypothesis statement is required."},
                                status=400)
                return
            if not rationale:
                self._send_json({"error": "A rationale is required before registration."},
                                status=400)
                return

            edges = []
            parent_id = str(req_data.get("parent_id") or "").strip()
            if parent_id:
                if store.get_hypothesis(parent_id) is None:
                    self._send_json(
                        {"error": f"Parent hypothesis {parent_id} is not registered."},
                        status=404)
                    return
                relation = str(req_data.get("relation") or "adjacent-to")
                if relation not in RELATION_TYPES:
                    self._send_json(
                        {"error": f"Invalid relation {relation!r}."}, status=400)
                    return
                edges.append(Edge(target_id=parent_id, relation=relation))

            title = str(req_data.get("title") or statement).strip()
            if len(title) > 160:
                title = title[:157].rstrip() + "..."
            hypothesis = Hypothesis(
                id=store.next_hypothesis_id(),
                title=title,
                statement=statement,
                rationale=rationale,
                family=family,
                edges=edges,
                tags=["submitted_from_explore"],
            )
            store.save_hypothesis(hypothesis)
            self._send_json(hypothesis.to_dict(), status=201)
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

    def _handle_breeze_callback(
        self, parsed: urllib.parse.ParseResult, body: bytes | None = None,
    ) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        if body:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
            posted: dict[str, list[str]] = {}
            try:
                if content_type == "application/x-www-form-urlencoded":
                    posted = urllib.parse.parse_qs(body.decode("utf-8"))
                elif content_type == "application/json":
                    decoded = json.loads(body.decode("utf-8"))
                    if isinstance(decoded, dict):
                        posted = {str(k): [str(v)] for k, v in decoded.items()
                                  if v is not None}
            except (UnicodeDecodeError, json.JSONDecodeError):
                posted = {}
            for key, values in posted.items():
                query.setdefault(key, []).extend(values)

        token = breeze_auth.extract_session_token(query)
        if not token:
            provider_error = next(iter(query.get("error", [])), "")
            message = provider_error or "The callback did not include an apisession token."
            self._send_auth_result(False, message, status=400)
            return
        valid_login, opener_origin = breeze_auth.PENDING_LOGINS.consume_cookie(
            self.headers.get("Cookie")
        )
        if not valid_login and self.command == "POST":
            valid_login, opener_origin = breeze_auth.PENDING_LOGINS.consume_latest()
        if not valid_login:
            self._send_auth_result(
                False,
                "This Breeze login was not started from the brickbreak Settings page, or it expired.",
                status=400,
            )
            return
        try:
            creds = config.load_credentials(require_session=False)
            breeze_auth.validate_session_token(creds, token)
            config.save_breeze_session_token(token)
        except (config.ConfigError, breeze_auth.BreezeAuthError) as exc:
            self._send_auth_result(False, str(exc), status=400,
                                   clear_cookie=True,
                                   opener_origin=opener_origin)
            return
        except Exception as exc:
            self._send_auth_result(
                False,
                f"Could not save the verified Breeze session ({type(exc).__name__}: {exc}).",
                status=500,
                clear_cookie=True,
                opener_origin=opener_origin,
            )
            return
        self._send_auth_result(
            True,
            "The new Breeze session was verified and saved to .env.",
            clear_cookie=True,
            opener_origin=opener_origin,
        )

    def _send_json(
        self, data: Any, status: int = 200,
        cache_control: str | None = None,
    ) -> None:
        # `allow_nan=False` plus a NaN-scrubbing pass, not one or the other.
        # Python emits bare `NaN` by default, which is *not* JSON: the browser
        # throws on parse and the whole view fails to load rather than showing
        # a blank cell. A selector that took nothing legitimately has NaN
        # everywhere, so this is the normal path, not an edge case.
        body = json.dumps(_json_safe(data), indent=2, default=str,
                          allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_auth_result(
        self,
        success: bool,
        message: str,
        status: int = 200,
        clear_cookie: bool = False,
        opener_origin: str | None = None,
    ) -> None:
        """Render a tiny popup-safe callback page without exposing the token."""
        title = "Breeze connected" if success else "Breeze login failed"
        colour = "#3fb950" if success else "#f85149"
        safe_title = html.escape(title)
        safe_message = html.escape(message)
        success_js = "true" if success else "false"
        opener_origin_js = json.dumps(opener_origin)
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{safe_title}</title><style>
body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#0d1117;
color:#c9d1d9; font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ width:min(420px,calc(100% - 40px)); padding:28px; background:#161b22;
border:1px solid #30363d; border-radius:10px; }}
h1 {{ margin:0 0 10px; color:{colour}; font-size:20px; }}
p {{ line-height:1.55; }} a {{ color:#58a6ff; }}
</style></head><body><main><h1>{safe_title}</h1><p>{safe_message}</p>
<p><a href="/?tab=settings">Return to Settings</a></p></main>
<script>
history.replaceState(null, '', '/auth/breeze/complete');
if (window.opener) {{
  const openerOrigin = {opener_origin_js} || window.location.origin;
  window.opener.postMessage({{type:'breeze-auth-complete',success:{success_js}}}, openerOrigin);
}}
if ({success_js}) window.setTimeout(() => window.close(), 700);
</script></body></html>""".encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if clear_cookie:
            self.send_header("Set-Cookie", breeze_auth.clear_login_cookie())
        self.end_headers()
        self.wfile.write(body)


def _json_safe(value: Any) -> Any:
    """Replace non-finite floats with null, recursively.

    A missing number is not a zero. `null` is the honest wire representation
    and the frontend already renders it as an em dash.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def serve_backend(port: int = 8080, block: bool = True) -> tuple[socketserver.ThreadingTCPServer, threading.Thread | None]:
    """Start the primary research backend and web application server."""
    # Anything still marked running belongs to a process that is no longer
    # here — jobs do not outlive the server that dispatched them.
    job.reap_orphans()

    # Threaded on purpose. An exploration holds its request open for as long
    # as the worker takes; on a single-threaded server that also holds every
    # other request, so the progress list could never refresh while there was
    # anything to watch.
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), BackendHandler)
    print(f"\n=======================================================")
    print(f"  brickbreak backend running at:")
    print(f"  http://127.0.0.1:{port}")
    print(f"=======================================================\n")

    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nBackend server stopped.")
        return server, None
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, t
