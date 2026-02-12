import pythoncom
import win32com.client as win32
import os

class EmailService:
    @staticmethod
    def send_report(subject, html_body, recipients, attachments=None):
        """
        Sends an email via Outlook COM.
        """
        pythoncom.CoInitialize()
        try:
            outlook = win32.Dispatch('Outlook.Application')
            mail = outlook.CreateItem(0) # 0 = MailItem
            
            # Combine recipients
            if isinstance(recipients, list):
                to_str = "; ".join(recipients)
            else:
                to_str = recipients
                
            mail.To = to_str
            mail.Subject = subject
            mail.HTMLBody = html_body
            
            if attachments:
                for att in attachments:
                    if os.path.exists(att):
                        mail.Attachments.Add(os.path.abspath(att))
            
            mail.Send()
            return True, "Sent"
        except Exception as e:
            return False, str(e)
        finally:
            pythoncom.CoUninitialize()

if __name__ == "__main__":
    # Test
    EmailService.send_report("Test Subject", "<h1>Test Report</h1>", "Lunarius007@hotmail.com")
    print("Test Sent")
