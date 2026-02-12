# PCP Nexus: Intelligence & Auditing Specification

This document details the logic and implementation of the "Automated Intelligence" layer, which scans processed documents and metadata for critical action items, flags them for human review, and maintains a comprehensive real-time audit trail.

---

## 1. Intelligence Engine Logic

The `IntelligenceEngine` is responsible for scanning both document text (via PDF extraction/OCR) and email metadata (specifically "Accepted Comments") for high-priority keywords defined in the Action Phrase Library.

### 1.1 Action Phrase Library
The system uses a configurable library (`reporting_keywords.json`) to identify potential issues such as:
- **Rush Requests**: "Rush", "ASAP", "Urgent".
- **Financial Indicators**: "Fee", "$", "USD", "Payment".
- **Instructional Phrases**: "Hold", "Serve", "Stop".
- **Special Comments**: "Thank you", "Notes", or any manual entry by a court clerk.

### 1.2 "Accepted Comments" Extraction
The system monitors the "Accepted Comments" field in Tyler Technologies e-filing notifications.
- **Heuristic**: Uses `REGEX_COMMENTS = r"Accepted Comments\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)"` to isolate the first line of the comments block.
- **Default Pattern**: Many court clerk systems default to "Filing Type EFile" if no manual notes are entered.
- **Manual Pattern**: If a clerk enters a note (e.g., "THANK YOU FOR E-FILING/ EROMERO"), the system prioritizes this string.
- **Logic**:
    1. Extract the raw text following "Accepted Comments:".
    2. Scan the text against the Action Phrase Library.
    3. If a match is found, set `Action_Flag` to **"Yes"** and list the `Matched_Phrases`.
    4. If no specific action phrase is found but a comment exists, set `Action_Flag` to **"No"** but still record the `Accepted_Comments` value.

### 1.3 Real-time Prefix Auditing (Original vs. New)
To verify correct Phase 1 to Phase 2 transformations, the system applies a dual-source extraction heuristic for auditing:
- **Original Prefix**: Extracted from the first 4 characters of the `original_filename` in metadata. 
- **New Prefix**: Extracted from the final generated filename. The system first attempts to match the regex pattern `r'^(AX\d{2})'`. If no match is found (e.g., for non-AX patterns during Phase 2 or legacy cases), it falls back to extracting the first 4 characters of the filename.

### 1.4 Cross-Module Standardization (Standardized Logic)
To ensure zero discrepancies between the dashboard, real-time exports, and daily reports, all modules must use the following standard extraction patterns:

#### Metadata Field Fallbacks
| Logical Field | Primary Key | Fallback Keys |
| :--- | :--- | :--- |
| **Envelope ID** | `envelope_num` | `envelope_id`, `envelope` |
| **Lead Document** | `lead_doc` | `lead_document`, `subject` |
| **Original Filename**| `original_filename` | - |
| **Job Number** | `pcp_job_num` | `job_num`, `old_job_num` |
| **Comments** | `raw_comments` | `comments`, `accepted_comments` |

#### Standardized Comment Processing
```python
def get_comments(metadata):
    """Unified comment extraction with flag detection."""
    comments = (metadata.get('raw_comments') or 
                metadata.get('comments') or 
                metadata.get('accepted_comments') or '')
    
    # Binary indicator for auditing
    has_comments = "No"
    if comments and comments.strip() and comments.strip() != '-':
        has_comments = "Yes"
        
    return has_comments, comments.strip() if comments else "-"
```

### 1.4 Comment Aggregation Strategy
The system employs a dual-source aggregation method to ensure no context is lost during processing:
- **Email Source**: Extracted via `REGEX_COMMENTS` from the Tyler notification (body or HTML).
- **Document Source**: Extracted from each individual PDF page/header during the merge phase.
- **Precedence**:
    1. The email's "Accepted Comments" are treated as the primary instruction and are prefaced with `[Email Link Comments]:`.
    2. Comments found inside the PDFs are appended with their respective document prefixes and a source tag (e.g., `[AX02 Document]: Service completed at...`).
    3. The final `Accepted_Comments` audit field contains the **merged string** of all discovered comments, preserving the source headers for analytical clarity. This merged string is then passed to the `analyze_text` engine for keyword-based priority flagging.

