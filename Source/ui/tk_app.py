import datetime
import os
import queue
import shutil
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk, filedialog

from agents.hunter_v2 import HunterV2
from agents.auditor import Auditor
from agents.clerk import Clerk
from core.engine import OrchestratorEngine
from core.secure_config import conf
from core import app_paths
from core import dashboard_generator


def _get_program_data_dir() -> str:
    # Legacy helper name: historically returned ProgramData. Now returns the app's writable base dir.
    return str(app_paths.base_dir())


def _open_path(path: str) -> None:
    if not path:
        return
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        try:
            webbrowser.open(path)
        except Exception:
            pass


class NexusTkApp:
    def __init__(self):
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._running = False
        self._engine = None
        self._engine_init_thread = None

        self.root = tk.Tk()
        self.root.title("PCP Nexus | Document Automation")
        self.root.geometry("980x700")
        self.root.minsize(900, 640)

        self._agent_status_vars = {
            "Intake": tk.StringVar(value="OFFLINE"),
            "Audit": tk.StringVar(value="OFFLINE"),
            "Clerk": tk.StringVar(value="OFFLINE"),
        }

        self._build_ui()
        self._refresh_settings_from_config()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_log_queue)
        
        # Auto-detect Outlook account and connect on startup
        self.root.after(200, self._auto_detect_outlook_account)
        # Live status bar polling
        self.root.after(2000, self._poll_engine_status)

        self._log("Initializing engine (OCR may take a moment)...", "INFO")
        self._async_init_engine()
        self._log("System Ready. Waiting for user activation...", "INFO")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(4, weight=1)

        self.btn_toggle = ttk.Button(header, text="Start Engine", command=self._toggle_engine, state="disabled")
        self.btn_toggle.grid(row=0, column=0, padx=(0, 8))

        ttk.Button(header, text="Open Config", command=self._open_config).grid(row=0, column=1, padx=(0, 8))
        self.btn_open_dashboard = ttk.Button(header, text="Open Dashboard", command=self._open_dashboard)
        self.btn_open_dashboard.grid(row=0, column=2, padx=(0, 8))
        self.btn_open_logs = ttk.Button(header, text="Open Logs", command=self._open_logs)
        self.btn_open_logs.grid(row=0, column=3, padx=(0, 8))

        status_frame = ttk.Frame(header)
        status_frame.grid(row=0, column=4, sticky="e")
        ttk.Label(status_frame, text="Intake:").grid(row=0, column=0, padx=(0, 4))
        ttk.Label(status_frame, textvariable=self._agent_status_vars["Intake"]).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(status_frame, text="Audit:").grid(row=0, column=2, padx=(0, 4))
        ttk.Label(status_frame, textvariable=self._agent_status_vars["Audit"]).grid(row=0, column=3, padx=(0, 10))
        ttk.Label(status_frame, text="Clerk:").grid(row=0, column=4, padx=(0, 4))
        ttk.Label(status_frame, textvariable=self._agent_status_vars["Clerk"]).grid(row=0, column=5)

        body = ttk.Notebook(self.root)
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.tab_console = ttk.Frame(body, padding=10)
        self.tab_settings = ttk.Frame(body, padding=10)
        body.add(self.tab_console, text="Console")
        body.add(self.tab_settings, text="Settings")

        self._build_console_tab()
        self._build_settings_tab()

        # --- FOOTER STATUS BAR ---
        footer = ttk.Frame(self.root, padding=(10, 4))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._status_indicator = tk.Label(
            footer, text="\u26AA Engine Stopped", anchor="w",
            font=("Segoe UI", 9), fg="#888888", bg="#f0f0f0",
            relief="sunken", padx=8, pady=2
        )
        self._status_indicator.grid(row=0, column=0, sticky="ew")

    def _build_console_tab(self) -> None:
        self.tab_console.rowconfigure(0, weight=1)
        self.tab_console.columnconfigure(0, weight=1)

        self.txt_console = tk.Text(self.tab_console, wrap="none", height=20)
        self.txt_console.grid(row=0, column=0, sticky="nsew")

        scroll_y = ttk.Scrollbar(self.tab_console, orient="vertical", command=self.txt_console.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.txt_console.configure(yscrollcommand=scroll_y.set)

        btn_row = ttk.Frame(self.tab_console, padding=(0, 10, 0, 0))
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Button(btn_row, text="Clear Console", command=self._clear_console).pack(side="left")

    def _build_settings_tab(self) -> None:
        # Use a scrollable canvas so the settings tab doesn't clip on smaller windows
        canvas = tk.Canvas(self.tab_settings, borderwidth=0, highlightthickness=0)
        scroll = ttk.Scrollbar(self.tab_settings, orient="vertical", command=canvas.yview)
        self._settings_inner = ttk.Frame(canvas, padding=10)
        self._settings_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._settings_inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        self.tab_settings.columnconfigure(0, weight=1)
        self.tab_settings.rowconfigure(0, weight=1)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        # Enable mouse-wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        sf = self._settings_inner  # shorthand
        sf.columnconfigure(1, weight=1)

        # Outlook Account
        self.var_outlook_account = tk.StringVar()

        # Phase 1 Settings
        self.var_phase1_enabled = tk.BooleanVar(value=True)
        self.var_phase1_input = tk.StringVar()
        self.var_phase1_completed = tk.StringVar()
        self.var_phase1_exceptions = tk.StringVar()
        self.var_phase1_output = tk.StringVar()

        # Phase 2 Settings
        self.var_phase2_enabled = tk.BooleanVar(value=True)
        self.var_phase2_input = tk.StringVar()
        self.var_phase2_completed = tk.StringVar()
        self.var_phase2_exceptions = tk.StringVar()
        self.var_phase2_output = tk.StringVar()

        # Test-only settings
        self.var_phase1_strict_sender = tk.BooleanVar(value=True)
        self.var_phase1_strict_subject = tk.BooleanVar(value=True)
        self.var_phase2_strict_sender = tk.BooleanVar(value=True)
        self.var_phase2_strict_subject = tk.BooleanVar(value=True)
        self.var_phase2_skip_tag = tk.BooleanVar(value=True)
        self.var_phase2_reopen_packets = tk.BooleanVar(value=True)
        self.var_uat_mode = tk.BooleanVar(value=False)

        # Global Settings
        self.var_poll_minutes = tk.StringVar()
        self.var_enable_ocr = tk.BooleanVar()
        self.var_ocr_path = tk.StringVar()

        # CSV & Scheduling Settings
        self.var_csv_output_phase1 = tk.StringVar()
        self.var_csv_output_phase2 = tk.StringVar()
        self.var_csv_archive_phase1 = tk.StringVar()
        self.var_csv_archive_phase2 = tk.StringVar()
        self.var_schedule_p1_mode = tk.StringVar(value="daily")
        self.var_schedule_p1_hour = tk.StringVar(value="22")
        self.var_schedule_p1_minute = tk.StringVar(value="0")
        self.var_schedule_p2_mode = tk.StringVar(value="hourly")
        self.var_email_p1_enabled = tk.BooleanVar(value=False)
        self.var_email_p1_recipient = tk.StringVar()
        self.var_email_p2_enabled = tk.BooleanVar(value=False)
        self.var_email_p2_recipient = tk.StringVar()

        # Legacy compatibility
        self.var_outlook_folder = tk.StringVar()
        self.var_output_path = tk.StringVar()
        self.var_backup_path = tk.StringVar()
        self.var_logs_path = tk.StringVar()
        self.var_verbose = tk.BooleanVar()
        self.var_sound = tk.BooleanVar()

        row = 0

        # ═══════════════════════════════════════
        # OUTLOOK CONNECTION
        # ═══════════════════════════════════════
        ttk.Label(sf, text="─── OUTLOOK CONNECTION ───", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        row += 1

        ttk.Label(sf, text="Outlook Account").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(sf, textvariable=self.var_outlook_account, width=40).grid(row=row, column=1, sticky="ew", pady=4)
        self.btn_test_connection = ttk.Button(sf, text="Test Connection", command=self._test_outlook_connection)
        self.btn_test_connection.grid(row=row, column=2, sticky="e", padx=(10, 0))
        row += 1

        # ═══════════════════════════════════════
        # PHASE 1: CIVIL PROCESS
        # ═══════════════════════════════════════
        ttk.Label(sf, text="─── PHASE 1: CIVIL PROCESS ───", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(16, 8)
        )
        row += 1

        ttk.Checkbutton(sf, text="Phase 1 Enabled", variable=self.var_phase1_enabled).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4
        )
        row += 1

        ttk.Label(sf, text="Inbox Folder").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        self.cbo_phase1_input = ttk.Combobox(sf, textvariable=self.var_phase1_input, width=50)
        self.cbo_phase1_input.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(sf, text="Completed Folder").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        self.cbo_phase1_completed = ttk.Combobox(sf, textvariable=self.var_phase1_completed, width=50)
        self.cbo_phase1_completed.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(sf, text="Exceptions Folder").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        self.cbo_phase1_exceptions = ttk.Combobox(sf, textvariable=self.var_phase1_exceptions, width=50)
        self.cbo_phase1_exceptions.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(sf, text="Output Path").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        entry_p1_output = ttk.Entry(sf, textvariable=self.var_phase1_output)
        entry_p1_output.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(sf, text="Browse", command=lambda: self._browse_dir(entry_p1_output)).grid(
            row=row, column=2, sticky="e", padx=(10, 0)
        )
        row += 1

        # ═══════════════════════════════════════
        # PHASE 2: E-FILING
        # ═══════════════════════════════════════
        ttk.Label(sf, text="─── PHASE 2: E-FILING ───", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(16, 8)
        )
        row += 1

        ttk.Checkbutton(sf, text="Phase 2 Enabled", variable=self.var_phase2_enabled).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4
        )
        row += 1

        ttk.Label(sf, text="Inbox Folder").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        self.cbo_phase2_input = ttk.Combobox(sf, textvariable=self.var_phase2_input, width=50)
        self.cbo_phase2_input.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(sf, text="Completed Folder").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        self.cbo_phase2_completed = ttk.Combobox(sf, textvariable=self.var_phase2_completed, width=50)
        self.cbo_phase2_completed.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(sf, text="Exceptions Folder").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        self.cbo_phase2_exceptions = ttk.Combobox(sf, textvariable=self.var_phase2_exceptions, width=50)
        self.cbo_phase2_exceptions.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(sf, text="Output Path").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        entry_p2_output = ttk.Entry(sf, textvariable=self.var_phase2_output)
        entry_p2_output.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(sf, text="Browse", command=lambda: self._browse_dir(entry_p2_output)).grid(
            row=row, column=2, sticky="e", padx=(10, 0)
        )
        row += 1

        # ═══════════════════════════════════════
        # GLOBAL
        # ═══════════════════════════════════════
        ttk.Label(sf, text="─── GLOBAL ───", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(16, 8)
        )
        row += 1

        ttk.Label(sf, text="Poll Interval (min)").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(sf, textvariable=self.var_poll_minutes, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Checkbutton(sf, text="Enable OCR", variable=self.var_enable_ocr).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4
        )
        row += 1

        # ═══════════════════════════════════════
        # CSV & SCHEDULING (v4.3)
        # ═══════════════════════════════════════
        ttk.Label(sf, text="─── CSV & SCHEDULING ───", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(16, 8)
        )
        row += 1
        ttk.Label(
            sf,
            text="Network share paths for CSV rotation and archive. These are the production destinations.",
            foreground="#777777", wraplength=700, justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1

        ttk.Label(sf, text="P1 CSV Share Path").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry_csv_p1 = ttk.Entry(sf, textvariable=self.var_csv_output_phase1)
        entry_csv_p1.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(sf, text="Browse", command=lambda: self._browse_dir(entry_csv_p1)).grid(
            row=row, column=2, sticky="e", padx=(10, 0)
        )
        row += 1

        ttk.Label(sf, text="P1 CSV Archive Path").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry_csv_arch_p1 = ttk.Entry(sf, textvariable=self.var_csv_archive_phase1)
        entry_csv_arch_p1.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(sf, text="Browse", command=lambda: self._browse_dir(entry_csv_arch_p1)).grid(
            row=row, column=2, sticky="e", padx=(10, 0)
        )
        row += 1

        ttk.Label(sf, text="P2 CSV Share Path").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry_csv_p2 = ttk.Entry(sf, textvariable=self.var_csv_output_phase2)
        entry_csv_p2.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(sf, text="Browse", command=lambda: self._browse_dir(entry_csv_p2)).grid(
            row=row, column=2, sticky="e", padx=(10, 0)
        )
        row += 1

        ttk.Label(sf, text="P2 CSV Archive Path").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        entry_csv_arch_p2 = ttk.Entry(sf, textvariable=self.var_csv_archive_phase2)
        entry_csv_arch_p2.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(sf, text="Browse", command=lambda: self._browse_dir(entry_csv_arch_p2)).grid(
            row=row, column=2, sticky="e", padx=(10, 0)
        )
        row += 1

        ttk.Separator(sf, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Label(sf, text="P1 Rotation").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        sched_p1 = ttk.Frame(sf)
        sched_p1.grid(row=row, column=1, sticky="w", pady=3)
        ttk.Combobox(sched_p1, textvariable=self.var_schedule_p1_mode, values=["daily", "hourly"], width=8, state="readonly").pack(side="left")
        ttk.Label(sched_p1, text="  Hour:").pack(side="left")
        ttk.Entry(sched_p1, textvariable=self.var_schedule_p1_hour, width=4).pack(side="left")
        ttk.Label(sched_p1, text="  Min:").pack(side="left")
        ttk.Entry(sched_p1, textvariable=self.var_schedule_p1_minute, width=4).pack(side="left")
        row += 1

        ttk.Label(sf, text="P2 Rotation").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        sched_p2 = ttk.Frame(sf)
        sched_p2.grid(row=row, column=1, sticky="w", pady=3)
        ttk.Combobox(sched_p2, textvariable=self.var_schedule_p2_mode, values=["daily", "hourly"], width=8, state="readonly").pack(side="left")
        row += 1

        ttk.Separator(sf, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1

        ttk.Checkbutton(sf, text="P1 Auto-Email CSV after rotation", variable=self.var_email_p1_enabled).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2
        )
        row += 1
        ttk.Label(sf, text="P1 Recipient").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        ttk.Entry(sf, textvariable=self.var_email_p1_recipient).grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        ttk.Checkbutton(sf, text="P2 Auto-Email CSV after rotation", variable=self.var_email_p2_enabled).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2
        )
        row += 1
        ttk.Label(sf, text="P2 Recipient").grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        ttk.Entry(sf, textvariable=self.var_email_p2_recipient).grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        # ═══════════════════════════════════════
        # 🧪 LOCAL TESTING  (boxed group)
        # ═══════════════════════════════════════
        test_box = ttk.LabelFrame(
            sf,
            text="  Local Testing Only  ",
            padding=12,
        )
        test_box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(16, 4))
        test_box.columnconfigure(1, weight=1)
        row += 1

        tr = 0  # row counter inside the test_box
        ttk.Label(
            test_box,
            text=(
                "These settings are for LOCAL / UAT testing only. In production, "
                "Strict Sender and Strict Subject should be ON to enforce sender and "
                "subject-line validation. Turning them OFF lets test emails bypass "
                "validation without being moved to AI Exceptions."
            ),
            foreground="#999999", wraplength=700, justify="left",
        ).grid(row=tr, column=0, columnspan=3, sticky="w", pady=(0, 10))
        tr += 1

        ttk.Checkbutton(test_box, text="UAT Mode (master test flag)", variable=self.var_uat_mode).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2
        )
        tr += 1

        ttk.Separator(test_box, orient="horizontal").grid(row=tr, column=0, columnspan=3, sticky="ew", pady=6)
        tr += 1

        ttk.Label(test_box, text="Phase 1", font=("Segoe UI", 9, "bold")).grid(row=tr, column=0, sticky="w", pady=(4, 2))
        tr += 1
        ttk.Checkbutton(test_box, text="Strict Sender Validation", variable=self.var_phase1_strict_sender).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2, padx=(16, 0)
        )
        tr += 1
        ttk.Checkbutton(test_box, text="Strict Subject Validation", variable=self.var_phase1_strict_subject).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2, padx=(16, 0)
        )
        tr += 1

        ttk.Label(test_box, text="Phase 2", font=("Segoe UI", 9, "bold")).grid(row=tr, column=0, sticky="w", pady=(8, 2))
        tr += 1
        ttk.Checkbutton(test_box, text="Strict Sender Validation", variable=self.var_phase2_strict_sender).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2, padx=(16, 0)
        )
        tr += 1
        ttk.Checkbutton(test_box, text="Strict Subject Validation", variable=self.var_phase2_strict_subject).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2, padx=(16, 0)
        )
        tr += 1
        ttk.Checkbutton(test_box, text="Skip Tag When No Files", variable=self.var_phase2_skip_tag).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2, padx=(16, 0)
        )
        tr += 1
        ttk.Checkbutton(test_box, text="Reopen Completed Packets on New Files", variable=self.var_phase2_reopen_packets).grid(
            row=tr, column=0, columnspan=2, sticky="w", pady=2, padx=(16, 0)
        )
        tr += 1

        ttk.Label(
            test_box,
            text=(
                "Production: Strict Sender ON, Strict Subject ON, Skip Tag ON, Reopen Packets OFF, UAT Mode OFF.\n"
                "Testing:     Strict Sender OFF, Strict Subject OFF, Skip Tag ON, Reopen Packets ON, UAT Mode ON."
            ),
            foreground="#888888", font=("Consolas", 8),
        ).grid(row=tr, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tr += 1

        # ═══════════════════════════════════════
        # ACTION BUTTONS
        # ═══════════════════════════════════════
        btns = ttk.Frame(sf, padding=(0, 16, 0, 0))
        btns.grid(row=row, column=0, columnspan=3, sticky="w")
        ttk.Button(btns, text="Save Settings", command=self._save_settings).pack(side="left")
        ttk.Button(btns, text="Reload", command=self._refresh_settings_from_config).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Open Config File", command=self._open_config).pack(side="left", padx=(8, 0))

    def _test_outlook_connection(self) -> None:
        """Test Outlook connection and populate folder dropdowns."""
        account_name = self.var_outlook_account.get().strip()
        if not account_name:
            messagebox.showerror("Error", "Please enter an Outlook account email address first.")
            return

        if getattr(self, "btn_test_connection", None):
            self.btn_test_connection.configure(state="disabled")

        self._log("Testing Outlook connection (this can take a moment on large mailboxes)...", "INFO")

        def worker():
            folder_list = []
            smtp = None
            err = None
            try:
                import pythoncom
                pythoncom.CoInitialize()
                import win32com.client

                outlook = win32com.client.Dispatch("Outlook.Application")
                namespace = outlook.GetNamespace("MAPI")

                # Find matching account by SMTP address (users typically enter email)
                target_account = None
                available = []
                for acc in namespace.Accounts:
                    try:
                        available.append(acc.SmtpAddress)
                    except Exception:
                        continue
                    try:
                        if account_name.lower() in acc.SmtpAddress.lower():
                            target_account = acc
                            break
                    except Exception:
                        continue

                if not target_account:
                    err = f"Account not found: {account_name}\n\nAvailable accounts:\n" + "\n".join(available)
                else:
                    smtp = getattr(target_account, "SmtpAddress", None)
                    
                    # Scan ALL mailboxes (including shared mailboxes like efiling, eaffidavits)
                    max_folders = 5000
                    for mailbox in namespace.Folders:
                        mailbox_name = mailbox.Name
                        if "Public Folders" in mailbox_name:
                            continue
                        
                        # Add mailbox root and iterate its subfolders
                        stack = [(mailbox, f"{mailbox_name}\\")]
                        while stack and len(folder_list) < max_folders:
                            parent, prefix = stack.pop()
                            try:
                                for f in parent.Folders:
                                    name = getattr(f, "Name", "")
                                    if not name:
                                        continue
                                    path = f"{prefix}{name}"
                                    folder_list.append(path)
                                    stack.append((f, f"{path}\\"))
                                    if len(folder_list) >= max_folders:
                                        break
                            except Exception:
                                continue
            except Exception as e:
                err = f"Failed to connect to Outlook:\n\n{e}"
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

            def finish():
                if getattr(self, "btn_test_connection", None):
                    self.btn_test_connection.configure(state="normal")

                if err:
                    messagebox.showerror("Connection Error", err)
                    return

                # Populate all comboboxes
                self.cbo_phase1_input["values"] = folder_list
                self.cbo_phase1_completed["values"] = folder_list
                self.cbo_phase1_exceptions["values"] = folder_list
                self.cbo_phase2_input["values"] = folder_list
                self.cbo_phase2_completed["values"] = folder_list
                self.cbo_phase2_exceptions["values"] = folder_list

                shown = len(folder_list)
                extra = " (showing first 5000)" if shown >= 5000 else ""
                messagebox.showinfo("Success", f"✓ Connected to {smtp}\n\nFound {shown} folders{extra}.\nDropdowns populated.")

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True, name="OutlookTestThread").start()

    def _auto_detect_outlook_account(self) -> None:
        """Auto-detect Outlook account if Outlook is already running. Shows error if not running."""
        def worker():
            detected_email = None
            outlook_not_running = False
            try:
                import pythoncom
                pythoncom.CoInitialize()
                import win32com.client
                
                # Use GetActiveObject - will fail if Outlook Classic isn't running
                # This does NOT launch Outlook, just connects to an existing instance
                try:
                    outlook = win32com.client.GetActiveObject("Outlook.Application")
                except Exception:
                    outlook_not_running = True
                    raise Exception("Outlook Classic is not running. Please start Outlook before using this application.")
                
                namespace = outlook.GetNamespace("MAPI")
                
                # Get first account's SMTP address
                for acc in namespace.Accounts:
                    try:
                        detected_email = acc.SmtpAddress
                        break
                    except Exception:
                        continue
            except Exception as e:
                if outlook_not_running:
                    self._log(f"[Auto-Detect] ERROR: Outlook Classic is not running. Please start Outlook first.", "ERROR")
                else:
                    self._log(f"[Auto-Detect] Outlook connection warning: {e}", "WARN")
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            
            def finish():
                if detected_email:
                    current = self.var_outlook_account.get().strip()
                    if not current:
                        self.var_outlook_account.set(detected_email)
                        self._log(f"[Auto-Detect] Found Outlook account: {detected_email}", "INFO")
                    else:
                        self._log(f"[Auto-Detect] Using configured account: {current}", "INFO")
                    # Trigger silent connection test to populate folders
                    self.root.after(300, self._auto_test_connection)
                elif not outlook_not_running:
                    self._log("[Auto-Detect] No Outlook account detected. Please enter manually.", "WARN")
            
            self.root.after(0, finish)
        
        threading.Thread(target=worker, daemon=True, name="OutlookAutoDetect").start()

    def _auto_test_connection(self) -> None:
        """Silently test Outlook connection and populate folder dropdowns (no popups)."""
        account_name = self.var_outlook_account.get().strip()
        if not account_name:
            self._log("[Auto-Connect] No Outlook account configured, skipping.", "WARN")
            return

        self._log("[Auto-Connect] Connecting to Outlook (populating folders)...", "INFO")

        def worker():
            folder_list = []
            smtp = None
            err = None
            try:
                import pythoncom
                pythoncom.CoInitialize()
                import win32com.client

                outlook = win32com.client.Dispatch("Outlook.Application")
                namespace = outlook.GetNamespace("MAPI")

                # Find matching account by SMTP address
                target_account = None
                for acc in namespace.Accounts:
                    try:
                        if account_name.lower() in acc.SmtpAddress.lower():
                            target_account = acc
                            break
                    except Exception:
                        continue

                if not target_account:
                    err = f"Account not found: {account_name}"
                else:
                    smtp = getattr(target_account, "SmtpAddress", None)
                    
                    # Scan ALL mailboxes (including shared mailboxes like efiling, eaffidavits)
                    max_folders = 5000
                    for mailbox in namespace.Folders:
                        mailbox_name = mailbox.Name
                        if "Public Folders" in mailbox_name:
                            continue
                        
                        # Add mailbox root and iterate its subfolders
                        stack = [(mailbox, f"{mailbox_name}\\")]
                        while stack and len(folder_list) < max_folders:
                            parent, prefix = stack.pop()
                            try:
                                for f in parent.Folders:
                                    name = getattr(f, "Name", "")
                                    if not name:
                                        continue
                                    path = f"{prefix}{name}"
                                    folder_list.append(path)
                                    stack.append((f, f"{path}\\"))
                                    if len(folder_list) >= max_folders:
                                        break
                            except Exception:
                                continue
            except Exception as e:
                err = f"Failed to connect: {e}"
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

            def finish():
                if err:
                    self._log(f"[Auto-Connect] {err}", "WARN")
                    return

                # Populate all comboboxes silently
                self.cbo_phase1_input["values"] = folder_list
                self.cbo_phase1_completed["values"] = folder_list
                self.cbo_phase2_input["values"] = folder_list
                self.cbo_phase2_completed["values"] = folder_list

                self._log(f"[Auto-Connect] ✓ Connected to {smtp} ({len(folder_list)} folders loaded)", "SUCCESS")

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True, name="OutlookAutoConnect").start()

    def _async_init_engine(self) -> None:
        if self._engine_init_thread and self._engine_init_thread.is_alive():
            return

        def worker():
            err = None
            engine = None
            try:
                engine = self._init_engine()
            except Exception as e:
                err = str(e)

            def finish():
                if err:
                    self._log(f"Engine initialization failed: {err}", "ERROR")
                    messagebox.showerror("Engine Error", f"Engine failed to initialize:\n\n{err}")
                    self.btn_toggle.configure(state="disabled")
                    return

                self._engine = engine
                self.btn_toggle.configure(state="normal")
                self._log("Engine ready.", "SUCCESS")

            self.root.after(0, finish)

        self._engine_init_thread = threading.Thread(target=worker, daemon=True, name="EngineInitThread")
        self._engine_init_thread.start()

    def _browse_dir(self, widget: tk.Widget) -> None:
        initial = None
        try:
            initial = widget.get()
        except Exception:
            initial = None
        chosen = filedialog.askdirectory(initialdir=initial or None)
        if chosen:
            try:
                widget.delete(0, "end")
                widget.insert(0, chosen)
            except Exception:
                pass

    def _init_engine(self) -> OrchestratorEngine:
        def log_callback(msg: str, level: str = "INFO") -> None:
            self._log(msg, level)

        def ui_callback(agent_name: str, status: str) -> None:
            var = self._agent_status_vars.get(agent_name)
            if not var:
                return
            self.root.after(0, lambda: var.set(status))

        hunter = HunterV2(ui_callback=ui_callback)
        auditor = Auditor(ui_callback=ui_callback)
        clerk = Clerk(config=conf, ui_callback=ui_callback)

        # Preserve existing file logging, but also surface to UI
        def patch_agent(agent):
            original = agent.log

            def wrapped(message, level="INFO"):
                try:
                    original(message, level)
                except Exception:
                    pass
                log_callback(f"{agent.name}: {message}", level)

            agent.log = wrapped

        for agent in (hunter, auditor, clerk):
            patch_agent(agent)

        return OrchestratorEngine(hunter, auditor, clerk, log_callback)

    def _toggle_engine(self) -> None:
        if not self._engine:
            messagebox.showinfo("Engine", "Engine is still initializing. Please wait a moment and try again.")
            return

        self._running = not self._running

        if self._running:
            self.btn_toggle.configure(text="Stop Engine")
            for v in self._agent_status_vars.values():
                v.set("ONLINE")
            self._engine.start()
        else:
            self.btn_toggle.configure(text="Start Engine")
            self._engine.stop()
            for v in self._agent_status_vars.values():
                v.set("OFFLINE")

    def _poll_engine_status(self) -> None:
        """Poll engine_status.json every 2s and update footer status bar."""
        try:
            from core.status_writer import StatusWriter
            import datetime
            status = StatusWriter.read()
            if status:
                state = status.get("state", "STOPPED")
                phase = status.get("phase", "")
                activity = status.get("activity", "")
                progress = status.get("progress", "")
                envelope = status.get("current_envelope", "")
                
                # Build display text
                if state == "RUNNING" and progress:
                    # Active processing with progress
                    phase_label = "Phase 1" if phase == "Phase1" else "Phase 2" if phase == "Phase2" else ""
                    text = f"\U0001F7E2 {phase_label}: {activity} [{progress}]"
                    if envelope:
                        text += f" | Env: {envelope}"
                    # Add elapsed time
                    cycle_start = status.get("cycle_start")
                    if cycle_start:
                        try:
                            start = datetime.datetime.fromisoformat(cycle_start)
                            elapsed = datetime.datetime.now() - start
                            mins = int(elapsed.total_seconds() // 60)
                            secs = int(elapsed.total_seconds() % 60)
                            text += f" | \u23F1 {mins}m {secs}s"
                        except Exception:
                            pass
                    color = "#2e7d32"  # green
                elif state == "RUNNING":
                    text = f"\U0001F7E2 Engine Active \u2014 {activity}"
                    color = "#2e7d32"
                elif state == "ERROR":
                    text = f"\U0001F534 {activity}"
                    color = "#c62828"
                elif state == "STALLED":
                    text = f"\U0001F7E1 Engine Stalled \u2014 No heartbeat"
                    color = "#f57f17"
                else:
                    text = "\u26AA Engine Stopped"
                    color = "#888888"
                
                self._status_indicator.configure(text=text, fg=color)
            else:
                self._status_indicator.configure(
                    text="\u26AA Engine Stopped", fg="#888888"
                )
        except Exception:
            pass  # Non-critical — don't crash the UI
        finally:
            self.root.after(2000, self._poll_engine_status)

    def _clear_console(self) -> None:
        self.txt_console.delete("1.0", "end")

    def _log(self, msg: str, level: str = "INFO") -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_queue.put(f"[{ts}] [{level}] {msg}")

    def _drain_log_queue(self) -> None:
        max_per_tick = 200
        processed = 0
        try:
            while processed < max_per_tick:
                line = self._log_queue.get_nowait()
                self.txt_console.insert("end", line + "\n")
                self.txt_console.see("end")
                processed += 1
        except queue.Empty:
            pass

        # Prevent UI lockups on long runs by trimming the text widget.
        try:
            max_lines = 3000
            line_count = int(self.txt_console.index("end-1c").split(".")[0])
            if line_count > max_lines:
                # Delete oldest lines, keep the newest `max_lines`.
                delete_upto = line_count - max_lines + 1
                self.txt_console.delete("1.0", f"{delete_upto}.0")
        except Exception:
            pass
        self.root.after(150, self._drain_log_queue)

    def _open_config(self) -> None:
        path = getattr(conf, "config_path", None)
        if not path:
            messagebox.showerror("Error", "Config path not resolved.")
            return
        if not os.path.exists(path):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("{}\n")
            except Exception as e:
                messagebox.showerror("Error", f"Config not found and could not be created:\n\n{path}\n\n{e}")
                return
        _open_path(path)

    def _open_logs(self) -> None:
        path = conf.get("paths.logs") or str(app_paths.logs_dir())
        os.makedirs(path, exist_ok=True)
        _open_path(path)

    def _open_dashboard(self) -> None:
        if getattr(self, "btn_open_dashboard", None):
            self.btn_open_dashboard.configure(state="disabled")

        self._log("Generating dashboard...", "INFO")

        def worker():
            html = None
            err = None
            try:
                html = dashboard_generator.generate_dashboard(days=1, output_mode="string")
            except Exception as e:
                err = str(e)

            def finish():
                if getattr(self, "btn_open_dashboard", None):
                    self.btn_open_dashboard.configure(state="normal")

                if err:
                    messagebox.showerror("Dashboard Error", err)
                    return

                if not html:
                    messagebox.showinfo("Dashboard", "Dashboard not available yet (DB/jobs table not ready). Run the engine first.")
                    return

                out_dir = str(app_paths.dashboard_dir())
                assets_dir = os.path.join(out_dir, "assets")
                os.makedirs(assets_dir, exist_ok=True)

                # Copy logo so the dashboard renders cleanly outside Program Files.
                try:
                    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    src_logo = os.path.join(app_root, "assets", "pcp_logo.jpg")
                    dst_logo = os.path.join(assets_dir, "pcp_logo.jpg")
                    if os.path.exists(src_logo) and not os.path.exists(dst_logo):
                        shutil.copy(src_logo, dst_logo)
                except Exception:
                    pass

                out_path = os.path.join(out_dir, "dashboard.html")
                try:
                    with open(out_path, "w", encoding="utf-8") as handle:
                        handle.write(html)
                except Exception as e:
                    messagebox.showerror("Dashboard Error", f"Failed to write dashboard: {e}")
                    return

                _open_path(out_path)

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True, name="DashboardThread").start()

    def _refresh_settings_from_config(self) -> None:
        # Outlook
        self.var_outlook_account.set(conf.get("outlook_account", "") or "")

        # Phase 1
        self.var_phase1_enabled.set(bool(conf.get("Phase1.Enabled", True)))
        self.var_phase1_input.set(conf.get("Phase1.Input", "Inbox") or "Inbox")
        self.var_phase1_completed.set(conf.get("Phase1.Completed", "") or "")
        self.var_phase1_exceptions.set(conf.get("Phase1.Exceptions", "") or "")
        self.var_phase1_output.set(conf.get("Phase1.Output", "") or str(app_paths.default_phase_output_dir("Phase1")))

        # Phase 2
        self.var_phase2_enabled.set(bool(conf.get("Phase2.Enabled", True)))
        self.var_phase2_input.set(conf.get("Phase2.Input", "Inbox") or "Inbox")
        self.var_phase2_completed.set(conf.get("Phase2.Completed", "") or "")
        self.var_phase2_exceptions.set(conf.get("Phase2.Exceptions", "") or "")
        self.var_phase2_output.set(conf.get("Phase2.Output", "") or str(app_paths.default_phase_output_dir("Phase2")))

        # Global
        self.var_poll_minutes.set(str(conf.get("PollIntervalMinutes", 5) or 5))
        self.var_enable_ocr.set(bool(conf.get("EnableOCR", False)))

        # CSV & Scheduling (v4.3)
        self.var_csv_output_phase1.set(conf.get("paths.csv_output_phase1", "") or "")
        self.var_csv_output_phase2.set(conf.get("paths.csv_output_phase2", "") or "")
        self.var_csv_archive_phase1.set(conf.get("paths.csv_archive_phase1", "") or "")
        self.var_csv_archive_phase2.set(conf.get("paths.csv_archive_phase2", "") or "")
        self.var_schedule_p1_mode.set(conf.get("schedule.phase1_mode", "daily") or "daily")
        self.var_schedule_p1_hour.set(str(conf.get("schedule.phase1_hour", 22)))
        self.var_schedule_p1_minute.set(str(conf.get("schedule.phase1_minute", 0)))
        self.var_schedule_p2_mode.set(conf.get("schedule.phase2_mode", "hourly") or "hourly")
        self.var_email_p1_enabled.set(bool(conf.get("email.phase1_enabled", False)))
        self.var_email_p1_recipient.set(conf.get("email.phase1_recipient", "") or "")
        self.var_email_p2_enabled.set(bool(conf.get("email.phase2_enabled", False)))
        self.var_email_p2_recipient.set(conf.get("email.phase2_recipient", "") or "")

        # Test-only settings
        self.var_phase1_strict_sender.set(bool(conf.get("Phase1.StrictSender", True)))
        self.var_phase1_strict_subject.set(bool(conf.get("Phase1.StrictSubject", True)))
        self.var_phase2_strict_sender.set(bool(conf.get("Phase2.StrictSender", True)))
        self.var_phase2_strict_subject.set(bool(conf.get("Phase2.StrictSubject", True)))
        self.var_phase2_skip_tag.set(bool(conf.get("Phase2.SkipTagOnNoFiles", True)))
        self.var_phase2_reopen_packets.set(bool(conf.get("Phase2.ReopenCompletedOnNewFiles", True)))
        self.var_uat_mode.set(bool(conf.get("UAT_MODE", False)))

        # Legacy (keep for compatibility)
        self.var_outlook_folder.set(conf.get("outlook_folder", "Inbox") or "Inbox")
        self.var_output_path.set(conf.get("paths.output", "") or "")
        self.var_backup_path.set(conf.get("paths.backup", "") or "")
        self.var_logs_path.set(conf.get("paths.logs", "") or "")
        self.var_ocr_path.set(conf.get("OCRPath", "") or "")
        self.var_verbose.set(bool(conf.get("ui.verbose", False)))
        self.var_sound.set(bool(conf.get("ui.sound", True)))

    def _save_settings(self) -> None:
        try:
            # Outlook Account
            conf.set("outlook_account", self.var_outlook_account.get().strip())

            # Phase 1
            p1_enabled = bool(self.var_phase1_enabled.get())
            p1_input = self.var_phase1_input.get().strip() or "Inbox"
            p1_completed = self.var_phase1_completed.get().strip()
            p1_exceptions = self.var_phase1_exceptions.get().strip()
            p1_output = self.var_phase1_output.get().strip()

            conf.set("Phase1.Enabled", p1_enabled)
            conf.set("Phase1.Input", p1_input)
            conf.set("Phase1.Completed", p1_completed)
            conf.set("Phase1.Exceptions", p1_exceptions)
            conf.set("Phase1.Output", p1_output)

            # Sync nested structure (Critical for persistence)
            conf.set("Phases.Phase1.Enabled", p1_enabled)
            conf.set("Phases.Phase1.InputFolder", p1_input)
            conf.set("Phases.Phase1.ProcessedFolder", p1_completed)
            conf.set("Phases.Phase1.ExceptionFolder", p1_exceptions)
            conf.set("Phases.Phase1.OutputPath", p1_output)

            # Phase 2
            p2_enabled = bool(self.var_phase2_enabled.get())
            p2_input = self.var_phase2_input.get().strip() or "Inbox"
            p2_completed = self.var_phase2_completed.get().strip()
            p2_exceptions = self.var_phase2_exceptions.get().strip()
            p2_output = self.var_phase2_output.get().strip()

            conf.set("Phase2.Enabled", p2_enabled)
            conf.set("Phase2.Input", p2_input)
            conf.set("Phase2.Completed", p2_completed)
            conf.set("Phase2.Exceptions", p2_exceptions)
            conf.set("Phase2.Output", p2_output)

            # Sync nested structure (Critical for persistence)
            conf.set("Phases.Phase2.Enabled", p2_enabled)
            conf.set("Phases.Phase2.InputFolder", p2_input)
            conf.set("Phases.Phase2.ProcessedFolder", p2_completed)
            conf.set("Phases.Phase2.ExceptionFolder", p2_exceptions)
            conf.set("Phases.Phase2.OutputPath", p2_output)

            # Global
            poll_raw = self.var_poll_minutes.get().strip()
            poll = int(poll_raw) if poll_raw else 5
            conf.set("PollIntervalMinutes", max(1, poll))
            conf.set("EnableOCR", bool(self.var_enable_ocr.get()))

            # CSV & Scheduling (v4.3)
            conf.set("paths.csv_output_phase1", self.var_csv_output_phase1.get().strip())
            conf.set("paths.csv_output_phase2", self.var_csv_output_phase2.get().strip())
            conf.set("paths.csv_archive_phase1", self.var_csv_archive_phase1.get().strip())
            conf.set("paths.csv_archive_phase2", self.var_csv_archive_phase2.get().strip())
            conf.set("schedule.phase1_mode", self.var_schedule_p1_mode.get().strip() or "daily")
            try:
                conf.set("schedule.phase1_hour", int(self.var_schedule_p1_hour.get().strip() or 22))
            except ValueError:
                conf.set("schedule.phase1_hour", 22)
            try:
                conf.set("schedule.phase1_minute", int(self.var_schedule_p1_minute.get().strip() or 0))
            except ValueError:
                conf.set("schedule.phase1_minute", 0)
            conf.set("schedule.phase2_mode", self.var_schedule_p2_mode.get().strip() or "hourly")
            conf.set("email.phase1_enabled", bool(self.var_email_p1_enabled.get()))
            conf.set("email.phase1_recipient", self.var_email_p1_recipient.get().strip())
            conf.set("email.phase2_enabled", bool(self.var_email_p2_enabled.get()))
            conf.set("email.phase2_recipient", self.var_email_p2_recipient.get().strip())

            # Test-only settings
            conf.set("Phase1.StrictSender", bool(self.var_phase1_strict_sender.get()))
            conf.set("Phase1.StrictSubject", bool(self.var_phase1_strict_subject.get()))
            conf.set("Phase2.StrictSender", bool(self.var_phase2_strict_sender.get()))
            conf.set("Phase2.StrictSubject", bool(self.var_phase2_strict_subject.get()))
            conf.set("Phase2.SkipTagOnNoFiles", bool(self.var_phase2_skip_tag.get()))
            conf.set("Phase2.ReopenCompletedOnNewFiles", bool(self.var_phase2_reopen_packets.get()))
            conf.set("UAT_MODE", bool(self.var_uat_mode.get()))

            # Legacy (keep for compatibility)
            conf.set("outlook_folder", self.var_outlook_folder.get().strip() or "Inbox")
            conf.set("paths.output", self.var_output_path.get().strip())
            conf.set("paths.backup", self.var_backup_path.get().strip())
            conf.set("paths.logs", self.var_logs_path.get().strip())
            conf.set("OCRPath", self.var_ocr_path.get().strip())
            conf.set("ui.verbose", bool(self.var_verbose.get()))
            conf.set("ui.sound", bool(self.var_sound.get()))

            ok = conf.save()
            if ok:
                messagebox.showinfo("Settings", f"Saved: {getattr(conf, 'config_path', 'config.json')}")
            else:
                messagebox.showerror("Settings", "Save failed. Try running as Administrator.")
        except PermissionError as e:
            messagebox.showerror("Settings", f"Permission denied. Run as Administrator.\n\n{e}")
        except Exception as e:
            messagebox.showerror("Settings", f"Save error: {e}")

    def _on_close(self) -> None:
        if self._engine and self._running:
            if not messagebox.askyesno("Exit", "Engine is running. Stop and exit?"):
                return
            try:
                self._engine.stop()
            except Exception:
                pass
        self.root.destroy()


def run() -> None:
    app = NexusTkApp()
    app.root.mainloop()


if __name__ == "__main__":
    run()
