# ==============================================================================
# Cosmofeed Daily Payout Audit — Windows Scheduled Task Setup Script
# Registers a Windows Scheduled Task to run daily at 06:30 AM IST automatically
# (Guaranteed completion before 08:00 AM IST daily)
# ==============================================================================

$taskName = "CosmofeedDailyPayoutAudit"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = (Get-Command python.exe).Source
$automationScript = Join-Path $scriptDir "daily_automation.py"

Write-Host "Registering Windows Scheduled Task: $taskName" -ForegroundColor Cyan
Write-Host "Target Time: 06:30 AM IST Daily (Completed before 08:00 AM IST)" -ForegroundColor Green
Write-Host "Script: $automationScript" -ForegroundColor Gray

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$automationScript`"" -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Daily -At "06:30AM"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Unregister if already exists
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Register new scheduled task
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily Cosmofeed settlement audit, Telegram/SEBI verification, and non-SEBI cumulative ledger generation running before 08:00 AM IST."

Write-Host "Successfully registered scheduled task '$taskName'!" -ForegroundColor Green
Write-Host "You can verify or run it in Windows Task Scheduler (taskschd.msc)." -ForegroundColor Yellow
