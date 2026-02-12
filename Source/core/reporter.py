
import sqlite3
import csv
import os
import json
import datetime
from core.job_manager import job_manager
from core.job_manager import job_manager
from core.secure_config import conf
from core.emailer import mailer
from core import app_paths

class Reporter:
    def __init__(self):
        self.db_path = job_manager.db_path
        default_output = str(app_paths.output_dir()) if os.name == "nt" else os.path.join(os.getcwd(), "Output")
        self.output_path = conf.get("paths.output", default_output)

    def generate_daily_csv(self, target_date_str=None):
        """
        Generates the eaffidavits_accepted_{MMDDYYYY}.csv from the Database.
        target_date_str: 'MMDDYYYY' (Defaults to today)
        """
        if not target_date_str:
            target_date_str = datetime.datetime.now().strftime("%m%d%Y")
        
        # We need to query jobs that match this date.
        # However, the 'date_accepted' is inside the JSON metadata.
        # SQLite JSON queries are possible but depend on the extension.
        # Safer to fetch relevant jobs (e.g. by created_at) and filter, OR fetch all 'VERIFIED'/'NEW' jobs?
        # Actually, simpler: Queries ALL jobs with metadata, parses, and checks the date.
        # Efficiency warning: Checks all jobs? 
        # Better: Filter by 'created_at' timestamp if possible, but 'date_accepted' might differ from 'created_at'.
        # For now, fetching LIMIT 1000 or filtering by updated_at > X is safer.
        # Given the requirements, let's just fetch ALL jobs for now (Database size isn't huge yet).
        
        csv_filename = f"eaffidavits_accepted_{target_date_str}.csv"
        full_csv_path = os.path.join(self.output_path, csv_filename)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Fetch status, metadata
        cursor.execute("SELECT id, status, metadata FROM jobs WHERE metadata IS NOT NULL AND metadata != '{}'")
        rows = cursor.fetchall()
        conn.close()
        
        matching_rows = []
        
        # Target Date Format: MMDDYYYY -> Matches extraction logic?
        # Metadata 'date_accepted_raw': "1/5/2026 10:53 PM"
        
        # Helper to parse date string "1/5/2026" -> "01052026"
        def matches_target_date(raw_date_str, target):
            # raw_date_str like "1/5/2026 ..."
            if not raw_date_str: return False
            try:
                # Extract just the date part "1/5/2026"
                date_part = raw_date_str.split(' ')[0]
                dt = datetime.datetime.strptime(date_part, "%m/%d/%Y")
                return dt.strftime("%m%d%Y") == target
            except:
                return False

        # Helper to format date/time
        def format_row_dt(raw_dt_str):
            # Expects "12/15/2025 4:36 PM"
            if not raw_dt_str: return "", ""
            try:
                dt = datetime.datetime.strptime(raw_dt_str, "%m/%d/%Y %I:%M %p")
                return dt.strftime("%m/%d/%y"), dt.strftime("%H:%M:00")
            except:
                # Fallback try without PM?
                parts = raw_dt_str.split(' ')
                if len(parts) > 1:
                    return parts[0], " ".join(parts[1:])
                return raw_dt_str, ""

        for r in rows:
            jid, status, meta_json = r
            try:
                meta = json.loads(meta_json)
            except:
                continue
                
            raw_acc = meta.get('date_accepted_raw', '')
            if matches_target_date(raw_acc, target_date_str):
                
                sub_date, sub_time = format_row_dt(meta.get('date_submitted_raw', ''))
                acc_date, acc_time = format_row_dt(meta.get('date_accepted_raw', ''))

                # Format Email Timestamps and Calculate Delta
                email_received_str = meta.get('email_received_at', '')
                email_processed_str = meta.get('email_processed_at', '')
                delta_minutes = ""
                
                if email_received_str and email_processed_str:
                    try:
                        # Parse timestamps
                        received = datetime.datetime.strptime(email_received_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
                        processed = datetime.datetime.strptime(email_processed_str, "%Y-%m-%d %H:%M:%S")
                        # Calculate delta in minutes
                        delta = (processed - received).total_seconds() / 60
                        delta_minutes = f"{delta:.2f}"
                        # Format as MM/DD/YY HH:MM:SS
                        email_received_str = received.strftime("%m/%d/%y %H:%M:%S")
                        email_processed_str = processed.strftime("%m/%d/%y %H:%M:%S")
                    except Exception as e:
                        # Fallback: keep raw strings
                        pass

                # Build Row (Unified Data Dictionary Compliance)
                row = [
                    str(meta.get('envelope_num', '')).strip(),
                    str(meta.get('case_num', '')).strip(),
                    sub_date,
                    sub_time,
                    acc_date,
                    acc_time,
                    str(meta.get('lead_document', '')).strip(),
                    str(meta.get('pcp_job_num', '')).strip(),
                    # Audit Columns
                    str(meta.get('original_filename', '')).strip(),
                    str(meta.get('new_filename', '')).strip(),
                    str(meta.get('final_path', '')).strip(),
                    str(meta.get('constituent_docs', '')).strip(),
                    str(meta.get('merged_link', '')).strip(),
                    email_received_str,
                    email_processed_str,
                    delta_minutes
                ]
                matching_rows.append(row)
        
        # Write CSV
        if matching_rows:
            with open(full_csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                header = ["Envelope_Num", "Case_Num", "Date_Submitted", "Time_Submitted", "Date_Accepted", "Time_Accepted", "Lead_Document", "PCP_Job_Num", 
                          "Original_Filename", "New_Filename", "Final_Path", "Constituent_Docs", "Merged_Link",
                          "Email_Received", "Email_Processed", "Processing_Delta_Minutes"]
                writer.writerow(header)
                writer.writerows(matching_rows)
            return full_csv_path, len(matching_rows)
        else:
            return None, 0

    def email_daily_csv(self, target_date_str=None):
        """
        Generates and EMAILS the daily CSV.
        Default date: Yesterday (Previous Day's Activity).
        """
        # 1. Determine Date (Default to Yesterday)
        if not target_date_str:
            yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
            target_date_str = yesterday.strftime("%m%d%Y")
            display_date = yesterday.strftime("%Y-%m-%d")
        else:
            # target_date_str is MMDDYYYY
            display_date = f"{target_date_str[0:2]}/{target_date_str[2:4]}/{target_date_str[4:]}"

        # 2. Check Config
        if not conf.get_kvi("reporting.daily_csv_enabled", False):
            print("Daily CSV Reporting is disabled in config.")
            return

        recipients = conf.get_kvi("reporting.daily_csv_recipients", [])
        if not recipients:
            print("No recipients configured for Daily CSV.")
            return

        print(f"Generating report for {display_date}...")

        # 3. Generate CSV
        csv_path, count = self.generate_daily_csv(target_date_str)
        
        if not csv_path or count == 0:
            print(f"No records found for {target_date_str}, skipping email.")
            return

        # 4. Email
        subject = f"PCP Daily Accepted Report - {display_date}"
        body = f"""
        <html>
        <body>
            <h2>Daily Accepted Filings Report</h2>
            <p><strong>Date:</strong> {display_date}</p>
            <p><strong>Total Accepted:</strong> {count}</p>
            <p>Please find the attached CSV report.</p>
        </body>
        </html>
        """
        
        print(f"Sending email to {recipients}...")
        mailer.send_email(
            subject=subject, 
            body=body, 
            recipients=recipients, 
            attachments=[csv_path], 
            is_html=True
        )

if __name__ == "__main__":
    # Test Run
    r = Reporter()
    path, count = r.generate_daily_csv()
    if path: print(f"Generated {path} with {count} records.")
    else: print("No records found for today.")
