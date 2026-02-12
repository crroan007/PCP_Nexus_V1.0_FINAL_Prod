# PCP Nexus: Operations Manual

This document provides a consolidated reference for the operational, boarding, and maintenance procedures for the PCP Nexus platform.

---

## 1. Project Handover & Onboarding Guide

### 1.1 Key Knowledge Areas
- **Phase 1**: Focuses on renaming single-document affidavits based on prefix transformations (e.g., AX02 -> AX42).
- **Phase 2**: Focuses on multi-document aggregation (Petition + Exhibits) using a 20-minute smart-wait window. Merged files are prioritized so the Petition (AX40) is Page 1.
- **System Architecture**: Python 3.11, CustomTkinter (GUI), EasyOCR (Validation), win32com (Outlook integration).
- **Persistence**: `nexus.db` (SQLite) tracks the state of every processed envelope.

### 1.2 Onboarding Checklist
1. **Resource Review**: Review the [System Documentation Overview](../overview.md) and the [Logic & Policy Manual](../governance/policy_and_logic_manual.md).
2. **Environment Setup**: Set up a Python 3.11 virtual environment and install dependencies via `pip install -r requirements.txt`.
3. **Local Testing**: Run the app via `python main.py` or use test injection scripts.

### 1.3 Key File Locations
- **Source**: `.../PCP_LEAN_DEV_TRANSFER/Source/Orchestrator`
- **Output**: Configurable in UI (defaults to Documents or ProgramData).
- **Primary Data Root**: `C:\ProgramData\PCP-Automation` (Authoritative for all runtime data).
- **Logs**: `C:\ProgramData\PCP-Automation\Logs` (See Section 5 for resolution logic).
- **Note**: Paths defined in `config.json` (e.g., `paths.logs`) are currently ignored by the engine in favor of the `app_paths.py` priority logic.

---

## 2. SOP Videos and Training Materials

Access to current SOPs is critical for maintaining alignment between automation logic and human business rules.

