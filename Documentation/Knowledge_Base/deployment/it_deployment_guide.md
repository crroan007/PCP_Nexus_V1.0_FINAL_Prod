# PCP Nexus - IT Deployment & Configuration Guide

## 1. Delivery Format & Source Protection
To ensure stability and protect Intellectual Property, the **PCP Nexus** application is delivered as a **Compiled Single-File Executable (`.exe`)**.
*   **Format**: Standalone OneFile Executable or Setup Installer.
*   **Source Code**: **Not Included**. The core application logic is compiled into C-extensions (Cython), and the entire package is bundled using PyInstaller into a single binary. This prevents source-code inspection and simplifies deployment to just one file.
*   **Modifications**: Technical configuration is performed via `config.json` (placed in the same directory as the `.exe`) or the Settings UI. Core logic is immutable.

## 2. Workstation Prerequisites
Before installation, ensure the target workstation meets the following criteria:

### Hardware Profile & Performance 
Based on empirical load testing (100 production email batch), the application is primarily **I/O Bound** (Disk Write + Outlook COM Latency).

| Metric | Observed Peak | Target Specification |
| :--- | :--- | :--- |
| **CPU** | **< 5%** | Quad-Core 2.0GHz+ (Intel i5/Ryzen 5) |
| **RAM** | **~900 MB** | 8 GB Recommended (4 GB Minimum) |
| **Disk** | Moderate | SSD strongly recommended for SQLite/I/O |
| **Throughput**| ~19-20 ppm | ~1,200 Files/Hour capacity |

### Software Dependencies
*   **OS**: Windows 10 or Windows 11 (64-bit).
*   **Microsoft Outlook**: Classic Desktop Version (2016, 2019, 2021, or 365). *New "Outlook for Windows" (PWA) is NOT supported.*
*   **Microsoft Edge WebView2 Runtime**: Required for the user interface. (Standard on Windows 11).
*   **Visual C++ Redistributable 2015-2022 (x64)**: Required for the internal engine runtime.

### User Privileges
The User Account running the application requires:
*   **Read/Write Access**: To the Application Directory (to write logs and database updates).
*   **Read/Write Access**: To the configured `Output` (Test Results), `Exceptions`, and `Archive` network shares.
*   **Local Execution**: Ability to run executables from the chosen installation path.

## 3. Security & Antivirus Configuration
The application uses automated hooks into Microsoft Outlook and high-frequency File System operations, which can trigger aggressive Heuristic Scans or false-positive blocks.

### Antivirus / EDR Whitelisting
**Action**: Add an Exclusion for the Application Folder (e.g., `C:\Program Files\PCP Nexus` or `C:\Apps\PCP Nexus`).
*   **Reason**: Prevents "File In Use" errors when the engine rapidly moves PDFs or updates status logs.
*   **Process**: Exclude `PCP_Nexus.exe` (or `main.exe`) and the associated application directory.

### Outlook "Programmatic Access" Security
The application uses MAPI/COM to read and move emails. Outlook may block this by default or show security prompts.
**Action**:
1.  Open **Outlook Trust Center** -> **Programmatic Access**.
2.  Set to: *"Warn me about suspicious activity when my antivirus software is inactive or out-of-date"* (Recommended).
3.  **Enterprise Policy**: Ensure GPO does not strictly *block* programmatic access to the Outlook Object Model.

## 4. Configuration (Post-Install)
The application expects a `config.json` file in the root directory.
*   **First Run**: The app will generate a default config if missing.
*   **Key Paths**:
    - `paths.output`: Point this to the mapped network drive for processing results.
    - `outlook_account`: The exact name of the mailbox as it appears in the Outlook navigation pane.

## 5. Deployment Steps
1.  **Extract/Install** the provided package to the target machine.
2.  **Verify Outlook** is open and the target account is signed in.
3.  **Launch `PCP_Nexus.exe`**.
4.  **Confirm Readiness**: Check the "System Status" indicator on the dashboard to ensure MAPI and Database connections are successful.

## 6. Troubleshooting & Diagnostics

In scenarios where the automation appears idle despite an active email backlog ("Silent Engine"), follow these diagnostic checks:

