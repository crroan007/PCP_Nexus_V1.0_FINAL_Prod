
import sys
import os
import ctypes
import smtplib
from email.message import EmailMessage
import threading
import time
import datetime

class TamperGuard:
    def __init__(self, admin_email="Lunarius007@hotmail.com"):
        self.admin_email = admin_email
        self.alert_sent = False
        
    def check_debugger(self):
        """
        Windows API check for attached debugger.
        """
        try:
            kernel32 = ctypes.windll.kernel32
            return kernel32.IsDebuggerPresent() != 0
        except:
            return False

    def send_sos(self, reason):
        if self.alert_sent: return
        
        print(f"SECURITY ALERT: {reason}")
        
        # 1. Save locally (The Black Box)
        self._save_incident(reason)
        
        # 2. Try to verify internet/email immediately
        t = threading.Thread(target=self._send_email, args=(reason,))
        t.start()
        t.join(timeout=2.0) 
        self.alert_sent = True

    def _save_incident(self, reason):
        try:
            # Save to a hidden/obscure file
            # In a real scenario, this would be encrypted binary
            with open("core/sys_log.dat", "a") as f:
                f.write(f"{datetime.datetime.now()}|{reason}\n")
        except: pass

    def _send_email(self, reason):
        try:
            # Mock email logic - in real app, use SMTPLib with embedded creds
            # For now, we rely on the system's ability to just execute this block
            # If we had the Mailer, we'd import it.
            from core.emailer import mailer
            mailer.send_email(
                self.admin_email, 
                f"SECURITY ALERT: {reason}", 
                f"Tampering detected on machine: {os.getenv('COMPUTERNAME')}"
            )
        except Exception as e: 
            print(f"SOS Failed (Offline?): {e}")

    def report_pending(self):
        """Check for offline incidents and upload them."""
        if os.path.exists("core/sys_log.dat"):
            try:
                with open("core/sys_log.dat", "r") as f:
                    incidents = f.readlines()
                
                if incidents:
                    from core.emailer import mailer
                    mailer.send_email(
                        self.admin_email,
                        "Delayed Security Report",
                        f"The following incidents occurred offline:\n{''.join(incidents)}"
                    )
                    # Clear log after success
                    open("core/sys_log.dat", 'w').close()
            except: pass

    def monitor(self):
        """
        Background canary.
        """
        while True:
            if self.check_debugger():
                self.send_sos("Debugger Detected via Kernel32")
                # CRASH THE APP
                ctypes.windll.user32.MessageBoxW(0, "Security Violation Detected. Terminating.", "System Error", 0x10)
                os._exit(1) # Hard exit
            time.sleep(5)

def activate_protection():
    guard = TamperGuard()
    # 1. Report old crimes
    guard.report_pending()
    # 2. Start monitoring
    t = threading.Thread(target=guard.monitor, daemon=True)
    t.start()
