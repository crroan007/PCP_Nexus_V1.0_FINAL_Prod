# Standardized Reporting & Export Logic

The PCP Nexus platform implements a multi-channel reporting suite (Dashboard, CSV/Excel Exports, Daily Reports) that utilizes a unified metadata extraction heuristic to ensure data consistency across all outputs.

## 1. Differentiated Real-time Export Formats

As of February 4, 2026, the `RealtimeExporter` differentiates between CSV and Excel formats to serve distinct operational needs: compatability with external intake systems (CSV) and detailed internal auditing (Excel).

### 1.1 Phase-Specific CSV Files (v4.3)
The `RealtimeExporter` produces **two phase-specific CSV files** rather than a single activity CSV:
- **Phase 1**: `pcp_phase1_YYYYMMDD.csv` — Written when a job reaches `ARCHIVED` status (`service_type='AFFIDAVITS'`)
- **Phase 2**: `pcp_phase2_YYYYMMDD.csv` — Written when a job reaches `FILED` status (`service_type='PROJECT_2'`)

#### Rotation Lifecycle (Move + Reset)
CSVs are rotated on a schedule (Phase 1 daily at 10 PM, Phase 2 hourly):
1. **Archive**: If a file already exists on the network share, it is timestamped and moved to `Archive/`
2. **Move**: The local CSV is **moved** (not copied) to the network share
3. **Reset**: A fresh blank CSV with headers replaces the local file

This ensures the network share always has the latest data, while the local file accumulates new records for the next cycle.

### 1.2 Simplified CSV Format (8 Columns)
Designed for maximum compatibility with external software that expects a specific document manifest.

| Column | Description | Extraction Logic |
| :--- | :--- | :--- |
| **Envelope_Num** | Envelope ID | `metadata['envelope_num']` or `metadata['envelope_id']` |
| **Case_Num** | Case Number | `metadata['case_num']` |
| **Date_Submitted** | Date document was sent | `_parse_datetime(date_submitted_raw)` [Date] |
| **Time_Submitted** | Time document was sent | `_parse_datetime(date_submitted_raw)` [Time] |
| **Date_Accepted** | Date document was processed | `_parse_datetime(date_accepted_raw)` [Date] |
| **Time_Accepted** | Time document was processed | `_parse_datetime(date_accepted_raw)` [Time] |
| **Lead_Document** | Lead document name | `metadata['lead_doc']` or `metadata['lead_document']` or `metadata['subject']` |
| **PCP_Job_Num** | PCP unique job ID | `metadata['pcp_job_num']` or `metadata['job_num']` |

### 1.2 Full-Detail Excel Format (14 Columns)
Designed for exhaustive internal auditing and historical record-keeping.

| Column | Description |
| :--- | :--- |
| **ID** | Database unique ID |
| **Timestamp** | Full ISO timestamp of event |
| **Filename** | Local archived filename |
| **Envelope_ID** | Original envelope identifier |
| **Case_Number** | Court case number |
| **Lead_Doc** | Normalized lead document title |
| **Orig_Input** | Original filename as received |
| **Orig_Prefix** | Regex `(AX\d{2})` extracted from Lead Doc (e.g., AX02 from AX02A26101444.PDF) |
| **New_Prefix** | Regex `(AX\d{2})` extracted from final filename |
| **Status** | Terminal job status (FILED, VERIFIED, etc.) |
| **Outcome** | High-level outcome summary |
| **Next_Steps** | Prescribed resolution action |
| **Has_Comments** | Boolean (Y/N) indicating existence of clerk comments |
| **Comments** | Raw concatenated comment text |

## 2. Shared Data Heuristics

To ensure alignment across all reporting modules (`realtime_exporter.py`, `dashboard_generator.py`, `reporter.py`, and `sharepoint_logger.py`), a standardized lookup pattern is used.

### 2.1 Metadata Key Mapping

