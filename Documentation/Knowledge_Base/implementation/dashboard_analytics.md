# Dashboard & Failure Analytics Implementation

The PCP Nexus system incorporates a multi-dimensional **Failure Analytics** suite designed for high-resolution monitoring during large-scale production runs (e.g., 400+ email load tests).

## 1. Data Fetching Model (`dashboard_generator.py`)

To support both legacy HTML reports and the native Flet UI, the `dashboard_generator` implements a tiered data fetching strategy using `output_mode='data'`.

### 1.1 Multi-Dimensional Aggregation
The generator performs Python-based aggregation across three dimensions: **Type**, **Stage**, and **Reason**. This provides a more granular view than a simple SQL `GROUP BY`, allowing for custom log parsing (e.g., extracting specific validation error substrings).

```python
# Failure Analytics (Detailed Aggregation)
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
    # Type (e.g., AFFIDAVITS, EFILING)
    st = row['service_type'] or "Unknown"
    fail_by_type[st] = fail_by_type.get(st, 0) + 1
    
    # Stage (Mapped to Lifecycle Names)
    stat = row['status']
    stage_name = get_stage_name(stat)
    fail_by_stage[stage_name] = fail_by_stage.get(stage_name, 0) + 1
    
    # Reason (Parsed from logs via helper)
    logs = row['logs'] or ""
    reason = parse_log_reason(logs)
    
    if len(reason) > 30: reason = reason[:27] + "..."
    fail_by_reason[reason] = fail_by_reason.get(reason, 0) + 1

failure_stats = {
    "by_type": fail_by_type,
    "by_stage": fail_by_stage,
    "by_reason": fail_by_reason
}
```

### 1.2 Regex Cleaning (Timestamp Sanitization)
To ensure charts are not polluted by ephemeral data, the parser applies regex to strip timestamps and environment tags:
*   **Pattern**: `\\[\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\]` (Strips `[2025-12-30 13:00:00]`).
*   **Pattern**: `^\\d{3,}-\\d{2}-\\d{2}.*?\\]` (Strips truncated timestamps like `025-12-30 13:20:49]`).
*   **Pattern**: `\\[.*?\\]` (Strips `[Orion]`, `[Hunter]`).

### 1.3 Legacy Log Mapping
For items where the structured `Reason:` protocol was not followed, the parser maps generic strings to actionable categories:
*   `"MANUAL_REVIEW using FAILED"` -> `"Audit Verification Failed"`.
*   `"File missing during archive"` -> `"System: File Missing (Archive)"`.

### 1.4 Output Structure
The returned dictionary includes a `failure_stats` key containing nested dictionaries for each dimension, ready for direct consumption by the `flet.BarChart` component.

## 2. UI Implementation (`ui/dashboard_window.py`)

The dashboard UI renders these analytics using a dynamic "Mini-Card" pattern.

### 2.1 The Interactive Bar Chart Pattern
To visualize bottlenecks, the UI uses `flet.BarChart` to render three distinct graphs. This replaced the initial "Mini-Card" pattern to support comparative analysis across different failure reasons and stages.

```python
def create_mini_chart(title, data_dict, color_seed):
    # Logic to build ft.BarChartGroup from data_dict
    # Applies tooltips and color seeds (Blue for Type, Orange for Stage, Red for Reason)
    return ft.Container(
        content=ft.Column([
            ft.Text(title, size=14, weight="bold", color="white70"),
            ft.BarChart(
                bar_groups=groups,
                border=ft.border.all(1, "white10"),
                left_axis=ft.ChartAxis(labels_size=30, title_size=10),
                bottom_axis=ft.ChartAxis(
                    labels=[ft.ChartAxisLabel(value=i, label=ft.Text(k, size=10, text_align="center")) for i, k in enumerate(keys)],
                    labels_size=40, # Sufficient for full text
                ),
                # ... Axis and Grid configuration ...
                interactive=True,
                expand=True,
            )
        ]),
        height=300,  # Scaled for readability
        width=400,   # Scaled for readability
        bgcolor=GLASS_COLOR,
        border_radius=10,
        padding=25   # Prevents tooltip clipping at window edges
    )
```

