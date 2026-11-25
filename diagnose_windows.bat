@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Start run_windows.bat first to install Python packages.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" diagnose.py
echo.
pause
