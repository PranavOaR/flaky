"""Self-contained local web dashboard for flaky-test-autopsy results."""

from __future__ import annotations

import json
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

# ── embedded HTML ──────────────────────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Flaky Test Autopsy</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #7d8590;
    --red: #f85149;
    --orange: #d29922;
    --yellow: #e3b341;
    --green: #3fb950;
    --blue: #58a6ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, monospace;
    font-size: 14px;
    line-height: 1.5;
  }
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
  }
  header h1 {
    font-family: monospace;
    font-size: 20px;
    color: var(--text);
    letter-spacing: 0.5px;
  }
  header .subline {
    color: var(--muted);
    font-size: 12px;
    margin-top: 4px;
  }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
  .cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 24px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
    text-align: center;
  }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
  .card .value { font-size: 32px; font-weight: 700; margin-top: 6px; }
  .card.flaky-red .value { color: var(--red); }
  .card.flaky-green .value { color: var(--green); }
  .section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 24px;
    overflow: hidden;
  }
  .section-header {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    font-size: 13px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .chart-wrapper { padding: 16px; height: 280px; position: relative; }
  #filter-bar {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  #filter-bar input {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-size: 13px;
    padding: 6px 10px;
    width: 300px;
    outline: none;
  }
  #filter-bar input:focus { border-color: var(--blue); }
  table { width: 100%; border-collapse: collapse; }
  th {
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    color: var(--muted);
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: 10px 16px;
    text-align: left;
    text-transform: uppercase;
    user-select: none;
  }
  th:hover { color: var(--text); }
  th.sorted-asc::after { content: " ▲"; }
  th.sorted-desc::after { content: " ▼"; }
  td {
    border-bottom: 1px solid var(--border);
    padding: 10px 16px;
    font-size: 13px;
    font-family: monospace;
  }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,0.02); }
  .sev-critical { color: var(--red); font-weight: 700; }
  .sev-high     { color: var(--red); }
  .sev-medium   { color: var(--yellow); }
  .sev-low      { color: var(--blue); }
  .sev-none     { color: var(--muted); }
  .trend-regression  { color: var(--red); }
  .trend-worsening   { color: var(--orange); }
  .trend-improvement { color: var(--green); }
  .trend-stable_flaky { color: var(--yellow); }
  .trend-stable_clean { color: var(--muted); }
  .trend-new         { color: var(--blue); }
  .badge {
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 6px;
    text-transform: uppercase;
  }
  .badge-ordering   { background: rgba(210,153,34,0.2);  color: var(--orange); }
  .badge-timing     { background: rgba(227,179,65,0.2);  color: var(--yellow); }
  .badge-randomness { background: rgba(88,166,255,0.2);  color: var(--blue); }
  .badge-network    { background: rgba(248,81,73,0.2);   color: var(--red); }
  .badge-unknown    { background: rgba(125,133,144,0.15);color: var(--muted); }
  .sparkline { display: inline-block; vertical-align: middle; }
  .auto-refresh { float: right; color: var(--muted); font-size: 11px; font-weight: normal; text-transform: none; letter-spacing: 0; }
</style>
</head>
<body>
<header>
  <h1>&#128302; Flaky Test Autopsy</h1>
  <div class="subline" id="subline">Loading...</div>
</header>
<div class="container">
  <div class="cards" id="cards">
    <div class="card"><div class="label">Total Tests</div><div class="value" id="c-total">-</div></div>
    <div class="card" id="c-flaky-card"><div class="label">Flaky</div><div class="value" id="c-flaky">-</div></div>
    <div class="card"><div class="label">Clean</div><div class="value" id="c-clean">-</div></div>
    <div class="card"><div class="label">Sessions</div><div class="value" id="c-sessions">-</div></div>
  </div>

  <div class="section">
    <div class="section-header">
      Flakiness Over Time
      <span class="auto-refresh" id="refresh-note"></span>
    </div>
    <div class="chart-wrapper"><canvas id="trend-chart"></canvas></div>
  </div>

  <div class="section">
    <div class="section-header">Tests</div>
    <div id="filter-bar">
      <input type="text" id="filter-input" placeholder="Filter by test name..." oninput="applyFilter()"/>
    </div>
    <table id="test-table">
      <thead>
        <tr>
          <th onclick="sortTable(0)">Test</th>
          <th onclick="sortTable(1)">Severity</th>
          <th onclick="sortTable(2)">Root Cause</th>
          <th onclick="sortTable(3)">Pass Rate</th>
          <th onclick="sortTable(4)">Flakiness</th>
          <th onclick="sortTable(5)">Trend</th>
          <th>Sparkline</th>
        </tr>
      </thead>
      <tbody id="test-tbody"></tbody>
    </table>
  </div>
