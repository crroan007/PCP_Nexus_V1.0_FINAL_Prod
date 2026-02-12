import sqlite3
import json
import os
from datetime import datetime, timedelta
from core import app_paths

# Dynamic Path Resolution (must be writable in installed/frozen mode)
if os.name == 'nt':
    DB_PATH = str(app_paths.db_path())
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "nexus.db")

class PacketManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Self-Healing: Ensures pending_packets table exists."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_packets (
                envelope_id TEXT PRIMARY KEY,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                file_count INTEGER DEFAULT 1,
                status TEXT DEFAULT 'PENDING',
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.commit()
        conn.close()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def add_to_packet(self, envelope_id, file_path, prefix, message_entry_id, first_seen=None, doc_type="UNKNOWN", reopen_completed=True, original_name="", email_metadata=None):
        """Adds a file to a pending envelope packet. doc_type can be LEAD, ATTACHMENT, CLERK_LETTER, CORRECTION."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Check if envelope exists
        cursor.execute("SELECT metadata, file_count, status FROM pending_packets WHERE envelope_id = ?", (envelope_id,))
        row = cursor.fetchone()
        
        if row:
            metadata = json.loads(row[0]) if row[0] else {}
            metadata.setdefault('files', [])
            file_count = row[1] + 1
            status = row[2] or "PENDING"
            metadata['files'].append({
                'path': file_path,
                'prefix': prefix,
                'entry_id': message_entry_id,
                'doc_type': doc_type,  # LEAD, ATTACHMENT, CLERK_LETTER, CORRECTION
                'original_name': original_name,
                'timestamp': datetime.now().isoformat()
            })
            # Store email metadata at packet level from first email that provides it
            if email_metadata and not metadata.get('email_metadata'):
                metadata['email_metadata'] = {k: v for k, v in email_metadata.items() if isinstance(v, (str, int, float, bool, type(None)))}
            if status != "PENDING" and reopen_completed:
                cursor.execute("""
                    UPDATE pending_packets 
                    SET first_seen = CURRENT_TIMESTAMP,
                        last_seen = CURRENT_TIMESTAMP,
                        file_count = ?, 
                        metadata = ?,
                        status = 'PENDING'
                    WHERE envelope_id = ?
                """, (file_count, json.dumps(metadata), envelope_id))
            else:
                cursor.execute("""
                    UPDATE pending_packets 
                    SET last_seen = CURRENT_TIMESTAMP, 
                        file_count = ?, 
                        metadata = ? 
                    WHERE envelope_id = ?
                """, (file_count, json.dumps(metadata), envelope_id))
        else:
            metadata = {
                'files': [{
                    'path': file_path,
                    'prefix': prefix,
                    'entry_id': message_entry_id,
                    'doc_type': doc_type,  # LEAD, ATTACHMENT, CLERK_LETTER, CORRECTION
                    'original_name': original_name,
                    'timestamp': datetime.now().isoformat()
                }]
            }
            # Store email metadata at packet level
            if email_metadata:
                metadata['email_metadata'] = {k: v for k, v in email_metadata.items() if isinstance(v, (str, int, float, bool, type(None)))}
            # Use custom first_seen if provided (e.g., from Email ReceivedTime), else CURRENT_TIMESTAMP
            if first_seen:
                # Convert datetime object to string if needed, or assume it's a string/datetime
                # SQLite expects 'YYYY-MM-DD HH:MM:SS'
                if isinstance(first_seen, datetime):
                    fs_str = first_seen.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    fs_str = str(first_seen)
                    
                cursor.execute("""
                    INSERT INTO pending_packets (envelope_id, first_seen, last_seen, file_count, metadata)
                    VALUES (?, ?, CURRENT_TIMESTAMP, 1, ?)
                """, (envelope_id, fs_str, json.dumps(metadata)))
            else:
                cursor.execute("""
                    INSERT INTO pending_packets (envelope_id, file_count, metadata)
                    VALUES (?, 1, ?)
                """, (envelope_id, json.dumps(metadata)))
        
        conn.commit()
        conn.close()

    def get_expired_packets(self, wait_minutes=20):
        """Returns envelopes that have been waiting longer than wait_minutes since first_seen."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Convert minutes to seconds for accurate sub-minute timing
        wait_seconds = int(wait_minutes * 60)
        
        cursor.execute("""
            SELECT envelope_id, metadata 
            FROM pending_packets 
            WHERE status = 'PENDING' 
            AND datetime(first_seen, '+' || ? || ' seconds') < CURRENT_TIMESTAMP
        """, (wait_seconds,))
        
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            results.append({
                'envelope_id': row[0],
                'metadata': json.loads(row[1])
            })
        return results

    def get_packet_status(self, envelope_id):
        """Returns the status of a packet (PENDING/COMPLETED) or None if not found."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM pending_packets WHERE envelope_id = ?", (envelope_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def mark_completed(self, envelope_id):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE pending_packets SET status = 'COMPLETED' WHERE envelope_id = ?", (envelope_id,))
        conn.commit()
        conn.close()

    def cleanup_old_packets(self, days=7):
        """Helper to keep the table clean."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_packets WHERE status = 'COMPLETED' AND last_seen < datetime('now', '-' || ? || ' days')", (days,))
        conn.commit()
        conn.close()


