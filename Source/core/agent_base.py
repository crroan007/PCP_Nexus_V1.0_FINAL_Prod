import logging
import time
import os
from core.job_manager import job_manager
from core import app_paths
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    """
    Abstract Base Class for all PCP Nexus Agents (Hunter, Auditor, Clerk).
    Provides standardized logging, status updates, and error handling.
    """
    
    def __init__(self, name, config=None, ui_callback=None):
        self.name = name
        self.config = config or {}
        self.ui_callback = ui_callback # Function to call for UI updates: callback(agent_name, status_msg, is_error)
        
        # Setup Logger
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.INFO)
        
        # Ensure log directory exists - Use ProgramData to avoid UAC issues in Program Files
        if os.name == 'nt':
            log_dir = str(app_paths.logs_dir())
        else:
            log_dir = os.path.join(os.getcwd(), "Logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # File Handler
        try:
            log_path = os.path.join(log_dir, f"{name}.log")
            if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == os.path.abspath(log_path) for h in self.logger.handlers):
                handler = logging.FileHandler(log_path, encoding="utf-8")
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)
        except Exception as e:
            print(f"[CRITICAL] Could not set up file logging: {e}")

    def log(self, message, level="INFO"):
        """Logs to disk and updates the UI console."""
        if level == "INFO":
            self.logger.info(message)
        elif level == "WARN":
            self.logger.warning(message)
        elif level == "ERROR":
            self.logger.error(message)
        elif level == "SUCCESS":
            self.logger.info(f"[SUCCESS] {message}")
            
        print(f"[{self.name}] {message}") # Console fallback

    def log_workflow(self, job_id, message):
        """Appends a granular step to the Job's persistent Audit Trail."""
        try:
            job_manager.append_workflow_log(job_id, message)
        except Exception as e:
            self.logger.error(f"Failed to append workflow log: {e}")

    def update_status(self, status):
        """Updates the visual status on the Agent Card in the UI."""
        if self.ui_callback:
            try:
                # Dispatch update to UI thread/callback
                self.ui_callback(self.name, status)
            except Exception as e:
                self.logger.error(f"Failed to update UI status: {e}")

    @abstractmethod
    def run_cycle(self):
        """
        The main logic loop for the agent. 
        Must be implemented by subclasses.
        """
        pass
