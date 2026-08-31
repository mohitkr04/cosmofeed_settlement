@echo off
REM ==============================================================================
REM Cosmofeed Compliance & Payout Audit Dashboard — Offline Localhost Server
REM Runs 100% locally without external dependencies or internet requirements
REM ==============================================================================

cd /d "%~dp0"
echo ==============================================================================
echo  COSMOFEED EXECUTIVE AUDIT DASHBOARD — LOCAL SERVER
echo ==============================================================================
echo.
echo Starting local web server at http://localhost:8000 ...
echo Press Ctrl+C in this window at any time to stop the server.
echo.

start "" "http://localhost:8000/"
python server.py

pause
