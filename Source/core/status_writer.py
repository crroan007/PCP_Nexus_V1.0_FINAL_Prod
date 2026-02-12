"""
Engine Status Writer — Atomic JSON status file for live UI visibility.

Writes to: C:\ProgramData\PCP-Automation\data\engine_status.json
Read by: TK app footer, Dashboard banner, HealthService watchdog
"""
import json
import os
import time
import datetime
import tempfile
from core import app_paths


class StatusWriter:
    """Thread-safe, atomic JSON status writer."""
    
    def __init__(self):
        self._path = str(app_paths.data_dir() / "engine_status.json")
        self._state = "STOPPED"
        self._cycle_start = None
        self._start_time = None
        self._p1_jobs = 0
        self._p2_packets = 0
        self._last_error = None
        
    @property
    def path(self):
        return self._path
    
    def set_state(self, state: str):
        """Set engine state: RUNNING, STOPPED, ERROR, STALLED, IDLE"""
        self._state = state
        if state == "RUNNING":
            self._start_time = self._start_time or datetime.datetime.now()
        self._write({
            "state": state,
            "phase": "",
            "activity": state.capitalize(),
            "progress": "",
            "current_envelope": "",
        })
        
    def cycle_start(self):
        """Mark the beginning of a processing cycle."""
        self._cycle_start = datetime.datetime.now()
        self._p1_jobs = 0
        self._p2_packets = 0
        
    def update(self, phase: str, activity: str, progress: str = "", envelope: str = ""):
        """Update current processing status."""
        self._write({
            "state": "RUNNING",
            "phase": phase,
            "activity": activity,
            "progress": progress,
            "current_envelope": envelope,
        })
    
    def increment_p1(self):
        self._p1_jobs += 1
        
    def increment_p2(self):
        self._p2_packets += 1
        
    def set_error(self, error_msg: str):
        self._last_error = error_msg
        self._state = "ERROR"
        self._write({
            "state": "ERROR",
            "phase": "",
            "activity": f"Error: {error_msg[:100]}",
            "progress": "",
            "current_envelope": "",
        })

    def _write(self, fields: dict):
        """Atomic write — temp file + rename to prevent partial reads."""
        now = datetime.datetime.now()
        
        data = {
            "state": fields.get("state", self._state),
            "last_heartbeat": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "phase": fields.get("phase", ""),
            "activity": fields.get("activity", ""),
            "progress": fields.get("progress", ""),
            "current_envelope": fields.get("current_envelope", ""),
            "cycle_start": self._cycle_start.strftime("%Y-%m-%dT%H:%M:%S") if self._cycle_start else None,
            "p1_jobs_this_cycle": self._p1_jobs,
            "p2_packets_this_cycle": self._p2_packets,
            "last_error": self._last_error,
            "uptime_minutes": round((now - self._start_time).total_seconds() / 60, 1) if self._start_time else 0,
        }
        
        try:
            dir_path = os.path.dirname(self._path)
            os.makedirs(dir_path, exist_ok=True)
            
            # Atomic: write to temp, then rename
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, indent=2)
                # On Windows, can't rename over existing — remove first
                if os.path.exists(self._path):
                    os.remove(self._path)
                os.rename(tmp_path, self._path)
            except Exception:
                # Cleanup temp file on failure
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            pass  # Status file is non-critical — never crash the engine
    
    @staticmethod
    def read(path=None):
        """Read current status. Returns dict or None."""
        if path is None:
            path = str(app_paths.data_dir() / "engine_status.json")
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return None


# Singleton
status_writer = StatusWriter()
