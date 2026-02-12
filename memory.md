# PCP Nexus — Session Memory (Feb 11, 2026)

## Current State: 🔄 LIVE TESTING (v4.3.2 Prefix Whitelist + Dedup + Multi-Doc Fix)

**Phase 1 Processing: ✅ WORKING**
- 38 PDFs generated with correct prefix renames (100% pass rate)
- All files verified: correct naming, file exists, reasonable page counts (2–12 pages)
- Processes "Filing Accepted" emails correctly.

**Phase 2 Processing: 🔧 TWO CRITICAL FIXES DEPLOYED — TESTING**
- **Bug 1 — N× Duplication (Feb 11):** Tyler sends N notification emails per envelope, each wrapping the SAME download page in a different Proofpoint URL. Old code downloaded from every email → N× page duplication.
- **Fix 1:** First-email-only download in both `_packetize_envelope` AND `_process_envelope_complete` (immediate path).
- **Bug 2 — MultiDocumentResult Swallowed (Feb 11):** `link_downloader.py` detected multi-doc Tyler pages and raised `MultiDocumentResult`, but `except Exception` handlers on 3 levels caught and swallowed it. The HTML landing page was saved as a corrupt PDF. The multi-doc download handler in `_download_message_parts` NEVER fired.
- **Fix 2:** Added `except MultiDocumentResult: raise` at all 3 exception levels in `link_downloader.py`. Added HTML cleanup before individual doc downloads.
- **Evidence:** 181 occurrences of "Unfurling Error: Tyler page contains 2 documents" in Intake.log. 0/76 envelopes had multi-prefix sources.
- **Reference Case:** Envelope #110567610 (Brandy's test case) — should show AX40 + AXPB + AXPE sources.

**Phase 2 Verification Reporter: ✅ REWRITTEN**
- New columns: Envelope | Output PDF (linked) | Pages | Sources (#) | Source Pages | Check | Status | Source Documents
- Uses PyPDF2 `PdfReader` for actual page counts
- Source docs show per-file page counts and clickable links
- Check column: ✔ (green) if output pages = source pages, ▲ (yellow) if mismatch

---

## ⚠️ Technical Fixes Applied (Feb 11) — MAJOR CODE CHANGE

> **WARNING:** v4.3.1 contains significant changes to the Phase 2 merge pipeline across multiple core files:
> `hunter_v2.py`, `verification_reporter.py`, `status_writer.py`, `engine.py`, `tk_app.py`, `dashboard_generator.py`, `health_service.py`.
> Requires full regression test before production deployment.

### 1. Phase 2 First-Email-Only Download (Critical)
**File:** `Source/agents/hunter_v2.py` (`_packetize_envelope` + `_process_envelope_complete`)
**Issue:** N emails per envelope → N× downloads of the same Tyler multi-doc page → N× duplicate pages in merge.
**Fix:** Only download from the first email per envelope. Applied to BOTH the delayed packet path AND the immediate processing path (which handles all jobs when emails arrive in batch).

### 2. Basename Dedup Safety Net
**File:** `Source/agents/hunter_v2.py` (`_process_expired_packets`)
**Issue:** Safety net for any residual file-level duplicates.
**Fix:** Before merge, deduplicate files by `os.path.basename()`.

### 3. Constituent Docs Metadata
**File:** `Source/agents/hunter_v2.py` (`_process_expired_packets`)
**Issue:** `constituent_docs` was never populated (always `None`).
**Fix:** Now stores `original_name` for each merged file in metadata. Verification reporter reads this for detailed source doc display.

### 4. Phase 2 Verification Table Rewrite
**File:** `Source/core/verification_reporter.py`
**Issue:** Old table showed wrong columns (Parts, Type) instead of page counts and source doc details.
**Fix:** Complete rewrite with page counting, source doc enumeration, and integrity checks.

### 5. Live Status & Health Monitoring
**Files:** `status_writer.py`, `engine.py`, `hunter_v2.py`, `tk_app.py`, `dashboard_generator.py`, `health_service.py`
**Feature:** Real-time engine status updates (heartbeat, progress, stall detection).

### 6. MultiDocumentResult Exception Swallowing Fix (Critical)
**File:** `Source/utils/link_downloader.py`
**Issue:** `download_file()` correctly detected Tyler multi-doc pages and raised `MultiDocumentResult`, but `except Exception` on 3 levels caught and swallowed it. The HTML landing page was saved as a corrupt `.pdf`. 181 occurrences in logs.
**Fix:** Added `except MultiDocumentResult: raise` before all generic `except Exception` handlers. Also cleans up HTML landing page file in `_download_message_parts` before downloading individual documents.
**Impact:** Tyler pages with 2+ documents (AX40 + CL, or AX40 + AXPB + AXPE) now correctly download each document individually.

### 7. Phase 2 Prefix Whitelist on Tyler Multi-Doc Pages (v4.3.2)
**File:** `Source/agents/hunter_v2.py` (`_download_message_parts` MDR handler)
**Issue:** Tyler multi-doc pages sometimes list documents from multiple phases (e.g., AX09 Phase 1 affidavits, AX06 unknown prefix). The MDR handler only filtered CL/AX69/AX81:code blindly downloaded and merged all others into the Phase 2 output PDF.
**Fix:** Added a prefix whitelist check after the CL/AX69/AX81 discard scan. Only documents with valid Phase 2 actionable prefixes (`AX40, AXPB, AXPE, AXPM, AXPL, AXPA`) are downloaded. All others are skipped with an INFO log.
**Affected prefixes now skipped:** AX09, AX06, AX02, AX03, AX07, and any other non-Phase-2 prefix.

---

## Business Rules (Per Brandy, Feb 11)

1. **One AX40 per envelope** — Lead document (never duplicated)
2. **One AXPB per envelope** — Usually one
3. **Multiple AXPE allowed** — Courts require separate exhibit filings (Exhibits A, B, C, etc.)
4. **Merge order:** AX40 (lead on top) → AXPB → AXPE(s) → AXPM → AXPL → AXPA → CL (excluded from merge)
5. **CL suffix detection:** `AX40(Job#)CL.pdf` → Clerk Letter, excluded from merge

---

## Prior Fixes (Feb 9)

### Phase 2 Stale Packet Fix
**File:** `Source/agents/hunter_v2.py`
**Issue:** Packets marked `COMPLETED` were ignoring late-arriving split parts.
**Fix:** Added logic to detect new files for `COMPLETED` packets, reset status to `PENDING`, and trigger re-merge.
**Flag:** `Phase2.ReopenCompletedOnNewFiles: true`

### Config Output Path
**File:** `config.json`
**Issue:** `Phases.Phase2.OutputPath` (old nested key) was overriding `Phase2.Output`.
**Fix:** Removed/Updated nested key to point to correct output directory.

---

## Known Gaps (Future Enhancements)
1. **Phase 1 Non-Filing Handlers**: Emails for "Affidavits Sent", "Conformed M&O" are currently skipped.
2. **Sender Validation**: Currently commented out in `hunter_v2.py` for testing. **Uncomment for production**.

---

## Reset Procedure (For Clean Run)
1. Stop App.
2. Run wipe script (DB + packets + logs + CSV + engine status + outputs).
3. Clear Outlook categories if needed.
4. Relaunch with `python -B -X utf8 main.py`.
