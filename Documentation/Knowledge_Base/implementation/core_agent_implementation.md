# PCP Nexus: Core Technical & Implementation Guide

This document provides a consolidated technical reference for the architecture, path management, threading models, and diagnostic utilities of the PCP Nexus platform.

---

## 1. Core Architecture (Sovereign Agents)

The system is built on a **Sovereign Agent** pattern, where autonomous agents manage specific stages of the document lifecycle.

### 1.1 Agent Definitions
- **Hunter (Ingestion)**: Scans Outlook for filings. Supports `affidavit` (Phase 1) and `efiling` (Phase 2 - sequential) modes.
- **Librarian (Discovery)**: Builds a reverse-index of Case IDs and Job Numbers from the filesystem.
- **Auditor (Intelligence)**: Performs 3-layer scanning (Text -> OCR -> Deep OCR). **Parallelism**: Runs in 2 concurrent worker threads to handle OCR load.
- **Clerk (Filing)**: Renames and moves documents to production folders. **Parallelism**: Runs in 2 concurrent worker threads.

### 1.2 Orchestrator Engine Parallelism
The `OrchestratorEngine` manages a fleet of 6 core threads to ensure high throughput:
- `HunterThread` (1): Scans Outlook every 2-5 seconds.
- `AuditorThread-1` & `AuditorThread-2` (2): Consumes `NEW` jobs for OCR validation.
- `ClerkThread-1` & `ClerkThread-2` (2): Consumes `VERIFIED` jobs for archiving.
- `ReporterThread` (1): Generates `dashboard.html` and daily/weekly email reports.

### 1.2 MAPI & OS Transport Patterns
- **"Write-Run-Delete" PowerShell Transport**: Bypasses TLS fingerprinting for PDF downloads by using native `Invoke-WebRequest`.
- **COM Threading**: Strict adherence to `pythoncom.CoInitialize()` and `CoUninitialize()` in agent threads.
- **Reverse Iteration**: Use reverse loops when moving/deleting Outlook items to preserve index integrity.

---

## 2. Unified Path Management (`app_paths.py`)

The application dynamically resolves writable directories to ensure reliability across admin and non-admin installations.

### 2.1 Directory Hierarchy
1. **ENV Override**: `PCP_DATA_DIR` (if set).
2. **ProgramData**: `C:\ProgramData\PCP-Automation` (Standard).
3. **LocalAppData**: `%LOCALAPPDATA%\PCP-Automation` (Fallback for non-admin).
4. **User Profile**: `%USERPROFILE%\.pcp-nexus` (Legacy/Last resort).

### 2.2 Output Path Auto-Recovery
If a configured output path is not writable (e.g., ghost config from another machine):
1. Log a warning.
2. Fall back to **Documents\PCP_Output\[Civil|Criminal]**.
3. **Auto-Repair**: Update `config.json` with the newly validated path.

### 2.3 Configuration Decoupling & Log Redirection
Note: The `app_paths.py` utility is decoupled from `SecureConfig` to resolve path circularity. 
- **The Conflict**: `SecureConfig` needs `app_paths` to find `config.json`, so `app_paths` cannot depend on `config.json` for base paths.
- **The Solution (Feb 2026)**: In `main.py`, the engine reads potential log paths from multiple configuration locations (`paths.logs`, `LogFolder`, and KVI store) upon startup and sets an environment variable **`PCP_LOGS_DIR`**.
- **Implementation**:
  ```python
  # main.py
  from core.secure_config import conf
  log_overrides = [
      conf.get("paths.logs"),
      conf.get("LogFolder"),
      conf.get_kvi("LogFolder")
  ]
  for log_path in log_overrides:
      if log_path and os.path.isdir(os.path.dirname(log_path)):
          os.environ["PCP_LOGS_DIR"] = log_path
          break

  # app_paths.py
  def logs_dir() -> Path:
      override = os.environ.get("PCP_LOGS_DIR")
      if override: 
          return ensure_dir(Path(override))
      return ensure_dir(base_dir() / "Logs")
  ```
- **Benefit**: This allows the UI-configured log path to be honored by the engine despite the technical decoupling, ensuring logs appear in the user-specified directory (e.g., `C:\Homebrew Apps\PCP New\Logs`).


---

## 3. Standardized Agent Logging (`BaseAgent`)

Every agent (Hunter, Auditor, Clerk) inherits from `BaseAgent`, which centralizes the logging lifecycle.

