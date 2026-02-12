# PCP Nexus — Automated Document Processing System

## Overview
PCP Nexus automates legal document processing from Tyler Technologies' e-Filing system.
- **Phase 1**: Immediate download/rename/save for single-doc emails (Affidavits).
- **Phase 2**: Delayed merge/save for multi-part split petitions with intelligent document ordering.

## Current Status (Feb 11, 2026)
- **Phase 1:** ✅ FULLY OPERATIONAL — 38 PDFs, 100% pass rate
- **Phase 2:** 🔧 DEDUP FIX DEPLOYED — Live testing in progress
- **Version:** v4.3
- **Repo**: [PCP_Production-Version-Testing-v1.0-](https://github.com/crroan007/PCP_Production-Version-Testing-v1.0-)

### Recent Changes (v4.3)
- **Phase 2 Dedup Fix:** Fixed critical N× page duplication caused by downloading the same Tyler multi-doc page from each notification email. Now downloads from first email only.
- **Verification Reporter:** Rewritten with actual page counts (PyPDF2), source doc enumeration, per-file details with clickable links, and integrity checks.
- **Live Status Monitoring:** Real-time engine status (heartbeat, progress, stall detection) via `engine_status.json`.
- **Constituent Docs:** Merge metadata now includes actual source doc filenames for full audit trail.

## Installation (USB Backup)
1. Copy the `PCP_Source` folder to `C:\PCP-Nexus`.
2. Install Python 3.10+.
3. Install dependencies: `pip install -r requirements.txt`.
4. Configure `C:\ProgramData\PCP-Automation\config.json`.
5. Run via PowerShell (Admin):
   ```powershell
   cd C:\PCP-Nexus\Source
   python -B -X utf8 main.py
   ```

## Directory Structure
- `Source/` — Application code (`agents/hunter_v2.py` is the engine).
- `Source/core/` — Job manager, packet manager, verification reporter, status writer.
- `Source/tests/` — 85 unit tests (pytest).
- `Documentation/` — Logic manuals, Knowledge Base, and specs.
- `memory.md` — Session history and known issues.

## Testing
- Unit tests: `python -B -m pytest tests/ -x -q` (85 tests)
- Verification report: Dynamic in dashboard (Verification tab)
- See `memory.md` for detailed test results and known issues.
