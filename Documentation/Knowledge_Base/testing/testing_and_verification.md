# PCP Nexus: Testing & Verification Authority

This document consolidates all verification strategies, stress-test results, and quality assurance protocols for the PCP Nexus platform.

---

## 1. Quality Assurance Strategy

The system uses a progression-based testing lifecycle, moving from mock verification to high-volume production simulations.

### 1.1 Progression Stages
- **Pilot Batch**: Verified scalability and basic logic.
- **Stress Test (Golden Run)**: 575-email dataset processed autonomously.
- **Live Fire Simulation**: Real MAPI delivery to verify Outlook's "Inbox Rule" behavior and HTML parsing.

### 1.2 Failure Impact Tiers
Failures are prioritized based on their operational impact:
- **P0: Data Loss/Logic**: Missing documents or corrupted merges.
- **P0: Environment Integration**: Outlook MAPI connection success (HRESULT 0x0).
- **P1: Classification**: Mis-identifying prefixes or missing "Action Words".
- **P2: Metadata**: Incorrect job number extraction.
- **P3: Dashboard/Reporting**: Visual or metric count errors.

---

## 2. In-Depth Verification Milestones

### 2.1 The Golden Run (575-Email Stress Test)
A 575-email dataset was used to stress-test the `HunterV2` agent in "Mega-Ralph" (persistence) mode.
- **Throughput**: 429 files ingested in ~10 seconds.
- **Success**: Achieve 100% throughput for actionable items once `LinkDownloader` and aggregation intervals were patched.
- **Resilience**: The system successfully resumed from a known-good baseline after a hardware power loss during the run.

### 2.2 Live Fire Simulation
Physically injecting scenarios from the `QA_Test_Set` into standard Hotmail/Outlook mailboxes.
- **Discovery**: Identified "Attachment Collision" hazards where identical filenames in different emails were overwriting each other in Staging.
- **Fix**: Implemented high-resolution relative timestamps in temporary filenames.

---

## 3. Edge Case Inventory

| Category | Edge Case | Handling Strategy |
| :--- | :--- | :--- |
| **User Logic** | Wrong Prefix | Move to `AI Exceptions` folder. |
| **Technical** | Multi-Defendant | Librarian reverse-lookup for secondary jobs. |
| **Technical** | Duplicate Resend | SHA-256 hash comparison; skip if identical. |
| **Technical** | Image-Only PDF | Fallback to `MANUAL_REVIEW` to avoid missing un-OCRed action words. |
| **Environment**| Batch Starvation | Increased batch size to 600 items to see past recently tagged items. |
| **Environment**| Privilege Mismatch | (Admin App vs User Outlook) Blocks COM. Ensure matching privilege levels. |
| **Environment**| PowerShell Popups | Enhanced window concealment via `CREATE_NO_WINDOW` and `STARTUPINFO` flags in `LinkDownloader`. |

---

## 6. Live Run Debugging Insights (Feb 2026)

During the pilot rollout, persistent issues with PowerShell windows and dashboard visibility were analyzed.

### 6.1 PowerShell Concealment
While `CREATE_NO_WINDOW` was present, some environments still flashed console windows during the `Invoke-WebRequest` cycles.
- **Root Cause**: PowerShell sub-processes spawning via the "ExecutionPolicy Bypass" flag sometimes ignored the parent's creation flags on specific Windows 10/11 build versions.
- **Resolution**: Enhanced concealment implementation using `subprocess.STARTUPINFO`:
  ```python
  if os.name == 'nt':
      si = subprocess.STARTUPINFO()
      si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # Note: Must be STARTF, not STARTFLAGS
      si.wShowWindow = subprocess.SW_HIDE
  ```
  This is used in conjunction with `creationflags=subprocess.CREATE_NO_WINDOW` to bypass flashing windows caused by `ExecutionPolicy Bypass`.