### 3.1 Initialization
- **Path Resolution**: The logger uses `app_paths.logs_dir()`, which defaults to `C:\ProgramData\PCP-Automation\Logs`.
- **File Handler**: Each agent gets its own log file (e.g., `Intake.log` for Hunter, `Auditor.log`, etc.) using a UTF-8 encoded `FileHandler`.
- **UI Integration**: Logs are simultaneously dispatched to a `ui_callback` to populate the real-time console in the Dashboard.

### 3.2 Thread-Safe Logging
Agents use a shared logging instance but ensure that high-volume writes do not block the 6-thread execution loop.

## 4. UI Threading & COM Models

### 4.1 UI Freezing Resolution
All heavy operations or COM interactions must be offloaded from the main thread.
- **COM Initialization**: `pythoncom.CoInitialize()` must be called at the start of every background thread using COM.
- **UI State updates**: Use `root.after(0, callback)` to safely update TKinter widgets from background threads.
- **Button Debouncing**: Disable buttons (`state="disabled"`) during async operations (e.g., "Test Connection").

### 4.2 Console Drain Optimization
To prevent UI lag during high-volume logging, use a **Bounded Drain** pattern:
- Process max 200 lines per tick.
- Trim `insert("end", ...)` content once it exceeds 3000 lines to prevent memory bloat.

---

## 5. Frozen Application (PyInstaller) Patterns

### 5.1 Resource Resolution
Use `sys._MEIPASS` when `IS_FROZEN` is True to locate icons, templates, and other bundled assets.

### 5.2 Startup Diagnostics
When `console=False` in PyInstaller:
1. **Redirection**: `sys.stdout` and `sys.stderr` are redirected to `%LOCALAPPDATA%/PCP-Automation/debug_logs/`.
2. **Exception Hook**: A global hook catches fatal errors and displays them in a GUI messagebox before termination.
3. **Log Check**: Verify `pythoncom` is present in the `_internal` folder for any "Module Not Found" issues.
4. **Log Rotation**: In frozen builds, logs are rotated daily with the pattern `startup_YYYYMMDD_HHMMSS.log` in `%ProgramData%\PCP-Automation\logs`.

### 5.3 Process Elevation & Monitoring
- **Run as Administrator**: Use the following PowerShell command to ensure the application starts with correct privileges to interact with Outlook and restricted data folders:
  ```powershell
  Start-Process -FilePath "path\to\venv\Scripts\python.exe" -ArgumentList "main.py" -Verb RunAs
  ```
  *Note: Matching integrity levels (both Admin/Admin or both User/User) is required for successful Outlook COM session acquisition.*
- **Log Tailing**: Monitors `Intake.log` and `Agent_Trace.log` in real-time to verify that the hunter is scanning the inbox and correctly identifying case IDs.

---

## 6. Deployment & Build Troubleshooting

### 6.1 Build Requirements
- **Complete Environment**: Always `pip install -r requirements.txt` in the targeted build venv.
- **Tcl/Tk Paths**: Ensure the `.spec` file points to the Python root (e.g., `Python311\tcl`) rather than a subdirectory.

### 6.2 Common Fixes
- **ModuleNotFoundError: pythoncom**: Ensure `pywin32` is installed in the current environment BEFORE running PyInstaller.
- **Output Directory Not Empty**: Run `Remove-Item -Recurse -Force build, dist` before starting a new build.

### 6.3 Post-Build Runtime Gaps
- **win32timezone**: Although part of `pywin32`, it must sometimes be explicitly imported in the main entry point (e.g., `main.py`) or listed separately in some build configurations to be included in the frozen binary. Its absence causes `Could not capture ReceivedTime` warnings in the Intake logs.

### 6.4 File Editing Troubleshooting (TargetContent Mismatch)
During development on some Python files (notably `hunter_v2.py`), the `replace_file_content` tool may fail to find target strings due to invisible formatting or mixed indentation (tabs vs. spaces) that standard viewers elide.
- **Mechanism**: Use PowerShell to verify exact source content.
- **Diagnostic Command**: `Get-Content "path/to/file.py" | Select-Object -Skip [Line-1] -First [Count] | Format-List`
- **Result**: This exposes the raw string including whitespace, enabling exact reconstruction of the `TargetContent` for the edit tool.

---

## 7. Database Standards

