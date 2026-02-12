import os
import csv
import datetime
import json
import threading
from core.telemetry import Telemetry
from core import app_paths

class SharePointLogger:
    """
    SOW 3.1: "Log all automated actions in SharePoint"
    Implementation: Writes CSV logs to a Synced Local Folder (OneDrive/SharePoint).
    This avoids complex Graph API auth and uses the robustness of the Sync Client.
    
    ENHANCED: Full chain-of-custody audit trail with 26 columns.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SharePointLogger, cls).__new__(cls)
            cls._instance._init_logger()
        return cls._instance

    def _init_logger(self):
        self.node_id = Telemetry.get_node_id()
        self.log_path = self._get_log_path()
        
        # ENHANCED SCHEMA: 26 columns for complete chain of custody
        self.FIELDNAMES = [
            "Timestamp",           # 1: When processed
            "NodeID",              # 2: Which machine
            "JobID",               # 3: Internal ID
            "Action",              # 4: Event type (DETECTION, FILE_OUTPUT, etc.)
            "Status",              # 5: INGESTING, FILED, ERROR, etc.
            "Message",             # 6: Description
            "Original_Filename",   # 7: Source file name
            "New_Filename",        # 8: Output file name
            "Old_Job_Num",         # 9: PCP job number
            "Envelope_ID",         # 10: Tyler envelope
            "Case_Number",         # 11: Case ID
            "Court",               # 12: Jurisdictional Court
            "Case_Style",          # 13: Litigants
            "Source_Path",         # 11: Original file location
            "Source_Link",         # 12: Clickable hyperlink to source
            "Final_Path",          # 13: Output file location
            "File_Link",           # 14: Clickable hyperlink to output
            "Constituent_Docs",    # 15: List of merged files
            "Reason",              # 16: Processing reason
            "Next_Steps",          # 17: Follow-up actions
            "Lead_Doc",            # 18: Lead document name
            "Original_Prefix",     # 19: Source prefix (AX02)
            "Target_Prefix",       # 20: Final prefix (AX42)
            "Action_Flag",         # 21: Yes or No
            "Matched_Phrases",     # 25: Keywords that triggered flag
            "Accepted_Comments",   # 26: Comments parsed from email body
            "Phase",               # 23: Phase1 or Phase2
            "Part_Count",          # 24: Number of merged files
            "Email_Received",      # 25: When email arrived
            "Email_Subject",       # 26: Original subject line
        ]

    def _get_log_path(self):
        return str(app_paths.ensure_dir(app_paths.logs_dir() / "SharePoint_Mirror"))
    
    def _make_hyperlink(self, path):
        """Create Excel-clickable hyperlink formula."""
        if path and os.path.exists(str(path)):
            # Escape quotes in path
            safe_path = str(path).replace('"', '""')
            return f'=HYPERLINK("{safe_path}","Open")'
        return ''

    def log_action(self, action_type, job_id, message, status="INFO", metadata=None):
        """
        Appends a row to the daily CSV log with full chain-of-custody fields.
        """
        if metadata is None: metadata = {}
        
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        filename_safe = f"PCP_Log_{self.node_id}_{today_str}.csv"
        full_path_safe = os.path.join(self.log_path, filename_safe)
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # EXTRACT ALL COMPLIANCE FIELDS
        orig_name = metadata.get('original_filename', '')
        new_name = metadata.get('new_filename', '')
        old_num = metadata.get('pcp_job_num') or metadata.get('old_job_num', '')
        envelope_id = metadata.get('envelope') or metadata.get('envelope_id', '')
        source_path = metadata.get('source_path', '')
        final_path = metadata.get('final_path', '')
        constituents = str(metadata.get('constituent_docs', ''))
        reason = metadata.get('reason', '')
        steps = metadata.get('steps', '')
        lead_doc = metadata.get('lead_doc', '')
        
        # NEW ENHANCED FIELDS
        original_prefix = metadata.get('original_prefix', '')
        target_prefix = metadata.get('target_prefix', '')
        action_flag_raw = metadata.get('action_flag', 0)
        action_flag = 'Yes' if action_flag_raw else 'No'
        matched_phrases = metadata.get('matched_phrases', '')
        phase = metadata.get('phase', '')
        part_count = metadata.get('part_count', '')
        email_received = metadata.get('email_received', '')
        email_subject = metadata.get('email_subject', '')
        
        # CLICKABLE HYPERLINKS
        source_link = self._make_hyperlink(source_path)
        file_link = self._make_hyperlink(final_path)
        
        row = [
            timestamp, self.node_id, str(job_id), action_type, status, message,
            orig_name, new_name, old_num, envelope_id, metadata.get('case_num', ''), metadata.get('court', ''), metadata.get('case_style', ''),
            source_path, source_link, final_path, file_link, constituents, reason, 
            steps, lead_doc, original_prefix, target_prefix, action_flag, 
            matched_phrases, metadata.get('accepted_comments', ''), phase, part_count, email_received, email_subject
        ]
        
        with self._lock:
            try:
                file_exists = os.path.exists(full_path_safe)
                
                with open(full_path_safe, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(self.FIELDNAMES)
                    writer.writerow(row)
            except Exception as e:
                print(f"SharePoint Logger Error: {e}")

# Global Access
sp_logger = SharePointLogger()


