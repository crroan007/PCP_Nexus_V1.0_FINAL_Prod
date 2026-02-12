"""
PCP Nexus - Startup Diagnostics Module
=======================================
Logs all critical environment info at startup per PyInstaller debugging guide.
This module MUST be imported at the very start of main.py.
"""
import sys
import os
import platform
import locale
import logging
import traceback
from datetime import datetime
from pathlib import Path

from core import app_paths

# Determine if running frozen (PyInstaller)
IS_FROZEN = getattr(sys, 'frozen', False)
MEIPASS = getattr(sys, '_MEIPASS', None) if IS_FROZEN else None

# Debug mode from environment
DEBUG_MODE = os.environ.get('APP_DEBUG', '0') == '1'

# Log directory - MUST be in user-writable space (never inside Program Files)
LOG_DIR = app_paths.logs_dir()

# Create timestamped log file
LOG_FILE = LOG_DIR / f"startup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure logging
log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout) if not IS_FROZEN else logging.NullHandler()
    ]
)

logger = logging.getLogger('pcp_nexus.startup')

def log_startup_diagnostics():
    """Log all critical environment info at startup."""
    logger.info("=" * 60)
    logger.info("PCP NEXUS - STARTUP DIAGNOSTICS")
    logger.info("=" * 60)
    
    # Python info
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Executable: {sys.executable}")
    logger.info(f"argv: {sys.argv}")
    logger.info(f"sys.path: {sys.path[:5]}...")  # First 5 entries
    logger.info(f"CWD: {os.getcwd()}")
    
    # Frozen state
    logger.info(f"IS_FROZEN: {IS_FROZEN}")
    logger.info(f"_MEIPASS: {MEIPASS}")
    logger.info(f"DEBUG_MODE: {DEBUG_MODE}")
    
    # OS info
    logger.info(f"OS: {platform.system()} {platform.release()}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Architecture: {platform.architecture()}")
    logger.info(f"Machine: {platform.machine()}")
    logger.info(f"Processor: {platform.processor()}")
    
    # Locale and encoding
    logger.info(f"Locale: {locale.getlocale()}")
    logger.info(f"Preferred Encoding: {locale.getpreferredencoding()}")
    logger.info(f"Default Encoding: {sys.getdefaultencoding()}")
    logger.info(f"Filesystem Encoding: {sys.getfilesystemencoding()}")
    
    # User info
    logger.info(f"Username: {os.environ.get('USERNAME', 'UNKNOWN')}")
    logger.info(f"Computer: {os.environ.get('COMPUTERNAME', 'UNKNOWN')}")
    logger.info(f"USERPROFILE: {os.environ.get('USERPROFILE', 'UNKNOWN')}")
    logger.info(f"LOCALAPPDATA: {os.environ.get('LOCALAPPDATA', 'UNKNOWN')}")
    
    # Tkinter info (if available)
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        logger.info(f"Tk Version: {tk.TkVersion}")
        logger.info(f"Tcl Version: {tk.TclVersion}")
        try:
            scaling = root.tk.call('tk', 'scaling')
            logger.info(f"Tk Scaling: {scaling}")
        except:
            pass
        root.destroy()
    except Exception as e:
        logger.warning(f"Tkinter check failed: {e}")
    
    # Config paths
    config_path = app_paths.config_path()
    logger.info(f"Config Path: {config_path}")
    logger.info(f"Config Exists: {config_path.exists()}")
    
    if config_path.exists():
        try:
            import stat
            st = config_path.stat()
            logger.info(f"Config Size: {st.st_size} bytes")
            logger.info(f"Config Mode: {oct(st.st_mode)}")
        except Exception as e:
            logger.warning(f"Config stat failed: {e}")
    
    # Database path
    db_path = app_paths.db_path()
    logger.info(f"Database Path: {db_path}")
    logger.info(f"Database Exists: {db_path.exists()}")
    
    logger.info("=" * 60)
    logger.info(f"Log File: {LOG_FILE}")
    logger.info("=" * 60)

def install_exception_hook():
    """Install global exception hook to log uncaught exceptions."""
    def exception_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        
        logger.critical("UNCAUGHT EXCEPTION:")
        logger.critical("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    
    sys.excepthook = exception_hook
    logger.info("Global exception hook installed")

def resolve_resource_path(relative_path: str) -> Path:
    """
    Resolve a resource path correctly for both source and frozen modes.
    
    Args:
        relative_path: Path relative to project root (source) or MEIPASS (frozen)
    
    Returns:
        Absolute Path to the resource
    """
    if IS_FROZEN:
        base = Path(MEIPASS)
    else:
        # Source mode - relative to this file's parent
        base = Path(__file__).parent.parent
    
    resolved = base / relative_path
    logger.debug(f"resolve_resource_path('{relative_path}') -> {resolved} (exists={resolved.exists()})")
    return resolved

def resolve_data_path(relative_path: str) -> Path:
    """
    Resolve a user-data path (config, database, logs).
    These must ALWAYS be outside the install directory.
    
    Args:
        relative_path: Path relative to ProgramData/PCP-Automation
    
    Returns:
        Absolute Path to the data file
    """
    resolved = app_paths.base_dir() / relative_path
    
    # Ensure parent exists
    resolved.parent.mkdir(parents=True, exist_ok=True)
    
    logger.debug(f"resolve_data_path('{relative_path}') -> {resolved} (exists={resolved.exists()})")
    return resolved

# Auto-run diagnostics when imported
install_exception_hook()
log_startup_diagnostics()
