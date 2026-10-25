@echo off
setlocal
cd /d "%~dp0"
title Basecoat Local Test

where py >nul 2>nul
if not errorlevel 1 (
  py -3 --version >nul 2>nul
  if not errorlevel 1 goto use_py
)
where python >nul 2>nul
if not errorlevel 1 (
  python --version >nul 2>nul
  if not errorlevel 1 goto use_python
)

echo Python 3 was not found. Basecoat cannot start until Python 3.11 or newer is installed.
echo Install Python from https://www.python.org/downloads/windows/
echo During setup, select the option to add Python to PATH, then close and reopen this window.
echo After installing, double-click START_BASECOAT.bat again.
pause
exit /b 1

:use_py
echo Checking and installing Basecoat's small Python dependencies...
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto install_failed
echo.
echo Starting Basecoat. Keep this window open while using the app.
echo Open http://127.0.0.1:5000 in your browser (Opera GX works).
echo To stop Basecoat, close this window or press Ctrl+C.
py -3 server.py
goto stopped

:use_python
echo Checking and installing Basecoat's small Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto install_failed
echo.
echo Starting Basecoat. Keep this window open while using the app.
echo Open http://127.0.0.1:5000 in your browser (Opera GX works).
echo To stop Basecoat, close this window or press Ctrl+C.
python server.py
goto stopped

:install_failed
echo.
echo Dependency installation failed. Check your internet connection and try again.
echo If this keeps happening, install Python 3.11+ from python.org and ensure pip is included.
pause
exit /b 1

:stopped
echo.
echo Basecoat has stopped. The browser will not connect until you start it again.
pause