</div>

<script>
const SEV_ORDER = {critical:0,high:1,medium:2,low:3,none:4};
const TREND_ICON = {
  regression:'&#8600; Regress',
  worsening:'&#8599; Worse',
  improvement:'&#8595; Improv',
  stable_flaky:'~ Flaky',
  stable_clean:'&#10003; Stable',
  new:'&#9733; New',
  gone:'&#10007; Gone'
};
const CAUSE_COLORS = {
  ordering:'#d29922',timing:'#e3b341',randomness:'#58a6ff',
  network:'#f85149',unknown:'#7d8590'
};

let allTests = [];
let sortCol = 4;
let sortDir = -1; // -1=desc, 1=asc
let chart = null;

async function fetchData() {
  const res = await fetch('/api/data');
  return await res.json();
}

function sparklineSVG(data) {
  if (!data || data.length === 0) return '';
  const w = 6, h = 20, gap = 2;
  const total = data.length;
  const svgW = total * (w + gap) - gap;
  let bars = '';
  for (let i = 0; i < total; i++) {
    const v = Math.min(1, Math.max(0, data[i]));
    const bh = Math.max(2, Math.round(v * h));
    const x = i * (w + gap);
    const y = h - bh;
    const color = v === 0 ? '#3fb950' : v < 0.3 ? '#e3b341' : '#f85149';
    bars += `<rect x="${x}" y="${y}" width="${w}" height="${bh}" fill="${color}" rx="1"/>`;
  }
  return `<svg class="sparkline" width="${svgW}" height="${h}" viewBox="0 0 ${svgW} ${h}">${bars}</svg>`;
}

function renderTable(tests) {
  const tbody = document.getElementById('test-tbody');
  const filter = document.getElementById('filter-input').value.toLowerCase();
  const visible = tests.filter(t => t.test_id.toLowerCase().includes(filter));

  tbody.innerHTML = visible.map(t => {
    const shortId = t.test_id.length > 60
      ? '&hellip;' + t.test_id.slice(-57)
      : t.test_id;
    const sev = t.severity || 'none';
    const cause = t.root_cause || 'unknown';
    const trend = t.trend || 'new';
    const passRate = (t.pass_rate * 100).toFixed(1) + '%';
    const flakePct = (t.flakiness_score * 100).toFixed(1) + '%';
    const trendIcon = TREND_ICON[trend] || trend;
    const spark = sparklineSVG(t.sparkline_data || []);

    return `<tr>
      <td title="${t.test_id}">${shortId}</td>
      <td><span class="sev-${sev}">${sev.toUpperCase()}</span></td>
      <td><span class="badge badge-${cause}">${cause}</span></td>
      <td>${passRate}</td>
      <td>${flakePct}</td>
      <td><span class="trend-${trend}">${trendIcon}</span></td>
      <td>${spark}</td>
    </tr>`;
  }).join('');
}

function applyFilter() {
  renderTable(allTests);
}

