@echo off
cd /d "%~dp0"
py rent_app.py --demo --port 8766
echo.
echo If an error appeared, copy it or take a screenshot.
pause