1.  **Mailbox Verification**: Confirm the `outlook_account` and `outlook_folder` in `config.json` match the exact labels in the Outlook UI.
2.  **MAPI Liveness**: Check `Logs/Intake.log`. If the file size is not changing, the Hunter session is stalled or blocked by an active Outlook security prompt.
3.  **Process Isolation**: If the app fails to launch or "Start Engine" does nothing, verify that no orphaned `PCP_Nexus.exe` processes are holding the database singleton mutex. 
5.  **Forensic Log Dumps**: Inspect `Logs/debug_hunter.log` to reveal exact document rejection reasons (e.g., "Metadata missing Case Number").
6.  **Encoding Nuance (UTF-16 Diagnostics)**: Automated audit logs or redirects (`>`) in some Windows shells may be written in **UTF-16le**. If standard viewing tools (like `view_file` or some text editors) fail with "unsupported mime type" or show empty content, use the following PowerShell-safe one-liner to inspect the file cleanly:
    - `python -c "print(open('your_file.txt', 'r', encoding='utf-16').read())"`
7. **Force Restart Pattern (Pick up Changes)**: If updates to configuration or source code are not appearing in the running application, or if the COM session appears "Zombie", use the following command to force-clear current state and restart:
    - `taskkill /F /IM python.exe /T 2>$null; Remove-Item "hunter_heartbeat.txt" -Force -ErrorAction SilentlyContinue; .\run_app.bat`
8. **Real-Time Database Health Check**: To verify ingestion and job creation counts without the UI:
    - `python -c "import sqlite3; conn=sqlite3.connect('Executive/Orchestrator/data/nexus.db'); c=conn.cursor(); c.execute('SELECT COUNT(*) FROM pending_packets'); print(f'Pending: {c.fetchone()[0]}'); c.execute('SELECT COUNT(*) FROM jobs'); print(f'Jobs: {c.fetchone()[0]}')"`
9. **Heartbeat Diagnostics**: To confirm if the agent thread is actually cycling (vs waiting for user activation):
    - `Get-Content hunter_heartbeat.txt -Tail 10`
    - **Healthy**: Continuous `Cycle Start` entries.
    - **Granular Hang (Phase Heartbeat)**: Look for `Phase 1 START` vs `Phase 1 END`. If END is missing, the engine is hanging during ingestion (e.g., large folder scan).
    - If the heartbeat is stagnant, ensure the user has clicked **"ACTIVATE SYSTEM"** in the Dashboard.
10. **Dashboard vs Database Skew**: The Dashboard UI tracks the `jobs` table. 
    - **In Sequential Model**: Progress reflects in real-time. As each envelope completes, the "Action Items" count increases. 
    - **In Legacy Batch Mode**: A screen showing **0 Action Items** may hide hundreds of hidden `pending_packets` awaiting the 20-minute aggregation window.
    - **Download Latency**: During large backlogs (e.g., 575 emails), a stall at "0" for several minutes is normal while the `LinkDownloader` sequentially acquires PDFs before the first envelope is finalized. Use **Side-Channel Metrics** (Physical files appearing in `Staging/`) to verify health.
11. **Process Elevation & UAC Suppression**:
    - **Requirement**: The application must often be launched as **Administrator** to interact with restricted `ProgramData` folders and certain Outlook MAPI configurations.
    - **Match Integrity Levels**: Critical: Both the application and Microsoft Outlook must run at the same privilege level. If the app is Admin and Outlook is Standard (or vice versa), the MAPI connection will fail with a `Server execution failed` error.
    - **Automation Nuance**: When launching via scripts (e.g., `Start-Process -Verb RunAs`), if the environment is non-interactive or lacks a shell, the **UAC prompt may be suppressed or hidden**, causing the launch to fail silently. In these cases, use the "Compatibility" tab on the `.exe` to "Run this program as an administrator" persistently.


 ## 7. Code Persistence & Shortcut Integrity
 
 Unlike packaged applications where code is immutable in the installation directory, the **PCP Nexus** development environment utilizes direct source-file modification.
 - **Shortcut Behavior**: Any Windows Desktop shortcut (`.lnk`) pointing to `run_app.bat` or the Python entry point will automatically reflect the most recent architectural changes (e.g., the move to Sequential Processing) upon the next execution.
 - **Version Verification**: To confirm the active version, inspect the dashboard logs immediately after launch. The "Mega-Ralph Mode" or specific "Ingestion Type" identifiers in the logs verify that the latest patches are loaded.
 - **Automatic Refresh**: There is no requirement to manually re-create shortcuts or clear local caches after a logic update, provided the execution path remains consistent.
