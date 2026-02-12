
import flet as ft
import datetime
import os
import json
from agents.hunter_v2 import HunterV2 as Hunter
from agents.auditor import Auditor
from agents.clerk import Clerk
from core.engine import OrchestratorEngine
from core.secure_config import conf
from core import app_paths
from core.telemetry import Telemetry
from core.dashboard_generator import generate_dashboard
import sqlite3
import pandas as pd
import subprocess
import sys
import threading
import time

# Track child process
dashboard_process = None

def main_window(page: ft.Page):
    # -- Branding / Theme Configuration --
    PCP_RED = "#c62127"  
    PCP_RED_DARK = "#4a0b0d" # Darker shade for gradients
    WINDOWS_BLUE = "#357EC7" # User requested Windows Blue

    # iPhone-style Glass Settings
    # Darker tint for contrast against Blue background
    GLASS_COLOR = "#40000000" # 25% Black tint
    GLASS_BORDER = "#30ffffff" # Stronger white border for definition
    GLASS_BLUR = 20 # Heavy blur

    page.title = "PCP Nexus | Document Automation"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0 # Remove page padding to allow full-screen gradient
    page.window.width = 1100
    page.window.height = 700
    
    # -- SnackBar for Settings Page Feedback --
    def show_snack(message, success=True):
        """Show a visual feedback message to the user."""
        page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color="white"),
            bgcolor="#34c759" if success else "#ff3b30",
            duration=3000
        )
        page.snack_bar.open = True
        try:
            page.update()
        except:
            pass
    
    # -- Folder Picker Setup (Flet 0.80+ synchronous API) --
    # In Flet 0.80+, get_directory_path() returns the path directly (synchronous)
    # We use a simple helper function instead of callbacks
    
    def browse_for_folder(target_field=None, callback=None):
        """Opens folder picker and updates target field or calls callback."""
        folder_picker = ft.FilePicker()
        page.overlay.append(folder_picker)
        page.update()
        
        # Get path synchronously
        result = folder_picker.get_directory_path(dialog_title="Select Folder")
        
        if result:
            if target_field:
                target_field.value = result
                target_field.update()
            if callback:
                callback(result)
            show_snack(f"✓ Path set to: {result}", success=True)
        
        # Clean up
        page.overlay.remove(folder_picker)
        page.update()
    
    
    # -- Components --
    
    # Styles
    glass_style = {
        "bgcolor": GLASS_COLOR,
        "border": ft.border.all(1, GLASS_BORDER),
        "border_radius": 4,
        "padding": 20,
        "blur": ft.Blur(sigma_x=GLASS_BLUR, sigma_y=GLASS_BLUR, tile_mode=ft.BlurTileMode.MIRROR),
        "animate": ft.Animation(400, "easeOutCubic"),
    }

    def on_hover_card(e):
        container = e.control
        is_hovered = e.data == "true"
        
        # Visual Pop for the Card
        container.scale = 1.05 if is_hovered else 1.0
        # Animate shadow to transparent instead of None to prevent artifacts
        container.shadow = ft.BoxShadow(spread_radius=1, blur_radius=20, color="#44000000", offset=ft.Offset(0,10)) if is_hovered else ft.BoxShadow(spread_radius=0, blur_radius=0, color="transparent", offset=ft.Offset(0,0))
        
        # Frost Effect on Content
        stack = container.content
        if len(stack.controls) > 1:
            overlay = stack.controls[1]
            # Use CLAMP to avoid pulling edge pixels (which might be white)
            overlay.blur = ft.Blur(5, 5, ft.BlurTileMode.CLAMP) if is_hovered else ft.Blur(0, 0, ft.BlurTileMode.CLAMP)
        
        container.update()

    # Dictionary to store references to Status Text controls for updates
    agent_status_refs = {}

    def create_agent_card(name, role, status, icon_name, color_code):
        status_text = ft.Text(status, size=10, color="white", weight="bold")
        # Register for updates
        agent_status_refs[name] = status_text

        content_column = ft.Column([
                ft.Container(
                    content=ft.Icon(icon_name, size=32, color="white"),  # Flet 0.80: positional
                    bgcolor=color_code,
                    padding=10,
                    border_radius=50,
                    shadow=ft.BoxShadow(spread_radius=1, blur_radius=10, color=color_code, offset=ft.Offset(0,0))
                ),
                ft.Text(name, size=18, weight="bold", color="white", font_family="Segoe UI Variable"),
                ft.Text(role, size=11, color="white70", italic=True),
                ft.Divider(height=10, color="transparent"),
                ft.Container(
                    content=status_text,
                    bgcolor="#30000000",
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    border_radius=10
                ),
            ], alignment="center", horizontal_alignment="center", spacing=5)
            
        frost_overlay = ft.Container(
            expand=True,
            bgcolor="transparent",
            blur=ft.Blur(0, 0, ft.BlurTileMode.CLAMP), # Use CLAMP
            border_radius=4,
            opacity=1.0, # Always present, just unblurred
            animate=ft.Animation(750, "easeOut"), # Faster animation
            ignore_interactions=True 
        )

        return ft.Container(
            content=ft.Stack([
                ft.Container(content=content_column, padding=20), # Content
                frost_overlay # Glass on top
            ], expand=True),
            width=260, height=200,
            bgcolor=GLASS_COLOR,
            border=ft.border.all(1, GLASS_BORDER),
            border_radius=4,
            animate=ft.Animation(400, "easeOutCubic"),
            animate_scale=ft.Animation(400, "easeOutBack"),
            on_hover=on_hover_card,
            scale=1.0
        )

    # (View State logic moved to bottom)
        
    # Header (Skeleton)
    # Header (Factory to allow dynamic updates if needed, but we'll use one static instance and update state)
    
    # Navigation Buttons
    btn_nav_dashboard = ft.IconButton("monitor_heart", tooltip="Live Dashboard", icon_color="white54")
    btn_nav_sql = ft.IconButton("dataset", tooltip="SQL Console", icon_color="white54")
    btn_nav_settings = ft.IconButton("settings", tooltip="Configuration", icon_color="white54")
    btn_nav_logs = ft.IconButton("history", icon_color="white54", tooltip="Logs")

    # -- SIDEBAR & LAYOUT --

    # Navigation Buttons (Vertical)
    # We use a helper to create consistent sidebar buttons
    def create_nav_btn(icon, text, action):
        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=20, color="white54"),
                ft.Text(text, size=12, color="white54", weight="w500")
            ], spacing=10),
            padding=ft.padding.symmetric(horizontal=15, vertical=12),
            border_radius=8,
            on_click=lambda e: navigate_to(action),
            data=action,
            animate=ft.Animation(200, "easeOut"),
        )
    
    # We kept refs to change styling on active
    btn_nav_home = create_nav_btn("home", "Home", "home")
    btn_nav_dashboard = create_nav_btn("dashboard", "Dashboard", "dashboard")
    btn_nav_sql = create_nav_btn("dataset", "SQL Console", "sql")
    btn_nav_settings = create_nav_btn("settings", "Settings", "settings")

    sidebar = ft.Container(
        content=ft.Column([
            # Branding
            ft.Row([
                ft.Image(src="pcp_logo.jpg", width=30, height=30, fit="contain"),  # Flet 0.80: use string
                ft.Column([
                    ft.Text("PCP NEXUS", size=18, weight="bold", color="white"),
                    ft.Text("Civil Process", size=9, color="white54")
                ], spacing=0)
            ], alignment="center", spacing=10),
            
            ft.Divider(color="white10", height=20),
            
            # Nav Menu
            ft.Text("MENU", size=10, color="white30", weight="bold"),
            btn_nav_home,
            btn_nav_dashboard,
            btn_nav_sql,
            
            ft.Divider(color="white10", height=20),
            ft.Text("SYSTEM", size=10, color="white30", weight="bold"),
            btn_nav_settings,
            
            ft.Container(expand=True), # Spacer
            
            # Footer / Session
            ft.Container(
                content=ft.Row([
                    ft.Icon("fiber_manual_record", color="#00ff00", size=10),
                    ft.Text("ONLINE", size=10, color="white54")
                ]),
                padding=10,
                border=ft.border.all(1, "white10"),
                border_radius=8
            )
        ], spacing=5),
        width=220,
        height=700, # Fill vertical
        padding=20,
        bgcolor="#25000000", # Slightly darker than glass
        border=ft.border.only(right=ft.BorderSide(1, GLASS_BORDER)),
    )
    
    # Metrics / status bar
    status_bar = ft.Container(
        content=ft.Row([
            ft.Icon("fiber_manual_record", color="#00ff00", size=10),  # Flet 0.80: positional
            ft.Text("SYSTEM ONLINE", color="white", size=11, weight="bold"),
            ft.Container(expand=True),
            ft.Text(f"SESSION: {datetime.datetime.now().strftime('%Y-%m-%d')}", color="white30", size=11),
        ], alignment="center")
    )

    # Agent Grid
    agents_grid = ft.Row([
        create_agent_card("Intake (v2)", "Mega-Ralph Engine", "OFFLINE", "all_inbox", "#ff3b30"),
        create_agent_card("Auditor", "Compliance & Rules", "OFFLINE", "manage_search", "#ffcc00"),
        create_agent_card("Clerk", "Archival & Filing", "OFFLINE", "archive", "#34c759"),
    ], alignment="center", spacing=30)
    
    # Phase Status Indicators (Home Page)
    def get_phase_status_color(enabled):
        return "#00ff00" if enabled else "#ff3b30"
    
    def get_phase_status_text(enabled):
        return "ONLINE" if enabled else "OFFLINE"
    
    p1_status_enabled = conf.get("Phase1.Enabled", True)
    p2_status_enabled = conf.get("Phase2.Enabled", True)
    
    phase_status_row = ft.Container(
        content=ft.Row([
            ft.Container(
                content=ft.Row([
                    ft.Icon("fiber_manual_record", color=get_phase_status_color(p1_status_enabled), size=12),
                    ft.Text("Phase 1: AX02, AX03, AX07, AX09", weight="bold", color="white", size=12),
                    ft.Text(get_phase_status_text(p1_status_enabled), 
                           color=get_phase_status_color(p1_status_enabled), size=11, weight="bold")
                ], spacing=8),
                padding=ft.padding.symmetric(horizontal=15, vertical=8),
                bgcolor="#20000000",
                border_radius=8,
                border=ft.border.all(1, "cyan")
            ),
            ft.Container(
                content=ft.Row([
                    ft.Icon("fiber_manual_record", color=get_phase_status_color(p2_status_enabled), size=12),
                    ft.Text("Phase 2: AX40, AX69, AX81, AXPB, AXPE, AXPL, AXPM", weight="bold", color="white", size=11),
                    ft.Text(get_phase_status_text(p2_status_enabled),
                           color=get_phase_status_color(p2_status_enabled), size=11, weight="bold")
                ], spacing=8),
                padding=ft.padding.symmetric(horizontal=15, vertical=8),
                bgcolor="#20000000",
                border_radius=8,
                border=ft.border.all(1, "orange")
            )
        ], alignment="center", spacing=20),
        padding=ft.padding.only(bottom=10)
    )

    # Console Output
    console_view = ft.ListView(
        expand=True,
        spacing=4,
        auto_scroll=True,
        padding=15
    )
    
    def log(msg, type="INFO"):
        color = "white80"
        bgcolor = "transparent"
        prefix = "[INFO]"
        
        if type == "SUCCESS": 
            color = "#34c759" 
            bgcolor = "#1534c759" 
            prefix = "[OK]"
        if type == "WARN": 
            color = "#ffcc00"
            bgcolor = "#15ffcc00"
            prefix = "[WARN]"
        if type == "ERROR": 
            color = "#ff3b30"
            bgcolor = "#15ff3b30"
            prefix = "[ERR]"
        
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        full_text = f"{prefix} [{timestamp}] {msg}"
        print(full_text) # Agent Mirror
        
        # Removed on_click/ink to allow native text selection dragging
        item = ft.Container(
            content=ft.Text(full_text, font_family="Consolas", size=12, color=color, weight="w500"),
            padding=ft.padding.symmetric(horizontal=10, vertical=2),
            border_radius=4,
            bgcolor=bgcolor,
        )

        # Limit Log Size to prevent UI freeze
        if len(console_view.controls) > 200:
            console_view.controls.pop(0)

        console_view.controls.append(item)
        try:
            console_view.update()
        except:
            pass

    log(f"Initializing PCP Nexus Kernel... (PID: {os.getpid()})", "INFO")
    log("Singleton Lock: ACTIVE (Global\\PCP_Nexus_Singleton)", "SUCCESS")
    
    # Wrap ListView in SelectionArea to enable multi-row selection
    console_container = ft.Container(
        content=ft.SelectionArea(content=console_view),
        expand=True,
        height=220,
        border_radius=4,
        bgcolor=GLASS_COLOR,
        border=ft.border.all(1, GLASS_BORDER),
        blur=ft.Blur(sigma_x=20, sigma_y=20, tile_mode=ft.BlurTileMode.MIRROR)
    )

    # -- ORCHESTRATION BRIDGE --
    
    def ui_callback(agent_name, status_msg):
        """Called by background thread agents."""
        # User Feedback: "remove the current work text"
        # We NO LONGER update the specific text message on the card.
        # Status is binary: ONLINE / OFFLINE (controlled by Main Engine toggle)
        pass
        
    def log_callback(msg, level="INFO"):
        """Called by agents/engine to print to console."""
        log(msg, level)

    # Initialize Backend
    hunter = Hunter(ui_callback=ui_callback)
    hunter.log = log_callback # Patching log function (Functional injection)
    
    auditor = Auditor(ui_callback=ui_callback)
    auditor.log = log_callback
    
    clerk = Clerk(config=conf, ui_callback=ui_callback)
    clerk.log = log_callback
    
    engine = OrchestratorEngine(hunter, auditor, clerk, log_callback)

    # Floating Action Button Logic
    is_running = False # Manual Start
    
    def toggle_execution(e):
        nonlocal is_running
        is_running = not is_running
        if is_running:
            fab_container.gradient = ft.LinearGradient(colors=["#ff3b30", PCP_RED])
            fab_text.value = "ABORT SEQUENCE"
            fab_icon.name = "stop_circle"
            
            # Set All Agents to ONLINE
            for name, ref in agent_status_refs.items():
                ref.value = "ONLINE"
                ref.color = "#00ff00" # Green for Online
                ref.update()
                
            engine.start()
        else:
            fab_container.gradient = ft.LinearGradient(colors=[PCP_RED, "#ff3b30"])
            fab_text.value = "ACTIVATE SYSTEM"
            fab_icon.name = "play_circle"
            
            # Set All Agents to OFFLINE
            for name, ref in agent_status_refs.items():
                ref.value = "OFFLINE"
                ref.color = "white" # Neutral for Offline
                ref.update()
                
            engine.stop()
            
        e.control.update()

    # Initial State: STOPPED (Manual Mode)
    fab_icon = ft.Icon("play_circle", size=24, color="white")  # Flet 0.80: positional
    fab_text = ft.Text("ACTIVATE SYSTEM", color="white", weight="bold")
    
    fab_container = ft.Container(
        content=ft.Row([fab_icon, fab_text], alignment="center", spacing=10),
        width=200, height=50,
        gradient=ft.LinearGradient(colors=[PCP_RED, "#ff3b30"]),
        border_radius=4,
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=15, color=PCP_RED, offset=ft.Offset(0,5)),
        on_click=toggle_execution,
        animate=ft.Animation(200, "easeOut")
    )

    # -- SETTINGS TAB --
    
    # 1. Configuration Loading (Unified Schema)
    # We prioritize loading the schema compatible with SetupWizard.ps1
    # Key Structure:
    # {
    #   MailboxProfile: "Default",
    #   SourceFolders: { "AX42": "Inbox\AX42", ... },
    #   CompletedFolder: "...",
    #   ExceptionFolder: "...",
    #   OutputShare: "...",
    #   RenameRules: {},
    #   EnableOCR: Bool,
    #   OCRPath: "...",
    #   LogFolder: "..."
    # }

    # --- STATE FOR CONNECTION STATUS ---
    connection_status = ft.Text("Not Connected", size=12, color="red")
    mailbox_count_text = ft.Text("", size=11, color="white54")
    
    # Holder for folder options (populated by Test Connection)
    outlook_folder_options = []

    # --- Outlook Connection Test Logic ---
    def test_outlook_connection(e):
        nonlocal outlook_folder_options
        try:
            print("DEBUG: Testing Outlook Connection...")
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            
            outlook = win32com.client.Dispatch("Outlook.Application")
            ns = outlook.GetNamespace("MAPI")
            user = ns.CurrentUser
            
            # 1. Update Profile
            t_profile.value = f"{user.Name} ({user.Address})"
            t_profile.update()
            
            # 2. Count Mailboxes (Top-Level Folders in MAPI namespace)
            mailbox_count = ns.Folders.Count
            mailbox_count_text.value = f"{mailbox_count} mailbox(es) detected"
            mailbox_count_text.update()
            
            # 3. Scan Folders for Dropdowns (from ALL mailboxes, including shared)
            outlook_folder_options = []
            
            # Iterate through ALL top-level mailboxes (stores)
            for mailbox in ns.Folders:
                mailbox_name = mailbox.Name
                if "Public Folders" in mailbox_name:
                    continue
                outlook_folder_options.append(ft.dropdown.Option(f"{mailbox_name}"))
                try:
                    for folder in mailbox.Folders:
                        folder_path = f"{mailbox_name}\\{folder.Name}"
                        outlook_folder_options.append(ft.dropdown.Option(folder_path))
                        try:
                            for sub in folder.Folders:
                                sub_path = f"{mailbox_name}\\{folder.Name}\\{sub.Name}"
                                outlook_folder_options.append(ft.dropdown.Option(sub_path))
                                try:
                                    for sub2 in sub.Folders:
                                        sub2_path = f"{mailbox_name}\\{folder.Name}\\{sub.Name}\\{sub2.Name}"
                                        outlook_folder_options.append(ft.dropdown.Option(sub2_path))
                                except:
                                    pass
                        except:
                            pass
                except:
                    pass

            # Update all Outlook Dropdowns - EACH GETS ITS OWN COPY to avoid shared state
            for dd in [t_p1_input, t_p1_completed, t_p2_input, t_p2_completed]:
                dd.options = [ft.dropdown.Option(opt.key) for opt in outlook_folder_options]
                dd.update()
            
            # 4. Update Status
            connection_status.value = "✓ Connected"
            connection_status.color = "green"
            connection_status.update()
            
            show_snack(f"✓ Connected: {user.Name}. {len(outlook_folder_options)} folders found.", success=True)
            log(f"Settings: Connected to {user.Name}, {len(outlook_folder_options)} folders.", "SUCCESS")
            
        except Exception as ex:
            print(f"ERROR: Outlook Connection Failed - {ex}")
            connection_status.value = "✗ Connection Failed"
            connection_status.color = "red"
            connection_status.update()
            show_snack("Ensure Microsoft Outlook Classic is running and you are logged in.", success=False)
            log(f"Settings: Connection Failed: {ex}", "ERROR")

    # --- A. OUTLOOK CONNECTION SECTION ---
    t_profile = ft.TextField(label="Outlook Profile / Account", value=conf.get("MailboxProfile", "Default"), bgcolor=GLASS_COLOR, expand=True, text_size=12, read_only=False)
    btn_test_conn = ft.ElevatedButton("Test Connection", icon="compare_arrows", on_click=test_outlook_connection, bgcolor="#228822", color="white")
    
    # --- PHASE 1 CONFIGURATION (CIVIL) ---
    p1_input_val = conf.get("Phase1.Input") or "Inbox"
    p1_completed_val = conf.get("Phase1.Completed") or "Inbox\\Completed"
    p1_output_val = conf.get("Phase1.Output") or "C:\\PCP\\Output\\Civil"
    p1_enabled_val = conf.get("Phase1.Enabled", True)
    
    t_p1_input = ft.Dropdown(label="Input Folder (Outlook)", value=p1_input_val, options=[ft.dropdown.Option(p1_input_val)], expand=True, filled=True, bgcolor="#1a1a1a", text_size=12)
    t_p1_completed = ft.Dropdown(label="Completed Folder (Outlook)", value=p1_completed_val, options=[ft.dropdown.Option(p1_completed_val)], expand=True, filled=True, bgcolor="#1a1a1a", text_size=12)
    t_p1_output = ft.TextField(label="Output Folder (Disk)", value=p1_output_val, expand=True, bgcolor=GLASS_COLOR, text_size=12)
    t_p1_enabled = ft.Switch(label="Phase Enabled", value=p1_enabled_val, active_color="cyan")
    t_p1_strict_sender = ft.Switch(label="Strict Sender Validation", value=conf.get("Phase1.StrictSender", True), active_color="cyan")
    t_p1_strict_subject = ft.Switch(label="Strict Subject Validation", value=conf.get("Phase1.StrictSubject", True), active_color="cyan")
    
    p1_section = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Phase 1: Civil (AX42, AX43, AX47, AX89)", size=13, color="cyan", weight="bold"),
                ft.Container(expand=True),
                t_p1_enabled
            ], alignment="spaceBetween"),
            ft.Row([t_p1_input]),
            ft.Row([t_p1_completed]),
            ft.Row([t_p1_output, ft.IconButton(icon="folder_open", tooltip="Browse Disk", on_click=lambda e: browse_for_folder(t_p1_output))]),
        ], spacing=5),
        padding=10,
        border=ft.border.all(1, "cyan"),
        border_radius=5
    )

    # --- PHASE 2 CONFIGURATION (CRIMINAL) ---
    p2_input_val = conf.get("Phase2.Input") or "Inbox"
    p2_completed_val = conf.get("Phase2.Completed") or "Inbox\\Completed"
    p2_output_val = conf.get("Phase2.Output") or "C:\\PCP\\Output\\Criminal"
    p2_enabled_val = conf.get("Phase2.Enabled", True)
    
    t_p2_input = ft.Dropdown(label="Input Folder (Outlook)", value=p2_input_val, options=[ft.dropdown.Option(p2_input_val)], expand=True, filled=True, bgcolor="#1a1a1a", text_size=12)
    t_p2_completed = ft.Dropdown(label="Completed Folder (Outlook)", value=p2_completed_val, options=[ft.dropdown.Option(p2_completed_val)], expand=True, filled=True, bgcolor="#1a1a1a", text_size=12)
    t_p2_output = ft.TextField(label="Output Folder (Disk)", value=p2_output_val, expand=True, bgcolor=GLASS_COLOR, text_size=12)
    p2_wait_val = conf.get_kvi("Phases.Phase2.AggregationMinutes") or 20
    t_p2_wait = ft.TextField(label="Aggregation Wait (Min)", value=str(p2_wait_val), width=150, bgcolor="#1a1a1a", text_size=12)
    t_p2_enabled = ft.Switch(label="Phase Enabled", value=p2_enabled_val, active_color="orange")
    t_p2_strict_sender = ft.Switch(label="Strict Sender Validation", value=conf.get("Phase2.StrictSender", True), active_color="orange")
    t_p2_strict_subject = ft.Switch(label="Strict Subject Validation", value=conf.get("Phase2.StrictSubject", True), active_color="orange")
    t_p2_skip_tag = ft.Switch(label="Skip Tag When No Files", value=conf.get("Phase2.SkipTagOnNoFiles", True), active_color="orange")
    t_p2_reopen_packets = ft.Switch(label="Reopen Completed Packets on New Files", value=conf.get("Phase2.ReopenCompletedOnNewFiles", True), active_color="orange")

    p2_section = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Phase 2: Criminal (AX40, AXPE, AXPM...)", size=13, color="orange", weight="bold"),
                ft.Container(expand=True),
                t_p2_enabled
            ], alignment="spaceBetween"),
            ft.Row([t_p2_input]),
            ft.Row([t_p2_completed]),
            ft.Row([t_p2_output, ft.IconButton(icon="folder_open", tooltip="Browse Disk", on_click=lambda e: browse_for_folder(t_p2_output))]),
            ft.Row([t_p2_wait, ft.Text("mins wait for all documents per envelope", size=10, color="white54")]),
            ft.Row([t_p2_strict_sender, t_p2_strict_subject]),
            ft.Row([t_p2_skip_tag]),
            ft.Row([t_p2_reopen_packets]),
            ft.Text("Local testing: turn OFF Strict Sender + Strict Subject to keep test emails from moving to AI Exceptions. Keep Skip-Tag ON. Reopen Packets ON if you re-test the same envelopes.", size=10, color="white54"),
        ], spacing=5),
        padding=10,
        border=ft.border.all(1, "orange"),
        border_radius=5
    )

    # --- D. OCR SETTINGS (Always Enabled) ---
    t_ocr_path = ft.TextField(label="Tesseract Path", value=conf.get("OCRPath", r"C:\Program Files\Tesseract-OCR\tesseract.exe"), bgcolor=GLASS_COLOR, expand=True, text_size=12)

    # --- E. SCHEDULING ---
    t_poll_interval = ft.TextField(label="Poll Interval (Minutes)", value=str(conf.get("PollIntervalMinutes", 1)), width=200, bgcolor=GLASS_COLOR, text_size=12)

    # --- RESTART DIALOG AND LOGIC ---
    restart_dialog = None
    restart_progress = ft.ProgressBar(width=300)
    restart_status = ft.Text("Draining pending jobs...", size=12, color="white54")
    
    def drain_and_restart():
        """Background thread to drain hoppers and restart app."""
        from core.job_manager import job_manager
        log("[RESTART] Entering graceful shutdown mode...", "WARN")
        
        # Stop engine from taking new work
        engine.stop()
        
        # Wait for hoppers to empty
        max_wait = 300  # 5 minutes max
        waited = 0
        while waited < max_wait:
            pending = len(job_manager.get_jobs_by_status('PENDING'))
            audited = len(job_manager.get_jobs_by_status('AUDITED'))
            moving = len(job_manager.get_jobs_by_status('MOVING'))
            total = pending + audited + moving
            
            if total == 0:
                break
            
            log(f"[RESTART] Waiting for {total} jobs to complete...", "INFO")
            try:
                restart_status.value = f"Draining: {total} jobs remaining..."
                restart_progress.value = max(0.1, 1 - (total / 20))  # Approximate progress
                page.update()
            except:
                pass
            time.sleep(2)
            waited += 2
        
        log("[RESTART] All hoppers drained. Restarting...", "SUCCESS")
        
        # Launch new instance FIRST
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv, 
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        
        # Give new process a moment to start
        time.sleep(0.5)
        
        # Properly close the Flet window (this prevents the frozen blue window)
        try:
            page.window_close()
        except:
            pass
        
        # Clean exit
        os._exit(0)
    
    def show_restart_dialog():
        nonlocal restart_dialog
        restart_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Restart Required"),
            content=ft.Column([
                ft.Text("Configuration saved. The application must restart."),
                ft.Divider(height=10, color="transparent"),
                ft.Text("Current status:", weight="bold"),
                restart_status,
                ft.Divider(height=10, color="transparent"),
                restart_progress,
            ], tight=True, width=350),
            actions=[]
        )
        page.dialog = restart_dialog
        restart_dialog.open = True
        page.update()
        
        # Start drain-and-restart in background
        threading.Thread(target=drain_and_restart, daemon=True).start()

    # --- SAVE LOGIC ---
    def save_settings(e):
        import getpass
        import socket
        
        log("Saving Configuration...", "INFO")
        
        # Capture audit info
        try:
            username = getpass.getuser()
            computer = socket.gethostname()
        except:
            username = "UNKNOWN"
            computer = "UNKNOWN"
        
        # Get previous values
        was_p1 = conf.get("Phase1.Enabled", True)
        was_p2 = conf.get("Phase2.Enabled", True)
        
        # Get new values
        now_p1 = t_p1_enabled.value
        now_p2 = t_p2_enabled.value
        
        # Detect toggle directions
        p1_turning_on = not was_p1 and now_p1
        p2_turning_on = not was_p2 and now_p2
        p1_turning_off = was_p1 and not now_p1
        p2_turning_off = was_p2 and not now_p2
        
        # Audit logging for toggle changes
        if p1_turning_on:
            log(f"[AUDIT] Phase 1 ENABLED by {username}@{computer}", "WARN")
        if p1_turning_off:
            log(f"[AUDIT] Phase 1 DISABLED by {username}@{computer}", "WARN")
        if p2_turning_on:
            log(f"[AUDIT] Phase 2 ENABLED by {username}@{computer}", "WARN")
        if p2_turning_off:
            log(f"[AUDIT] Phase 2 DISABLED by {username}@{computer}", "WARN")
        
        conf.set("MailboxProfile", t_profile.value)
        conf.set("outlook_account", t_profile.value.split(" (")[0]) # Sync flat account name
        
        # Phase 1
        conf.set_kvi("Phases.Phase1.InputFolder", t_p1_input.value)
        conf.set_kvi("Phases.Phase1.ProcessedFolder", t_p1_completed.value)
        conf.set_kvi("Phases.Phase1.OutputPath", t_p1_output.value)
        conf.set_kvi("Phases.Phase1.Enabled", now_p1)
        conf.set("Phase1.StrictSender", bool(t_p1_strict_sender.value))
        conf.set("Phase1.StrictSubject", bool(t_p1_strict_subject.value))
        
        # Backward Compatibility (Flat Keys)
        conf.set("Phase1.Input", t_p1_input.value)
        conf.set("Phase1.Completed", t_p1_completed.value)
        conf.set("Phase1.Output", t_p1_output.value)
        conf.set("Phase1.Enabled", now_p1)
        
        # Phase 2
        conf.set_kvi("Phases.Phase2.InputFolder", t_p2_input.value)
        conf.set_kvi("Phases.Phase2.ProcessedFolder", t_p2_completed.value)
        conf.set_kvi("Phases.Phase2.OutputPath", t_p2_output.value)
        conf.set_kvi("Phases.Phase2.Enabled", now_p2)
        conf.set("Phase2.StrictSender", bool(t_p2_strict_sender.value))
        conf.set("Phase2.StrictSubject", bool(t_p2_strict_subject.value))
        conf.set("Phase2.SkipTagOnNoFiles", bool(t_p2_skip_tag.value))
        conf.set("Phase2.ReopenCompletedOnNewFiles", bool(t_p2_reopen_packets.value))

        # Backward Compatibility (Flat Keys)
        conf.set("Phase2.Input", t_p2_input.value)
        conf.set("Phase2.Completed", t_p2_completed.value)
        conf.set("Phase2.Output", t_p2_output.value)
        conf.set("Phase2.Enabled", now_p2)
        
        # Aggregation Timer
        try:
            wait_val = int(t_p2_wait.value)
            conf.set_kvi("Phases.Phase2.AggregationMinutes", wait_val)
        except:
            pass

        # OCR (Always Enabled)
        conf.set("EnableOCR", True)
        conf.set("OCRPath", t_ocr_path.value)
        
        # Scheduling
        try:
            conf.set("PollIntervalMinutes", int(t_poll_interval.value))
        except:
            conf.set("PollIntervalMinutes", 1)

        if conf.save():
            log("Configuration Saved Successfully.", "SUCCESS")
            
            # Determine action based on toggle direction
            any_turning_on = p1_turning_on or p2_turning_on
            any_turning_off = p1_turning_off or p2_turning_off
            
            if any_turning_on:
                # RESTART REQUIRED - drain all hoppers first
                show_snack("✓ Configuration Saved. Restart required for phase activation.", success=True)
                show_restart_dialog()
            elif any_turning_off:
                # HOT TOGGLE - just notify, Hunter will stop intake next cycle
                show_snack("✓ Phase(s) will stop after current jobs complete.", success=True)
            else:
                show_snack("✓ Configuration Saved Successfully!", success=True)
        else:
            log("Configuration Save Failed.", "ERROR")
            show_snack("✗ Configuration Save Failed!", success=False)

    # --- SETTINGS VIEW LAYOUT ---
    def section_header(title):
        return ft.Container(
            content=ft.Text(title, size=14, weight="bold", color="white"),
            padding=ft.padding.only(top=10, bottom=5)
        )

    settings_view = ft.Container(
        content=ft.ListView([ 
            ft.Text("SYSTEM CONFIGURATION", size=18, weight="bold", color="white"),
            ft.Text("Edit settings directly. Restart required for major changes.", size=12, color="white54"),
            ft.Divider(color="white10"),
            
            section_header("A. Outlook Connection"),
            ft.Row([t_profile, btn_test_conn], alignment="spaceBetween"),
            ft.Row([connection_status, mailbox_count_text], alignment="spaceBetween"),
            ft.Divider(height=10, color="transparent"),
            
            p1_section,
            ft.Text("Phase 1 Validation", size=11, color="white54", italic=True),
            ft.Row([t_p1_strict_sender, t_p1_strict_subject]),
            ft.Divider(height=5, color="transparent"),
            p2_section,
            
            section_header("D. OCR Engine"),
            ft.Text("OCR is always enabled.", size=11, color="white54", italic=True),
            ft.Row([t_ocr_path, ft.IconButton(icon="folder_open", on_click=lambda e: browse_for_folder(t_ocr_path))]),
            
            section_header("E. Scheduling"),
            t_poll_interval,

            ft.Divider(height=30, color="transparent"),
            ft.ElevatedButton("Save Configuration", on_click=save_settings, color="white", bgcolor=PCP_RED, height=50)
        ], spacing=10, padding=20),
        expand=True
    )

    # -- MAIN DASHBOARD CONTENT (Without Header) --
    dashboard_content = ft.Column([
        status_bar,
        ft.Divider(color="transparent", height=10),
        phase_status_row,
        ft.Container(content=agents_grid, padding=ft.padding.symmetric(vertical=20)),
        ft.Divider(color="transparent", height=5),
        ft.Text("LIVE TRANSMISSION", size=11, weight="bold", color="white30"),
        console_container,
        ft.Divider(color="transparent", height=10),
        ft.Row([fab_container], alignment="center")
    ])

    # Placeholder for dynamic content
    content_area = ft.Container(content=dashboard_content, expand=True)

    # -- EXTENDED VIEWS: SQL CONSOLE & DASHBOARD --

    # -- EXTENDED VIEWS: SQL CONSOLE & DASHBOARD --
    
    # Original Native Dashboard removed in favor of HTML "Local URL Window"
    # per user request.
    
    # We also need a SQL Console
    t_sql_query = ft.TextField(label="SQL Query", multiline=True, height=100, bgcolor=GLASS_COLOR, text_style=ft.TextStyle(font_family="Consolas"))
    sql_results_view = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True)

    def run_sql_query(e):
        query = t_sql_query.value
        if not query: return
        
        try:
            # Connect to DB (Path relative or absolute?)
            db_path = str(app_paths.db_path())
            if not os.path.exists(db_path):
                db_path = "data/nexus.db"
                
            conn = sqlite3.connect(db_path)
            
            # Safety check (rudimentary)
            if "DROP" in query.upper() or "DELETE" in query.upper():
                log("SQL Safety violation. Use Admin tools for destructive ops.", "WARN")
                return

            df = pd.read_sql_query(query, conn)
            
            # Build DataTable
            cols = [ft.DataColumn(ft.Text(str(c))) for c in df.columns]
            rows = []
            for index, row in df.iterrows():
                cells = [ft.DataCell(ft.Text(str(val)[:50])) for val in row.values]
                rows.append(ft.DataRow(cells=cells))
            
            dt = ft.DataTable(columns=cols, rows=rows, heading_row_color="#2d2d2d")
            sql_results_view.controls = [dt]
            sql_results_view.update()
            log(f"Query executed. {len(df)} rows returned.", "SUCCESS")
            
        except Exception as ex:
            log(f"SQL Error: {ex}", "ERROR")
            sql_results_view.controls = [ft.Text(f"Error: {ex}", color="red")]
            sql_results_view.update()
            
    # Schema Viewer
    def show_schema_dialog(e):
        try:
            db_path = str(app_paths.db_path())
            if not os.path.exists(db_path):
                db_path = "data/nexus.db"
             
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get Tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            md_content = "# Database Schema Guide\n\n"
            
            for t in tables:
                table_name = t[0]
                md_content += f"## Table: `{table_name}`\n"
                
                # Get Info
                cursor.execute(f"PRAGMA table_info({table_name})")
                cols = cursor.fetchall()
                # cid, name, type, notnull, dflt_value, pk
                
                md_content += "| CID | Name | Type | PK |\n|---|---|---|---|\n"
                for c in cols:
                    pk_mark = "🔑" if c[5] else ""
                    md_content += f"| {c[0]} | **{c[1]}** | {c[2]} | {pk_mark} |\n"
                md_content += "\n"
                
            conn.close()
            
            # 1. Install/Save Locally
            guide_path = os.path.abspath("sql_schema_guide.md")
            with open(guide_path, "w", encoding="utf-8") as f:
                f.write(md_content)
                
            # 2. Show Dialog
            dlg_modal = ft.AlertDialog(
                modal=True,
                title=ft.Text("Database Schema"),
                content=ft.Container(
                    content=ft.Markdown(md_content, extension_set="github_web"),
                    width=600, height=400,
                    scroll=ft.ScrollMode.AUTO
                ),
                actions=[
                    ft.TextButton("Close", on_click=lambda e: page.close(dlg_modal)),
                    ft.TextButton(f"Saved to: {guide_path}", disabled=True)
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.open(dlg_modal)
            log(f"Schema Guide generated at: {guide_path}", "SUCCESS")

        except Exception as ex:
            log(f"Schema Error: {ex}", "ERROR")

    sql_view_instance = ft.Container(
        content=ft.Column([
            ft.Text("SQL DIAGNOSTICS CONSOLE", size=18, weight="bold", color="white"),
            t_sql_query,
            ft.Row([
                ft.ElevatedButton("Execute Query", on_click=run_sql_query, bgcolor="blue", color="white"),
                ft.OutlinedButton("View Schema Guide", on_click=show_schema_dialog, icon="schema", icon_color="white70", style=ft.ButtonStyle(color="white"))
            ]),
            ft.Divider(color="white10"),
            ft.Container(content=sql_results_view, expand=True, bgcolor="#10000000", border_radius=5)
        ]),
        padding=20,
        expand=True
    )

    # View Switching Logic
    def navigate_to(page_name):
        # Update styling of buttons
        for btn in [btn_nav_home, btn_nav_dashboard, btn_nav_sql, btn_nav_settings]:
             if btn.page: # Lifecycle Safety
                 is_active = btn.data == page_name
                 btn.bgcolor = "#30ffffff" if is_active else "transparent"
                 btn.content.controls[1].color = "white" if is_active else "white54"
                 btn.content.controls[0].color = "white" if is_active else "white54"
                 btn.update()

        content_area.content = None
        if page_name == "home":
             content_area.content = dashboard_content
        elif page_name == "dashboard":
             # content_area.content = dashboard_view_instance
             # LAUNCH LOCAL URL WINDOW (Browser)
             
             # Show placeholder
             content_area.content = ft.Container(
                content=ft.Column([
                    ft.Icon("open_in_new", size=48, color="white54"),
                    ft.Text("Dashboard Running in Browser", size=20, color="white"),
                    ft.Text("The dashboard has been launched in your default web browser.", size=12, color="white54"),
                    ft.ElevatedButton("Relaunch Dashboard", on_click=lambda e: navigate_to("dashboard"))
                ], alignment="center", horizontal_alignment="center", spacing=10),
                alignment=ft.alignment.center, expand=True
             )
             
             try:
                 report_path = generate_dashboard(output_mode='file')
                 if report_path:
                     # Calculate file URL
                     file_url = f"file:///{report_path.replace(os.sep, '/')}"
                     page.launch_url(file_url)
                     show_snack("✓ Dashboard opened in browser", success=True)
                 else:
                     show_snack("No data available for dashboard", success=False)
             except Exception as e:
                 show_snack(f"Error launching dashboard: {e}", success=False)
                 
        elif page_name == "sql":
             content_area.content = sql_view_instance
        elif page_name == "settings":
             content_area.content = settings_view
        
        content_area.update()

    # Layout Assembly
    layout = ft.Row([
        sidebar,
        content_area
    ], expand=True, spacing=0)

    # Initial Route
    # MOVED: Must be called AFTER page.add to ensure controls are mounted
    # navigate_to("home")
    
    # Background Image Stack
    page.add(
        ft.Stack([
            ft.Image(src="background.jpg", width=1100, height=700, fit="cover", opacity=0.4), # Flet 0.80: use string
            ft.Container(
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),  # top_left in Flet 0.80
                    end=ft.Alignment(1, 1),  # bottom_right in Flet 0.80
                    colors=[PCP_RED_DARK, "#000000", "#1a1a1a"]
                ),
                opacity=0.9
            ),
            layout
        ], expand=True)
    )

    log("UI Rendering Complete. Standing By...", "SUCCESS")
    navigate_to("home") # Start Navigation now that Page is ready
