# PCP Nexus Build and Distribution Guide

## 1. Distribution Strategy
The goal is to create a robust, standalone application that runs on Windows 10+ without requiring local Python installation.

### Key Decisions:
- **Mode**: Use `--onedir` instead of `--onefile`.
  - *Rationale*: Faster startup (~3-5x), fewer antivirus false positives, and better handling of large dependencies like EasyOCR models (~100MB).
- **Installer**: Use **Inno Setup** to create a single setup executable.

## 2. PyInstaller Configuration
A custom `.spec` file is used to handle complex dependencies.

### Critical Fix: Tcl/Tk Bundling
CustomTkinter requires Tcl/Tk runtime files. If missing, the app crashes with `FileNotFoundError: Tcl data directory not found`.

**Robust Discovery Method (Final Fix):**
```python
import sys
from pathlib import Path

# Paths depend on Python distribution (Standard vs MS Store)
python_root = Path(sys.executable).parent
tcl_dir = python_root / "tcl"
tk_dir = python_root / "tk"
```

**Conditional Bundling in .spec File:**
To prevent `ERROR: Unable to find ...` failures when a folder is missing:
```python
datas=[
    (str(tcl_dir), 'tcl') if tcl_dir.exists() else None,
    (str(tk_dir), 'tk') if tk_dir.exists() else None,
    # ... other assets
]
# Filter out None values
datas = [d for d in datas if d is not None]
```

> **Note**: Standard Python installs often bundle Tcl/Tk in a `tcl` folder at the root. If `tk` is missing, the application may still function if the Tcl runtime includes the necessary components or if `customtkinter` doesn't strictly require the legacy `tk` assets for the specific theme used.

### Dependency Collection:
- Use `collect_all('customtkinter')` for all UI assets.
- Use `collect_data_files('easyocr')` for OCR models.
- Include hidden imports for `win32com`, `win32com.client`, `pythoncom`.

## 3. Automated Build Process
Use `build.ps1` to ensure a clean, repeatable build environment.

```powershell
# 1. Ensure venv is active and fully populated
python -m pip install -r requirements.txt
python -m pip install pyinstaller

# 2. Clean previous builds
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# 3. Build with spec file (use --noconfirm to avoid user prompts)
python -m PyInstaller --noconfirm pcp_nexus_fixed.spec

# 4. Verify Build
if (Test-Path "dist\PCP_Nexus\PCP_Nexus.exe") {
    Write-Host "Build Successful!" -ForegroundColor Green
}
```

## 4. Dependency Management
- **pywin32**: Essential for Outlook COM automation. Providing `pythoncom`, `win32api`, `win32con`, etc.
- **pythoncom**: Should **not** be listed separately in `requirements.txt`. It is provided by `pywin32`.
- **Complete Environment**: PyInstaller bundles what it finds in the environment. If the build environment is missing dependencies (like `pywin32`), the frozen app will fail with `ModuleNotFoundError` at runtime. Always run `pip install -r requirements.txt` in the build venv.
- **PyInstaller**: Must be installed in the specific virtual environment being used for the build.
- **Execution Policy**: On systems where PowerShell script execution is restricted, activate the venv and then call `python -m PyInstaller` directly instead of using a `.ps1` wrapper if necessary.
- **EasyOCR**: Model files are bundled via `collect_data_files`. Ensure `torch` and `torchvision` are installed.

## 5. Diagnostics Infrastructure
To debug issues on remote machines, a `startup_diagnostics.py` module is included.
- **Log Location**: `%LOCALAPPDATA%\PCP-Automation\debug_logs\`
- **Captured Data**: Bundle contents, environment variables, Python version, and global exceptions.

## 6. Installer Creation (Inno Setup)
The installer handles:
- Copying `dist\PCP_Nexus` content to `{app}`.
- Creating Desktop and Start Menu shortcuts.
- Managing the Uninstaller.
- Registry entries if needed.

## 7. Common Post-Build Issues
If the app launches but behaves unexpectedly:
- **UI Freezes**: Likely due to COM operations running on the main UI thread.
- **Missing Images**: Verify assets are being called via `get_resource_path()`.
- **Silent Failures**: Check `%LOCALAPPDATA%\PCP-Automation\debug_logs` for startup errors.
- **ModuleNotFoundError: 'pythoncom'**: 
  - *Cause*: `pywin32` was missing from the build environment (venv). 
  - *Fix*: Install all dependencies (`pip install -r requirements.txt`) in the active build environment. PyInstaller uses the current environment's site-packages to bundle DLLs and runtime hooks like `pyi_rth_pythoncom.py`.
- **ERROR: The output directory "dist\PCP_Nexus" is not empty**:
  - *Cause*: PyInstaller refuses to overwrite a non-empty directory in some configurations.
  - *Fix*: Use `Remove-Item -Recurse -Force build, dist` before running PyInstaller, or add `--noconfirm` to the command line.

See [Core Technical & Implementation Guide](core_agent_implementation.md) for detailed runtime fixes.