### 6.2 Data Persistence & Permissions
Investigations revealed that "Dashboard Not Available" was often caused by the app failing to create the database in the target directory (e.g., `ProgramData`).
- **Discovery**: Writable checks in `app_paths.py` are critical. If the app is installed in a restricted folder but *not* run as Admin, it may fail to even create the `data/` subdirectory.
- **Verification**: Confirmed that `C:\ProgramData\PCP-Automation` is a safer target than `%LOCALAPPDATA%` for multi-user consistency, provided the installer (Inno Setup) pre-creates the folder with permissive ACLs.

### 6.3 Startup Diagnostics & Live Heartbeat
To provide visibility into the "Black Box" behavior of the engine during pilot runs, a real-time **Diagnostics Console** was implemented.
- **Metrics Logged at Startup**:
    - **Environment**: Python version, CWD, OS/Architecture details.
    - **Identity**: Username and Computer Name (crucial for MAPI troubleshooting).
    - **Config Health**: Path to `config.json`, Existence check, and Permission mode.
    - **DB Health**: Path to `nexus.db`, Existence check, and connection verification.
    - **UI Stats**: Tk/Tcl versions and High-DPI scaling factors.
- **Purpose**: Allows IT staff to quickly verify if the engine is running with the correct permissions and paths without needing to grep local log files.

## 4. Mandatory Verification Protocols

### 4.1 The "Clean Slate" Reset
Mandatory before any major stress test to eliminate residual state.
1. **Terminate**: `taskkill /F /IM python.exe`
2. **Clear MAPI**: Reset `PCP-Processed` / `PCP-Packetized` tags via `reset_categories.py` (See Operations Manual Section 6.1).
3. **Nuke DB**: Delete `nexus.db` (or use the elevated clear script in Ops Manual 6.2).
4. **Purge Files**: Delete contents of `Staging/` and `temp_attachments/`.

### 4.2 Meta-Dump Diagnostic
Verify empty state:
`python -c "import sqlite3; conn=sqlite3.connect('nexus.db'); c=conn.cursor(); c.execute('SELECT COUNT(*) FROM pending_packets'); print(c.fetchone()[0])"`

### 4.3 Subprocess Constant Verification
Verify that the correct Windows suppression constants are available in the current Python environment:
`python -c "import subprocess; print(f'STARTF_USESHOWWINDOW: {subprocess.STARTF_USESHOWWINDOW}')"`
*Expected Output: `STARTF_USESHOWWINDOW: 1`*

## 5. Deployment Verification Record (Feb 2026)