---

## 2. Real-Time Audit Schema (The 30-Column Mirror)

To meet customer requirements for "Comment Flagging" and enhanced case data tracking, the audit log (SharePoint Mirror) has been expanded to 30 columns. This ensures every document has a clear "Action vs. Information" status and full case context.

### 2.1 Schema Definition

| # | Field | Description |
|---|---|---|
| 1 | **Timestamp** | Arrival time of the processing event. |
| 2 | **NodeID** | Identifies the physical/virtual machine performing the task. |
| 3 | **JobID** | Internal PCP Database ID. |
| 4 | **Action** | Event type (DETECTION, FILE_OUTPUT, ERROR). |
| 5 | **Status** | Current state (INGESTING, FILED, ERROR). |
| 6 | **Message** | Human-readable description of the activity. |
| 7 | **Original_Filename**| The name of the file as received. |
| 8 | **New_Filename** | The final transformed filename. |
| 9 | **Old_Job_Num** | The extracted Job Number (A25...). |
| 10 | **Envelope_ID** | The Tyler Technologies Envelope ID. |
| 11 | **Case_Number** | **(NEW)** The court case number (e.g., 26-0025-FC3). |
| 12 | **Court** | **(NEW)** The jurisdictional Court name parsed from the email. |
| 13 | **Case_Style** | **(NEW)** The litigants/style (e.g., In The Matter Of...). |
| 14 | **Source_Path** | Local path to the source file. |
| 15 | **Source_Link** | Excel Hyperlink to the source file. |
| 16 | **Final_Path** | Local path to the production PDF. |
| 17 | **File_Link** | Excel Hyperlink to the production PDF. |
| 18 | **Constituent_Docs**| (Phase 2) List of files merged into the result. |
| 19 | **Reason** | Business logic reason for the action. |
| 20 | **Next_Steps** | Tasks flagged for human review. |
| 21 | **Lead_Doc** | The "Lead Document" name from email body. |
| 22 | **Original_Prefix** | The 4-character source prefix (AX02). |
| 23 | **Target_Prefix** | The 4-character target prefix (AX42). |
| 24 | **Action_Flag** | **(NEW)** "Yes" if action phrases found; "No" otherwise. |
| 25 | **Matched_Phrases** | Keywords triggering the action flag (e.g., "Rush"). |
| 26 | **Accepted_Comments**| **(NEW)** The raw value from the "Accepted Comments" section. |
| 27 | **Phase** | Identifier (Phase1 or Phase2). |
| 28 | **Part_Count** | Number of unique attachments/links processed. |
| 29 | **Email_Received** | Timestamp from the Outlook message header. |
| 30 | **Email_Subject** | Original subject line for correlation. |

---

## 3. Implementation Notes

### 3.1 SharePointLogger Integration
The `SharePointLogger` uses a thread-safe append mechanism. When a document is filed, it queries the `IntelligenceEngine` for the `Action_Flag` based on extracted comments before writing the final row to the mirror CSV.

### 3.2 Metadata Extraction (HunterV2)
The `Hunter` agent uses robust regex patterns to populate the audit log:
- `REGEX_COURT`: `Court\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)`
- `REGEX_CASE_STYLE`: `Case Style\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)`
- `REGEX_COMMENTS`: `Accepted Comments\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)`

### 3.3 Dashboard Priority
The Dashboard consumes this 30-column log to highlight "Yes" flags with red indicators, ensuring clerks can prioritize files with specific instructions or issues (ASAP, Rush, etc.).

### 3.4 Portability & Path Resolution
To support deployment across multiple nodes (including frozen PyInstaller builds), `IntelligenceEngine` uses the `app_paths.py` utility for locating its ruleset:
- **Relative Resolution**: `KEYWORDS_PATH = str(app_paths.ensure_dir(app_paths.logs_dir().parent / "data") / "reporting_keywords.json")`
- **Fallback**: If the config folder or `reporting_keywords.json` is missing, the engine defaults to a hardcoded baseline set of financial and instructional keywords to ensure processing continuity.

---

## 4. Auditor OCR Pipeline (v2.3)

The `Auditor` agent implements a high-precision OCR pipeline to minimize "Manual Review" false positives.

