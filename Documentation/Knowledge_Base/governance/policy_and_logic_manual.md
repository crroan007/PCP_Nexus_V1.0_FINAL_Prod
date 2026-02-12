# PCP Nexus: Policy, Logic, and Governance Manual (Consolidated)

This document provides a comprehensive reference for the rules, policies, and strategic decisions governing the PCP Nexus automation system.

---

## 1. Document Processing Rules (The Two Workflows)

PCP Nexus operates using two distinct logic workflows based on document complexity and archival requirements.

### 1.1 Phase 1 Workflow (Transactional/Affidavit)
- **Objective**: Immediate processing and renaming of individual Affidavits/Motions.
- **Identification**: Parsed from the "Lead Document" name in Tyler emails or the first 4 chars of the attachment (`AX02`, `AX03`, `AX07`, `AX09`).
- **Logic Path**: 
    1. **Prefix Transform**: Source prefix mapped to Target prefix (e.g., `AX02` -> `AX42`) using `naming_rules`.
    2. **Job Extraction**: Captures the PCP Job Number (e.g., `A25B...`).
    3. **No Aggregation**: Each "Accepted" email results in one discrete output file.
- **Naming Convention**: `{TargetPrefix}{JobNumber}.pdf`

### 1.2 Phase 2 Workflow (Stateful/Petition)
- **Objective**: Aggregating "Split Petitions" and multi-document e-filings into a single packet.
- **Identification**: Documents marked as Petitions (`AX40`) or supplementary parts (`AXPB`, `AXPE`, `AXPL`, `AXPM`).
- **Logic Path**: 
    1. **Envelope Grouping**: All emails sharing the same **Tyler Envelope ID** are treated as a single "Stateful Packet".
    2. **Wait Window**: The system allows a 20-minute window from the first observed part to ensure all asynchronous emails (split parts) have arrived.
    3. **Packet Merging**: Merges all downloaded parts into one PDF.
    4. **Lead Doc Ordering**: The Petition (`AX40`) is programmatically moved to the first page.
- **Naming Convention**: `AX40{EnvelopeID}.pdf`

### 1.3 Workflow Comparison Matrix
| Feature | Phase 1 (Transactional) | Phase 2 (Stateful) |
| :--- | :--- | :--- |
| **Logic Mode** | Stateless (Immediate Trigger) | Stateful (Packet Aggregation) |
| **Primary Trigger**| Affidavit/Motion Prefix (`AX02/03/07/09`) | Petition Prefix (`AX40`) |
| **Wait Window** | Zero (Process on arrival) | 20 Minutes (Collect split parts) |
| **Naming Rule** | `{TargetPrefix}{JobNumber}.pdf` | `AX40{EnvelopeID}.pdf` |
| **Aggregation** | No (1 File : 1 Output) | Yes (Merge multiple parts) |
| **Archival Goal** | Production Archive (Standard) | Document Review (Audit) |

### 1.4 Cross-Phase Prefix Handling (Project 2 Aggregate)
In Phase 2 (Split Petition) processing, documents that originally carried Phase 1 prefixes (e.g., `AX09` - JP Server Motion) might be part of a larger e-filing envelope. 
- **Rule**: If the envelope is identified as a Phase 2 "Filing Accepted" case, the lead document's originally detected prefix (e.g., `AX09`) is mapped to the Phase 2 target prefix (**`AX40`**) to maintain aggregate filing standards.

---

## 2. Multi-Defendant & Split Petition Policy

### 2.1 Split Petition (Explicit SOP)
A scenario where a single electronic "Envelope" contains multiple distinct documents (e.g., AX40, AXPE, AXPM) sent as separate emails.
- **Action**: Merge all parts into one packet.
- **Lead Rule**: `AX40` (Petition) MUST be the first document in the packet.

### 2.2 Multi-Defendant (Implicit Requirement)
A scenario where a single envelope might apply to multiple defendants/jobs.
- **Action**: Treated as Advanced Intelligence. Validates defendant name against case style and queries the **Case Index** for associated job numbers.
- **The Librarian**: Consults the `case_index` (populated from existing Job Numbers) to map Case IDs to multiple jobs.

---

## 3. Logic Traceability Matrix

