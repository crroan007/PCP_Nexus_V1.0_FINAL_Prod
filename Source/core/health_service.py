import threading
import time
import os
import datetime
from core import app_paths


class HealthService:
    """
    Enterprise Heartbeat Monitor with Stall Detection.
    
    1. Writes a heartbeat file every 60s (for external IT monitoring).
    2. Reads engine_status.json to detect engine stalls (>5 min no heartbeat).
    3. Sends email alerts on stall/error detection (rate-limited: 1 per 30 min).
    4. Sends recovery email when engine resumes after a stall.
    """
    STALL_THRESHOLD_MINUTES = 5
    ALERT_COOLDOWN_MINUTES = 30

    def __init__(self, log_callback):
        self.log = log_callback
        self._running = False
        if os.name == 'nt':
            self.pulse_path = str(app_paths.staging_dir() / "heartbeat.txt")
        else:
            self.pulse_path = os.path.join(os.getcwd(), "Staging", "heartbeat.txt")
        self._thread = None
        self._last_alert_time = None
        self._was_stalled = False

    def start(self):
        self._running = True
        self._was_stalled = False
        self._last_alert_time = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log(f"Health Service Started. Pulse: {self.pulse_path}", "INFO")

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            try:
                # 1. Write heartbeat file (for external monitoring)
                with open(self.pulse_path, "w") as f:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"SYSTEM_ONLINE: {timestamp}")
                
                # 2. Check engine status for stalls
                self._check_engine_health()
                
                time.sleep(60)  # Check every minute
            except Exception as e:
                self.log(f"Health Service Failed: {e}", "ERROR")
                time.sleep(60)

    def _check_engine_health(self):
        """Read engine_status.json and detect stalls."""
        try:
            from core.status_writer import StatusWriter
            status = StatusWriter.read()
            if not status:
                return  # No status file = engine never started, nothing to do
            
            state = status.get("state", "STOPPED")
            
            # Don't monitor if engine is intentionally stopped
            if state == "STOPPED":
                self._was_stalled = False
                return
            
            # Check heartbeat freshness
            last_hb_str = status.get("last_heartbeat")
            if not last_hb_str:
                return
            
            try:
                last_hb = datetime.datetime.fromisoformat(last_hb_str)
            except Exception:
                return
            
            age_minutes = (datetime.datetime.now() - last_hb).total_seconds() / 60
            
            if state == "ERROR" or age_minutes > self.STALL_THRESHOLD_MINUTES:
                # ENGINE IS STALLED OR IN ERROR
                if not self._was_stalled:
                    self._was_stalled = True
                    self.log(f"⚠ ENGINE STALL DETECTED: Last heartbeat {age_minutes:.1f}m ago (threshold: {self.STALL_THRESHOLD_MINUTES}m)", "CRITICAL")
                    
                    # Update status file to STALLED
                    from core.status_writer import status_writer
                    status_writer.set_state("STALLED")
                    
                    # Send alert email (rate-limited)
                    self._send_alert(status, age_minutes)
            else:
                # Engine is healthy
                if self._was_stalled:
                    # Recovery! Engine was stalled but is now responding
                    self._was_stalled = False
                    self.log("✓ ENGINE RECOVERED: Heartbeat resumed.", "SUCCESS")
                    self._send_recovery_alert(status)
                    
        except Exception as e:
            self.log(f"Health check error: {e}", "WARN")

    def _send_alert(self, status, age_minutes):
        """Send stall/error alert email. Rate-limited to 1 per ALERT_COOLDOWN_MINUTES."""
        now = datetime.datetime.now()
        
        if self._last_alert_time:
            elapsed = (now - self._last_alert_time).total_seconds() / 60
            if elapsed < self.ALERT_COOLDOWN_MINUTES:
                self.log(f"Alert suppressed (cooldown: {self.ALERT_COOLDOWN_MINUTES - elapsed:.0f}m remaining)", "INFO")
                return
        
        try:
            from core.email_service import EmailService
            from core.secure_config import conf
            
            recipients = self._get_alert_recipients(conf)
            if not recipients:
                self.log("No alert recipients configured.", "WARN")
                return
            
            activity = status.get("activity", "Unknown")
            phase = status.get("phase", "Unknown")
            progress = status.get("progress", "N/A")
            error = status.get("last_error", "None")
            
            subject = f"⚠ PCP Nexus Alert: Engine {'Error' if status.get('state') == 'ERROR' else 'Stalled'}"
            body = f"""
            <h2 style="color: #dc2626;">PCP Nexus Engine Alert</h2>
            <table style="border-collapse: collapse; font-family: sans-serif;">
                <tr><td style="padding: 4px 12px; font-weight: bold;">Status:</td><td style="padding: 4px 12px; color: #dc2626;">{status.get('state', 'UNKNOWN')}</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Last Heartbeat:</td><td style="padding: 4px 12px;">{age_minutes:.1f} minutes ago</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Phase:</td><td style="padding: 4px 12px;">{phase}</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Activity:</td><td style="padding: 4px 12px;">{activity}</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Progress:</td><td style="padding: 4px 12px;">{progress}</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Last Error:</td><td style="padding: 4px 12px; color: #dc2626;">{error}</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Detected At:</td><td style="padding: 4px 12px;">{now.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
            </table>
            <p style="margin-top: 16px; color: #6b7280;">This alert will not repeat for {self.ALERT_COOLDOWN_MINUTES} minutes.</p>
            """
            
            success, msg = EmailService.send_report(subject, body, recipients)
            if success:
                self._last_alert_time = now
                self.log(f"Alert email sent to {len(recipients)} recipient(s).", "INFO")
            else:
                self.log(f"Alert email failed: {msg}", "ERROR")
                
        except Exception as e:
            self.log(f"Failed to send alert: {e}", "ERROR")

    def _send_recovery_alert(self, status):
        """Send recovery notification email."""
        try:
            from core.email_service import EmailService
            from core.secure_config import conf
            
            recipients = self._get_alert_recipients(conf)
            if not recipients:
                return
            
            now = datetime.datetime.now()
            subject = "✓ PCP Nexus: Engine Recovered"
            body = f"""
            <h2 style="color: #16a34a;">PCP Nexus Engine Recovered</h2>
            <p>The engine has resumed normal operation.</p>
            <table style="border-collapse: collapse; font-family: sans-serif;">
                <tr><td style="padding: 4px 12px; font-weight: bold;">Status:</td><td style="padding: 4px 12px; color: #16a34a;">RUNNING</td></tr>
                <tr><td style="padding: 4px 12px; font-weight: bold;">Recovered At:</td><td style="padding: 4px 12px;">{now.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
            </table>
            """
            
            EmailService.send_report(subject, body, recipients)
            self.log("Recovery email sent.", "INFO")
        except Exception as e:
            self.log(f"Recovery email failed: {e}", "WARN")

    def _get_alert_recipients(self, conf):
        """Get alert recipients from config. Reuses existing email config keys."""
        recipients = []
        try:
            # Try reporting subscribers first
            reporting = conf.get("reporting", {})
            subs = reporting.get("subscribers", [])
            if subs:
                return subs
            
            # Fallback: try email recipients from phase configs
            r1 = conf.get("email.phase1_recipient", "")
            r2 = conf.get("email.phase2_recipient", "")
            for r in [r1, r2]:
                if r and r not in recipients:
                    recipients.append(r)
        except Exception:
            pass
        return recipients
