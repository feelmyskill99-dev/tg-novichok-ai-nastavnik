param(
    [string]$TaskName = "DepositAiDiary"
)

# Registers Windows Task Scheduler entry "DepositAiDiary":
#   - runs pythonw.exe (no console window) + bot.py
#   - trigger: at user logon
#   - working dir: project root
#   - restart on failure: 3 times, 1 minute interval
#
# Run as the user (not admin) in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install_scheduler_task.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$BotPy = Join-Path $ProjectRoot "bot.py"

if (-not (Test-Path $BotPy)) {
    Write-Error "bot.py not found: $BotPy"
    exit 1
}

$PythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $PythonW) {
    $Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($Python) {
        $PythonW = Join-Path (Split-Path $Python -Parent) "pythonw.exe"
    }
}
if (-not (Test-Path $PythonW)) {
    Write-Error "pythonw.exe not found. Install Python in PATH or set the path manually."
    exit 1
}

Write-Host "Project root: $ProjectRoot"
Write-Host "pythonw.exe:  $PythonW"
Write-Host "Task name:    $TaskName"

$action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument ('"' + $BotPy + '"') `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task $TaskName already exists, re-registering."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Deposit AI Diary - long-running scheduler (10:00/19:00 MSK posts + news + confirm callbacks)"

Write-Host ""
Write-Host "DONE. Task registered."
Write-Host ""
Write-Host "Run now:    Start-ScheduledTask -TaskName $TaskName"
Write-Host "Status:     Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
$rmCmd = "Unregister-ScheduledTask -TaskName " + $TaskName + " -Confirm:" + [char]36 + "false"
Write-Host "Remove:     $rmCmd"
