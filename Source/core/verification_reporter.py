import sqlite3
import json
import datetime
import os
from core.job_manager import job_manager


class VerificationReporter:
    """
    Generates the HTML content for the 'Verification' tab in the dashboard
    by querying the live database instead of reading a static file.
    Default behavior: Shows jobs for the CURRENT DAY (Implies Daily Reset).
    """
    
    def __init__(self):
        self.db_path = job_manager.db_path

    def generate_html(self, date_filter=None):
        """
        Generates the HTML string for the Verification tab.
        date_filter: 'YYYY-MM-DD' string. If None, defaults to TODAY.
        """
        if not date_filter:
            date_filter = datetime.datetime.now().strftime("%Y-%m-%d")
            
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query_p1 = """
                SELECT * FROM jobs 
                WHERE service_type = 'AFFIDAVITS' 
                AND created_at LIKE ? 
                ORDER BY created_at DESC
            """
            cursor.execute(query_p1, (f"{date_filter}%",))
            rows_p1 = cursor.fetchall()
            
            query_p2 = """
                SELECT * FROM jobs 
                WHERE service_type = 'PROJECT_2' 
                AND created_at LIKE ? 
                ORDER BY created_at DESC
            """
            cursor.execute(query_p2, (f"{date_filter}%",))
            rows_p2 = cursor.fetchall()
            
            conn.close()
            
            return self._build_html(rows_p1, rows_p2, date_filter)
            
        except Exception as e:
            return f'<div class="v-section"><div class="v-subtitle" style="color: #ef4444;">Error generating report: {str(e)}</div></div>'

    @staticmethod
    def _count_pdf_pages(file_path):
        """Count pages in a PDF file. Returns 0 on failure."""
        if not file_path or file_path == '#' or not os.path.isfile(file_path):
            return 0
        try:
            from PyPDF2 import PdfReader
            return len(PdfReader(file_path).pages)
        except Exception:
            return 0

    def _build_html(self, rows_p1, rows_p2, date_str):
        """Constructs the HTML with stacked sections for Phase 1 and Phase 2"""
        
        # --- Phase 1 Table Rows ---
        p1_rows_html = ""
        p1_pass = 0
        for row in rows_p1:
            try: 
                meta = json.loads(row['metadata']) if row['metadata'] else {}
            except: 
                meta = {}
            
            env_id = meta.get('envelope', row['original_source'] or '?')
            output_pdf = row['filename']
            file_path = row['file_path'] or '#'
            file_url = 'file:///' + file_path.replace('\\', '/') if file_path != '#' else '#'
            status = row['status']
            is_passed = (status in ['FILED', 'VERIFIED', 'NEW', 'COMPLETED', 'ARCHIVED'])
            if is_passed: p1_pass += 1
            
            status_class = "status-pass" if is_passed else "status-fail"
            status_text = "PASS" if is_passed else "FAIL"
            orig = row['original_source'] or '-'
            ts = row['created_at'].split(' ')[1] if ' ' in row['created_at'] else row['created_at']
            
            # Extract prefixes from metadata
            lead_doc = meta.get('lead_doc', '')
            orig_prefix = lead_doc[:4].upper() if lead_doc and len(lead_doc) >= 4 else '-'
            new_prefix = output_pdf[:4].upper() if output_pdf and len(output_pdf) >= 4 else '-'
            raw_name = output_pdf.replace('.pdf', '').replace('.PDF', '') if output_pdf and not output_pdf.startswith('ERROR') else '-'
            job_name = raw_name[4:] if len(raw_name) > 4 and raw_name != '-' else raw_name
            
            p1_rows_html += f"""
            <tr>
                <td>{env_id}</td>
                <td><a href="{file_url}" target="_blank">{output_pdf}</a></td>
                <td class="center"><span class='badge lead'>{orig_prefix}</span></td>
                <td class="center"><span class='badge attach'>{new_prefix}</span></td>
                <td>{job_name}</td>
                <td>{orig}</td>
                <td class="center">{ts}</td>
                <td class="center {status_class}">{status_text}</td>
            </tr>"""

        # --- Phase 2 Table Rows ---
        p2_rows_html = ""
        p2_pass = 0
        for row in rows_p2:
            try: 
                meta = json.loads(row['metadata']) if row['metadata'] else {}
            except: 
                meta = {}
            
            env_id = meta.get('envelope', row['original_source'] or '?')
            output_pdf = row['filename']
            file_path = row['file_path'] or '#'
            file_url = 'file:///' + file_path.replace('\\', '/') if file_path != '#' else '#'
            status = row['status']
            is_passed = (status in ['FILED', 'VERIFIED', 'NEW', 'COMPLETED', 'ARCHIVED'])
            if is_passed: p2_pass += 1
            
            status_class = "status-pass" if is_passed else "status-fail"
            status_text = "PASS" if is_passed else "FAIL"
            
            # Output directory for source file lookups
            output_dir = os.path.dirname(file_path) if file_path and file_path != '#' else ''
            
            # Count pages in merged output PDF
            output_pages = self._count_pdf_pages(file_path)
            
            # Resolve source document filenames
            source_docs = meta.get('constituent_docs', None)
            # Filter out any 'Unknown' entries
            if source_docs:
                source_docs = [d for d in source_docs if d and d != 'Unknown']
            if not source_docs:
                # Legacy/current data: reconstruct from merged_parts + directory scan
                prefixes = meta.get('merged_parts', [])
                env = meta.get('envelope', '')
                if prefixes and output_dir and env:
                    try:
                        existing_files = os.listdir(output_dir) if os.path.isdir(output_dir) else []
                        source_docs = []
                        for prefix in prefixes:
                            # Match P2_{env}_*_DL_{prefix}.pdf pattern
                            cat_pattern = f"_DL_{prefix}"
                            matches = [f for f in existing_files 
                                       if f.startswith(f"P2_{env}") and cat_pattern in f 
                                       and f != output_pdf and f not in source_docs]
                            if matches:
                                source_docs.append(matches[0])
                            else:
                                # Fallback: just use prefix label
                                source_docs.append(f"{prefix}{env}.pdf")
                    except Exception:
                        source_docs = [f"{p}{env}.pdf" for p in prefixes]
                else:
                    source_docs = prefixes or []
            
            source_count = len(source_docs)
            source_pages_total = 0
            
            # Build source docs detail column with per-file page counts + links
            sources_str = ""
            if not source_docs and 'audit_trace' in meta:
                sources_str = f"<span style='color:#94a3b8; font-style:italic;'>{meta['audit_trace']}</span>"
            elif source_docs:
                # Staging dir is where P2 source files typically live
                staging_dir = os.path.join(os.path.dirname(os.path.dirname(file_path)), 'Staging') if file_path and file_path != '#' else ''
                if not staging_dir or not os.path.isdir(staging_dir):
                    staging_dir = os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'PCP-Automation', 'Staging')
                
                for doc in source_docs:
                    # Determine badge label from filename
                    doc_upper = doc.upper()
                    if "AX40" in doc_upper:
                        badge_type, badge_label = "lead", "AX40"
                    elif "AXPB" in doc_upper:
                        badge_type, badge_label = "attach", "AXPB"
                    elif "AXPE" in doc_upper:
                        badge_type, badge_label = "attach", "AXPE"
                    elif "AXPM" in doc_upper:
                        badge_type, badge_label = "attach", "AXPM"
                    elif "AXPL" in doc_upper:
                        badge_type, badge_label = "attach", "AXPL"
                    elif "AXPA" in doc_upper:
                        badge_type, badge_label = "attach", "AXPA"
                    else:
                        badge_type, badge_label = "attach", "ATTACH"
                    
                    # Try staging_dir FIRST (original source files), then output_dir
                    # v4.3.5: CRITICAL — search staging first to avoid matching the MERGED
                    # output file (which has the same basename as the AX40 lead source).
                    doc_path = ''
                    for search_dir in [staging_dir, output_dir]:
                        if search_dir:
                            candidate = os.path.join(search_dir, doc)
                            # v4.3.6: Only skip if this is literally the merged output file
                            # (same full path), NOT just same basename. The AX40 source in
                            # staging/ shares a basename with the merged output but is a
                            # different file.
                            if os.path.isfile(candidate) and os.path.abspath(candidate) != os.path.abspath(file_path):
                                doc_path = candidate
                                break
                    
                    # If exact match failed, search by prefix pattern in staging dir
                    # Source files are stored as: P2_{envelope}_{ts}_{i}_DL_{prefix}.pdf
                    if not doc_path and staging_dir and os.path.isdir(staging_dir):
                        doc_prefix_4 = doc[:4].upper() if len(doc) >= 4 else ''
                        env_id = meta.get('envelope', '')
                        if doc_prefix_4 and env_id:
                            try:
                                for f in os.listdir(staging_dir):
                                    if f.startswith(f"P2_{env_id}") and f"_DL_{doc_prefix_4}" in f.upper() and f.lower().endswith('.pdf'):
                                        doc_path = os.path.join(staging_dir, f)
                                        break
                            except Exception:
                                pass
                    
                    # Also try searching output_dir by prefix pattern
                    if not doc_path and output_dir and os.path.isdir(output_dir):
                        doc_prefix_4 = doc[:4].upper() if len(doc) >= 4 else ''
                        if doc_prefix_4:
                            try:
                                for f in os.listdir(output_dir):
                                    if doc_prefix_4 in f.upper() and f.lower().endswith('.pdf') and f != output_pdf:
                                        doc_path = os.path.join(output_dir, f)
                                        break
                            except Exception:
                                pass
                    
                    doc_pages = self._count_pdf_pages(doc_path) if doc_path else 0
                    source_pages_total += doc_pages
                    pages_text = f" ({doc_pages} pg)" if doc_pages else ""
                    
                    if doc_path:
                        doc_url = 'file:///' + doc_path.replace('\\', '/')
                        sources_str += f"<div class='source-file'><span class='badge {badge_type}'>{badge_label}</span> <a href='{doc_url}' target='_blank'>{doc}</a>{pages_text}</div>"
                    else:
                        sources_str += f"<div class='source-file'><span class='badge {badge_type}'>{badge_label}</span> {doc}{pages_text}</div>"
            
            # Integrity check: do output pages match sum of source pages?
            if output_pages > 0 and source_pages_total > 0 and output_pages == source_pages_total:
                check_icon = "<span style='color:#4ade80'>✔</span>"
            elif output_pages > 0 and source_pages_total > 0:
                check_icon = "<span style='color:#fbbf24'>▲</span>"
            else:
                check_icon = ""

            # Phase 2 Job Name: extract PCP Job Number (strip 4-char prefix per Logic Doc Step 10)
            lead_doc_p2 = meta.get('lead_doc', '')
            if lead_doc_p2:
                raw_p2 = lead_doc_p2.replace('.pdf', '').replace('.PDF', '').strip()
                job_name_p2 = raw_p2[4:] if len(raw_p2) > 4 else raw_p2
            else:
                # Fallback: use the output filename without extension, strip prefix
                raw_p2 = output_pdf.replace('.pdf', '').replace('.PDF', '') if output_pdf and not output_pdf.startswith('ERROR') else '-'
                job_name_p2 = raw_p2[4:] if len(raw_p2) > 4 and raw_p2 != '-' else raw_p2

            p2_rows_html += f"""
            <tr>
                <td>{env_id}</td>
                <td><a href="{file_url}" target="_blank">{output_pdf}</a></td>
                <td>{job_name_p2}</td>
                <td class="center">{output_pages or '-'}</td>
                <td class="center">{source_count}</td>
                <td class="center">{source_pages_total or '-'}</td>
                <td class="center">{check_icon}</td>
                <td class="center {status_class}">{status_text}</td>
                <td class="sources">{sources_str}</td>
            </tr>"""

        p1_count = len(rows_p1)
        p2_count = len(rows_p2)

        # No-data messages
        p1_empty = f'<div style="padding:20px; text-align:center; color:#64748b; font-style:italic;">No Phase 1 jobs for {date_str}</div>' if not rows_p1 else ''
        p2_empty = f'<div style="padding:20px; text-align:center; color:#64748b; font-style:italic;">No Phase 2 jobs for {date_str}</div>' if not rows_p2 else ''

        # Simple stacked layout — no tabs, no JS
        html = f"""
        <div class="v-section">
            <div class="v-subtitle" style="margin-bottom:16px;">
                Verification Report for {date_str} — Auto-Reset at Midnight
            </div>

            <h3 style="color:#e2e8f0; margin:16px 0 8px 0;">📄 Phase 1: Rename <span class="v-count" style="margin-left:8px;">{p1_count}</span> <span style="color:#4ade80; font-size:0.8em; margin-left:4px;">({p1_pass} passed)</span></h3>
            <table>
                <thead>
                    <tr>
                        <th>ENVELOPE ID</th>
                        <th>OUTPUT PDF</th>
                        <th class="center">ORIG PREFIX</th>
                        <th class="center">NEW PREFIX</th>
                        <th>JOB NAME</th>
                        <th>ORIGINAL SOURCE</th>
                        <th class="center">TIME</th>
                        <th class="center">STATUS</th>
                    </tr>
                </thead>
                <tbody>{p1_rows_html}</tbody>
            </table>
            {p1_empty}

            <hr style="border:0; border-top:1px solid #334155; margin:24px 0;">

            <h3 style="color:#e2e8f0; margin:16px 0 8px 0;">📑 Phase 2: Merge <span class="v-count" style="margin-left:8px;">{p2_count}</span> <span style="color:#4ade80; font-size:0.8em; margin-left:4px;">({p2_pass} passed)</span></h3>
            <table>
                <thead>
                    <tr>
                        <th>ENVELOPE</th>
                        <th>OUTPUT PDF</th>
                        <th>JOB NAME</th>
                        <th class="center">PAGES</th>
                        <th class="center">SOURCES</th>
                        <th class="center">SRC PAGES</th>
                        <th class="center">CHECK</th>
                        <th class="center">STATUS</th>
                        <th>SOURCE DOCUMENTS</th>
                    </tr>
                </thead>
                <tbody>{p2_rows_html}</tbody>
            </table>
            {p2_empty}
        </div>
        """
        return html
