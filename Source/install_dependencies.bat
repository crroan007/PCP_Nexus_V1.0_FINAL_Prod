@echo off
echo Installing PCP-Nexus Dependencies...
echo.

cd /d C:\PCP-Nexus

echo Installing pywin32...
pip install pywin32

echo Installing easyocr...
pip install easyocr

echo Installing openpyxl...
pip install openpyxl

echo Installing customtkinter...
pip install customtkinter

echo.
echo ========================================
echo All dependencies installed successfully!
echo ========================================
echo.
pause
