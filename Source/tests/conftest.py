"""
PCP Nexus Test Suite — Shared Fixtures
=======================================
Provides all common fixtures for unit, integration, and E2E tests.
"""
import pytest
import os
import sys
import sqlite3
import json
import tempfile
import shutil
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add source root to path so we can import modules
SOURCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)


# ──────────────────────────────────────────────
# Temporary Directories & Cleanup
# ──────────────────────────────────────────────

@pytest.fixture
def tmp_dir(tmp_path):
    """Provides a clean temporary directory."""
    return tmp_path


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provides a clean output directory."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def tmp_download_dir(tmp_path):
    """Provides a clean download staging directory."""
    dl = tmp_path / "downloads"
    dl.mkdir()
    return dl


# ──────────────────────────────────────────────
# Database Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Fresh SQLite database for testing."""
    db_path = str(tmp_path / "test_nexus.db")
    return db_path


@pytest.fixture
def job_mgr(tmp_db, monkeypatch):
    """JobManager instance with temporary database."""
    # Patch the DB path before importing
    monkeypatch.setattr("core.job_manager.DB_PATH", tmp_db)
    # Also need to handle the app_paths
    from core.job_manager import JobManager
    mgr = JobManager.__new__(JobManager)
    mgr.db_path = tmp_db
    mgr.hostname = "TEST_NODE"
    mgr.lock = __import__("threading").Lock()
    mgr.telemetry = MagicMock()
    mgr._init_db()
    return mgr


@pytest.fixture
def packet_mgr(tmp_db):
    """PacketManager instance with temporary database."""
    from core.packet_manager import PacketManager
    return PacketManager(db_path=tmp_db)


# ──────────────────────────────────────────────
# Configuration Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def mock_config():
    """In-memory configuration dict matching production schema."""
    return {
        "Phases": {
            "Phase1": {
                "Enabled": True,
                "Input": "C:\\Test\\Input",
                "OutputPath": "C:\\Test\\Output\\Phase1",
                "Prefixes": {
                    "Affidavit": ["AX02", "AX03", "AX07", "AX09"]
                },
                "RenameMap": {
                    "AX02": "AX42",
                    "AX03": "AX43",
                    "AX07": "AX47",
                    "AX09": "AX89"
                }
            },
            "Phase2": {
                "Enabled": True,
                "OutputPath": "C:\\Test\\Output\\Phase2",
                "AggregationMinutes": 20,
                "Prefixes": {
                    "Lead": ["AX40", "AX69"],
                    "Attachment": ["AXPE", "AXEX"],
                    "ClerkLetter": ["CL"],
                    "Correction": ["AXCR"],
                    "Ignore": ["AX81"]
                },
                "MergeOrder": ["AX40", "AX69", "AXCR", "AXPE", "AXEX"],
                "ReopenCompletedOnNewFiles": True,
                "SkipTagOnNoFiles": True
            }
        },
        "paths": {
            "output": "C:\\Test\\Output",
            "realtime_exports": "C:\\Test\\Exports"
        },
        "Phase2.ReopenCompletedOnNewFiles": True,
        "Phase2.SkipTagOnNoFiles": True
    }


@pytest.fixture
def conf_mock(mock_config):
    """Mock for secure_config.conf.get()."""
    def _get(key, default=None):
        # Navigate nested keys with dot notation
        parts = key.split(".")
        val = mock_config
        for p in parts:
            if isinstance(val, dict) and p in val:
                val = val[p]
            else:
                return default
        return val
    
    mock = MagicMock()
    mock.get = _get
    return mock


# ──────────────────────────────────────────────
# PDF Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def sample_pdf(tmp_path):
    """Creates a minimal valid PDF file with extractable text."""
    from pypdf import PdfWriter
    pdf_path = str(tmp_path / "sample.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


@pytest.fixture
def sample_pdf_factory(tmp_path):
    """Factory fixture to create multiple named PDFs."""
    created = []
    
    def _create(name, text_pages=None):
        from pypdf import PdfWriter
        pdf_path = str(tmp_path / name)
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        created.append(pdf_path)
        return pdf_path
    
    return _create


# ──────────────────────────────────────────────
# Email Body Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def sample_email_body_phase1():
    """Tyler 'Filing Accepted' email body for Phase 1."""
    return """Filing Notification
Envelope Number: 110282126
Case Number: CV-2025-001234
Court: Harris County District Court
Filing Type: eAffidavit
Date Submitted: 01/15/2025 10:30:00 AM
Date Accepted: 01/15/2025 02:45:00 PM
Lead Document: AX02A25B01085.PDF
Accepted Comments: None"""


@pytest.fixture
def sample_email_body_phase2():
    """Tyler 'Filing Accepted' email body for Phase 2 (eFiling)."""
    return """Filing Notification
Envelope Number: 110395847
Case Number: CV-2025-005678
Court: Travis County Civil Court
Filing Type: eFiling
Date Submitted: 02/01/2025 09:00:00 AM
Date Accepted: 02/01/2025 11:15:00 AM
Lead Document: AX40A25C05955.PDF
Accepted Comments: serve immediately - $500 bond required"""


# ──────────────────────────────────────────────
# Tyler HTML Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def sample_tyler_html_single():
    """Tyler landing page with single document download link."""
    return """<html><body>
    <div id="main">
        <a href="/DownloadResource.ashx?id=abc123&name=AX40A25C05955.pdf">Download Document</a>
    </div>
    </body></html>"""


@pytest.fixture
def sample_tyler_html_multi():
    """Tyler landing page with multiple document download links (Brandy's scenario)."""
    return """<html><body>
    <div id="main">
        <h2>Filing Documents</h2>
        <table>
            <tr>
                <td><a href="/DownloadResource.ashx?id=abc123&name=AX40A25C05955.pdf">AX40A25C05955.pdf</a></td>
            </tr>
            <tr>
                <td><a href="/DownloadResource.ashx?id=def456&name=AXPEA25C05955.pdf">AXPEA25C05955.pdf</a></td>
            </tr>
            <tr>
                <td><a href="/DownloadResource.ashx?id=ghi789&name=AX40A25C05955CL.pdf">AX40A25C05955CL.pdf</a></td>
            </tr>
        </table>
    </div>
    </body></html>"""


@pytest.fixture
def sample_tyler_html_expired():
    """Tyler landing page showing expired document."""
    return """<html><body>
    <div id="main">
        <span id="lblexpired">This document is no longer available for download.</span>
    </div>
    </body></html>"""


# ──────────────────────────────────────────────
# Packet / File Metadata Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def sample_packet_files(sample_pdf_factory):
    """Creates a realistic packet with Lead, Attachment, and CL files."""
    lead = sample_pdf_factory("P2_110395847_143000_0_DL_AX40.pdf")
    att = sample_pdf_factory("P2_110395847_143000_1_DL_AXPE.pdf")
    cl = sample_pdf_factory("P2_110395847_143000_2_DL_AX40.pdf")
    
    return [
        {
            'path': lead,
            'prefix': 'AX40',
            'original_name': 'AX40A25C05955.pdf',
            'doc_type': 'LEAD',
            'timestamp': datetime.now()
        },
        {
            'path': att,
            'prefix': 'AXPE',
            'original_name': 'AXPEA25C05955.pdf',
            'doc_type': 'ATTACHMENT',
            'timestamp': datetime.now()
        },
        {
            'path': cl,
            'prefix': 'AX40',
            'original_name': 'AX40A25C05955CL.pdf',
            'doc_type': 'CLERK_LETTER',
            'timestamp': datetime.now()
        }
    ]
