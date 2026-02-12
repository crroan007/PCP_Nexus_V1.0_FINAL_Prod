from __future__ import annotations

import os
import uuid
from pathlib import Path

APP_DIRNAME = "PCP-Automation"


def _program_data_base() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / APP_DIRNAME


def _local_app_data_base() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_DIRNAME
    return Path.home() / "AppData" / "Local" / APP_DIRNAME


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write_probe_{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def base_dir() -> Path:
    """
    Returns the writable base directory for runtime data (config, logs, db, etc.).

    Order:
    - `PCP_DATA_DIR` env override (absolute path)
    - ProgramData if it already exists and is writable
    - LocalAppData (always preferred for non-admin installs)
    """
    override = os.environ.get("PCP_DATA_DIR")
    if override:
        return Path(override)

    program_data = _program_data_base()
    if program_data.exists() and _is_writable_dir(program_data):
        return program_data

    local_app_data = _local_app_data_base()
    if _is_writable_dir(local_app_data):
        return local_app_data

    # Last resort: user profile (should still be writable)
    return Path.home() / APP_DIRNAME


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return base_dir() / "config.json"


def logs_dir() -> Path:
    override = os.environ.get("PCP_LOGS_DIR")
    if override:
        return ensure_dir(Path(override))
    return ensure_dir(base_dir() / "Logs")


def data_dir() -> Path:
    return ensure_dir(base_dir() / "data")


def db_path() -> Path:
    return data_dir() / "nexus.db"


def staging_dir() -> Path:
    return ensure_dir(base_dir() / "Staging")


def outlook_archive_dir() -> Path:
    return ensure_dir(staging_dir() / "Outlook_Archive")


def temp_dir() -> Path:
    return ensure_dir(base_dir() / "temp")


def output_dir() -> Path:
    return ensure_dir(base_dir() / "Output")


def backups_dir() -> Path:
    return ensure_dir(base_dir() / "Backups")


def dashboard_dir() -> Path:
    return ensure_dir(base_dir() / "Dashboard")


def dashboard_report_path() -> Path:
    return dashboard_dir() / "dashboard.html"


def documents_dir() -> Path:
    """
    Best-effort path to the user's Documents folder (for human-friendly outputs).
    Falls back to the writable app base dir if Documents isn't available.
    """
    candidate = Path.home() / "Documents"
    if candidate.exists():
        return candidate
    return base_dir()


def default_user_output_root() -> Path:
    return ensure_dir(documents_dir() / "PCP_Output")


def default_phase_output_dir(phase: str) -> Path:
    """
    Default human-friendly output directories for phase processing.
    - Phase1 -> Civil
    - Phase2 -> Criminal
    """
    name = "Output"
    phase_norm = (phase or "").strip().lower()
    if phase_norm in {"phase1", "civil", "affidavits"}:
        name = "Civil"
    elif phase_norm in {"phase2", "criminal", "efiling", "project_2"}:
        name = "Criminal"
    return ensure_dir(default_user_output_root() / name)
