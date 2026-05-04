"""Self-contained local web dashboard for flaky-test-autopsy results."""

from __future__ import annotations

import html as _html_lib
import json
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
    --bg:       #0d1117;
    --surface:  #161b22;
    --border:   #30363d;
    --text:     #e6edf3;
    --muted:    #7d8590;
    --critical: #f85149;
    --high:     #e06c4a;
    --medium:   #e3b341;
    --low:      #58a6ff;
    --clean:    #3fb950;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }

  /* ---- header ---- */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    height: 52px;
    padding: 0 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .hdr-left  { display: flex; align-items: center; gap: 10px; }
  .hdr-title { font-family: monospace; font-size: 15px; font-weight: 600; letter-spacing: 0.4px; }
  .hdr-sep   { color: var(--border); }
  .hdr-db    { font-family: monospace; font-size: 12px; color: var(--muted); }
  .hdr-right { font-size: 12px; color: var(--muted); }

  /* ---- layout ---- */
  .container { max-width: 1440px; margin: 0 auto; padding: 20px 24px; }

  /* ---- metric cards ---- */
  .cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 20px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
  }
  .card-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
  }
  .card-value {
    font-size: 30px;
    font-weight: 700;
    margin-top: 6px;
    font-variant-numeric: tabular-nums;
  }
  .card-value.red   { color: var(--critical); }
  .card-value.green { color: var(--clean); }

  /* ---- charts row ---- */
  .charts-row {
    display: grid;
    grid-template-columns: 60fr 40fr;
    gap: 12px;
    margin-bottom: 20px;
  }
  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .panel-header {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
  }
  .chart-wrap { padding: 16px; height: 240px; position: relative; }

  /* ---- table panel ---- */
  .table-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .table-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
  }
  .table-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
  }
  #filter-input {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-size: 12px;
    font-family: system-ui, sans-serif;
    padding: 5px 10px;
    width: 240px;
    outline: none;
  }
  #filter-input::placeholder { color: var(--muted); }
  #filter-input:focus { border-color: var(--low); }

  table { width: 100%; border-collapse: collapse; }
  thead th {
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    color: var(--muted);
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
    padding: 9px 16px;
    text-align: left;
    text-transform: uppercase;
    user-select: none;
    white-space: nowrap;
  }
  thead th:hover { color: var(--text); }
  thead th.sorted-asc::after  { content: " \25B2"; font-size: 9px; }
  thead th.sorted-desc::after { content: " \25BC"; font-size: 9px; }

  tbody td {
    border-bottom: 1px solid var(--border);
    padding: 10px 16px;
    vertical-align: middle;
    font-size: 13px;
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover td { background: rgba(255,255,255,0.03); }

  .td-test {
    font-family: monospace;
    font-size: 12px;
    max-width: 440px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .td-muted { font-size: 12px; color: var(--muted); text-transform: capitalize; }

  /* ---- severity pill ---- */
  .sev-pill {
    display: inline-block;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 2px 7px;
    text-transform: uppercase;
  }
  .sev-critical { background: rgba(248,81,73,0.15);   color: var(--critical); }
  .sev-high     { background: rgba(224,108,74,0.15);  color: var(--high); }
  .sev-medium   { background: rgba(227,179,65,0.15);  color: var(--medium); }
  .sev-low      { background: rgba(88,166,255,0.15);  color: var(--low); }
  .sev-none     { background: rgba(125,133,144,0.12); color: var(--muted); }

  /* ---- flakiness cell ---- */
  .flake-cell  { min-width: 90px; }
  .flake-pct   { font-size: 13px; font-variant-numeric: tabular-nums; margin-bottom: 4px; }
  .flake-track { height: 2px; background: var(--border); border-radius: 1px; overflow: hidden; }
  .flake-fill  { height: 100%; border-radius: 1px; }

  /* ---- trend ---- */
  .trend-regression   { font-size: 12px; color: var(--critical); }
  .trend-worsening    { font-size: 12px; color: var(--high); }
  .trend-improvement  { font-size: 12px; color: var(--clean); }
  .trend-stable_flaky { font-size: 12px; color: var(--medium); }
  .trend-stable_clean { font-size: 12px; color: var(--muted); }
  .trend-new          { font-size: 12px; color: var(--low); }
  .trend-gone         { font-size: 12px; color: var(--muted); }

  .empty-state { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }

  /* ---- detail panel ---- */
  #detail-overlay {
    display: none;
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 100;
  }
  #detail-overlay.open { display: block; }
  #detail-panel {
    position: fixed;
    top: 0; right: -500px;
    width: 500px; height: 100%;
    background: var(--surface);
    border-left: 1px solid var(--border);
    overflow-y: auto;
    transition: right 0.25s ease;
    z-index: 101;
  }
  #detail-panel.open { right: 0; }
  .dp-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    gap: 12px;
  }
  .dp-test-id {
    font-family: monospace;
    font-size: 12px;
    word-break: break-all;
    flex: 1;
  }
  .dp-close {
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 20px;
    line-height: 1;
    padding: 0 4px;
    flex-shrink: 0;
  }
  .dp-close:hover { color: var(--text); }
  .dp-body { padding: 16px 20px; }
  .dp-section { margin-bottom: 20px; }
  .dp-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
  }
  .dp-stats {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .dp-stat { text-align: center; }
  .dp-stat-val { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .dp-stat-lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .dp-timeline {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .dp-dot {
    width: 10px; height: 10px;
    border-radius: 2px;
    cursor: default;
  }
  .dp-dot.passed { background: var(--clean); }
  .dp-dot.failed { background: var(--critical); }
  .dp-dot.error  { background: var(--high); }
  .dp-dot.skipped { background: var(--muted); }
  .dp-dot.missing { background: var(--border); }
  .dp-fix {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 13px;
    padding: 10px 14px;
    line-height: 1.6;
  }
  .dp-failure {
    background: rgba(248,81,73,0.07);
    border: 1px solid rgba(248,81,73,0.2);
    border-radius: 4px;
    font-family: monospace;
    font-size: 11px;
    max-height: 240px;
    overflow-y: auto;
    padding: 10px 14px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  #detail-loading { color: var(--muted); font-size: 13px; padding: 20px; }
</style>
</head>
<body>
<div id="detail-overlay" onclick="closeDetail()"></div>
<div id="detail-panel">
  <div class="dp-header">
    <div class="dp-test-id" id="dp-test-id">—</div>
    <button class="dp-close" onclick="closeDetail()">✕</button>
  </div>
  <div class="dp-body" id="dp-body"><div id="detail-loading">Loading…</div></div>
</div>
<header>
  <div class="hdr-left">
    <span class="hdr-title">FLAKY TEST AUTOPSY</span>
    <span class="hdr-sep">|</span>
    <span class="hdr-db" id="hdr-db">loading...</span>
  </div>
  <div class="hdr-right" id="hdr-refresh"></div>
</header>

<div class="container">
  <div class="cards">
    <div class="card">
      <div class="card-label">Total Tests</div>
      <div class="card-value" id="c-total">--</div>
    </div>
    <div class="card">
      <div class="card-label">Flaky</div>
      <div class="card-value" id="c-flaky">--</div>
    </div>
    <div class="card">
      <div class="card-label">Sessions</div>
      <div class="card-value" id="c-sessions">--</div>
    </div>
    <div class="card">
      <div class="card-label">Health</div>
      <div class="card-value" id="c-health">--%</div>
    </div>
  </div>

  <div class="charts-row">
    <div class="panel">
      <div class="panel-header">Flakiness Over Sessions</div>
      <div class="chart-wrap"><canvas id="trend-chart"></canvas></div>
    </div>
    <div class="panel">
      <div class="panel-header">Root Causes</div>
      <div class="chart-wrap"><canvas id="cause-chart"></canvas></div>
    </div>
  </div>

  <div class="table-panel">
    <div class="table-header">
      <span class="table-title">Tests</span>
      <input type="text" id="filter-input" placeholder="Filter by test name..." oninput="applyFilter()"/>
    </div>
    <table>
      <thead>
        <tr>
          <th onclick="sortTable(0)">Test</th>
          <th onclick="sortTable(1)">Severity</th>
          <th onclick="sortTable(2)">Root Cause</th>
          <th onclick="sortTable(3)">Pass Rate</th>
          <th onclick="sortTable(4)">Flakiness</th>
          <th onclick="sortTable(5)">Trend</th>
        </tr>
      </thead>
      <tbody id="test-tbody"></tbody>
    </table>
  </div>
</div>

<script>
const SEV_ORDER = { critical: 0, high: 1, medium: 2, low: 3, none: 4 };
const TREND_LABEL = {
  regression:   'Regress',
  worsening:    'Worsening',
  improvement:  'Improving',
  stable_flaky: 'Stable Flaky',
  stable_clean: 'Stable Clean',
  new:          'New',
  gone:         'Gone',
};
const PALETTE = [
  '#f85149','#58a6ff','#3fb950','#e3b341','#bc8cff',
  '#ff7b72','#79c0ff','#56d364','#d2a8ff','#ffa657',
];

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let allTests   = [];
let sortCol    = 4;
let sortDir    = -1;
let trendChart = null;
let causeChart = null;

const DB_PATH = document.querySelector('meta[name="db-path"]')?.content || '';

async function fetchData() {
  const r = await fetch('/api/data');
  return r.json();
}

function flakeColor(v) {
  if (v <= 0.05) return '#3fb950';
  if (v <= 0.20) return '#58a6ff';
  if (v <= 0.40) return '#e3b341';
  if (v <= 0.60) return '#e06c4a';
  return '#f85149';
}

function renderTable(tests) {
  const filter  = document.getElementById('filter-input').value.toLowerCase();
  const visible = tests.filter(t => t.test_id.toLowerCase().includes(filter));
  const tbody   = document.getElementById('test-tbody');

  if (visible.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">No tests match.</div></td></tr>';
    return;
  }

  tbody.innerHTML = visible.map(t => {
    const sev        = t.severity || 'none';
    const cause      = t.root_cause || 'unknown';
    const trend      = t.trend || 'new';
    const flakeV     = t.flakiness_score || 0;
    const barColor   = flakeColor(flakeV);
    const barWidth   = Math.min(100, flakeV * 100).toFixed(1);
    const passRate   = ((t.pass_rate || 0) * 100).toFixed(1) + '%';
    const flakePct   = (flakeV * 100).toFixed(1) + '%';
    const trendLabel = TREND_LABEL[trend] || trend;
    const raw        = t.test_id;
    const short      = esc(raw.length > 60 ? '…' + raw.slice(-59) : raw);

    return `<tr style="cursor:pointer" onclick="showDetail(${JSON.stringify(raw)})">
      <td class="td-test" title="${esc(raw)}">${short}</td>
      <td><span class="sev-pill sev-${esc(sev)}">${esc(sev)}</span></td>
      <td class="td-muted">${esc(cause)}</td>
      <td style="font-variant-numeric:tabular-nums">${passRate}</td>
      <td class="flake-cell">
        <div class="flake-pct" style="color:${barColor}">${flakePct}</div>
        <div class="flake-track"><div class="flake-fill" style="width:${barWidth}%;background:${barColor}"></div></div>
      </td>
      <td><span class="trend-${trend}">${trendLabel}</span></td>
    </tr>`;
  }).join('');
}

async function showDetail(testId) {
  document.getElementById('dp-test-id').textContent = testId;
  document.getElementById('dp-body').innerHTML = '<div id="detail-loading">Loading…</div>';
  document.getElementById('detail-overlay').classList.add('open');
  document.getElementById('detail-panel').classList.add('open');

  try {
    const r = await fetch('/api/test?id=' + encodeURIComponent(testId));
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    renderDetail(data);
  } catch (e) {
    document.getElementById('dp-body').innerHTML =
      '<div style="color:var(--critical);padding:12px">Failed to load: ' + esc(e.message) + '</div>';
  }
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
  document.getElementById('detail-panel').classList.remove('open');
}

function renderDetail(d) {
  const sev = d.severity || 'none';
  const flakeColor = v => v <= 0.05 ? '#3fb950' : v <= 0.20 ? '#58a6ff' : v <= 0.40 ? '#e3b341' : v <= 0.60 ? '#e06c4a' : '#f85149';
  const fc = flakeColor(d.flakiness_score || 0);

  const timeline = (d.history || []).map(h => {
    const st = h.status || 'missing';
    const tip = `Run ${h.run_index} · ${h.session_label || h.session_id || ''} · ${st} · ${(h.duration_s||0).toFixed(2)}s`;
    return `<div class="dp-dot ${st}" title="${esc(tip)}"></div>`;
  }).join('');

  const fixHtml = d.template_fix
    ? `<div class="dp-section"><div class="dp-label">Fix Suggestion</div><div class="dp-fix">${esc(d.template_fix)}</div></div>`
    : '';

  const failHtml = d.latest_failure
    ? `<div class="dp-section"><div class="dp-label">Latest Failure</div><div class="dp-failure">${esc(d.latest_failure)}</div></div>`
    : '';

  document.getElementById('dp-body').innerHTML = `
    <div class="dp-stats">
      <div class="dp-stat">
        <div class="dp-stat-val"><span class="sev-pill sev-${esc(sev)}">${esc(sev)}</span></div>
        <div class="dp-stat-lbl">Severity</div>
      </div>
      <div class="dp-stat">
        <div class="dp-stat-val" style="color:${fc}">${((d.flakiness_score||0)*100).toFixed(1)}%</div>
        <div class="dp-stat-lbl">Flakiness</div>
      </div>
      <div class="dp-stat">
        <div class="dp-stat-val">${((d.pass_rate||0)*100).toFixed(1)}%</div>
        <div class="dp-stat-lbl">Pass Rate</div>
      </div>
      <div class="dp-stat">
        <div class="dp-stat-val">${d.total_runs || 0}</div>
        <div class="dp-stat-lbl">Runs</div>
      </div>
    </div>
    <div class="dp-section">
      <div class="dp-label">Run Timeline (green=pass, red=fail)</div>
      <div class="dp-timeline">${timeline || '<span style="color:var(--muted);font-size:12px">No history</span>'}</div>
    </div>
    ${fixHtml}
    ${failHtml}
  `;
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

function applyFilter() { renderTable(allTests); }

function sortTable(col) {
  document.querySelectorAll('thead th').forEach(th => th.classList.remove('sorted-asc', 'sorted-desc'));
  if (sortCol === col) { sortDir *= -1; }
  else { sortCol = col; sortDir = (col === 4 || col === 1) ? -1 : 1; }
  document.querySelectorAll('thead th')[col].classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');

  allTests.sort((a, b) => {
    let va, vb;
    switch (col) {
      case 0: va = a.test_id;                        vb = b.test_id; break;
      case 1: va = SEV_ORDER[a.severity || 'none'];  vb = SEV_ORDER[b.severity || 'none']; break;
      case 2: va = a.root_cause || '';               vb = b.root_cause || ''; break;
      case 3: va = a.pass_rate;                      vb = b.pass_rate; break;
      case 4: va = a.flakiness_score;                vb = b.flakiness_score; break;
      case 5: va = a.trend || '';                    vb = b.trend || ''; break;
      default: return 0;
    }
    if (va < vb) return -sortDir;
    if (va > vb) return  sortDir;
    return 0;
  });
  renderTable(allTests);
}

function renderTrendChart(data) {
  const sessions = data.sessions || [];
  const tests    = data.tests    || [];
  const flaky    = tests.filter(t => (t.flakiness_score || 0) > 0.05).slice(0, 10);
  const labels   = sessions.map(s => s.label || s.started_at.slice(0, 10));

  const datasets = flaky.map((t, i) => {
    const name = t.test_id.length > 40 ? '…' + t.test_id.slice(-39) : t.test_id;
    const pts  = (t.sparkline_data || []).slice(0, labels.length);
    return {
      label: name,
      data: pts.map(v => +(v * 100).toFixed(1)),
      borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: 'transparent',
      borderWidth: 1.5,
      pointRadius: 3,
      pointHoverRadius: 4,
      tension: 0.2,
    };
  });

  const ctx = document.getElementById('trend-chart').getContext('2d');
  if (trendChart) trendChart.destroy();

  if (datasets.length === 0) {
    ctx.fillStyle = '#7d8590';
    ctx.font = '13px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No flaky tests detected.', ctx.canvas.width / 2, 100);
    return;
  }

  trendChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#7d8590', font: { family: 'monospace', size: 10 }, boxWidth: 10, padding: 10 } },
        tooltip: {
          backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1,
          titleColor: '#e6edf3', bodyColor: '#7d8590',
          callbacks: { label: c => ` ${c.dataset.label}: ${c.parsed.y}%` },
        },
      },
      scales: {
        x: { ticks: { color: '#7d8590', font: { size: 11 } }, grid: { color: '#30363d' } },
        y: {
          min: 0, max: 100,
          ticks: { color: '#7d8590', font: { size: 11 }, callback: v => v + '%' },
          grid: { color: '#30363d' },
        },
      },
    },
  });
}

