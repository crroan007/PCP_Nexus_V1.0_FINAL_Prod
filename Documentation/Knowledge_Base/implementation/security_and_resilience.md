# PCP Nexus: Security & Resilience Implementation

This document details the security layers and resilience mechanisms integrated into the PCP Nexus platform to prevent tampering and ensure stable execution.

---

## 1. Tamper Guard System

The `TamperGuard` module provides active monitoring against reverse engineering and debugging attempts.

### 1.1 Debugger Detection
- **Mechanism**: Utilizes `ctypes` to call `kernel32.IsDebuggerPresent()`.
- **Frequency**: Runs in a background "Canary" thread, checking the process state every 5 seconds.
- **Reaction**: If a debugger is detected:
    1. A critical security alert is logged locally (the "Black Box").
    2. An immediate "SOS" email is attempted to the security administrator.
    3. The application displays a "Security Violation" message box and perform a hard exit (`os._exit(1)`).

### 1.2 SOS Alerting (Immediate & Delayed)
- **Immediate Alert**: The guard attempts to send an SOS email via `core.emailer` as soon as a violation occurs.
- **Delayed Recovery**: If the machine is offline during an incident, the violation is written to a local hidden log (`core/sys_log.dat`). Upon the next successful application start, `TamperGuard` scans for this "Black Box" file and uploads any pending security incidents.

---

## 2. Process Resilience

### 2.1 Single Instance Mutex
To prevent multiple instances of the application from conflicting over Outlook folders or database file locks, `main.py` implements a Global Mutex.
- **Mutex Name**: `Global\PCP_Nexus_Singleton`.
- **Logic**: Uses `ctypes.windll.kernel32.CreateMutexW`. If `GetLastError()` returns `183` (`ERROR_ALREADY_EXISTS`), the second instance terminates immediately with a warning.

### 2.2 Database Concurrency (WAL Mode)
The `JobManager` initializes the SQLite connection with `PRAGMA journal_mode=WAL`.
- **Benefit**: Allows the Hunter, Auditor, and Clerk threads to read current job states without waiting for active write transactions to complete, significantly reducing "Database is locked" contention in multi-thread environments.

### 2.3 Atomic Status Transitions
The system uses atomic `UPDATE` queries for status transitions. 
- **Locked Reservation**: Agents reserve jobs using a `locked_by` (Node ID) and `locked_at` timestamp. 
- **Zombie Recovery**: On startup, the engine identifies jobs stuck in `IN_PROGRESS` or `MOVING` for more than 60 minutes and automatically resets them to `NEW` or `ARCHIVED` (reconciliation), ensuring no job is permanently "stuck" due to a system crash.

---

## 3. Directory & Path Resilience

### 3.1 Nested Creation Guard
The application relies on a deeply nested directory structure for staging and output (e.g., `[Phase]/[Envelope]/[Job]`).
- **Mechanism**: `app_paths.ensure_dir` uses `Path.mkdir(parents=True, exist_ok=True)`.
- **Handling Permission Denied**: If a `PermissionError` (WinError 5) occurs, it typically indicates a conflict with inheritance or a missing intermediate permission on a parent directory (like `C:\Users\[User]`). 
- **Resilience Strategy**: 
    1. **Granular Logging**: The system logs the full absolute path of the failure to identify the exact "permission ceiling".
    2. **Fallback Dir**: If `ensure_dir` fails on a secondary folder, the agent diverts the current workflow envelope to `Exceptions` to prevent data loss while allowing other threads to continue if they are using different primary paths.
