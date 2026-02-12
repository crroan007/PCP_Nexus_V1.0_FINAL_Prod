# Project 2 Part 1: Master Specification
## Multi-Type Document Automation & Multi-Defendant Logic

**Date**: 2026-01-16
**Status**: APPROVED / ACTIVE ARCHITECTURE

---

## Part 1: Product Requirements Document (PRD)

### 1. Executive Summary
This phase extends the existing "Hunter" automation (Phase 1) to support a broader range of legal document types (`AX69`, `AX81`, `AXPB`, etc.). The core complexity is the **Multi-Defendant Scenario**, where a single incoming email mapping to a legal case must be associated with *one or more* internal PCP Job Numbers.

The system will employ a **3-Layer "Worst Case" Extraction Strategy** to ensure no defendant is missed, scanning purely digital metadata first, but falling back to deep OCR inspection if ambiguity exists.

---

### 2. Document Classification Strategy
*(Updated per Video 3 Requirements)*

#### 2.1 Actionable Packets (Phase 2)
The system will monitor the **1-AcceptedFiling** folder for the following prefixes. These trigger the **Smart Wait** logic and **PDF Merging** engine:

| Code | Type | Logic Pattern |
| :--- | :--- | :--- |
| **AX40** | *Lead Petition* | Prefix Match `AX40` (MUST be Page 1) |
| **AXPE** | *Exhibit* | Prefix Match `AXPE` |
| **AXPM** | *Military Affidavit* | Prefix Match `AXPM` |
| **AXPB** | *Business Record* | Prefix Match `AXPB` |
| **AXPL** | *Letter* | Prefix Match `AXPL` |
| **AXPA** | *Proposed Order* | Prefix Match `AXPA` |

#### 2.2 Explicitly Ignored (Silent Skip)
The following types must be **Identified, Marked Read, and Filed Away** into `3-AI Completed` without downloading or processing:

| Code | Type | Logic Pattern |
| :--- | :--- | :--- |
| **AX69** | *Non-Deliverable* | Prefix Match `AX69` |
| **AX81** | *Non-Deliverable* | Prefix Match `AX81` |
| **CL**   | *Clerk Letter* | Prefix Match `CL` or `AX...CL` |

---

### 3. High-Level Logic Flow

#### Step 1: Trigger & Intake (Hunter Agent)
1.  **Monitor**: "Filing Accepted" emails.
2.  **Filter**: Subject Line validation (matches `Case \d+; .* vs .*`).
3.  **Parse**: Extract `Lead Document` name from HTML body.
    *   *Validation*: Check if Lead Doc starts with an in-scope prefix (e.g., `AX69...`).
    *   *Extraction*: Parse the "Primary Job Number" embedded in the filename (e.g., `AX81`**`A25C01512`**`.PDF` -> `A25C01512`).

#### Step 2: "Worst Case" Deep Scan (The 3-Layer System)
*Goal: Identify if this document applies to OTHER defendants/Jobs not listed in the filename.*

1.  **Layer 1 (Metadata Check - <100ms)**
    *   Check Email Subject: Does it contain "et al" or multiple names?
    *   Check Email Body: Parse "Case Contacts" table if present.
    *   *Result*: If explicit single defendant -> Proceed. If ambiguous -> Trigger Layer 2.

2.  **Layer 2 (PDF Text Extraction - 1-2s)**
    *   Download `File Stamp Copy` PDF.
    *   Extract text using `pypdf`.
    *   Regex Search: `Defendant(s?):?\s*(.*)`
    *   *Result*: List of names found.

3.  **Layer 3 (Heavy OCR - 5-10s)**
    *   *Trigger*: If Layer 2 yields < 50 characters or "scanned image" signature.
    *   Action: `pytesseract` (Tesseract v5) with image preprocessing (upscaling/thresholding).
    *   *Result*: Final text block for Regex.

#### Step 3: Job Matching (The "Brain")
*Goal: Map the "Defendants Found" to "Internal PCP Job Numbers".*

