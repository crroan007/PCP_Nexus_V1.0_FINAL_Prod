import os
import datetime
import win32com.client
import pythoncom
import re
import html
import hashlib
import sqlite3
import shutil
from core.agent_base import BaseAgent
from core.job_manager import job_manager
from core.secure_config import conf
from core import app_paths
from utils.link_downloader import LinkDownloader
from utils.pdf_validator import PDFValidator

# Regex Patterns for Parsing
REGEX_ENVELOPE = r"Envelope Number:\s*(\d+)"
REGEX_CASE = r"Case Number:\s*([\w\-]+)"
REGEX_DATE_SUB = r"Date/Time Submitted\s*([\d\/\-\s\:APMCST]+)" 
REGEX_DATE_ACC = r"Date/Time Accepted\s*([\d\/\-\s\:APMCST]+)"
REGEX_LEAD_DOC = r"Lead Document[:\s]+([\w\-\.]+\.pdf)"
# Regex to find the "View Documents" link (Handles Proofpoint and Microsoft SafeLinks)
# Updated to support escaped HTML entities like &quot; and SafeLinks wrapper
REGEX_DOWNLOAD_LINK = r'href=(?:["\']|&quot;)(https?://(?:urldefense\.proofpoint\.com|[\w.-]*safelinks\.protection\.outlook\.com)/(?:[a-zA-Z0-9-._~:/?#[\]@!$&\'()*+,;=%]|\s)+)(?:["\']|&quot;)'