- **Primary Timestamp**: `created_at` (UTC).
- **Filtering**: Use `WHERE created_at >= date('now')`.
- **UTC Paradox**: All logs and DB entries use UTC. Account for the 5-8 hour offset during local debugging.

---

## 8. Outlook COM Connection Diagnostics

When the engine fails to connect to Outlook, check `agent_trace.log` for these specific HRESULT codes:

### 8.1 Common COM Errors
| Error Code | Meaning | Probable Cause | Symptom |
| :--- | :--- | :--- | :--- |
| `-2147221021` | **Operation unavailable** | Outlook is closed. | Engine "Waiting for user activation" indefinitely. |
| `-2146959355` | **Server execution failed** | **Integrity Level Mismatch**: App is Admin while Outlook is standard User (or vice versa). | **Stalled Queue**: 130+ emails in Inbox but zero processing logs/downloads. |
| `0x80080005` | **Server execution failed** | COM server cannot be started or accessed in the current context. Commonly occurs when launching as Admin while Outlook is user-owned. | Entire cycle aborts after trying 3 strategies. |
| `WinError 5` | **Access is denied** | **User Profile Restriction**: Admin app attempting to write to `C:\Users\<User>\Documents`. | "Access is denied" error in Intake log when saving files. |
| `-2147352567` | **Array index out of bounds** | **Outlook MAPI Context Error**: Attempting to access an index in a collection (e.g., `Items` or `Attachments`) that does not exist. | `HunterV2 Critical Error: Microsoft Outlook: Array index out of bounds.` Often occurs if an email is deleted or moved by another process (or Inbox Rule) while the agent is iterating. |

**Final Verification (Feb 4, 2026)**: The `-2146959355` error was definitively resolved by ensuring both the PCP Nexus application and Outlook Classic were running as the same user (in this case, both as Administrator).

### 8.2 Connection Strategy (Retry Logic)
The `JobManager` attempts three distinct strategies to acquire a MAPI session:
1. `GetActiveObject`: Connect to an already running instance.
2. `Dispatch`: Create a new instance if none are found.
3. `EnsureDispatch`: Force instantiation with specific typelib requirements.

**Note**: If all three fail, Ensure Outlook is open and running as the same user as the application. Both MUST have matching privilege levels (both Admin or both User). **Verified (Feb 4, 2026)**: Application successfully connected and processed emails immediately once both Outlook Classic and PCP Nexus were launched as Administrator.

### 8.3 Dashboard Availability Diagnostics
When the UI reports "Dashboard Not Available", verify the following:
1. **Path Resolution**: Check that the UI's "Open Dashboard" button matches the path returned by `app_paths.dashboard_report_path()`. (Standard: `%ProgramData%\PCP-Automation\Dashboard\dashboard.html`).
2. **First Run Latency**: The `ReporterThread` typically runs every 30-60 seconds. On a fresh installation, the file will not exist until the first cycle completes.
3. **Database Readiness**: If `nexus.db` is empty or the `jobs` table is missing, the generator returns `None` and skips file creation to prevent showing an empty template.
4. **Permissions**: Ensure the service has write access to the `Dashboard` folder within the app data base directory.

---

## 9. Known Issues & Bug Tracking

### 9.1 Resolved Issues (Feb 4, 2026)
- **Disruptive PowerShell Windows**: The "Native Bypass" download logic in `utils/link_downloader.py` previously invoked `subprocess.run` without window suppression flags.
    - *Investigation*: A global codebase audit was performed. `link_downloader.py` was the primary source.
    - *Resolution*: Applied `creationflags=subprocess.CREATE_NO_WINDOW` and `startupinfo` with `STARTF_USESHOWWINDOW`.
    - *Technical Note*: Standardized on `STARTF_USESHOWWINDOW`. Avoid `STARTFLAGS_USESHOWWINDOW` (found in some legacy snippets), as it triggers an `AttributeError` in modern Python `subprocess` modules on Windows.
- **Config-Mapping Mismatch (Naming Logic)**: An architectural mismatch existed between the code's expectation of a nested configuration (`Phases.Phase1.RenameMap`) and the actual flat `naming_rules` key in `config.json`.
    - *Resolution*: Updated `HunterV2` to check the root `naming_rules` first, then fall back to the nested map. This restored correct Phase 1 naming (Prefix+JobNum).
- **Audit Log Schema Alignment**: The real-time mirror log (SharePoint Mirror) was inconsistent with the database metadata extraction.
    - *Resolution*: Standardized the audit log to **30 columns**, integrating Case Number, Court, Case Style, and Accepted Comments. Verified the construction logic in `SharePointLogger._write_row` to ensure correct field mapping.
