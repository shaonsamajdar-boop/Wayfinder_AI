@echo off
setlocal
cd /d "%~dp0"
title Wayfinder AI - Premium Gemini + Geoapify
set "PYTHON=C:\Users\ayush\miniconda3\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
echo.
echo   WAYFINDER AI  /  Gemini + Geoapify
 echo.
if not exist ".env" (
  if exist ".env.example" copy /y ".env.example" ".env" >nul
  echo A new .env file was created. Enter your Gemini and Geoapify keys.
  start "" notepad.exe ".env"
  echo.
  echo Save the .env file, close this window, then run the launcher again.
  pause
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >nul 2>&1
  if errorlevel 1 (
    echo Repairing old virtual environment...
    rmdir /s /q ".venv"
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating local environment...
  "%PYTHON%" -m venv .venv
  if errorlevel 1 goto fail
)
echo Installing/checking dependencies (first run might take longer)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 goto fail
echo.
echo Website: http://127.0.0.1:8000
echo To check Gemini, run diagnose_windows.bat in this folder.
start "" "http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Launch failed. Review the error above. Close any old app on port 8000.
echo If Gemini fails while website works, run diagnose_windows.bat.
pause
exit /b 1
