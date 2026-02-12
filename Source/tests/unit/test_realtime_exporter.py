"""
Test Realtime Exporter — CSV/Excel Generation
===============================================
Covers: EX-01..EX-06 from the testing plan.
"""
import pytest
import csv
import os
import sys
import json
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@pytest.fixture
def exporter(tmp_path, monkeypatch):
    """RealtimeExporter with output directed to temp dir."""
    monkeypatch.setattr("core.realtime_exporter.conf", MagicMock(
        get=lambda key, *args: str(tmp_path) if 'export' in key or 'output' in key else None
    ))
    
    from core.realtime_exporter import RealtimeExporter
    exp = RealtimeExporter.__new__(RealtimeExporter)
    exp.output_dir = str(tmp_path)
    today_str = datetime.now().strftime("%Y%m%d")
    # Phase-specific CSV paths
    exp.csv_paths = {
        "Phase1": os.path.join(str(tmp_path), f"pcp_phase1_{today_str}.csv"),
        "Phase2": os.path.join(str(tmp_path), f"pcp_phase2_{today_str}.csv"),
    }
    # Legacy compat
    exp.csv_path = exp.csv_paths["Phase1"]
    exp.excel_filename = f"pcp_activity_{today_str}.xlsx"
    exp.excel_path = os.path.join(str(tmp_path), exp.excel_filename)
    exp._ensure_csv_headers()
    return exp


class TestCSVFormat:
    """EX-01..EX-04: CSV header and row format."""

    def test_csv_header_8_columns(self, exporter):
        """EX-01: CSV header must match the v4.2 8-column spec."""
        expected = [
            "Envelope_Num", "Case_Num", "Date_Submitted", "Time_Submitted",
            "Date_Accepted", "Time_Accepted", "Lead_Document", "PCP_Job_Num"
        ]
        
        with open(exporter.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
        
        assert header == expected

    def test_csv_only_archived_status(self, exporter):
        """EX-02: Only ARCHIVED status rows are written to CSV."""
        metadata = json.dumps({
            "envelope": "12345", "case_num": "CV-2025-001",
            "lead_doc": "AX42TEST.pdf", "pcp_job_num": "TEST123",
            "date_submitted_raw": "01/15/2025 10:30:00 AM",
            "date_accepted_raw": "01/15/2025 02:45:00 PM"
        })
        
        # Write NEW status (should NOT appear in CSV)
        exporter.export_job(1, "test.pdf", "NEW", metadata)
        # Write ARCHIVED status (should appear)
        exporter.export_job(2, "test2.pdf", "ARCHIVED", metadata)
        
        with open(exporter.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        assert len(rows) == 2  # Header + 1 ARCHIVED row (not 3)

    def test_parse_datetime_standard(self, exporter):
        """EX-03: Parse m/d/Y I:M:S PM format."""
        date, time = exporter._parse_datetime("01/15/2025 10:30:00 AM")
        assert date == "01/15/2025"
        assert time == "10:30:00"

    def test_parse_datetime_empty(self, exporter):
        """EX-04: Empty string returns ("", "")."""
        date, time = exporter._parse_datetime("")
        assert date == ""
        assert time == ""

    def test_parse_datetime_iso(self, exporter):
        """Parse ISO datetime format."""
        date, time = exporter._parse_datetime("2025-01-15 14:45:00")
        assert date == "01/15/2025"
        assert time == "14:45:00"

    def test_csv_row_data_correct(self, exporter):
        """Verify CSV row contains correct mapped values."""
        metadata = json.dumps({
            "envelope": "110282126",
            "case_num": "CV-2025-001234",
            "lead_doc": "AX02A25B01085.PDF",
            "pcp_job_num": "A25B01085",
            "date_submitted_raw": "01/15/2025 10:30:00 AM",
            "date_accepted_raw": "01/15/2025 02:45:00 PM"
        })
        
        exporter.export_job(1, "AX42A25B01085.pdf", "ARCHIVED", metadata)
        
        with open(exporter.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            row = next(reader)
        
        assert row[0] == "110282126"        # Envelope_Num
        assert row[1] == "CV-2025-001234"   # Case_Num  
        assert row[6] == "AX02A25B01085.PDF" # Lead_Document
        assert row[7] == "A25B01085"         # PCP_Job_Num