### 2.2 Placement and Visibility
- **Relative Layout**: The Failure Analytics container is placed immediately below the primary Metrics Row but above the activity tables.
- **Dynamic Visibility**: The container is automatically hidden (`visible=False`) if the failure count is zero, maintaining a "Clean Desk" UI for perfect runs.

## 3. Classification Integration

The dashboard now surfaces the `service_type` (e.g., `AFFIDAVITS`, `EFILING`) across all tables:
- **Action Required Table**: Includes a "Type" column using a 3-character prefix (e.g., `AFF`) to save horizontal space.
- **Recent Success Table**: Displays the full service name in a subtle `white54` color.

## 4. Lineage Tracking in UI
The "Reason" column in the **Action Required** table displays the last 30 characters of the `logs` field, providing immediate context for failures (e.g., "...AX02 Prefix Missing") without requiring the user to open the full log file.

## 5. Troubleshooting: The "Initializing" Loop

During system startup or heavy database load, the Dashboard window may hang on an "Initializing" state. This occurs when `generate_dashboard(output_mode='data')` returns `None`.

### 5.1 Root Causes
- **Missing Database**: The engine has not yet created `nexus.db`.
- **Missing Schema**: `nexus.db` exists, but the `jobs` table hasn't been initialized by the `JobManager`.
- **Recursive Import/Pathing**: If the `core` package is not in `sys.path` (see Multi-Window Management).

### 5.2 Implementation of Readiness Check
The `dashboard_generator` includes an explicit safety check to prevent crashing on uninitialized environments:

```python
def generate_dashboard(days=1, output_mode='file'):
    if not os.path.exists(DB_PATH):
        return None # DB doesn't exist yet
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # SAFETY CHECK: Ensure 'jobs' table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
    if not cursor.fetchone():
        conn.close()
        return None # Table not ready
```

### 5.4 Improvement for Empty Environment (Standby Mode)
To avoid the "Dashboard Not Available" error on fresh installs or when the database is being initialized, `generate_dashboard` returns a **Standby Page** instead of `None`.

```python
EMPTY_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PCP Nexus | Standby</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body { font-family: sans-serif; background: #0f172a; color: #f8fafc; 
               display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .box { text-align: center; padding: 2rem; background: #1e293b; border-radius: 12px; }
    </style>
</head>
<body>
    <div class="box">
        <h2>PCP Nexus Standby</h2>
        <p>Waiting for engine to process the first batch of emails...</p>
        <p style="font-size: 0.8em; color: #64748b">Generated at: {TIMESTAMP}</p>
    </div>
</body>
</html>
"""
```
This ensures the "Open Dashboard" button is immediately functional and provides real-time feedback (via meta-refresh) until data is ready.

### 5.5 Debugging the Hang
If the dashboard stays on "Initializing", developers should check the following:
1.  **Debug Prints**: Add a print statement within the `while True` update loop of `dashboard_window.py` to verify if `data` is `None`.
2.  **Diagnostic Logs**: Check `dashboard_error.log`. Note that this file is typically created in the **Current Working Directory (CWD)** (project root) because the generator uses a relative path in its `try/except` block.
3.  **Refactoring Regressions**: In high-complexity UI updates (like transitioning to Bar Charts), ensure that essential SQL query blocks (e.g., those defining `action_rows` or `recent_rows`) were not inadvertently deleted, which can cause a `NameError` that prevents the generator from returning data.

---

## 6. Session Log Snapshot (`generate_log_snapshot`)

In addition to the full analytical dashboard, PCP Nexus generates a lightweight **Session Log Snapshot** upon shutdown (or via the "Send Session Log" UI command).

### 6.1 Purpose
- **Context**: Used for high-speed verification that the engine successfully ran its cycles.
- **Content**: Displays only the primary activity table (ID, Filename, Status, Log Snippet).
- **Format**: Optimized for Outlook email rendering (no complex SVG or interactive charts).

