import sqlite3
import os
import datetime
from string import Template
from core import app_paths
from core.verification_reporter import VerificationReporter

# Use a writable app data dir (LocalAppData by default; ProgramData if pre-created and writable)
if os.name == 'nt':
    DB_PATH = str(app_paths.db_path())
    DASHBOARD_DIR = str(app_paths.dashboard_dir())
    REPORT_PATH = str(app_paths.dashboard_report_path())
else:
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(ROOT_DIR, "data")
    DB_PATH = os.path.join(DATA_DIR, "nexus.db")
    DASHBOARD_DIR = os.path.join(ROOT_DIR, "Dashboard")
    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    REPORT_PATH = os.path.join(DASHBOARD_DIR, "dashboard.html")

EMPTY_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PCP Nexus | Standby</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body { font-family: sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .box { text-align: center; padding: 2rem; background: #1e293b; border-radius: 12px; border: 1px solid #334155; }
        .spinner { border: 4px solid rgba(255,255,255,0.1); border-left-color: #3b82f6; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 1rem; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="box">
        <div class="spinner"></div>
        <h2>PCP Nexus Standby</h2>
        <p style="color: #94a3b8">Waiting for engine to process the first batch of emails...</p>
        <p style="font-size: 0.8em; color: #64748b">Generated at: {TIMESTAMP}</p>
    </div>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PCP Nexus | Live Dashboard</title>
    <!-- Auto-refresh controlled by JavaScript toggle -->
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --accent: #3b82f6;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
        }
        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            margin: 0;
            padding: 2rem;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            margin-bottom: 2rem;
            border-bottom: 1px solid #334155;
            padding-bottom: 1rem;
        }
        h1 { margin: 0; font-weight: 700; letter-spacing: -0.025em; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 3rem;
        }
        .card {
            background-color: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            border: 1px solid #334155;
        }
        .stat-value {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        .stat-label {
            color: var(--text-secondary);
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .table-container {
            background-color: var(--card-bg);
            border-radius: 12px;
            overflow: auto;
            max-height: 600px;
            border: 1px solid #334155;
        }
        .main-tab-content {
            overflow: auto;
            max-height: calc(100vh - 120px);
        }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            text-align: left;
            padding: 1rem 1.5rem;
            border-bottom: 1px solid #334155;
        }
        th {
            background-color: #0f172a;
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 0.75rem;
            text-transform: uppercase;
        }
        tr:last-child td { border-bottom: none; }
        .status-badge {
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .status-verified { background-color: rgba(16, 185, 129, 0.2); color: var(--success); }
        .status-failed { background-color: rgba(239, 68, 68, 0.2); color: var(--danger); }
        .status-duplicate { background-color: rgba(245, 158, 11, 0.2); color: var(--warning); }

        /* Auto-Refresh Toggle */
        .refresh-toggle-wrap {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-left: auto;
        }
        .refresh-toggle-label {
            color: var(--text-secondary);
            font-size: 0.8rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            user-select: none;
        }
        .toggle-switch {
            position: relative;
            width: 44px;
            height: 24px;
            cursor: pointer;
        }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .toggle-slider {
            position: absolute;
            inset: 0;
            background: #334155;
            border-radius: 12px;
            transition: background 0.25s;
        }
        .toggle-slider::before {
            content: '';
            position: absolute;
            width: 18px;
            height: 18px;
            left: 3px;
            bottom: 3px;
            background: #94a3b8;
            border-radius: 50%;
            transition: transform 0.25s, background 0.25s;
        }
        .toggle-switch input:checked + .toggle-slider {
            background: rgba(16, 185, 129, 0.3);
        }
        .toggle-switch input:checked + .toggle-slider::before {
            transform: translateX(20px);
            background: var(--success);
        }
        .refresh-indicator {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #334155;
            transition: background 0.3s;
        }
        .refresh-indicator.active {
            background: var(--success);
            animation: pulse-dot 2s infinite;
        }
        @keyframes pulse-dot {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .status-filed { background-color: rgba(59, 130, 246, 0.2); color: var(--accent); }
        
        .potential-action-flag {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            color: var(--danger);
            font-weight: 700;
            background: rgba(239, 68, 68, 0.1);
            padding: 4px 8px;
            border-radius: 4px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.6; }
            100% { opacity: 1; }
        }
        
        .action-btn {
            background-color: var(--accent);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.875rem;
            font-weight: 500;
            display: inline-block;
            transition: opacity 0.2s;
        }
        .action-btn:hover { opacity: 0.9; }
        .refresh-time {
            color: var(--text-secondary);
            font-size: 0.875rem;
        }
        /* Top-level Tab Navigation */
        .main-tab-bar {
            display: flex;
            background: #1e293b;
            border-bottom: 2px solid #334155;
            padding: 0 24px;
            margin: -2rem -2rem 2rem -2rem;
        }
        .main-tab {
            padding: 14px 28px;
            cursor: pointer;
            color: #94a3b8;
            font-weight: 600;
            font-size: 0.95rem;
            border-bottom: 3px solid transparent;
            transition: all 0.2s;
            user-select: none;
        }
        .main-tab:hover { color: #cbd5e1; background: #283548; }
        .main-tab.active { color: #38bdf8; border-bottom-color: #38bdf8; }
        .main-tab-content { display: none; }
        .main-tab-content.active { display: block; }
        /* Verification sub-tabs (Phase 1/2) */
        .v-tab-bar { display: flex; background: #1e293b; border-bottom: 2px solid #334155; padding: 0 24px; margin-bottom: 20px; border-radius: 8px 8px 0 0; }
        .v-tab { padding: 12px 24px; cursor: pointer; color: #94a3b8; font-weight: 600; font-size: 0.9rem; border-bottom: 3px solid transparent; transition: all 0.2s; user-select: none; }
        .v-tab:hover { color: #cbd5e1; background: #283548; }
        .v-tab.active { color: #38bdf8; border-bottom-color: #38bdf8; }
        .v-tab .v-count { background: #334155; color: #94a3b8; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; margin-left: 8px; }
        .v-tab.active .v-count { background: #0c4a6e; color: #38bdf8; }
        .v-tab-content { display: none; }
        .v-tab-content.active { display: block; }
        /* Verification table styles */
        .v-section h2 { color: #38bdf8; font-size: 1.4rem; margin-bottom: 6px; }
        .v-section .v-subtitle { color: #94a3b8; margin-bottom: 20px; font-size: 0.9rem; }
        .v-summary { display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }
        .v-stat { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px 20px; min-width: 120px; }
        .v-stat .v-label { color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; }
        .v-stat .v-value { font-size: 1.6rem; font-weight: 700; color: #f1f5f9; margin-top: 2px; }
        .v-stat .v-value.green { color: #4ade80; }
        .v-stat .v-value.blue { color: #60a5fa; }
        .v-section table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
        .v-section th { background: #1e293b; color: #38bdf8; padding: 10px 8px; text-align: left; border-bottom: 2px solid #334155; font-weight: 600; }
        .v-section th.center, .v-section td.center { text-align: center; }
        .v-section td { padding: 7px 8px; border-bottom: 1px solid #1e293b; vertical-align: top; }
        .v-section tr:hover { background: #1e293b; }
        .v-section .status-pass { color: #4ade80; font-weight: 700; }
        .v-section .status-warn { color: #facc15; font-weight: 700; }
        .v-section .status-fail { color: #f87171; font-weight: 700; }
        .v-section .env { font-family: monospace; color: #a5b4fc; }
        .v-section .badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; font-family: monospace; }
        .v-section .badge.lead { background: #166534; color: #4ade80; }
        .v-section .badge.attach { background: #1e3a5f; color: #60a5fa; }
        .v-section .pages { color: #64748b; font-size: 0.78rem; }
        .v-section .sources { max-width: 420px; }
        .v-section .missing { color: #64748b; font-style: italic; }
        .v-section .source-file { margin: 2px 0; white-space: nowrap; }
        .v-section table { table-layout: auto; }
        .v-section { overflow: auto; max-height: calc(100vh - 200px); }
        .export-btn {
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(59,130,246,0.15); color: #60a5fa;
            border: 1px solid rgba(59,130,246,0.3); border-radius: 6px;
            padding: 8px 16px; cursor: pointer; font-size: 0.85rem;
            font-weight: 500; transition: all 0.2s;
        }
        .export-btn:hover { background: rgba(59,130,246,0.25); color: #93c5fd; }
        .v-section a { color: #60a5fa; text-decoration: none; }
        .v-section a:hover { text-decoration: underline; color: #93c5fd; }

        /* Engine Status Banner */
        .engine-banner {
            padding: 10px 20px;
            border-radius: 8px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.9rem;
            font-weight: 500;
        }
        .engine-banner.running { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); color: #4ade80; }
        .engine-banner.idle { background: rgba(96, 165, 250, 0.1); border: 1px solid rgba(96, 165, 250, 0.2); color: #93c5fd; }
        .engine-banner.error { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; }
        .engine-banner.stalled { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.3); color: #fbbf24; }
        .engine-banner.stopped { background: rgba(100, 116, 139, 0.1); border: 1px solid rgba(100, 116, 139, 0.2); color: #94a3b8; }
        .engine-progress { flex: 1; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; }
        .engine-progress-fill { height: 100%; background: #4ade80; transition: width 0.5s ease; border-radius: 3px; }
    </style>
</head>
<body>
    <div class="container">
        <!-- TOP-LEVEL TAB BAR -->
        <div class="main-tab-bar">
            <div class="main-tab active" onclick="switchMainTab('activity')">📊 Activity</div>
            <div class="main-tab" onclick="switchMainTab('verification')">✅ Verification</div>
            <div class="main-tab" onclick="switchMainTab('csv1')">📋 Phase 1 CSV</div>
            <div class="main-tab" onclick="switchMainTab('csv2')">📋 Phase 2 CSV</div>
        </div>

        <!-- ENGINE STATUS BANNER -->
        {ENGINE_STATUS_BANNER}

        <!-- ACTIVITY TAB (existing dashboard) -->
        <div id="main-activity" class="main-tab-content active">
        <header>
            <div class="section-header">
                <div style="display: flex; align-items: center; gap: 15px; width: 100%;">
                    <img src="assets/pcp_logo.jpg" style="height: 50px; width: auto; object-fit: contain;">
                    <div>
                        <h1>PCP Nexus Dashboard</h1>
                        <div class="refresh-time">Last Updated: {GENERATED_AT}</div>
                    </div>
                    <div class="refresh-toggle-wrap">
                        <span class="refresh-indicator" id="refreshDot"></span>
                        <span class="refresh-toggle-label" id="refreshLabel">Auto-Refresh</span>
                        <label class="toggle-switch">
                            <input type="checkbox" id="refreshToggle" checked>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                </div>
            </div>
        </header>

        <div class="stats-grid">
            <div class="card">
                <div class="stat-value" style="color: var(--text-primary)">{TOTAL_JOBS}</div>
                <div class="stat-label">Total Jobs</div>
            </div>
            <div class="card">
                <div class="stat-value" style="color: var(--success)">{SUCCESS_RATE}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
            <div class="card">
                <div class="stat-value" style="color: var(--warning)">{DUPLICATES}</div>
                <div class="stat-label">Duplicates Caught</div>
            </div>
            <div class="card">
                <div class="stat-value" style="color: var(--danger)">{ACTION_ITEMS}</div>
                <div class="stat-label">Action Items</div>
            </div>
        </div>

        <div class="section-header">
            <h2>🚨 Manual Review Queue</h2>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Filename</th>
                        <th>Flag</th>
                        <th>Env ID</th>
                        <th>Case #</th>
                        <th>Job #</th>
                        <th>Lead Doc</th>
                        <th>Status</th>
                        <th>Issue / Reason</th>
                        <th>Prescribed Next Steps</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {ACTION_ROWS}
                </tbody>
            </table>
        </div>
        
        <br><br>

        <div class="section-header">
            <h2>⚠️ Duplicate Review</h2>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Dup ID</th>
                        <th>Dup Source (Pending)</th>
                        <th>Dup File</th>
                        <th>Orig ID</th>
                        <th>Orig Source (Existing)</th>
                        <th>Orig File</th>
                    </tr>
                </thead>
                <tbody>
                    {DUPLICATE_ROWS}
                </tbody>
            </table>
        </div>
        
        <br><br>

        <div class="section-header">
            <h2>✅ Recent Filings</h2>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Filename</th>
                        <th>Orig Prefix</th>
                        <th>New Prefix</th>
                        <th>Location</th>
                        <th>Computer</th>
                        <th>Status</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    {RECENT_ROWS}
                </tbody>
            </table>
        </div>
        <br><br>

        <div class="section-header">
            <h2>📜 24-Hour Activity Log</h2>
        </div>
        <script>
        function exportActivityLog() {
            // Extract table data
            const table = document.querySelector('.table-container table');
            const rows = table.querySelectorAll('tbody tr');
            let csv = 'ID,Time,Filename,Env ID,Case #,Job #,Lead Doc,Orig Input,Orig Prefix,New Prefix,Status,Outcome,Next Steps\\n';
            
            rows.forEach(row => {
                const cells = row.querySelectorAll('td');
                const rowData = Array.from(cells).map(cell => {
                    let text = cell.textContent.trim();
                    // Escape quotes and wrap in quotes if contains comma
                    if (text.includes(',') || text.includes('"') || text.includes('\\n')) {
                        text = '"' + text.replace(/"/g, '""') + '"';
                    }
                    return text;
                }).join(',');
                csv += rowData + '\\n';
            });
            
            // Download CSV
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const now = new Date();
            const filename = `PCP_Activity_Log_${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}.csv`;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }
        </script>
        <div class="table-container" style="max-height: 500px; overflow-y: auto;">
            <table>
                <thead>
                    <tr>
                        <th style="position: sticky; top: 0; z-index: 10;">ID</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Time</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Filename</th>
                        
                        <th style="position: sticky; top: 0; z-index: 10;">Env ID</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Case #</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Job #</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Lead Doc</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Orig Input</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Orig Prefix</th>
                        <th style="position: sticky; top: 0; z-index: 10;">New Prefix</th>
                        
                        <th style="position: sticky; top: 0; z-index: 10;">Status</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Outcome</th>
                        <th style="position: sticky; top: 0; z-index: 10;">Next Steps</th>
                    </tr>
                </thead>
                <tbody>
                    {LOG_ROWS}
                </tbody>
            </table>
        </div>

        <br><br>
        <div class="section-header">
            <h2>💬 Comments & Follow-up</h2>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Filename</th>
                        <th>Env ID</th>
                        <th>Comments</th>
                        <th>Status</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    {COMMENT_ROWS}
                </tbody>
            </table>
        </div>
        </div><!-- /main-activity -->

        <!-- VERIFICATION TAB -->
        <div id="main-verification" class="main-tab-content">
            {VERIFICATION_TAB_CONTENT}
        </div>

        <!-- PHASE 1 CSV TAB -->
        <div id="main-csv1" class="main-tab-content">
            <div style="padding: 24px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                    <div>
                        <h2 style="color: #e2e8f0; margin-bottom: 4px;">📋 Phase 1 CSV — Current Local</h2>
                        <p style="color: #64748b; font-size: 0.85rem;">Affidavits (Rename) — Rotated daily at 10:00 PM</p>
                    </div>
                    <button class="export-btn" onclick="exportCSVTab('csv1')">📥 Export CSV</button>
                </div>
                <div id="csv1-data">{CSV1_TABLE}</div>
            </div>
        </div>

        <!-- PHASE 2 CSV TAB -->
        <div id="main-csv2" class="main-tab-content">
            <div style="padding: 24px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                    <div>
                        <h2 style="color: #e2e8f0; margin-bottom: 4px;">📋 Phase 2 CSV — Current Local</h2>
                        <p style="color: #64748b; font-size: 0.85rem;">Merge (Aggregation) — Rotated hourly</p>
                    </div>
                    <button class="export-btn" onclick="exportCSVTab('csv2')">📥 Export CSV</button>
                </div>
                <div id="csv2-data">{CSV2_TABLE}</div>
            </div>
        </div>
    </div>
    <script>
    // Tab Navigation
    function switchMainTab(tab) {
        document.querySelectorAll('.main-tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.main-tab').forEach(el => el.classList.remove('active'));
        document.getElementById('main-' + tab).classList.add('active');
        document.querySelector('.main-tab[onclick*="' + tab + '"]').classList.add('active');
    }
    function switchVTab(tab) {
        document.querySelectorAll('.v-tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.v-tab').forEach(el => el.classList.remove('active'));
        document.getElementById('vtab-' + tab).classList.add('active');
        document.querySelector('.v-tab[onclick*="' + tab + '"]').classList.add('active');
    }

    // Auto-Refresh Toggle System
    // CSV Export for Phase 1/2 tabs
    function exportCSVTab(tabId) {
        const container = document.getElementById(tabId + '-data');
        if (!container) return;
        const table = container.querySelector('table');
        if (!table) return;
        let csv = '';
        table.querySelectorAll('tr').forEach(row => {
            const cells = row.querySelectorAll('th, td');
            const rowData = Array.from(cells).map(cell => {
                let text = cell.textContent.trim();
                if (text.includes(',') || text.includes('"') || text.includes('\\n')) {
                    text = '"' + text.replace(/"/g, '""') + '"';
                }
                return text;
            }).join(',');
            csv += rowData + '\\n';
        });
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const phase = tabId === 'csv1' ? 'Phase1' : 'Phase2';
        const now = new Date();
        a.download = `PCP_${phase}_${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }
    (function() {
        const REFRESH_INTERVAL_MS = 10000; // 10 seconds
        const STORAGE_KEY = 'pcp_dashboard_autorefresh';
        let refreshTimer = null;

        const toggle = document.getElementById('refreshToggle');
        const dot = document.getElementById('refreshDot');
        const label = document.getElementById('refreshLabel');

        // Load saved preference (default: ON)
        const savedState = localStorage.getItem(STORAGE_KEY);
        const isOn = savedState === null ? true : savedState === 'true';
        toggle.checked = isOn;

        function startRefresh() {
            stopRefresh();
            refreshTimer = setInterval(() => { location.reload(); }, REFRESH_INTERVAL_MS);
            dot.classList.add('active');
            label.textContent = 'Auto-Refresh';
        }

        function stopRefresh() {
            if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
            dot.classList.remove('active');
            label.textContent = 'Paused';
        }

        toggle.addEventListener('change', function() {
            localStorage.setItem(STORAGE_KEY, this.checked);
            this.checked ? startRefresh() : stopRefresh();
        });

        // Initialize
        isOn ? startRefresh() : stopRefresh();
    })();
    </script>
</body>
</html>
"""






import re

def parse_log_reason(logs):
    if not logs: return "No Logs"
    
    # Specific Mapping for Legacy/Generic Status Logs
    if "MANUAL_REVIEW using FAILED" in logs:
        return "Audit Verification Failed"
    if "File missing during archive" in logs:
        return "System: File Missing (Archive)"
        
    triggers = ["Reason:", "Verification Failed:", "Audit Failed:", "Error:","[ERR]"]
    reason = None
    for t in triggers:
        if t in logs:
             reason = logs.split(t)[-1].split("\n")[0].strip()
             break
    
    if not reason:
        # Fallback: Last 60 chars, but try to find a clean start
        reason = logs[-60:]
        
    # Cleanup Timestamp [YYYY-MM-DD...] or partials like 025-12-30...
    # Remove standard brackets
    reason = re.sub(r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]', '', reason).strip()
    # Remove orphan date strings like "025-12-30 13:20:49]" if truncation broke the bracket
    reason = re.sub(r'^\d{3,}-\d{2}-\d{2}.*?\]', '', reason).strip()
    
    # Cleanup [Orion] or [AgentName]
    reason = re.sub(r'\[.*?\]', '', reason).strip()
    
    return reason if reason else "Unknown Error"


def get_stage_name(status):
    if status == 'QA_FAILED': return "1. Intake (Validation)"
    if status == 'MANUAL_REVIEW': return "2. Audit (Verification)"
    if status == 'ERROR': return "3. System/Archive"
    if status == 'DUPLICATE': return "0. Pre-Processing"
    return status


def get_resolution_strategy(reason, file_path):
    """Maps failure reasons to specific human actions."""
    reason = reason.lower()
    
    if "audit verification failed" in reason:
        return "1. Open File. 2. Visually verify Case Number. 3. If valid, manually move to 'Verified' or use Console to force status."
        
    if "file missing" in reason:
        folder = os.path.dirname(file_path) if file_path else "Source"
        return f"1. Check folder '{folder}'. 2. If file lost, re-download from Outlook. 3. If present, check permissions."
        
    if "validation failed" in reason:
        return "1. Review PDF content. 2. If it's a valid Affidavit, check OCR quality. 3. If non-standard, reject or manually key."
        
    if "duplicate" in reason:
        return "1. Review 'Duplicate Review' table. 2. If strict duplicate, Ignore. 3. If new content, rename and re-submit."

    return "1. Investigate Logs. 2. Determine root cause."


def _extract_verification_content():
    """
    Read the standalone verification_report.html and extract the body content
    for embedding in the dashboard as a tab. Strips login overlay and scripts,
    remaps CSS classes to avoid collisions.
    """
    # Find verification_report.html relative to the Source directory
    source_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_path = os.path.join(os.path.dirname(source_dir), "verification_report.html")
    
    if not os.path.exists(report_path):
        return '<div style="padding: 2rem; color: #94a3b8; text-align: center;"><h3>Verification Report Not Found</h3><p>Place verification_report.html in the project root.</p></div>'
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            raw_html = f.read()
        
        # Extract just the #main-content div contents
        # Find start: after <div id="main-content">
        start_marker = '<div id="main-content">'
        end_marker = '<script>'
        
        start_idx = raw_html.find(start_marker)
        if start_idx == -1:
            return '<div style="padding: 2rem; color: #94a3b8;">Could not parse verification report.</div>'
        
        start_idx += len(start_marker)
        
        # Find the last </div> before the first <script>
        script_idx = raw_html.find(end_marker, start_idx)
        if script_idx == -1:
            script_idx = len(raw_html)
        
        # Go back to find the closing </div> of main-content before <script>
        content = raw_html[start_idx:script_idx].strip()
        
        # Remove the trailing </div> that closes main-content
        if content.endswith('</div>'):
            content = content[:-6].strip()
        
        # Wrap everything in v-section for CSS scoping
        content = '<div class="v-section">' + content + '</div>'
        
        # Remap the tab system to use v-tab classes to avoid collisions
        content = content.replace('class="tab-bar"', 'class="v-tab-bar"')
        content = content.replace('class="tab active"', 'class="v-tab active"')
        content = content.replace('class="tab"', 'class="v-tab"')
        content = content.replace('class="tab-content active"', 'class="v-tab-content active"')
        content = content.replace('class="tab-content"', 'class="v-tab-content"')
        content = content.replace('class="count"', 'class="v-count"')
        
        # Remap tab IDs: tab-p1 -> vtab-p1, tab-p2 -> vtab-p2
        content = content.replace('id="tab-p1"', 'id="vtab-p1"')
        content = content.replace('id="tab-p2"', 'id="vtab-p2"')
        
        # Remap onclick from switchTab to switchVTab
        content = content.replace("switchTab('p1')", "switchVTab('p1')")
        content = content.replace("switchTab('p2')", "switchVTab('p2')")
        
        # Remap stat CSS classes
        content = content.replace('class="summary"', 'class="v-summary"')
        content = content.replace('class="stat"', 'class="v-stat"')
        content = content.replace('class="label"', 'class="v-label"')
        content = content.replace('class="value"', 'class="v-value"')
        content = content.replace('class="value green"', 'class="v-value green"')
        content = content.replace('class="value blue"', 'class="v-value blue"')
        content = content.replace('class="subtitle"', 'class="v-subtitle"')
        
        return content
        
    except Exception as e:
        return f'<div style="padding: 2rem; color: #f87171;">Error loading verification report: {e}</div>'

def _read_csv_for_dashboard(phase):
    """
    Query the database for phase-specific job data and render as an HTML table.
    Pulls directly from the DB (not the polling CSVs) for always-current data.
    phase: "Phase1" or "Phase2"
    """
    import json as _json
    
    service_type = "AFFIDAVITS" if phase == "Phase1" else "PROJECT_2"
    target_status = "ARCHIVED" if phase == "Phase1" else "FILED"
    
    headers = ["Envelope_Num", "Case_Num", "Date_Submitted", "Time_Submitted",
               "Date_Accepted", "Time_Accepted", "Lead_Document", "PCP_Job_Num"]
    
    try:
        if not os.path.exists(DB_PATH):
            return '<div style="padding: 1rem; color: #64748b; font-style: italic;">Database not found.</div>'
        
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT metadata FROM jobs WHERE service_type = ? AND status = ? ORDER BY updated_at DESC",
            (service_type, target_status)
        )
        db_rows = cursor.fetchall()
        conn.close()
        
        if not db_rows:
            return f'<div style="padding: 1rem; color: #64748b; font-style: italic;">No {phase} data yet.</div>'
        
        # Extract CSV-equivalent fields from metadata JSON
        rows = []
        for db_row in db_rows:
            try:
                meta = _json.loads(db_row['metadata']) if db_row['metadata'] else {}
            except:
                meta = {}
            
            envelope = meta.get('envelope', meta.get('envelope_num', meta.get('envelope_id', '-')))
            case_num = meta.get('case_num', '-')
            lead_doc = meta.get('lead_doc', meta.get('lead_document', meta.get('subject', '-')))
            pcp_job = meta.get('pcp_job_num', meta.get('job_num', '-'))
            
            # Parse dates
            ds_raw = meta.get('date_submitted_raw', '')
            da_raw = meta.get('date_accepted_raw', '')
            
            def _split_dt(raw):
                if not raw:
                    return ('-', '-')
                parts = str(raw).strip().split(' ', 1)
                return (parts[0], parts[1] if len(parts) > 1 else '-')
            
            ds_date, ds_time = _split_dt(ds_raw)
            da_date, da_time = _split_dt(da_raw)
            
            rows.append([str(envelope), str(case_num), ds_date, ds_time, da_date, da_time, str(lead_doc), str(pcp_job)])
        
        # Build HTML table
        html_parts = [
            f'<div style="color: #94a3b8; font-size: 0.85rem; margin-bottom: 8px;">📊 {len(rows)} records from database</div>',
            '<div class="table-container" style="max-height: 600px; overflow-y: auto;">',
            '<table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">',
            '<thead><tr>'
        ]
        
        for h in headers:
            html_parts.append(f'<th style="position: sticky; top: 0; z-index: 10; background: #1e293b; padding: 8px 12px; text-align: left; color: #94a3b8; border-bottom: 2px solid #334155;">{h}</th>')
        
        html_parts.append('</tr></thead><tbody>')
        
        for row in rows:
            html_parts.append('<tr style="border-bottom: 1px solid #1e293b;">')
            for cell in row:
                html_parts.append(f'<td style="padding: 6px 12px; color: #e2e8f0;">{cell}</td>')
            html_parts.append('</tr>')
        
        html_parts.append('</tbody></table></div>')
        
        return '\n'.join(html_parts)
        
    except Exception as e:
        return f'<div style="padding: 1rem; color: #f87171;">Error loading {phase} data: {e}</div>'

def _build_engine_status_banner():
    """Read engine_status.json and return an HTML status banner."""
    try:
        from core.status_writer import StatusWriter
        status = StatusWriter.read()
        if not status:
            return '<div class="engine-banner stopped">⚪ Engine status unavailable</div>'
        
        state = status.get("state", "STOPPED")
        phase = status.get("phase", "")
        activity = status.get("activity", "")
        progress = status.get("progress", "")
        envelope = status.get("current_envelope", "")
        
        phase_label = "Phase 1" if phase == "Phase1" else "Phase 2" if phase == "Phase2" else ""
        
        if state == "RUNNING" and progress:
            # Calculate progress percentage for the bar
            try:
                current, total = progress.split("/")
                pct = min(100, int(int(current) / int(total) * 100))
            except Exception:
                pct = 0
            
            elapsed_text = ""
            cycle_start = status.get("cycle_start")
            if cycle_start:
                try:
                    start = datetime.datetime.fromisoformat(cycle_start)
                    elapsed = datetime.datetime.now() - start
                    mins = int(elapsed.total_seconds() // 60)
                    secs = int(elapsed.total_seconds() % 60)
                    elapsed_text = f" &mdash; ⏱ {mins}m {secs}s"
                except Exception:
                    pass
            
            env_text = f" | Envelope: {envelope}" if envelope else ""
            return f'''<div class="engine-banner running">
                <span>🟢 {phase_label}: {activity} [{progress}]{env_text}{elapsed_text}</span>
                <div class="engine-progress"><div class="engine-progress-fill" style="width:{pct}%"></div></div>
            </div>'''
        elif state == "RUNNING":
            return f'<div class="engine-banner idle">🟢 Engine Active &mdash; {activity}</div>'
        elif state == "ERROR":
            return f'<div class="engine-banner error">🔴 {activity}</div>'
        elif state == "STALLED":
            return '<div class="engine-banner stalled">🟡 Engine Stalled &mdash; No heartbeat detected</div>'
        else:
            return '<div class="engine-banner stopped">⚪ Engine Stopped</div>'
    except Exception:
        return '<div class="engine-banner stopped">⚪ Engine status unavailable</div>'

def generate_dashboard(days=1, output_mode='file'):
    """
    Generates dashboard data or HTML.
    output_mode: 'file' (writes HTML), 'string' (HTML), 'data' (Dict).
    """
    try:
        if not os.path.exists(DB_PATH):
            print(f"DTO_DEBUG: DB Path Not Found: {DB_PATH}")
            # Fallback: Return empty dashboard instead of None to prevent UI errors
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return EMPTY_DASHBOARD_TEMPLATE.replace("{TIMESTAMP}", now_str)

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # SAFETY CHECK: Ensure 'jobs' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
        if not cursor.fetchone():
            print("DTO_DEBUG: 'jobs' table not found in DB.")
            conn.close()
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return EMPTY_DASHBOARD_TEMPLATE.replace("{TIMESTAMP}", now_str)

        print(f"DEBUG_DASH: Using DB at {DB_PATH}")

        # Time Filter
        time_filter = f"created_at >= datetime('now', '-{days} day')"
        
        # --- QUERIES (Wrapped in try/except blocks if schema changes?) ---
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE {time_filter}")
        period_jobs = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM jobs")
        total_jobs_all_time = cursor.fetchone()[0]
        
        # Success Rate logic: Include standard successes + Manual Reviews that are flagged with action_flag=1
        # (Flagged items are successful identifies, but held for instructional SOP review)
        cursor.execute(f"""
            SELECT COUNT(*) FROM jobs 
            WHERE (status IN ('FILED', 'VERIFIED', 'ARCHIVED', 'EXCEPTION_PROCESSED', 'DUPLICATE') 
                   OR (status = 'MANUAL_REVIEW' AND action_flag = 1))
            AND {time_filter}
        """)
        success_count = cursor.fetchone()[0]
        
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE status='DUPLICATE' AND {time_filter}")
        dup_count = cursor.fetchone()[0]
        
        # Count Expired (Excluded from Failure Rate)
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE status='EXPIRED' AND {time_filter}")
        expired_count = cursor.fetchone()[0]

        # Query for Action Items (Now Includes EXPIRED for visibility)
        cursor.execute("SELECT * FROM jobs WHERE status IN ('MANUAL_REVIEW', 'ERROR', 'EXPIRED') ORDER BY id DESC")
        action_rows = []
        for row in cursor.fetchall():
            d = dict(row)
            
            # --- METADATA EXTRACTION ---
            import json
            try:
                meta_json = d.get('metadata', '{}')
                meta = json.loads(meta_json) if meta_json else {}
            except:
                meta = {}
            
            d['envelope_id'] = meta.get('envelope_id', '-')
            d['case_num'] = meta.get('case_num', '-')
            d['job_num'] = meta.get('job_num', meta.get('pcp_job_num', '-'))
            d['lead_doc'] = meta.get('lead_doc', meta.get('subject', '-'))
            d['orig_filename'] = meta.get('original_filename', '-') 
            
            # Prefer Metadata-defined Reason/Resolution over generic parsing
            d['stage'] = get_stage_name(d['status'])
            d['reason'] = meta.get('reason', parse_log_reason(d.get('logs', '')))
            d['resolution'] = meta.get('steps', get_resolution_strategy(d['reason'], d.get('file_path')))
            
            action_rows.append(d)
        
        print(f"DEBUG_DASH: Found {len(action_rows)} Action Items in DB.")

        # Duplicate Comparison Query (Self-Join)
        # Find Duplicates and their "Originals" (older ID)
        cursor.execute("""
            SELECT 
                d.id as dup_id, d.filename as dup_filename, d.original_source as dup_source, d.created_at as dup_time, d.file_path as dup_path,
                o.id as orig_id, o.filename as orig_filename, o.original_source as orig_source, o.created_at as orig_time, o.file_path as orig_path
            FROM jobs d
            JOIN jobs o ON d.file_hash = o.file_hash AND d.id > o.id
            WHERE d.status = 'DUPLICATE'
            ORDER BY d.id DESC LIMIT 50
        """)
        duplicate_rows = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM jobs WHERE status IN ('FILED', 'ARCHIVED') ORDER BY id DESC LIMIT 10")
        raw_recent = [dict(row) for row in cursor.fetchall()]
        recent_rows = []
        for r in raw_recent:
            import json
            try:
                meta = json.loads(r.get('metadata', '{}')) if r.get('metadata') else {}
            except: meta = {}
            
            # File Column Logic
            # Old File = Prefer Lead Doc (has Prefix) -> or Original Filename -> or Subject -> or -
            # New File = Final Generated Filename (from DB)
            r['old_file'] = meta.get('lead_doc') or meta.get('original_filename') or meta.get('subject') or '-'
            r['new_file'] = r.get('filename') or '-'
            r['file_path_short'] = r.get('file_path','')[-40:] if r.get('file_path') else '-'
            
            # Fallback for old prefix if original filename is garbage
            r['input_prefix'] = r['old_file'][:4].upper() if len(r['old_file']) >= 4 else "-"
            
            # Extract Destination Prefix (New Prefix) from final filename
            # The filename starts with the destination prefix (e.g., AX02..., AX03...)
            final_filename = r.get('filename', '')
            try:
                # Match AXnn at the start of filename
                prefix_match = re.match(r'^(AX\d{2})', final_filename)
                if prefix_match:
                    r['dest_prefix'] = prefix_match.group(1)
                else:
                    r['dest_prefix'] = "-"
            except: 
                r['dest_prefix'] = "-"
                
            recent_rows.append(r)
        
        cursor.execute(f"SELECT * FROM jobs WHERE {time_filter} ORDER BY id DESC")
        log_rows = [dict(row) for row in cursor.fetchall()]

        # Failure Analytics (Exclude Action-Flagged items as they are 'Successes' in the metrics)
        cursor.execute(f"""
            SELECT service_type, status, logs FROM jobs 
            WHERE status IN ('QA_FAILED', 'ERROR', 'MANUAL_REVIEW') 
            AND (action_flag = 0 OR action_flag IS NULL)
            AND {time_filter}
        """)
        all_failures = cursor.fetchall()
        
        fail_by_type = {}
        fail_by_stage = {}
        fail_by_reason = {}
        
        for row in all_failures:
            # Type
            st = row['service_type'] or "Unknown"
            fail_by_type[st] = fail_by_type.get(st, 0) + 1
            
            # Stage
            stat = row['status']
            stage_name = get_stage_name(stat)
            fail_by_stage[stage_name] = fail_by_stage.get(stage_name, 0) + 1
            
            # Reason
            logs = row['logs'] or ""
            reason = parse_log_reason(logs)
            # Normalize common obscure errors
            # Normalize common obscure errors
            if len(reason) > 30: reason = reason[:27] + "..."
            
            fail_by_reason[reason] = fail_by_reason.get(reason, 0) + 1
        
        failure_stats = {
            "by_type": fail_by_type,
            "by_stage": fail_by_stage,
            "by_reason": fail_by_reason
        }
        
        conn.close()

        # --- DATA PROCESSING (Same as before) ---
        effective_success = success_count + dup_count
        # Adjusted Rate: Exclude EXPIRED from the denominator (It's a "Non-Event")
        adjusted_total = period_jobs - expired_count
        success_rate = round((effective_success / adjusted_total * 100), 1) if adjusted_total > 0 else 0
        
        # DATA MODE RETURN
        if output_mode == 'data':
            return {
                "period_jobs": period_jobs,
                "total_jobs": total_jobs_all_time,
                "success_count": success_count,
                "dup_count": dup_count,
                "expired_count": expired_count, # Added for UI visibility if needed
                "success_rate": success_rate,
                "action_items": action_rows,
                "recent_items": recent_rows,
                "logs": log_rows,
                "failure_stats": failure_stats
            }

        # --- HTML GENERATION (Legacy Support) ---
        
        # ... Action Rows HTML building ...
        action_html = ""
        if not action_rows:
            action_html = "<tr><td colspan='5' style='text-align:center; color:#94a3b8; padding:2rem'>✅ No Manual Review Items. Queue Empty.</td></tr>"
        else:
            for row in action_rows:
                logs = row['logs'] if row['logs'] else ""
                reason = parse_log_reason(logs)
                
                fpath = row['file_path'] if row['file_path'] else "N/A"
                if fpath != "N/A" and not os.path.isabs(fpath): fpath = os.path.abspath(fpath)
                
                file_url = f"file:///{fpath.replace(os.sep, '/')}"
                folder_url = f"file:///{os.path.dirname(fpath).replace(os.sep, '/')}" if fpath != "N/A" else "#"
                
                
                status_class = "status-failed"
                
                # Intelligent Flag with Red Triangle SVG
                flag_html = ""
                if row.get('action_flag') == 1:
                    flag_html = """
                    <div class="potential-action-flag">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="#ef4444" stroke="currentColor" stroke-width="2">
                            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                            <line x1="12" y1="9" x2="12" y2="13" stroke="white"/>
                            <line x1="12" y1="17" x2="12.01" y2="17" stroke="white"/>
                        </svg>
                        !
                    </div>
                    """
                
                comments = row.get('raw_comments', '')
                if comments:
                    display_reason = f"<b>Potential Action Words Detected:</b><br><small>{comments[:200]}...</small>" if row.get('action_flag') == 1 else f"<b>Comments Found:</b><br><small>{comments[:200]}...</small>"
                else:
                    display_reason = reason

                # ID | Type | File | Envelope | Job | Lead Doc | Stage | Reason | Steps | Action
                action_html += f"""
                <tr>
                    <td>#{row['id']}</td>
                    <td>{row['filename']}</td>
                    <td>{flag_html}</td>
                    
                    <!-- NEW COLUMNS -->
                    <td><span style='font-family:monospace; font-size:0.9em; color:#94a3b8'>{row['envelope_id']}</span></td>
                    <td><span style='font-family:monospace; font-size:0.9em; color:#94a3b8'>{row['case_num']}</span></td>
                    <td><span style='font-family:monospace; font-size:0.9em; color:#94a3b8'>{row['job_num']}</span></td>
                    <td><span style='font-size:0.9em; color:#94a3b8'>{row.get('lead_doc', '-')}</span></td>
                    
                    <td><span class='status-badge {status_class}'>{row['status']}</span></td>
                    <td>{display_reason}</td>
                    <td style='color:#94a3b8; font-style:italic; font-size:0.85em'>{row['resolution']}</td>
                    <td><a href='{file_url}' class='action-btn' target='_blank'>Review</a></td>
                </tr>
                """


        # ... Duplicate Rows HTML ...
        dup_html = ""
        if not duplicate_rows:
            dup_html = "<tr><td colspan='6' style='text-align:center; color:#94a3b8; padding:2rem'>✅ No Duplicates Found.</td></tr>"
        else:
            for row in duplicate_rows:
                # Dup File Link
                d_path = row['dup_path'] if row['dup_path'] else "#"
                if d_path != "#" and not os.path.isabs(d_path): d_path = os.path.abspath(d_path)
                d_url = f"file:///{d_path.replace(os.sep, '/')}"
                
                # Orig File Link
                o_path = row['orig_path'] if row['orig_path'] else "#"
                if o_path != "#" and not os.path.isabs(o_path): o_path = os.path.abspath(o_path)
                o_url = f"file:///{o_path.replace(os.sep, '/')}"

                dup_html += f"""
                <tr>
                    <td><span class='status-badge status-duplicate'>#{row['dup_id']}</span></td>
                    <td><b>{row['dup_filename']}</b><br><small>{row['dup_source']}</small><br><span style='color:#94a3b8; font-size:0.8em'>{row['dup_time']}</span></td>
                    <td><a href='{d_url}' target='_blank'>View Dup</a></td>
                    <td><span class='status-badge status-verified'>#{row['orig_id']}</span></td>
                    <td><b>{row['orig_filename']}</b><br><small>{row['orig_source']}</small><br><span style='color:#94a3b8; font-size:0.8em'>{row['orig_time']}</span></td>
                    <td><a href='{o_url}' target='_blank'>View Orig</a></td>
                </tr>
                """

        # ... Recent Rows ...
        recent_html = ""
        for row in recent_rows:
            fpath = row.get('file_path', '#')
            if fpath != "#" and not os.path.isabs(fpath): fpath = os.path.abspath(fpath)
            furl = f"file:///{fpath.replace(os.sep, '/')}"
            link_text = "Open File" if fpath != "#" else "-"
            
            recent_html += f"""
            <tr>
                <td>#{row['id']}</td>
                <td title='{row['filename']}'>{row['filename'][:25]}...</td>
                <td><span class='status-badge'>{row['input_prefix']}</span></td>
                <td><span class='status-badge' style='background:rgba(59,130,246,0.1); color:#3b82f6'>{row['dest_prefix']}</span></td>
                <td><a href='{furl}' target='_blank'>{link_text}</a></td>
                <td>{row.get('computer_name', '-')}</td>
                <td><span class='status-badge status-filed'>{row['status']}</span></td>
                <td>{row['created_at']}</td>
            </tr>
            """

        # ... Log Rows ...
        log_html = ""
        for row in log_rows:
            d = dict(row)
            # Parse Metadata
            import json
            try:
                meta_json = d.get('metadata', '{}')
                meta = json.loads(meta_json) if meta_json else {}
            except: meta = {}
            
            env_id = meta.get('envelope_num', meta.get('envelope_id', '-'))
            case_num = meta.get('case_num', '-')
            job_num = meta.get('pcp_job_num', meta.get('job_num', '-'))
            lead_doc = meta.get('lead_doc', meta.get('lead_document', meta.get('subject', '-')))
            if len(lead_doc) > 30: lead_doc = lead_doc[:27] + "..."
            
            orig_input = meta.get('original_filename', '-')
            if orig_input and '\\' in orig_input:
                orig_input = os.path.basename(orig_input)
            # Derive prefix from input: AX02... -> AX02
            input_prefix = "-"
            if orig_input and len(orig_input) >= 4: input_prefix = orig_input[:4].upper()

            s = d['status']
            badge = "status-filed"
            reason = "Processed"
            steps = "-"

            if s == 'DUPLICATE': 
                badge = "status-duplicate"
                reason = "Existing Record Found"
                steps = "Compare with Original"
            elif s in ['QA_FAILED', 'ERROR', 'MANUAL_REVIEW']: 
                badge = "status-failed"
                # Inherit Action Item logic for these
                reason = meta.get('reason', parse_log_reason(d.get('logs', '')))
                steps = meta.get('steps', get_resolution_strategy(reason, d.get('file_path')))
            elif s == 'EXPIRED':
                badge = "status-warning" # You might need to define this class or reuse duplicate
                reason = "Link Expired > 45 Days"
                steps = "Moved to Expired Links Folder"
            elif s in ['FILED', 'VERIFIED', 'ARCHIVED']: 
                badge = "status-verified"
                reason = "Filing Accepted / Verified"
                steps = "Archived Successfully"
            elif s == "NEW":
                badge = "status-filed"
                reason = "Ingested"
                steps = "Processing..."
            
            # Timestamp formatting (HH:MM)
            ts = d['created_at']
            try: ts = ts.split(" ")[1][:5] 
            except: pass

            # Build file link (like Recent Files section)
            fpath = d.get('file_path', '#')
            if fpath != "#" and not os.path.isabs(fpath): fpath = os.path.abspath(fpath)
            furl = f"file:///{fpath.replace(os.sep, '/')}"
            
            link_text = d['filename'][:20] + "..."
            filename_display = f"<a href='{furl}' target='_blank' style='color: #3b82f6; text-decoration: none;'>{link_text}</a>" if fpath != "#" else link_text

            # Extract ORIGINAL Prefix (from lead_doc or original input)
            old_file = lead_doc if lead_doc != '-' else orig_input
            orig_prefix = old_file[:4].upper() if len(old_file) >= 4 else "-"
            
            # Extract NEW/DESTINATION Prefix (from final filename - AXnn pattern)
            final_filename = d.get('filename', '')
            try:
                prefix_match = re.match(r'^(AX\d{2})', final_filename)
                if prefix_match:
                    dest_prefix = prefix_match.group(1)
                else:
                    dest_prefix = "-"
            except:
                dest_prefix = "-"

            log_html += f"""
            <tr>
                <td>#{d['id']}</td>
                <td style='color:#94a3b8; font-size:0.8em'>{ts}</td>
                <td title='{d['filename']}'>{filename_display}</td>
                
                <td><span style='font-family:monospace; font-size:0.9em; color:#94a3b8'>{env_id}</span></td>
                <td><span style='font-family:monospace; font-size:0.9em; color:#94a3b8'>{case_num}</span></td>
                <td><span style='font-family:monospace; font-size:0.9em; color:#94a3b8'>{job_num}</span></td>
                <td title='{meta.get("lead_doc", "")}' style='font-size:0.8em'>{lead_doc}</td>
                <td title='{orig_input}' style='font-size:0.8em; color:#64748b'>{orig_input[:15]}...</td>
                <td><span class='status-badge'>{orig_prefix}</span></td>
                <td><span class='status-badge' style='background:rgba(59,130,246,0.1); color:#3b82f6'>{dest_prefix}</span></td>
                
                <td><span class='status-badge {badge}'>{s}</span></td>
                <td style='font-size:0.8em'>{reason[:50]}</td>
                <td style='color:#94a3b8; font-size:0.8em; font-style:italic'>{steps[:50]}</td>
            </tr>
            """

        # --- TEMPLATE FILLING ---
        html = HTML_TEMPLATE.replace("{GENERATED_AT}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        html = html.replace("{TOTAL_JOBS}", str(period_jobs))
        html = html.replace("{SUCCESS_RATE}", str(success_rate))
        html = html.replace("{DUPLICATES}", str(dup_count))
        html = html.replace("{ACTION_ITEMS}", str(len(action_rows)))
        html = html.replace("{ACTION_ROWS}", action_html)
        html = html.replace("{DUPLICATE_ROWS}", dup_html)
        html = html.replace("{RECENT_ROWS}", recent_html)
        html = html.replace("{LOG_ROWS}", log_html)
        
        # Comments & Follow-up Section — jobs that have raw_comments
        comment_html = ""
        try:
            conn2 = sqlite3.connect(DB_PATH, timeout=5)
            conn2.row_factory = sqlite3.Row
            c2 = conn2.cursor()
            c2.execute("SELECT id, filename, original_source, raw_comments, status, created_at, metadata FROM jobs WHERE raw_comments IS NOT NULL AND raw_comments != '' ORDER BY created_at DESC LIMIT 50")
            comment_rows = c2.fetchall()
            conn2.close()
            for crow in comment_rows:
                try:
                    cmeta = json.loads(crow['metadata']) if crow['metadata'] else {}
                except:
                    cmeta = {}
                cenv = cmeta.get('envelope', crow['original_source'] or '-')
                ccomments = (crow['raw_comments'] or '').replace('\n', '<br>').replace('\t', ' ')[:300]
                cts = crow['created_at'].split(' ')[1] if ' ' in crow['created_at'] else crow['created_at']
                cstatus = crow['status']
                cbadge = 'status-verified' if cstatus in ('FILED','ARCHIVED','COMPLETED','VERIFIED') else 'status-failed'
                comment_html += f"""
                <tr>
                    <td>{crow['id']}</td>
                    <td>{crow['filename']}</td>
                    <td>{cenv}</td>
                    <td style="max-width:400px; font-size:0.8em; white-space:pre-wrap;">{ccomments}</td>
                    <td><span class='status-badge {cbadge}'>{cstatus}</span></td>
                    <td style="font-size:0.8em;">{cts}</td>
                </tr>"""
        except Exception:
            comment_html = '<tr><td colspan="6" style="color:#64748b; font-style:italic;">No comments data available</td></tr>'
        html = html.replace("{COMMENT_ROWS}", comment_html)
        
        # Engine Status Banner — reads engine_status.json
        status_banner_html = _build_engine_status_banner()
        html = html.replace("{ENGINE_STATUS_BANNER}", status_banner_html)

        # Verification Tab Content — Dynamic Generation (Daily Reset)
        # verification_content = _extract_verification_content() # LEGACY
        verification_content = VerificationReporter().generate_html()
        html = html.replace("{VERIFICATION_TAB_CONTENT}", verification_content)
        
        # CSV Tab Content — read phase-specific CSV files
        csv1_html = _read_csv_for_dashboard("Phase1")
        csv2_html = _read_csv_for_dashboard("Phase2")
        html = html.replace("{CSV1_TABLE}", csv1_html)
        html = html.replace("{CSV2_TABLE}", csv2_html)
        
        period_label = "Last 24 Hours"
        if days == 7: period_label = "Last 7 Days"
        if days == 30: period_label = "Last 30 Days"
        html = html.replace("PCP Nexus Dashboard", f"PCP Nexus | {period_label}")

        if output_mode == 'file':
            # ATOMIC WRITE: Write to .tmp, then replace
            abs_path = os.path.abspath(REPORT_PATH)
            temp_path = abs_path + ".tmp"
            
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(html)
            
            # Atomic swap
            os.replace(temp_path, abs_path)
            
            # print(f"Dashboard generated at: {abs_path}")
            return abs_path
        else: # output_mode == 'string'
            return html

    except Exception as e:
        err_path = os.path.join(str(app_paths.logs_dir()), "dashboard_error.log")
        try:
            with open(err_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now()}] Error: {e}\n")
                import traceback
                traceback.print_exc(file=f)
        except: pass
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return EMPTY_DASHBOARD_TEMPLATE.replace("{TIMESTAMP}", now_str)

LOG_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PCP Nexus | Session Log</title>
    <style>
        body { font-family: monospace; background: #0f172a; color: #f8fafc; padding: 2rem; }
        h1 { border-bottom: 1px solid #334155; padding-bottom: 1rem; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #334155; }
        th { color: #94a3b8; }
        .status-badge { padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; }
        .status-failed { color: #ef4444; background: rgba(239, 68, 68, 0.1); }
        .status-filed { color: #3b82f6; background: rgba(59, 130, 246, 0.1); }
        .status-verified { color: #10b981; background: rgba(16, 185, 129, 0.1); }
        .status-duplicate { color: #f59e0b; background: rgba(245, 158, 11, 0.1); }
    </style>
</head>
<body>
    <h1>Session Activity Log <span style="font-size:0.5em; color:#64748b">Generated: {GENERATED_AT}</span></h1>
    <table>
        <thead>
            <tr><th>Time</th><th>ID</th><th>File</th><th>Status</th><th>Message</th></tr>
        </thead>
        <tbody>
            {LOG_ROWS}
        </tbody>
    </table>
</body>
</html>
"""

def generate_log_snapshot(limit=50):
    """Generates a specialized HTML report containing ONLY the logs."""
    try:
        if not os.path.exists(DB_PATH): return None
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT * FROM jobs ORDER BY id DESC LIMIT {limit}")
        rows = cursor.fetchall()
        conn.close()
        
        log_html = ""
        for row in rows:
            s = row['status']
            badge = "status-filed"
            if s == 'DUPLICATE': badge = "status-duplicate"
            elif s in ['QA_FAILED', 'ERROR']: badge = "status-failed"
            elif s == 'NEW': badge = "status-verified"
            
            snippet = row['logs'][-60:] if row['logs'] else ""
            log_html += f"<tr><td>{row['created_at']}</td><td>#{row['id']}</td><td>{row['filename']}</td><td><span class='status-badge {badge}'>{s}</span></td><td>{snippet}</td></tr>"

        html = LOG_TEMPLATE.replace("{GENERATED_AT}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        html = html.replace("{LOG_ROWS}", log_html)
        return html
    except Exception:
        return None

if __name__ == "__main__":
    path = generate_dashboard(days=1, output_mode='file')
    print(f"Dashboard generated at: {path}")