| Logical Field | Primary Key | Fallback Keys |
| :--- | :--- | :--- |
| **Envelope ID** | `envelope_num` | `envelope_id`, `envelope` |
| **Case Number** | `case_num` | - |
| **Lead Document** | `lead_doc` | `lead_document`, `subject` |
| **Job Number** | `pcp_job_num` | `job_num`, `old_job_num` |
| **Comments** | `raw_comments` | `comments`, `accepted_comments` |

### 2.2 Date/Time Splitting (`_parse_datetime`)
Legacy input strings (e.g., `2026-02-04 14:30:00`) are parsed using a robust multi-format strategy to extract separate `MM/DD/YYYY` and `HH:MM:SS` components for the CSV manifest.

### 2.3 Prefix Extraction
Prefixes are crucial for tracking the transition from Phase 1 (Incoming) to Phase 2 (Outgoing) workflows.
- **Original Prefix**: Regex search `(AX\d{2})` against Lead Document filename (e.g., `AX02A26101444.PDF` → `AX02`)
- **New Prefix**: Regex search `(AX\d{2})` against final archived filename
- **Fallback**: Returns `-` if no AX pattern is found

## 3. Dashboard Interactivity

The live dashboard (`dashboard.html`) provides interactive extensions to the static manifests:
- **Clickable Links**: Filenames are linked via `file:///` URI protocol for instant file review.
- **DB-Driven CSV Tabs**: Two dedicated tabs (📋 Phase 1 CSV, 📋 Phase 2 CSV) query the SQLite database directly for always-current phase-specific data. These are independent of the polling CSVs.
- **Verification Tab**: Stacked Phase 1 (Rename) + Phase 2 (Merge) sections generated dynamically from `nexus.db` by `VerificationReporter`. Daily auto-reset (filters by `TODAY`). Phase 2 columns: Envelope | Output PDF (linked) | Pages | Sources (#) | Source Pages | Check (✔/▲) | Status | Source Documents (per-file with prefix badge + link + page count). Uses PyPDF2 `PdfReader` for actual page counting. `constituent_docs` metadata populated during merge for audit trail. Passing statuses: `FILED`, `VERIFIED`, `NEW`, `COMPLETED`, `ARCHIVED`.
- **Dynamic CSS**: Flagged comments (those containing "RUSH" or "CORRECT") trigger visual indicators.
- **Standardized Refresh**: 10-second auto-refresh ensures visibility of processing bursts.

## 4. Standard Alignment Status (Feb 11, 2026)

- **RealtimeExporter**: Phase-specific CSVs with move+reset rotation lifecycle. ✅
- **DashboardGenerator**: Phase 1/Phase 2 CSV tabs (DB-driven), Verification tab with stacked layout. ✅
- **VerificationReporter**: Rewritten with page counting (PyPDF2), source doc enumeration, integrity checks (output pages vs source pages), per-file details with prefix badges and clickable links. ✅
- **Reporter** (Daily CSV): Alignment pending. 🔄
- **SharePointLogger**: Comprehensive 30-column log. ✅

## 5. Phase 2 Merge Pipeline (v4.3)

The Phase 2 merge pipeline handles multi-document envelopes from Tyler e-Filing:

1. **Email Grouping**: Emails grouped by Envelope ID. Tyler sends N notification emails per envelope.
2. **First-Email-Only Download**: Only the first email downloads from the Tyler multi-doc page (all emails have the same docs). Others are tagged `PCP-Packetized` without downloading.
3. **Packetization**: Downloaded files queued in `pending_packets` table with `doc_type` classification (LEAD, ATTACHMENT, CLERK_LETTER, CORRECTION).
4. **Delayed Merge**: After configurable wait, packets are merged in order: LEAD → AXPB → AXPE(s) → AXPM → AXPL. CL excluded from merge.
5. **Basename Dedup Safety Net**: Before merge, deduplicate files by `os.path.basename()` to catch any residual duplicates.
6. **Intelligence**: Comments extracted from all parts, analyzed for action keywords, classification set.
7. **Metadata**: `constituent_docs` (actual filenames), `merged_parts` (prefixes), `part_count` stored for verification.

> **Note**: Launch with `python -B -X utf8 main.py` to prevent stale `.pyc` cache issues and ensure proper encoding.
