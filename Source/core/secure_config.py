import json
import os
import keyring

from core import app_paths

class SecureConfig:
    """
    SOW 4.2: Credential Security.
    Wraps 'keyring' (Windows Credential Manager) to avoid plaintext secrets.
    """
    SERVICE_NAME = "PCP_Nexus_Automation"
    
    def __init__(self):
        # SEARCH PATH STRATEGY: 
        # 1. ProgramData config (legacy installs)
        # 2. LocalAppData config (preferred for non-admin installs)
        # 2. CWD (Current Working Directory)
        # 3. Main Module Directory (sys.path[0])
        
        program_data_cfg = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "PCP-Automation", "config.json")
        local_app_data_cfg = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PCP-Automation", "config.json")

        candidates = [
            program_data_cfg,
            local_app_data_cfg,
            str(app_paths.config_path()),
            os.path.join(os.getcwd(), "config.json"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.json"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "config.json"),
            os.path.join(os.getcwd(), "..", "..", "config.json")
        ]
        
        self.config_path = str(app_paths.config_path())  # Default to writable base dir if nothing exists
        
        # Try to find existing
        for p in candidates:
            if os.path.exists(p):
                self.config_path = os.path.abspath(p)
                print(f"DEBUG: Found existing config at: {self.config_path}")
                break
                
        self._load_config()

    def _load_config(self):
        print(f"DEBUG: Config Path resolved to: {self.config_path}")
        if not hasattr(self, 'config'):
            self.config = {}

        if not os.path.exists(self.config_path):
            print("DEBUG: Config File NOT FOUND! Using Memory Defaults.")
            return
            
        try:
            with open(self.config_path, 'r') as f:
                new_data = json.load(f)
                self.config.clear()
                self.config.update(new_data)
            print(f"DEBUG: Config Loaded. Keys: {list(self.config.keys())}")
        except Exception as e:
            print(f"Config Load Error: {e}")

    def get(self, key, default=None):
        """Gets non-sensitive config."""
        if key in self.config:
            return self.config.get(key, default)
        if "." in key:
            return self.get_kvi(key, default)
        return default

    def set(self, key, value):
        """Sets a config value (Non-sensitive)."""
        self.config[key] = value

    def set_kvi(self, keypath, value):
        """
        Sets values in nested dictionaries using dot notation: 
        set_kvi('Phases.Phase1.InputFolder', 'NewInbox')
        """
        keys = keypath.split('.')
        d = self.config
        for i, k in enumerate(keys[:-1]):
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    def save(self):
        """Persists current config to disk."""
        try:
            # Ensure directory exists (Critical for ProgramData first run)
            folder = os.path.dirname(self.config_path)
            if not os.path.exists(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                    print(f"Created config directory: {folder}")
                except Exception as dir_err:
                    print(f"Failed to create config directory {folder}: {dir_err}")
                    # Fallback to LocalAppData if ProgramData fails (Program Files/CWD is often non-writable)
                    self.config_path = os.path.abspath(str(app_paths.config_path()))
                    folder = os.path.dirname(self.config_path)
                    os.makedirs(folder, exist_ok=True)
                    print(f"Fallback: Switching config path to {self.config_path}")

            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            print(f"Config saved to {self.config_path}")
            return True
        except Exception as e:
            print(f"Config Save Error: {e}")
            # One more attempt: if we were targeting ProgramData, fall back to LocalAppData.
            try:
                if "ProgramData" in self.config_path:
                    self.config_path = os.path.abspath(str(app_paths.config_path()))
                    folder = os.path.dirname(self.config_path)
                    os.makedirs(folder, exist_ok=True)
                    with open(self.config_path, "w") as f:
                        json.dump(self.config, f, indent=4)
                    print(f"Config saved to {self.config_path} (fallback)")
                    return True
            except Exception:
                pass
            return False

    def get_kvi(self, keypath, default=None):
        """
        Traverses nested keys: get_kvi('paths.output')
        """
        keys = keypath.split('.')
        val = self.config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default

    def get_secret(self, account_name):
        """
        Retrieves secret from Windows Credential Manager.
        """
        try:
            return keyring.get_password(self.SERVICE_NAME, account_name)
        except Exception as e:
            print(f"Keyring Error ({account_name}): {e}")
            return None

    def set_secret(self, account_name, password):
        """
        Stores secret in Windows Credential Manager.
        Run this via a setup script, NEVER manually in code.
        """
        try:
            keyring.set_password(self.SERVICE_NAME, account_name, password)
            print(f"Secret set for {account_name}")
        except Exception as e:
            print(f"Keyring Set Error: {e}")

# Global Instance
conf = SecureConfig()
