"""
Test CSV Rotation, Network Paths & Scheduling (v4.3 Compliance)
================================================================
Covers gaps 3, 4, 5 from the audit.

Tests the new RealtimeExporter features:
  - CSV rotation with archive subfolder lifecycle
  - Phase-specific network share output paths (configurable)
  - Scheduled CSV placement (Phase 1 daily @ 10 PM, Phase 2 hourly)
"""
import pytest
import os
import sys
import csv
import shutil
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def mock_conf():
    """Mock the secure_config.conf before importing RealtimeExporter."""
    mock = MagicMock()
    mock.get = MagicMock(return_value=None)
    return mock


@pytest.fixture
def exporter_with_tmp(tmp_path, mock_conf):
    """Create a RealtimeExporter pointing to a temp directory."""
    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)
    
    # Override conf.get to return our temp path for output
    def fake_get(key):
        if key == "paths.realtime_exports":
            return output_dir
        if key in ("paths.csv_output_phase1", "paths.csv_output_phase2"):
            return str(tmp_path / key.split("_")[-1])
        return None
    
    mock_conf.get = fake_get
    
    with patch("core.realtime_exporter.conf", mock_conf):
        from core.realtime_exporter import RealtimeExporter
        exp = RealtimeExporter()
    
    return exp


@pytest.fixture
def source_csv(tmp_path):
    """Create a sample CSV file to test rotation."""
    csv_path = tmp_path / "pcp_activity_20260210.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Envelope_Num", "Case_Num", "Date_Submitted", "Time_Submitted",
                         "Date_Accepted", "Time_Accepted", "Lead_Document", "PCP_Job_Num"])
        writer.writerow(["ENV001", "CASE001", "02/10/2026", "10:00:00",
                         "02/10/2026", "10:05:00", "AX40A25C05955.pdf", "A25C05955"])
    return str(csv_path)


# ──────────────────────────────────────────────
# Gap 3: CSV Rotation & Archive Lifecycle
# ──────────────────────────────────────────────