### 4.1 Multi-Stage Pipeline
1.  **High-Res Rendering**: Uses `PyMuPDF` (Fitz) to render the first page of the PDF at 3x resolution (approx 216 DPI) via a `Matrix(3, 3)`.
2.  **Preprocessing**:
    - **Grayscale**: Removes color noise.
    - **Contrast Enhancement**: Boosts contrast by 2.0x using `ImageEnhance`.
3.  **OCR Execution**: Uses `EasyOCR` (English model, CPU mode) to extract text content.
4.  **Fuzzy Verification**:
    - Compares extracted text against the known **Case Number**, **Envelope ID**, and **Job Number**.
    - Threshold: **85%** (via `thefuzz.partial_ratio`) to account for common OCR character substitutions (e.g., `0` vs `O`).
5.  **Heuristic Extraction (Fallback)**: If fuzzy verification fails, the Auditor applies 4 regex patterns to the raw OCR text:
    - `Pattern 1`: Standard case format (`25-CCV-077597`).
    - `Pattern 2`: "CAUSE NO" identifier.
    - `Pattern 3`: Anchor-based (Inv/Case/No) + Alphanumeric (e.g., `A254...`).
    - `Pattern 4`: A-Series Format (`A-##-...`).

---

## 5. System Continuity Services

### 5.1 Enterprise Backup Service
To mitigate database corruption risks on shared network drives, the `BackupService` handles period redundancy:
- **Frequency**: Every 30 minutes.
- **Mechanism**: Naive `shutil.copy2` (Safe for WAL-enabled SQLite databases).
- **Retention**: Keeps exactly the last **10** backups.
- **Location**: `C:\ProgramData\PCP-Automation\Backups`.

### 5.2 Reporter Service
The `Reporter` generates critical business manifests from `nexus.db` metadata:
- **Daily CSV**: `eaffidavits_accepted_{MMDDYYYY}.csv`.
- **Standardized Columns (20 Total)**:
    - Envelope_Num, Case_Num, Date_Submitted, Time_Submitted, Date_Accepted, Time_Accepted, Lead_Document, PCP_Job_Num.
    - Audit Trail: Original_Filename, New_Filename, **Orig_Prefix**, **New_Prefix**, **Has_Comments**, **Comments**, Final_Path, Constituent_Docs, Merged_Link.
    - Performance Data: Email_Received, Email_Processed, Processing_Delta_Minutes.
- **Distribution**: Automatically emails the CSV to configured recipients upon the conclusion of a processing cycle or scheduled interval.

---

## 6. Internal Database Schema

The system uses a SQLite database (`nexus.db`) located in the **data** sub-directory (relative to the base data root).

### 6.1 The `jobs` Table
The authoritative schema for the `jobs` table (which tracks every processed document) is as follows:

| Column | Type | Description |
|---|---|---|
| **id** | INTEGER (PK) | Primary unique identifier for the record. |
| **filename** | TEXT | The output filename (e.g., AX40...). |
| **file_path** | TEXT | Full path to the processed output file. |
| **status** | TEXT | Processing state (ARCHIVED, PENDING, ERROR). |
| **original_source**| TEXT | Path to the source document or Tyler link. |
| **locked_by** | TEXT | Computer Name/Process ID currently handling the job. |
| **locked_at** | TIMESTAMP | Time of lock acquisition. |
| **created_at** | TIMESTAMP | Job creation timestamp. |
| **updated_at** | TIMESTAMP | Last modification timestamp. |
| **computer_name** | TEXT | Node ID performing the work. |
| **logs** | TEXT | Internal processing trace for this specific job. |
| **service_type** | TEXT | E.g., 'AFFIDAVITS'. |
| **workflow_log** | TEXT | JSON snippet of state transitions. |
| **metadata** | TEXT | JSON blob of extracted Tyler metadata. |
| **action_flag** | INTEGER | 0 or 1 indicator for high-priority comments. |
| **raw_comments** | TEXT | The unfiltered "Accepted Comments" text. |
| **file_hash** | TEXT | Unique MD5/SHA hash of the file content. |

**Note**: Querying for `job_id` will result in an error; use the **`id`** column for record retrieval or **`filename`** for business-logic correlation.
