
import win32com.client
import pythoncom
import os
import datetime
from core.secure_config import conf

class OutlookMailer:
    def __init__(self):
        self.enabled = conf.get("reporting.enabled", True)
        self.recipients = conf.get("reporting.recipients", ["Lunarius007@hotmail.com"])
        self.outlook = None

    def _connect(self):
        try:
            # Ensure COM is initialized for this thread
            pythoncom.CoInitialize() 
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            return True
        except Exception as e:
            print(f"Error connecting to Outlook: {e}")
            return False

    def send_email(self, subject, body, recipients, attachments=None, is_html=True):
        """
        Generic send method with attachment support.
        recipients: list of strings (email addresses)
        attachments: list of strings (absolute file paths)
        """
        if not self.enabled:
            print("Reporting disabled in config.")
            return

        if not recipients:
            print("No recipients provided.")
            return

        if not self._connect():
            return

        try:
            mail = self.outlook.CreateItem(0) # 0 = olMailItem
            
            # Combine Recipients
            to_list = ";".join(recipients)
            mail.To = to_list
            mail.Subject = subject
            
            if is_html:
                mail.HTMLBody = body
            else:
                mail.Body = body
            
            # Attachments
            if attachments:
                for path in attachments:
                    if os.path.exists(path):
                        mail.Attachments.Add(path)
                    else:
                        print(f"Attachment not found: {path}")

            mail.Send()
            print(f"Email sent to {to_list}")
            
        except Exception as e:
            print(f"Failed to send email: {e}")
        finally:
            pythoncom.CoUninitialize()

    def send_session_report(self, html_content, stats_summary=""):
        # Wrapper for session reports
        subject = f"PCP Nexus Session Report - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        if stats_summary:
            subject += f" - {stats_summary}"
        
        self.send_email(subject, html_content, self.recipients, is_html=True)


# Singleton
mailer = OutlookMailer()
