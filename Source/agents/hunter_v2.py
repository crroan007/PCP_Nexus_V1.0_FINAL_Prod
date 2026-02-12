import os
import time
import re
import sys
import pythoncom
import win32com.client
from datetime import datetime
from pypdf import PdfWriter, PdfReader

from agents.hunter import Hunter
from core.packet_manager import PacketManager, ScanLedger
from core.intelligence_engine import IntelligenceEngine
from core import app_paths
from core.secure_config import conf
from core.job_manager import job_manager

class HunterV2(Hunter):
    """
    Phase 2 Smart Agent: 20-min Persistent Aggregator.
    Handles 'Split Petitions' and 'Intelligent Flagging'.
    """
    def __init__(self, ui_callback=None):
        super().__init__(mode="efiling", ui_callback=ui_callback)
        print(f"DEBUG: Loading HunterV2 from {__file__}")
        self.packet_mgr = PacketManager()
        self.intel = IntelligenceEngine()
        self.stop_event = None  # Set by OrchestratorEngine for graceful shutdown
        
        # v4.3.3: Retry tracking — prevents infinite re-processing loops
        self._envelope_attempts = {}  # {envelope_id: attempt_count}
        self.MAX_ENVELOPE_RETRIES = int(conf.get("Phase2.MaxEnvelopeRetries", 3))
        
        # v4.3.5: DB-backed scan ledger (circuit breaker)
        self.scan_ledger = ScanLedger()
        self.MAX_SCAN_RETRIES = int(conf.get("ScanCircuitBreaker.MaxRetries", 10))
        # Safety window = 2x the Phase 2 packet wait. Breaker only fires AFTER this window.
        p2_wait = float(conf.get("Phase2.WaitMinutes", 20))
        self.SCAN_SAFETY_WINDOW = float(conf.get("ScanCircuitBreaker.SafetyWindowMinutes", p2_wait * 2))
        
        # Load ALL prefixes from config (dynamic, not hardcoded)
        self._reload_prefix_config()
    
    def _reload_prefix_config(self):
        """Reload ALL prefix configuration from config.json (Phase 1 AND Phase 2)."""
        phases_conf = conf.get("Phases", {})
        
        # Phase 1 config (dynamic from config.json RenameMap)
        p1_conf = phases_conf.get("Phase1", {})
        self.phase1_prefixes = p1_conf.get("Prefixes", ["AX02", "AX03", "AX07", "AX09"])
        self.phase1_rename_map = p1_conf.get("RenameMap", {"AX02": "AX42", "AX03": "AX43", "AX07": "AX47", "AX09": "AX89"})
        
        # Phase 2 config
        p2_conf = phases_conf.get("Phase2", {})
        p2_prefixes = p2_conf.get("Prefixes", {})
        
        # Build comprehensive Phase 2 prefix lists from config
        self.phase2_lead_prefixes = p2_prefixes.get("Lead", ["AX40"])
        self.phase2_attachment_prefixes = p2_prefixes.get("Attachment", ["AXPB", "AXPE", "AXPM", "AXPL", "AXPA"])
        self.phase2_clerk_prefixes = p2_prefixes.get("ClerkLetter", [])
        self.phase2_correction_prefixes = p2_prefixes.get("Corrections", [])
        self.phase2_ignore_prefixes = p2_prefixes.get("Ignore", ["AX69", "AX81", "CL"])
        
        # Combined Phase 2 prefix set (all actionable — AX69, AX81, CL excluded)
        self.phase2_prefixes = (
            self.phase2_lead_prefixes + 
            self.phase2_attachment_prefixes + 
            self.phase2_correction_prefixes
        )
        
        # All actionable prefixes (Phase 1 + Phase 2)
        self.actionable_prefixes = self.phase1_prefixes + self.phase2_prefixes
        
        # Ignore list
        self.ignore_prefixes = self.phase2_ignore_prefixes
    
    def _classify_document_type(self, prefix):
        """Classify a prefix into document type category."""
        prefix_upper = prefix.upper()
        if prefix_upper in self.phase2_lead_prefixes:
            return "LEAD"
        elif prefix_upper in self.phase2_attachment_prefixes:
            return "ATTACHMENT"
        elif prefix_upper in self.phase2_clerk_prefixes:
            return "CLERK_LETTER"
        elif prefix_upper in self.phase2_correction_prefixes:
            return "CORRECTION"
        elif prefix_upper in self.phase1_prefixes:
            return "PHASE1_AFFIDAVIT"
        else:
            return "UNKNOWN"

    def _parse_email_body(self, body_text, html_body=None, subject=None):
        """
        Robust Parsing for Phase 1 (Subject-based) and Phase 2 (Body-based).
        Handles optional colons in 'Envelope Number'.
        """
        metadata = {}
        
        # Regex Definitions
        # UPDATED: Extremely permissive to match "Envelope Number:  1092..." or "Envelope ID 109..."
        # UPDATED: Robust Patterns for Phase 2 Data Quality
        # 1. Envelope: Handles "Envelope Number:", "Env ID", etc. with optional whitespace/digits
        REGEX_ENVELOPE = r"(?:Envelope|Env)(?:\s*(?:Number|ID|#))?[:\s]*(\d{8,})"
        REGEX_CASE = r"Case[:\s]*([\w\-]+)"
        REGEX_DATE_SUB = r"(?:Submitted|Date/Time Submitted)[:\s]+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)"
        REGEX_DATE_ACC = r"(?:Accepted|Date/Time Accepted)[:\s]+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)"
        # FIX: Lead Doc - STRICTLY exclude newlines from filename. Handles tabs/spaces before value.
        REGEX_LEAD_DOC = r"Lead Document\s*(?:[:\-])?\s*([A-Za-z0-9\-\._]+\.pdf)" 
        REGEX_DOWNLOAD_LINK = r'href=(?:["\']|&quot;)(https?://(?:urldefense\.proofpoint\.com|[\w.-]*safelinks\.protection\.outlook\.com)/(?:[a-zA-Z0-9-._~:/?#[\]@!$&\'()*+,;=%]|\s)+)(?:["\']|&quot;)'

        REGEX_COURT = r"Court\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)"
        REGEX_CASE_STYLE = r"Case Style\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)"
        REGEX_COMMENTS = r"Accepted Comments\s*[ \t]*[:\-]?[ \t]*([^\n\r]+)"

        # 1. Subject Extraction (Priority for Envelope/Case if present in subject)
        if subject:
             env_match = re.search(REGEX_ENVELOPE, subject, re.IGNORECASE)
             if env_match: metadata['envelope_num'] = env_match.group(1)
             
             # Case in subject? "Case: 01-FC..."
             case_match = re.search(r"Case[:\s]*([A-Z0-9-]+)", subject, re.IGNORECASE)
             if case_match: metadata['case_num'] = case_match.group(1)
             
             # Lead Doc in subject?
             lead_match_sub = re.search(REGEX_LEAD_DOC, subject, re.IGNORECASE)
             if lead_match_sub: metadata['lead_document'] = lead_match_sub.group(1)

        # 2. Body Extraction (Standard)
        if body_text:
            if not metadata.get('envelope_num'):
                env_match = re.search(REGEX_ENVELOPE, body_text, re.IGNORECASE)
                if env_match: metadata['envelope_num'] = env_match.group(1)
            
            if not metadata.get('case_num'):
                case_match = re.search(REGEX_CASE, body_text, re.IGNORECASE)
                if case_match: metadata['case_num'] = case_match.group(1)
            
            # New fields extraction
            court_match = re.search(REGEX_COURT, body_text, re.IGNORECASE)
            if court_match: metadata['court'] = court_match.group(1).strip()
            
            style_match = re.search(REGEX_CASE_STYLE, body_text, re.IGNORECASE)
            if style_match: metadata['case_style'] = style_match.group(1).strip()
            
            comm_match = re.search(REGEX_COMMENTS, body_text, re.IGNORECASE)
            if comm_match: metadata['accepted_comments'] = comm_match.group(1).strip()
                
            sub_match = re.search(REGEX_DATE_SUB, body_text, re.IGNORECASE)
            acc_match = re.search(REGEX_DATE_ACC, body_text, re.IGNORECASE)
            lead_match = re.search(REGEX_LEAD_DOC, body_text, re.IGNORECASE)

            metadata['date_submitted_raw'] = sub_match.group(1) if sub_match else None
            metadata['date_accepted_raw'] = acc_match.group(1) if acc_match else None
            metadata['lead_document'] = lead_match.group(1) if lead_match else None
        
        # 3. HTML Extraction (Fallback)
        # If still missing critical info, check raw HTML
        if (not metadata.get('envelope_num') or not metadata.get('lead_document')) and html_body:
            if not metadata.get('envelope_num'):
                 env_match = re.search(REGEX_ENVELOPE, html_body, re.IGNORECASE)
                 if env_match: metadata['envelope_num'] = env_match.group(1)
            
            if not metadata.get('lead_document'):
                 lead_match = re.search(REGEX_LEAD_DOC, html_body, re.IGNORECASE)
                 if lead_match: metadata['lead_document'] = lead_match.group(1)

            if not metadata.get('accepted_comments'):
                 comm_match = re.search(REGEX_COMMENTS, html_body, re.IGNORECASE)
                 if comm_match: metadata['accepted_comments'] = comm_match.group(1).strip()

        # 4. Standardize / Defaults
        # Extract PCP Job Num from Lead Document Name
        if metadata.get('lead_document'):
            base_name = metadata['lead_document'].replace(".pdf", "")
            # Pattern: AX42-..., AX07 ...
            job_match = re.search(r"(AX\d{2})[-\s]?([A-Z0-9]+)", base_name)
            if job_match:
                 metadata['pcp_job_num'] = job_match.group(2)
            else:
                 if len(base_name) > 4:
                    metadata['pcp_job_num'] = base_name[4:].strip(" -_")

        # 5. Link Decoding (HTML) - ROBUST DOM PARSING
        if html_body:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_body, 'html.parser')
                links = soup.find_all('a', href=True)
                
                valid_candidates = []
                
                for link in links:
                    raw_url = link['href']
                    decoded = self.downloader.decode_proofpoint_url(raw_url)
                    decoded_lower = decoded.lower()
                    
                    # BLACKLIST: Skip obvious noise
                    ignored_terms = ["zendesk", "privacy", "subscription", "microsoft", "help", "terms", "faq", "twitter", "facebook", "linkedin"]
                    if any(term in decoded_lower for term in ignored_terms): 
                        continue
                        
                    # WHITELIST/HEURISTIC: Prioritize Tyler/Filing links
                    # We accept any link that survived the blacklist, but we flag specifically good ones
                    is_tyler = any(t in decoded_lower for t in ["tyler", "txcourts", "viewdocuments", "downloadresource"])
                    
                    valid_candidates.append((decoded, raw_url, is_tyler))
                
                # Selection Strategy:
                # 1. Pick the first "Tyler-like" link
                # 2. Fallback to the first non-blacklisted link
                
                selected_url = None
                
                # Check for Tyler High Priority
                for url, raw, is_good in valid_candidates:
                    if is_good:
                        selected_url = raw # Use RAW for the downloader to handle if needed, or decoded? 
                        # Hunter logic usually passes Raw to logic, but downloader decodes it again. Correct.
                        # Wait, lines 507-508: url = metadata.get('download_url'); real_url = self.downloader.decode...(url)
                        # So we store RAW.
                        selected_url = raw
                        break
                        
                # Fallback
                if not selected_url and valid_candidates:
                    selected_url = valid_candidates[0][1] # First raw
                    
                if selected_url:
                    metadata['download_url'] = selected_url
                    
            except Exception as e:
                self.log(f"Link Parsing Error (BS4): {e}", "ERROR")
                pass

            # Regex fallback if BS4 missing or no anchor-based match
            if not metadata.get('download_url'):
                try:
                    matches = re.finditer(REGEX_DOWNLOAD_LINK, html_body, re.IGNORECASE)
                    for m in matches:
                        raw_url = m.group(1)
                        decoded = self.downloader.decode_proofpoint_url(raw_url)
                        ignored_terms = ["zendesk", "privacy", "subscription", "microsoft", "help", "terms", "faq", "twitter", "facebook", "linkedin"]
                        if any(term in decoded.lower() for term in ignored_terms):
                            continue
                        metadata['download_url'] = raw_url
                        break
                except Exception as e:
                    self.log(f"Link Parsing Error (Regex Fallback): {e}", "ERROR")
        
        return metadata

    def _resolve_outlook_root_folder(self, namespace, account_hint: str):
        """
        Resolve the Outlook root folder/store reliably.

        Users typically enter an email address (SMTP). Outlook's `Namespace.Folders(...)`
        often expects the store display name, so we attempt multiple strategies.
        """
        if not account_hint:
            try:
                return namespace.GetDefaultFolder(6).Parent  # 6 = Inbox
            except Exception:
                return None

        # Strategy 1: direct access (works if account_hint is the store display name)
        try:
            return namespace.Folders(account_hint)
        except Exception:
            pass

        # Strategy 2: match by SMTP address, then use the DeliveryStore display name
        try:
            for acc in namespace.Accounts:
                try:
                    smtp = (acc.SmtpAddress or "").lower()
                except Exception:
                    smtp = ""
                if smtp and account_hint.lower() in smtp:
                    try:
                        return namespace.Folders.Item(acc.DeliveryStore.DisplayName)
                    except Exception:
                        return namespace.GetDefaultFolder(6).Parent
        except Exception:
            pass

        # Strategy 3: fallback to default store
        try:
            return namespace.GetDefaultFolder(6).Parent
        except Exception:
            return None

    def _resolve_output_dir(self, phase: str, configured_path: str | None) -> str:
        """
        Ensure the configured output directory is writable on THIS machine.

        This protects against "ghost config" shipping paths from a developer machine
        (e.g., `C:\\Users\\Kado\\...`) which will fail on other computers.
        """
        phase_key = "Phase1" if (phase or "").lower() == "phase1" else "Phase2"

        candidate = (configured_path or "").strip()
        if not candidate:
            candidate = str(app_paths.default_phase_output_dir(phase_key))

        # Normalize common formats: env vars, ~, and forward slashes.
        candidate = os.path.expandvars(os.path.expanduser(candidate)).replace("/", os.sep)

        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except Exception as e:
            fallback = str(app_paths.default_phase_output_dir(phase_key))
            try:
                os.makedirs(fallback, exist_ok=True)
            except Exception:
                pass

            self.log(
                f"Output path not writable: '{candidate}'. Using fallback '{fallback}'. ({e})",
                "WARN",
            )

            # Best-effort: update the config so the user sees the corrected path.
            try:
                conf.set(f"{phase_key}.Output", fallback)
                conf.save()
            except Exception:
                pass

            return fallback

    def run_cycle(self):
        # RESILIENCE WRAPPER
        from core.resilience import safe_trace, connect_outlook_robustly
        
        # ESSENTIAL: Initialize COM for this background thread
        pythoncom.CoInitialize()
        
        safe_trace("HunterV2 Cycle START (Thread Initialized)", "INFO")
        
        try:
            # 1. Attempt Robust Connection
            safe_trace("Attempting Outlook Connection...", "INFO")
            outlook, strategy = connect_outlook_robustly()
            
            if not outlook:
                safe_trace("CRITICAL: Failed to connect to Outlook via any strategy. Aborting cycle.", "CRITICAL")
                self.log("Outlook Connection Failed (Check agent_trace.log)", "ERROR")
                return

            safe_trace(f"Outlook Connected via: {strategy}", "INFO")

            # 2. Sequential Processing by Phase
            from core.resilience import safe_trace
            
            # HOT RELOAD: Re-read config at cycle start for toggle changes
            conf._load_config()
            self._reload_prefix_config()  # Reload Phase 2 prefix schema
            p1_enabled = conf.get("Phase1.Enabled", True)
            p2_enabled = conf.get("Phase2.Enabled", True)
            
            # --- PHASE 1 CYCLE ---
            # PRIORITY: Flat keys (from Settings UI) take precedence over nested config
            p1_folder = conf.get("Phase1.Input") or "Inbox"
            p1_output = self._resolve_output_dir("Phase1", conf.get("Phase1.Output"))
            
            if p1_enabled:
                safe_trace(f"Starting Phase 1 Scan: {p1_folder}", "INFO")
                if hasattr(self, 'status_writer') and self.status_writer:
                    self.status_writer.update("Phase1", "Scanning inbox for affidavits", "", "")
                self._ingest_new_emails(outlook, p1_folder, p1_output, phase="Phase1")
            else:
                safe_trace("Phase 1 DISABLED - Skipping intake (existing jobs continue)", "INFO")
            
            # --- PHASE 2 CYCLE ---
            # PRIORITY: Flat keys (from Settings UI) take precedence over nested config
            p2_folder = conf.get("Phase2.Input") or "Inbox"
            p2_output = self._resolve_output_dir("Phase2", conf.get("Phase2.Output"))
            
            if p2_enabled:
                safe_trace(f"Starting Phase 2 Scan: {p2_folder}", "INFO")
                if hasattr(self, 'status_writer') and self.status_writer:
                    self.status_writer.update("Phase2", "Scanning inbox for e-filing", "", "")
                self._ingest_new_emails(outlook, p2_folder, p2_output, phase="Phase2")
            else:
                safe_trace("Phase 2 DISABLED - Skipping intake (existing jobs continue)", "INFO")
            
            # --- PROCESS DELAYED PACKETS (ALWAYS RUNS) ---
            # Ensures pending Phase 2 merges complete even if intake is disabled
            # Read from new config structure: Phases.Phase2.AggregationMinutes
            p2_conf = conf.get("Phases", {}).get("Phase2", {})
            wait_min = p2_conf.get("AggregationMinutes") or conf.get("phase2", {}).get("wait_minutes", 20)
            if wait_min is None:
                wait_min = 20  # Default to 20 minutes
            if wait_min > 0:
                 if hasattr(self, 'status_writer') and self.status_writer:
                     self.status_writer.update("Phase2", "Processing delayed merge packets")
                 self._process_expired_packets(wait_minutes=wait_min)
            
            if hasattr(self, 'status_writer') and self.status_writer:
                self.status_writer.update("", "Cycle complete — waiting for next poll")
            safe_trace("HunterV2 Cycle END - Success", "INFO")
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            safe_trace(f"HunterV2 UNHANDLED EXCEPTION:\n{tb}", "CRITICAL")
            self.log(f"HunterV2 Critical Error: {e}", "ERROR")
        finally:
            # ESSENTIAL: Cleanup COM
            try:
                pythoncom.CoUninitialize()
            except: pass

    def _ingest_new_emails(self, outlook, target_folder_name, target_output_path, phase="Phase1"):
        """SEQUENTIAL PROCESSING: Scan + group by envelope, then process each envelope to completion."""
        from core.resilience import safe_trace
        
        target_account = conf.get_kvi("phase2.efiling_account") or conf.get("outlook_account") or ""
        # target_folder_name passed as argument now
        
        safe_trace(f"Config: Account='{target_account}' Folder='{target_folder_name}' Output='{target_output_path}'", "DEBUG")
        
        try:
            namespace = outlook.GetNamespace("MAPI")
            
            # CROSS-MAILBOX SUPPORT: Check if folder path starts with a different mailbox
            # E.g., if target_folder_name is "eaffidavits\Inbox\..." but account is "ai@pcpusa.net"
            folder_parts = target_folder_name.split("\\")
            first_part = folder_parts[0] if folder_parts else ""
            
            # Check if first_part matches any mailbox in namespace.Folders
            cross_mailbox_root = None
            for mailbox in namespace.Folders:
                mailbox_name = getattr(mailbox, "Name", "")
                if mailbox_name.lower() == first_part.lower():
                    cross_mailbox_root = mailbox
                    safe_trace(f"Cross-mailbox detected: Using '{mailbox_name}' instead of '{target_account}'", "INFO")
                    break
            
            if cross_mailbox_root:
                root = cross_mailbox_root
                # Strip the mailbox name from the folder path since we're already at that root
                target_folder_name = "\\".join(folder_parts[1:]) if len(folder_parts) > 1 else ""
            else:
                root = self._resolve_outlook_root_folder(namespace, target_account)
            
            try:
                root_name = getattr(root, "Name", None) or str(root)
            except Exception:
                root_name = "UNKNOWN"
            safe_trace(f"Outlook root resolved: {root_name}", "DEBUG")
            folder = self._get_folder_by_path(root, target_folder_name)
        except Exception as e:
            safe_trace(f"Folder Access Error: {e}", "ERROR")
            self.log(f"Folder Access Error: {e}", "ERROR")
            return

        if not folder:
            safe_trace(f"Folder '{target_folder_name}' NOT FOUND", "ERROR")
            self.log(f"Folder {target_folder_name} not found.", "ERROR")
            return

        items = folder.Items
        try:
            item_count = items.Count
            safe_trace(f"Folder '{folder.Name}' found. Item Count: {item_count}", "INFO")
            items.Sort("[ReceivedTime]", True)
        except Exception as e:
            safe_trace(f"Item Access/Sort Error: {e}", "ERROR")
            return
        
        PROCESSED_TAG = "PCP-Processed"
        
        # STEP 1: Scan and group by envelope
        envelope_groups = {}  # {envelope_id: [(msg, prefix, metadata), ...]}
        
        # Snapshot items to avoid 'Array index out of bounds' when emails
        # are moved out of the folder during processing (shrinks collection).
        snapshot = []
        for i in range(1, min(600, items.Count) + 1):
            try:
                snapshot.append(items.Item(i))
            except Exception:
                break  # Collection shifted, stop snapshotting
        
        safe_trace(f"Snapshot captured: {len(snapshot)} items", "DEBUG")
        
        for msg in snapshot:
            try:
                cats = msg.Categories or ""
                subject = msg.Subject
            except Exception:
                continue  # Stale reference, skip

            if PROCESSED_TAG in cats or "PCP-Packetized" in cats: 
                continue
            
            # v4.3.5: DB-backed scan ledger — Layer 2 defense
            entry_id = getattr(msg, 'EntryID', None)
            if entry_id:
                scan_count = self.scan_ledger.record_scan(entry_id)
                if scan_count == -1:
                    # Already finalized (COMPLETED/EXCEPTIONED) in DB — skip silently
                    continue
                if self.scan_ledger.should_circuit_break(entry_id, self.MAX_SCAN_RETRIES, self.SCAN_SAFETY_WINDOW):
                    self.log(f"CIRCUIT BREAKER: Email {entry_id[:20]}... scanned {scan_count}x over {self.SCAN_SAFETY_WINDOW}min. Exceptioning out.", "ERROR")
                    safe_trace(f"CIRCUIT BREAKER fired for EntryID {entry_id[:20]}... (count={scan_count})", "ERROR")
                    self.scan_ledger.mark_disposition(entry_id, 'EXCEPTIONED')
                    try:
                        msg.Categories = "PCP-Exception;PCP-CircuitBreaker"
                        msg.Save()
                    except Exception:
                        pass
                    try:
                        self._move_to_exceptions(msg, folder, phase)
                    except Exception:
                        pass
                    continue
            
            # subject = msg.Subject (Moved up)
            body = msg.Body
            
            # Check for "Filing Accepted" in subject (required per Logic Doc)
            # This method handles Filing Accepted emails ONLY — for both phases.
            # Phase 1 non-Filing-Accepted emails (Affidavits, M&O) are handled
            # by attachment extraction within this same pipeline.
            strict_subject = conf.get(f"{phase}.StrictSubject", True)
            if "Filing Accepted" not in subject:
                if strict_subject:
                    self.log(f"Subject Rejected (no 'Filing Accepted'): '{subject[:60]}'", "WARN")
                    self._move_to_exceptions(msg, folder, phase)
                continue
            
            # Sender validation per Logic Doc — must be Tyler Technologies
            # TODO: Re-enable after testing. Commented out for UAT with injected test emails.
            strict_sender = conf.get(f"{phase}.StrictSender", True)
            sender = ""
            try:
                sender = (msg.SenderEmailAddress or "").lower()
            except Exception:
                pass
            VALID_SENDER = "no-reply@efilingmail.tylertech.cloud"
            if strict_sender and sender and VALID_SENDER not in sender:
                self.log(f"Sender Rejected: '{sender}' (expected '{VALID_SENDER}')", "WARN")
                self._move_to_exceptions(msg, folder, phase)
                continue
            
            html_body = getattr(msg, "HTMLBody", None)
            metadata = self._parse_email_body(body, html_body, subject)
            
            lead_doc = metadata.get('lead_document', '')
            prefix = lead_doc[:4].upper() if lead_doc else "AXPM"  # Default to AXPM if no lead doc
            
            # Skip ignore list (config-driven, not hardcoded)
            if self.ignore_prefixes and any(p in prefix for p in self.ignore_prefixes):
                self.log(f"Audit: Classification=SILENT_SKIP Reason={prefix} in config exclusion list", "INFO")
                self._mark_as_processed(msg)
                continue

            # --- HARDENING: Strict Whitelist Check ---
            # If the derived prefix is not in our approved list, DO NOT PROCESS.
            # DYNAMIC: Include keys from SourceFolders (Custom User Mappings)
            custom_prefixes = list(conf.get("SourceFolders", {}).keys())
            allowed_set = set(self.actionable_prefixes + custom_prefixes)
            
            if prefix not in allowed_set:
                 self.log(f"HARDENING: Ignored/Skipped unapproved prefix '{prefix}' (No Action).", "INFO")
                 continue
            
            # Process all envelopes (including those without explicit lead doc)
            envelope_id = metadata.get('envelope_num')
            
            # --- FALLBACK: Attachment Scanning (Phase 1 Python Logic) ---
            if not envelope_id:
                try:
                    for att in msg.Attachments:
                        fname = att.FileName
                        # Look for Phase 1 Pattern: AX* (Affidavit)
                        if fname.upper().startswith("AX") and fname.lower().endswith(".pdf"):
                            # Use the filename as the unique Envelope ID
                            # Clean it up: remove extension
                            potential_id = fname[:-4] # Remove .pdf
                            envelope_id = potential_id
                            metadata['envelope_num'] = envelope_id
                            metadata['lead_document'] = fname
                            self.log(f"Fallback: Extracted Envelope ID '{envelope_id}' from attachment '{fname}'", "INFO")
                            break
                except Exception as att_err:
                     self.log(f"Attachment scan error: {att_err}", "DEBUG")

            if not envelope_id:
                self.log(f"Warning: No Envelope ID in '{subject[:50]}'. Moving to Exceptions.", "WARN")
                self._move_to_exceptions(msg, folder)
                continue
            
            # --- PHASE ROUTING: Filter by prefix to prevent duplicate processing ---
            # Phase 1 handles affidavits (immediate), Phase 2 handles petitions (delayed)
            if phase == "Phase1" and prefix not in self.phase1_prefixes:
                # Not a Phase 1 prefix, skip for now (Phase 2 will handle it)
                continue
            elif phase == "Phase2" and prefix not in self.phase2_prefixes:
                # Not a Phase 2 prefix, skip (already handled by Phase 1)
                continue
            
            # Add to group
            envelope_groups.setdefault(envelope_id, []).append((msg, prefix, metadata))
            
            # v4.3.5: Update scan ledger with the real envelope_id (was UNKNOWN at scan time)
            if entry_id:
                self.scan_ledger.record_scan(entry_id, envelope_id)  # Updates envelope_id in DB
        
        # STEP 2: Process each envelope sequentially to completion
        total_envelopes = len(envelope_groups)
        safe_trace(f"Found {total_envelopes} unique envelopes to process", "INFO")
        self.log(f"Found {total_envelopes} unique envelopes to process sequentially", "INFO")
        
        for idx, (envelope_id, msg_data) in enumerate(envelope_groups.items(), 1):
            # GRACEFUL SHUTDOWN: Check stop_event before each envelope
            if self.stop_event and self.stop_event.is_set():
                remaining = total_envelopes - idx + 1
                safe_trace(f"STOP REQUESTED: Aborting processing ({remaining} envelopes remaining)", "WARN")
                self.log(f"STOP: Graceful shutdown ({remaining} envelopes will be processed next run)", "WARN")
                return
            
            try:
                from core.sharepoint_logger import sp_logger # Late import for safety
                
                msg_count = len(msg_data)
                
                # v4.3.3: Retry tracking — exception out after max attempts
                self._envelope_attempts[envelope_id] = self._envelope_attempts.get(envelope_id, 0) + 1
                attempt = self._envelope_attempts[envelope_id]
                if attempt > self.MAX_ENVELOPE_RETRIES:
                    self.log(f"EXCEPTION: Envelope {envelope_id} exceeded max retries ({self.MAX_ENVELOPE_RETRIES}). Moving to Exceptions.", "ERROR")
                    safe_trace(f"Envelope {envelope_id} EXCEPTIONED after {self.MAX_ENVELOPE_RETRIES} failed attempts", "ERROR")
                    for msg, _, _ in msg_data:
                        try:
                            self._move_to_exceptions(msg, folder)
                        except Exception:
                            # Last resort: tag so we don't loop
                            try:
                                msg.Categories = "PCP-Exception"
                                msg.Save()
                            except Exception:
                                pass
                    del self._envelope_attempts[envelope_id]
                    continue
                
                safe_trace(f"[{idx}/{total_envelopes}] Processing Envelope {envelope_id} ({msg_count} emails, attempt {attempt})", "INFO")
                self.log(f"[{idx}/{total_envelopes}] Processing Envelope {envelope_id} ({msg_count} parts, attempt {attempt}/{self.MAX_ENVELOPE_RETRIES})", "INFO")
                
                # Live status update
                if hasattr(self, 'status_writer') and self.status_writer:
                    self.status_writer.update(
                        phase,
                        f"Processing envelope ({msg_count} parts)",
                        f"{idx}/{total_envelopes}",
                        str(envelope_id)
                    )
                
                # AUDIT: Log Chain of Custody Start
                # We don't have a job ID yet (0), but we record the envelope touch
                first_meta = msg_data[0][2] if msg_data else {}
                audit_meta = {
                    "envelope": envelope_id, 
                    "pcp_job_num": first_meta.get('pcp_job_num'),
                    "original_filename": "Email Batch",
                    "constituent_docs": [str(m[0].Subject)[:50] for m in msg_data]
                }
                sp_logger.log_action("DETECTION", 0, f"Processing started for Envelope {envelope_id}", status="INGESTING", metadata=audit_meta)
                
                if phase == "Phase1":
                    # IMMEDIATE PROCESSING
                    self._process_envelope_complete(envelope_id, msg_data, folder, target_output_path)
                    safe_trace(f"Envelope {envelope_id} DONE (Phase 1 Immediate)", "INFO")
                    # v4.3.5: Mark all emails for this envelope as COMPLETED in scan ledger
                    self.scan_ledger.mark_all_for_envelope(envelope_id, 'COMPLETED')
                else:
                    # DELAYED PROCESSING (PHASE 2)
                    self._packetize_envelope(envelope_id, msg_data, folder)
                    safe_trace(f"Envelope {envelope_id} PACKETIZED (Phase 2 Delayed)", "INFO")
                    # v4.3.5: Mark emails as COMPLETED in scan ledger (they're now in packet DB)
                    self.scan_ledger.mark_all_for_envelope(envelope_id, 'COMPLETED')
                
                # v4.3.3: Clear retry counter on success
                self._envelope_attempts.pop(envelope_id, None)
                
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                safe_trace(f"ERROR processing envelope {envelope_id}:\n{tb}", "ERROR")
                self.log(f"ERROR processing envelope {envelope_id}: {e}", "ERROR")
                
                # AUDIT: Log Failure
                sp_logger.log_action("PROCESSING_FAILURE", 0, f"Failed processing envelope {envelope_id}: {e}", status="ERROR", metadata={"envelope": envelope_id})
                
                # DASHBOARD: Create Failed Job Record so metrics capture it
                try:
                    job_manager.create_job(
                        filename=f"ERROR_{envelope_id}",
                        file_path="N/A",
                        source=f"Tyler: {envelope_id}",
                        initial_status="ERROR",
                        metadata={
                            "envelope_id": envelope_id,
                            "job_num": first_meta.get('pcp_job_num', 'N/A') if 'first_meta' in locals() else 'N/A', # Safe access
                            "reason": f"System Error: {str(e)[:50]}...",
                            "steps": "1. Investigate Logs (Generic Error). 2. Check Traceback.",
                            "error": str(e),
                            "traceback": tb,
                            "final_path": "N/A"
                        }
                    )
                except Exception as db_err:
                    safe_trace(f"Failed to create error job record: {db_err}", "ERROR")
                
                # Move to exceptions folder to prevent retry loop
                try:
                    exception_folder = self._get_exception_folder(folder, "Phase2")
                    moved_count = 0
                    for msg, _, _ in msg_data:
                        msg.Categories = "PCP-Processed"
                        msg.Save()
                        try: msg.Move(exception_folder)
                        except: pass # Move might fail if object invalid
                        moved_count += 1
                    safe_trace(f"Moved {moved_count} items to Exceptions", "WARN")
                except Exception as move_err:
                    safe_trace(f"Failed to move exception emails: {move_err}", "ERROR")

    def _process_envelope_complete(self, envelope_id, msg_data, source_folder, target_output_path):
        """Process ONE envelope completely: download -> merge -> intelligence -> job -> move emails."""
        # Capture email received time from first message
        email_received_time = None
        if msg_data and len(msg_data) > 0:
            try:
                first_msg = msg_data[0][0]
                email_received_time = first_msg.ReceivedTime
            except Exception as e:
                self.log(f"Could not capture ReceivedTime: {e}", "WARN")
        
        from utils.link_downloader import LinkExpiredError

        # Step 1: Download all parts for this envelope (v4.3.3 Tyler-Filename Dedup)
        # Download from ALL emails, but deduplicate by original Tyler filename.
        # This handles both patterns:
        #   Pattern 1: N emails → N different documents (each has unique Tyler filename)
        #   Pattern 2: N emails → same Tyler page (duplicate Tyler filenames detected & skipped)
        files = []
        seen_tyler_names = set()  # Track Tyler filenames to deduplicate across emails
        try:
            for msg, prefix, metadata in msg_data:
                # DEBUG: Check attachments
                count = msg.Attachments.Count
                if count == 0 and not metadata.get('download_url'):
                    self.log(f"DEBUG: Msg '{msg.Subject[:20]}' has 0 attachments and no Link.", "WARN")
                
                downloaded_files = self._download_message_parts(msg, envelope_id, prefix, metadata, phase="Phase1")
                if downloaded_files:
                    for f in downloaded_files:
                        tyler_name = f.get('original_name', '').upper().strip()
                        if tyler_name and tyler_name in seen_tyler_names:
                            self.log(f"Dedup: Skipping duplicate Tyler doc '{tyler_name}' for envelope {envelope_id} (already downloaded)", "INFO")
                            try:
                                os.remove(f['path'])
                            except Exception:
                                pass
                            continue
                        if tyler_name:
                            seen_tyler_names.add(tyler_name)
                        files.append(f)
        except LinkExpiredError:
            self.log(f"Envelope {envelope_id} contains EXPIRED links. Checking Fallback...", "WARN")
            
            # --- FALLBACK: Check OriginalFiles folder for pre-downloaded PDFs ---
            # Match by: 1) Lead document name, 2) Envelope ID in P2_* files, 3) Job number with transformed prefix
            FALLBACK_DIR = conf.get("FallbackDir", "")
            fallback_files = []
            
            # Phase 1 prefix transformations - USE CONFIG (not hardcoded)
            PHASE1_PREFIX_MAP = self.phase1_rename_map
            
            # Collect lead document info and extract job numbers
            lead_doc_names = set()
            job_numbers = set()
            transformed_names = set()  # What the file would be named after processing
            
            for msg, prefix, metadata in msg_data:
                lead_doc = metadata.get('lead_document', '')
                if lead_doc:
                    # Clean up the name (remove extension if partial, normalize)
                    lead_doc_clean = lead_doc.replace('.pdf', '').replace('.PDF', '').strip()
                    lead_doc_names.add(lead_doc_clean)
                    self.log(f"Fallback: Looking for lead document '{lead_doc_clean}' in OriginalFiles", "INFO")
                    
                    # Extract job number (everything after the 4-char prefix)
                    if len(lead_doc_clean) > 4:
                        source_prefix = lead_doc_clean[:4].upper()
                        job_num = lead_doc_clean[4:].strip('-_ ')
                        job_numbers.add(job_num)
                        
                        # If Phase 1 prefix, calculate transformed filename
                        if source_prefix in PHASE1_PREFIX_MAP:
                            target_prefix = PHASE1_PREFIX_MAP[source_prefix]
                            transformed_name = f"{target_prefix}{job_num}"
                            transformed_names.add(transformed_name)
                            self.log(f"Fallback: Phase 1 transform - looking for '{transformed_name}' (from {source_prefix}â†’{target_prefix})", "INFO")
            
            if os.path.exists(FALLBACK_DIR):
                env_str = str(envelope_id)
                for f in os.listdir(FALLBACK_DIR):
                    if not f.lower().endswith(".pdf"):
                        continue
                    fname_clean = f.replace('.pdf', '').replace('.PDF', '')
                    matched = False
                    
                    # Match Type 1: Exact lead document name (source prefix)
                    for lead_doc in lead_doc_names:
                        if lead_doc in fname_clean or fname_clean in lead_doc:
                            matched = True
                            self.log(f"Fallback: Found matching file '{f}' for lead doc '{lead_doc}'", "INFO")
                            break
                    
                    # Match Type 2: Transformed Phase 1 name (e.g., AX42A25B02646)
                    if not matched:
                        for transformed in transformed_names:
                            if transformed in fname_clean or fname_clean.startswith(transformed):
                                matched = True
                                self.log(f"Fallback: Found Phase 1 transformed file '{f}' matching '{transformed}'", "INFO")
                                break
                    
                    # Match Type 3: Job number with any Phase 1 target prefix
                    if not matched:
                        for job_num in job_numbers:
                            if job_num in fname_clean and len(job_num) >= 6:  # Avoid short matches
                                matched = True
                                self.log(f"Fallback: Found file '{f}' containing job number '{job_num}'", "INFO")
                                break
                    
                    # Match Type 4: Envelope ID in P2_* pattern (Phase 2)
                    if not matched and f.startswith("P2_") and env_str in f:
                        matched = True
                        self.log(f"Fallback: Found P2_* file '{f}' matching envelope {envelope_id}", "INFO")
                    
                    # Match Type 5: Envelope ID in AX40* pattern (Phase 2)
                    if not matched and fname_clean.startswith("AX40") and env_str in fname_clean:
                        matched = True
                        self.log(f"Fallback: Found AX40 file '{f}' containing envelope ID {envelope_id}", "INFO")
                    
                    if matched:
                        fallback_path = os.path.join(FALLBACK_DIR, f)
                        fallback_files.append({
                            'path': fallback_path,
                            'prefix': f[:4].upper() if len(f) >= 4 else "UNKN",
                            'original_name': f,
                            'timestamp': datetime.now()
                        })
            
            if fallback_files:
                self.log(f"Fallback SUCCESS: Found {len(fallback_files)} files for expired envelope {envelope_id}", "INFO")
                files = fallback_files  # Use fallback files instead
            else:
                self.log(f"Fallback MISS: No files in OriginalFiles for envelope {envelope_id} (lead docs: {lead_doc_names}, jobs: {job_numbers}). Marking EXPIRED.", "WARN")
            
                # Log to DB as EXPIRED Action
                try:
                    # We need a dummy filename for the log
                    dummy_name = f"EXPIRED_LINK_{envelope_id}"
                    job_manager.create_job(
                        filename=dummy_name,
                        file_path="N/A",
                        source=f"Tyler: {envelope_id}",
                        initial_status="EXPIRED",
                        metadata={
                            "envelope_id": envelope_id,
                            "job_num": msg_data[0][2].get('pcp_job_num', "UNKNOWN"),
                            "lead_doc": msg_data[0][0].Subject[:30],
                            "reason": "Link Expired (>45 Days)",
                            "steps": "No Action Required. Filed as Expired.",
                            "subject": msg_data[0][0].Subject,
                            "received_time": str(email_received_time)
                        }
                    )
                except Exception as dbe:
                     self.log(f"Failed to log Expired job to DB: {dbe}", "ERROR")

                # Move to configured Phase1 Exceptions folder
                try:
                     exception_folder = self._resolve_configured_folder("Phase1.Exceptions")
                     if exception_folder:
                         for msg, _, _ in msg_data:
                              msg.Move(exception_folder)
                     else:
                         self.log("Phase1.Exceptions folder not found in Outlook — emails NOT moved", "ERROR")
                except Exception as move_err:
                     self.log(f"Failed to move items to Expired folder: {move_err}", "ERROR")
                
                return # Exit processing for this envelope

        # --- FALLBACK CHECK: If no files downloaded, try fallback folder ---
        if not files:
            self.log(f"No files downloaded for envelope {envelope_id}. Trying fallback folder...", "WARN")
            FALLBACK_DIR = conf.get("FallbackDir", "")
            
            if os.path.exists(FALLBACK_DIR):
                # Collect lead document info from metadata
                lead_doc_names = set()
                job_numbers = set()
                
                for msg, prefix, metadata in msg_data:
                    lead_doc = metadata.get('lead_document', '')
                    if lead_doc:
                        lead_doc_clean = lead_doc.replace('.pdf', '').replace('.PDF', '').strip()
                        lead_doc_names.add(lead_doc_clean)
                        if len(lead_doc_clean) > 4:
                            job_num = lead_doc_clean[4:].strip('-_ ')
                            job_numbers.add(job_num)
                        self.log(f"Fallback: Looking for lead doc '{lead_doc_clean}'", "INFO")
                
                # Search fallback folder
                for f in os.listdir(FALLBACK_DIR):
                    if not f.lower().endswith(".pdf"):
                        continue
                    fname_clean = f.replace('.pdf', '').replace('.PDF', '')
                    matched = False
                    
                    # Match by lead document name
                    for lead_doc in lead_doc_names:
                        if lead_doc in fname_clean or fname_clean in lead_doc:
                            matched = True
                            self.log(f"Fallback: Matched file '{f}' to lead doc '{lead_doc}'", "INFO")
                            break
                    
                    # Match by job number
                    if not matched:
                        for job_num in job_numbers:
                            if job_num in fname_clean and len(job_num) >= 6:
                                matched = True
                                self.log(f"Fallback: Matched file '{f}' by job number '{job_num}'", "INFO")
                                break
                    
                    if matched:
                        fallback_path = os.path.join(FALLBACK_DIR, f)
                        files.append({
                            'path': fallback_path,
                            'prefix': f[:4].upper() if len(f) >= 4 else "UNKN",
                            'original_name': f,
                            'timestamp': datetime.now()
                        })
                
                if files:
                    self.log(f"Fallback SUCCESS: Found {len(files)} files for envelope {envelope_id}", "INFO")

        if not files:
            self.log(f"No files downloaded for envelope {envelope_id}. Moving to Exceptions.", "ERROR")
            
            # DASHBOARD: Log "No Files" Error
            try:
                job_manager.create_job(
                    filename=f"ERROR_NOFILES_{envelope_id}",
                    file_path="N/A",
                    source=f"Tyler: {envelope_id}",
                    initial_status="ERROR",
                    metadata={
                        "envelope_id": envelope_id,
                        "job_num": msg_data[0][2].get('pcp_job_num', "N/A") if msg_data else "N/A",
                        "reason": "Download Failed: No Files extracted.",
                        "steps": "1. Check emails in 'AI Exceptions'. 2. Verify links manually.",
                    }
                )
            except Exception as db_err:
                 self.log(f"Failed to log No Files error: {db_err}", "ERROR")
            # CRITICAL LOOP BREAKER: Move to exceptions
            try:
                exception_folder = self._get_exception_folder(source_folder, "Phase2")
                for msg, _, _ in msg_data:
                    # self._mark_as_processed(msg) # Optional tag
                    try: msg.Move(exception_folder)
                    except: pass
            except Exception as e:
                self.log(f"Failed to move empty envelope {envelope_id} to exceptions: {e}", "CRITICAL")
            return
        
        # Step 2: Sort files (AX40 petition must be first)
        main_petitions = [f for f in files if f['prefix'] == "AX40"]
        attachments = [f for f in files if f['prefix'] != "AX40"]
        sorted_files = main_petitions + attachments
        
        if not main_petitions:
            self.log(f"Warning: No AX40 found in Envelope {envelope_id}. Ordering by timestamp.", "WARN")
            sorted_files = sorted(files, key=lambda x: x['timestamp'])
        
        # Step 3: Extract comments for intelligence
        all_comments = []
        
        # ADDED: Include the "Accepted Comments" parsed from the email body
        email_metadata = msg_data[0][2] if msg_data else {}
        email_comments = email_metadata.get('accepted_comments', '')
        if email_comments:
             all_comments.append(f"[Email Link Comments]: {email_comments}")

        for file_info in sorted_files:
            path = file_info['path']
            if os.path.exists(path):
                comments = self.intel.extract_comments(path)
                if comments: 
                    all_comments.append(f"[{file_info['prefix']} Document]: {comments}")
        
        # Step 4: Run intelligence + flagging
        full_comment_str = "\n".join(all_comments)
        has_action, matched = self.intel.analyze_text(full_comment_str)
        classification = "ACTION_FLAGGED" if has_action else "STANDARD_PROCESS"
        self.log(f"Audit: Env={envelope_id} Classification={classification} Matched={matched}", "INFO")
        
        # Step 5: Merge PDFs
        writer = PdfWriter()
        valid_files_count = 0
        for f_info in sorted_files:
            path = f_info['path']
            if os.path.exists(path):
                try:
                    reader = PdfReader(path)
                    for page in reader.pages:
                        writer.add_page(page)
                    valid_files_count += 1
                except Exception as pdf_err:
                    self.log(f"WARNING: Corrupt/unreadable PDF skipped: {f_info.get('original_name', path)} — {pdf_err}", "WARN")
            else:
                self.log(f"Warning: Part missing {path}", "WARN")
        
        if valid_files_count == 0:
            self.log(f"ERROR: No valid files to merge for envelope {envelope_id}. Skipping.", "ERROR")
            return
        
        # Check for Phase 1 Mapping (e.g. AX02 -> AX42)
        rename_rules = conf.get("naming_rules", {})
        if not rename_rules:
             rename_rules = conf.get("Phases", {}).get("Phase1", {}).get("RenameMap", {})
        # HARDCODED FALLBACK (v4.3.2): Prevent Phase 1 docs from falling through
        # to Phase 2 AX40 naming if config.json is missing naming_rules
        if not rename_rules:
             rename_rules = {"AX02": "AX42", "AX03": "AX43", "AX07": "AX47", "AX09": "AX89"}
             self.log("WARNING: naming_rules missing from config. Using hardcoded Phase 1 defaults.", "WARN")
        
        # Extract lead_prefix from first file
        lead_prefix = sorted_files[0]['prefix'] if sorted_files else "UNKN"
        final_prefix = None
        
        if lead_prefix in rename_rules:
             final_prefix = rename_rules[lead_prefix]
        # Check if already in target format (AX42 -> AX42)
        elif lead_prefix in rename_rules.values():
             final_prefix = lead_prefix
             
        if final_prefix:
            # PHASE 1 LOGIC: Prefix + JobNum
            # We need the "Job Number" (e.g. A25B01085)
            # Try metadata first, then extract from filename
            first_meta = msg_data[0][2] if msg_data else {}
            job_num = first_meta.get('pcp_job_num')
            
            if not job_num or job_num == "UNKNOWN":
                 # Extract from file path - ensure we strip known source prefixes if they overlap
                 full_name = os.path.basename(sorted_files[0]['path']).replace(".pdf", "").replace(".PDF", "")
                 if full_name.upper().startswith(lead_prefix.upper()):
                      job_num = full_name[len(lead_prefix):].strip(" -_")
                 else:
                      job_num = self._extract_job_num(sorted_files[0]['path'])

            final_name = f"{final_prefix}{job_num}.pdf"
            self.log(f"Naming Logic: Phase 1 ({lead_prefix}->{final_prefix}) + Job {job_num} -> {final_name}", "INFO")
        else:
            # PHASE 2 LOGIC: AX40 + PCP Job Number (from lead doc filename)
            lead_doc = email_metadata.get('lead_document', '')
            if lead_doc and len(lead_doc) > 4:
                p2_job_num = lead_doc.replace('.pdf', '').replace('.PDF', '')[4:].strip(' -_')
            else:
                p2_job_num = email_metadata.get('pcp_job_num', envelope_id)
            final_name = f"AX40{p2_job_num}.pdf"
            self.log(f"Naming Logic: Phase 2 (Petition) JobNum={p2_job_num} -> {final_name}", "INFO")

        output_dir = target_output_path
        os.makedirs(output_dir, exist_ok=True)
        final_path = os.path.join(output_dir, final_name)
        
        with open(final_path, "wb") as f:
            writer.write(f)
        
        # AUDIT: Log file write step
        self.log(f"PDF merged and saved to: {final_path}", "INFO")
        
        # Step 7: Create job in database
        processing_time = datetime.now()
        service_type = "AFFIDAVITS" if final_prefix else "PROJECT_2"
        job_id = job_manager.create_job(
            filename=final_name,
            file_path=final_path,
            service_type=service_type,
            initial_status="FILED",
            source=f"Tyler: {envelope_id}",
            metadata={
                "envelope": envelope_id,
                "classification": classification,
                "merged_parts": [f['prefix'] for f in sorted_files],
                "potential_actions": matched,
                "part_count": len(files),
                "audit_trace": f"Merged {len(files)} parts. Lead={sorted_files[0]['prefix']}.",
                # --- NEW COMPLIANCE FIELDS ---
                "original_filename": sorted_files[0].get('original_name', 'Unknown'),
                "new_filename": final_name,
                "final_path": final_path,
                "constituent_docs": [f.get('original_name', 'Unknown') for f in sorted_files],
                "merged_link": final_path,
                "pcp_job_num": email_metadata.get('pcp_job_num', ''),
                "case_num": email_metadata.get('case_num', ''),
                "court": email_metadata.get('court', ''),
                "case_style": email_metadata.get('case_style', ''),
                "accepted_comments": email_metadata.get('accepted_comments', ''),
                "date_submitted_raw": email_metadata.get('date_submitted_raw'),
                "date_accepted_raw": email_metadata.get('date_accepted_raw'),
                
                # --- ENHANCED DASHBOARD & AUDIT ---
                "lead_doc": email_metadata.get('lead_document') or (msg_data[0][0].Subject[:50] if msg_data else "Unknown"),
                "reason": "Filing Accepted (Phase 1/2 Match)",
                "steps": "Archived Successfully",
                
                # --- TIMESTAMP AUDIT ---
                "email_received_at": str(email_received_time) if email_received_time else None,
                "email_processed_at": processing_time.strftime("%Y-%m-%d %H:%M:%S")
            }
        )
        
        # AUDIT TRAIL: Log all processing steps to workflow_log
        job_manager.append_workflow_log(job_id, f"Downloaded {len(files)} files for envelope {envelope_id}")
        job_manager.append_workflow_log(job_id, f"Merged {valid_files_count} PDFs into single document")
        job_manager.append_workflow_log(job_id, f"Renamed: {sorted_files[0].get('original_name', 'Unknown')} -> {final_name}")
        job_manager.append_workflow_log(job_id, f"Saved to: {final_path}")
        job_manager.append_workflow_log(job_id, f"Classification: {classification}" + (f" (Flagged: {', '.join(matched)})" if matched else ""))
        
        job_manager.update_job_column(job_id, "raw_comments", full_comment_str)
        job_manager.update_job_column(job_id, "action_flag", 1 if has_action else 0)
        
        # AUDIT: Log completion with full 30-column chain of custody
        from core.sharepoint_logger import sp_logger
        sp_logger.log_action(
            "FILE_OUTPUT",
            job_id,
            f"Merged {len(sorted_files)} files to {final_name}",
            status="FILED",
            metadata={
                'original_filename': sorted_files[0].get('original_name', 'Unknown'),
                'new_filename': final_name,
                'pcp_job_num': metadata.get('pcp_job_num', ''),
                'envelope': envelope_id,
                'case_num': metadata.get('case_num', ''),
                'court': metadata.get('court', ''),
                'case_style': metadata.get('case_style', ''),
                'accepted_comments': metadata.get('accepted_comments', ''),
                'source_path': sorted_files[0].get('path', ''),
                'final_path': final_path,
                'constituent_docs': [f.get('original_name', 'Unknown') for f in sorted_files],
                'lead_doc': metadata.get('lead_document', ''),
                'original_prefix': lead_prefix,
                'target_prefix': final_prefix or 'AX40',
                'action_flag': 1 if has_action else 0,
                'matched_phrases': ', '.join(matched) if matched else '',
                'phase': 'Phase1' if final_prefix else 'Phase2',
                'part_count': len(sorted_files),
                'email_received': str(email_received_time) if email_received_time else '',
                'email_subject': msg_data[0][0].Subject if msg_data else '',
                'reason': 'Filing Accepted',
                'steps': 'Archived Successfully',
            }
        )
        
        # Step 8: Move ALL emails for this envelope to completed folder (WITH TRANSACTION SAFETY)
        # Safety: Set status to MOVING before move, then ARCHIVED after.
        # If interrupted, startup reconciliation can handle MOVING jobs.
        try:
            job_manager.update_job_status(job_id, 'MOVING', log_msg="Preparing to move emails to Completed folder")
            
            dest_folder = self._resolve_configured_folder("Phase1.Completed")
            completed_name = conf.get("Phase1.Completed", "Phase1.Completed")
            moved_count = 0
            if dest_folder:
                for msg, _, _ in msg_data:
                    try:
                        msg.Move(dest_folder)
                        moved_count += 1
                    except Exception as move_ex:
                        self.log(f"Warning: Could not move email: {move_ex}", "WARN")
                
                if moved_count > 0:
                    self.log(f"Moved {moved_count} emails to '{completed_name}'", "INFO")
            else:
                self.log(f"Phase1.Completed folder not found in Outlook ('{completed_name}') — emails NOT moved", "ERROR")
            
            # Mark as ARCHIVED after successful move
            job_manager.update_job_status(job_id, 'ARCHIVED', log_msg=f"Emails moved to Completed ({moved_count} items)")
            job_manager.append_workflow_log(job_id, f"Moved {moved_count} emails to '{completed_name}'")
            job_manager.append_workflow_log(job_id, f"COMPLETE - Archived successfully")
        except Exception as move_err:
            self.log(f"Email Move Error: {move_err}", "WARN")
            job_manager.append_workflow_log(job_id, f"WARNING: Email move failed - {move_err}")
            # Keep status as MOVING - will be reconciled on startup
        
        self.log(f"Envelope {envelope_id} COMPLETE: {final_name} (Action={has_action})", "SUCCESS")

    def _packetize_envelope(self, envelope_id, msg_data, source_folder):
        """Phase 2: Add emails to PacketManager queue and tag them as Packetized."""
        from core.resilience import safe_trace
        
        # v4.3.5: GUARD — If packet already exists in DB, skip re-downloading.
        # The PCP-Packetized category may not persist on injected test emails,
        # causing infinite re-ingestion. Use the DB as the source of truth.
        existing = self.packet_mgr.get_packet_status(envelope_id)
        if existing is not None:
            # Packet already in DB — just re-tag emails and skip
            for msg, prefix, metadata in msg_data:
                try:
                    cats = getattr(msg, 'Categories', '') or ''
                    if 'PCP-Packetized' not in cats:
                        msg.Categories = (cats + ';PCP-Packetized') if cats else 'PCP-Packetized'
                        msg.Save()
                except Exception:
                    pass
            self.log(f"Envelope {envelope_id} already in packet DB (status={existing}). Re-tagged emails, skipping re-download.", "INFO")
            return
        
        # Get Received Time from first message (Persistent Delay)
        try:
            first_msg = msg_data[0][0]
            # pywintypes.Time -> datetime conversion might be needed, or pass as is if PacketManager handles it.
            # PacketManager converts to str.
            received_time = first_msg.ReceivedTime
        except:
            received_time = datetime.now()
            
        processed_count = 0
        seen_tyler_names = set()  # v4.3.3: Tyler-filename dedup across emails
        
        for msg, prefix, metadata in msg_data:
            # v4.3.3: Download from ALL emails, deduplicate by Tyler filename.
            # Each email may point to a DIFFERENT document (AX40, AXPB, AXPE).
            # True duplicates (same Tyler page) are caught by filename matching.
            files = self._download_message_parts(msg, envelope_id, prefix, metadata, phase="Phase2")
            
            if not files:
                 self.log(f"Warning: No files extracted for Packet {envelope_id} (Msg: {msg.Subject})", "WARN")
                 skip_tag = conf.get("Phase2.SkipTagOnNoFiles", False)  # v4.3.3: Default False — always tag to prevent infinite re-scan loop
                 if skip_tag:
                     continue
            entry_id = getattr(msg, "EntryID", "UNKNOWN")
            
            for f in files:
                # v4.3.3: Tyler-filename dedup — skip duplicate Tyler docs across emails
                tyler_name = f.get('original_name', '').upper().strip()
                if tyler_name and tyler_name in seen_tyler_names:
                    self.log(f"Dedup: Skipping duplicate Tyler doc '{tyler_name}' for packet {envelope_id} (already downloaded)", "INFO")
                    try:
                        os.remove(f['path'])
                    except Exception:
                        pass
                    continue
                if tyler_name:
                    seen_tyler_names.add(tyler_name)
                
                # Classify per-file (v4.2): use the file's own prefix + full-filename CL scan
                file_prefix = f.get('prefix', prefix)
                file_original_name = f.get('original_name', '')
                
                # Full-filename CL override: if the filename has CL suffix, classify as CLERK_LETTER
                if self._is_clerk_letter(file_original_name):
                    doc_type = "CLERK_LETTER"
                else:
                    doc_type = self._classify_document_type(file_prefix)
                
                reopen_completed = conf.get("Phase2.ReopenCompletedOnNewFiles", True)
                self.packet_mgr.add_to_packet(
                    envelope_id, 
                    f['path'], 
                    file_prefix, 
                    entry_id, 
                    first_seen=received_time,
                    doc_type=doc_type,  # LEAD, ATTACHMENT, CLERK_LETTER, CORRECTION
                    reopen_completed=reopen_completed,
                    original_name=f.get('original_name', ''),
                    email_metadata=metadata  # Store email fields for CSV enrichment
                )
            
        # v4.3.5: ALWAYS register the envelope in the packet DB, even if zero files downloaded.
        # This ensures the DB guard (L1217) catches re-scans on subsequent cycles.
        # Without this, empty downloads → no DB record → DB guard returns None → infinite loop.
        if self.packet_mgr.get_packet_status(envelope_id) is None:
            self.packet_mgr.add_to_packet(
                envelope_id,
                file_path="(no-file)",
                prefix="NONE",
                message_entry_id=getattr(msg_data[0][0], "EntryID", "UNKNOWN"),
                first_seen=received_time,
                doc_type="PLACEHOLDER",
                reopen_completed=True,
                original_name="",
                email_metadata=msg_data[0][2] if msg_data else {}
            )
            self.log(f"Registered packet {envelope_id} in DB (placeholder — {processed_count} emails processed, {len(seen_tyler_names)} files)", "INFO")
        
        # Tag ALL emails as Packetized
        for msg, prefix, metadata in msg_data:
            try:
                msg.Categories = "PCP-Packetized"
                msg.Save()
                processed_count += 1
            except Exception as e:
                self.log(f"Failed to tag email as Packetized: {e}", "WARN")
            
        self.log(f"Packetized {processed_count} emails for Envelope {envelope_id}. Waiting for timeout.", "INFO")

    def _is_clerk_letter(self, filename):
        """Full-filename discard scanning (v4.2): detect CL suffix in document names.
        Naming convention: AX40(PCP Job #)CL.pdf — CL is a suffix, not a prefix.
        Also catches standalone 'CL' prefix documents."""
        name_upper = filename.upper().replace(".PDF", "").replace(".pdf", "").strip()
        # Check for CL suffix: e.g. AX40A25C05955CL
        if name_upper.endswith("CL"):
            return True
        # Check for CL as a standalone prefix (legacy)
        if name_upper.startswith("CL"):
            return True
        return False
    
    def _download_message_parts(self, msg, envelope_id, prefix, metadata, phase="Phase2"):
        """Download all PDF parts from a single message (attachments or links).
        Handles multi-document Tyler pages (v4.2) and applies CL suffix filtering.
        phase param (v4.3.3): Controls which prefix whitelist is applied on multi-doc pages."""
        from core.resilience import safe_trace
        from utils.link_downloader import MultiDocumentResult
        
        files = []
        ts = datetime.now().strftime("%H%M%S_%f")
        
        # Try direct attachments first
        for att in msg.Attachments:
            if att.FileName.lower().endswith(".pdf"):
                # --- FULL-FILENAME DISCARD SCANNING (v4.2) ---
                if self._is_clerk_letter(att.FileName):
                    self.log(f"CL Discard: Attachment '{att.FileName}' identified as Clerk Letter (full-filename scan). Skipping.", "INFO")
                    continue
                
                temp_name = f"P2_{envelope_id}_{ts}_{att.FileName}"
                temp_path = os.path.join(self.download_path, temp_name)
                att.SaveAsFile(temp_path)
                
                # HARDENING: Extract prefix from ACTUAL filename, not email-parsed value
                # v4.3.5: Include ALL known prefixes (Phase 1 + Phase 2)
                ALL_KNOWN_PFX = list(set(self.phase1_prefixes + self.phase2_prefixes +
                                        ["AX02", "AX03", "AX07", "AX09", "BX09", "AX42", "AX43", "AX47", "AX89",
                                         "AX40", "AXPB", "AXPE", "AXPM", "AXPL", "AXPA"]))
                raw_filename_prefix = att.FileName[:4].upper()
                
                if raw_filename_prefix in ALL_KNOWN_PFX:
                     actual_prefix = raw_filename_prefix
                elif prefix.upper() in ALL_KNOWN_PFX:
                     actual_prefix = prefix
                else:
                     actual_prefix = prefix  # v4.3.5: Use email prefix as fallback, not raw filename prefix
                
                files.append({
                    'path': temp_path,
                    'prefix': actual_prefix,
                    'original_name': att.FileName,
                    'timestamp': datetime.now()
                })
        
        # Fallback to link download if no attachments
        if not files and metadata.get('download_url'):
            self.log("No attachments found, attempting Link Download...", "INFO")
            url = metadata.get('download_url')
            real_url = self.downloader.decode_proofpoint_url(url)
            temp_name = f"P2_{envelope_id}_{ts}_DL_{prefix}.pdf"
            temp_path = os.path.join(self.download_path, temp_name)
            
            try:
                if self.downloader.download_file(real_url, temp_path):
                    # --- v4.3.5: Probe for REAL filename from Content-Disposition ---
                    job_num = metadata.get('pcp_job_num')
                    original_name = f"{job_num}.pdf" if job_num else "Link Download"
                    resolved_prefix = prefix  # Start with email-parsed prefix
                    
                    probed_name = self.downloader.probe_filename(real_url)
                    if probed_name:
                        original_name = probed_name
                        # Derive prefix from probed filename (e.g., AX40A26200835.PDF -> AX40)
                        probed_pfx = probed_name[:4].upper() if len(probed_name) >= 4 else ''
                        ALL_KNOWN_PFX = list(set(self.phase1_prefixes + self.phase2_prefixes))
                        if probed_pfx in ALL_KNOWN_PFX:
                            resolved_prefix = probed_pfx
                            self.log(f"Link filename resolved: '{probed_name}' -> prefix '{resolved_prefix}'", "INFO")
                    
                    if envelope_id or job_num:
                        try:
                            reader = PdfReader(temp_path)
                            text_content = ""
                            for p_idx in range(min(3, len(reader.pages))):
                                text_content += reader.pages[p_idx].extract_text()
                            
                            PHASE_1_PREFIXES = ["AX02", "AX42", "AX03", "AX43", "AX07", "AX47", "AX09", "AX89"]
                            is_affidavit = resolved_prefix in PHASE_1_PREFIXES
                            
                            primary_verified = False
                            if is_affidavit:
                                if job_num and job_num in text_content:
                                    safe_trace(f"Integrity Verified (Primary): Job Num '{job_num}' confirmed in Affidavit.", "INFO")
                                    primary_verified = True
                                elif job_num: 
                                    safe_trace(f"Integrity Warning: Primary Job Num '{job_num}' NOT FOUND in Affidavit {temp_name}", "WARN")
                            else:
                                if envelope_id and envelope_id in text_content:
                                    safe_trace(f"Integrity Verified (Primary): Envelope {envelope_id} confirmed in Phase 2 Doc.", "INFO")
                                    primary_verified = True
                                elif envelope_id:
                                    safe_trace(f"Integrity Warning: Primary Envelope {envelope_id} NOT FOUND in Phase 2 Doc {temp_name}", "WARN")

                            if is_affidavit and envelope_id and envelope_id not in text_content:
                                safe_trace(f"Integrity Note: Secondary Envelope {envelope_id} missing from Affidavit (Expected).", "INFO")
                            if not is_affidavit and job_num and job_num not in text_content:
                                safe_trace(f"Integrity Note: Secondary Job Num '{job_num}' missing from Phase 2 Doc.", "INFO")
                        except Exception as verify_err:
                            safe_trace(f"Integrity Check Failed (Read Error): {verify_err}", "WARN")
                    
                    files.append({
                        'path': temp_path,
                        'prefix': resolved_prefix,
                        'original_name': original_name,
                        'timestamp': datetime.now()
                    })
                    self.log(f"Download Success: {temp_name} (resolved: {original_name}, prefix: {resolved_prefix})", "INFO")
                else:
                    self.log(f"Download Failed for Envelope {envelope_id}", "ERROR")
                    
            except MultiDocumentResult as mdr:
                # --- TYLER MULTI-DOCUMENT PAGE (v4.2) ---
                # The Tyler page listed multiple documents. Download each one individually.
                self.log(f"Tyler Multi-Document Page for Envelope {envelope_id}: {len(mdr.documents)} documents found", "INFO")
                
                # Clean up the HTML landing page that was saved as a .pdf before the exception
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                        self.log(f"Cleaned up HTML landing page: {temp_name}", "DEBUG")
                    except Exception:
                        pass
                
                for i, doc_info in enumerate(mdr.documents):
                    doc_url = doc_info['url']
                    doc_filename = doc_info['filename']
                    
                    # v4.3.4: If Tyler HTML gave a generic filename (doc_0.pdf etc.),
                    # probe the actual download URL for the real filename via Content-Disposition
                    if doc_filename.startswith('doc_') or doc_filename.lower() in ('document.pdf', 'download.pdf'):
                        probed = self.downloader.probe_filename(doc_url)
                        if probed:
                            self.log(f"Tyler filename resolved: '{doc_filename}' -> '{probed}'", "INFO")
                            doc_filename = probed
                    
                    # --- FULL-FILENAME DISCARD SCANNING (v4.2) ---
                    name_upper = doc_filename.upper().replace(".PDF", "")
                    if self._is_clerk_letter(doc_filename) or "AX69" in name_upper or "AX81" in name_upper:
                        self.log(f"CL/Discard: Tyler doc '{doc_filename}' identified as discardable (full-filename scan). Skipping download.", "INFO")
                        continue
                    
                    # Determine prefix from the Tyler-provided filename
                    doc_prefix = doc_filename[:4].upper() if len(doc_filename) >= 4 else prefix
                    
                    # v4.3.3: If Tyler gives a generic filename (doc_0.pdf, document.pdf, etc.)
                    # that doesn't match ANY known prefix, fall back to the email's prefix.
                    all_known_prefixes = set(self.phase1_prefixes + self.phase2_prefixes)
                    if doc_prefix not in all_known_prefixes:
                        self.log(f"Tyler generic filename '{doc_filename}' (prefix '{doc_prefix}') — falling back to email prefix '{prefix}'", "INFO")
                        doc_prefix = prefix
                    
                    # --- PHASE-AWARE PREFIX WHITELIST (v4.3.3) ---
                    # Only apply prefix whitelist for the ACTIVE phase.
                    # Phase 2: Only download Phase 2 actionable prefixes (AX40/AXPB/AXPE/AXPM/AXPL/AXPA)
                    # Phase 1: Only download Phase 1 prefixes (AX02/AX03/AX07/AX09)
                    if phase == "Phase2" and doc_prefix not in self.phase2_prefixes:
                        self.log(f"Non-Phase2 prefix: Tyler doc '{doc_filename}' has prefix '{doc_prefix}' — not a Phase 2 actionable prefix. Skipping.", "INFO")
                        continue
                    elif phase == "Phase1" and doc_prefix not in self.phase1_prefixes:
                        self.log(f"Non-Phase1 prefix: Tyler doc '{doc_filename}' has prefix '{doc_prefix}' — not a Phase 1 prefix. Skipping.", "INFO")
                        continue
                    
                    # Download this individual document
                    doc_ts = datetime.now().strftime("%H%M%S_%f")
                    doc_temp_name = f"P2_{envelope_id}_{doc_ts}_{i}_DL_{doc_prefix}.pdf"
                    doc_temp_path = os.path.join(self.download_path, doc_temp_name)
                    
                    try:
                        if self.downloader.download_file(doc_url, doc_temp_path):
                            files.append({
                                'path': doc_temp_path,
                                'prefix': doc_prefix,
                                'original_name': doc_filename,
                                'timestamp': datetime.now()
                            })
                            self.log(f"Tyler Multi-Doc Download [{i+1}/{len(mdr.documents)}]: {doc_filename} -> {doc_prefix}", "INFO")
                        else:
                            self.log(f"Tyler Multi-Doc Download FAILED [{i+1}]: {doc_filename}", "ERROR")
                    except Exception as dl_err:
                        self.log(f"Tyler Multi-Doc Download ERROR [{i+1}] {doc_filename}: {dl_err}", "ERROR")
                
                if files:
                    self.log(f"Tyler Multi-Doc Complete: {len(files)} actionable documents downloaded for Envelope {envelope_id}", "INFO")
                else:
                    self.log(f"Tyler Multi-Doc: All {len(mdr.documents)} documents were discarded (CL/AX69/AX81) for Envelope {envelope_id}", "WARN")
        
        return files

    def _process_expired_packets(self, wait_minutes=0.083):
        """Checks the queue for packets >wait_minutes old and merges them. (0.083 = 5 seconds for testing)"""
        expired = self.packet_mgr.get_expired_packets(wait_minutes=wait_minutes)
        self.log(f"DEBUG AGGREGATOR: Found {len(expired)} expired packets to process", "INFO")
        
        for packet in expired:
            try:
                env_id = packet['envelope_id']
                files = packet['metadata']['files']
                
                self.log(f"Processing Expired Packet: Envelope {env_id} ({len(files)} files)", "INFO")
                
                # Sort by doc_type using config-driven MergeOrder
                # Order: LEAD (AX40, AX69) -> Attachments -> CLERK_LETTER (CL) last
                p2_conf = conf.get("Phases", {}).get("Phase2", {})
                merge_order = p2_conf.get("MergeOrder", ["LEAD", "AXPB", "AXPE", "AXPM", "AXPL", "AXPA", "CL"])
                
                # Create priority map: doc_type -> order index
                # LEAD=0, ATTACHMENT=1-5 by prefix, CLERK_LETTER=last
                def get_sort_key(file_info):
                    doc_type = file_info.get('doc_type', 'UNKNOWN')
                    prefix = file_info.get('prefix', '')
                    
                    if doc_type == "LEAD":
                        return (0, 0)  # Lead docs first
                    elif doc_type == "CORRECTION":
                        return (1, 0)  # Corrections after lead
                    elif doc_type == "ATTACHMENT":
                        # Sort by prefix position in MergeOrder
                        try:
                            pos = merge_order.index(prefix) if prefix in merge_order else 50
                        except:
                            pos = 50
                        return (2, pos)  # Attachments in configured order
                    elif doc_type == "CLERK_LETTER":
                        return (99, 0)  # CL always last
                    else:
                        return (50, 0)  # Unknown in middle
                
                sorted_files = sorted(files, key=get_sort_key)
                
                # Identify lead document for final naming
                lead_docs = [f for f in sorted_files if f.get('doc_type') == 'LEAD']
                if not lead_docs:
                    # Fallback: check for AX40/AX69 prefix
                    lead_prefixes = p2_conf.get("Prefixes", {}).get("Lead", ["AX40", "AX69"])
                    lead_docs = [f for f in sorted_files if f.get('prefix') in lead_prefixes]
                
                if not lead_docs:
                    # v4.3.3: HARD GATE — No merge without a lead document.
                    # Check how long the packet has been waiting
                    import time
                    packet_first_seen = packet.get('metadata', {}).get('files', [{}])[0].get('timestamp', '')
                    max_wait_minutes = int(conf.get("Phase2.MaxLeadWaitMinutes", 60))
                    
                    try:
                        first_ts = datetime.fromisoformat(packet_first_seen) if packet_first_seen else datetime.now()
                        elapsed_minutes = (datetime.now() - first_ts).total_seconds() / 60
                    except Exception:
                        elapsed_minutes = 0
                    
                    if elapsed_minutes > max_wait_minutes:
                        # Waited too long — exception this packet out
                        self.log(f"EXCEPTION: Packet {env_id} has no Lead Document after {int(elapsed_minutes)} min. Exceptioning out.", "ERROR")
                        self.packet_mgr.mark_completed(env_id)
                        # Create exception job for tracking
                        job_manager.create_job(
                            filename=f"NO_LEAD_{env_id}.pdf",
                            file_path="",
                            service_type="PROJECT_2",
                            initial_status="EXCEPTION",
                            source=f"Tyler: {env_id}",
                            metadata={
                                "envelope": env_id,
                                "error": f"No lead document after {int(elapsed_minutes)} min wait",
                                "parts_received": [f.get('prefix', '?') for f in sorted_files],
                                "part_count": len(sorted_files),
                            }
                        )
                        continue
                    else:
                        # Still waiting — keep packet PENDING, don't merge yet
                        self.log(f"Packet {env_id}: No Lead Document yet ({len(sorted_files)} attachments waiting, {int(elapsed_minutes)}/{max_wait_minutes} min). Holding.", "INFO")
                        continue

                # Aggregator: Merge PDFs
                writer = PdfWriter()
                # Aggregator: Extract Comments and prepare for Merge PDFs
                all_comments = []
                for file_info in sorted_files:
                    path = file_info['path']
                    if os.path.exists(path):
                        # 1. Intelligence Phase: Extract Comments
                        comments = self.intel.extract_comments(path)
                        if comments: all_comments.append(f"[{file_info['prefix']}]: {comments}")
                
                # 3. Final Flagging Logic
                full_comment_str = "\n".join(all_comments)
                has_action, matched = self.intel.analyze_text(full_comment_str)
                classification = "ACTION_FLAGGED" if has_action else "STANDARD_PROCESS"
                self.log(f"Audit Trace: Env={env_id} Classification={classification} Matched={matched}", "INFO")
                
                # Filter CL from merge (v4.2 compliance): Clerk Letters are classified but NOT merged
                merge_files = [f for f in sorted_files if f.get('doc_type') != 'CLERK_LETTER']
                cl_excluded = len(sorted_files) - len(merge_files)
                if cl_excluded > 0:
                    self.log(f"CL Exclusion: {cl_excluded} Clerk Letter(s) excluded from merge for Envelope {env_id}", "INFO")
                
                # SAFETY NET: Deduplicate files by basename to catch any residual duplicates
                seen_basenames = set()
                deduped_merge_files = []
                for f_info in merge_files:
                    basename = os.path.basename(f_info['path'])
                    if basename not in seen_basenames:
                        seen_basenames.add(basename)
                        deduped_merge_files.append(f_info)
                    else:
                        self.log(f"Dedup: Skipping duplicate file {basename} for Envelope {env_id}", "INFO")
                if len(merge_files) != len(deduped_merge_files):
                    self.log(f"Dedup: Removed {len(merge_files) - len(deduped_merge_files)} duplicate files for Envelope {env_id}", "INFO")
                merge_files = deduped_merge_files
                
                # Merge PDFs (CL-excluded, deduplicated list)
                writer = PdfWriter()
                valid_files_count = 0
                for f_info in merge_files:
                    path = f_info['path']
                    if os.path.exists(path):
                        self.log(f"DEBUG: Merging part {f_info['prefix']} from {path}", "DEBUG")
                        reader = PdfReader(path)
                        for page in reader.pages:
                            writer.add_page(page)
                        valid_files_count += 1
                    else:
                        self.log(f"Warning: Part missing {path}", "WARN")
                        
                if valid_files_count == 0: 
                    self.log(f"ERROR: No valid files found to merge for packet {env_id}. Skipping.", "ERROR")
                    continue
                
                # 4. Save Final Master PDF
                # Use lead doc prefix for naming (AX40/AX69) + Job Number
                # v4.2 Fix: Extract job number from lead document's original_name, not temp path
                lead_prefix = "AX40"  # Default
                job_num = "UNKNOWN"
                if lead_docs:
                    lead_prefix = lead_docs[0].get('prefix', 'AX40')
                    original_name = lead_docs[0].get('original_name', '')
                    if original_name and len(original_name) > 4:
                        # Strip extension and prefix: AX40A25C05955.pdf → A25C05955
                        job_num = original_name.upper().replace('.PDF', '').replace('.pdf', '')[4:].strip('-_ ')
                        self.log(f"DEBUG: Job# from lead original_name '{original_name}' -> '{job_num}'", "INFO")
                
                # Fallback: extract from temp path if original_name didn't yield a result
                if not job_num or job_num == "UNKNOWN":
                    job_num = self._extract_job_num(sorted_files[0]['path'])
                    self.log(f"DEBUG: Job# fallback from temp path for {env_id}: {job_num}", "INFO")
                
                # lead_original_name for metadata enrichment
                lead_original_name = lead_docs[0].get('original_name', '') if lead_docs else ''
                
                final_name = f"{lead_prefix}{job_num}.pdf"
                
                # Use Phase2.OutputPath from config (new structure)
                p2_output = self._resolve_output_dir(
                    "Phase2",
                    p2_conf.get("OutputPath") or conf.get("Phase2.Output") or conf.get("paths.output"),
                )
                os.makedirs(p2_output, exist_ok=True)
                final_path = os.path.join(p2_output, final_name)
                
                with open(final_path, "wb") as f:
                    writer.write(f)
                    
                # Enrich Phase 2 metadata with email-level fields (for CSV dashboard)
                # Pull from packet-level email metadata if available
                packet_email_meta = packet.get('metadata', {}).get('email_metadata', {})
                
                job_id = job_manager.create_job(
                    filename=final_name,
                    file_path=final_path,
                    service_type="PROJECT_2",
                    initial_status="FILED",
                    source=f"Tyler: {env_id}",
                    metadata={
                        "envelope": env_id,
                        "classification": classification,
                        "merged_parts": [f['prefix'] for f in merge_files],
                        "constituent_docs": [f.get('original_name', os.path.basename(f['path'])) for f in merge_files],
                        "potential_actions": matched,
                        "part_count": len(merge_files),
                        "audit_trace": f"Merged {len(merge_files)} parts. Lead={sorted_files[0]['prefix']}.",
                        # --- CSV ENRICHMENT (v4.3.3) ---
                        "lead_doc": lead_original_name if lead_original_name else f"AX40{job_num}.pdf",
                        "pcp_job_num": job_num,
                        "case_num": packet_email_meta.get('case_num', ''),
                        "court": packet_email_meta.get('court', ''),
                        "case_style": packet_email_meta.get('case_style', ''),
                        "date_submitted_raw": packet_email_meta.get('date_submitted_raw', ''),
                        "date_accepted_raw": packet_email_meta.get('date_accepted_raw', ''),
                        "accepted_comments": packet_email_meta.get('accepted_comments', ''),
                        "original_filename": lead_original_name or 'Unknown',
                        "new_filename": final_name,
                        "final_path": final_path,
                    }
                )
                job_manager.update_job_column(job_id, "raw_comments", full_comment_str)
                job_manager.update_job_column(job_id, "action_flag", 1 if has_action else 0)
                
                # 6. Move emails to Completed folder (use configured path)
                try:
                    dest_folder = self._resolve_configured_folder("Phase2.Completed")
                    completed_name = conf.get("Phase2.Completed", "Phase2.Completed")
                    if dest_folder:
                        outlook = win32com.client.Dispatch("Outlook.Application")
                        namespace = outlook.GetNamespace("MAPI")
                        # Get unique entry IDs from all files in this packet
                        entry_ids = set(f.get('entry_id') for f in sorted_files if f.get('entry_id'))
                        moved_count = 0
                        for entry_id in entry_ids:
                            try:
                                msg = namespace.GetItemFromID(entry_id)
                                msg.Move(dest_folder)
                                moved_count += 1
                            except Exception as move_ex:
                                self.log(f"Warning: Could not move email {entry_id[:20]}...: {move_ex}", "WARN")
                        if moved_count > 0:
                            self.log(f"Moved {moved_count} emails to '{completed_name}'", "INFO")
                    else:
                        self.log(f"Phase2.Completed folder not found in Outlook ('{completed_name}') — emails NOT moved", "ERROR")
                except Exception as move_err:
                    self.log(f"Email Move Error: {move_err}", "WARN")
                
                # 7. Cleanup
                self.packet_mgr.mark_completed(env_id)
                self.log(f"Packet Successfully Filed: {final_name} (Action Word={has_action})", "SUCCESS")
            except Exception as e:
                self.log(f"AGGREGATION ERROR for Envelope {packet.get('envelope_id', 'UNKNOWN')}: {e}", "ERROR")
                import traceback
                self.log(traceback.format_exc(), "ERROR")

    def _mark_as_processed(self, msg):
        PROCESSED_TAG = "PCP-Processed"
        c = msg.Categories or ""
        if PROCESSED_TAG not in c:
            msg.Categories = (c + ";" + PROCESSED_TAG) if c else PROCESSED_TAG
            msg.Save()

    def _move_to_exceptions(self, msg, parent_folder, phase="Phase2"):
        dest = self._get_exception_folder(parent_folder, phase)
        if dest: msg.Move(dest)

    def _get_exception_folder(self, parent_folder, phase="Phase2"):
        """Resolve the exceptions folder from config. Returns None if not found (never creates folders)."""
        return self._resolve_configured_folder(f"{phase}.Exceptions")

    def _get_folder_by_path(self, parent_folder, folder_path_str):
        """Navigate to a subfolder by path string (e.g., '1-AcceptedFiling').
        
        Handles paths that include the mailbox name prefix (e.g., 'ai@pcpusa.net\Inbox').
        If the first segment matches the parent folder name, it's stripped automatically.
        """
        if not folder_path_str: return parent_folder
        folders = folder_path_str.split("\\")
        current_folder = parent_folder
        
        # Strip the mailbox prefix if it matches the parent folder name
        # This handles paths like "ai@pcpusa.net\Inbox" when root IS ai@pcpusa.net
        try:
            parent_name = getattr(parent_folder, 'Name', '').lower()
            if folders and folders[0].lower() == parent_name:
                folders = folders[1:]  # Skip the first segment (mailbox name)
        except Exception:
            pass
        
        for name in folders:
            if not name: continue
            try:
                current_folder = current_folder.Folders(name)
            except Exception:
                return None
        return current_folder

    def _resolve_configured_folder(self, config_key):
        """Resolve an Outlook folder from a config key (e.g. 'Phase1.Completed').
        
        Reads the path from config (e.g. 'Lunarius007@hotmail.com\\3- AI Completed'),
        then navigates to it from the mailbox root. NEVER creates folders.
        Returns the folder COM object, or None if the path is not found.
        """
        configured_path = conf.get(config_key, "") or ""
        if not configured_path:
            self.log(f"Config key '{config_key}' not set — cannot resolve folder", "WARN")
            return None
        try:
            import win32com.client
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            target_account = conf.get("outlook_account", "")
            root = self._resolve_outlook_root_folder(namespace, target_account)
            resolved = self._get_folder_by_path(root, configured_path)
            if not resolved:
                self.log(f"Folder not found for '{config_key}': '{configured_path}'", "WARN")
            return resolved
        except Exception as e:
            self.log(f"Error resolving folder for '{config_key}': {e}", "ERROR")
            return None

    def _extract_job_num(self, path):
        # Extract envelope ID from filename pattern: P2_ENVELOPE_timestamp_...
        fname = os.path.basename(path)
        # Pattern 1: P2_123456789_... (envelope ID)
        match = re.search(r"P2_(\d{9,})", fname)
        if match:
            res = match.group(1)
            self.log(f"DEBUG: _extract_job_num (envelope) on '{fname}' -> '{res}'", "INFO")
            return res
        # Pattern 2: AX40A25001 style (legacy)
        match = re.search(r"(A\d{2}[A-Z0-9]+)", fname)
        if match:
            res = match.group(1)
            self.log(f"DEBUG: _extract_job_num (AX style) on '{fname}' -> '{res}'", "INFO")
            return res
        self.log(f"DEBUG: _extract_job_num UNKNOWN on '{fname}'", "WARN")
        return "UNKNOWN"
