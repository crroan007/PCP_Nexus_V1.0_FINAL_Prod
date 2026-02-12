import os
import json
import sys

# Replicate SecureConfig candidate logic
APP_DIRNAME = "PCP-Automation"
program_data_cfg = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), APP_DIRNAME, "config.json")
local_app_data_cfg = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_DIRNAME, "config.json")

candidates = [
    program_data_cfg,
    local_app_data_cfg,
    "config.json", # CWD
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
]

with open("debug_scan_results.txt", "w", encoding="utf-8") as out:
    out.write(f"LOCALAPPDATA: {os.environ.get('LOCALAPPDATA')}\n")
    out.write("Scanning for config files...\n")
    for p in candidates:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            out.write(f"\n[FOUND] {abs_p}\n")
            try:
                with open(abs_p, 'r') as f:
                    data = json.load(f)
                    p1_out = data.get("Phase1.Output", "NOT SET")
                    out.write(f"  Phase1.Output: {p1_out}\n")
                    
                    nested = data.get("Phases", {}).get("Phase1", {}).get("OutputPath", "NOT SET")
                    out.write(f"  Phases.Phase1.OutputPath: {nested}\n")
            except Exception as e:
                out.write(f"  Error reading: {e}\n")
        else:
            out.write(f"[MISSING] {abs_p}\n")
    
    out.write("\nTesting SecureConfig Class Resolution:\n")
    try:
        sys.path.append(os.getcwd())
        from core.secure_config import SecureConfig
        sc = SecureConfig()
        out.write(f"SecureConfig.config_path: {sc.config_path}\n")
        out.write(f"Phase1.Output via SecureConfig: {sc.get('Phase1.Output')}\n")
        out.write(f"PCP_DATA_DIR Env Var: {os.environ.get('PCP_DATA_DIR', 'Not Set')}\n")
    except Exception as e:
        out.write(f"SecureConfig Error: {e}\n")