- **win32timezone Build Gap**: Captured as a build requirement to prevent audit logging warnings in frozen binaries.
- **Phases_conf & Variable Scope Shadowing**: Resolved `NameError` in `hunter_v2.py` where a loop variable (`metadata`) shadowed the function argument of the same name.
    - *Symptom*: When iterating through attachments in `_process_envelope_complete`, the loop `for msg, prefix, metadata in msg_data:` would overwrite the email-level `metadata` object. If the loop resulted in an empty set or a specific branch was taken later that expected the original object, a `NameError` or logic failure occurred.
    - *Resolution*: Renamed the function argument to `email_metadata` and ensured all downstream calls were updated.
- **Robust Job Extraction**: Improved prefix-stripping logic to handle overlapping filenames (e.g., `AX02A25...` → `A25...`).

### 9.2 Remaining Non-Blocker Bugs
- **Log Column Alignment**: Some legacy jobs may display as "No Logs" if their status was set manually via the database rather than through an agent's "update_job_status" call.

---

## 10. Phase 2 (e-Filing) Processing Logic

The `HunterV2` agent implements a sophisticated sequential processing model for complex filings.

### 10.1 Ingestion Flow
1. **Grouping**: Emails are grouped by `Envelope ID`.
2. **Link Download**: Documents are retrieved using a "Native Bypass" via PowerShell to handle secure Tyler Tech links.
3. **Smart Unfurling**: If the downloaded link returns an HTML "Landing Page" rather than a PDF (common in some secure portals), the `LinkDownloader` automatically scans the HTML for the actual `DownloadResource.ashx` endpoint and recursively retries the download to retrieve the binary artifact.
4. **Merging**: Multi-part filings are merged into a single PDF, ensuring the AX40 (Petition) is the first page if found.
4. **Renaming (Identification Strategy)**: 
    - **Pattern**: `AX40{EnvelopeID}.pdf`
    - **Nuance**: Unlike Phase 1, which preserves the original Job ID in the filename (e.g., `AX09A25...` -> `AX42A25...`), Phase 2 uses the **Envelope ID** as the primary filename identifier. 
    - **Validation**: To cross-reference an output PDF with its original Job Number, the operator must check the `PCP_Log` (SharePoint Mirror) or the live Dashboard, which maps these two identifiers.

### 10.2 Archiving & Transaction Safety
- **Target Folder**: `3- AI Completed` (Sub-folder of the source Inbox).
- **Atomic Move**: The agent follows a strict state-transition in the DB:
    - `PROCESSING` -> `MOVING` -> `ARCHIVED`.
- **Reconciliation**: If the move is interrupted, the job remains in `MOVING` state. The system reconciles these orphaned states upon application restart to prevent duplicate processing.
- **Folder Retrieval**: Uses `_ensure_folder` to create the destination folder on-demand within the MAPI store.

### 10.3 Link Expiration Fallback logic
The system includes a hardcoded fallback for links that have expired (>45 days). 
- **Search Path**: `D:\Homebrew Apps\PCP WORKING PHASE 1 BACKUP 012026\these`
- **Mechanism**: If a link download fails with `LinkExpiredError`, `HunterV2` automatically scans this local directory for pre-archived PDFs matching the expected filenames or job numbers.

### 10.4 Naming Discrepancy (Feb 4 Resolution)
The identified bug where Phase 1 documents were defaulting to `AX40{EnvelopeID}` has been resolved.
- **Root Cause**: Configuration key mismatch (`naming_rules` vs `RenameMap`).
- **Resolution**: Updated `HunterV2` to perform dual-schema config inspection and hardened prefix detection.

### 10.5 Robust Prefix & Job Extraction Logic
To ensure Phase 1 documents are never misidentified as Phase 2 Petitions, the following logic was implemented in `hunter_v2.py`:
- **Prefix Guard List**: A hardcoded list (`SOURCE_PFX`) including `AX02`, `AX03`, `AX07`, `AX09`, `BX09`, and their transformation targets is used to validate incoming document types.
- **Metadata Overrides**: If the attachment filename is non-standard (e.g., `A25B...pdf`), the system cross-references the Outlook folder metadata to recover the intended prefix.
- **Prefix Stripping**: When extracting the Job Number from a filename like `AX02A25C07678.PDF`, the system programmatically strips the known prefix to isolate the numeric PCP Job ID.

