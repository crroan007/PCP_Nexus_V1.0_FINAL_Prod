"""
Test PacketManager — Aggregation Queue
========================================
Covers: PM-01..PM-09 from the testing plan.
"""
import pytest
import os
import sys
import json
import sqlite3
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@pytest.fixture
def pm(tmp_path):
    """Fresh PacketManager with temp DB."""
    db_path = str(tmp_path / "test.db")
    from core.packet_manager import PacketManager
    return PacketManager(db_path=db_path)


def _backdate_packet(pm, envelope_id, minutes_ago):
    """Helper: backdate a packet's first_seen for expiry testing."""
    conn = sqlite3.connect(pm.db_path)
    past = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE pending_packets SET first_seen = ? WHERE envelope_id = ?", (past, envelope_id))
    conn.commit()
    conn.close()


class TestPacketManagerAdd:
    """PM-01..PM-03: Adding files to packets."""

    def test_create_new_packet(self, pm):
        """PM-01: First file creates a new envelope entry."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        
        # Verify directly via DB since timing affects get_expired_packets
        conn = sqlite3.connect(pm.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT envelope_id, status FROM pending_packets WHERE envelope_id = 'ENV001'")
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        assert row[0] == "ENV001"
        assert row[1] == "PENDING"

    def test_append_to_existing_packet(self, pm):
        """PM-02: Second file appends to same envelope."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        pm.add_to_packet("ENV001", "/tmp/att.pdf", "AXPE", "MSG002", doc_type="ATTACHMENT")
        
        conn = sqlite3.connect(pm.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT metadata, file_count FROM pending_packets WHERE envelope_id = 'ENV001'")
        row = cursor.fetchone()
        conn.close()
        
        metadata = json.loads(row[0])
        assert len(metadata['files']) == 2
        assert row[1] == 2  # file_count

    def test_doc_type_stored_correctly(self, pm):
        """PM-03: doc_type is persisted for each file in the packet."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        pm.add_to_packet("ENV001", "/tmp/att.pdf", "AXPE", "MSG001", doc_type="ATTACHMENT")
        pm.add_to_packet("ENV001", "/tmp/cl.pdf", "AX40", "MSG001", doc_type="CLERK_LETTER")
        
        conn = sqlite3.connect(pm.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT metadata FROM pending_packets WHERE envelope_id = 'ENV001'")
        row = cursor.fetchone()
        conn.close()
        
        files = json.loads(row[0])['files']
        doc_types = [f['doc_type'] for f in files]
        
        assert "LEAD" in doc_types
        assert "ATTACHMENT" in doc_types
        assert "CLERK_LETTER" in doc_types


class TestPacketExpiry:
    """PM-04..PM-05, PM-08: Expiry window logic."""

    def test_expired_packet_returned(self, pm):
        """PM-04: Packets older than wait_minutes are returned."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        # Backdate to 30 minutes ago
        _backdate_packet(pm, "ENV001", minutes_ago=30)
        
        packets = pm.get_expired_packets(wait_minutes=20)
        assert len(packets) == 1
        assert packets[0]['envelope_id'] == "ENV001"

    def test_fresh_packet_not_returned(self, pm):
        """PM-05: Packets within the window are NOT returned."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        # Don't backdate → just created
        packets = pm.get_expired_packets(wait_minutes=60)
        assert len(packets) == 0


class TestPacketLifecycle:
    """PM-06..PM-07, PM-09: Complete lifecycle."""

    def test_mark_completed(self, pm):
        """PM-06: Completed packet no longer returned as expired."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        _backdate_packet(pm, "ENV001", minutes_ago=30)
        pm.mark_completed("ENV001")
        
        packets = pm.get_expired_packets(wait_minutes=20)
        assert len(packets) == 0

    def test_reopen_completed_on_new_file(self, pm):
        """PM-07: New file for completed envelope reopens it when reopen=True."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        pm.mark_completed("ENV001")
        
        # Add a new file with reopen=True
        pm.add_to_packet("ENV001", "/tmp/new.pdf", "AXPE", "MSG002", doc_type="ATTACHMENT", reopen_completed=True)
        
        # Backdate the reopened packet
        _backdate_packet(pm, "ENV001", minutes_ago=30)
        
        packets = pm.get_expired_packets(wait_minutes=20)
        assert len(packets) == 1  # Reopened!

    def test_cleanup_old_packets(self, pm):
        """PM-09: Cleanup removes old COMPLETED packets."""
        pm.add_to_packet("ENV001", "/tmp/lead.pdf", "AX40", "MSG001", doc_type="LEAD")
        pm.mark_completed("ENV001")
        
        # Backdate the last_seen so cleanup catches it
        conn = sqlite3.connect(pm.db_path)
        past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE pending_packets SET last_seen = ? WHERE envelope_id = 'ENV001'", (past,))
        conn.commit()
        conn.close()
        
        pm.cleanup_old_packets(days=7)
        
        conn = sqlite3.connect(pm.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pending_packets")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0
