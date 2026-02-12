# PCP Nexus Build Script
# Builds a Windows executable with proper Tcl/Tk bundling (PyInstaller onedir)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PCP NEXUS BUILD SCRIPT" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Step 1: Check Python
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Yellow
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "  ERROR Python not found! Install Python 3.9+ first." -ForegroundColor Red
    exit 1
}
$pythonVersion = python --version 2>&1
Write-Host "  OK Found: $pythonVersion" -ForegroundColor Green

# Step 2: Clean previous builds
Write-Host ""
Write-Host "[2/6] Cleaning previous builds..." -ForegroundColor Yellow
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
Write-Host "  OK Cleaned build and dist folders" -ForegroundColor Green

# Step 3: Check/Create virtual environment
Write-Host ""
Write-Host "[3/6] Setting up virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "  OK Virtual environment exists" -ForegroundColor Green
} else {
    Write-Host "  Creating new virtual environment..." -ForegroundColor Gray
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK Virtual environment created" -ForegroundColor Green
}

Write-Host "  Activating virtual environment..." -ForegroundColor Gray
& ".\\venv\\Scripts\\Activate.ps1"

# Step 4: Install dependencies
Write-Host ""
Write-Host "[4/6] Installing dependencies..." -ForegroundColor Yellow
Write-Host "  This may take several minutes (OCR stack is large)..." -ForegroundColor Gray
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR Dependency installation failed!" -ForegroundColor Red
    exit 1
}
Write-Host "  OK Dependencies installed" -ForegroundColor Green

# Step 5: Build with PyInstaller
Write-Host ""
Write-Host "[5/6] Building executable with PyInstaller..." -ForegroundColor Yellow
Write-Host "  Using spec file: pcp_nexus_fixed.spec" -ForegroundColor Gray
pyinstaller pcp_nexus_fixed.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR Build failed! Check errors above." -ForegroundColor Red
    exit 1
}

# Step 6: Verify output
Write-Host ""
Write-Host "[6/6] Verifying build output..." -ForegroundColor Yellow
$exePath = "dist\\PCP_Nexus\\PCP_Nexus.exe"
if (Test-Path $exePath) {
    $size = (Get-Item $exePath).Length / 1MB
    Write-Host "  OK Build successful!" -ForegroundColor Green
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "BUILD COMPLETE" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Output location: dist\\PCP_Nexus\\" -ForegroundColor White
    Write-Host "Executable: $exePath" -ForegroundColor White
    Write-Host "Size: $([math]::Round($size, 2)) MB" -ForegroundColor White
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Test locally: cd dist\\PCP_Nexus && .\\PCP_Nexus.exe" -ForegroundColor Gray
    Write-Host "  2. Create installer with Inno Setup (if installed)" -ForegroundColor Gray
    Write-Host "  3. Test on clean Windows VM" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host "  ERROR Executable not found at $exePath" -ForegroundColor Red
    Write-Host "  Check build output above for errors." -ForegroundColor Red
    exit 1
}

# Display directory size
$distSize = (Get-ChildItem -Path "dist\\PCP_Nexus" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Total package size: $([math]::Round($distSize, 2)) MB" -ForegroundColor Gray
Write-Host ""