function sortTable(col) {
  const ths = document.querySelectorAll('th');
  ths.forEach((th, i) => {
    th.classList.remove('sorted-asc', 'sorted-desc');
  });

  if (sortCol === col) {
    sortDir *= -1;
  } else {
    sortCol = col;
    sortDir = col === 4 ? -1 : 1; // flakiness default desc, others asc
  }

  ths[col].classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');

  allTests.sort((a, b) => {
    let va, vb;
    switch (col) {
      case 0: va = a.test_id; vb = b.test_id; break;
      case 1: va = SEV_ORDER[a.severity||'none']; vb = SEV_ORDER[b.severity||'none']; break;
      case 2: va = a.root_cause||''; vb = b.root_cause||''; break;
      case 3: va = a.pass_rate; vb = b.pass_rate; break;
      case 4: va = a.flakiness_score; vb = b.flakiness_score; break;
      case 5: va = a.trend||''; vb = b.trend||''; break;
      default: va = 0; vb = 0;
    }
    if (va < vb) return -sortDir;
    if (va > vb) return sortDir;
    return 0;
  });

  renderTable(allTests);
}

function renderChart(data) {
  const sessions = data.sessions || [];
  const tests = data.tests || [];
  const flaky = tests.filter(t => t.flakiness_score > 0.05);

  const labels = sessions.map(s => s.label || s.started_at.slice(0,10));

  const palette = [
    '#f85149','#58a6ff','#3fb950','#d29922','#bc8cff',
    '#ff7b72','#79c0ff','#56d364','#e3b341','#d2a8ff'
  ];

  const datasets = flaky.slice(0, 10).map((t, i) => {
    const name = t.test_id.length > 40
      ? '...' + t.test_id.slice(-37)
      : t.test_id;
    const pts = (t.sparkline_data || []).slice(0, labels.length);
    return {
      label: name,
      data: pts.map(v => +(v * 100).toFixed(1)),
      borderColor: palette[i % palette.length],
      backgroundColor: palette[i % palette.length] + '22',
      borderWidth: 2,
      pointRadius: 3,
      tension: 0.3,
      fill: false,
    };
  });

  const ctx = document.getElementById('trend-chart').getContext('2d');
  if (chart) chart.destroy();

  if (datasets.length === 0) {
    ctx.fillStyle = '#7d8590';
    ctx.font = '14px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No flaky tests detected — all clean!', ctx.canvas.width / 2, 100);
    return;
  }

  chart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: {
            color: '#e6edf3',
            font: { family: 'monospace', size: 11 },
            boxWidth: 12,
          }
        },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#7d8590',
          callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y}%` }
        }
      },
      scales: {
        x: {
          ticks: { color: '#7d8590', font: { size: 11 } },
          grid: { color: '#30363d' }
        },
        y: {
          min: 0, max: 100,
          ticks: {
            color: '#7d8590',
            font: { size: 11 },
            callback: v => v + '%'
          },
          grid: { color: '#30363d' }
        }
      }
    }
  });
}

async function refresh() {
  const data = await fetchData();
  const s = data.summary || {};

  document.getElementById('subline').textContent =
    `${DB_PATH} · ${s.total_runs||0} runs · ${s.sessions||0} sessions`;

  document.getElementById('c-total').textContent = s.unique_tests || 0;
  document.getElementById('c-flaky').textContent = s.flaky_count || 0;
  document.getElementById('c-clean').textContent = s.clean_count || 0;
  document.getElementById('c-sessions').textContent = s.sessions || 0;

  const flakyCard = document.getElementById('c-flaky-card');
  flakyCard.className = 'card ' + ((s.flaky_count || 0) > 0 ? 'flaky-red' : 'flaky-green');

  allTests = data.tests || [];
  allTests.sort((a, b) => b.flakiness_score - a.flakiness_score);
  renderTable(allTests);
  renderChart(data);

  const now = new Date().toLocaleTimeString();
  document.getElementById('refresh-note').textContent = `Last updated: ${now}`;
}

const DB_PATH = document.querySelector('meta[name="db-path"]')?.content || 'unknown';

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""

# ── API data builder ───────────────────────────────────────────────────────────

def _build_api_data(db_path: str) -> dict[str, Any]:
    """Query the SQLite DB and return the dashboard JSON payload."""
    from autopsy.db import get_all_sessions, get_results_by_session, open_db
    from autopsy.scorer import score_from_conn, filter_flaky
    from autopsy.trends import compute_trends

    path = Path(db_path)
    if not path.exists():
        return {"summary": {}, "tests": [], "sessions": [], "regressions": []}

    conn = open_db(path)
    try:
        sessions_raw = get_all_sessions(conn)
        results_by_session = get_results_by_session(conn)

        # Aggregate summary counts
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        unique_tests = conn.execute(
            "SELECT COUNT(DISTINCT test_id) FROM results"
        ).fetchone()[0]

        reports = score_from_conn(conn, min_runs=1, flaky_threshold=0.05)
        flaky_count = sum(1 for r in reports if r.is_flaky)
        clean_count = len(reports) - flaky_count
    finally:
        conn.close()

    # Trend data per test (sparkline_data = flakiness score per session)
    trend_reports = compute_trends(db_path, min_sessions=1, regression_threshold=0.10)
    trend_by_id = {tr.test_id: tr for tr in trend_reports}

    tests_out: list[dict] = []
    for r in reports:
        tr = trend_by_id.get(r.test_id)
        sparkline_data = (
            [sc.flakiness_score for sc in tr.sessions] if tr else [r.flakiness_score]
        )
        tests_out.append({
            "test_id": r.test_id,
            "flakiness_score": round(r.flakiness_score, 4),
            "severity": r.severity,
            "root_cause": r.root_cause.category if r.root_cause else "unknown",
            "confidence": r.root_cause.confidence if r.root_cause else "low",
            "pass_rate": round(r.pass_rate, 4),
            "total_runs": r.total_runs,
            "trend": tr.trend if tr else "new",
            "trend_delta": round(tr.trend_delta, 4) if tr else 0.0,
            "sparkline_data": [round(v, 4) for v in sparkline_data],
        })

    sessions_out: list[dict] = []
    for s in sessions_raw:
        tid_map = results_by_session.get(s["id"], {})
        flaky_in_session = sum(
            1 for statuses in tid_map.values()
            if any(st in ("failed", "error") for st in statuses)
            and any(st == "passed" for st in statuses)
        )
        sessions_out.append({
            "id": s["id"],
            "label": s.get("label"),
            "started_at": s["started_at"],
            "run_count": s["run_count"],
            "flaky_count": flaky_in_session,
        })

    regressions = [t for t in tests_out if t["trend"] in ("regression", "worsening")]

    return {
        "summary": {
            "total_runs": total_runs,
            "unique_tests": unique_tests,
            "flaky_count": flaky_count,
            "clean_count": clean_count,
            "sessions": len(sessions_raw),
        },
        "tests": tests_out,
        "sessions": sessions_out,
        "regressions": regressions,
    }


# ── HTTP handler ───────────────────────────────────────────────────────────────

def _make_handler(db_path: str):
    """Return a BaseHTTPRequestHandler class bound to `db_path`."""

    class Handler(BaseHTTPRequestHandler):
        """Serve the dashboard HTML and /api/data endpoint."""

        def do_GET(self) -> None:
            """Handle GET requests for / and /api/data."""
            if self.path == "/" or self.path == "":
                html = _HTML.replace(
                    '<meta charset="UTF-8"/>',
                    f'<meta charset="UTF-8"/>\n<meta name="db-path" content="{db_path}"/>',
                )
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            elif self.path == "/api/data":
                try:
                    data = _build_api_data(db_path)
                    body = json.dumps(data, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    error = json.dumps({"error": str(exc)}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(error)

            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ANN001
            """Suppress default access log noise."""
            pass

    return Handler


# ── public API ─────────────────────────────────────────────────────────────────

def serve_dashboard(db_path: str, port: int = 7878, open_browser: bool = True) -> None:
    """Serve the dashboard and (optionally) open browser automatically."""
    handler = _make_handler(db_path)
    server = HTTPServer(("localhost", port), handler)
    url = f"http://localhost:{port}"

    print(f"✓ Dashboard running at {url}")
    print("Press Ctrl+C to stop.\n")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
