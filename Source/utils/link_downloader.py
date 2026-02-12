import re
import urllib.parse
import requests
import logging
import os
import subprocess
import random
import uuid
from core import app_paths

class LinkExpiredError(Exception):
    """Raised when a Tyler Technologies link is expired (>45 days)."""
    pass

class MultiDocumentResult(Exception):
    """Signal raised when a Tyler page contains multiple downloadable documents.
    Carries the list of document URLs and filenames so the caller can download them individually."""
    def __init__(self, base_url, documents):
        self.base_url = base_url
        self.documents = documents  # list of {'url': str, 'filename': str}
        super().__init__(f"Tyler page contains {len(documents)} documents")

class LinkDownloader:
    """
    Utility class to handle downloading files from secure links, 
    specifically designed for Proofpoint-wrapped Tyler Tech URLs.
    """

    def __init__(self, parent_logger=None):
        if parent_logger:
            self.logger = parent_logger
        else:
            self.logger = logging.getLogger("LinkDownloader")
            # Fallback to console if no parent logger
            if not self.logger.handlers:
                h = logging.StreamHandler()
                h.setFormatter(logging.Formatter('%(message)s'))
                self.logger.addHandler(h)
                self.logger.setLevel(logging.INFO)

        # Standard headers to mimic a browser
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        self.headers = {
            'User-Agent': random.choice(self.user_agents)
        }

    def decode_proofpoint_url(self, safe_url):
        """
        Decodes a URL that might be wrapped in Microsoft SafeLinks OR Proofpoint.
        Handles the chain: SafeLinks -> Proofpoint -> Real URL.
        """
        try:
            current_url = safe_url
            
            # 1. unwrapping SafeLinks
            if 'safelinks.protection.outlook.com' in current_url:
                try:
                    parsed = urllib.parse.urlparse(current_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if 'url' in qs:
                        current_url = qs['url'][0]
                        self.logger.info(f"Unwrapped SafeLink: {current_url[:50]}...")
                except Exception as ex:
                    self.logger.warning(f"Failed to unwrap SafeLink: {ex}")

            # 2. decoding Proofpoint
            if 'urldefense.proofpoint.com' in current_url:
                parsed = urllib.parse.urlparse(current_url)
                query_params = urllib.parse.parse_qs(parsed.query)
                
                if 'u' in query_params:
                    encoded_url = query_params['u'][0]
                    # Specific Proofpoint Translation
                    trans_map = str.maketrans('-_', '%/')
                    fixed_encoding = encoded_url.translate(trans_map)
                    decoded = urllib.parse.unquote(fixed_encoding)
                    
                    self.logger.info(f"Unwrapped Proofpoint: {decoded[:50]}...")
                    return decoded
            
            # Return whatever we managed to unwrap (or original if no wrappers)
            return current_url
            
        except Exception as e:
            self.logger.error(f"Failed to decode URL: {e}")
            return safe_url

    def download_file(self, url, target_path):
        """
        Downloads a file from the given URL to the target path.
        Returns True if successful, False otherwise.
        """
        try:
            self.logger.info(f"Attempting to download from: {url}")
            
            user_agent = random.choice(self.user_agents)
            script_name = f"dl_{uuid.uuid4().hex[:8]}.ps1"
            # Use temp directory to avoid UAC issues in Program Files
            if os.name == 'nt':
                temp_dir = str(app_paths.temp_dir())
                script_path = os.path.join(temp_dir, script_name)
            else:
                script_path = os.path.join(os.getcwd(), script_name)
            
            # Construct PowerShell Script Content
            ps_content = f'''
$ErrorActionPreference = "Stop"
try {{
    Invoke-WebRequest -Uri "{url}" -OutFile "{target_path}" -UserAgent "{user_agent}" -TimeoutSec 20
    exit 0
}} catch {{
    Write-Error $_.Exception.Message
    exit 1
}}
'''
            try:
                with open(script_path, "w") as f:
                    f.write(ps_content)
                    
                # Execute PowerShell Script (use full path to avoid CWD issues)
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=temp_dir if os.name == 'nt' else os.getcwd(),
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                
                if result.returncode != 0:
                    err_msg = result.stderr.strip()
                    self.logger.error(f"PowerShell Script Failed: {err_msg}")
                    
                    # Enhanced Expiration Detection
                    if "410" in err_msg or "Gone" in err_msg or "404" in err_msg or "Not Found" in err_msg:
                        self.logger.warning("Download Failed with 404/410 (Likely Expired).")
                        raise LinkExpiredError("Link Unavailable (404/410)")
                        
                    if "403" in err_msg or "Forbidden" in err_msg:
                         self.logger.error("Access Denied (Native 403).")
                    return False
                
                # Verify File Exists and has content
                if not os.path.exists(target_path) or os.path.getsize(target_path) < 100:
                    self.logger.error("File downloaded but is empty/corrupt.")
                    return False
                    
                self.logger.info(f"Successfully downloaded to {target_path} (Native Bypass)")
                
                # --- SMART UNFURLING: Tyler Landing Page Detection ---
                # --- SMART UNFURLING & EXPIRY DETECTION ---
                try:
                    with open(target_path, "rb") as f:
                        header = f.read(1024)
                    
                    # Heuristic: It's HTML
                    if b"<!DOCTYPE html" in header or b"<html" in header:
                        # Read full content for robust parsing
                        with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                            full_html = f.read()
                        
                        lower_content = full_html.lower()
                        
                        # GLOBAL CHECK: Is it an Expired Page? (Tyler or otherwise)
                        # User Screenshot: "The document that you are trying to access has expired."
                        if "no longer available" in lower_content or "lblexpired" in full_html or "document that you are trying to access has expired" in lower_content:
                                self.logger.warning("Link EXPIRED (Document > 45 days old).")
                                raise LinkExpiredError("Document Expired")

                        # TYLER UNFURLING logic
                        if "tyler" in lower_content or "view documents" in lower_content:
                            self.logger.info("Detected Tyler HTML Landing Page. Scanning for download links...")
                            
                            # Find ALL DownloadResource.ashx links on the page
                            all_links = re.findall(r'href=["\'](/DownloadResource\.ashx\?RID=[a-f0-9-]+)["\']', full_html, re.IGNORECASE)
                            
                            # Try to extract associated filenames from the page
                            # Tyler pages show filenames in various locations: table cells, spans, link text
                            # Strategy: Find ALL PDF-like filenames on the page, then match to links
                            doc_filenames = re.findall(r'([A-Z][A-Za-z0-9]{2,}[A-Za-z0-9_\-]*(?:CL)?\.(?:pdf|PDF))', full_html)
                            # Also try to find filenames in title/alt attributes or nearby text
                            if not doc_filenames:
                                doc_filenames = re.findall(r'>([^<]+\.pdf)<', full_html, re.IGNORECASE)
                                doc_filenames = [f.strip() for f in doc_filenames if f.strip()]
                            
                            if all_links:
                                parsed_original = urllib.parse.urlparse(url)
                                base_url = f"{parsed_original.scheme}://{parsed_original.netloc}"
                                
                                if len(all_links) == 1:
                                    # Single document — use original recursive download behavior
                                    new_url = base_url + all_links[0]
                                    self.logger.info(f"Unfurled Tyler Link (single doc): {new_url}")
                                    return self.download_file(new_url, target_path)
                                else:
                                    # MULTI-DOCUMENT PAGE: Signal the caller to use bulk download
                                    documents = []
                                    for i, relative_link in enumerate(all_links):
                                        doc_url = base_url + relative_link
                                        # Try to match a filename from the page, otherwise use index
                                        filename = doc_filenames[i] if i < len(doc_filenames) else f"doc_{i}.pdf"
                                        documents.append({'url': doc_url, 'filename': filename})
                                    
                                    self.logger.info(f"Tyler Multi-Document Page: Found {len(documents)} documents: {[d['filename'] for d in documents]}")
                                    raise MultiDocumentResult(base_url, documents)
                            else:
                                self.logger.warning("Tyler Page detected but no DownloadResource link found.")
                                return False
                except LinkExpiredError:
                    raise # Propagate to caller
                except MultiDocumentResult:
                    raise # Propagate to caller — handler in _download_message_parts
                except Exception as unfurl_err:
                    self.logger.error(f"Unfurling Error: {unfurl_err}")
                
                return True

            except subprocess.TimeoutExpired:
                 self.logger.error("PowerShell Download Timed Out.")
                 return False
            except Exception as e:
                 # Check if it was LinkExpiredError or MultiDocumentResult caught in generic Exception
                 if isinstance(e, LinkExpiredError):
                     raise
                 if isinstance(e, MultiDocumentResult):
                     raise
                 self.logger.error(f"Downloader Error: {e}")
                 return False
            finally:
                if os.path.exists(script_path):
                    try: os.remove(script_path)
                    except: pass
            
        except LinkExpiredError:
            raise # Re-raise for HunterV2 to handle
        except MultiDocumentResult:
            raise # Re-raise for HunterV2 multi-doc handler
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def probe_filename(self, url):
        """Do a HEAD request to extract the real filename from Content-Disposition header.
        Returns the filename string, or None if not available."""
        try:
            user_agent = random.choice(self.user_agents)
            resp = requests.head(url, headers={'User-Agent': user_agent}, timeout=10, allow_redirects=True)
            cd = resp.headers.get('Content-Disposition', '')
            if cd:
                # Parse filename from: attachment; filename="AX40A26200712.PDF"
                match = re.search(r'filename[*]?=["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
                if match:
                    fname = match.group(1).strip().strip('"').strip("'")
                    if fname:
                        self.logger.info(f"Probed filename from Content-Disposition: {fname}")
                        return fname
        except Exception as e:
            self.logger.warning(f"Filename probe failed for {url[:60]}...: {e}")
        return None
