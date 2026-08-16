@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo Starting Photo Gallery...
echo Browser will open at http://localhost:8000
echo Close this window to stop.
echo.
python app.py
pause
