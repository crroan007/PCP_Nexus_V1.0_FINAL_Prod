# PCP Nexus: Architecture & System Design (DOE Framework)

The PCP Nexus platform follows the **Directive, Orchestration, Execution (DOE)** framework to ensure modularity, transactional integrity, and "Zero Data Loss" performance.

---

## 1. Architectural Philosophy: Sovereign Agents
The system is built on a **Sovereign Agent (Side-Car) Pattern**. Independent agents (Phase 1 Hunter vs. Phase 2 HunterV2) monitor the same Outlook folders using strict prefix whitelisting.
- **Decoupling**: Faults in Phase 2 (OCR/Aggregation) do not impact high-revenue Phase 1 Affidavit flows.
- **Isolation**: Agents are stateless workers that can be scaled or restarted without losing overall system state.

---

## 2. The DOE Framework

### 2.1 Directives (State & Rules)
- **Nexus DB (`nexus.db`)**: Central authority for job state and indices. Uses **WAL (Write-Ahead Logging)** mode for high-concurrency multi-lane access.
- **Config (`config.json`)**: Parameters for keywords, retention, and output paths. Dynamically resolved via `app_paths.py`.

### 2.2 Orchestration (Coordination)
- **`JobManager`**: Handles **Distributed Locking** via `locked_by` and `locked_at` columns. Includes an automated **Zombie Cleanup** (stale lock release) that triggers every 60 minutes or on startup.
- **`OrchestratorEngine`**: Manages agent lifecycles, spawns workers, and performs **Startup Reconciliation** to recover jobs stuck in `MOVING` status from interrupted runs.

### 2.3 Execution (stateless Workers)
- **Intake**: Multi-mode `Hunter` services for diverse document types.
- **Auditor**: Multi-lane classification and OCR verification.
- **Clerk**: Final archival, renaming, and system cleanup.

---

## 3. Architecture Decision Records (ADR Collection)

### ADR 001: Sovereign Agents Side-Car Pattern
**Decision**: Independent agents for Phase 1 and Phase 2.
**Rationale**: Adheres to the "Zero-Touch" mandate for Phase 1. Ensures critical affidavit processing is never blocked by high-latency Phase 2 link-downloads.

### ADR 002: High-Volume Batch Ingestion
**Decision**: Increased `HunterV2` scan limit from 50 to **600** items.
**Rationale**: In high-volume stress tests (e.g., 575 emails), a small batch would get stuck on recently processed/tagged items and never reach the remaining backlog.

### ADR 003: Sequential Per-Envelope Processing
**Decision**: Abandoned "Batch Ingest -> 20m Wait -> Aggregate" for a **Sequential Atomic** model.
**Rationale**: 
- **Real-Time Feedback**: Jobs appear on the dashboard as they are processed, rather than in one giant burst after a wait.
- **Improved Stability**: Eliminates race conditions between ingestion and separate aggregator tasks.
- **MAPI Reliability**: Maintains a stable COM context during the entire lifecycle of a specific envelope.

---

## 4. Multi-Lane Parallel Execution (The 6-Thread Model)
To maximize throughput and maintain responsiveness, the `OrchestratorEngine` spawns six functional threads:
1. **Engine**: Core supervisor, managing agent heartbeats and thread health.
2. **Hunter**: Primary email monitor and document downloader (Phase 1 & 2).
3. **Auditor**: Handles OCR verification and document integrity checks.
4. **Clerk**: Orchestrates archival, final renaming, and move to SharePoint.
5. **Reporter**: Generates the HTML Dashboard and processes scheduled email reports.
6. **BackupService**: Manages periodic WAL-safe database redundancy and rotation.

### Concurrent Performance (WAL Mode)
SQLite is configured in **Write-Ahead Logging (WAL)** mode. This permits concurrent reads while a write is in progress, preventing "Database is locked" errors during high-volume bursts.

---

## 5. Resilience & Security Services

### 5.1 Backup Service
Independent of the processing loop, the `BackupService` performs naive copies of `nexus.db` every 30 minutes to `ProgramData\PCP-Automation\Backups`. It enforces a 10-backup rotation to prevent disk exhaustion.

### 5.2 Tamper Guard
Active during system initialization, the `TamperGuard` monitors for debugger attachment or unauthorized environment manipulation (e.g., settrace interference), sending alerts via telemetry if a breach is detected.

### 5.3 Single-Instance Lock
A system-wide MUTEX (`Global\PCP_Nexus_Singleton`) prevents multiple engines from accessing the same database or Outlook inbox simultaneously, avoiding index corruption.
