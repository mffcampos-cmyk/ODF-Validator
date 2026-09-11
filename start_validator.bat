@echo off
REM ODF Validator Startup Script
cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Dependencies are already installed
REM (Note: pip install -e . skipped due to project structure)

REM Start the validator server
echo.
echo Starting ODF Validator...
echo The web interface will open automatically in your browser.
echo.
uvicorn api.app:app --reload --host 127.0.0.1 --port 8000

pause
