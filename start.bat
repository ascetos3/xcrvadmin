@echo off
cd /d "%~dp0"
echo.
echo ========================================
echo   Xcrover Admin Web Panel Baslatiliyor
echo ========================================
echo.
"..\..\.venv\Scripts\python.exe" app.py
pause
