# CRITICAL: Import startup diagnostics FIRST before anything else
# This logs all environment info and installs exception hooks
try:
    from core.startup_diagnostics import IS_FROZEN, DEBUG_MODE, LOG_FILE
    print(f"Diagnostics logged to: {LOG_FILE}")
except Exception as e:
    print(f"Warning: Startup diagnostics failed: {e}")
    IS_FROZEN = False
    DEBUG_MODE = False

import os
import sys
import datetime

# ============================================================================
# ADMIN ELEVATION CHECK - App requires admin privileges
# ============================================================================
def _is_admin():
    """Check if running with admin privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def _request_admin_elevation():
    """Re-launch this script with admin privileges via UAC."""
    import ctypes
    
    if IS_FROZEN:
        # Running as bundled exe
        executable = sys.executable
        params = ' '.join(sys.argv[1:])
    else:
        # Running as python script
        executable = sys.executable  # python.exe
        # v4.3.5: Always pass -B to prevent stale .pyc bytecache in elevated subprocess
        params = '-B ' + ' '.join([f'"{arg}"' for arg in sys.argv])
    
    print("[INIT] Admin privileges required. Requesting elevation...")
    
    # ShellExecuteW with 'runas' verb triggers UAC prompt
    result = ctypes.windll.shell32.ShellExecuteW(
        None,           # hwnd
        "runas",        # lpOperation (run as admin)
        executable,     # lpFile
        params,         # lpParameters
        None,           # lpDirectory
        1               # nShowCmd (SW_SHOWNORMAL)
    )
    
    # ShellExecuteW returns > 32 on success
    if result > 32:
        print("[INIT] Elevated process launched. Exiting non-admin instance.")
        sys.exit(0)
    else:
        print(f"[INIT] Elevation failed (error {result}). Continuing without admin...")

# Check admin status before anything else
if os.name == 'nt' and not _is_admin():
    _request_admin_elevation()
    # If we get here, elevation failed - continue anyway (some features may not work)

from ui.tk_app import run

def main():
    """
    Main Entry Point for PCP Automation (Nexus)
    """
    # Ensure environment is ready
    print("Initializing PCP Nexus...")
    
    # LOG REDIRECTION: Respect config-defined log paths
    try:
        from core.secure_config import conf
        log_overrides = [
            conf.get("paths.logs"),
            conf.get("LogFolder"),
            conf.get_kvi("LogFolder")
        ]
        for log_path in log_overrides:
            if log_path and os.path.isdir(os.path.dirname(log_path)):
                os.environ["PCP_LOGS_DIR"] = log_path
                print(f"Log Redirection: {log_path}")
                break
    except Exception as e:
        print(f"Log Redirection Warning: {e}")
    
    # SECURITY: Activate Tamper Guard
    try:
        from core.tamper_guard import activate_protection
        activate_protection()
        print("Security Services Active.")
    except Exception as e:
        print(f"Security Load Warning: {e}")

    # Single Instance Lock (SOW Hardening)
    # Kill any previous instances before launching fresh
    try:
        import ctypes
        from ctypes import wintypes
        import subprocess
        
        # ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        
        # Try to create mutex first
        mutex = kernel32.CreateMutexW(None, False, "Global\\PCP_Nexus_Singleton")
        
        if kernel32.GetLastError() == 183:
            print("\n[INIT] Previous PCP Nexus instance detected. Force-killing...")
            
            # Kill all matching python processes running main.py or PCP_Nexus.exe
            try:
                import psutil
                current_pid = os.getpid()
                killed_count = 0
                
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        if proc.pid == current_pid:
                            continue
                        
                        pname = proc.info['name'].lower() if proc.info['name'] else ''
                        cmdline = ' '.join(proc.info['cmdline']).lower() if proc.info['cmdline'] else ''
                        
                        # Match python running our main.py OR the bundled exe
                        if ('pcp_nexus' in pname) or \
                           ('python' in pname and 'main.py' in cmdline and 'orchestrator' in cmdline):
                            print(f"  → Killing PID {proc.pid}: {pname}")
                            proc.kill()
                            killed_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                if killed_count > 0:
                    print(f"[INIT] Killed {killed_count} previous instance(s). Waiting for cleanup...")
                    import time
                    time.sleep(0.5)  # Brief pause for processes to fully terminate
                    
                    # Release the old mutex and reacquire
                    kernel32.CloseHandle(mutex)
                    mutex = kernel32.CreateMutexW(None, False, "Global\\PCP_Nexus_Singleton")
                else:
                    print("[INIT] No killable processes found. Mutex may be stale, continuing...")
                    
            except ImportError:
                print("[INIT] psutil not available. Using fallback taskkill...")
                # Fallback: use taskkill for bundled exe
                subprocess.run(['taskkill', '/F', '/IM', 'PCP_Nexus.exe'], 
                             capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                import time
                time.sleep(0.5)
                kernel32.CloseHandle(mutex)
                mutex = kernel32.CreateMutexW(None, False, "Global\\PCP_Nexus_Singleton")
            
            print("[INIT] Previous instances cleared. Launching fresh.\n")
            
    except Exception as e:
        print(f"Warning: Single Instance Lock failed: {e}")

    try:
        run()
    except KeyboardInterrupt:
        print("User Aborted (Ctrl+C)")
    finally:
        print("Shutting down... Generating Session Report.")
        try:
            from core.dashboard_generator import generate_log_snapshot
            from core.emailer import mailer
            
            # 1. Generate Log Snapshot (No Stats)
            html = generate_log_snapshot(limit=100)
            
            subject = f"PCP Nexus Session Log - {datetime.datetime.now().strftime('%H:%M')}"
            
            # 2. Send
            if html:
                mailer.send_session_report(html, subject)
                print("Session Log sent.")
                
        except Exception as e:
            print(f"Failed to send shutdown report: {e}")


if __name__ == "__main__":
    main()
