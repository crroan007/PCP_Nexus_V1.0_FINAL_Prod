import threading
import time
import traceback

from core.health_service import HealthService
from core.backup_service import BackupService
from core.job_manager import job_manager # Forces DB Initialization
from core.status_writer import status_writer

class OrchestratorEngine:
    """
    The heart of the system. Manages the infinite loop of:
    Hunter -> Auditor -> Clerk.
    Runs in a background thread to keep UI responsive.
    """
    
    def __init__(self, hunter, auditor, clerk, log_callback):
        self.hunter = hunter
        self.auditor = auditor
        self.clerk = clerk
        self.log = log_callback
        self.health_service = HealthService(log_callback)
        self.backup_service = BackupService(log_callback)
        
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        
        # Independent Control Flags
        self.hunter_enabled = True
        self.auditor_enabled = True
        self.clerk_enabled = True

    def start(self):
        if self._running:
            return
        
        self._running = True
        self._stop_event.clear()
        status_writer.set_state("RUNNING")
        status_writer.cycle_start()
        
        # STARTUP RECONCILIATION: Handle jobs stuck in MOVING status from interrupted run
        self._reconcile_moving_jobs()
        
        # Start Services
        self.health_service.start()
        self.backup_service.start()
        
        # Spawn Independent Threads for Parallel Execution
        self._threads = []
        
        if self.hunter_enabled:
            # Pass stop_event to hunter for graceful mid-cycle shutdown
            if hasattr(self.hunter, 'stop_event'):
                self.hunter.stop_event = self._stop_event
            # Pass status_writer for live progress updates
            self.hunter.status_writer = status_writer
            t = threading.Thread(target=self._run_agent_loop, args=(self.hunter, 2), daemon=True, name="HunterThread")
            t.start()
            self._threads.append(t)
            
        if self.auditor_enabled:
            # Thread A
            t1 = threading.Thread(target=self._run_agent_loop, args=(self.auditor, 2), daemon=True, name="AuditorThread-1")
            t1.start()
            self._threads.append(t1)
            # Thread B (Double Capacity)
            t2 = threading.Thread(target=self._run_agent_loop, args=(self.auditor, 2), daemon=True, name="AuditorThread-2")
            t2.start()
            self._threads.append(t2)
            
        if self.clerk_enabled:
            # Thread A
            t1 = threading.Thread(target=self._run_agent_loop, args=(self.clerk, 2), daemon=True, name="ClerkThread-1")
            t1.start()
            self._threads.append(t1)
            # Thread B (Double Capacity)
            t2 = threading.Thread(target=self._run_agent_loop, args=(self.clerk, 2), daemon=True, name="ClerkThread-2")
            t2.start()
            self._threads.append(t2)

        # Reporter Thread
        tr = threading.Thread(target=self._run_reporter_loop, daemon=True, name="ReporterThread")
        tr.start()
        self._threads.append(tr)

        self.log("Orchestrator Engine STARTED (Parallel + Reporter).", "SUCCESS")

    def stop(self):
        if not self._running:
            return
            
        self.log("Stopping Engine... Signaling all threads to stop.", "WARN")
        self.health_service.stop()
        self.backup_service.stop()
        self._running = False
        self._stop_event.set()
        status_writer.set_state("STOPPED")
        
        # Wait for threads to exit (with timeout to prevent UI hang)
        for t in getattr(self, '_threads', []):
            if t.is_alive():
                self.log(f"Waiting for {t.name} to stop...", "INFO")
                t.join(timeout=3)  # Wait max 3 seconds per thread
                if t.is_alive():
                    self.log(f"⚠ {t.name} did not stop in time (may be blocked on I/O).", "WARN")
                else:
                    self.log(f"✓ {t.name} stopped.", "INFO")
        
        self.log("Engine STOPPED.", "SUCCESS")

    def _reconcile_moving_jobs(self):
        """
        Startup reconciliation: Handle jobs stuck in MOVING status from previous interrupted run.
        These jobs have files created but emails may or may not have been moved.
        Safe action: Mark them as ARCHIVED (assume move completed or will be skipped).
        """
        from core.job_manager import job_manager
        
        try:
            # Find all jobs stuck in MOVING status
            moving_jobs = job_manager.get_jobs_by_status('MOVING')
            
            if moving_jobs:
                self.log(f"RECONCILIATION: Found {len(moving_jobs)} jobs in MOVING status from previous run.", "WARN")
                
                for job in moving_jobs:
                    job_id = job['id']
                    filename = job.get('filename', 'Unknown')
                    
                    # Mark as ARCHIVED since the file was already created
                    # The email move either completed or will be skipped (already moved or still in inbox)
                    job_manager.update_job_status(
                        job_id, 
                        'ARCHIVED', 
                        log_msg="Recovered from interrupted MOVING state on startup"
                    )
                    self.log(f"  ✓ Recovered Job #{job_id}: {filename}", "INFO")
                
                self.log(f"RECONCILIATION COMPLETE: {len(moving_jobs)} jobs recovered.", "SUCCESS")
        except Exception as e:
            self.log(f"RECONCILIATION ERROR: {e}", "ERROR")

    def _run_agent_loop(self, agent, interval):
        """
        Generic Loop for an Agent Thread.
        """
        self.log(f"{agent.name} Thread Started (Interval: {interval}s).", "INFO")
        
        while self._running and not self._stop_event.is_set():
            try:
                agent.run_cycle()
                time.sleep(interval)
            except Exception as e:
                self.log(f"{agent.name} Error: {e}", "ERROR")
                status_writer.set_error(str(e))
                traceback.print_exc()
                time.sleep(interval)
        
        self.log(f"{agent.name} Thread Stopped.", "INFO")

    def _run_sequential_loop(self):
        """Sequential loop: Hunter -> Auditor -> Clerk"""
        while self._running:
            try:
                # 1. Hunter (Intake)
                if self.hunter_enabled:
                    self.hunter.run_cycle()
                    if self._stop_event.is_set(): break
                
                # 2. Auditor (Classification)
                if self.auditor_enabled:
                    self.auditor.run_cycle()
                    if self._stop_event.is_set(): break
                    
                # 3. Clerk (Filing)
                if self.clerk_enabled:
                    self.clerk.run_cycle()
                    if self._stop_event.is_set(): break

                # Main Loop Interval
                time.sleep(2)
                
            except Exception as e:
                self.log(f"Engine Loop Error: {e}", "ERROR")
                traceback.print_exc()
                time.sleep(5)
        
        self.log("Engine Thread Stopped.", "INFO")


    def _run_reporter_loop(self):
        """
        Background Reporter.
        1. Generates dashboard.html every 60 seconds.
        2. Checks for Email Report Schedules (Daily/Weekly/Monthly).
        """
        from core.dashboard_generator import generate_dashboard
        from core.email_service import EmailService
        from core.secure_config import conf
        from core.realtime_exporter import exporter as csv_exporter
        import datetime
        from datetime import timedelta
        
        
        self.log("Reporter Thread Started.", "INFO")
        print("DEBUG: Reporter Thread Started - Checking Schedule...")
        # print(f"DEBUG: Config Reporting: {conf.get('reporting')}") # Debug noise
        
        # State tracking to prevent double-sending
        last_sent = {
            "daily": None,   # Date string YYYY-MM-DD
            "weekly": None,  # Date string
            "monthly": None  # Date string
        }
        
        while self._running and not self._stop_event.is_set():
            try:
                # 1. Live Dashboard Refresh (Always runs)
                generate_dashboard(days=1, output_mode='file')
                
                # 2. CSV Scheduled Placement (v4.3 Compliance)
                try:
                    csv_exporter.run_scheduled_placements()
                except Exception as csv_err:
                    self.log(f"CSV Placement Check Error: {csv_err}", "WARN")
                
                # 2. Check Reporting Schedule
                cfg = conf.get('reporting', {})
                if cfg.get('enabled'):
                    now = datetime.datetime.now()
                    current_time_str = now.strftime("%H:%M") # HH:MM
                    weekday = now.strftime("%A") # Monday
                    day_str = now.strftime("%Y-%m-%d")
                    
                    subs = cfg.get('subscribers', [])
                    schedules = cfg.get('schedules', {})
                    
                    # --- DAILY REPORT ---
                    if schedules.get('daily') and last_sent['daily'] != day_str:
                        sched_time = schedules['daily']
                        if current_time_str >= sched_time:
                            self.log("Triggering Daily Report...", "INFO")
                            html_body = generate_dashboard(days=1, output_mode='string')
                            subject = f"PCP Daily Report - {day_str}"
                            success, msg = EmailService.send_report(subject, html_body, subs)
                            if success:
                                last_sent['daily'] = day_str
                                self.log(f"Daily Report Sent: {msg}", "SUCCESS")
                            else:
                                self.log(f"Daily Report Failed: {msg}", "ERROR")

                    # --- WEEKLY REPORT ---
                    if schedules.get('weekly') and last_sent['weekly'] != day_str:
                        parts = schedules['weekly'].split(":", 1)
                        if len(parts) == 2:
                             s_day, s_time = parts
                             if weekday == s_day and current_time_str >= s_time:
                                 self.log("Triggering Weekly Report...", "INFO")
                                 html_body = generate_dashboard(days=7, output_mode='string')
                                 subject = f"PCP Weekly Report - {day_str}"
                                 success, msg = EmailService.send_report(subject, html_body, subs)
                                 if success:
                                     last_sent['weekly'] = day_str
                                     self.log(f"Weekly Report Sent: {msg}", "SUCCESS")
                                 else:
                                     self.log(f"Weekly Report Failed: {msg}", "ERROR")

                    # --- MONTHLY REPORT ---
                    if schedules.get('monthly') and last_sent['monthly'] != day_str:
                        parts = schedules['monthly'].split(":", 1)
                        if len(parts) == 2:
                            s_tag, s_time = parts
                            if s_tag == "First" and now.day == 1 and current_time_str >= s_time:
                                self.log("Triggering Monthly Report...", "INFO")
                                html_body = generate_dashboard(days=30, output_mode='string')
                                
                                # Subject: Previous Month Name
                                prev_month = now - timedelta(days=1)
                                subject = f"PCP Monthly Report - {prev_month.strftime('%B %Y')}"
                                
                                success, msg = EmailService.send_report(subject, html_body, subs)
                                if success:
                                    last_sent['monthly'] = day_str
                                    self.log(f"Monthly Report Sent: {msg}", "SUCCESS")
                                else:
                                    self.log(f"Monthly Report Failed: {msg}", "ERROR")

                time.sleep(10)
            except Exception as e:
                self.log(f"Reporter Error: {e}", "ERROR")
                time.sleep(10)
        
        self.log("Reporter Thread Stopped.", "INFO")