### 10.6 Transactional Auditing (SharePointLogger)
The `SharePointLogger` provides real-time CSV mirroring of database transactions.
- **Thread Safety**: Uses a `threading.Lock` to prevent file corruption during high-volume bursts from the 6-thread engine.
- **Excel Readiness**: Automatically generates `=HYPERLINK` formulas for source and output files, allowing immediate "one-click" access from auditing spreadsheets.
- **Completeness**: Captures **30 columns** of metadata (expanded Feb 2026), including:
    - **Legal Metadata**: Case Number, Court Name, and Case Style.
    - **Intelligence Flags**: Raw "Accepted Comments" and binary `Action_Flag` (Yes/No).
    - **Chain of Custody**: Original email subject and receiving timestamp.

### 10.7 Intelligence-Driven Extraction (HunterV2)
The `Hunter` agent now employs robust regex patterns to populate the expanded audit fields:
- `REGEX_COURT`: Captures jurisdictional court from the notification body.
- `REGEX_CASE_STYLE`: Extracts the "In The Matter Of..." style.
- `REGEX_COMMENTS`: Isolates the "Accepted Comments" block.
- **Portability**: Path resolution for `reporting_keywords.json` now uses `app_paths.py` instead of hardcoded absolute strings, ensuring the Intelligence Engine works across all deployment nodes.

### 10.8 Intake Filtering Logic (Deduplication)

The `Hunter` and `HunterV2` agents implement a robust filtering loop to prevent redundant processing:
1. **Category Filter**: `if PROCESSED_TAG not in m.Categories:` (where `PROCESSED_TAG` is `PCP-Processed`).
2. **Subject Exclusion**: Ignores self-generated reports (Daily/Weekly/Monthly).
3. **Database Guard**: Even if an email is not tagged, the agent performs a SHA-256 hash check against `nexus.db` to ensure the specific file content hasn't been archived previously under a different email.

### 10.9 Phase 2 Prefix Whitelist for Tyler Multi-Doc Pages (v4.3.2)
When a Tyler multi-document page lists files from multiple phases, only Phase 2 actionable prefixes are downloaded:
- **Whitelist:** `AX40`, `AXPB`, `AXPE`, `AXPM`, `AXPL`, `AXPA`
- **Skipped:** Phase 1 prefixes (`AX02`, `AX03`, `AX07`, `AX09`), unknown prefixes (`AX06`), and discarded prefixes (`AX69`, `AX81`, `CL`)
- **Implementation:** Check occurs in `_download_message_parts` MDR handler after the CL/AX69/AX81 discard scan. Any doc whose 4-character prefix is not in `self.phase2_prefixes` is skipped with an INFO log.
- **Rationale:** Prevents cross-phase contamination where Phase 1 affidavits or unknown document types are incorrectly merged into Phase 2 petition PDFs.

---

## 11. Clerk & Exception Management

### 11.1 Code 26 Handling
Per SOW 3.2, the Clerk agent monitors for `QA_FAILED` jobs. 
- **FilePro Simulation**: Captures the "Code 26" failure logic, simulating the entry of rejection metadata into the legal management system.
- **Physical Quarantine**: Moves documents that fail validation (e.g., mismatched Case Number) into a dedicated `Exceptions` folder within the production output tree.
- **Status Transition**: Updates the job to `EXCEPTION_PROCESSED` to prevent re-scanning while keeping the audit trail intact.

### 11.2 Archiving Renaming Rules
The Clerk applies dynamic prefix transformations (e.g., `AX02` -> `AX42`) based on the `naming_rules` configuration. If no rule matches, it preserves the original filename to ensure zero data loss.

---

## 12. Real-time Auditing & Reporting (Upcoming)

Following the stabilization of the core intake flow in early February 2026, the focus has shifted to real-time status visibility.

### 12.1 Reporter Service (Daily CSV Standardization)
The `Reporter` module translates database state into business-facing manifests. As of Feb 4, 2026, the Daily CSV format has been standardized to align with the Intelligence Engine's audit requirements.
- **Storage**: `eaffidavits_accepted_MMDDYYYY.csv` in the Output folder.
- **Standardized Columns (20 Total)**:
    - **Tyler Context**: `Envelope_Num`, `Case_Num`.
    - **Timestamps**: `Date_Submitted`, `Time_Submitted`, `Date_Accepted`, `Time_Accepted`.
    - **Processing Context**: `Lead_Document`, `PCP_Job_Num`, `Original_Filename`, `New_Filename`.
    - **Auditing (Prefixes)**: `Orig_Prefix`, `New_Prefix`.
    - **Auditing (Comments)**: `Has_Comments`, `Comments`.
    - **Lineage**: `Final_Path`, `Constituent_Docs`, `Merged_Link`.
    - **Performance**: `Email_Received`, `Email_Processed`, `Processing_Delta_Minutes`.
