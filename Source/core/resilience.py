import os
import sys
from datetime import datetime
from core import app_paths

def safe_trace(msg, error_level="INFO"):
    """
    Robust centralized file Logger.
    Writes to C:\\ProgramData\\PCP-Automation\\Logs\\agent_trace.log
    Ensures directory exists.
    """
    try:
        log_dir = str(app_paths.logs_dir())
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_file = os.path.join(log_dir, "agent_trace.log")
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{error_level}] {msg}\n")
            
    except Exception as e:
        # Last resort: print to stderr if file logging fails
        sys.stderr.write(f"LOGGING FAILURE: {e}\n")

def connect_outlook_robustly():
    """
    Attempts to connect to Outlook using multiple strategies.
    1. GetActiveObject (Attach to running instance) -> Best for threading
    2. Dispatch (Create new instance)
    3. EnsureDispatch (Cache-based)
    
    Returns: (outlook_object, strategy_used) or (None, error_msg)
    """
    import pythoncom
    import win32com.client
    
    # Ensure COM is initialized for this thread
    try:
        pythoncom.CoInitialize()
    except:
        pass # Might already be initialized
    
    last_error = "None"

    # Strategy 1: Attach to Existing (Ideal for GUI threads)
    try:
        outlook = win32com.client.GetActiveObject("Outlook.Application")
        return outlook, "GetActiveObject"
    except Exception as e1:
        last_error = str(e1)
        safe_trace(f"GetActiveObject failed: {e1}", "WARN")

    # Strategy 2: Standard Dispatch
    try:
        safe_trace("Attempting Strategy 2: Dispatch...", "INFO")
        outlook = win32com.client.Dispatch("Outlook.Application")
        safe_trace("Strategy 2: Dispatch SUCCESS", "INFO")
        return outlook, "Dispatch"
    except Exception as e2:
         last_error = str(e2)
         safe_trace(f"Dispatch failed: {e2}", "WARN")

    # Strategy 3: EnsureDispatch (GenCache)
    try:
        safe_trace("Attempting Strategy 3: EnsureDispatch...", "INFO")
        outlook = win32com.client.gencache.EnsureDispatch("Outlook.Application")
        safe_trace("Strategy 3: EnsureDispatch SUCCESS", "INFO")
        return outlook, "EnsureDispatch"
    except Exception as e3:
         last_error = str(e3)
         safe_trace(f"EnsureDispatch failed: {e3}", "WARN")
         
    return None, f"All Strategies Failed. Last Error: {last_error}"