class ScanLedger:
    """v4.3.5: DB-backed per-email scan counter with time-aware circuit breaker.
    
    Tracks how many times each Outlook email (by EntryID) has been scanned.
    The circuit breaker fires ONLY when BOTH conditions are true:
      1. scan_count > max_retries
      2. time since first_scan > safety_window_minutes
    
    This prevents false-positive exception-outs during the normal Phase 2
    packet wait window (default 20 min), while still catching truly stuck emails.
    """
    
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_table()
    
    def _init_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_ledger (
                entry_id    TEXT PRIMARY KEY,
                envelope_id TEXT,
                scan_count  INTEGER DEFAULT 1,
                first_scan  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_scan   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                disposition TEXT DEFAULT 'ACTIVE'
            )
        """)
        conn.commit()
        conn.close()
    
    def record_scan(self, entry_id, envelope_id='UNKNOWN'):
        """Increment scan count for an email. Returns the new count."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT scan_count, disposition FROM scan_ledger WHERE entry_id = ?", (entry_id,))
        row = cursor.fetchone()
        
        if row:
            if row[1] in ('COMPLETED', 'EXCEPTIONED'):
                conn.close()
                return -1  # Signal: already finalized, skip immediately
            new_count = row[0] + 1
            cursor.execute("""
                UPDATE scan_ledger 
                SET scan_count = ?, last_scan = CURRENT_TIMESTAMP, envelope_id = ?
                WHERE entry_id = ?
            """, (new_count, envelope_id, entry_id))
        else:
            new_count = 1
            cursor.execute("""
                INSERT INTO scan_ledger (entry_id, envelope_id, scan_count)
                VALUES (?, ?, 1)
            """, (entry_id, envelope_id))
        
        conn.commit()
        conn.close()
        return new_count
    
    def should_circuit_break(self, entry_id, max_retries=3, safety_window_minutes=40):
        """Time-aware circuit breaker. Returns True only if BOTH:
           1. scan_count > max_retries
           2. time since first_scan > safety_window_minutes
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT scan_count, first_scan FROM scan_ledger WHERE entry_id = ?
        """, (entry_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return False
        
        scan_count, first_scan_str = row
        if scan_count <= max_retries:
            return False
        
        # Parse first_scan and check time window
        try:
            first_scan = datetime.strptime(first_scan_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                first_scan = datetime.fromisoformat(first_scan_str)
            except Exception:
                return scan_count > max_retries  # Fallback: count-only
        
        elapsed = (datetime.now() - first_scan).total_seconds() / 60.0
        return elapsed > safety_window_minutes
    
    def mark_disposition(self, entry_id, disposition):
        """Set final disposition: COMPLETED or EXCEPTIONED."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scan_ledger SET disposition = ?, last_scan = CURRENT_TIMESTAMP
            WHERE entry_id = ?
        """, (disposition, entry_id))
        conn.commit()
        conn.close()
    
    def mark_all_for_envelope(self, envelope_id, disposition):
        """Mark all emails for an envelope as COMPLETED/EXCEPTIONED."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scan_ledger SET disposition = ?, last_scan = CURRENT_TIMESTAMP
            WHERE envelope_id = ?
        """, (disposition, envelope_id))
        conn.commit()
        conn.close()
    
    def cleanup(self, days=7):
        """Remove old finalized entries."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM scan_ledger 
            WHERE disposition IN ('COMPLETED', 'EXCEPTIONED') 
            AND last_scan < datetime('now', '-' || ? || ' days')
        """, (days,))
        conn.commit()
        conn.close()