class TestCSVRotation:
    """Tests the rotate-and-replace CSV lifecycle."""

    def test_fresh_placement_no_archive(self, tmp_path, source_csv, mock_conf):
        """First placement creates CSV at target, no archive needed."""
        target_dir = str(tmp_path / "network_share")
        os.makedirs(target_dir, exist_ok=True)
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path / "local_output")
            exp.csv_path = source_csv
            exp.csv_paths = {"Phase1": source_csv, "Phase2": source_csv}
            exp.phase_output_paths = {"Phase1": target_dir}
            exp._last_placement = {"Phase1": None, "Phase2": None}
            exp._schedule_lock = __import__('threading').Lock()
        
        success, msg = exp.rotate_csv_to_share("Phase1", source_csv)
        
        assert success is True
        assert os.path.exists(os.path.join(target_dir, os.path.basename(source_csv)))
        # No Archive directory should exist (no previous file)
        assert not os.path.exists(os.path.join(target_dir, "Archive"))

    def test_rotation_archives_existing(self, tmp_path, source_csv, mock_conf):
        """When a CSV already exists at target, it gets moved to Archive/."""
        target_dir = str(tmp_path / "network_share")
        os.makedirs(target_dir, exist_ok=True)
        
        # Place an "existing" CSV at target first
        existing_csv = os.path.join(target_dir, os.path.basename(source_csv))
        with open(existing_csv, 'w', newline='') as f:
            csv.writer(f).writerow(["old", "data"])
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            exp.csv_path = source_csv
            exp.csv_paths = {"Phase1": source_csv, "Phase2": source_csv}
            exp.phase_output_paths = {"Phase1": target_dir}
            exp.phase_archive_paths = {"Phase1": os.path.join(target_dir, "Archive"), "Phase2": ""}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._last_placement = {"Phase1": None, "Phase2": None}
            exp._schedule_lock = __import__('threading').Lock()
        
        success, msg = exp.rotate_csv_to_share("Phase1", source_csv)
        
        assert success is True
        # Archive directory should exist
        archive_dir = os.path.join(target_dir, "Archive")
        assert os.path.exists(archive_dir)
        # Archive should contain exactly 1 file
        archived_files = os.listdir(archive_dir)
        assert len(archived_files) == 1
        # Fresh CSV should be at target
        assert os.path.exists(existing_csv)

    def test_rotation_preserves_fresh_data(self, tmp_path, source_csv, mock_conf):
        """The fresh CSV placed at target should contain the current data."""
        target_dir = str(tmp_path / "network_share")
        os.makedirs(target_dir, exist_ok=True)
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            exp.csv_path = source_csv
            exp.csv_paths = {"Phase1": source_csv, "Phase2": source_csv}
            exp.phase_output_paths = {"Phase1": target_dir}
            exp.phase_archive_paths = {"Phase1": os.path.join(target_dir, "Archive"), "Phase2": ""}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._last_placement = {"Phase1": None, "Phase2": None}
            exp._schedule_lock = __import__('threading').Lock()
        
        exp.rotate_csv_to_share("Phase1", source_csv)
        
        target_csv = os.path.join(target_dir, os.path.basename(source_csv))
        with open(target_csv, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        assert len(rows) == 2  # header + 1 data row
        assert rows[1][0] == "ENV001"

    def test_rotation_fails_gracefully_no_source(self, tmp_path, mock_conf):
        """Rotation returns error if source CSV doesn't exist."""
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            nonexistent = str(tmp_path / "nonexistent.csv")
            exp.csv_path = nonexistent
            exp.csv_paths = {"Phase1": nonexistent, "Phase2": nonexistent}
            exp.phase_output_paths = {"Phase1": str(tmp_path / "target")}
            exp.phase_archive_paths = {"Phase1": "", "Phase2": ""}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._last_placement = {"Phase1": None, "Phase2": None}
            exp._schedule_lock = __import__('threading').Lock()
        
        success, msg = exp.rotate_csv_to_share("Phase1")
        assert success is False
        assert "not found" in msg


# ──────────────────────────────────────────────
# Gap 4: Network Share Output Paths
# ──────────────────────────────────────────────

class TestNetworkPaths:
    """Tests that phase-specific output paths are properly configured."""

    def test_default_network_paths(self):
        """DEFAULT_NETWORK_PATHS point to the correct network share."""
        from core.realtime_exporter import RealtimeExporter
        assert r"\\172.31.47.151\psaffidavits" in RealtimeExporter.DEFAULT_NETWORK_PATHS["Phase1"]
        assert r"\\172.31.47.151\psaffidavits" in RealtimeExporter.DEFAULT_NETWORK_PATHS["Phase2"]

    def test_phase1_and_phase2_paths_differ(self):
        """Phase1 and Phase2 should output to different directories."""
        from core.realtime_exporter import RealtimeExporter
        assert RealtimeExporter.DEFAULT_NETWORK_PATHS["Phase1"] != RealtimeExporter.DEFAULT_NETWORK_PATHS["Phase2"]

    def test_config_override_paths(self, tmp_path, mock_conf):
        """Config keys can override default network paths."""
        custom_p1 = str(tmp_path / "custom_phase1")
        custom_p2 = str(tmp_path / "custom_phase2")
        
        def fake_get(key):
            if key == "paths.realtime_exports":
                return str(tmp_path / "output")
            if key == "paths.csv_output_phase1":
                return custom_p1
            if key == "paths.csv_output_phase2":
                return custom_p2
            return None
        
        mock_conf.get = fake_get
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter()
        
        assert exp.phase_output_paths["Phase1"] == custom_p1
        assert exp.phase_output_paths["Phase2"] == custom_p2


# ──────────────────────────────────────────────
# Gap 5: CSV Scheduling
# ──────────────────────────────────────────────

class TestCSVScheduling:
    """Tests the scheduled CSV placement logic."""

    def test_schedule_config_phase1_daily(self):
        """Phase 1 schedule is daily at 10 PM."""
        from core.realtime_exporter import RealtimeExporter
        sched = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG["Phase1"]
        assert sched["mode"] == "daily"
        assert sched["hour"] == 22  # 10 PM

    def test_schedule_config_phase2_hourly(self):
        """Phase 2 schedule is hourly."""
        from core.realtime_exporter import RealtimeExporter
        sched = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG["Phase2"]
        assert sched["mode"] == "hourly"

    def test_phase2_hourly_triggers(self, tmp_path, source_csv, mock_conf):
        """Phase 2 should trigger placement if >= 1 hour since last."""
        target_dir = str(tmp_path / "phase2_target")
        os.makedirs(target_dir, exist_ok=True)
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            exp.csv_path = source_csv
            exp.csv_paths = {"Phase1": source_csv, "Phase2": source_csv}
            exp.phase_output_paths = {"Phase2": target_dir}
            exp.phase_archive_paths = {"Phase1": "", "Phase2": os.path.join(target_dir, "Archive")}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._schedule_lock = __import__('threading').Lock()
            # Simulate last placement was 2 hours ago
            exp._last_placement = {
                "Phase1": None,
                "Phase2": datetime.datetime.now() - datetime.timedelta(hours=2)
            }
        
        placed, msg = exp.check_and_place_scheduled("Phase2")
        assert placed is True

    def test_phase2_hourly_skips_if_recent(self, tmp_path, source_csv, mock_conf):
        """Phase 2 should NOT trigger if < 1 hour since last."""
        target_dir = str(tmp_path / "phase2_target")
        os.makedirs(target_dir, exist_ok=True)
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            exp.csv_path = source_csv
            exp.csv_paths = {"Phase1": source_csv, "Phase2": source_csv}
            exp.phase_output_paths = {"Phase2": target_dir}
            exp.phase_archive_paths = {"Phase1": "", "Phase2": os.path.join(target_dir, "Archive")}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._schedule_lock = __import__('threading').Lock()
            # Last placement was 10 minutes ago
            exp._last_placement = {
                "Phase1": None,
                "Phase2": datetime.datetime.now() - datetime.timedelta(minutes=10)
            }
        
        placed, msg = exp.check_and_place_scheduled("Phase2")
        assert placed is False

    def test_phase1_daily_triggers_after_10pm(self, tmp_path, source_csv, mock_conf):
        """Phase 1 triggers after 10 PM if no placement today."""
        target_dir = str(tmp_path / "phase1_target")
        os.makedirs(target_dir, exist_ok=True)
        
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            exp.csv_path = source_csv
            exp.csv_paths = {"Phase1": source_csv, "Phase2": source_csv}
            exp.phase_output_paths = {"Phase1": target_dir}
            exp.phase_archive_paths = {"Phase1": os.path.join(target_dir, "Archive"), "Phase2": ""}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._schedule_lock = __import__('threading').Lock()
            exp._last_placement = {"Phase1": None, "Phase2": None}
        
        # Simulate it being 10:30 PM
        fake_now = datetime.datetime.now().replace(hour=22, minute=30)
        with patch("core.realtime_exporter.datetime") as mock_dt:
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.strptime = datetime.datetime.strptime
            mock_dt.datetime.side_effect = lambda *args, **kw: datetime.datetime(*args, **kw)
            
            placed, msg = exp.check_and_place_scheduled("Phase1")
        
        assert placed is True

    def test_run_scheduled_placements_returns_dict(self, tmp_path, mock_conf):
        """run_scheduled_placements returns per-phase results."""
        with patch("core.realtime_exporter.conf", mock_conf):
            from core.realtime_exporter import RealtimeExporter
            exp = RealtimeExporter.__new__(RealtimeExporter)
            exp.output_dir = str(tmp_path)
            nonexistent = str(tmp_path / "nonexistent.csv")
            exp.csv_path = nonexistent
            exp.csv_paths = {"Phase1": nonexistent, "Phase2": nonexistent}
            exp.phase_output_paths = {
                "Phase1": str(tmp_path / "p1"),
                "Phase2": str(tmp_path / "p2"),
            }
            exp.phase_archive_paths = {"Phase1": "", "Phase2": ""}
            exp.schedule_config = RealtimeExporter.DEFAULT_SCHEDULE_CONFIG.copy()
            exp._schedule_lock = __import__('threading').Lock()
            exp._last_placement = {"Phase1": None, "Phase2": None}
        
        results = exp.run_scheduled_placements()
        
        assert "Phase1" in results
        assert "Phase2" in results
        assert "placed" in results["Phase1"]
        assert "message" in results["Phase1"]
