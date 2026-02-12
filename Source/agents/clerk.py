import os
import shutil
import time
from core.agent_base import BaseAgent
from core.job_manager import job_manager
import pythoncom
from core import app_paths

class Clerk(BaseAgent):
    def __init__(self, config=None, ui_callback=None):
        super().__init__("Clerk", config=config, ui_callback=ui_callback)
        # Use configured Output path (e.g. Test Results or Network Share)
        default_output = str(app_paths.output_dir()) if os.name == 'nt' else os.path.join(os.getcwd(), "Output")
        self.archive_dir = self.config.get('paths.output') if self.config else None
        if not self.archive_dir or not self.archive_dir.strip():
            self.archive_dir = default_output
        os.makedirs(self.archive_dir, exist_ok=True)

    def run_cycle(self):
        pythoncom.CoInitialize()
        try:
            self._run_cycle_impl()
        finally:
            pythoncom.CoUninitialize()

    def apply_renaming_rules(self, original_filename):
        """
        SOW 2.3: Applies prefix replacement rules (e.g., AX02 -> AX42).
        Returns tuple (new_filename, log_entry).
        """
        rules = self.config.get('naming_rules', {}) if self.config else {}
        name = original_filename
        log_detail = None
        
        for old_prefix, new_prefix in rules.items():
            if name.upper().startswith(old_prefix.upper()):
                # Cut old prefix, prepend new
                remainder = name[len(old_prefix):]
                new_name = new_prefix + remainder
                log_detail = f"Renamed '{name}' -> '{new_name}' (Rule: {old_prefix}->{new_prefix})"
                return new_name, log_detail
        
        # Default: No change (or generic prefix if preferred, but SOW says no match = no change)
        # To avoid collisions or confusion, we might prepend FILED_ if explicit rule missing?
        # SOW says: "Original File -> (no match) -> Same Name".
        return name, "No rename rule matched"

    def _run_cycle_impl(self):
        """
        ATOMIC LOCKING MODE:
        Reserves 'VERIFIED' job -> Archives -> Updates DB.
        """
        try:
            # 1a. Priority: Check for Exceptions (QA_FAILED)
            # SOW 3.2: "Clerk handles Code 26 logic for failed filings"
            job_ex = job_manager.reserve_job('QA_FAILED')
            if job_ex:
                self._handle_exception(job_ex)
                return

            # 1b. Standard Workflow
            job = job_manager.reserve_job('VERIFIED')
            
            if not job:
                self.update_status("Waiting for Workflow...")
                return

            self.update_status(f"Filing Job #{job['id']} (Locked)...")
            
            filepath = job['file_path']
            filename = job['filename']
                
            try:
                # 1. Renaming Logic
                new_name, rename_log = self.apply_renaming_rules(filename)
                target_path = os.path.join(self.archive_dir, new_name)
                
                # Log detailed transformation audit
                self.log_workflow(job['id'], rename_log if rename_log else f"Kept original name: {filename}")
                
                # 2. Move Physical File
                if os.path.exists(filepath):
                    shutil.move(filepath, target_path)
                    self.log_workflow(job['id'], f"Archived to: {target_path}")
                else:
                    job_manager.update_job_status(job['id'], 'ERROR', log_msg="File missing during archive phase")
                    return
                
                # 3. DB Update (Releases Lock)
                job_manager.update_job_status(job['id'], 'ARCHIVED', new_path=target_path, log_msg="Archived Successfully")
                self.log(f"Job #{job['id']} Complete: {new_name}", "SUCCESS")
                
            except Exception as job_error:
                self.log(f"Error filing Job #{job['id']}: {job_error}", "ERROR")
                job_manager.update_job_status(job['id'], 'ERROR', log_msg=str(job_error))
                    
        except Exception as e:
            self.log(f"Clerk DB Error: {e}", "ERROR")
            self.update_status("Database Error")

    def _handle_exception(self, job):
        """
        SOW 3.2: Handle QA Exceptions (Code 26).
        Simulates entering the failure code into FilePro.
        """
        self.update_status(f"Handling Exception #{job['id']}...")
        try:
            # 1. Simulation of FilePro API Interaction
            # In Prod, this would be: FilePro.Entry(case_num, "Code 26", "QA Failed: " + job['logs'])
            self.log(f"Simulating FilePro Update: Code 26 for Job #{job['id']}", "WARN")
            time.sleep(1) # Mock API latency
            
            # 2. Move to Exceptions Folder (Physical Quarantine)
            exceptions_dir = os.path.join(self.archive_dir, "Exceptions")
            os.makedirs(exceptions_dir, exist_ok=True)
            
            filename = os.path.basename(job['file_path'])
            target_path = os.path.join(exceptions_dir, filename)
            
            if os.path.exists(job['file_path']):
                shutil.move(job['file_path'], target_path)
                self.log_workflow(job['id'], f"Quarantined to: {target_path}")
            else:
                self.log(f"Warning: File missing for Exception move: {job['file_path']}", "WARN")

            # 3. Update DB
            job_manager.update_job_status(job['id'], 'EXCEPTION_PROCESSED', new_path=target_path, log_msg="FilePro Updated (Simulated)")
            self.log(f"Exception Handled & Quarantined: #{job['id']}", "SUCCESS")
            
        except Exception as e:
            self.log(f"Error handling exception #{job['id']}: {e}", "ERROR")
            job_manager.update_job_status(job['id'], 'ERROR', log_msg=str(e))