- **Distribution**: Emailed to stakeholders upon completion of the daily processing cycle.

### 12.2 Real-time Export Implementation (`RealtimeExporter`)
In Feb 2026, a dedicated real-time export engine was added to provide immediate visibility into every job completion.
- **Design**: Uses a singleton pattern (`exporter` in `core.realtime_exporter.py`).
- **Storage**: Appends to a daily CSV file (e.g., `pcp_activity_YYYYMMDD.csv`) **and** a native Excel file (`pcp_activity_YYYYMMDD.xlsx`) in the **Output Directory**.
- **Differentiated Formats**:
    - **CSV (Simplified - 8 columns)**: Optimized for external manifest imports. Contains: `Envelope_Num`, `Case_Num`, `Date_Submitted`, `Time_Submitted`, `Date_Accepted`, `Time_Accepted`, `Lead_Document`, `PCP_Job_Num`.
    - **Excel (Full Details - 14 columns)**: Comprehensive audit file including prefixes, state, outcome, and raw comments.
- **Distinction from SharePointLogger**:
    - **SharePointLogger**: Strict **30-column** schema mirrors full database metadata for deep auditing.
    - **RealtimeExporter**: Lightweight, specialized log focus on high-level state (ID, Filename, EnvelopeID, Case#, Status, Outcome, Prefix).
- **Trigger**: `JobManager.update_job_status` initiates an export immediately following the DB commit of any status change, ensuring the physical files are never "behind" the dashboard.
- **Technical Dependency**: Requires `openpyxl` for Excel generation. 
    - **Graceful Fallback**: If missing, the exporter logs a warning and proceeds with CSV-only mode.
- **Metadata Standardization**: Uses multi-key fallback logic to ensure consistency across different email notification formats:
    - **Envelope ID**: `metadata.get('envelope_num', metadata.get('envelope_id', '-'))`
    - **Lead Document**: `metadata.get('lead_doc', metadata.get('lead_document', metadata.get('subject', '-')))`
    - **Original Input**: Prefers `metadata.get('original_filename')`.
- **Hybrid Prefix Extraction**:
    - **Original Prefix**: First 4 characters of the `original_filename`.
    - **New Prefix**: Attempts regex match `r'^(AX\d{2})'` first; falls back to the first 4 characters of the final filename.
- **Table Columns**: `[ID, Timestamp, Filename, Envelope_ID, Case_Number, Lead_Doc, Orig_Input, Orig_Prefix, New_Prefix, Status, Outcome, Next_Steps, Has_Comments, Comments]`.
- **Comment Tracking**:
    - **Has_Comments**: A binary "Yes/No" flag indicating if the intelligence engine detected any text in the "Accepted Comments" field.
    - **Comments**: The raw text of the comment (clerk note or system default).

### 12.3 Verification & Monitoring (Feb 4 Monitoring)
To verify that real-time logging and exports are active:
1. **Check PCP_LOGS_DIR**: Ensure the environment variable is set during startup (see Section 2.3).
2. **Tail Active Logs**: Use `Get-Content "Intake.log" -Tail 20 -Wait` to monitor live email processing.
3. **Monitor Activity CSV**: Open the latest `pcp_activity_*.csv` file in the Output folder and verify that new rows appear instantly as emails are moved to the `3- AI Completed` folder.

### 12.4 In-Dashboard Export Mechanism
To supplement the physical CSV mirroring, the HTML Dashboard provides a client-side export hook:
- **Button**: "📥 Export CSV" (Activity Log section).
- **Functionality**: Uses JavaScript to parse the HTML table `<tbody>` and download the current state as a CSV.
- **Enhanced UX**: Includes clickable `file://` links for filenames, enabling instant document retrieval from the local filesystem or mapped network drives.
- **Reasoning**: Provides a "what I see is what I get" export that ensures the operator is reviewing exactly what is visible on the dashboard without needing to locate physical files in the Output directory.