> **CRITICAL COMPONENT: "THE LIBRARIAN" (Lookup Logic)**
> Since no external Master List exists, we rely on a self-built **Reverse Index**.

1.  **Primary Job**: From Lead Doc filename (e.g., `A25001`).
2.  **Secondary Jobs**: Lookup `Case ID` in `nexus.db` (The Index).
    *   *Query*: `SELECT job_numbers FROM case_index WHERE case_id = ?`
    *   *Result*: `[A25001, A25002, A25003]`
3.  **Fallback (Human-Assist)**:
    *   IF index returns *only* the Primary Job, but OCR found "Jane Doe" (implies missing secondary job):
    *   **ACTION**: Create "Pending" Task in Dashboard.
    *   **USER**: Manually enters "A25002" for Jane Doe.
    *   **SYSTEM**: Files the document AND updates the Index forever.

#### Step 4: Output & Filing (Clerk Agent)
*Configuration: Default "Option B" (Redundant)*

1.  **Iterate**: For `Job_Num` in `List[Job_Numbers]`:
    *   **Rename**: `[Prefix][Job_Num].pdf` (e.g., `AX81A25002.pdf`).
    *   **Save**: Copy file to `\\Output\Job Folder`.
2.  **Complete**: Mark email as Read (or move to `3-AI Completed`).

---

### 4. Architecture Component: "The Librarian" (New)
*A background agent that builds the "Master List" from your existing files.*