### 2.1 Training Resources
- **SOP: AX40 and Split Petition**: [Loom (30e9e7e836a74e13a9348135373728d6)](https://www.loom.com/share/30e9e7e836a74e13a9348135373728d6).
- **Training Root**: `C:\Homebrew Apps\Professional Civil Process - PCP - three project\Videos and Transcripts of SOP`.
- **Transcripts**: Linked in the project root as `Link to video.docx`.

---

## 3. Source Management & Golden Copy Strategy

The system uses a **"Golden Copy"** strategy to ensure that the entire development environment is preserved at critical project milestones.

### 3.1 Golden Copy "Save Point" Philosophy
A Golden Copy save point captures:
- **Full Source Tree**: The exact state of `.py` and `.ps1` files.
- **Compiled Binaries**: All `.pyd` (Cython) and `.exe` (PyInstaller) artifacts.
- **Development Assets**: Non-committed trial data, manual logs, and prototypes.

### 3.2 Backup Execution (Robocopy)
To ensure a complete, unpruned copy, `robocopy` is the preferred tool:
```powershell
robocopy "c:\Homebrew Apps\Professional Civil Process - PCP - three project" `
         "c:\Homebrew Apps\_PROJECT_SAVES\PCP_FULL_BACKUP_YYYYMMDD" `
         /E /R:3 /W:5
```
- **/E**: Copies subdirectories, including empty ones.
- **/R:3 /W:5**: Retries 3 times with a 5-second wait if a file is locked (critical for active SQLite or Log files).

### 3.3 Troubleshooting Database Locks
The SQLite database (`nexus.db`) is often locked while the PCP Nexus application is running. 
- **The "ReadOnly" Error**: If you attempt to modify the database via CLI (e.g., `sqlite3.OperationalError: attempt to write a readonly database`), you must **Close the application** first.
- **Verification**: Ensure no `python.exe` processes associated with the app are running before executing cleanup scripts or manual database edits.


---

## 4. Post-Processing Verification

### 4.1 Checking Success
- **Email Location**: Once processed, emails are moved from the **Inbox** to a sub-folder named **`3- AI Completed`**.
- **Sync Visibility**: If items appear "stuck" in the Inbox but logs show success:
    - Verify they are present in the `3- AI Completed` folder.
    - Press **F9 (Send/Receive)** in Outlook Classic to force a view refresh.
- **Output Validation**: Check the Documents folder for PDFs matching the pattern `AX40*.pdf`.
- **Audit Reports**: Audit logs are generated with different levels of reliability:
    - **SharePoint Mirror (Primary / High Reliability)**: `C:\ProgramData\PCP-Automation\Logs\SharePoint_Mirror\PCP_Log_{NodeID}_{YYYY-MM-DD}.csv`. **Note**: This is the authoritative source for Phase 2 sequential processing status.
    - **Local Legacy (Unreliable)**: `eaffidavits_accepted_MMDDYYYY.csv` in the configured output directory. This file may not be generated if the engine is running in "Sequential/Phase 2" mode exclusively.
    - **Excel Portals**: No static Excel files are created; audit data is typically visualized via the live Dashboard or through the SharePoint Mirror CSV export.
- **Audit Data Schema**: The SharePoint Mirror log contains rich metadata including `Envelope_ID`, `Constituent_Docs`, `Lead_Doc`, `Original_Prefix`, `Target_Prefix`, `Action_Flag`, and `Matched_Phrases`.
- **Log Verification**: Confirm "[SUCCESS] Envelope ... COMPLETE" exists in `Intake.log`.

### 4.3 File Identification Nuance (Phase 2)
In Phase 2 sequential processing, the final PDF filename (e.g., `AX40103279377.pdf`) uses the **Tyler Envelope ID** rather than the **PCP Job Number** (e.g., `A25505826`).
- **Standard**: This is intended behavior for aggregate filings.
- **Operator Action**: If searching for a specific Job ID (AX09...), refer to the **SharePoint Mirror Log** or the **Dashboard** to find the corresponding `AX40` Envelope file. 
- **Alert**: As of Feb 4, several Phase 1 docs (AX02, AX03, AX07, AX09) are currently being incorrectly named as `AX40` due to a configuration mapping bug. Use the Job # column in the Dashboard to find the correct file.

### 4.4 Outlook Categories & State Management

The application uses Outlook Categories to track the processing state of each email directly within the MAPI store. This is the primary mechanism for preventing duplicate processing.

- **`PCP-Processed`**: Applied once the documents have been successfully archived. The engine will skip any email with this tag.
- **`PCP-Packetized`**: Used in Phase 2 to group multiple emails belonging to the same Envelope ID.
- **`PCP-Packetized-Priority`**: Indicates an e-filing packet containing high-priority documents (e.g., Petitions).
- **Troubleshooting "Stalled" Processing**: If the logs report `Found 0 unique envelopes` but the Inbox appears full, check if the emails are tagged with these categories. 
- **The "Work Finished" Signature**:
  ```text
  Intake: Found 0 unique envelopes to process sequentially
  Intake: DEBUG LOOP [1]: Subj='...' Cats='PCP-Processed'
  ```
  If you see the above in the logs, the engine is successfully identifying that the items in the folder have already been handled. This is **not** a stall; it is evidence of successful deduplication.
- **Manual Reprocessing (Category Reset)**: To force the engine to re-process an email (e.g., for testing), you must **remove the `PCP-Processed` category** from the email in Outlook and ensure its hash is not already in the database (or clear the database).

### 4.5 Real-time Activity Logs (CSV/Excel)
As of Feb 10, 2026, the system generates **phase-specific** real-time activity CSVs in the **Output Folder**.
- **File Pattern**: `pcp_phase1_YYYYMMDD.csv` (Phase 1, on ARCHIVED) and `pcp_phase2_YYYYMMDD.csv` (Phase 2, on FILED), plus `pcp_activity_YYYYMMDD.xlsx` (full 14-column audit).
- **Rotation Lifecycle**: CSVs are rotated on schedule (Phase 1 daily at 10 PM, Phase 2 hourly) via **move + reset**: the local file is moved to the network share, then reset with blank headers. Existing files on the share are archived with timestamps.
- **Differentiated Formats**: 
    - **CSV (8 Columns)**: Optimized for external imports; contains `Envelope_Num`, `Case_Num`, `Date/Time Submitted`, `Date/Time Accepted`, `Lead_Document`, and `PCP_Job_Num`.
    - **Excel (14 Columns)**: Full internal audit file; adds `Orig_Prefix`, `New_Prefix`, `Status`, `Outcome`, `Next_Steps`, and `Comments`.
- **Function**: Unlike on-demand daily reports, these files are appended to **in real-time** as each job completes.
- **Auditing**: This is the most reliable way to monitor system throughput and confirm that specific Envelope IDs or Case Numbers have been processed without waiting for a daily summary.
- **Dashboard CSV Tabs**: The dashboard includes dedicated **Phase 1 CSV** and **Phase 2 CSV** tabs that query the database directly for always-current data (independent of the polling CSV rotation state).
- **Comment Tracking**: Activity logs now include specialized columns for **Has_Comments (Yes/No)** and the **Comments** text itself, allowing for rapid auditing of clerk notes and system defaults.
- **Enhanced Visibility**: Filenames in the Dashboard's activity log are **clickable links** (`file://`), allowing operators to open documents instantly for manual verification.


### 4.2 Visual Artifacts & Behavior
- **PowerShell Windows (SUPPRESSED)**: As of the Feb 4, 2026 build, PowerShell windows previously visible during "Native Bypass" downloads have been suppressed. Document ingestion now occurs silently in the background.
- **Startup Latency**: The application may take 5-10 seconds to initialize the AI engine (EasyOCR/MAPI) on startup. This is normal.

---

## 5. Log & Data Redirection Logic

As of Feb 4, 2026, the application uses a centralized path resolution utility (`app_paths.py`) to ensure data persistence across different installation environments.

### 5.1 Directory Resolution Priority
The application determines the `base_dir` for logs, database, and staging using the following order of precedence:
1.  **Environment Variable**: `PCP_DATA_DIR` (if set, this overrides the root directory).
2.  **Environment Variable**: `PCP_LOGS_DIR` (if set, this specifically overrides the **Logs** directory).
3.  **System-Wide (Admin)**: `C:\ProgramData\PCP-Automation` (Primary location for automation services).
4.  **User-Specific (Standard)**: `%LOCALAPPDATA%\PCP-Automation`.
5.  **Fallback**: `%USERPROFILE%\PCP-Automation`.

### 5.2 Custom Log Locations ("Homebrew" Paths)
Users may expect logs to appear in a custom source directory (e.g., `C:\Homebrew Apps\PCP New\Logs`).
- **Default Behavior**: Logs are **not** created there in real-time by the internal engine.
- **Solution**: To force the engine to use a specific directory for logging, set the **`PCP_LOGS_DIR`** environment variable to the desired path before launching the application.

### 5.3 Config Path Support (Feb 2026)
As of February 2026, the engine now honors `"paths.logs"` or `"LogFolder"` keys in `config.json` by setting the `PCP_LOGS_DIR` environment variable during the startup sequence in `main.py`. This ensures that user-configured log paths are used correctly by the internal file handlers.

---

## 6. Maintenance & Troubleshooting Utilities

### 6.1 Category Reset Utility (`reset_categories.py`)
To re-process emails for testing without manually editing each one in Outlook, use the following automation script:

```python
import win32com.client
import pythoncom

def reset_categories():
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6) # 6 = Inbox
        
        print(f"Scanning {inbox.Name} for tags to reset...")
        items = inbox.Items
        count = 0
        
        # Sort by received time descending
        items.Sort("[ReceivedTime]", True)
        
        for i in range(1, min(100, items.Count) + 1):
            m = items.Item(i)
            cats = m.Categories or ""
            if "PCP-Processed" in cats or "PCP-Packetized" in cats:
                new_cats = cats.replace("PCP-Processed", "").replace("PCP-Packetized", "").strip("; ")
                m.Categories = new_cats
                m.Save()
                print(f"Reset: {m.Subject[:50]}")
                count += 1
        print(f"Finished. Reset {count} emails.")
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    reset_categories()
```

### 6.2 Force Clearing the Database (Elevated)
If the database cannot be deleted or modified due to permissions or locks:
1. **Kill Python Instances**:
   `Get-Process python | Stop-Process -Force`
2. **Elevated SQLite Utility**:
   Instead of complex inline PowerShell strings (which often trigger parser errors due to nesting), use a dedicated utility script:
   
   **`clear_db_utility.py`**:
   ```python
   import sqlite3
   DB_PATH = r'C:\ProgramData\PCP-Automation\data\nexus.db'
   def clear_database():
       conn = sqlite3.connect(DB_PATH)
       cursor = conn.cursor()
       cursor.execute("DELETE FROM jobs")
       conn.commit()
       print("Database 'jobs' table cleared successfully.")
       conn.close()
   if __name__ == "__main__":
       clear_database()
   ```
3. **Execution**:
   Launch the utility with elevated privileges via PowerShell:
   ```powershell
   Start-Process 'python.exe' -ArgumentList 'clear_db_utility.py' -Verb RunAs -Wait
   ```
   *Note: This pattern bypasses SQL 'readonly' errors caused by file system permissions or lingering process locks.*

### 6.3 Diagnostic: checking existing categories
To verify which emails have tags without opening Outlook:
```python
import win32com.client
outlook = win32com.client.Dispatch("Outlook.Application")
inbox = outlook.GetNamespace("MAPI").GetDefaultFolder(6)
for msg in list(inbox.Items)[:20]:
    print(f"Subj: {msg.Subject} | Cats: {msg.Categories}")
```

### 6.4 Diagnostic: Database Comment Verification (`verify_comments_diag.py`)
If the Dashboard or Activity Logs report "None" for comments but you believe the email intake should have captured text, use this utility to query the raw database storage:

```python
import sqlite3
import json
import os

DB_PATH = r'C:\ProgramData\PCP-Automation\data\nexus.db'

def verify_jobs(ids):
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Query for specific filenames or job numbers
    query = f"SELECT id, filename, status, raw_comments, metadata FROM jobs WHERE " + " OR ".join([f"filename LIKE '%{i}%'" for i in ids])
    
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        
        print(f"{'ID':<10} | {'Filename':<30} | {'Status':<10} | {'Comments'}")
        print("-" * 80)
        
        for row in rows:
            jid, fname, status, raw, meta_json = row
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except:
                meta = {}
            
            # Extract from either the direct raw_comments field or the metadata blob
            comments = meta.get('accepted_comments', raw or 'N/A')
            print(f"{jid:<10} | {fname[:30]:<30} | {status:<10} | {comments}")
            
    except Exception as e:
        print(f"Error executing query: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    # Add Job Numbers or filenames to test here
    test_ids = ["A25A05528", "A26101449", "A25C01833"]
    verify_jobs(test_ids)
```
- **Validation**: If this script returns text (e.g., "THANK YOU FOR E-FILING"), it confirms the INTAKE service is working correctly. If the Dashboard still shows "None", the issue lies in the HTML report generator or the `RealtimeExporter` mapping logic.
### 6.5 Procedure: Full System Cleanup ("Gold Run" Prep)
To prepare the environment for a final end-to-end verification test (a "Gold Run"), follow this sequence to ensure a completely clean state:

1. **Stop Active Processes**:
   ```powershell
   Get-Process python | Stop-Process -Force
   ```
2. **Clear Application Files**:
   - Delete all real-time exports (`pcp_phase1_*`, `pcp_phase2_*`, `pcp_activity_*`) from the **Output Folder**.
   - Delete the current dashboard (`dashboard.html`) from `C:\ProgramData\PCP-Automation\Dashboard\`.
3. **Clear Database**:
   - Use the Elevated SQLite Utility (Section 6.2) to clear the `jobs` table.
4. **Reset Outlook Categories**:
   - Run `reset_categories.py` (Section 6.1) to remove the `PCP-Processed` tag from inbox emails.
5. **Verify Inbox**:
   - Ensure target emails are in the **Inbox** (not subfolders).
6. **Launch with Elevation**:
   - Launch `main.py` using **Run as Administrator**. This ensures the engine has the necessary permissions to write logs and connect to Outlook via COM.

### 6.6 Troubleshooting: Mapped Drive Visibility (Admin vs. User)
During the migration to external drives (e.g., `E: PCP drive`), scripts may report `DriveNotFound` or `Cannot find drive`. This is a known Windows security behavior where mapped drives created in a **Standard User** session are not visible to **Elevated (Administrator)** processes.

- **Symptom**: `Get-ChildItem : Cannot find drive. A drive with the name 'E' does not exist.`
- **Root Cause**: Windows maintains separate drive letter mappings for each login session and integrity level.
- **Resolution**:
  1. **Remap as Admin**: Open an elevated PowerShell prompt and manually map the drive:
     ```powershell
     net use E: \\Server\Share
     ```
  2. **Direct UNC Paths**: Use the full network path (e.g., `\\192.168.1.100\PCP`) instead of the mapped letter.
  3. **EnableLinkedConnections**: (Registry Fix) Set `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\EnableLinkedConnections` to `1` (requires restart).
  4. **Manual Copy**: Use Windows Explorer to copy the files instead of using elevated scripts for file movement.