function renderCauseChart(tests) {
  const counts = {};
  for (const t of tests) {
    const c = t.root_cause || 'unknown';
    counts[c] = (counts[c] || 0) + 1;
  }
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const labels  = entries.map(e => e[0]);
  const values  = entries.map(e => e[1]);
  const CAUSE_COLOR = { ordering: '#e3b341', timing: '#58a6ff', randomness: '#3fb950', network: '#f85149', unknown: '#7d8590' };
  const colors  = labels.map(l => CAUSE_COLOR[l] || '#7d8590');

  const ctx = document.getElementById('cause-chart').getContext('2d');
  if (causeChart) causeChart.destroy();

  if (labels.length === 0) {
    ctx.fillStyle = '#7d8590';
    ctx.font = '13px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No data.', ctx.canvas.width / 2, 100);
    return;
  }

  causeChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: colors, borderWidth: 0, borderRadius: 3 }],
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#161b22', borderColor: '#30363d', borderWidth: 1,
          titleColor: '#e6edf3', bodyColor: '#7d8590',
        },
      },
      scales: {
        x: { ticks: { color: '#7d8590', font: { size: 11 }, stepSize: 1 }, grid: { color: '#30363d' } },
        y: { ticks: { color: '#e6edf3', font: { size: 12 } }, grid: { display: false } },
      },
    },
  });
}

