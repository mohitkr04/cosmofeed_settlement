@echo off
REM ==============================================================================
REM Cosmofeed Daily Payout Audit & Non-SEBI Cumulative Ledger Runner
REM Triggers every morning before 10:00 AM IST (recommended 09:00 AM IST)
REM ==============================================================================

cd /d "%~dp0"
echo Starting Cosmofeed Daily Payout & Compliance Pipeline...
python daily_automation.py
echo.
echo Daily audit execution completed. Log saved in reports/daily_automation.log.
pause
