import sqlite3
import os
import datetime
import threading
import json
import socket
from core.telemetry import Telemetry
from core.sharepoint_logger import sp_logger
from core import app_paths
from core.realtime_exporter import exporter

class JobManager:
    """
    Singleton-style manager for the SQLite 'nexus.db'.
    Handles all State Transitions, Persistence, and Transaction Safety.
    Now supports DISTRIBUTED LOCKING.
    """
    def __init__(self):
        # Reliable Path Resolution (Relative to this file)
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        if os.name == 'nt':
            # Windows: Use a writable app data dir (LocalAppData by default; ProgramData if pre-created and writable)
            self.data_dir = str(app_paths.data_dir())
        else:
            # Fallback/Linux
            self.data_dir = os.path.join(self.root_dir, "data")
            
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            print(f"DTO_DEBUG: JobManager using DB at: {self.data_dir}")
        except Exception as e:
            # Fallback if permission denied (never fall back into Program Files / frozen bundle)
            print(f"DTO_DEBUG: Failed to create data dir ({e}). Falling back to user-writable app dir.")
            self.data_dir = str(app_paths.data_dir())
            os.makedirs(self.data_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.data_dir, "nexus.db")
        self.lock = threading.Lock()
        self.node_id = Telemetry.get_node_id()
        self.node_info = json.dumps(Telemetry.get_node_info())
        self.computer_name = socket.gethostname()  # Local machine name
        self._init_db()

    def _init_db(self):
        """Creates table if not exists with correct schema."""
        with self.lock:
            print(f"DEBUG_JM: Connecting to DB at {self.db_path}")
            conn = sqlite3.connect(self.db_path)
            # IMMUNIZATION: Enable Write-Ahead Logging (WAL) for Concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;") # Balance speed/safety
            cursor = conn.cursor()
            
            # Check if columns exist (Migration logic for existing DB)
            try:
                cursor.execute("SELECT locked_by FROM jobs LIMIT 1")
            except sqlite3.OperationalError:
                # Column check failed, assuming schema needs update or create
                pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    original_source TEXT,
                    
                    -- Distributed locking
                    locked_by TEXT,
                    locked_at TIMESTAMP,
                    
                    -- Audit Telemetry
                    processing_node_info TEXT,  
                    
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    computer_name TEXT,
                    logs TEXT DEFAULT '',
                    
                    -- Phase 1/2 Classification & Audit
                    service_type TEXT DEFAULT 'AFFIDAVITS',
                    workflow_log TEXT DEFAULT '[]',
                    
                    -- Metadata for CSV Reconciliation
                    metadata TEXT DEFAULT '{}',
                    
                    -- Phase 2 Mega-Ralph Columns
                    action_flag INTEGER DEFAULT 0,
                    raw_comments TEXT DEFAULT ''
                )
            ''')
            
            # Naive migration: Add columns if they don't exist (Catch-all for dev)
            # In Prod, we'd use a real migration tool.
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN locked_by TEXT")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN locked_at TIMESTAMP")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN processing_node_info TEXT")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN file_hash TEXT")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN service_type TEXT DEFAULT 'AFFIDAVITS'")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN workflow_log TEXT DEFAULT '[]'")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN metadata TEXT DEFAULT '{}'")
            except: pass
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN computer_name TEXT")
            except: pass

            conn.commit()
            conn.close()

    def create_job(self, filename, file_path, source="Hunter", initial_status="NEW", file_hash=None, metadata=None, service_type='AFFIDAVITS'):
        """Called by Hunter when a new PDF is staged."""
        if metadata is None: metadata = {}
        metadata_json = json.dumps(metadata)
        
        local_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO jobs (filename, file_path, status, original_source, processing_node_info, file_hash, service_type, workflow_log, metadata, created_at, updated_at, computer_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, '["Job Created"]', ?, ?, ?, ?)
            ''', (filename, file_path, initial_status, source, self.node_info, file_hash, service_type, metadata_json, local_now, local_now, self.computer_name))
            job_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # v4.3.6: Export to CSV when job is created at a terminal status
            # Phase 2 jobs are created directly as FILED, Phase 1 may skip to ARCHIVED
            # Without this, export_job() in update_job_status() is never reached.
            if initial_status in ("FILED", "ARCHIVED"):
                try:
                    exporter.export_job(job_id, filename, initial_status, metadata_json, service_type=service_type)
                except Exception as e:
                    print(f"[EXPORT] Warning: Failed to export job {job_id} on create: {e}")

            # SOW 3.1: Log Creation to SharePoint immediately
            sp_logger.log_action("JOB_CREATED", job_id, f"Created new job: {filename}", status=initial_status, metadata=metadata)

            return job_id

    def reserve_job(self, status):
        """
        ATOMIC RESERVATION.
        Finds a job in 'status' that is NOT locked.
        Locks it to THIS node.
        Returns the job (dict).
        """
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=30.0) # 30s timeout
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = sqlite3.Row 
            cursor = conn.cursor()
            
            # 1. Atomic Update: Try to lock ONE record
            # We select ID first to avoid locking whole table if possible, 
            # but SQLite wraps this in transaction anyway.
            
            # Reset stale locks (Self-healing: If lock > 30 mins old, clear it)
            # (Skipping for now to keep it simple, but good for Phase 4)

            # Optimistic Locking (using local time)
            local_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            query = f'''
                UPDATE jobs 
                SET locked_by = ?, locked_at = ?, processing_node_info = ?, computer_name = ?
                WHERE id = (
                    SELECT id FROM jobs 
                    WHERE status = ? AND (locked_by IS NULL OR locked_by = '')
                    ORDER BY created_at ASC 
                    LIMIT 1
                )
                RETURNING *
            '''
            try:
                # RETURNING clause support in SQLite 3.35+ (2021)
                cursor.execute(query, (self.node_id, local_now, self.node_info, self.computer_name, status))
                row = cursor.fetchone()
                conn.commit()
                if row:
                    return dict(row)
                return None
            except:
                # Fallback for older SQLite (Fetch ID then Update)
                conn.rollback()
                # Find candidate
                cursor.execute('''SELECT id FROM jobs WHERE status = ? AND (locked_by IS NULL OR locked_by = '') ORDER BY created_at ASC LIMIT 1''', (status,))
                row = cursor.fetchone()
                if not row:
                    conn.close()
                    return None
                
                target_id = row['id']
                cursor.execute('''UPDATE jobs SET locked_by = ?, locked_at = ?, processing_node_info = ?, computer_name = ? WHERE id = ?''', (self.node_id, local_now, self.node_info, self.computer_name, target_id))
                conn.commit()
                
                cursor.execute("SELECT * FROM jobs WHERE id = ?", (target_id,))
                job = cursor.fetchone()
                conn.close()
                return dict(job)

    def get_jobs_by_status(self, status):
        """Get all jobs matching a specific status (for reconciliation)."""
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE status = ?", (status,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]

    def update_job_status(self, job_id, new_status, new_path=None, log_msg=None, release_lock=True):
        """Transitions a job to the next stage."""
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            
            local_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            update_query = "UPDATE jobs SET status = ?, updated_at = ?"
            params = [new_status, local_now]
            
            if release_lock:
                update_query += ", locked_by = NULL"
            
            if new_path:
                update_query += ", file_path = ?"
                params.append(new_path)
                
            if log_msg:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                update_query += ", logs = logs || char(10) || ?"
                params.append(f"[{timestamp}][{self.node_id}] {log_msg}")

            update_query += " WHERE id = ?"
            params.append(job_id)
            
            cursor.execute(update_query, tuple(params))
            
            # Retrieve Metadata for SharePoint Logger context
            try:
                cursor.execute("SELECT metadata FROM jobs WHERE id = ?", (job_id,))
                row = cursor.fetchone()
                current_metadata = json.loads(row[0]) if row and row[0] else {}
            except:
                current_metadata = {}

            # SOW 3.1: Log to SharePoint
            safe_msg = log_msg if log_msg else f"Status changed to {new_status}"
            sp_logger.log_action("STATUS_CHANGE", job_id, safe_msg, status=new_status, metadata=current_metadata)
            
            # Real-time CSV Export
            try:
                cursor.execute("SELECT filename, metadata, service_type FROM jobs WHERE id = ?", (job_id,))
                export_row = cursor.fetchone()
                if export_row:
                    filename_val, metadata_val, svc_type = export_row
                    exporter.export_job(job_id, filename_val, new_status, metadata_val, service_type=svc_type or 'AFFIDAVITS')
            except Exception as e:
                print(f"[EXPORT] Warning: Failed to export job {job_id}: {e}")
            
            conn.commit()
            conn.close()

    def update_job_column(self, job_id, column_name, value):
        """Specialized helper for Phase 2 dynamic columns (raw_comments, action_flag)."""
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            try:
                # Use parameter substitution for the value, but string formatting for column name 
                # (Column names cannot be parameters, but we control the inputs in HunterV2)
                local_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                query = f"UPDATE jobs SET {column_name} = ?, updated_at = ? WHERE id = ?"
                cursor.execute(query, (value, local_now, job_id))
                conn.commit()
            finally:
                conn.close()

    def get_stats(self):
        """Returns counts for UI Dashboard."""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
            rows = cursor.fetchall()
            conn.close()
            return dict(rows)

    def release_stale_locks(self, timeout_minutes=60):
        """
        ZOMBIE CLEANUP (SOW Hardening):
        Releases locks on jobs that have been stuck in 'IN_PROGRESS' for too long.
        CRITICAL: Only targets 'IN_PROGRESS'. Never touches 'COMPLETED' or 'VERIFIED'.
        """
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # SQLite modifier for minutes is just a string in some versions, 
            # but standard SQL syntax 'datetime' usage is safer.
            # We used CURRENT_TIMESTAMP (UTC) so we compare against UTC.
            
            try:
                # Calculate cutoff time string for logging/debugging (optional)
                # Query: UPDATE jobs SET status='NEW', locked_by=NULL WHERE status='IN_PROGRESS' AND locked_at < datetime('now', '-60 minutes')
                
                cursor.execute(f'''
                    UPDATE jobs 
                    SET status = 'NEW', locked_by = NULL, locked_at = NULL, 
                        logs = logs || char(10) || '[{self.node_id}] System: Lock expired (Stale). Resetting to NEW.'
                    WHERE status = 'IN_PROGRESS' 
                      AND locked_at < datetime('now', '-{timeout_minutes} minutes')
                ''')
                
                rows_affected = cursor.rowcount
                conn.commit()
                
                if rows_affected > 0:
                    print(f"JobManager: Released {rows_affected} stale zombie locks.")
                    
            except Exception as e:
                print(f"JobManager Error releasing locks: {e}")
            finally:
                conn.close()

    def _get_conn(self):
        """Helper for Agents needing raw read access (Use with Caution)."""
        return sqlite3.connect(self.db_path)
    
    def append_workflow_log(self, job_id, step_message):
        """
        Appends a step to the audit trail (JSON list).
        """
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            
            try:
                # 1. Get current log
                cursor.execute("SELECT workflow_log FROM jobs WHERE id = ?", (job_id,))
                row = cursor.fetchone()
                if not row: return
                
                current_log_json = row[0]
                try:
                    log_list = json.loads(current_log_json) if current_log_json else []
                except:
                    log_list = []
                
                # 2. Append new step
                timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                log_list.append(f"[{timestamp}] {step_message}")
                
                # 3. Save back
                new_json = json.dumps(log_list)
                local_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("UPDATE jobs SET workflow_log = ?, updated_at = ? WHERE id = ?", (new_json, local_now, job_id))
                conn.commit()
                
            except Exception as e:
                print(f"Error appending workflow log: {e}")
            finally:
                conn.close()

# Global Instance
job_manager = JobManager()
# Run cleanup on module load (Startup)
job_manager.release_stale_locks(60)