| Test Case | Status | Verified On | Note |
| :--- | :---: | :--- | :--- |
| **frozen exe Startup** | ✅ | 2026-02-04 | No `ModuleNotFoundError` or Tcl/Tk crashes. |
| **MAPI Elevation Sync** | ✅ | 2026-02-04 | Connected to Outlook as Admin (matching integrity). |
| **Live Ingestion Logic**| ✅ | 2026-02-04 | Correct Phase 1/2 workflow split and Job extraction. |
| **PowerShell Suppression**| ✅ | 2026-02-04 | Aggressive concealment (SW_HIDE) verified during live run. |
| **Dashboard Access** | ✅ | 2026-02-04 | Immediate availability via Standby Screen verified. |
| **Log Schema Integrity** | ✅ | 2026-02-04 | 30-column sync verified in SharePointMirror. |
| **Intake Stability** | ✅ | 2026-02-04 | Verified `HunterV2 Cycle END - Success` after patching shadowing/subprocess bugs. |
| **Identity Verification**| ✅ | 2026-02-04 | Correct process identification via `MainWindowTitle` ("PCP Nexus | Document Automation") verified. |
| **Real-time Export Sync**| ✅ | 2026-02-04 | Concurrent CSV and Excel (.xlsx) generation verified. |
| **Dual-Prefix Auditing**| ✅ | 2026-02-04 | Verified "Orig Prefix" (Subject) vs "New Prefix" (Regex match) logic. |
| **Dashboard Interactivity**| ✅ | 2026-02-04 | Client-side Export button and Clickable file links (URI protocol) verified. |
| **Real-time Comments**| ✅ | 2026-02-04 | Verified `Has_Comments` and `Comments` extraction in CSV/Excel. |
| **Cross-Module Sync** | ✅ | 2026-02-04 | Standardized metadata keys and hybrid prefix logic verified across all 4 report modules. |
| **Folder Navigation** | ✅ | 2026-02-04 | Dashboard "Open Output Folder" button (file:/// URI) verified. |

### 6.4 Resolved: The "Instant Exception" Failure Mode
During stress testing, a condition was observed and subsequently resolved where all emails were immediately diverted to the `AI Exceptions` folder. 
- **Symptoms**: Logs show `Moving X items to Exceptions` for every envelope without processing.
- **Root Cause 1: SQLite Schema Inconsistency**: `sqlite3.OperationalError: no such table: jobs` surfaced in `HunterV2` despite initialization checks. This can occur if the database is file-locked or if the initial connection fails silently before schema application.
- **Root Cause 2: Deep Permission Denied**: `PermissionError: [WinError 5] Access is denied` occurring during `os.makedirs` (via `app_paths.ensure_dir`).
    - **Insight**: Even if the primary Data Dir is writable, the nested directory structure (e.g., `Output/Phase1/EnvelopeID/`) may hit a permission ceiling if the application attempts to create a folder chain where it lacks rights to a parent segment.
- **Root Cause 3: Subprocess Constant Mismatch**: `AttributeError: module 'subprocess' has no attribute 'STARTFLAGS_USESHOWWINDOW'`.
    - **Insight**: In some Python documentation or older snippets, `STARTFLAGS_USESHOWWINDOW` is cited, but the correct constant in modern Python `subprocess` modules on Windows is `STARTF_USESHOWWINDOW`. Using the wrong constant crashes the `LinkDownloader` thread, causing an immediate failover to `Exceptions`.
    - **Log Signature**: `[ERROR] Intake: Downloader Error: module 'subprocess' has no attribute 'STARTFLAGS_USESHOWWINDOW'`
- **Root Cause 4: Variable Scope Shadows**: `NameError: name 'metadata' is not defined`.
    - **Insight**: Deep within `hunter_v2.py`, logic originally used a generic `metadata` variable that was later refactored to `email_metadata` to avoid confusion with `job_metadata`. Some calls to `create_job` or logging missed this rename, leading to crashes in the "Success" branch of the intake flow.
- **Fix/Mitigation**:
    1. **Retry-Initialization**: `JobManager` now implements a "Retry-on-Missing-Table" loop, attempting to re-run `_create_tables` if an operational error indicates a missing schema.
    2. **Dashboard Standby**: If the database or tables are unavailable, the Dashboard now returns an `EMPTY_DASHBOARD_TEMPLATE` (Standby Page) instead of crashing, providing visual confirmation that the engine is waiting for data.
    3. **Path Validation**: Enhanced `ensure_dir` logging to capture the exact segment in the path chain that fails, allowing for faster IT intervention.
    4. **Constant Verification**: Standardized on `STARTF_USESHOWWINDOW` for all hidden process spawning.

## 7. Post-Patch Operational State (Final Status)

Following the implementation of the "Instant Exception" fixes, the system was verified to be in a stable operational state:

### 7.1 Successful Cycle Signature
The following log signature confirms that the `HunterV2` agent is successfully scanning and completing its work without crashing or diverting unnecessarily to exceptions:
```text
[2026-02-04 01:17:XX] [INFO] Starting Phase 1 Scan: Inbox
...
[2026-02-04 01:17:XX] [INFO] Found X unique envelopes to process
...
[2026-02-04 01:17:XX] [INFO] HunterV2 Cycle END - Success
```

### 7.2 Multi-Process Management
When running with complex elevation or debug hooks, multiple `python` processes may appear. The verified diagnostic for identifying the primary automation engine is:
`Get-Process python | Select-Object Id, ProcessName, MainWindowTitle`
- **Primary Process**: `MainWindowTitle` == `"PCP Nexus | Document Automation"`
- **Auxiliary Processes**: No `MainWindowTitle` (background workers/interpreters).

### 7.3 Post-Patch Production Samples (Verified Feb 4, 01:20)
The following jobs were verified as successfully archived and indexed in the `3rd Party Audit Mirror` following the fix deployment:

| Job # | Case # | Lead Doc | Outcome |
|---|---|---|---|
| **A25A05528** | 1263179 | AX07A25A05528.pdf | ARCHIVED / Filing Accepted |
| **A26101449** | 1267577 | AX07A26101449.PDF | ARCHIVED / Filing Accepted |
| **A25A06432** | 2025-009076-2 | AX07A25A06432.pdf | ARCHIVED / Filing Accepted |
| **A25B02871** | 2025-009764-2 | AX07A25B02871.pdf | ARCHIVED / Filing Accepted |
| **A25A05515** | 202579316 | AX07A25A05515-MOTION.pdf | ARCHIVED / Filing Accepted |
| **A25C01812** | 202588108 | AX07A25C01812.PDF | ARCHIVED / Filing Accepted |
| **A25C01833** | 2025DCV5441 | AX07A25C01833.pdf | ARCHIVED / Filing Accepted |

### 7.4 Intelligence Verification: Comment Extraction (Feb 4)
A diagnostic scan (`verify_comments_diag.py`) was performed to confirm that "Accepted Comments" were correctly indexed in the database for the post-patch run.
- **Verification Method**: SQL query mapping `id`, `filename`, and `raw_comments` for the pilot batch.
- **Result Index**:
    - **Job A25C07768**: Logged as "Filing Type EFile" (System Default).
    - **Job A25C01833**: Logged as "THANK YOU FOR E-FILING/ EROMERO" (Clerk Note).
    - **Bulk Phase 1 (Job A25A...)**: All verified as successfully capturing the "EFile" default indicator.
- **Conclusion**: The regex-based extraction from the notification body is correctly identifying and persisting clerk comments.

- **Verification**: Verified that state persistence via Outlook Categories is functioning as designed. To re-process, the `PCP-Processed` category must be manually removed from the target emails.

### 7.6 Incident: Missing Real-time Exports (Feb 4, 12:15)
After implementing the `RealtimeExporter` for 8-column CSV and 14-column Excel formats, an initial verification indicated that no files were being generated in the `Output` folder.
- **Diagnosis**: 
    1.  Checked `nexus.db` state: `SELECT status, COUNT(*) FROM jobs GROUP BY status`
    2.  Result: `ARCHIVED: 20`
    3.  Checked logic: `job_manager.py` calls `exporter.export_job` during the `update_job_status` transition.
- **Root Cause**: All 20 jobs in the database were already in the final `ARCHIVED` state from a previous run. Since no status transitions were occurring for these jobs, the RealtimeExporter was not triggered.
- **Verification**: Confirmed that the "missing" exports were not a functional bug, but a result of a stale session where all pending work was already complete. **Lesson**: For export verification on a "Clean Slate", ensure the DB is cleared or new unique emails are present in the Inbox.

### 7.7 Analysis: Array index out of bounds (Feb 4, 12:10)
A critical error was observed in the `Intake.log`: `HunterV2 Critical Error: (-2147352567, 'Exception occurred.', (4096, 'Microsoft Outlook', 'Array index out of bounds.', None, 0, -2147352567), None)`
- **Discovery**: Occurred during high-volume scanning of mixed Inbox items.
- **Technical Breakdown**: This typically occurs when the agent maintains a reference to a COM collection (like `Items`) but an item is removed from that collection (e.g., by an Outlook rule, manual move, or deletion) while the agent is still iterating by index.
- **Resilience**: The engine’s error handling correctly caught the exception, logged the HRESULT, and safely terminated the current cycle to prevent a hard crash, allowing for a retry in the next interval.