### 6.2 Key Difference from `dashboard.html`
While `dashboard.html` provides the full 30-day analytics suite (BarCharts, Duplicate Reviews, Action Items), the `log_snapshot` is a **stateless** HTML view of the current session's top 50-100 items, intended for immediate situational awareness via email alerts.

---

## 7. Success Rate Metric Calculation

The project maintains a strict >98% success rate mandate. This is calculated live via the `dashboard_generator`.

### 6.1 The Success Formula
Initially, the success rate only counted primary outputs. It was refined during load testing to include neutral system actions to prevent metric distortion.

**Current Formula:**
`Success Rate % = (FILED + VERIFIED + ARCHIVED + EXCEPTION_PROCESSED + DUPLICATE + POTENTIAL_ACTION_REVIEW) / Total Period Jobs` 

*Note: 'POTENTIAL_ACTION_REVIEW' refers to jobs in `MANUAL_REVIEW` where `action_flag = 1`. These are counted as successes because the system successfully identified the specific instructional triggers requested (Potential Action Words). This ensures that correctly flagged items do not penalize the overall automation success metric.*

### 6.2 Key Categories
- **VERIFIED/ARCHIVED**: Direct automation successes (processed and filed).
- **DUPLICATES**: Neutral successes; the system correctly identified and ignored redundant work.
- **EXCEPTION_PROCESSED**: Systematic successes; internal reports (e.g., PCP Daily Reports) that the system is programmed to ignore are counted as "Successfully Handled" rather than "Failures".
- **MANUAL_REVIEW**: Counted as a **Miss** until rectified by the Self-Annealing Auditor loop.

## 7. Duplicate Comparison & Review

High-volume environments frequently receive identical documents sent via different electronic envelopes or from multiple attorneys. The system identifies these as `DUPLICATE` to save processing time and storage but provides a dedicated audit trail to ensure 100% detection accuracy.

### 7.1 Cross-Reference Logic (Self-Join Query)
The system uses a SQL self-join on the `file_hash` column to pair a detected duplicate with its original entry. This allows for immediate visual comparison without navigating separate database logs.

```sql
SELECT 
    d.id as dup_id, d.filename as dup_filename, d.original_source as dup_source, d.created_at as dup_time, d.file_path as dup_path,
    o.id as orig_id, o.filename as orig_filename, o.original_source as orig_source, o.created_at as orig_time, o.file_path as orig_path
FROM jobs d
JOIN jobs o ON d.file_hash = o.file_hash AND d.id > o.id
WHERE d.status = 'DUPLICATE'
ORDER BY d.id DESC LIMIT 50
```

### 7.2 The Duplicate Review Table
To flag these for human verification without categorizing them as failures, a **Duplicate Review** table is added to the dashboard. 

