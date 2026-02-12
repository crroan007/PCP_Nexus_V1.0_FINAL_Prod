import threading
import time
import os
import shutil
import datetime
from core import app_paths

class BackupService:
    """
    Enterprise Backup Service.
    Periodically copies the 'nexus.db' to an Archive/Backups folder.
    This mitigates the risk of SQLite corruption on network drives.
    """
    def __init__(self, log_callback):
        self.log = log_callback
        self._running = False
        if os.name == 'nt':
            self.db_path = str(app_paths.db_path())
            self.backup_dir = str(app_paths.backups_dir())
        else:
            self.db_path = os.path.join(os.getcwd(), "Executive", "Orchestrator", "data", "nexus.db")
            self.backup_dir = os.path.join(os.getcwd(), "Archive", "Backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("Backup Service Started.", "INFO")

    def stop(self):
        self._running = False

    def _run_loop(self):
        # Initial Backup on Startup
        self._perform_backup()
        
        while self._running:
            try:
                # Backup every 30 minutes
                for _ in range(30 * 60): 
                    if not self._running: break
                    time.sleep(1)
                
                if self._running:
                    self._perform_backup()
                    
            except Exception as e:
                self.log(f"Backup Loop Error: {e}", "ERROR")
                time.sleep(60)

    def _perform_backup(self):
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"nexus_backup_{timestamp}.db"
            target = os.path.join(self.backup_dir, filename)
            
            # Use SQLite backup API if possible, or naive copy usually works if WAL enabled
            # Simple Copy:
            if os.path.exists(self.db_path):
                shutil.copy2(self.db_path, target)
                self.log(f"Database Backed Up: {filename}", "SUCCESS")
                
                # Cleanup Old Backups (Keep last 10)
                backups = sorted([os.path.join(self.backup_dir, f) for f in os.listdir(self.backup_dir)])
                while len(backups) > 10:
                    os.remove(backups.pop(0))
                    
        except Exception as e:
            self.log(f"Backup Failed: {e}", "ERROR")