| Step | Automation Logic | SOW Req ID | SOP Timing (AX89) |
| :--- | :--- | :--- | :--- |
| **1.1** | **Monitor Mailbox**: `Hunter` scans folder. | **2.1.1** | `00:00:15` |
| **1.3** | **Check "Filing Accepted"**: Regex Search. | **2.1.2** | `00:00:53` |
| **1.4** | **Check Lead Document**: Parse Body/Prefix. | **2.1.2** | `00:01:06` |
| **2.1** | **Download PDF**: Locate "File Stamp Copy". | **2.1.1** | `00:01:29` |
| **2.4** | **"The Librarian"**: Query multi-defendant index. | **1.2.3** | Automation Enhancement |
| **3.3** | **Duplicate Check**: Hash comparison. | **2.1.3** | SOW Req 110 |

---

## 4. Strategic & Architecture Reviews (CR Log)

### 4.1 Phase 2 Architecture Update (CR-001)
- **Status**: INCORPORATED (Jan 16, 2026)
- **Change**: Shifted from "Real-Time Processing" to **Stateful Packet Aggregation**.
- **Rationale**: Handle "Split Petitions" arriving asynchronously over ~20 minutes.
- **Wait Logic**: 20-minute countdown initiated on first email seen for an Envelope ID.

### 4.2 CTO Strategic Review
- **Directive**: Transition to **"Intelligent Flagging"** for review-worthy events.
- **Classification**: Failed items categorized into Tiered Failure Classification (P0-P3).
- **Metric Success**: Correct identification of "Potential Action Words" (Rush, Fee, etc.) counts as an **Automated Success**.

---

## 5. Compliance & Dashboard Standards
- **Flagged Items**: Designated as **"Automated Insights"** (Red Triangle).
- **Silent Skip**: Internal skip logs for `AX69`, `AX81`, `CL` prevent dashboard clutter.
- **Default Action**: Ambiguity triggers move to `AI Exceptions` rather than incorrect processing.

---

## 6. Logic Fail-Safes (Feb 4 Recovery)
1. **Naming Fallback**: If a Phase 1 document lacks a Job Number in the configuration or email metadata, the system attempts to extract it from the attachment filename using regex/parsing. It identifies the "Lead Prefix" and strips it from the filename to isolate the numeric Job ID before appending the target prefix.
2. **Config Resilience (Dual-Schema)**: The system implements a fallback check for configuration keys. It prioritizes the new flat `naming_rules` map at the root of the config, but retains compatibility by checking the legacy `Phases.Phase1.RenameMap` if the primary key is missing or empty.
3. **Prefix Hardening**: The system maintains a `SOURCE_PFX` guard list. If an attachment name doesn't match a known prefix but the Outlook folder/metadata indicates a Phase 1 doc, the system overrides the attachment's raw prefix with the metadata-intended code (e.g., forcing an `AX42` target for a non-standardized `A25B` input).

---

## 7. Audit & Compliance Reporting

### 7.1 Real-Time Auditing (The SharePoint Mirror)
The system maintains a real-time, high-fidelity audit trail for every document processed. This log is stored as a CSV in local sync folders that push to SharePoint.

- **Authoritative Path**: `C:\ProgramData\PCP-Automation\Logs\SharePoint_Mirror\PCP_Log_[NodeID]_[Date].csv`
- **Cadence**: Records are appended immediately upon completion of ingestion OR archiving.

### 7.2 The 30-Column Schema (Intelligence & Chain of Custody)
The audit log has been expanded to 30 columns to support "Accepted Comments" extraction, automated "Action Item" flagging, and full case metadata.

- **Action Flagging Logic**: If the "Accepted Comments" field in a Tyler notification contains any keywords from the Action Phrase Library (e.g., "Rush", "Fee"), the `Action_Flag` is set to **Yes**. If a comment exists but contains no keywords, the flag is **No**. If no comment exists, the flag is **No** (or blank depending on the specific implementation version).
- **Key Identifiers**: The log now explicitly captures **Case Number**, **Court**, and **Case Style** for better legal correlation.

*For the full list of 30 columns and detailed intelligence logic, refer to the [Intelligence & Auditing Specification](../implementation/intelligence_and_auditing.md).*

---

## 8. Workflow Logic Recap (Feb 4)

- **Phase 1**: Triggered by `AX02/03/07/09`. Naming: `{TargetPrefix}{JobID}.pdf`.
- **Phase 2**: Triggered by `AX40` or multi-part envelopes. Naming: `AX40{EnvelopeID}.pdf`.
- **Config Resilience**: The system prioritizes the root `naming_rules` map but retains a fallback to the nested `Phases.Phase1.RenameMap` structure.
- **Prefix Guard**: Hardened detection ensures non-standardized filenames (e.g., `A25B...`) are correctly mapped using email metadata.