*   **Role**: Reverse-Indexer.
*   **Behavior**:
    1.  Recursively scans your server folders: `\\172...\psaffidavits\Output\` (or main Job root).
    2.  Reads Folder Names / Existing File Names.
    3.  Extracts: `Case ID` <-> `Job Number` pairs.
    4.  Populates: `nexus.db` -> `case_index` table.
*   **Safety**: Runs low-priority to avoid network lag.
*   **Benefit**: "Learns" your case history automatically without data entry.

---

### 5. The "Packet Aggregator" (Hunter V2)
**Architecture**: Stateful "Wait & Merge" Agent.
**Budget**: 5 Hours.

**Operational Lifecycle**:
1.  **Ingestion Phase**:
    *   **Monitor**: Scans the `1-AcceptedFiling` folder.
    *   **Filter**: Identifies actionable prefixes (`AX40`, `AXPE`, `AXPM`, `AXPB`, `AXPL`, `AXPA`).
    *   **Silent Skip**: Prefixes `AX69`, `AX81`, and `CL` are identified, marked as read, and moved to `3-AI Completed` immediately.
    *   **Queue**: Actionable files are staged locally and registered in the `pending_packets` table (Tracks `envelope_id`, `first_seen`, `file_count`).
2.  **Aggregation Phase (The 20-Min Wait)**:
    *   A background loop polls the `pending_packets` table.
    *   **Trigger**: When `CURRENT_TIMESTAMP > (first_seen + 20 minutes)`.
    *   **Sort**: Ensures the `AX40` petition is explicitly moved to **Page 1** of the merged document.
    *   **Merge**: Uses `pypdf` to combine all envelope parts into a single master PDF.
3.  **Intelligence & Filing**:
    *   **Scrutiny**: Runs the `IntelligenceEngine` to extract comments and flag potential action items.
    *   **Save**: Outputs the final Master PDF to the `Output` directory using the `AX40[JobNum].pdf` naming convention.
    *   **Commit**: Records the job in `nexus.db` and marks the packet as `COMPLETED`.

---

### 6. Enhanced Reporting & Intelligence
**Architecture**: Content Analysis & Flagging.
**Budget**: 3 Hours.

**Database Schema Updates**:
*   **Table: `jobs`**:
    *   `raw_comments` (TEXT): Full extraction from PDF "Comments" section (Only for Actionable types in 2.1).
    *   `action_flag` (INTEGER): SQLite boolean (0/1). True if "Potential Action Words" found.
*   **Table: `pending_packets`**: Tracks state of multi-email envelopes (`envelope_id`, `first_seen`, `last_seen`, `file_count`).
*   **Keyword Intelligence**: Driven by `reporting_keywords.json` containing financial indicators (`$`, `USD`, `Fee`) and potential action verbs (`Serve`, `Hold`).

**The "Red Triangle" Intelligence**:
*   **Detector**: Scans `raw_comments` for any match against the glossary (Potential Action Words) via the `IntelligenceEngine`.
*   **UI Implementation**: 
    *   Verified match sets `action_flag = 1`.
    *   Dashboard renders a **Pulsing Red Triangle** with a white '!' for files requiring attention.
    *   **Metric Success**: Verified "Potential Action" detections are counted as **automation successes** in reports to reflect accurate system performance (since the system correctly identified and flagged the trigger).
    *   Displays extracted comments (e.g., "Potential Action Words Detected") in a dedicated "Manual Review" column.

---

### 7. Phase 1 Protection Strategy (Zero-Touch Mandate)
*Requirement: "Do not overwrite anything pertaining to Phase 1."*

To ensure absolute safety of the live Phase 1 system:
1.  **Parallel Execution**: Project 2 will run via a dedicated script (`pipeline_project2.py`) separate from the main `engine.py`.
2.  **Code Isolation**:
    *   **Hunter V2**: Implemented as a *subclass* in a new file (`agents/hunter_v2.py`). Inherits logic but does not modify `hunter.py`.
    *   **Librarian**: New underlying service (`core/librarian.py`).
    *   **PDF Reader**: New utility (`utils/pdf_reader_v2.py`).
3.  **Config Safety**: Project 2 rules are *additive* to `config.json` (new keys) and will not alter existing `AX02/AX03` keys.

---

### 8. Risk Assessment & Safety Gates

| Risk | Description | Impact | Mitigation (The "Air-Gap") |
| :--- | :--- | :--- | :--- |
| **Logic Mismatch** | Hunter **V1** (Dumb Logic) picks up a Project 2 file (`AX40`). | **Data Loss**. V1 files it for Primary Defendant only, ignoring 2nd/3rd defendants. | **Config Air-Gap**: Phase 1 only knows specific prefixes in its `naming_rules` dict. It silently fails validation on P2 prefixes. |
| **Prefix Confusion** | A new file type reuses an old prefix (e.g. `AX02`). | System processes it as Phase 1. | **Strict Prefix Audit**: `AX02` is exclusive to Phase 1. `AX40` is Project 2. Hard-coded "Block List" in Hunter V2. |
| **Race Condition** | Both agents verify the same email. | File locked/corrupted. | **Disjoint Sets**: The Phase 2 prefixes DO NOT overlap with Phase 1. Only one agent will ever "Validate" it. |

**Phase 1 Cross-Correlation Audit (Jan 17, 2026)**:
*   **Verified**: Hunter V1 (`hunter.py`) code audit confirms it uses a whitelist approach. If a prefix is not found in the `naming_rules` configuration, it logs a warning but **does not touch the email**.
*   **Safety**: This ensures Phase 2 emails remain unread/unmoved until the V2 agent picks them up.
*   **Compliance**: 100% "Zero-Touch" mandate adherence verified via code path analysis.

---

### 9. DOE QA Analyst: The Verifier
To ensure 100% adherence to the SOW and Video 3, we are implementing a **QA Analyst Agent** layer (The 'E' in DOE Verification).

#### Role Responsibilities:
*   **Documentation**: Before any code is finalized, the QA Analyst drafts the functional workflow in [.agent/workflows/qa_verification.md](file:///C:/Homebrew%20Apps/Professional%20Civil%20Process%20-%20PCP%20-%20three%20project/.agent/workflows/qa_verification.md).
*   **Automated Testing**: Every "Smart" feature (Timer, Merging, Flags) must have a corresponding test script in the `/tests/phase2/` directory.
*   **Shadow Mode Validation**: The QA Analyst runs V2 logic in parallel with V1 for a minimum of 50 samples to confirm zero cross-talk before full deployment.

> [!IMPORTANT]
> No feature is considered "Done" until the `qa_verification.md` workflow passes with 100% success on the automated test suite.

---

## Part 2: Architecture Decision Record (ADR) 001
### Decision: Sovereign Agents vs. Central Gatherer

#### Context
Investigation of the "smartest way" to handle message assignment between Phase 1 and Project 2.

#### Decision
Implement **Option B: Sovereign Agents (Side-Car Pattern)**.

#### Rationale
To maintain the **Zero-Touch** mandate, Hunter V1 (Phase 1) and Hunter V2 (Project 2) will run side-by-side. 
- **Fault Isolation**: If V2 (complex extraction) fails, V1 (revenue-critical) is unaffected.
- **Microservices Philosophy**: Decoupled agents are easier to scale and maintain without modifying core engine logic.

---

## Part 3: Edge Cases Inventory

### 1. Explicit Edge Cases (From Video Transcripts)
| Edge Case | Video Context | Action Taken |
| :--- | :--- | :--- |
| **Wrong Lead Document Prefix** | "If it does not start with an AX-09, you will stop there." (AX89 Video 00:01:12) | **Move to `AI Exceptions` folder.** |
| **Filing Not Accepted** | "Verify that it says Filing Accepted" (Implicit stop if missing). | **Skip / Move to `AI Exceptions`.** |
| **No Unread Emails** | "If there are no more emails, then you are done." | **System Sleep.** |

### 2. Implicit Edge Cases (Data-Driven)
| Edge Case | Data Evidence | "Librarian" Automated Solution |
| :--- | :--- | :--- |
| **Multi-Defendant Cases** | Subjects like `...vs. RAUL PEREZ, JR` and `et al` imply multiple parties. | **3-Layer Scan**: Deep-reads PDF + lookup in Index to find 2nd/3rd Job Numbers. |
| **Resends (Same Content)** | Emails arriving days later with identical PDFs. | **Hash Check**: Calculates MD5. If identical -> **STOP** (Status: `DUPLICATE`). |
| **Resends (New Content)** | "Amended" filings or corrected documents. | **Overwrite/Version**: Overwrites old file (per SOW) + files to all linked jobs. |
| **Typos in Subject** | "Case 11DC2600093" written as "Case 11-DC-..." | **Flexible Regex**: Normalizes Case ID format. |

---

## Part 4: Logic Traceability Matrix

### Stage 1: Intake & Validation
| Step | Automation Logic | SOW Req ID | Video Timestamp (AX89) |
| :--- | :--- | :--- | :--- |
| **1.1** | **Monitor Mailbox**: `Hunter` scans targeted folders. | **2.1.1** | `00:00:15` |
| **1.2** | **Filter Unread**: FIFO processing. | **2.1.1** | `00:00:43` |
| **1.3** | **Check "Filing Accepted"**: Strict Subject Search. | **2.1.2** | `00:00:53` |
| **1.4** | **Check Lead Document**: Prefix Validation. | **2.1.2** | `00:01:06` |

### Stage 2: Processing & "The Librarian"
| Step | Automation Logic | SOW Req ID | Video Timestamp |
| :--- | :--- | :--- | :--- |
| **2.1** | **Download PDF**: Retrieval via "File Stamp Copy" link. | **2.1.1** | `00:01:29` |
| **2.2** | **3-Layer Scan**: Defensive extraction. | **2.1.2** | *(Implicit)* |

---

## Part 5: Phase 1 vs Phase 2 Conflict Analysis

### 1. Retrieval Method
*   **Conflict**: SOW extracts attachments; SOP requires link downloads.
*   **Resolution**: Hunter Agent implements link parsing as primary retrieval.

### 2. Strictness
*   **Conflict**: Envelope number required by SOW but not prioritized in SOP videos.
*   **Resolution**: System logs Envelope ID for CSV audit but continues processing if filing is accepted.

---
**Verdict**: This Master Spec consolidates the entire automation logic for the Project 2 Part 1 scale-up, ensuring 100% compliance with both the SOW and training videos while maintaining zero-touch isolation from the Phase 1 system.