class Hunter(BaseAgent):
    """
    SOW v2 Role: e-Affidavits Automation.
    Configurable Outlook Source.
    """
    def __init__(self, mode="affidavit", ui_callback=None):
        super().__init__("Intake", ui_callback=ui_callback)
        self.mode = mode
        if os.name == 'nt':
            self.download_path = str(app_paths.staging_dir())
            self.archive_path = str(app_paths.outlook_archive_dir())
        else:
            self.download_path = os.path.join(os.getcwd(), "Staging") 
            self.archive_path = os.path.join(os.getcwd(), "Staging", "Outlook_Archive")
        os.makedirs(self.download_path, exist_ok=True)
        os.makedirs(self.archive_path, exist_ok=True)
        self.downloader = LinkDownloader(self.logger)
        self.validator = PDFValidator()

    # ... (Helper methods for folder traversal) ...

    def _parse_email_body(self, body_text, html_body=None):
        metadata = {}
        
        # 1. Standard Parsing (Plain Text)
        if body_text:
            env_match = re.search(REGEX_ENVELOPE, body_text, re.IGNORECASE)
            case_match = re.search(REGEX_CASE, body_text, re.IGNORECASE)
            sub_match = re.search(REGEX_DATE_SUB, body_text, re.IGNORECASE)
            acc_match = re.search(REGEX_DATE_ACC, body_text, re.IGNORECASE)
            lead_match = re.search(REGEX_LEAD_DOC, body_text, re.IGNORECASE)

            metadata['envelope_num'] = env_match.group(1) if env_match else None
            metadata['case_num'] = case_match.group(1) if case_match else None
            metadata['date_submitted_raw'] = sub_match.group(1) if sub_match else None
            metadata['date_accepted_raw'] = acc_match.group(1) if acc_match else None
            metadata['lead_document'] = lead_match.group(1) if lead_match else None
        
        # 1b. Fallback to HTML Body parsing if envelope_num not found in plain text
        if not metadata.get('envelope_num') and html_body:
            env_match = re.search(REGEX_ENVELOPE, html_body, re.IGNORECASE)
            if env_match:
                metadata['envelope_num'] = env_match.group(1)
            
            if not metadata.get('case_num'):
                case_match = re.search(REGEX_CASE, html_body, re.IGNORECASE)
                if case_match:
                    metadata['case_num'] = case_match.group(1)
            
            if not metadata.get('lead_document'):
                lead_match = re.search(REGEX_LEAD_DOC, html_body, re.IGNORECASE)
                if lead_match:
                    metadata['lead_document'] = lead_match.group(1)

            # PCP Job Num Extraction (Pattern: "AX42-123", "AX07 555", etc.)
            # Assuming file naming convention holds inside the lead document string or we parse it from Subject?
            # SOW: "Unique file name that always starts with the first 4 characters of the file name" -> That's the Lead Doc.
            # We extract it from Lead Document name.
            if metadata['lead_document']:
                # Heuristic: Remove extension
                base_name = metadata['lead_document'].replace(".pdf", "")
                
                # Try to extract the Job Number (last digits?)
                # Case 1: "AX42-1234.pdf" -> Job "1234"
                # Case 2: "Lead Document: AX47 25A02463.pdf" -> Job "25A02463"
                # We need to extract the whole identifying string
                
                # Refined Regex for PCP Job: (AX\d{2})[-\s]?([A-Z0-9]+)
                job_match = re.search(r"(AX\d{2})[-\s]?([A-Z0-9]+)", base_name)
                if job_match:
                     metadata['pcp_job_num'] = job_match.group(2) # The ID part
                else:
                     # Fallback: Just take everything after the first 4 chars?
                     if len(base_name) > 4:
                        metadata['pcp_job_num'] = base_name[4:].strip(" -_")
        else:
            # PCP Job Num Extraction (Pattern: "AX42-123", "AX07 555", etc.)
            # Assuming file naming convention holds inside the lead document string or we parse it from Subject?
            # SOW: "Unique file name that always starts with the first 4 characters of the file name" -> That's the Lead Doc.
            # We extract it from Lead Document name.
            if metadata.get('lead_document'):
                # Heuristic: Remove extension
                base_name = metadata['lead_document'].replace(".pdf", "")
                
                # Try to extract the Job Number (last digits?)
                # Case 1: "AX42-1234.pdf" -> Job "1234"
                # Case 2: "Lead Document: AX47 25A02463.pdf" -> Job "25A02463"
                # We need to extract the whole identifying string
                
                # Refined Regex for PCP Job: (AX\d{2})[-\s]?([A-Z0-9]+)
                job_match = re.search(r"(AX\d{2})[-\s]?([A-Z0-9]+)", base_name)
                if job_match:
                     metadata['pcp_job_num'] = job_match.group(2) # The ID part
                else:
                     # Fallback: Just take everything after the first 4 chars?
                     if len(base_name) > 4:
                        metadata['pcp_job_num'] = base_name[4:].strip(" -_")
        
        # 2. Link Decoding (HTML)
        if html_body:
            # We need to find the "View Documents" link
            # Search for specific text anchor? Or just a huge regex scan?
            # Iterate through ALL links to find the correct "View" link, skipping Footer/Help links
            matches = re.finditer(REGEX_DOWNLOAD_LINK, html_body, re.IGNORECASE)
            for m in matches:
                raw_url = m.group(1)
                # Unwrap to check if it's junk
                decoded = self.downloader.decode_proofpoint_url(raw_url)
                
                # Filter List
                ignored = ["zendesk", "privacy", "subscription", "microsoft", "help", "terms", "faq"]
                if any(term in decoded.lower() for term in ignored):
                    # self.log(f"Ignoring Junk Link: {decoded[:30]}...", "INFO")
                    continue
                
                # If we get here, it's likely the valid document link
                metadata['download_url'] = raw_url
                break
        
        return metadata

    def _calculate_hash(self, file_path):
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except: return None

    def _check_db_hash(self, file_hash):
        if not file_hash: return None
        try:
            conn = sqlite3.connect(job_manager.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT filename FROM jobs WHERE file_hash = ?", (file_hash,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except: return None

    def _check_db_full_duplicate(self, file_hash, source_str):
        """Checks if exact same File + Source (Envelope) exists."""
        if not file_hash or not source_str: return False
        try:
            conn = sqlite3.connect(r'Executive\Orchestrator\data\nexus.db')
            cursor = conn.cursor()
            # source_str example: "Tyler: 12345"
            cursor.execute("SELECT id FROM jobs WHERE file_hash = ? AND original_source = ?", (file_hash, source_str))
            row = cursor.fetchone()
            conn.close()
            return True if row else False
        except: return False

    def _get_folder_by_path(self, parent_folder, folder_path_str):
        if not folder_path_str: return parent_folder
        
        folders = folder_path_str.split("\\")
        current_folder = parent_folder
        
        for name in folders:
            if not name: continue
            try:
                current_folder = current_folder.Folders(name)
            except Exception:
                # self.log(f"Folder '{name}' not found in '{current_folder.Name}'.", "WARN")
                return None
        return current_folder

    def _ensure_folder(self, parent_folder, folder_name):
        try:
             return parent_folder.Folders(folder_name)
        except:
             try:
                 return parent_folder.Folders.Add(folder_name)
             except: return None

    def run_cycle(self):
        # Thread Safety for Outlook COM
        pythoncom.CoInitialize()
        try:
            # self.log("Hunter Cycle Start", "INFO") 
            # Config Switch based on Mode
            if self.mode == "efiling":
                target_account = conf.get_kvi("phase2.efiling_account", "")
                target_folder_name = conf.get_kvi("phase2.efiling_folder", "Inbox")
                self.update_status(f"Scanning (e-Filing): {target_folder_name}")
            else:
                target_folder_name = conf.get("outlook_folder", "Inbox")
                target_account = conf.get("outlook_account", "")
                self.update_status(f"Scanning (Affidavit): {target_folder_name}")

            PROCESSED_TAG = "PCP-Processed"
        
            pfx = f"{target_account}\\" if target_account else ""
            self.log(f"DEBUG: Target: {target_account} // {target_folder_name}", "INFO")
            
            # (Merged inner try)
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            
            target_folder = None
            
            if target_account:
                try:
                    root = namespace.Folders(target_account)
                    target_folder = self._get_folder_by_path(root, target_folder_name)
                    if not target_folder:
                        self.log(f"DEBUG: Folder '{target_folder_name}' not found in root '{target_account}'", "WARN")
                except Exception as e:
                    self.log(f"Err: Acct '{target_account}': {e}", "ERROR")
            
            if not target_folder and not target_account:
                root_inbox = namespace.GetDefaultFolder(6) 
                target_folder = self._get_folder_by_path(root_inbox, target_folder_name)
            
            if not target_folder:
                 self.log("DEBUG: Target Folder is NONE. Returning.", "WARN")
                 self.update_status("Folder Error")
                 return

            all_items = target_folder.Items
            all_items.Sort("[ReceivedTime]", True)

            found_count = 0
            MAX_BATCH = conf.get("processing.batch_size", 5)
            msgs = []
            scan_limit = 500 # Increased scan limit for larger batches
            total_items = all_items.Count
            
            self.log(f"Scanning: {target_folder.Name} ({total_items} items).", "INFO")
            
            for i in range(1, min(scan_limit, total_items) + 1):
                try:
                    m = all_items.Item(i)
                    # TAGGING LOGIC: Check Categories instead of Folder/Unread only
                    cats = m.Categories or ""
                    if PROCESSED_TAG not in cats:
                        msgs.append(m)
                        if len(msgs) >= MAX_BATCH: break
                    else:
                        # Debug: Log ignored processed items occasionally?
                        pass 
                except: pass 

            if len(msgs) == 0:
                self.update_status(f"No new affidavits.")
                return 

            self.log(f"Processing batch of {len(msgs)}...", "INFO")
            
            for message in msgs:
                try:
                    self.log(f"DEBUG: Processing contents of '{message.Subject}'...", "INFO")
                    subject = message.Subject
                    body = message.Body
                    try: html_body = message.HTMLBody
                    except: html_body = None
                    
                    # AUTO-IGNORE: Self-Generated Reports
                    if "PCP Daily Report" in subject or "PCP Weekly Report" in subject or "PCP Monthly Report" in subject:
                         self.log(f"Ignoring Self-Generated Report: {subject}", "INFO")
                         # Tag as ignored to prevent re-scan
                         try:
                             c = message.Categories or ""
                             if PROCESSED_TAG not in c:
                                 message.Categories = (c + ";" + PROCESSED_TAG) if c else PROCESSED_TAG
                                 message.Save()
                         except: pass
                         continue

                    # UPDATED CHECK: Allow "Filing Accepted" to trigger logic directly
                    # Expanded to include Body checks for "Filing Accepted" and "eFileTexas"
                    if ("Tyler Technologies" in body or 
                        "eFileTexas" in body or
                        "Filing Accepted" in body or
                        "Affidavit" in subject or 
                        "Filing Accepted" in subject):
                    
                        # Specific Workflow: Filing Accepted
                        if "Filing Accepted" in subject:
                            self.log(f"Processing Accepted Filing: {subject}", "INFO")
                            metadata = self._parse_email_body(body, html_body)
                            
                            processed = False
                            
                            # Attachments
                            if message.Attachments.Count > 0:
                                 files_processed = 0
                                 success_count = 0
                                 
                                 # Phase 2: Detect Multi-Attachment Packets
                                 valid_pdf_count = 0
                                 for k in range(1, message.Attachments.Count + 1):
                                     if message.Attachments.Item(k).FileName.lower().endswith(".pdf"):
                                         valid_pdf_count += 1
                                 
                                 override_status = None
                                 # Race Condition Fix: Use Two-Phase Commit for Packets
                                 is_batch_mode = False
                                 batch_job_ids = []
                                 
                                 if self.mode == "efiling":
                                     if valid_pdf_count > 1:
                                        override_status = "INTAKE_HOLD"
                                        is_batch_mode = True
                                     else:
                                        override_status = "NEW"

                                 for i in range(1, message.Attachments.Count + 1):
                                    attachment = message.Attachments.Item(i)
                                    if attachment.FileName.lower().endswith(".pdf"):
                                        # Updated Signature: success, job_id
                                        ok, jid = self._process_file(attachment, metadata, override_status)
                                        if ok:
                                            success_count += 1
                                            if jid: batch_job_ids.append(jid)
                                        files_processed += 1
                                 
                                 if files_processed > 0 and success_count == files_processed:
                                     # COMMIT TRANSACTION
                                     if is_batch_mode and batch_job_ids:
                                         self.log(f"Committing Batch of {len(batch_job_ids)} jobs to READY_TO_MERGE...", "INFO")
                                         for jid in batch_job_ids:
                                             job_manager.update_job_status(jid, "READY_TO_MERGE")
                                     
                                     found_count += 1
                                     processed = True
                                     # Backup Tag
                                     try:
                                         c = message.Categories or ""
                                         if PROCESSED_TAG not in c:
                                             message.Categories = (c + ";" + PROCESSED_TAG) if c else PROCESSED_TAG
                                             message.Save()
                                     except Exception as ex:
                                         self.log(f"Tag Error: {ex}", "WARNING")
                                     
                                     # Primary Move
                                     try:
                                         dest = self._ensure_folder(target_folder, "3 - AI Completed")
                                         if dest: message.Move(dest)
                                     except Exception as move_err:
                                          self.log(f"Move Error: {move_err}", "WARNING")
                                 else:
                                     if files_processed > 0 and success_count != files_processed:
                                          # Partial failure
                                          # Rollback? Or just leave as INTAKE_HOLD (Dead Letter)?
                                          # For now, we log validation warnings. Admin can fix.
                                          if is_batch_mode:
                                               self.log("Batch failed validation. Jobs remain in INTAKE_HOLD.", "WARN")
                                          pass 

                                     if files_processed == 0:
                                          if metadata.get('download_url'):
                                              self.log("No attachments, attempting Link Download...", "INFO")
                                              if self._process_download(metadata):
                                                  found_count += 1
                                                  processed = True
                                                  # Backup Tag
                                                  try:
                                                      c = message.Categories or ""
                                                      if PROCESSED_TAG not in c:
                                                          message.Categories = (c + ";" + PROCESSED_TAG) if c else PROCESSED_TAG
                                                          message.Save()
                                                  except Exception as ex:
                                                      self.log(f"Tag Error: {ex}", "WARNING")
                                                  
                                                  # Primary Move
                                                  try:
                                                      dest = self._ensure_folder(target_folder, "3 - AI Completed")
                                                      if dest: message.Move(dest)
                                                  except Exception as move_err:
                                                       self.log(f"Move Error: {move_err}", "WARNING")
                                              else: raise Exception("Link Download Failed")
                                          else: raise Exception("No PDF attachments and no Download Link found.")
                            
                            # Link Fallback (If no attachments at all)
                            elif not processed:
                                if metadata.get('download_url'):
                                    self.log("No attachments, attempting Link Download...", "INFO")
                                    if self._process_download(metadata):
                                        found_count += 1
                                        processed = True
                                        # Backup Tag
                                        try:
                                            c = message.Categories or ""
                                            if PROCESSED_TAG not in c:
                                                message.Categories = (c + ";" + PROCESSED_TAG) if c else PROCESSED_TAG
                                                message.Save()
                                        except Exception as ex:
                                            self.log(f"Tag Error: {ex}", "WARNING")

                                        # Primary Move
                                        try:
                                            dest = self._ensure_folder(target_folder, "3 - AI Completed")
                                            if dest: message.Move(dest)
                                        except Exception as move_err:
                                             self.log(f"Move Error: {move_err}", "WARNING")
                                    else: pass

                        else:
                            pass
                except Exception as ex:
                    self.log(f"Error msg '{message.Subject}': {ex}", "ERROR")
                    # On Error, Tag as Exception?
                    # Safer to leave untagged to retry, OR Tag as "PCP-Exception"
                    try:
                         c = message.Categories or ""
                         if "PCP-Exception" not in c:
                             message.Categories = (c + ";PCP-Exception") if c else "PCP-Exception"
                             message.Save()
                    except: pass
            
            if found_count > 0:
                self.update_status(f"Processed {found_count} affidavits.")
            else:
                self.update_status("No new affidavits.")

        except Exception as e:
            self.log(f"Hunter Error: {e}", "ERROR")
            self.update_status("Connection Failed")
        finally:
            pythoncom.CoUninitialize()

    def _get_target_filename(self, metadata):
        lead_doc = metadata.get('lead_document', '')
        pcp_job = metadata.get('pcp_job_num', 'UNKNOWN')
        # Refactored: load from config for adaptability
        naming_rules = conf.get("naming_rules", {})
        doc_prefix = lead_doc[:4] if lead_doc else ""
        output_prefix = naming_rules.get(doc_prefix, "AX_UNK")
        if output_prefix != "AX_UNK" and pcp_job != "UNKNOWN":
            new_filename = f"{output_prefix}{pcp_job}.pdf"
            save_path = os.path.join(self.download_path, new_filename)
            return new_filename, save_path
        else:
            self.log(f"Validation Failed: LeadDoc={lead_doc} -> Prefix={output_prefix}", "WARNING")
            return None

    def _process_file(self, attachment, metadata, override_status=None):
        res = self._get_target_filename(metadata)
        if not res: return False, None
        final_filename, final_path = res
        
        # 1. Download to Temp
        temp_path = final_path + ".tmp"
        try:
             attachment.SaveAsFile(temp_path)
             
             # 2. Hash & Check Duplicates
             f_hash = self._calculate_hash(temp_path)
             existing_filename = self._check_db_hash(f_hash)
             
             
             # Status Override for Duplicates
             forced_status = None

             if existing_filename:
                 # Check for LOGICAL DUPLICATE (Same File + Same Envelope)
                 env_id = metadata.get('envelope_num', 'N/A')
                 source_str = f"Tyler: {env_id}"
                 
                 if self._check_db_full_duplicate(f_hash, source_str):
                     self.log(f"Exact Duplicate Case Detected (Hash={existing_filename}, Source={source_str}). Marking DUPLICATE.", "WARN")
                     forced_status = 'DUPLICATE'
                     # Point to existing file (Duplicates are not archived, so safe to share)
                     try: os.remove(temp_path)
                     except: pass
                     final_filename = existing_filename
                     final_path = os.path.join(self.download_path, existing_filename)
                 else:
                     self.log(f"Duplicate Content Detected (Hash match: {existing_filename}). Creating Independent Copy.", "INFO")
                     # CONTENT EXISTS, BUT NEW JOB.
                     # MUST create unique file so Clerk doesn't break when archiving Job A.
                     ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                     final_filename = final_filename.replace(".pdf", f"_COPY_{ts}.pdf")
                     final_path = os.path.join(self.download_path, final_filename)
                     
                     shutil.move(temp_path, final_path)

             else:
                 # 3. New Content - Collision Check
                 if os.path.exists(final_path):
                     ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                     final_filename = final_filename.replace(".pdf", f"_v{ts}.pdf")
                     final_path = os.path.join(self.download_path, final_filename)
                     self.log(f"Filename Collision (Content Differs). Versioned to: {final_filename}", "INFO")
                 
                 shutil.move(temp_path, final_path)

             # 4. Validation & Registration
             is_valid, reason = self.validator.validate_content(final_path, metadata)
             
             # Status Logic
             status = 'QA_FAILED' # Default failure
             if is_valid:
                 if forced_status:
                     status = forced_status
                 elif override_status:
                     status = override_status
                 elif self.mode == "efiling":
                     status = 'NEW' # Phase 2: Needs Classification, defaults to NEW if not merged
                 else:
                     status = 'VERIFIED' # Phase 1: Direct to Audit/Archival
             
             job_id = job_manager.create_job(
                 filename=final_filename, 
                 file_path=final_path, 
                 source=f"Tyler: {metadata.get('envelope_num', 'N/A')}",
                 initial_status=status,
                 file_hash=f_hash,
                 metadata=metadata
             )
             self.log(f"Job #{job_id} Created: {final_filename} [{status}]", "SUCCESS" if is_valid else "WARN")
             if not is_valid: 
                 self.log(f"  Reason: {reason}", "WARN")
                 try: job_manager.append_log(job_id, f"Reason: {reason}")
                 except: pass
             self._append_to_daily_csv(metadata, final_filename)
             return True, job_id
        except Exception as e:
            self.log(f"Save Error {final_filename}: {e}", "ERROR")
            return False, None

    def _process_download(self, metadata):
        res = self._get_target_filename(metadata)
        if not res: return False
        final_filename, final_path = res
        
        url = metadata.get('download_url')
        if not url: return False
        real_url = self.downloader.decode_proofpoint_url(url)
        
        # 1. Download to Temp
        temp_path = final_path + ".tmp"
        
        # 3. Download
        self.log(f"Attempting to download from: {url}", "INFO")
        if self.downloader.download_file(real_url, temp_path):
             try:
                 # 2. Hash & Check Duplicates
                 f_hash = self._calculate_hash(temp_path)
                 existing_filename = self._check_db_hash(f_hash)
                 
                 if existing_filename:
                     self.log(f"Duplicate Content Detected (Hash match: {existing_filename}). Linking Job...", "INFO")
                     try: os.remove(temp_path)
                     except: pass
                     final_filename = existing_filename
                     final_path = os.path.join(self.download_path, existing_filename)
                 else:
                     # 3. New Content - Collision Check
                     if os.path.exists(final_path):
                         ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                         final_filename = final_filename.replace(".pdf", f"_v{ts}.pdf")
                         final_path = os.path.join(self.download_path, final_filename)
                         self.log(f"Filename Collision (Content Differs). Versioned to: {final_filename}", "INFO")
                     
                     shutil.move(temp_path, final_path)

                 # 4. Registration
                 is_valid, reason = self.validator.validate_content(final_path, metadata)
                 
                 # Status Logic
                 status = 'QA_FAILED'
                 if is_valid:
                     if self.mode == "efiling":
                         status = 'NEW'
                     else:
                         status = 'VERIFIED'

                 job_id = job_manager.create_job(
                      filename=final_filename, 
                      file_path=final_path, 
                      source=f"Tyler Link: {metadata.get('envelope_num', 'N/A')}",
                      initial_status=status,
                      file_hash=f_hash,
                      metadata=metadata
                 )
                 self.log(f"Job #{job_id} Created (Download): {final_filename} [{status}]", "SUCCESS" if is_valid else "WARN")
                 if not is_valid: 
                     self.log(f"  Reason: {reason}", "WARN")
                     try: job_manager.append_log(job_id, f"Reason: {reason}")
                     except: pass
                 self._append_to_daily_csv(metadata, final_filename)
                 return True
             except Exception as e:
                 self.log(f"Job Registration Error: {e}", "ERROR")
                 return False
        else:
            return False

    def _append_to_daily_csv(self, metadata, filename):
        try:
            today_str = datetime.datetime.now().strftime("%m%d%Y")
            csv_name = f"eaffidavits_accepted_{today_str}.csv"
            output_root = conf.get("paths.output", self.download_path) 
            csv_path = os.path.join(output_root, csv_name)
            row = [
                metadata.get('envelope_num', ''),
                metadata.get('case_num', ''),
                metadata.get('date_submitted_raw', '').split(' ')[0] if metadata.get('date_submitted_raw') else '',
                " ".join(metadata.get('date_submitted_raw', '').split(' ')[1:]) if metadata.get('date_submitted_raw') and ' ' in metadata.get('date_submitted_raw') else '',
                metadata.get('date_accepted_raw', '').split(' ')[0] if metadata.get('date_accepted_raw') else '',
                " ".join(metadata.get('date_accepted_raw', '').split(' ')[1:]) if metadata.get('date_accepted_raw') and ' ' in metadata.get('date_accepted_raw') else '',
                metadata.get('lead_document', ''),
                metadata.get('pcp_job_num', '')
            ]
            write_header = not os.path.exists(csv_path)
            import csv
            with open(csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["Envelope_Num", "Case_Num", "Date_Submitted", "Time_Submitted", "Date_Accepted", "Time_Accepted", "Lead_Document", "PCP_Job_Num"])
                writer.writerow(row)
        except Exception as csv_ex:
            self.log(f"CSV Append Error: {csv_ex}", "ERROR")

    def _perform_retention_policy(self):
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            
            target_account = conf.get("outlook_account", "")
            root = None
            if target_account:
                try:
                    root = namespace.Folders(target_account)
                except: pass
            
            if not root:
                root = namespace.GetDefaultFolder(6).Parent
            
            inbox = namespace.GetDefaultFolder(6) 
            try:
                completed_folder = inbox.Folders("Completed-AI")
            except:
                return 

            days = 90
            try:
                days = int(conf.get("rules.retention", "90 Days").split(" ")[0])
            except: pass
            
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
            items = completed_folder.Items
            deleted_count = 0
            for i in range(items.Count, 0, -1):
                item = items.Item(i)
                if item.ReceivedTime.replace(tzinfo=None) < cutoff_date:
                    item.Delete()
                    deleted_count += 1
            if deleted_count > 0:
                self.log(f"Retention Policy: Deleted {deleted_count} emails > {days} days.", "WARNING")
        except Exception as e:
            self.log(f"Retention Policy Error: {e}", "ERROR")
        finally:
            pythoncom.CoUninitialize()