async function refresh() {
  const data  = await fetchData();
  const s     = data.summary || {};
  const flaky = s.flaky_count  || 0;
  const total = s.unique_tests || 0;
  const health = total > 0 ? Math.round((1 - flaky / total) * 100) : 100;

  document.getElementById('hdr-db').textContent      = DB_PATH || 'autopsy_results.db';
  document.getElementById('hdr-refresh').textContent = 'Updated ' + new Date().toLocaleTimeString();
  document.getElementById('c-total').textContent     = total;
  document.getElementById('c-sessions').textContent  = s.sessions || 0;

  const flakyEl  = document.getElementById('c-flaky');
  flakyEl.textContent = flaky;
  flakyEl.className   = 'card-value ' + (flaky > 0 ? 'red' : 'green');

  const healthEl = document.getElementById('c-health');
  healthEl.textContent = health + '%';
  healthEl.className   = 'card-value ' + (health >= 90 ? 'green' : health >= 70 ? '' : 'red');

  allTests = (data.tests || []).sort((a, b) => b.flakiness_score - a.flakiness_score);
  renderTable(allTests);
  renderTrendChart(data);
  renderCauseChart(allTests);
}

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
    from autopsy.scorer import score_from_conn
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


# ── test detail builder ───────────────────────────────────────────────────────