| Feature | Implementation |
| :--- | :--- |
| **Comparative Pairing** | Rows are horizontally split between "Duplicate" data and "Original" data. |
| **Full Context** | Displays **Filename/Subject**, **Source (Envelope ID)**, and **Precise Timestamp** for both entries. |
| **Side-by-Side Review** | Provides individual "View" (file://) links for both the duplicate and the original, enabling a user to open both PDFs simultaneously to confirm content parity. |
| **Safety Guard** | Only jobs where the **Content Hash** matches AND the **Source** matches are marked `DUPLICATE`. If the hash matches but the Source differs, the system creates a physical copy (`_COPY_` suffix) and processes it as a unique task. |

## 8. Management by Exception (Final Failures Only)

To maintain a high signal-to-noise ratio during high-volume processing, the dashboard implements a **"Final State" filter** for the Action Required queue.

### 8.1 Transient State Filtering
- **The Problem**: Background agents like the `Auditor` frequently rectify `QA_FAILED` items within seconds of ingestion. Showing these transient failures caused the dashboard to constantly "breathe" (count increasing and decreasing), distracting operators from actual errors.
- **The Solution**: The `dashboard_generator` query excludes `QA_FAILED` from the Action table.
- **Query logic**:
  ```sql
  SELECT * FROM jobs 
  WHERE status IN ('MANUAL_REVIEW', 'ERROR') 
  ORDER BY id DESC
  ```
- **Impact**: The dashboard remains stable. The "Action Items" count only increases when a job has exhausted its automated recovery options (e.g., matching a Tier 2 OCR result) and truly requires human intervention.

## 9. Lifecycle Stage Mapping

To make analytics actionable for non-technical operators, the `dashboard_generator` maps database status codes to process stages via `get_stage_name()`:
- `DUPLICATE` -> **0. Pre-Processing**
- `QA_FAILED` -> **1. Intake (Validation)**
- `MANUAL_REVIEW` -> **2. Audit (Verification)**
- `ERROR` -> **3. System/Archive**

## 10. Relaunch & Recovery Protocols

During high-volume testing or UI logic updates, a "Hard Restart" is occasionally required to flush the Flet state and ensure all background threads are synchronized with the latest code.

### 10.1 Forced Termination
The system provides a global kill command to ensure no "Zombie" engine processes remain linked to the database:
```cmd
taskkill /F /IM python.exe /T
```

### 10.2 Safe Relaunch
1. Close all active UI windows.
2. Run `python Executive\Orchestrator\main.py`.
3. The engine automatically resumes processing the `nexus.db` queue from the last commit point.

## 11. Custom Aesthetic: Square UI Elements

To align with a more "technical" and "professional" dashboard aesthetic, standard rounded UI elements were replaced with square ones.

### 11.1 Implementation (BarCharts)
In `flet`, bar chart rods default to rounded corners. This was neutralized by setting `border_radius=0` in the `BarChartRod` configuration within `dashboard_window.py`.

```python
ft.BarChartRod(
    from_y=0,
    to_y=val,
    width=16,
    color=color_seed,
    tooltip=f"{k}: {val}",
    border_radius=0 # Square corners for technical look
)
```

## 12. Log Persistence Requirement for Analytics

For the **Heuristic Reason Extraction** (Section 1.1) to function, agents must persist specific error reasons to the database.

### 12.1 The Console-only Logging Trap
Early versions of the `Hunter` agent logged validation failures (e.g., "Reason: Low OCR Confidence") only to the stdout/console. Because the Dashboard generator queries `nexus.db`, those failures appeared as "Unknown" or showed timestamps because the `logs` column in the database was empty for those records.

### 12.2 Resolution: Mandatory DB Log Sync
Agents are requirement to explicitly call `job_manager.append_log(job_id, ...)` when recording final validation or processing failures.

```python
# Updated Hunter.py logic
if not is_valid: 
    self.log(f"  Reason: {reason}", "WARN")
    try: 
        job_manager.append_log(job_id, f"Reason: {reason}")
    except: 
        pass
```
This ensures the `Reason:` trigger is present in the database field, enabling the dashboard to successfully parse and categorize the failure.

## 13. Operational Context: Lifecycle Stage Mapping

To facilitate manual human intervention, abstract job statuses (e.g., `QA_FAILED`, `READY_TO_ARCHIVE`) are mapped to human-readable **Lifecycle Stages**.

### 13.1 Stage Definitions
Failures are categorized into three primary operational stages:
1. **Intake (Hunter agent)**: Failures during download or metadata extraction (e.g., `VALIDATION_FAILED`).
2. **Audit (Auditor agent)**: Failures during OCR verification or data matching (e.g., `QA_FAILED`).
3. **Archive (Clerk agent)**: Failures during final movement to CRM or file servers.

### 13.2 Dashboard Implementation
The `dashboard_generator.py` uses a helper `get_stage_name()` to inject a `stage` field into the Action Items table. This allows the UI to display:
*   **ID**: 214
*   **Stage**: Audit (Verification)
*   **Reason**: Missing Case Number

This provides the human operator with an immediate "Where to look" (the Document) vs. "Why it failed" (OCR mismatch).


## 14. Refined Success Rate Logic

To accurately reflect system performance, the "Success" metric was refined to include all correctly handled termination states.

### 14.1 Success Definition
A job is considered "Successful" if it reaches any of the following terminal states:
*   **VERIFIED**: Passed OCR and automation checks.
*   **EXCEPTION_PROCESSED**: Handled by custom system logic (e.g., system reports).
*   **DUPLICATE**: Correctly identified as redundant and handled (not archivable).
*   **POTENTIAL_ACTION**: Jobs correctly flagged for manual review due to identified keywords (e.g., "Rush Fee"). These are considered "Automated Insights" (Successes) rather than system failures.

### 14.2 Calculation Formula
```sql
Success_Rate = (FILED + VERIFIED + ARCHIVED + EXCEPTION_PROCESSED + DUPLICATE + (MANUAL_REVIEW WHERE action_flag=1)) / TOTAL_JOBS
```
Previously, `DUPLICATE` jobs were included in the denominator but not the numerator, creating a "penalty" for high-efficiency duplicate detection.

## 15. Duplicate Handling: Strict vs. Logical

The system differentiates between two types of redundancy to ensure no data is lost during high-volume ingest.

### 15.1 Strict Duplicates
*   **Condition**: Identical File Hash + Identical Source (e.g., re-emailing the same Tyler envelope).
*   **Action**: Marked `DUPLICATE`. No new archive is created.

### 15.2 Logical Duplicates
*   **Condition**: Identical File Hash + **New Source** (e.g., same document attached to a different email/case).
*   **Action**: Treated as a **New Job**. The system creates an **Independent Copy** (`_COPY_timestamp.pdf`) in the download directory.
*   **Why**: This prevents race conditions during the Archive phase where `Job A` might move/delete a file that `Job B` (a logical duplicate) still needs for processing.

## 16. UI Chart Scaling & Label Management

As the number of failure categories increases, X-axis labels on BarCharts can overlap or truncate.

### 16.1 Label Rotation
To maintain readability for long strings (e.g., "Audit Verification Failed"), labels are rotated approximately -30 degrees (-0.5 radians).

```python
ft.ChartAxis(
    labels_size=60, # Increased height for rotated text
    labels=[
        ft.ChartAxisLabel(
            value=i,
            label=ft.Container(
                content=ft.Text(label_text, size=10, text_align="right"),
                rotate=ft.Rotate(angle=-0.5), # Approx -30 degrees
                padding=ft.padding.only(top=10)
            )
        ) for i, label_text in enumerate(categories)
    ]
)
```

### 16.2 Dimension Capping
Standard chart dimensions are set to **300px height** and **400px width** to ensure they fit in a multi-column CRM-style layout without information masking.

## 17. Prescriptive Resolution Strategies

To minimize the cognitive load on human operators, the dashboard provides **Prescribed Next Steps** for every item in the manual review queue.

### 17.1 Heuristic Strategy Mapping
The `dashboard_generator.py` includes a `get_resolution_strategy()` function that maps failure reasons to concrete procedural instructions.

| Failure Reason | Prescribed Resolution |
| :--- | :--- |
| **Audit Verification Failed** | 1. Open File. 2. Visually verify Case Number. 3. If valid, force status. |
| **System: File Missing (Archive)** | 1. Check folder [X]. 2. Re-download if lost. 3. Check permissions. |
| **Validation Failed** | 1. Review PDF content. 2. Check OCR quality. 3. Reject or manually key. |
| **Duplicate Detected** | 1. Review Duplicate table. 2. Ignore if strict. 3. Rename and re-submit if new. |

### 17.2 UI Integration
The **Action Required** table features a dedicated "Prescribed Next Steps" column (width: 300px) with italicized text to guide the operator. This ensures that the person monitoring the system doesn't just see "What" broke, but knows exactly "How" to fix it.


---

## 18. CLI Verification & Manual Generation

To facilitate rapid iteration during Phase 2 development, the `dashboard_generator.py` was updated with a standalone execution block.

### 18.1 Technical Implementation
The script includes an `if __name__ == "__main__":` block that allows it to be run directly from the terminal.
```python
if __name__ == "__main__":
    path = generate_dashboard(days=1, output_mode='file')
    print(f"Dashboard generated at: {path}")
```

### 18.2 Usage in Verification
1.  **Mock Injection**: Run `mock_flagged_job.py` to populate the database with a **Potential Action Word** sample.
2.  **Manual Refresh**: Execute `python Executive/Orchestrator/core/dashboard_generator.py`.
3.  **UI Verification**: Open the resulting `dashboard.html` to confirm that the **Red Triangle (!) indicator** pulses correctly for flagged items in the "Manual Review" queue.
4.  **Visual Proof**: Confirmed via manual refresh that flagged jobs are visually distinct from standard manual review items, ensuring immediate operator awareness of **Potential Action Words** detected within comments.

---

## 19. Phase 2 Audit Visibility & Audit Trace Logic (v2.3)

Following the CTO Strategic Review, the dashboard was verified for Phase 2 "Live Audit" readiness. The system now surfaces the **Hardened Audit Trail** stored in job metadata.

### 19.1 Audit Trace Persistence
The `HunterV2` agent populates the `metadata` JSON column with a step-by-step processing rationale:
- **`classification`**: Explicitly states `ACTION_FLAGGED` or `STANDARD_PROCESS`.
- **`audit_trace`**: Text description of the merge/classification event (e.g., "Merged 3 parts. Lead=AX40.").
- **`part_count`**: Total email parts aggregated into the packet.

### 19.2 Dashboard Live Monitoring
- **Red Triangle SVG (!)**: Confirmed live and pulsing for any items where `action_flag = 1`.
- **Created_at Consistency**: The dashboard uses `created_at` for all period analytics, successfully bypassing the legacy `timestamp` column conflict.
- **Filtering Logic**: Action Flagged items are correctly categorized as **Successes** in the high-level metrics (ensuring no performance penalty for correct intelligence detection) but remain in the **Action Items** table for instructional review.
---

## 20. SharePoint Mirror Data Schema (v2.4 - 30-Column Sync)

The Dashboard surfaces data from the standardized **30-column** schema used by the `SharePointLogger`. 

For the full column definitions and extraction logic, see: [Intelligence & Auditing Specification](../implementation/intelligence_and_auditing.md#2-real-time-audit-schema-the-30-column-mirror).

---

## 21. Dashboard Refresh & Live Export (Feb 4 Update)

To support real-time monitoring of high-volume runs, the dashboard's operational lifecycle was optimized for responsiveness and immediate data portability.

### 21.1 Performance Optimization: 10-Second Refresh
The dashboard's `meta-refresh` rate was adjusted to **10 seconds** (up from 4s). 
- **Rationale**: Reduces the query load on the SQLite `nexus.db` during synchronous processing while maintaining a "near-live" view for operators.
- **Implementation**: Hardcoded in the `HTML_TEMPLATE` within `dashboard_generator.py`.

### 21.2 Client-Side Export & Navigation Logic
A high-priority requirement for real-time auditing was the ability to instantly capture the current activity log and navigate to the output repository.

- **The Solution**: An **"📥 Export CSV"** button was added to the **24-Hour Activity Log** section.
- **CSV Extraction**: Uses client-side JavaScript (`exportActivityLog()`) to traverse the DOM, extract row content (including `Has_Comments` and `Comments`), and trigger a local browser download for immediate review.
- **Folder Navigation**: To assist operators in verifying files locally, a dedicated **"📂 Open Output Folder"** button was added next to the export control.
- **Dynamic Link Resolution**: In `dashboard_generator.py`, the `OUTPUT_FOLDER_LINK` placeholder is dynamically replaced using `app_paths.output_dir()`. The path is converted to a browser-compatible URI: `f"file:///{output_folder.replace(os.sep, '/')}"`.
- **Technical Note**: The use of `.replace(os.sep, '/')` is critical on Windows to ensure that backslashes (which browsers may treat as escape characters or literal path segments) are converted to forward slashes for correct `file:///` protocol interpretation.
- **Benefit**: Ensures operators have zero-latency access to both the data manifest and the physical document repository without manual folder navigation.

### 21.3 Clickable File Links (URI Protocol)
To accelerate manual verification, filenames in the **24-Hour Activity Log** were transformed into hyperlinked elements.
- **Implementation**: Uses the `file:///` URI protocol. 
- **Technical Detail**: The generator uses `os.path.abspath(fpath).replace(os.sep, '/')` to ensure Windows paths are correctly formatted for browser navigation.
- **Operator Impact**: Allows one-click access to the original or archived document directly from the web-based monitoring view.

### 21.4 Prefix Auditing Logic (Original vs. New)
A critical requirement for Phase 1 verification is the visibility of prefix transformations (e.g., `AX02` -> `AX42`). 
- **Dashboad Columns**: The activity log displays both the **Orig Prefix** (Source) and the **New Prefix** (Target).
- **The Heuristics (Standardized Across Modules)**:
    1.  **Original Prefix**: Extracted from the first 4 characters of the `original_filename` from metadata.
    2.  **New Prefix**: Attempts to match the regex pattern `r'^(AX\d{2})'` first; falls back to the first 4 characters of the final generated filename.
    3.  **Metadata Fallbacks**: Uses `['envelope_num', 'envelope_id']` for Envelope IDs and `['lead_doc', 'lead_document', 'subject']` for Lead Documents to ensure cross-module data consistency.
- **Reasoning**: Ensures that operators can verify the transformation logic was applied correctly without opening the physical file, and identifies items where the system correctly transitioned from Phase 1 inputs to Phase 2 outputs.
- **Native Excel Sync**: The real-time exporter now also generates a native `.xlsx` file alongside the CSV to support immediate review in Excel without formatting issues.

### 21.5 Template Indentation & F-Strings
When editing the `dashboard_generator.py` HTML template within Python f-strings, strict adherence to indentation is required to avoid `IndentationError`.
- **Pattern**: For multi-line variables like `log_html`, ensure that the closing triple-quote `"""` and the assignment are correctly aligned with the parent loop's indentation.
- **Trap**: Unwanted spaces at the start of a logic line (like `link_text = ...`) inside the loop can trigger a compiler error.

---

## 22. Cross-Module Standardization (Feb 4, 2026)

To ensure data integrity and eliminate discrepancies between the Live Dashboard, Real-time Exports (CSV/Excel), and Daily Email Reports, the system implements a unified extraction heuristic.

### 22.1 Metadata Field Standard Definitions

| Logical Field | Primary Key | Fallback Keys |
| :--- | :--- | :--- |
| **Envelope ID** | `envelope_num` | `envelope_id`, `envelope` |
| **Case Number** | `case_num` | - |
| **Lead Document** | `lead_doc` | `lead_document`, `subject` |
| **Original Filename**| `original_filename` | - |
| **Job Number** | `pcp_job_num` | `job_num`, `old_job_num` |
| **Comments** | `raw_comments` | `comments`, `accepted_comments` |

### 22.2 Unified Prefix Heuristics

1.  **Original Prefix**: Extracted from the first 4 characters of the `original_filename` from job metadata.
2.  **New Prefix**:
    *   **Primary**: Regex match `r'^(AX\d{2})'` against the final filename.
    *   **Fallback**: Slicing the first 4 characters of the final filename.

### 22.3 Standard Alignment Status
- **RealtimeExporter**: Updated to use hybrid prefixes and unified keys. ✅
- **DashboardGenerator**: Updated to include `Orig_Prefix` / `New_Prefix` columns, unified keys, and the "Open Output Folder" action link. ✅
- **Reporter** (Daily CSV): Standardized to a 20-column schema including prefix and comment metadata. ✅
- **SharePointLogger**: Comprehensive 30-column log inherits these standardized keys prior to writing. ✅
