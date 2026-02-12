# PCP Document Automation: System Overview

## 1. Core Purpose
The PCP Document Automation System is a high-performance Windows platform designed to automate the extraction, validation, and processing of legal documents from Microsoft Outlook mailboxes. It eliminates manual downloads, standardizes document naming based on internal PCP Job Numbers, and provides a clear audit trail via daily manifests and a centralized job manager (`nexus.db`).

## 2. Roadmap & Version History

### Phase 1: e-Affidavits (V1.9)
- **Status**: PRODUCTION.
- **Scope**: Link-based ingestion for AX42, AX43, and AX47 documents. Implemented standard prefix transformations.
- **Milestone**: Successfully completed unattended regression testing for Batches 1-3 (358 jobs). Achieved 97% pass rate for Batch 3 (AX47) via high-resolution OCR fallback.

### Phase 2: e-Filing & Multi-Defendant (V2.3 → V4.3)
- **Status**: **DEDUP FIX DEPLOYED — LIVE TESTING**.
- **Scope**: Multi-document aggregation, Sequential Processing (ADR 003), and "Potential Action" keyword flagging.
- **Golden Run Result**: Successfully completed the **575-email stress test** (Mega-Ralph Mode) in Jan 2026. Verified 100% classification accuracy.
- **Critical Fix (Feb 11, 2026)**: Fixed N× page duplication caused by downloading the same Tyler multi-doc page from each notification email. Root cause: each envelope has N emails with different Proofpoint-wrapped URLs pointing to the same Tyler page. Fix: first-email-only download + basename dedup safety net.
- **Prefix Whitelist (Feb 11, v4.3.2)**: Tyler multi-doc pages can list documents from multiple phases. Added a Phase 2 prefix whitelist — only AX40/AXPB/AXPE/AXPM/AXPL/AXPA are downloaded. Non-Phase-2 docs (AX09, AX06, etc.) are now skipped.
- **Business Rules (Per Brandy)**: 1× AX40 (lead), 1× AXPB, multiple AXPE (separate exhibits A/B/C). Merge order: AX40 → AXPB → AXPE(s) → AXPM → CL (excluded).
- **Verification Reporter**: Rewritten with actual PDF page counts (PyPDF2), source doc enumeration, per-file details with clickable links.
- **Build Fixes**: Fixed Tcl/Tk bundling, `pythoncom` module management, unified path resolution.

---

## 3. Technical Documentation Map

### Core Architecture & Implementation
- [**Architecture & System Design**](architecture/system_design.md): DOE Framework, Parallel Lanes, and ADR Collection.
- [**Implementation Guide**](implementation/core_agent_implementation.md): Core agent logic, path management, and threading rules.
- [**Dashboard & Failure Analytics**](implementation/dashboard_analytics.md): Real-time monitoring and success rate formulas.

### Operations & Governance
- [**IT Deployment & Configuration**](deployment/it_deployment_guide.md): Hardware specs, security whitelisting, and MAPI setup.
- [**Build & Distribution**](implementation/build_and_distribution_guide.md): PyInstaller spec optimization and installer creation.
- [**Policy & Logic Manual**](governance/policy_and_logic_manual.md): Integrated prefix transformation and defendant identity rules.
- [**Operations Manual**](operations/operations_manual.md): Project handover, SOP video references, and source backup strategy.

### Testing & Quality Assurance
- [**Testing & Verification Authority**](testing/testing_and_verification.md): Gold Run results, Live Fire simulations, and Case ID normalizing.
- [**Project 2 Master PRD**](research/project_2_part1_prd.md): Original functional specification for multi-defendant logic.

---

## 4. Key Components
- **Hunter Agent**: The intake service. Monitors Outlook, parses email bodies, and handles initial file acquisition.
- **Auditor Agent**: Exception handler and classifier. Routes jobs into Merge or Split queues.
- **OCRSplitter Agent**: Uses deep OCR to segment "Batch Petitions" into individual case files.
- **Clerk/Scribe Agents**: Archival and reporting services. Handles FilePro integration (Code 26).
- **Job Manager**: Handles state persistence and distributed locking for parallel services.
- **Reporting Suite**: Includes a 60-second live dashboard and automated email reporting.

## 5. Distribution Model
- **Format**: Standalone `.exe` (PyInstaller) packaged in an Inno Setup installer.
- **Dependency Bundling**: Tcl/Tk, EasyOCR models, and `pywin32` runtime hooks are explicitly included to support "Zero-Install" deployment.
- **Elevation**: Application supports `Verb RunAs` for testing in restricted environments.

---

## 6. Live Operation Status (Feb 2026 Rollout)

The system is currently in **Stage 1 Pilot** in the production environment. 

### 6.1 Recent Enhancements (Phase 8-11)

| Phase | Feature | Key Implementation |
|-------|---------|-------------------|
| **8** | Real-Time Export | Live CSV (8 cols) + Excel (14 cols) with auto-export on job completion |
| **9** | Email Auto-Detection | `GetActiveObject` COM lookup populates Outlook account/folders on startup |
| **10** | Startup Hardening | Auto-kill prior instances, mandatory admin elevation via UAC |
| **11** | Phase 2 Dedup + Verification | First-email-only download, basename dedup, rewritten verification reporter with page counts |
| **11** | Live Status Monitoring | Real-time engine status via `engine_status.json`, TK footer, dashboard banner, stall detection |
| **12** | Phase 2 Prefix Whitelist (v4.3.2) | Tyler multi-doc pages only download Phase 2 actionable prefixes; non-Phase-2 docs (AX09, AX06) skipped |

### 6.2 Export Format Details
- **Lead Document**: Full filename from email (e.g., `AX02A26101444.PDF`)
- **Orig_Prefix**: Extracted AXnn code via regex `(AX\d{2})` from lead document
- **Output Location**: `C:\ProgramData\PCP-Automation\Output\pcp_phase1_YYYYMMDD.csv`, `pcp_phase2_YYYYMMDD.csv`, and `.xlsx`

### 6.3 Operational Caveats
- **Admin Required**: App auto-elevates via UAC on launch
- **Outlook Requirement**: Outlook Classic must be running before app launch
- **Silent Processing**: All PowerShell windows suppressed (CREATE_NO_WINDOW)
- **Instance Management**: Prior instances auto-terminated on new launch
