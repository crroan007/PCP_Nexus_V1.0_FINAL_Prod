#!/usr/bin/env python
"""
PCP Nexus — Test Reset Script (v4.3.3)
Cleanly resets ALL state for a fresh test run:
  1. Kills any running PCP python processes
  2. Clears DB tables (preserves schema)
  3. Clears Staging
  4. Clears Output CSVs + Documents CSV folders
  5. Clears Dashboard
  6. Clears pending packets
  NOTE: Outlook tag reset is done manually by the user.

Usage:
    python -B reset_for_testing.py
"""

import os
import sys
import glob
import shutil
import sqlite3
import subprocess
import time

# ── Paths ──────────────────────────────────────────────
PCP_DATA     = r"C:\ProgramData\PCP-Automation"
DB_PATHS     = [
    os.path.join(PCP_DATA, "data", "nexus.db"),           # Primary (app_paths.db_path())
    os.path.join(PCP_DATA, "nexus.db"),                    # Legacy root-level
    os.path.join(PCP_DATA, "pcp_automation.db"),           # Legacy name
    os.path.join(PCP_DATA, "data", "pcp_jobs.db"),         # Legacy name
]
STAGING_DIR  = os.path.join(PCP_DATA, "Staging")
OUTPUT_DIR   = os.path.join(PCP_DATA, "Output")
DASHBOARD_DIR= os.path.join(PCP_DATA, "Dashboard")
LOGS_DIR     = os.path.join(PCP_DATA, "Logs")
PACKETS_FILE = os.path.join(PCP_DATA, "pending_packets.json")

# Documents CSV folders (from config)
DOCUMENTS_CSV_DIRS = [
    r"C:\Users\Kado\Documents\phase 1 csv",
    r"C:\Users\Kado\Documents\phase 2 csv",
    r"C:\Users\Kado\Documents\phase 1 csv archive",
    r"C:\Users\Kado\Documents\phase 2 csv archive",
]

# DB tables to clear (order matters for FK constraints if any)
DB_TABLES = ["jobs", "workflow_log", "pending_packets"]


def step(msg):
    print(f"  ✓ {msg}")


def warn(msg):
    print(f"  ⚠ {msg}")


def kill_python_processes():
    """Kill all python processes except this one."""
    my_pid = os.getpid()
    try:
        # Get all python PIDs, kill everything except this script
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "processid"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid != my_pid:
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], 
                                     capture_output=True, timeout=5)
                    except Exception:
                        pass
        step("Killed running Python processes")
    except Exception as e:
        warn(f"Process kill: {e}")
    time.sleep(1)


def clear_db():
    """Clear all rows from the primary DB, preserving schema. Also delete legacy DBs."""
    primary_db = DB_PATHS[0]  # data/nexus.db
    
    # 1. Clear the primary DB (preserve schema for app startup)
    if os.path.exists(primary_db):
        try:
            conn = sqlite3.connect(primary_db)
            c = conn.cursor()
            # Get all tables
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in c.fetchall()]
            for table in tables:
                if table.startswith("sqlite_"): continue
                try:
                    c.execute(f"DELETE FROM {table}")
                    step(f"Cleared table '{table}'")
                except Exception:
                    pass
            # Reset autoincrement counters
            try:
                c.execute("DELETE FROM sqlite_sequence")
            except Exception:
                pass
            conn.commit()
            conn.close()
            step(f"Database wiped (schema preserved): {primary_db}")
        except Exception as e:
            warn(f"Could not clear primary DB: {e}")
    else:
        step("No primary database found (will be created on launch)")
    
    # 2. Delete any legacy/secondary DB files entirely
    for db_path in DB_PATHS[1:]:
        for suffix in ["", "-wal", "-shm", "-journal"]:
            fp = db_path + suffix
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                    step(f"Deleted legacy: {fp}")
                except Exception as e:
                    warn(f"Could not delete {fp}: {e}")


def clear_directory(dir_path, label=None, pattern="*"):
    """Remove all files in a directory, keeping the directory itself."""
    label = label or os.path.basename(dir_path)
    if not os.path.exists(dir_path):
        warn(f"{label} directory not found: {dir_path}")
        return
    
    count = 0
    for item in os.listdir(dir_path):
        fp = os.path.join(dir_path, item)
        try:
            if os.path.isfile(fp):
                os.remove(fp)
                count += 1
            elif os.path.isdir(fp):
                shutil.rmtree(fp)
                count += 1
        except Exception as e:
            warn(f"  Could not remove {item}: {e}")
    
    step(f"Cleared {label} ({count} items)")


def clear_dashboard():
    """Remove dashboard HTML and verification files, keep assets."""
    if not os.path.exists(DASHBOARD_DIR):
        return
    
    for f in glob.glob(os.path.join(DASHBOARD_DIR, "*.html")):
        try:
            os.remove(f)
        except Exception:
            pass
    step("Cleared dashboard HTML")


def clear_csvs():
    """Clear Output CSVs and Documents CSV folders."""
    # Local output CSVs
    if os.path.exists(OUTPUT_DIR):
        for f in glob.glob(os.path.join(OUTPUT_DIR, "*.csv")) + glob.glob(os.path.join(OUTPUT_DIR, "*.xlsx")):
            try:
                os.remove(f)
            except Exception:
                pass
        step("Cleared Output CSVs")
    
    # Documents folders
    for folder in DOCUMENTS_CSV_DIRS:
        if os.path.exists(folder):
            count = 0
            for f in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, f))
                    count += 1
                except Exception:
                    pass
            if count:
                step(f"Cleared {os.path.basename(folder)} ({count} files)")


def clear_pending_packets():
    """Remove the pending_packets.json file."""
    if os.path.exists(PACKETS_FILE):
        try:
            os.remove(PACKETS_FILE)
            step("Cleared pending_packets.json")
        except Exception as e:
            warn(f"Could not remove packets file: {e}")





def clear_staging():
    """Clear Staging directory."""
    clear_directory(STAGING_DIR, "Staging")


def main():
    print("=" * 55)
    print("  PCP Nexus — FULL TEST RESET")
    print("=" * 55)
    print()
    
    print("[1/6] Killing Python processes...")
    kill_python_processes()
    
    print("[2/6] Clearing database...")
    clear_db()
    
    print("[3/6] Clearing staging files...")
    clear_staging()
    
    print("[4/6] Clearing CSVs (local + Documents)...")
    clear_csvs()
    
    print("[5/6] Clearing dashboard...")
    clear_dashboard()
    
    print("[6/6] Clearing pending packets...")
    clear_pending_packets()
    
    print()
    print("=" * 55)
    print("  RESET COMPLETE — Ready for clean test run")
    print("  Remember: Reset Outlook tags manually!")
    print("  Launch with: python -B main.py")
    print("=" * 55)


if __name__ == "__main__":
    main()