def _build_test_detail(db_path: str, test_id: str) -> dict[str, Any]:
    """Return detail payload for a single test: history, fix suggestion, latest failure."""
    from autopsy.db import get_history_for_test, get_results_for_test, open_db
    from autopsy.fixer import get_fix_suggestion
    from autopsy.scorer import score_from_conn

    path = Path(db_path)
    if not path.exists():
        return {"error": "database not found"}

    conn = open_db(path)
    try:
        history = get_history_for_test(conn, test_id)
        reports = score_from_conn(conn, min_runs=1, flaky_threshold=0.05)
    finally:
        conn.close()

    report = next((r for r in reports if r.test_id == test_id), None)
    if report is None:
        return {"error": "test not found"}

    # Latest failure output
    latest_failure: str | None = None
    for row in reversed(history):
        if row["status"] in ("failed", "error") and row.get("stdout"):
            latest_failure = row["stdout"][:2000]
            break

    # Template fix suggestion (no AI, no cache needed for dashboard)
    template_fix: str | None = None
    try:
        conn2 = open_db(path)
        failure_outputs = [
            row["stdout"] or "" for row in get_results_for_test(conn2, test_id)
            if row["status"] in ("failed", "error")
        ]
        suggestion = get_fix_suggestion(report, failure_outputs, conn=conn2, use_ai=False, use_cache=False)
        template_fix = suggestion.template_fix
        conn2.close()
    except Exception:  # noqa: BLE001
        pass

    return {
        "test_id": test_id,
        "severity": report.severity,
        "flakiness_score": round(report.flakiness_score, 4),
        "pass_rate": round(report.pass_rate, 4),
        "total_runs": report.total_runs,
        "root_cause": report.root_cause.category if report.root_cause else "unknown",
        "history": [
            {
                "run_index": row["run_index"],
                "session_id": row.get("session_id"),
                "session_label": row.get("session_label"),
                "status": row["status"],
                "duration_s": row.get("duration_s", 0.0),
            }
            for row in history
        ],
        "latest_failure": latest_failure,
        "template_fix": template_fix,
    }


# ── HTTP handler ───────────────────────────────────────────────────────────────

def _make_handler(db_path: str) -> type[BaseHTTPRequestHandler]:
    """Return a BaseHTTPRequestHandler class bound to `db_path`."""

    class Handler(BaseHTTPRequestHandler):
        """Serve the dashboard HTML and /api/data endpoint."""

        def _send_security_headers(self) -> None:
            """Emit hardening headers on every response."""
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")

        def do_GET(self) -> None:
            """Handle GET requests for / and /api/data and /api/test."""
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(self.path)

            if parsed.path in ("/", ""):
                safe_db_path = _html_lib.escape(db_path, quote=True)
                html = _HTML.replace(
                    '<meta charset="UTF-8"/>',
                    f'<meta charset="UTF-8"/>\n<meta name="db-path" content="{safe_db_path}"/>',
                )
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._send_security_headers()
                self.end_headers()
                self.wfile.write(body)

            elif parsed.path == "/api/data":
                try:
                    data = _build_api_data(db_path)
                    body = json.dumps(data, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    error = json.dumps({"error": "internal error"}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(error)

            elif parsed.path == "/api/test":
                qs = parse_qs(parsed.query)
                ids = qs.get("id", [])
                if not ids:
                    error = json.dumps({"error": "missing id parameter"}).encode("utf-8")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(error)
                    return
                try:
                    data = _build_test_detail(db_path, ids[0])
                    status = 404 if "error" in data else 200
                    body = json.dumps(data, default=str).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    error = json.dumps({"error": "internal error"}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._send_security_headers()
                    self.end_headers()
                    self.wfile.write(error)

            else:
                self.send_response(404)
                self._send_security_headers()
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
